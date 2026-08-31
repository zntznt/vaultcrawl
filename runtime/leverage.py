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
  suggestive     raw p under 0.05 but not surviving false-discovery control over the whole
                 batch. A batch tests seventy-odd signals, so a handful land here for free.
  load-bearing   spread real, lift real, survives FDR. Part of how the game is won or lost.
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


RATE_SCALE = 1000.0   # events per thousand turns, so the numbers stay readable


def signals(rows: list) -> dict:
    """Every measurable use signal in the rows, flattened to name -> per-run value.

    Names carry their depth as a prefix so a label and a verb of the same name stay distinct:
    that collision is exactly the comparison this module exists to make.

    **Counts are rates, and this is not a detail.** A classic run that wins reaches floor 26
    over thousands of turns; one that loses dies early. Raw counts therefore measure how long
    a run lasted, and the first pass over 48 classic runs duly reported `event:noise` at +81.2%
    lift and `verb:move` at +75.0%. Noise is footsteps and move is walking. Neither is a
    mechanic anyone could use on purpose; both are duration wearing a system's name, and 30
    signals came back load-bearing on that basis. Dividing by turns asks the question that was
    meant: did this run use the mechanic at a higher *rate*, not did it live longer.

    `label:*` shares and `attractor:*` scores arrive normalised already and are left alone.

    Two signals are deliberately left raw and named `breadth:`, because they saturate rather
    than accumulate and dividing them by turns would invert their meaning: distinct labels
    used, and coupling pairs seen. They stay duration-confounded and must be read against
    `control:turns` below rather than on their own.

    `control:turns` and `control:decisions` are included as signals on purpose. They are pure
    duration, so their lift is the score a mechanic has to beat to have said anything. A signal
    that matches the control is not evidence about that mechanic.
    """
    out: dict = collections.defaultdict(lambda: [0.0] * len(rows))
    for i, r in enumerate(rows):
        turns = max(1.0, float(r.get("turns") or 1))
        rate = RATE_SCALE / turns
        for k, v in (r.get("label_share") or {}).items():
            out[f"label:{k}"][i] = float(v)
        for k, v in (r.get("verb_ok") or {}).items():
            out[f"verb:{k}"][i] = float(v) * rate
        for k, v in (r.get("events") or {}).items():
            out[f"event:{k}"][i] = float(v) * rate
        for k in ("kills", "items", "sigils_forged", "caches"):
            if k in r:
                out[f"count:{k}"][i] = float(r[k] or 0) * rate
        for k in ("labels", "coupling"):
            if k in r:
                out[f"breadth:{k}"][i] = float(r[k] or 0)
        for k, v in (r.get("attractors") or {}).items():
            out[f"attractor:{k}"][i] = float(v)
        out["control:turns"][i] = turns
        out["control:decisions"][i] = float(r.get("decisions") or 0)
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
STRATA = 3        # duration bands. 48 runs give 16 per band, splitting 8 against 8.


def duration_strata(rows: list, bands: int = STRATA) -> list:
    """Assign each run a duration band, so a signal is only ever compared like against like.

    Duration is not a confound that can be divided out, in either direction, and both attempts
    failed measurably on the same 48 classic runs. Raw counts accumulate with time, so
    `event:noise` (footsteps) read +81.2% and `verb:move` (walking) read +75.0%. Dividing by
    turns inverts the artifact rather than removing it: a run that dies at turn 60 having forged
    once scores 16.7 forges per thousand turns against a winner's 1.0, so `count:sigils_forged`
    then read -68.8% and `event:noise` flipped to -43.8%. Neither number was about forging or
    about noise.

    Comparing runs only against runs of similar length removes it properly. Duration remains a
    mediator (using a mechanic may well help you survive, and that is a real effect, not one to
    subtract) but it stops being a free ride.
    """
    n = len(rows)
    order = sorted(range(n), key=lambda i: (rows[i].get("turns") or 0, i))
    out = [0] * n
    for rank, i in enumerate(order):
        out[i] = min(bands - 1, rank * bands // max(1, n))
    return out


def _split(xs: list, idx: list) -> tuple:
    """High and low groups within one stratum. Median first, presence when the median ties.

    The median is the LOWER one. Taking `vals[len // 2]` picks the upper median on an even
    band, so a signal that splits the band exactly in half puts the boundary at the high
    value and leaves the high group empty. That is the most natural shape a real signal can
    have, and it was reading as `untestable`: the instrument was silently discarding exactly
    the mechanics it was built to find.
    """
    vals = sorted(xs[i] for i in idx)
    mid = vals[(len(vals) - 1) // 2]
    hi = [i for i in idx if xs[i] > mid]
    lo = [i for i in idx if xs[i] <= mid]
    if len(hi) >= MIN_GROUP and len(lo) >= MIN_GROUP:
        return hi, lo, "median"
    hi = [i for i in idx if xs[i] > 0]
    lo = [i for i in idx if xs[i] == 0]
    if len(hi) >= MIN_GROUP and len(lo) >= MIN_GROUP:
        return hi, lo, "presence"
    return [], [], ""


def _lift(xs: list, wins: list, strata=None) -> tuple:
    """Pooled within-stratum win-rate difference. Returns (lift, hi_wins, lo_wins, split).

    Each duration band contributes the difference between its high and low users, weighted by
    how many runs it could actually split. A band too lopsided to split is skipped rather than
    guessed at, and if no band can be split the answer is None, which reports as `untestable`:
    a verdict about the sample, never about the mechanic.
    """
    n = len(xs)
    if strata is None:
        strata = [0] * n
    if n < 2 * MIN_GROUP:
        return None, 0, 0, ""
    total = hi_w = lo_w = 0
    acc = 0.0
    kinds = set()
    for band in sorted(set(strata)):
        idx = [i for i in range(n) if strata[i] == band]
        hi, lo, kind = _split(xs, idx)
        if not kind:
            continue
        kinds.add(kind)
        w = len(idx)
        acc += w * (sum(wins[i] for i in hi) / len(hi) - sum(wins[i] for i in lo) / len(lo))
        total += w
        hi_w += sum(wins[i] for i in hi)
        lo_w += sum(wins[i] for i in lo)
    if not total:
        return None, 0, 0, ""
    return acc / total, hi_w, lo_w, "+".join(sorted(kinds))


def _permuted_p(xs: list, wins: list, observed: float, key: str, strata=None) -> float:
    """Two-sided p for the observed lift, shuffling outcomes against a fixed signal.

    Outcomes are shuffled WITHIN each duration band, never across them. Shuffling across would
    build a null in which duration carries no information, and the observed lift would then be
    tested against a world that does not exist.
    """
    rng = _rng(key)
    n = len(wins)
    strata = [0] * n if strata is None else strata
    groups = {}
    for i, b in enumerate(strata):
        groups.setdefault(b, []).append(i)
    shuffled = list(wins)
    hits = 0
    for _ in range(PERMUTATIONS):
        for idx in groups.values():
            vals = [wins[i] for i in idx]
            rng.shuffle(vals)
            for i, v in zip(idx, vals):
                shuffled[i] = v
        got, _, _, _ = _lift(xs, shuffled, strata)
        if got is not None and abs(got) >= abs(observed):
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


# Benjamini-Hochberg false-discovery rate. A batch tests seventy-odd signals, so at a raw
# threshold of 0.05 roughly four of them read load-bearing by construction, and the first
# stratified pass duly returned thirteen with p between 0.031 and 0.049. Controlling the
# discovery rate rather than each test in isolation is the difference between "these thirteen
# matter" and "one of these matters and twelve are the sound of testing seventy things".
FDR = 0.10


def _bh(pvals: list, q: float = FDR) -> list:
    """Which of these p-values survive at false-discovery rate q. Order-preserving."""
    m = len(pvals)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    keep = [False] * m
    cut = -1
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= q * rank / m:
            cut = rank
    for rank, i in enumerate(order, start=1):
        if rank <= cut:
            keep[i] = True
    return keep


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
    strata = duration_strata(rows)
    out = []
    for name, xs in signals(rows).items():
        mean, sd, cv, reach = _stats(xs)
        if reach < min_reach:
            continue
        lift, hi_w, lo_w, split = _lift(xs, wins, strata)
        p = _permuted_p(xs, wins, lift, name, strata) if lift is not None else 1.0
        out.append(dict(name=name, mean=mean, sd=sd, cv=cv, reach=reach,
                        lift=lift, p=p, hi_wins=hi_w, lo_wins=lo_w, split=split,
                        verdict=verdict(reach, cv, lift, p)))
    # FDR is computed over the tested signals only; untestable ones were never a hypothesis.
    tested = [d for d in out if d["lift"] is not None]
    for d, keep in zip(tested, _bh([d["p"] for d in tested])):
        d["survives_fdr"] = keep
        if d["verdict"] == "load-bearing" and not keep:
            # Real spread, real raw p, and not distinguishable from the batch's own noise.
            d["verdict"] = "suggestive"
    for d in out:
        d.setdefault("survives_fdr", False)
    out.sort(key=lambda d: (-abs(d["lift"] or 0), -d["cv"]))
    return out


def report(rows: list, label: str = "", min_reach: float = 0.0) -> list:
    res = analyse(rows, min_reach)
    wins = sum(1 for r in rows if r.get("won"))
    print(f"\n=== leverage: {label or 'rows'} ({len(rows)} runs, {wins} wins) ===")
    counts = collections.Counter(d["verdict"] for d in res)
    print("  " + "   ".join(f"{k} {counts[k]}" for k in
                            ("load-bearing", "suggestive", "decorative", "inert",
                             "untestable", "unreachable")
                            if counts[k]))

    ctrl = {d["name"]: d for d in res if d["name"].startswith("control:")}
    bar = max((abs(d["lift"] or 0) for d in ctrl.values()), default=0.0)
    if ctrl:
        print(f"\n  CONTROL: duration itself now scores "
              + ", ".join(f"{n.split(':')[1]} {(d['lift'] or 0):+.1%}"
                          for n, d in sorted(ctrl.items())))
        print(f"  Lift is measured within duration bands, so this should sit near zero. If it "
              f"does not,\n  the bands are not holding and nothing below is controlled.")

    load = [d for d in res if d["verdict"] == "load-bearing"
            and not d["name"].startswith("control:")]
    print(f"\n  LOAD-BEARING ({len(load)}): use it and the outcome moves")
    print(f"     {'signal':30}{'reach':>7}{'spread':>8}{'lift':>8}{'p':>8}  {'split':9}hi/lo wins")
    for d in load:
        flag = "  <- no better than duration" if abs(d["lift"]) <= bar else ""
        print(f"     {d['name']:30}{d['reach']:7.0%}{d['cv']:8.2f}{d['lift']:+8.1%}"
              f"{d['p']:8.4f}  {d['split']:9}{d['hi_wins']}/{d['lo_wins']}{flag}")
    if not load:
        print("     none. Nothing measured here separates a win from a loss.")

    sug = [d for d in res if d["verdict"] == "suggestive"]
    if sug:
        n_tested = sum(1 for d in res if d["lift"] is not None)
        print(f"\n  SUGGESTIVE ({len(sug)}): raw p under 0.05, does not survive FDR "
              f"{FDR:.0%} over {n_tested} tested signals")
        print(f"     Expect about {0.05 * n_tested:.0f} of these by chance. Read them as a "
              f"cluster or not at all.")
        for d in sorted(sug, key=lambda d: -abs(d["lift"] or 0))[:14]:
            print(f"     {d['name']:30}{d['reach']:7.0%}{d['cv']:8.2f}{d['lift']:+8.1%}"
                  f"{d['p']:8.4f}  {d['split']}")

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
