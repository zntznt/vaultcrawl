"""Is the game won by using what is implemented, and does using it change anything?

Win rate is one number and it answers neither question. A game can hold at 45% while every
run wins the same way through the same three verbs, with twenty-nine systems present and
inert. That is the failure this module is built to see.

The criterion has two halves and each needs its own statistic.

**Winnable by using the systems.** For a mechanic to be part of how the game is won, runs
that use it more must win more (or less, which is also information). That is `lift`: the win
rate in the top third of runs by that signal minus the win rate in the bottom third.

**Its use introduces variance.** A mechanic every run uses identically cannot differentiate
anything, however central it looks. That is `spread`: the standard deviation of the signal
across runs, over its mean. A signal with spread near zero is a constant wearing a system's
name.

Crossed, they give five verdicts, and only one of them is the thing we want:

  unreachable    reach 0, no run ever exercised it. Nothing downstream is measurable.
  inert          reached, spread ~0. Everyone does the same amount, so it separates nothing.
  decorative     spread real, lift ~0. It varies and the outcome does not notice.
  load-bearing   spread real, lift real. Using it is part of how the game is won or lost.
  untestable     too few runs on one side of any split. A verdict about the sample, never
                 about the mechanic, and it must not be quietly read as one of the others.

The signals are read at three depths on purpose, because they disagree and the disagreement
is the diagnosis:

  label      what the brain WANTED (it chose the objective)
  verb       what the game GRANTED (dispatch returned True)
  event      what a system actually FIRED

A label with spread and a verb without it means the agent keeps asking for something it
rarely gets. A verb with spread and no event behind it means the verb succeeds and no system
notices. Both have happened in this codebase.

Lift is tested by permutation rather than asserted, because with 48 runs and 10 wins a
tercile split is noisy enough to manufacture a story. The permutation is seeded from
SHA-256 of the signal name, so the same rows give the same p on any machine.

Usage:

    python3 -m runtime.leverage rows.json [rows_b.json ...] [--min-reach 0.05]

Rows come from `runtime.sandbox_eval --json`. Pass `--max-turns` to hold out runs that never
resolved: in sandbox they are two thirds of the batch and they share a label profile, so
without that every signal correlates with resolved-versus-wandered rather than with winning.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random

# Below this, a signal's variation across runs is not enough to separate anything, whatever
# its mean. Chosen as a coefficient of variation, so it means the same for a share and a count.
SPREAD_FLOOR = 0.15
# Below this the outcome does not notice the signal. One tercile in eight runs is 6.25 points,
# so a lift under 10 is within a single run's worth of noise on a 48-run arm.
LIFT_FLOOR = 0.10
# Permutations per signal. 2000 puts the resolution of p at 0.0005, well under any threshold
# worth reading here.
PERMUTATIONS = 2000


def _rng(key: str) -> random.Random:
    """Deterministic per-signal RNG. No wall clock, no hash(), per the project rule."""
    return random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))


def signals(rows: list) -> dict:
    """Every measurable use signal in the rows, flattened to name -> per-run value.

    Names carry their depth as a prefix so a label and a verb of the same name stay distinct:
    that collision is exactly the comparison this module exists to make.
    """
    out: dict = collections.defaultdict(lambda: [0.0] * len(rows))
    for i, r in enumerate(rows):
        for k, v in (r.get("label_share") or {}).items():
            out[f"label:{k}"][i] = float(v)
        for k, v in (r.get("verb_ok") or {}).items():
            out[f"verb:{k}"][i] = float(v)
        for k, v in (r.get("events") or {}).items():
            out[f"event:{k}"][i] = float(v)
        for k in ("kills", "items", "sigils_forged", "caches", "labels", "coupling"):
            if k in r:
                out[f"count:{k}"][i] = float(r[k] or 0)
        for k, v in (r.get("attractors") or {}).items():
            out[f"attractor:{k}"][i] = float(v)
    return dict(out)


def _stats(xs: list) -> tuple:
    n = len(xs) or 1
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n
    sd = math.sqrt(var)
    reach = sum(1 for x in xs if x > 0) / n
    # Coefficient of variation, so a share and a raw count are comparable. A signal with a
    # zero mean has no spread to speak of rather than an infinite one.
    cv = (sd / mean) if mean > 0 else 0.0
    return mean, sd, cv, reach


MIN_GROUP = 3


def _lift(xs: list, wins: list) -> tuple:
    """Win rate in the high group minus the low group. Returns (lift, hi_wins, lo_wins, split).

    Terciles first. When two thirds of runs share one value the tercile boundary is a tie and
    there is no high group and no low group, only a lump; for a mechanic most runs never touch
    that is the normal case, not a failure. Falling back to used-versus-not is the right test
    for a sparse signal, and calling those `inert` instead (which an earlier draft did) put
    twelve signals in the wrong bucket, several of them with a coefficient of variation above
    3. Which split ran is reported, because a presence lift and a tercile lift do not mean the
    same thing and should not be read off one column without saying so.
    """
    n = len(xs)
    if n < 2 * MIN_GROUP:
        return None, 0, 0, ""
    order = sorted(range(n), key=lambda i: (xs[i], i))
    k = n // 3
    if k >= MIN_GROUP and xs[order[k - 1]] != xs[order[n - k]]:
        lo, hi = order[:k], order[-k:]
        return (sum(wins[i] for i in hi) / k - sum(wins[i] for i in lo) / k,
                sum(wins[i] for i in hi), sum(wins[i] for i in lo), "tercile")
    hi = [i for i in range(n) if xs[i] > 0]
    lo = [i for i in range(n) if xs[i] == 0]
    if len(hi) < MIN_GROUP or len(lo) < MIN_GROUP:
        return None, 0, 0, ""
    return (sum(wins[i] for i in hi) / len(hi) - sum(wins[i] for i in lo) / len(lo),
            sum(wins[i] for i in hi), sum(wins[i] for i in lo), "presence")


def _permuted_p(xs: list, wins: list, observed: float, key: str) -> float:
    """Two-sided p for the observed lift, shuffling outcomes against a fixed signal."""
    rng = _rng(key)
    shuffled = list(wins)
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(shuffled)
        got, _, _, _ = _lift(xs, shuffled)
        if got is not None and abs(got) >= abs(observed):
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


def verdict(reach: float, cv: float, lift, p: float) -> str:
    if reach == 0.0:
        return "unreachable"
    if cv < SPREAD_FLOOR:
        return "inert"
    if lift is None:
        # Too few runs on one side of any split to test. Not a verdict about the mechanic,
        # a verdict about the sample, and it must not be read as either of the other two.
        return "untestable"
    if abs(lift) < LIFT_FLOOR or p > 0.05:
        return "decorative"
    return "load-bearing"


def analyse(rows: list, min_reach: float = 0.0) -> list:
    wins = [1 if r.get("won") else 0 for r in rows]
    out = []
    for name, xs in signals(rows).items():
        mean, sd, cv, reach = _stats(xs)
        if reach < min_reach:
            continue
        lift, hi_w, lo_w, split = _lift(xs, wins)
        p = _permuted_p(xs, wins, lift, name) if lift is not None else 1.0
        out.append(dict(name=name, mean=mean, sd=sd, cv=cv, reach=reach,
                        lift=lift, p=p, hi_wins=hi_w, lo_wins=lo_w, split=split,
                        verdict=verdict(reach, cv, lift, p)))
    out.sort(key=lambda d: (-abs(d["lift"] or 0), -d["cv"]))
    return out


def report(rows: list, label: str = "", min_reach: float = 0.0) -> list:
    res = analyse(rows, min_reach)
    wins = sum(1 for r in rows if r.get("won"))
    print(f"\n=== leverage: {label or 'rows'} ({len(rows)} runs, {wins} wins) ===")
    counts = collections.Counter(d["verdict"] for d in res)
    print("  " + "   ".join(f"{k} {counts[k]}" for k in
                            ("load-bearing", "decorative", "inert", "untestable",
                             "unreachable")
                            if counts[k]))

    load = [d for d in res if d["verdict"] == "load-bearing"]
    print(f"\n  LOAD-BEARING ({len(load)}): use it and the outcome moves")
    print(f"     {'signal':30}{'reach':>7}{'spread':>8}{'lift':>8}{'p':>8}  {'split':9}hi/lo wins")
    for d in load:
        print(f"     {d['name']:30}{d['reach']:7.0%}{d['cv']:8.2f}{d['lift']:+8.1%}"
              f"{d['p']:8.4f}  {d['split']:9}{d['hi_wins']}/{d['lo_wins']}")
    if not load:
        print("     none. Nothing measured here separates a win from a loss.")

    dec = [d for d in res if d["verdict"] == "decorative"]
    print(f"\n  DECORATIVE ({len(dec)}): varies run to run, outcome does not notice")
    for d in sorted(dec, key=lambda d: -d["cv"])[:12]:
        print(f"     {d['name']:30}{d['reach']:7.0%}{d['cv']:8.2f}"
              f"{(d['lift'] or 0):+8.1%}{d['p']:8.4f}")

    inert = [d for d in res if d["verdict"] == "inert"]
    print(f"\n  INERT ({len(inert)}): every run uses it the same, so it separates nothing")
    for d in sorted(inert, key=lambda d: -d["reach"])[:12]:
        print(f"     {d['name']:30}{d['reach']:7.0%}{d['cv']:8.2f}  mean {d['mean']:.3f}")

    unt = [d for d in res if d["verdict"] == "untestable"]
    if unt:
        print(f"\n  UNTESTABLE ({len(unt)}): too few runs on one side to split. About the "
              f"sample, not the mechanic")
        print("     " + ", ".join(f"{d['name']}({d['reach']:.0%})"
                                  for d in sorted(unt, key=lambda d: -d["reach"])[:14]))

    unr = [d for d in res if d["verdict"] == "unreachable"]
    if unr:
        print(f"\n  UNREACHABLE ({len(unr)}): no run ever exercised it")
        print("     " + ", ".join(d["name"] for d in unr))
    return res


def compare(a: list, b: list, name_a: str, name_b: str) -> None:
    """Which signals are load-bearing in one arm and not the other."""
    va = {d["name"]: d for d in a}
    vb = {d["name"]: d for d in b}
    la = {n for n, d in va.items() if d["verdict"] == "load-bearing"}
    lb = {n for n, d in vb.items() if d["verdict"] == "load-bearing"}
    print(f"\n=== {name_a} against {name_b} ===")
    print(f"  load-bearing in both: {sorted(la & lb) or 'none'}")
    print(f"  only in {name_a}: {sorted(la - lb) or 'none'}")
    print(f"  only in {name_b}: {sorted(lb - la) or 'none'}")
    gone = sorted(n for n in vb if va.get(n, {}).get("reach", 0) == 0 and vb[n]["reach"] > 0)
    print(f"  reached in {name_b}, never in {name_a}: {gone or 'none'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rows", nargs="+", help="row dumps from sandbox_eval --json")
    ap.add_argument("--min-reach", type=float, default=0.0,
                    help="skip signals reached by fewer than this fraction of runs")
    ap.add_argument("--max-turns", type=int, default=0,
                    help="drop runs at or above this many turns. In sandbox 33 of 48 runs "
                         "burn the harness budget without resolving, and they share a label "
                         "profile, so every signal correlates with resolved-versus-wandered "
                         "unless they are held out")
    args = ap.parse_args(argv)

    results = []
    for path in args.rows:
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        if args.max_turns:
            keep = [r for r in rows if r.get("turns", 0) < args.max_turns]
            print(f"\n[{path}] dropped {len(rows) - len(keep)} unresolved runs of {len(rows)}")
            rows = keep
        results.append((path, rows, report(rows, path, args.min_reach)))
    if len(results) == 2:
        compare(results[0][2], results[1][2], results[0][0], results[1][0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
