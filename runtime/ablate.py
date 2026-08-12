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

# Shared with `leverage.py` so a sweep and a signal table answer to the same threshold.
from runtime.leverage import FDR, _bh

# Dropping these does not test a mechanic, it breaks the agent's senses, so a dead arm would
# read as "this system matters enormously" when it only means the run could not start.
UNDROPPABLE = {"senses", "memory"}

# `run_agent` budgets a run at max_floor times max_turns_per_floor decisions, and in sandbox
# `descend` never moves `floor`, so all 99 of the default floors are phantom and an unresolved
# run costs 49,599 decisions. Two thirds of sandbox runs are exactly that, which puts a 28-arm
# sweep out of reach.
#
# 16 floors is 8,016 decisions, and the cut is outcome-neutral on everything measured so far:
# over 48 sandbox runs the longest WIN took 1,149 turns and not one exceeded 8,000, while every
# run past that budget had already lost. It converts 34 wanderers into fast losses and
# truncates no victory. If a sandbox win ever lands past 8,000 turns this constant is wrong and
# every number taken under it needs re-reading.
SANDBOX_MAX_FLOOR = 16


def _run_slice(args):
    idx, pairs, world, home, drop, sandbox, max_floor = args
    mode = "sbx" if sandbox else "cls"
    state_dir = os.path.join(home, f"abl_{mode}_{drop or 'base'}_w{idx}")
    os.makedirs(state_dir, exist_ok=True)
    os.environ["HOME"] = state_dir

    import runtime.agent_eval as ev
    from runtime.game import Game as RealGame
    from runtime.stack import build_systems

    if sandbox:
        def SandboxGame(manifest, *a, **kw):
            kw["sandbox"] = True
            return RealGame(manifest, *a, **kw)
        ev.Game = SandboxGame

    if drop:
        def _dropped():
            return [s for s in build_systems() if getattr(s, "name", "") != drop]
        ev._build_systems = _dropped

    rows = []
    for seed, agent in pairs:
        r = ev.run_agent(world, agent, run_seed=f"sbx-{seed}", max_floor=max_floor)
        rows.append(dict(agent=agent, seed=seed, drop=drop or "", won=bool(r.won),
                         floor=r.floor_reached, turns=r.turns_survived,
                         kills=r.kills, win_path=r.win_path,
                         died=bool(r.cause_of_death),
                         # In sandbox most runs neither win nor die, they wander until the
                         # harness budget ends them. That is the mode's characteristic
                         # outcome and neither the win column nor the death column records
                         # it, so a system that makes runs RESOLVE would be invisible.
                         resolved=bool(r.won or r.cause_of_death)))
    return rows


def _checkpoint_path(home: str, drop: str, sandbox: bool) -> str:
    mode = "sbx" if sandbox else "cls"
    return os.path.join(home, f"arm_{mode}_{drop or 'baseline'}.json")


def _arm(world: str, runs: int, home: str, drop: str = "", sandbox: bool = False,
         max_floor: int = 99, workers: int = 0, resume: bool = True) -> list:
    """One ablation arm, checkpointed to disk the moment it finishes.

    A 28-arm sweep runs for hours and this container has now restarted under two of them,
    each time discarding everything: the first lost a 96-run classic confirmation partway
    through its second arm, the second lost a sandbox sweep after 2 arms of 27. An arm is a
    natural unit of work and costs nothing to persist, so losing more than the arm in flight
    was never necessary.
    """
    import multiprocessing as mp

    from runtime.agent_eval import AGENT_NAMES

    ckpt = _checkpoint_path(home, drop, sandbox)
    if resume and os.path.exists(ckpt):
        try:
            with open(ckpt, encoding="utf-8") as fh:
                rows = json.load(fh)
            if len(rows) == runs * len(AGENT_NAMES):
                print(f"  reusing arm {drop or 'baseline':18} ({len(rows)} runs, cached)",
                      flush=True)
                return rows
            # A short file is a half-written arm from a run that died mid-flight. Rerun it
            # rather than quietly comparing against a partial arm.
            print(f"  arm {drop or 'baseline'} checkpoint has {len(rows)} of "
                  f"{runs * len(AGENT_NAMES)} runs, rerunning", flush=True)
        except Exception:
            pass
    pairs = [(s, a) for s in range(runs) for a in AGENT_NAMES]
    workers = max(1, min(len(pairs), workers or os.cpu_count() or 2))
    chunks = [(i, pairs[i::workers], world, home, drop, sandbox, max_floor)
              for i in range(workers)]
    chunks = [c for c in chunks if c[1]]
    print(f"  running arm {drop or 'baseline':18} ({len(pairs)} runs)", flush=True)
    with mp.get_context("fork").Pool(len(chunks)) as pool:
        rows = [r for part in pool.map(_run_slice, chunks) for r in part]
    tmp = ckpt + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    os.replace(tmp, ckpt)   # atomic, so a restart never leaves a torn checkpoint
    return rows


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
    br = sum(bk[k].get("resolved", True) for k in shared)
    ar = sum(ak[k].get("resolved", True) for k in shared)
    bf = [bk[k]["floor"] for k in shared]
    af = [ak[k]["floor"] for k in shared]
    lost, gained, p = _mcnemar(bk, ak)
    # How the game was won, not merely how often. `reactions` is why this column exists: its
    # removal moved the win count 12 to 11 and p to 1.000 while `boss_killed` went 4 to 0 and
    # every remaining win came by standing or commune. A whole route closed and the aggregate
    # could not see it. Floor spread could not either, at 9.2 to 6.5.
    bp = collections.Counter(bk[k]["win_path"] for k in shared if bk[k]["won"])
    apth = collections.Counter(ak[k]["win_path"] for k in shared if ak[k]["won"])
    return dict(system=name, n=len(shared), base_wins=bw, arm_wins=aw,
                base_resolved=br, arm_resolved=ar,
                base_floor=sum(bf) / max(1, len(bf)), arm_floor=sum(af) / max(1, len(af)),
                base_floor_sd=_sd(bf), arm_floor_sd=_sd(af),
                base_paths=dict(bp), arm_paths=dict(apth),
                closed=sorted(set(bp) - set(apth)), opened=sorted(set(apth) - set(bp)),
                lost=lost, gained=gained, p=p)


def report(results: list) -> None:
    # One arm per system means one hypothesis per system, so the same false-discovery
    # arithmetic applies here as in `leverage.py`. A sweep of 27 arms at a raw 0.05 hands out
    # about one and a half significant systems for free, and the top of this table is exactly
    # where that error would be invisible.
    for d, keep in zip(results, _bh([d["p"] for d in results])):
        d["survives_fdr"] = keep
    # The resolved column only appears when some run failed to resolve, which in practice
    # means sandbox. In classic every run wins or dies and the column would be noise.
    show_res = any(d["base_resolved"] < d["n"] or d["arm_resolved"] < d["n"]
                   for d in results)
    head = f"\n{'system':18}{'wins':>12}"
    sub = f"{'':18}{'base->drop':>12}"
    if show_res:
        head += f"{'resolved':>12}"
        sub += f"{'base->drop':>12}"
    print(head + f"{'p':>9}{'floor':>14}{'floor sd':>16}")
    print(sub + f"{'':>9}{'base->drop':>14}{'base->drop':>16}")
    for d in sorted(results, key=lambda d: d["p"]):
        wins = f"{d['base_wins']}->{d['arm_wins']}"
        res = (f"{d['base_resolved']}->{d['arm_resolved']}" if show_res else "")
        floor = f"{d['base_floor']:.1f}->{d['arm_floor']:.1f}"
        sd = f"{d['base_floor_sd']:.1f}->{d['arm_floor_sd']:.1f}"
        mark = ""
        if d["p"] <= 0.05:
            mark = "  MEAN MOVED" + ("" if d.get("survives_fdr") else " (raw p only)")
        elif d.get("closed"):
            mark = f"  route closed: {','.join(d['closed'])}"
        elif d["base_floor_sd"] > 0 and abs(
                d["arm_floor_sd"] / d["base_floor_sd"] - 1) >= 0.25:
            mark = "  spread moved, mean did not"
        line = f"{d['system']:18}{wins:>12}"
        if show_res:
            line += f"{res:>12}"
        print(line + f"{d['p']:9.4f}{floor:>14}{sd:>16}{mark}")
    surv = [d["system"] for d in results if d.get("survives_fdr")]
    raw = [d["system"] for d in results if d["p"] <= 0.05 and not d.get("survives_fdr")]
    print(f"\n  surviving FDR {FDR:.0%} over {len(results)} arms: {surv or 'none'}")
    if raw:
        print(f"  raw p under 0.05 but not surviving: {raw}. About "
              f"{0.05 * len(results):.1f} of these are expected by chance, so they are a "
              f"shortlist to confirm at higher n, not a result.")
    closed = [(d["system"], d["closed"]) for d in results
              if d.get("closed") and d["p"] > 0.05]
    if closed:
        print("\n  ROUTES CLOSED WITHOUT MOVING THE WIN RATE. The second half of the "
              "criterion,\n  and the aggregate is blind to every line here.")
        for sysname, paths in closed:
            d = next(x for x in results if x["system"] == sysname)
            print(f"     {sysname:16} lost {','.join(paths):14} "
                  f"{d['base_paths']} -> {d['arm_paths']}")
    opened = [(d["system"], d["opened"]) for d in results if d.get("opened")]
    if opened:
        print("\n  ROUTES THAT OPENED WHEN THE SYSTEM WAS REMOVED. A system suppressing a "
              "way to win.")
        for sysname, paths in opened:
            d = next(x for x in results if x["system"] == sysname)
            print(f"     {sysname:16} gained {','.join(paths):12} "
                  f"{d['base_paths']} -> {d['arm_paths']}")
    print("\n  A system whose removal moves neither the mean, the spread, nor the route mix "
          "is\n  present and the game does not need it.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("world")
    ap.add_argument("--runs", type=int, default=8, help="seeds per arm (times 6 agents)")
    ap.add_argument("--drop", action="append", default=[],
                    help="system name to ablate; repeatable, or 'all'")
    ap.add_argument("--json", default="")
    ap.add_argument("--sandbox", action="store_true",
                    help="ablate sandbox mode, the default interactive one, instead of "
                         "classic descent")
    ap.add_argument("--max-floor", type=int, default=0,
                    help="harness budget, as floors of 500 decisions. Defaults to 99 for "
                         "classic and 16 for sandbox; see SANDBOX_MAX_FLOOR")
    ap.add_argument("--workers", type=int, default=0,
                    help="processes per arm; defaults to the core count")
    ap.add_argument("--no-resume", action="store_true",
                    help="rerun every arm even if a checkpoint exists")
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

    max_floor = args.max_floor or (SANDBOX_MAX_FLOOR if args.sandbox else 99)
    mode = "sandbox" if args.sandbox else "classic"
    print(f"=== ablation ({mode}, budget {max_floor * 500} decisions): baseline plus "
          f"{len(drops)} arm(s), {args.runs * 6} runs each ===")
    resume = not args.no_resume
    base = _arm(args.world, args.runs, home, "", args.sandbox, max_floor, args.workers,
                resume)
    results, raw = [], {"baseline": base}
    for d in drops:
        arm = _arm(args.world, args.runs, home, d, args.sandbox, max_floor, args.workers,
                   resume)
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
