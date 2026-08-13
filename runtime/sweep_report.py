"""Compare arms of a parameter sweep on the terms this project actually accepts.

Win rate is not a target here and never has been, so an arm is judged on structure: how the
game was won, how it was lost, how far runs got and how much they differed, and whether any
run stalled. The aggregate is reported because it is a tripwire, with an interval, and it is
deliberately not the first column.

Everything count-based is normalised per thousand turns. An easier arm survives longer, and raw
counts turn a survival story into an engagement story: measured on 48 classic runs, raw
`event:noise` (footsteps) read +81.2% lift on the outcome and meant nothing at all.

Contrasts are paired on `(agent, seed)` so each arm faces the identical worlds, tested with
exact McNemar, and corrected across the whole family with Benjamini-Hochberg. A three-arm
sweep is two contrasts against the control, not three independent facts.

    python3 -m runtime.sweep_report rows_15.json rows_7.json rows_5.json --control rows_15.json

Rows come from `runtime.sandbox_eval --json`.
"""
from __future__ import annotations

import argparse
import collections
import json
import math

from runtime.ablate import _mcnemar
from runtime.leverage import FDR, _bh

# A run that neither won nor died burned the harness budget. In sandbox that is most runs and
# it is the mode's characteristic outcome; in classic it is a stall worth naming.
STALL_DT = 1.05
STALL_SHARE = 0.60


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """Wilson interval. A normal approximation misreports badly at the tails, and the tails
    are exactly where a broken arm lands."""
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _pct(xs: list, q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def summarise(rows: list) -> dict:
    n = len(rows) or 1
    wins = sum(1 for r in rows if r.get("won"))
    deaths = sum(1 for r in rows if r.get("died"))
    floors = [r.get("floor", 0) for r in rows]
    turns = [r.get("turns", 0) for r in rows]
    mean_f = sum(floors) / n
    sd_f = math.sqrt(sum((f - mean_f) ** 2 for f in floors) / n)
    stalls = [r for r in rows
              if r.get("per_turn", 0) > STALL_DT or r.get("top_share", 0) >= STALL_SHARE]
    # Rows written before the capture was widened carry no `events` key at all. That is not
    # the same as an event never firing, and printing 0.00 for it invites exactly the wrong
    # conclusion, so absence is tracked and rendered as "-".
    has_events = any("events" in r for r in rows)
    ev = collections.Counter()
    for r in rows:
        t = max(1, r.get("turns", 1))
        for k, v in (r.get("events") or {}).items():
            ev[k] += v * 1000.0 / t
    lo, hi = wilson(wins, len(rows))
    return dict(
        n=len(rows), wins=wins, win_lo=lo, win_hi=hi,
        deaths=deaths, stalled=len(rows) - wins - deaths,
        mean_floor=mean_f, med_floor=_pct(floors, 0.5),
        iqr_floor=(_pct(floors, 0.25), _pct(floors, 0.75)), sd_floor=sd_f,
        mean_turns=sum(turns) / n,
        paths=dict(collections.Counter(r.get("win_path", "") for r in rows if r.get("won"))),
        stall_runs=len(stalls),
        max_dt=max((r.get("per_turn", 0) for r in rows), default=0),
        max_share=max((r.get("top_share", 0) for r in rows), default=0),
        labels=sum(r.get("labels", 0) for r in rows) / n,
        coupling=sum(r.get("coupling", 0) for r in rows) / n,
        avg_hp=sum(r.get("avg_hp", 0) for r in rows) / n,
        has_events=has_events,
        events_per_1k={k: round(v / n, 2) for k, v in ev.most_common(14)},
    )


def contrast(control: list, arm: list, name: str) -> dict:
    ck = {(r["agent"], r["seed"]): r for r in control}
    ak = {(r["agent"], r["seed"]): r for r in arm}
    shared = sorted(set(ck) & set(ak))
    lost, gained, p = _mcnemar(ck, ak)
    cp = collections.Counter(ck[k]["win_path"] for k in shared if ck[k]["won"])
    ap = collections.Counter(ak[k]["win_path"] for k in shared if ak[k]["won"])
    return dict(name=name, n=len(shared),
                control_wins=sum(ck[k]["won"] for k in shared),
                arm_wins=sum(ak[k]["won"] for k in shared),
                lost=lost, gained=gained, p=p,
                closed=sorted(set(cp) - set(ap)), opened=sorted(set(ap) - set(cp)),
                control_paths=dict(cp), arm_paths=dict(ap))


def report(arms: dict, control: str) -> None:
    print(f"\n=== sweep: {len(arms)} arms, control = {control} ===\n")
    print(f"{'arm':14} {'wins':>9} {'95% CI':>13} {'died':>5} {'stall':>6} "
          f"{'floor mean':>10} {'med [IQR]':>12} {'sd':>5} {'labels':>7}")
    for name, rows in arms.items():
        s = summarise(rows)
        wins = f"{s['wins']}/{s['n']}"
        ci = f"[{s['win_lo']:.0%},{s['win_hi']:.0%}]"
        med = f"{s['med_floor']:.0f} [{s['iqr_floor'][0]:.0f},{s['iqr_floor'][1]:.0f}]"
        print(f"{name:14} {wins:>9} {ci:>13} {s['deaths']:>5} {s['stalled']:>6} "
              f"{s['mean_floor']:>10.1f} {med:>12} {s['sd_floor']:>5.1f} "
              f"{s['labels']:>7.1f}")

    print("\n  win-path composition (how the game was won, not how often):")
    for name, rows in arms.items():
        s = summarise(rows)
        print(f"     {name:12} {s['paths'] or 'no wins'}")

    print("\n  stall tripwire, both terms:")
    for name, rows in arms.items():
        s = summarise(rows)
        flag = "  LOOK" if s["stall_runs"] else ""
        print(f"     {name:12} runs tripped {s['stall_runs']:3}/{s['n']}   "
              f"max d/t {s['max_dt']:5.2f}   max top-label {s['max_share']:5.1%}{flag}")

    ctrl = arms[control]
    others = [(k, v) for k, v in arms.items() if k != control]
    if others:
        cs = [contrast(ctrl, rows, k) for k, rows in others]
        for d, keep in zip(cs, _bh([c["p"] for c in cs])):
            d["survives_fdr"] = keep
        print(f"\n  paired contrasts against {control}, exact McNemar, "
              f"BH at FDR {FDR:.0%} over {len(cs)}:")
        for d in cs:
            mark = "  MOVED" if d["survives_fdr"] else (
                "  raw p only" if d["p"] <= 0.05 else "")
            print(f"     {d['name']:12} wins {d['control_wins']}->{d['arm_wins']} "
                  f"(n={d['n']}, -{d['lost']}/+{d['gained']})  p={d['p']:.4f}{mark}")
            if d["closed"] or d["opened"]:
                print(f"        routes closed {d['closed'] or '-'}  "
                      f"opened {d['opened'] or '-'}")

    print("\n  events per 1000 turns (rates, so a longer arm is not credited for lasting):")
    keys = sorted({k for rows in arms.values() for k in summarise(rows)["events_per_1k"]})
    print(f"     {'event':22}" + "".join(f"{n:>12}" for n in arms))
    summaries = {n: summarise(r) for n, r in arms.items()}
    for k in keys:
        cells, vals = [], []
        for nm in arms:
            s = summaries[nm]
            if not s["has_events"]:
                cells.append(f"{'-':>12}")
            else:
                v = s["events_per_1k"].get(k, 0.0)
                vals.append(v)
                cells.append(f"{v:>12.2f}")
        if vals and max(vals) < 0.5:
            continue
        print(f"     {k:22}" + "".join(cells))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rows", nargs="+", help="row dumps, one per arm")
    ap.add_argument("--control", default="", help="which arm is the control (default: first)")
    ap.add_argument("--names", default="", help="comma-separated arm names")
    args = ap.parse_args(argv)

    names = args.names.split(",") if args.names else [p.split("/")[-1] for p in args.rows]
    arms = {}
    for name, path in zip(names, args.rows):
        with open(path, encoding="utf-8") as fh:
            arms[name] = json.load(fh)
    control = args.control or names[0]
    if control not in arms:
        control = names[0]
    report(arms, control)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
