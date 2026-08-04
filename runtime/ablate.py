"""Take a system out and see if the game notices. The causal version of the question.

The criterion is that the game be winnable by *using* the systems that are implemented, and
that using them introduce variance. `runtime/leverage.py` screens for that observationally and
cannot settle it, for a reason worth stating rather than working around: **progress and
mechanic-use are simultaneous.** Using a mechanic gets you further, and getting further gives
you more chances to use the mechanic. Measured on 48 classic runs, banding by duration leaves
band 0 with 1 win of 16 and band 2 with 15 of 16, so all the outcome variance lives in one
band of sixteen and nothing survives false-discovery control. That is not a sample-size
problem that another 300 runs would fix. It is the wrong instrument.

Ablation is the right one, and it is the method this project already applies to its own tests:
revert the fix, and if the test still passes it was never load-bearing. Applied to the game,
drop a system from the stack and re-run the same seeds:

  the mean moves    the system is part of how the game is won or lost
  the spread moves  the system is part of what makes runs differ from each other, which is
                    the second half of the criterion and is NOT the same measurement
  neither moves     the system is present and the game does not need it

Both halves are reported because they come apart. A system can hold the win rate exactly and
halve the variance across runs, and that system is doing something the mean cannot see.

Comparison is paired on the run seed, so McNemar applies to the win column and each arm faces
the identical set of worlds.

    PYTHONHASHSEED=0 python3 -m runtime.ablate examples/world.json --runs 8 \\
        --drop weather --drop factions

`--drop all` sweeps every droppable system one at a time, which is expensive: one arm per
system plus a baseline.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os

# Dropping these does not test a mechanic, it breaks the harness or the agent's senses, so a
# dead arm would be read as "this system matters enormously" when it only means the run could
# not start. Sense and memory feed perception; sigils and salvage feed the agent's own verbs
# through `agent_state`, and their absence is measured better by the verb-level rows.
UNDROPPABLE = {"senses", "memory"}


def _run_slice(args):
    idx, pairs, world, home, drop = args
    state_dir = os.path.join(home, f"abl_{drop or 'base'}_w{idx}")
    os.makedirs(state_dir, exist_ok=True)
    os.environ["HOME"] = state_dir

    import runtime.agent_eval as ev
    from runtime.stack import build_systems

    if drop:
        def _dropped():
            return [s for s in build_systems() if getattr(s, "name", "") != drop]
        ev._build_systems = _dropped

    rows = []
    for seed, agent in pairs:
        r = ev.run_agent(world, agent, run_seed=f"sbx-{seed}")
        rows.append(dict(agent=agent, seed=seed, drop=drop or "", won=bool(r.won),
                         floor=r.floor_reached, turns=r.turns_survived,
                         kills=r.kills, win_path=r.win_path,
                         died=bool(r.cause_of_death)))
    return rows


def _arm(world: str, runs: int, home: str, drop: str = "") -> list:
    import multiprocessing as mp

    from runtime.agent_eval import AGENT_NAMES
    pairs = [(s, a) for s in range(runs) for a in AGENT_NAMES]
    workers = max(1, min(len(pairs), os.cpu_count() or 2))
    chunks = [(i, pairs[i::workers], world, home, drop) for i in range(workers)]
    chunks = [c for c in chunks if c[1]]
    print(f"  running arm {drop or 'baseline':18} ({len(pairs)} runs)", flush=True)
    with mp.get_context("fork").Pool(len(chunks)) as pool:
        return [r for part in pool.map(_run_slice, chunks) for r in part]


def _sd(xs: list) -> float:
    n = len(xs) or 1
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / n)


def _mcnemar(base: dict, arm: dict) -> tuple:
    """Exact two-sided McNemar over the seeds both arms ran."""
    b = c = 0
    for k in set(base) & set(arm):
        if base[k]["won"] and not arm[k]["won"]:
            b += 1
        elif arm[k]["won"] and not base[k]["won"]:
            c += 1
    n = b + c
    if not n:
        return b, c, 1.0
    p = 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return b, c, min(1.0, p)


def compare(base: list, arm: list, name: str) -> dict:
    bk = {(r["agent"], r["seed"]): r for r in base}
    ak = {(r["agent"], r["seed"]): r for r in arm}
    shared = sorted(set(bk) & set(ak))
    bw = sum(bk[k]["won"] for k in shared)
    aw = sum(ak[k]["won"] for k in shared)
    bf = [bk[k]["floor"] for k in shared]
    af = [ak[k]["floor"] for k in shared]
    lost, gained, p = _mcnemar(bk, ak)
    return dict(system=name, n=len(shared), base_wins=bw, arm_wins=aw,
                base_floor=sum(bf) / max(1, len(bf)), arm_floor=sum(af) / max(1, len(af)),
                base_floor_sd=_sd(bf), arm_floor_sd=_sd(af),
                lost=lost, gained=gained, p=p)


def report(results: list) -> None:
    print(f"\n{'system':18}{'wins':>12}{'p':>9}{'floor':>14}{'floor sd':>16}")
    print(f"{'':18}{'base->drop':>12}{'':>9}{'base->drop':>14}{'base->drop':>16}")
    for d in sorted(results, key=lambda d: d["p"]):
        wins = f"{d['base_wins']}->{d['arm_wins']}"
        floor = f"{d['base_floor']:.1f}->{d['arm_floor']:.1f}"
        sd = f"{d['base_floor_sd']:.1f}->{d['arm_floor_sd']:.1f}"
        mark = ""
        if d["p"] <= 0.05:
            mark = "  MEAN MOVED"
        elif d["base_floor_sd"] > 0 and abs(
                d["arm_floor_sd"] / d["base_floor_sd"] - 1) >= 0.25:
            mark = "  spread moved, mean did not"
        print(f"{d['system']:18}{wins:>12}{d['p']:9.4f}{floor:>14}{sd:>16}{mark}")
    print("\n  A system whose removal moves neither the mean nor the spread is present and "
          "unused.\n  One that moves only the spread is doing work no win rate can see.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("world")
    ap.add_argument("--runs", type=int, default=8, help="seeds per arm (times 6 agents)")
    ap.add_argument("--drop", action="append", default=[],
                    help="system name to ablate; repeatable, or 'all'")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    home = os.environ.get("HOME", "")
    try:
        import pwd
        real = pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        real = os.path.expanduser("~")
    if os.path.realpath(home) == os.path.realpath(real):
        raise SystemExit("refusing to run against the real HOME; use a scratch one")

    from runtime.stack import build_systems
    names = [getattr(s, "name", "") for s in build_systems()]
    names = [n for n in names if n and n not in UNDROPPABLE]
    drops = names if "all" in args.drop else args.drop
    unknown = [d for d in drops if d not in names]
    if unknown:
        raise SystemExit(f"unknown or undroppable system(s): {unknown}\navailable: {names}")

    print(f"=== ablation: baseline plus {len(drops)} arm(s), {args.runs * 6} runs each ===")
    base = _arm(args.world, args.runs, home)
    results, raw = [], {"baseline": base}
    for d in drops:
        arm = _arm(args.world, args.runs, home, d)
        raw[d] = arm
        results.append(compare(base, arm, d))
        r = results[-1]
        print(f"    {d:18} wins {r['base_wins']}->{r['arm_wins']}  p={r['p']:.4f}", flush=True)

    report(results)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": results, "rows": raw}, fh, indent=2)
        print(f"\nSaved -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
