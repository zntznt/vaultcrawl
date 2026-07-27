"""Evaluation harness — runs each agent N times over a world and computes
aggregate statistics (win rate, floor depth, kills, sigils, etc.).

    python3 -m runtime.agent_eval world.json [--runs 100] [--floors 99]

Outputs:
    ~/.vaultcrawl/eval_stats.json  — per-agent aggregates + per-floor survival
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime.game import Game, load_manifest
from runtime.sense import make_brain
from runtime.pressure import (
    DecisionLog, EmergenceLog, divergence_matrix, percentiles,
    persistence_fingerprint,
)

def _build_systems():
    """Fresh instances every call. These objects are stateful (sigil slots, faction
    standing, cache counters), and this used to memoise one list into a module global,
    so every run after the first in a batch inherited the previous run's systems."""
    from runtime.stack import build_systems
    return build_systems()


def _register_brains():
    from runtime.stack import register_brains
    register_brains()


AGENT_NAMES = ["artisan", "cartographer", "emergent", "exploiter", "seeker", "whisper"]
DEFAULT_RUNS = 100
DEFAULT_MAX_FLOOR = 99


@dataclass
class RunResult:
    agent: str
    seed: int
    floor_reached: int
    max_floor: int
    won: bool
    kills: int
    items_collected: int
    sigils_forged: int
    caches_opened: int
    turns_survived: int
    hp_ended: int
    # `seed` above is the WORLD seed and is the same for every run of a batch, so it
    # cannot identify a run. This is the per-run varier that `evaluate_agents` passes as
    # `run_seed`, and it is what makes a row in the dump reproducible: re-running
    # `run_agent(world, agent, floors, run_seed=<this>)` replays that exact game.
    run_seed: object = None
    # State of the last stair at the moment the run ended. `egress_why` enumerates all four
    # routes with the counts the player actually had, so a run that reached the bottom and
    # stalled records what it was short of rather than only that it lost.
    egress_open: bool = False
    egress_route: str = ""
    egress_why: str = ""
    cause_of_death: str = ""
    floors_cleared: int = 0
    average_hp: float = 0.0
    attractor_scores: dict = None
    narrative: str = ""
    metrics: dict = None
    win_path: str = ""
    pressure: dict = None
    emergence: dict = None


def run_agent(world_json: str, agent_name: str,
              max_floor: int = DEFAULT_MAX_FLOOR,
              max_turns_per_floor: int = 500, run_seed=None) -> RunResult:
    """Run a single agent through a world descent and return the run's statistics.

    Args:
        world_json: path to world.json
        agent_name: brain tier to wire (one of the 6 agent names)
        max_floor: descend at most this many floors
        max_turns_per_floor: max decisions per floor (anti-stall)
    """
    from collections import deque
    from runtime.agent_action import AgentAction, dispatch
    from runtime.attractors import tracker as attractor_tracker

    from runtime.stack import reset_run_state
    reset_run_state()
    systems = _build_systems()
    _register_brains()

    manifest = load_manifest(world_json)
    game = Game(manifest, systems=systems, sandbox=False, run_seed=run_seed)
    game.player.brain = make_brain(game, game.player, name=agent_name)
    game.player.brain.name = agent_name
    game.starting_kit(agent_name)
    game._seed_attractors()

    sigils_forged = 0
    caches_opened = 0
    hp_samples: list[float] = []
    floors_cleared = 0
    turns_total = 0
    # The shared per-run tracker, not a private one. Four of the recorders fire from
    # deep inside the game (knowledge, sigils, forge, graves); a local instance could
    # never see them. reset_run_state() clears it at the top of every run.
    tracker = attractor_tracker()
    decisions = DecisionLog()
    emergence = EmergenceLog()
    # Watch the bus and the verbs for this run. A 28-system game whose systems never touch
    # is 28 games running in parallel, and a verb that never succeeds is a dead mechanic
    # burning the decision budget.
    _orig_emit = game.emit
    def _watched_emit(etype, **kw):
        emergence.observe_event(etype)
        return _orig_emit(etype, **kw)
    game.emit = _watched_emit

    def bfs_step(level, start, goal, avoid=None):
        avoid = avoid or set()
        if start == goal:
            return (0, 0)
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == goal:
                break
            x, y = cur
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (x + dx, y + dy)
                if nxt not in prev and level.walkable(*nxt) and (nxt not in avoid or nxt == goal):
                    prev[nxt] = cur
                    q.append(nxt)
        if goal not in prev:
            return None
        cur = goal
        while prev[cur] != start:
            cur = prev[cur]
        return (cur[0] - start[0], cur[1] - start[1])

    while game.alive and not game.won and floors_cleared < max_floor:
        floor_turns = 0
        while game.alive and not game.won:
            ppos = (game.player.x, game.player.y)
            adj_threat = any(
                max(abs(a.x - ppos[0]), abs(a.y - ppos[1])) == 1
                and game.hostile(game.player, a) for a in game.actors
            )
            has_poi = bool(game.items) or any(
                s.points_of_interest(game) for s in game.systems
            )
            if game.on_stairs() and not adj_threat and not has_poi:
                break

            result = game.player.brain.decide(game, game.player)
            decisions.observe(game, game.player.brain)
            if isinstance(result, tuple) and len(result) == 2:
                result = AgentAction("move", dx=result[0], dy=result[1])
            ok = dispatch(game, result)
            emergence.observe_verb(getattr(result, "kind", "?"), bool(ok))
            nr = getattr(game.player.brain, 'note_result', None)
            if nr:
                nr(ok)
            if not ok:
                if game.on_stairs():
                    break
                st = getattr(game.level, "stairs", None)
                if st:
                    step = bfs_step(game.level, ppos, st)
                    if step and step != (0, 0):
                        dispatch(game, AgentAction("move", dx=step[0], dy=step[1]))
                    else:
                        break
                else:
                    break

            hp_samples.append(float(max(0, game.player.hp)))

            # track sigils forged
            forge = game.system("forge")
            if forge is not None:
                slots = (game.system("sigils") or _Sentinel()).slots
                sigils_forged = max(sigils_forged, len(slots) if isinstance(slots, list) else 0)

            # track caches opened
            caches = game.system("caches")
            if caches is not None:
                # CacheSystem counts in `searched`; there is no `opened` attribute, so this
                # read was hardcoding 0 into every run the harness has ever recorded.
                caches_opened = max(caches_opened, int(getattr(caches, "searched", 0) or 0))

            floor_turns += 1
            if floor_turns > max_turns_per_floor:
                game.log("(no progress — abandoning floor)")
                break

        if not game.alive or game.won:
            break
        # Record attractor floor stats
        tracker.record_floor(floors_cleared, game.kills - (last_kills if 'last_kills' in dir() else 0))
        last_kills = game.kills
        floors_cleared += 1
        if floors_cleared < max_floor:
            game.descend()

    cause = ""
    if not game.alive:
        recent = [m for m in game.messages[-5:] if "die" in m.lower()
                  or "strike" in m.lower() or "kill" in m.lower()
                  or "slain" in m.lower()]
        cause = recent[-1][:120] if recent else "unknown"

    avg_hp = (sum(hp_samples) / len(hp_samples)) if hp_samples else 0.0

    # Attractor tracking
    tracker.record_run_stats(game.kills, game.turn)
    fcs = game.system("factions")
    if fcs:
        tracker.record_standing(dict(getattr(fcs, "standing", {})))
    # matter collected and forged are now recorded where they actually happen, in
    # Inventory.add and ForgeSystem, so nothing is guessed or re-read here.

    # Why the run did not end in a win. Measured on 288 runs: 55 of 211 losses reached the
    # bottom alive and simply never opened the last stair, and nothing recorded what they
    # were short of. `egress_ready` already computes exactly that and enumerates all four
    # routes with the player's current counts, so a stall can say which gate it failed and
    # by how much instead of being an anonymous tick in a loss column.
    #
    # A run that ended badly enough to leave the game half-built can make this raise, and a
    # batch of 144 must not die for a diagnostic. But swallowing the error would make a
    # broken capture look exactly like a run with nothing to report, so the failure is
    # written into the row instead of dropped.
    egress_open, egress_why, egress_route = False, "", ""
    try:
        egress_open, egress_why, egress_route = game.egress_ready()
    except Exception as exc:
        egress_why = f"egress_ready raised: {type(exc).__name__}: {exc}"

    return RunResult(
        agent=agent_name,
        seed=manifest["seed"],
        run_seed=run_seed,
        floor_reached=game.floor,
        max_floor=max_floor,
        won=game.won,
        kills=game.kills,
        items_collected=game.items_taken,
        sigils_forged=sigils_forged,
        caches_opened=caches_opened,
        turns_survived=game.turn,
        hp_ended=max(0, game.player.hp),
        cause_of_death=cause,
        floors_cleared=floors_cleared,
        average_hp=round(avg_hp, 2),
        attractor_scores=tracker.scores(),
        narrative=tracker.narrative(),
        metrics=_get_metrics(),
        win_path=getattr(game, "win_path", ""),
        egress_open=egress_open,
        egress_route=egress_route,
        egress_why=egress_why,
        pressure=decisions.summary(),
        emergence=emergence.summary(),
    )


def _mean(xs) -> float:
    xs = [x for x in xs]
    return sum(xs) / len(xs) if xs else 0.0


def _tally(xs) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in xs:
        out[x or "unknown"] = out.get(x or "unknown", 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _get_metrics() -> dict | None:
    """Collect metrics snapshot from the MetricsTracker for eval output."""
    try:
        from runtime.metrics import metrics as _m, reset_metrics
        m = _m()
        summary = m.summary()
        reset_metrics()
        return summary
    except Exception:
        return None


def _agg_metrics_field(runs, field: str) -> dict:
    """Aggregate a metrics dict field across runs."""
    totals = {}
    for r in runs:
        if r.metrics:
            for k, v in r.metrics.get(field, {}).items():
                totals[k] = totals.get(k, 0) + v
    return totals


class _Sentinel:
    slots = []


def evaluate_agents(world_json: str, n_runs: int = DEFAULT_RUNS,
                    max_floor: int = DEFAULT_MAX_FLOOR,
                    agents: list[str] | None = None) -> dict[str, Any]:
    """Run each agent n_runs times and compute aggregate statistics.

    Returns a dict with per-agent stats and per-floor survival curves,
    also written to ~/.vaultcrawl/eval_stats.json.
    """
    agent_names = list(agents) if agents else list(AGENT_NAMES)
    results: dict[str, list[RunResult]] = {name: [] for name in agent_names}

    total_runs = len(agent_names) * n_runs
    run_idx = 0
    t0 = time.monotonic()

    for agent_name in agent_names:
        for run_idx_for_agent in range(n_runs):
            # Vary the run, not the world. Without this every run of one agent on one world
            # was byte-identical, so `--runs 100` played the same game a hundred times and
            # the reported win rate could only ever be 0% or 100%. The apparent bimodality
            # across profiles was that artifact, not a property of the game.
            result = run_agent(world_json, agent_name, max_floor,
                               run_seed=run_idx_for_agent)
            results[agent_name].append(result)
            run_idx += 1
            elapsed = time.monotonic() - t0
            rate = run_idx / elapsed if elapsed > 0 else 0
            eta = (total_runs - run_idx) / rate if rate > 0 else 0
            print(f"\r[{run_idx}/{total_runs}] {agent_name} "
                  f"F{result.floor_reached} {'WON' if result.won else 'DIED'} "
                  f"ETA {eta:.0f}s ", end="", file=sys.stderr)
    print(file=sys.stderr)

    stats: dict[str, dict[str, Any]] = {}
    survival: dict[str, dict[int, int]] = {}

    for name, runs in results.items():
        n = len(runs)
        won = sum(1 for r in runs if r.won)
        floors = [r.floor_reached for r in runs]
        kills = [r.kills for r in runs]
        sigils = [r.sigils_forged for r in runs]
        caches = [r.caches_opened for r in runs]
        turns = [r.turns_survived for r in runs]
        hps = [r.hp_ended for r in runs]
        deaths = sum(1 for r in runs if not r.won and not r.hp_ended > 0)

        stats[name] = {
            "runs": n,
            "win_rate": round(won / n, 4) if n else 0,
            "avg_floor": round(sum(floors) / n, 2) if n else 0,
            "deepest_floor": max(floors) if floors else 0,
            "avg_kills": round(sum(kills) / n, 2) if n else 0,
            "avg_sigils_forged": round(sum(sigils) / n, 2) if n else 0,
            "avg_caches_opened": round(sum(caches) / n, 2) if n else 0,
            "avg_turns": round(sum(turns) / n, 2) if n else 0,
            "avg_hp_ended": round(sum(hps) / n, 2) if n else 0,
            "deaths": deaths,
            # Spread, not just the mean. Every aggregate above is an average, which is
            # what let six profiles look distinct while making identical choices.
            "floor_pct": percentiles(floors),
            "turns_pct": percentiles(turns),
            # Which of the four routes ended each win. A unanimous split is the finding.
            "win_paths": _tally(r.win_path for r in runs if r.won),
        }

        # Emergence: how much of the stack participates, and is any verb simply broken.
        emg = [r.emergence for r in runs if r.emergence]
        if emg:
            # Judge on the summed totals, not the union of per-run verdicts. A verb that
            # happens to fail every attempt in one unlucky run is not a broken verb; one
            # that never succeeds across the whole batch is.
            ok_all: dict[str, int] = {}
            fail_all: dict[str, int] = {}
            for e in emg:
                for k, v in (e.get("verb_ok") or {}).items():
                    ok_all[k] = ok_all.get(k, 0) + v
                for k, v in (e.get("verb_fail") or {}).items():
                    fail_all[k] = fail_all.get(k, 0) + v
            from runtime.pressure import MIN_ATTEMPTS_TO_JUDGE
            broken = sorted(k for k, n in fail_all.items()
                            if n >= MIN_ATTEMPTS_TO_JUDGE and not ok_all.get(k))
            kinds: dict[str, int] = {}
            for e in emg:
                for k, c in e.get("event_counts", {}).items():
                    kinds[k] = kinds.get(k, 0) + c
            stats[name]["emergence"] = {
                "event_kinds": round(_mean(e["event_kinds"] for e in emg), 1),
                "event_counts": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
                "broken_verbs": broken,
            }

        # Pressure: how forced were the decisions, and did the agent ever get hurt.
        press = [r.pressure for r in runs if r.pressure]
        if press:
            label_share: dict[str, float] = {}
            for p in press:
                for lbl, share in p.get("label_share", {}).items():
                    label_share[lbl] = label_share.get(lbl, 0.0) + share / len(press)
            # The whole distribution, not the top 8 of about 30. Every survival label sits
            # below that cut for every profile, so the truncation hid `fight`, `flee`,
            # `recall` and `shield` from every report this project has produced, and the
            # divergence matrix below was comparing policies by an arbitrary slice of each.
            stats[name]["pressure"] = {
                "label_share": {k: round(v, 4) for k, v in
                                sorted(label_share.items(), key=lambda kv: -kv[1])},
                "top_label_share": round(max(label_share.values()), 3) if label_share else 0.0,
                "contested_share": round(_mean(p["contested_share"] for p in press), 3),
                "uncontested_share": round(_mean(p["uncontested_share"] for p in press), 3),
                "median_margin": round(_mean(p["median_margin"] for p in press), 2),
                "avg_candidates": round(_mean(p["avg_candidates"] for p in press), 1),
                "min_hp_pct": min(p["min_hp_pct"] for p in press),
                "hurt_share": round(_mean(p["hurt_share"] for p in press), 3),
                "critical_share": round(_mean(p.get("critical_share", 0.0) for p in press), 3),
                "forced_share": round(_mean(p.get("forced_share", 0.0) for p in press), 3),
                "max_drop_pct": max((p.get("max_drop_pct", 0) for p in press), default=0),
                "top3_label_share": round(_mean(p["top3_label_share"] for p in press), 3),
                "labels_used": round(_mean(p["labels_used"] for p in press), 1),
            }

        # Attractor scores aggregation
        attractor_scores = {"industrial": [], "haunted": [], "companion_flux": [],
                             "pacifist": [], "echo_cascade": [], "standing_range": []}
        narratives = []
        for r in runs:
            if r.attractor_scores:
                for k in attractor_scores:
                    attractor_scores[k].append(r.attractor_scores.get(k, 0))
            if r.narrative:
                narratives.append(r.narrative)
        stats[name]["attractor_avg"] = {k: round(sum(v)/len(v), 3) if v else 0 for k, v in attractor_scores.items()}
        stats[name]["narratives"] = narratives[:3]  # sample

        # Metrics aggregation
        verb_totals: dict[str, list] = {}
        for r in runs:
            if r.metrics:
                for verb, count in r.metrics.get("verbs", {}).items():
                    verb_totals.setdefault(verb, []).append(count)
        stats[name]["metrics"] = {
            "avg_verb_diversity": round(sum(r.metrics.get("verb_diversity", 0) for r in runs if r.metrics) / max(1, sum(1 for r in runs if r.metrics)), 3),
            "top_verbs": {v: round(sum(c)/max(1, len(c)), 1) for v, c in sorted(verb_totals.items(), key=lambda x: -sum(x[1]))[:5] if c},
            "locus_types": _agg_metrics_field(runs, "locus_distribution"),
        }

        # per-floor survival: count how many runs reached at least floor f
        surv_curve: dict[int, int] = {}
        for f in range(1, max(floors, default=0) + 1):
            surv_curve[f] = sum(1 for r in runs if r.floor_reached >= f)
        survival[name] = surv_curve

    shares = {name: s.get("pressure", {}).get("label_share", {})
              for name, s in stats.items() if s.get("pressure")}

    # Every field above this line is an average. A mean carries no interval, so every
    # balance claim this project has made from `avg_kills` or `avg_hp_ended` has been a
    # point estimate quoted as though it were a measurement. The rows below are what make
    # a confidence interval, a median, or a two-sample test possible at all.
    #
    # It matters more than it looks. Extending three profiles from 8 seeds to 48 moved
    # artisan 37.5% -> 18.8%, cartographer 50% -> 22.9% and emergent 12.5% -> 29.2%, which
    # is up to three wins' worth against a documented noise budget of one. Without spread
    # there was no way to see that coming.
    #
    # Cost is small and bounded: one flat row per run, so `--runs 48` writes 288 rows.
    per_run = [
        {
            "agent": r.agent, "world_seed": r.seed, "run_seed": r.run_seed,
            "floor_reached": r.floor_reached, "floors_cleared": r.floors_cleared,
            "won": r.won, "win_path": r.win_path,
            "kills": r.kills, "items_collected": r.items_collected,
            "sigils_forged": r.sigils_forged, "caches_opened": r.caches_opened,
            "turns_survived": r.turns_survived,
            "hp_ended": r.hp_ended, "average_hp": round(r.average_hp, 2),
            "cause_of_death": r.cause_of_death,
            "egress_open": r.egress_open, "egress_route": r.egress_route,
            "egress_why": r.egress_why,
            # How the run ended, in HP. A death that fell from full health in one turn and a
            # death that was ground down over thirty are different problems, and the loss
            # column could not tell them apart.
            "hp_tail": (r.pressure or {}).get("hp_tail", []),
            "max_drop_pct": (r.pressure or {}).get("max_drop_pct", 0),
            "critical_share": round((r.pressure or {}).get("critical_share", 0.0), 4),
            "forced_share": round((r.pressure or {}).get("forced_share", 0.0), 4),
            "labels": (r.pressure or {}).get("label_share", {}),
        }
        for name in agent_names for r in results[name]
    ]

    output = {
        "world": world_json,
        "n_runs": n_runs,
        "max_floor": max_floor,
        "agent_stats": stats,
        "per_run": per_run,
        "per_floor_survival": survival,
        # Without this, no win rate here is comparable to any other: a clean state and a
        # warm one are different experiments run by the same command.
        "persistence": persistence_fingerprint(),
        "hash_seed": os.environ.get("PYTHONHASHSEED", "random"),
        "policy_divergence": {k: round(v, 3) for k, v in divergence_matrix(shares).items()},
    }

    out_path = Path(os.path.expanduser("~/.vaultcrawl/eval_stats.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)

    _print_table(stats)
    _print_pressure(stats, output["policy_divergence"])
    print(f"\nSaved → {out_path}")
    return output


def _print_pressure(stats: dict[str, dict[str, Any]], divergences: dict[str, float]):
    """The half of the report that says whether the choices were hard."""
    header = (f"{'AGENT':<16} {'TOP CHOICE':<20} {'TOP3':<6} {'LABELS':<7} "
              f"{'CONTEST':<8} {'MIN HP':<7} {'WIN PATHS'}")
    print()
    print(header)
    print("-" * len(header))
    for name, s in stats.items():
        p = s.get("pressure")
        if not p:
            continue
        top = next(iter(p["label_share"].items()), ("none", 0.0))
        paths = ", ".join(f"{k} {v}" for k, v in s.get("win_paths", {}).items()) or "no wins"
        print(f"{name:<16} {top[0] + ' ' + format(top[1], '.0%'):<20} "
              f"{p.get('top3_label_share', 0):<6.0%} {p.get('labels_used', 0):<7.0f} "
              f"{p['contested_share']:<8.0%} {p['min_hp_pct']:<7} {paths}")

    broken = sorted({v for s in stats.values()
                     for v in s.get("emergence", {}).get("broken_verbs", [])})
    kinds = max((s.get("emergence", {}).get("event_kinds", 0) for s in stats.values()),
                default=0)
    print(f"\nevent kinds per run: {kinds:.0f}")
    if broken:
        print(f"BROKEN VERBS (attempted, never once succeeded): {', '.join(broken)}")

    if divergences:
        vals = sorted(divergences.values())
        print(f"\npolicy divergence across profile pairs: "
              f"min {vals[0]:.2f}  median {vals[len(vals)//2]:.2f}  max {vals[-1]:.2f}")
        closest = min(divergences.items(), key=lambda kv: kv[1])
        print(f"  most alike: {closest[0].replace('|', ' and ')} at {closest[1]:.2f}")


def _print_table(stats: dict[str, dict[str, Any]]):
    header = (f"{'AGENT':<16} {'WIN%':<8} {'AVG FLR':<8} {'DEEPEST':<9} "
              f"{'AVG KILL':<9} {'SIGILS':<7} {'CACHES':<7} {'TURNS':<7} {'HP END':<8}")
    print(header)
    print("-" * len(header))
    for name in AGENT_NAMES:
        s = stats.get(name, {})
        if not s:
            continue
        print(f"{name:<16} {s['win_rate']:<8.2%} {s['avg_floor']:<8} {s['deepest_floor']:<9} "
              f"{s['avg_kills']:<9.1f} {s['avg_sigils_forged']:<7.1f} "
              f"{s['avg_caches_opened']:<7.1f} {s['avg_turns']:<7.0f} "
              f"{s['avg_hp_ended']:<8.1f}")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Evaluate all 6 vaultcrawl agent brains across N runs.")
    ap.add_argument("world", help="path to world.json")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                    help=f"runs per agent (default {DEFAULT_RUNS})")
    ap.add_argument("--floors", type=int, default=DEFAULT_MAX_FLOOR,
                    help=f"max floors per run (default {DEFAULT_MAX_FLOOR})")
    ap.add_argument("--agent", choices=AGENT_NAMES,
                    help="evaluate a single agent only")
    args = ap.parse_args(argv)

    world_json = args.world
    evaluate_agents(world_json, args.runs, args.floors,
                    agents=[args.agent] if args.agent else None)


if __name__ == "__main__":
    main()
