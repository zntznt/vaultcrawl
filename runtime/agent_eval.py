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

ALL_SYSTEMS: list = []


def _build_systems():
    global ALL_SYSTEMS
    if ALL_SYSTEMS:
        return ALL_SYSTEMS
    from runtime.senses import SenseField
    from runtime.memory import MemorySystem
    from runtime.sigils import SigilSystem
    from runtime.reactions import ReactionSystem
    from runtime.weather import WeatherSystem
    from runtime.flora import FloraSystem
    from runtime.structures import StructureSystem
    from runtime.decay import DecaySystem
    from runtime.fauna import FaunaSystem
    from runtime.salvage import SalvageSystem
    from runtime.forge import ForgeSystem
    from runtime.scent import ScentSystem
    from runtime.body_parts import BodySystem
    from runtime.terrain_mod import TerrainModSystem
    from runtime.portals import PortalSystem
    from runtime.sacrifice import SacrificeSystem
    from runtime.quests import QuestSystem
    from runtime.dialogue import DialogueSystem
    from runtime.machines import MachineSystem
    from runtime.caches import CacheSystem
    from runtime.factions import FactionSystem
    from runtime.history import HistorySystem
    from runtime.marginalia import MarginaliaSystem
    from runtime.knowledge import KnowledgeSystem
    from runtime.effects import EffectSystem
    from runtime.quality import QualitySystem
    import runtime.abilities  # noqa: F401

    ALL_SYSTEMS = [
        SenseField(), MemorySystem(), SigilSystem(), ReactionSystem(), WeatherSystem(),
        FloraSystem(), StructureSystem(), DecaySystem(), FaunaSystem(),
        SalvageSystem(), ForgeSystem(),
        ScentSystem(),
        QuestSystem(), DialogueSystem(), MachineSystem(),
        CacheSystem(),
        TerrainModSystem(),
        PortalSystem(),
        SacrificeSystem(),
        FactionSystem(), BodySystem(), QualitySystem(),
        HistorySystem(), MarginaliaSystem(), KnowledgeSystem(),
        EffectSystem(),
    ]
    return ALL_SYSTEMS


def _register_brains():
    from runtime import brains, tactics, planner, instincts  # noqa: F401
    from runtime import (  # noqa: F401
        agent_artisan, agent_cartographer, agent_emergent,
        agent_exploiter, agent_seeker, agent_whisper,
    )


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
    cause_of_death: str = ""
    floors_cleared: int = 0
    average_hp: float = 0.0
    attractor_scores: dict = None
    narrative: str = ""


def run_agent(world_json: str, agent_name: str,
              max_floor: int = DEFAULT_MAX_FLOOR,
              max_turns_per_floor: int = 500) -> RunResult:
    """Run a single agent through a world descent and return the run's statistics.

    Args:
        world_json: path to world.json
        agent_name: brain tier to wire (one of the 6 agent names)
        max_floor: descend at most this many floors
        max_turns_per_floor: max decisions per floor (anti-stall)
    """
    from collections import deque
    from runtime.agent_action import AgentAction, dispatch
    from runtime.attractors import AttractorTracker

    _build_systems()
    _register_brains()

    manifest = load_manifest(world_json)
    game = Game(manifest, systems=list(ALL_SYSTEMS), sandbox=False)
    game.player.brain = make_brain(game, game.player, name=agent_name)

    sigils_forged = 0
    caches_opened = 0
    hp_samples: list[float] = []
    floors_cleared = 0
    turns_total = 0
    tracker = AttractorTracker()

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
            if isinstance(result, tuple) and len(result) == 2:
                result = AgentAction("move", dx=result[0], dy=result[1])
            ok = dispatch(game, result)
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
                caches_opened = max(caches_opened,
                                    len(getattr(caches, "opened", []) or []))

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
    tracker.record_matter_forged(sigils_forged * 3)  # rough: each sigil costs ~3 matter
    salvage = game.system("salvage")
    if salvage:
        tracker.record_matter_collected(salvage.inventory(game).total())

    return RunResult(
        agent=agent_name,
        seed=manifest["seed"],
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
    )


class _Sentinel:
    slots = []


def evaluate_agents(world_json: str, n_runs: int = DEFAULT_RUNS,
                    max_floor: int = DEFAULT_MAX_FLOOR) -> dict[str, Any]:
    """Run each agent n_runs times and compute aggregate statistics.

    Returns a dict with per-agent stats and per-floor survival curves,
    also written to ~/.vaultcrawl/eval_stats.json.
    """
    results: dict[str, list[RunResult]] = {name: [] for name in AGENT_NAMES}

    total_runs = len(AGENT_NAMES) * n_runs
    run_idx = 0
    t0 = time.monotonic()

    for agent_name in AGENT_NAMES:
        for _ in range(n_runs):
            result = run_agent(world_json, agent_name, max_floor)
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

        # per-floor survival: count how many runs reached at least floor f
        surv_curve: dict[int, int] = {}
        for f in range(1, max(floors, default=0) + 1):
            surv_curve[f] = sum(1 for r in runs if r.floor_reached >= f)
        survival[name] = surv_curve

    output = {
        "world": world_json,
        "n_runs": n_runs,
        "max_floor": max_floor,
        "agent_stats": stats,
        "per_floor_survival": survival,
    }

    out_path = Path(os.path.expanduser("~/.vaultcrawl/eval_stats.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)

    _print_table(stats)
    print(f"\nSaved → {out_path}")
    return output


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
    evaluate_agents(world_json, args.runs, args.floors)


if __name__ == "__main__":
    main()
