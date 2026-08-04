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


def _run_slice(args):
    """One worker's share, in its own process and its own state directory."""
    idx, pairs, world, home = args
    state_dir = os.path.join(home, f"sbx_w{idx}")
    os.makedirs(state_dir, exist_ok=True)
    os.environ["HOME"] = state_dir

    import runtime.agent as A
    import runtime.agent_eval as ev
    from runtime.game import Game as RealGame

    def SandboxGame(manifest, *a, **kw):
        kw["sandbox"] = True
        return RealGame(manifest, *a, **kw)

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

    rows = []
    for seed, agent in pairs:
        calls["n"] = 0
        picked.clear()
        r = ev.run_agent(world, agent, run_seed=f"sbx-{seed}")
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
        ))
        print(f"  [sandbox] {agent:13} seed {seed} F{r.floor_reached:2} "
              f"won={str(r.won):5} t{turns:6} d/t={calls['n']/turns:.2f}", flush=True)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("world")
    ap.add_argument("--runs", type=int, default=4, help="runs per agent")
    ap.add_argument("--json", default="", help="write raw rows here")
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
    pairs = [(s, a) for s in range(args.runs) for a in AGENT_NAMES]
    workers = max(1, min(len(pairs), os.cpu_count() or 2))

    import multiprocessing as mp
    chunks = [(i, pairs[i::workers], args.world, home) for i in range(workers)]
    chunks = [c for c in chunks if c[1]]
    print(f"=== sandbox: {len(pairs)} runs across {len(chunks)} workers ===", flush=True)
    with mp.get_context("fork").Pool(len(chunks)) as pool:
        rows = [r for part in pool.map(_run_slice, chunks) for r in part]

    report(rows)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)
        print(f"\nSaved -> {args.json}")
    return 0


def report(rows: list) -> None:
    n = len(rows) or 1
    wins = sum(r["won"] for r in rows)
    print(f"\nSANDBOX: {wins}/{len(rows)} wins ({wins/n:.1%})")
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

    print("\n  mean label share, sandbox:")
    agg = collections.Counter()
    for r in rows:
        agg.update(r["label_share"])
    for k, v in agg.most_common(10):
        print(f"     {k:22} {v/n:6.1%}")


if __name__ == "__main__":
    raise SystemExit(main())
