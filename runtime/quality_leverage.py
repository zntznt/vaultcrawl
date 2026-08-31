"""What the item quality base actually controls, measured over the calls the game makes.

`quality.roll()` is usually reasoned about in the abstract: four binomial trials at
`ITEM_QUALITY_BASE`, decaying on success. That reasoning describes a call with `floor=0` and
`bias=0.0`, and the game almost never makes one. `forge.py` passes a floor pinned to the
lowest-quality ingredient and a bias of `0.15 * floor + 0.05 * len(additives)`, and `roll`
ends with `max(0, min(LEGENDARY, floor + successes))`, so the floor is additive and clamped.
Over the real call mix the floor supplies most of the delivered tier and the base moves what
is left.

Two passes:

    python3 -m runtime.quality_leverage capture examples/world.json --seeds 0,1,2 -o calls.json
    python3 -m runtime.quality_leverage report calls.json --bases 5,15,30

`capture` runs agents with `qualify_sigil` wrapped and records `(floor, bias, tier)` for every
roll the game made. `report` prints the observed distribution next to the exact distribution
`roll` would produce over those same calls at each candidate base, so a base can be priced
without spending an evaluation on it. The exact column is a check on the instrument as much as
on the base: it is computed from the same recurrence as `roll`, and `tests/test_quality.py`
pins the two together.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

from runtime.quality import ITEM_QUALITY_BASE, LEGENDARY, NAMES

PROFILES = ["artisan", "cartographer", "emergent", "exploiter", "seeker", "whisper"]


def exact(base: int, floor: int, bias: float) -> dict:
    """Exact P(tier) for one `roll(rng, floor, bias, base)`, by enumerating the four trials.

    The per-trial probability decays only on a success, so the chain is path dependent and
    this is not a binomial: it has to be walked, not counted.
    """
    p0 = min(90, max(4, base + int(bias * 20)))
    out: dict = collections.defaultdict(float)

    def walk(trial: int, prob: int, succ: int, w: float):
        if trial == LEGENDARY:
            out[max(0, min(LEGENDARY, floor + succ))] += w
            return
        p = prob / 100.0
        walk(trial + 1, prob * 3 // 4, succ + 1, w * p)
        walk(trial + 1, prob, succ, w * (1 - p))

    walk(0, p0, 0, 1.0)
    return dict(out)


def capture(world: str, seeds: list, out_path: str) -> list:
    """Run agents with `qualify_sigil` wrapped, recording every roll the game made."""
    import runtime.quality as Q

    calls: list = []
    original = Q.QualitySystem.qualify_sigil

    def wrapped(self, game, sigil, floor=0, bias=0.0, additives=None):
        tier = original(self, game, sigil, floor, bias, additives)
        # the same key the roll is seeded from, so the report can separate a distribution
        # over rolls from a distribution over distinct rolls
        key = f"{game.seed}:{game.floor}:{sigil.get('note', '')}:{sigil.get('ability', '')}"
        calls.append((int(floor), float(bias), int(sigil.get("quality", 0)), key))
        return tier

    Q.QualitySystem.qualify_sigil = wrapped
    try:
        from runtime.agent_eval import run_agent
        for seed in seeds:
            for profile in PROFILES:
                try:
                    run_agent(world, profile, run_seed=seed)
                except Exception as exc:                      # a crashed run still taught us
                    print(f"  run failed {profile}/{seed}: {type(exc).__name__}: {exc}",
                          file=sys.stderr)
    finally:
        Q.QualitySystem.qualify_sigil = original
    if out_path:
        json.dump(calls, open(out_path, "w"))
    return calls


def _row(label, dist, n) -> str:
    body = "".join(f"{100 * dist.get(t, 0) / n:8.1f}%" for t in range(LEGENDARY + 1))
    mean = sum(t * dist.get(t, 0) for t in range(LEGENDARY + 1)) / n
    return f"{label:>9}  {body}   {mean:9.2f}"


def report(calls: list, bases: list):
    calls = [tuple(c) for c in calls]
    n = len(calls)
    if not n:
        print("no calls captured")
        return
    keyed = len(calls[0]) > 3
    mean_floor = sum(c[0] for c in calls) / n
    mean_tier = sum(c[2] for c in calls) / n
    pinned = sum(1 for c in calls if c[0] >= c[2])
    clamped = sum(1 for c in calls if c[0] >= LEGENDARY)

    print(f"{n} rolls captured")
    print(f"  floor histogram        {dict(sorted(collections.Counter(c[0] for c in calls).items()))}")
    print(f"  mean floor {mean_floor:.2f} of mean delivered tier {mean_tier:.2f} "
          f"({100 * mean_floor / mean_tier:.0f}% of the grade is the floor)")
    print(f"  rolls the floor already guaranteed: {pinned} ({100 * pinned / n:.0f}%)")
    print(f"  rolls clamped Legendary at any base: {clamped} ({100 * clamped / n:.0f}%)")

    # `qualify_sigil` seeds a fresh Random per (seed, floor, note, ability), so two rolls
    # sharing a key return the identical tier. A distribution over rolls therefore weights
    # each distinct roll by how often the agent repeated it, and the analytic column, which
    # assumes independent draws, is only comparable to the deduplicated row.
    distinct = calls
    if keyed:
        first: dict = {}
        for c in calls:
            first.setdefault(c[3], c)
        distinct = list(first.values())
        print(f"  distinct rolls: {len(distinct)} of {n} "
              f"({n / len(distinct):.1f} rolls per distinct key)")

    header = "".join(f"{name:>9}" for name in NAMES)
    print(f"\n{'base':>9}  {header}   mean tier")
    print(_row("observed", collections.Counter(c[2] for c in calls), n))
    if keyed and len(distinct) != n:
        print(_row("distinct", collections.Counter(c[2] for c in distinct), len(distinct)))
    for base in bases:
        agg: dict = collections.defaultdict(float)
        for c in distinct:
            for tier, weight in exact(base, c[0], c[1]).items():
                agg[tier] += weight
        label = f"{base}*" if base == ITEM_QUALITY_BASE else str(base)
        print(_row(label, agg, len(distinct)))
    print("\n  * = the shipped ITEM_QUALITY_BASE. Compare it to `distinct`, not to"
          " `observed`: the model draws independently and the game does not.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="run agents and record every quality roll")
    cap.add_argument("world")
    cap.add_argument("--seeds", default="0,1,2")
    cap.add_argument("-o", "--out", default="quality_calls.json")
    cap.add_argument("--bases", default="5,11,15,30,60")

    rep = sub.add_parser("report", help="price candidate bases over a captured call list")
    rep.add_argument("calls")
    rep.add_argument("--bases", default="5,11,15,30,60")

    args = ap.parse_args(argv)
    if args.cmd == "capture":
        calls = capture(args.world, [int(s) for s in args.seeds.split(",")], args.out)
        print(f"captured {len(calls)} rolls to {args.out}")
        report(calls, [int(b) for b in args.bases.split(",")])
    else:
        report(json.load(open(args.calls)), [int(b) for b in args.bases.split(",")])


if __name__ == "__main__":
    main()
