"""Measure sandbox mode, which the benchmark has never touched.

`agent_eval` hardcodes `sandbox=False`, so every number this project has ever produced
describes **classic descent** (`--descent`, `--auto`). Sandbox is the Alexander pattern
compiler in `runtime/arch/`, it is LIVE per `CLAUDE.md`, and it is **the default interactive
mode**, the one a human actually gets when they run `python3 -m runtime.play world.json`.

So the mode nobody plays has 288-run baselines and seven health conditions, and the mode
everybody plays has never been run with an agent at all. This closes that.

It deliberately reuses `agent_eval.run_agent` rather than reimplementing the loop, patching
only the Game constructor, so any difference in the numbers is a difference in the mode and
not in the harness.

Usage:

    PYTHONHASHSEED=0 python3 -m runtime.sandbox_eval examples/world.json --runs 4

Runs are slower than classic descent: the agent covers ground rather than diving, so a run
uses more turns before it resolves.
"""
from __future__ import annotations

import argparse
import collections
import json
import os


# Wall-clock ceiling on one run. The decision budget bounds the decision LOOP and cannot
# bound a loop inside one decision, so a run can spin at 100% CPU indefinitely with the
# budget untouched. `ablate.py` gained this after a dropped system sent a worker into a
# CPU-bound spin for 2h12m against an arm that normally finishes in ten minutes; the quality
# sweep hit the same thing, where one chunk of six runs finished in six minutes and its
# neighbour was killed twice without finishing.
RUN_TIMEOUT = 420


class _RunTimeout(BaseException):
    """Inherits BaseException, NOT Exception, and that is the whole point.

    `agent_action.dispatch` wraps its entire body in `except Exception: return False`, and
    `run_agent` has broad catches too. A SIGALRM handler that raised an ordinary Exception
    was therefore swallowed by whatever verb happened to be executing when the alarm fired:
    the run carried on, the alarm was already spent, and no second one was ever scheduled.
    The ceiling silently did nothing, and the tell was an absence, which is why it survived
    two rounds of debugging: one chunk ran 30 minutes and the next ran 50, both against this
    420 second limit, and not one TIMEOUT line was ever printed. A guard that never fires
    looks exactly like a guard that is not needed.
    """


def _run_slice(args):
    """One worker's share, in its own process and its own state directory."""
    idx, pairs, world, home, sandbox = args
    state_dir = os.path.join(home, f"sbx_w{idx}")
    os.makedirs(state_dir, exist_ok=True)
    os.environ["HOME"] = state_dir

    import runtime.agent as A
    import runtime.agent_eval as ev
    from runtime.game import Game as RealGame

    def SandboxGame(manifest, *a, **kw):
        kw["sandbox"] = True
        return RealGame(manifest, *a, **kw)

    # `--classic` leaves the constructor alone, so the classic arm runs through exactly this
    # instrumentation rather than through `agent_eval`'s own reporting. The two arms then
    # differ in the mode and in nothing else, which is the only way the contrast is worth
    # quoting.
    if sandbox:
        ev.Game = SandboxGame

    calls = collections.Counter()
    picked = collections.Counter()
    orig = A.UniversalBrain.decide

    def decide(self, game, actor):
        calls["n"] += 1
        r = orig(self, game, actor)
        try:
            if self._last_choice is not None:
                picked[self._last_candidates[self._last_choice][0]] += 1
        except Exception:
            pass
        return r

    A.UniversalBrain.decide = decide

    import signal

    def _blew_the_clock(signum, frame):
        raise _RunTimeout()

    try:
        signal.signal(signal.SIGALRM, _blew_the_clock)
        can_time_out = True
    except (ValueError, AttributeError):
        can_time_out = False

    rows = []
    for seed, agent in pairs:
        calls["n"] = 0
        picked.clear()
        if can_time_out:
            signal.alarm(RUN_TIMEOUT)
        # The same run seed in both arms, so the comparison is paired.
        try:
            r = ev.run_agent(world, agent, run_seed=f"sbx-{seed}")
        except _RunTimeout:
            print(f"    TIMEOUT {agent} sbx-{seed} after {RUN_TIMEOUT}s", flush=True)
            rows.append(dict(agent=agent, seed=seed, won=False, floor=0, turns=1,
                             win_path="", died=False, decisions=calls["n"],
                             per_turn=0.0, top_label="-", top_share=0.0, labels=0,
                             label_share={}, attractors={}, coupling=0,
                             coupling_density=0.0, broken_verbs=[], verb_ok={},
                             verb_fail={}, events={}, kills=0, items=0,
                             sigils_forged=0, caches=0, floors_cleared=0, avg_hp=0.0,
                             egress_open=False, egress_route="", verb_crashes={},
                             crash_sites={}, shrine={}, timed_out=True))
            continue
        finally:
            if can_time_out:
                signal.alarm(0)
        turns = r.turns_survived or 1
        tot = sum(picked.values()) or 1
        top, cnt = picked.most_common(1)[0] if picked else ("-", 0)
        rows.append(dict(
            agent=agent, seed=seed, won=bool(r.won), floor=r.floor_reached,
            turns=turns, win_path=r.win_path, died=bool(r.cause_of_death),
            decisions=calls["n"], per_turn=round(calls["n"] / turns, 3),
            top_label=top, top_share=round(cnt / tot, 4), labels=len(picked),
            label_share={k: v / tot for k, v in picked.items()},
            attractors=dict(r.attractor_scores or {}),
            coupling=(r.emergence or {}).get("coupling_pairs", 0),
            coupling_density=(r.emergence or {}).get("coupling_density", 0.0),
            broken_verbs=(r.emergence or {}).get("broken_verbs", []),
            # What the run actually exercised, not merely what it chose. A label says the
            # brain wanted something; `verb_ok` says the game granted it and `event_counts`
            # says a system fired. `runtime/leverage.py` needs all three to tell an inert
            # mechanic from a decorative one from a load-bearing one.
            verb_ok=dict((r.emergence or {}).get("verb_ok", {})),
            verb_fail=dict((r.emergence or {}).get("verb_fail", {})),
            events=dict((r.emergence or {}).get("event_counts", {})),
            kills=r.kills, items=r.items_collected,
            sigils_forged=r.sigils_forged, caches=r.caches_opened,
            floors_cleared=r.floors_cleared, avg_hp=r.average_hp,
            egress_open=bool(r.egress_open), egress_route=r.egress_route,
            # Expected empty. Non-empty means `dispatch` swallowed a raise and reported it
            # as a refusal, which `verb_fail` cannot distinguish from the game saying no.
            verb_crashes=dict(r.verb_crashes or {}),
            crash_sites=dict(r.crash_sites or {}),
            # Shrine uptake as a RATE, so a build that refuses every shrine and one that
            # never reaches a shrine are distinguishable. They are opposite problems and a
            # bare take-count reports both as the same low number.
            shrine=dict((r.metrics or {}).get("shrine", {})),
        ))
        print(f"  [{'sandbox' if sandbox else 'classic'}] {agent:13} seed {seed} F{r.floor_reached:2} "
              f"won={str(r.won):5} t{turns:6} d/t={calls['n']/turns:.2f}", flush=True)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("world")
    ap.add_argument("--runs", type=int, default=4, help="runs per agent")
    ap.add_argument("--seed-start", type=int, default=0,
                    help="first seed. Lets one arm be split into chunks that each finish "
                         "inside the container's uptime: a 144-run arm takes longer than "
                         "this box stays up, and rows are only written at the end, so an "
                         "unchunked arm loses every run it completed")
    ap.add_argument("--json", default="", help="write raw rows here")
    ap.add_argument("--classic", action="store_true",
                    help="run classic descent through this same instrumentation, for a "
                         "paired contrast the harness cannot be blamed for")
    args = ap.parse_args(argv)

    home = os.environ.get("HOME", "")
    try:
        import pwd
        real = pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        real = os.path.expanduser("~")
    if os.path.realpath(home) == os.path.realpath(real):
        raise SystemExit(
            "refusing to run against the real HOME: this writes per-worker state\n"
            "directories and would race any other evaluation. Use a scratch HOME.")

    from runtime.agent_eval import AGENT_NAMES
    pairs = [(s, a) for s in range(args.seed_start, args.seed_start + args.runs)
             for a in AGENT_NAMES]
    workers = max(1, min(len(pairs), os.cpu_count() or 2))

    import multiprocessing as mp
    mode = "classic" if args.classic else "sandbox"
    chunks = [(i, pairs[i::workers], args.world, home, not args.classic)
              for i in range(workers)]
    chunks = [c for c in chunks if c[1]]
    print(f"=== {mode}: {len(pairs)} runs across {len(chunks)} workers ===", flush=True)
    with mp.get_context("fork").Pool(len(chunks)) as pool:
        rows = [r for part in pool.map(_run_slice, chunks) for r in part]

    report(rows, mode)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)
        print(f"\nSaved -> {args.json}")
    return 0


def report(rows: list, mode: str = "sandbox") -> None:
    n = len(rows) or 1
    wins = sum(r["won"] for r in rows)
    print(f"\n{mode.upper()}: {wins}/{len(rows)} wins ({wins/n:.1%})")
    print(f"  mean floor {sum(r['floor'] for r in rows)/n:5.1f}   "
          f"mean turns {sum(r['turns'] for r in rows)/n:7.0f}   "
          f"decisions/turn {sum(r['per_turn'] for r in rows)/n:.3f}")
    print(f"  labels used {sum(r['labels'] for r in rows)/n:.1f}   "
          f"max top-label share {max(r['top_share'] for r in rows):.1%}   "
          f"coupling {sum(r['coupling'] for r in rows)/n:.1f}")
    print(f"  win paths: {dict(collections.Counter(r['win_path'] for r in rows if r['won']))}")

    # The health conditions that can be read off a single batch.
    by_agent = collections.defaultdict(list)
    for r in rows:
        by_agent[r["agent"]].append(r)
    winners = [a for a, rs in by_agent.items() if any(x["won"] for x in rs)]
    print(f"\n  profiles that win: {len(winners)}/{len(by_agent)}  {sorted(winners)}")
    broken = collections.Counter()
    for r in rows:
        broken.update(r["broken_verbs"])
    print(f"  broken verbs: {dict(broken) or 'none'}")
    stalls = [r for r in rows if r["per_turn"] > 1.05 or r["top_share"] >= 0.60]
    print(f"  runs worth a look (d/t > 1.05 or one label >= 60%): {len(stalls)}/{len(rows)}")
    for r in sorted(stalls, key=lambda r: -r["per_turn"])[:5]:
        print(f"     {r['agent']:13} seed {r['seed']} {r['top_label']:18} "
              f"{r['top_share']:5.1%} d/t={r['per_turn']:.2f} F{r['floor']} won={r['won']}")

    print(f"\n  mean label share, {mode}:")
    agg = collections.Counter()
    for r in rows:
        agg.update(r["label_share"])
    for k, v in agg.most_common(10):
        print(f"     {k:22} {v/n:6.1%}")


if __name__ == "__main__":
    raise SystemExit(main())
