"""Which profile weights actually decide anything?

`_score` returns `max(profile_weight, state) + turn_bonus`. When the state urgency exceeds
the weight, the profile is not consulted: the candidate scores the same for all six agents.
The weight is still there, still readable, still edited in balance passes, and completely
inert.

This walks every `_score` call site during real runs and tallies which branch of that `max()`
won. A site at 0.0% is one where no profile has ever, on any measured decision, had its
preference make a difference to that candidate's score.

Why it matters: the six profiles are supposed to differentiate through weights, since the
Berlin contract forbids differentiating through locks. A weight that never binds is a
differentiation mechanism that is present in the source and absent from the game. Before
tuning a number, check here that the number is live.

The static version of this question is much weaker. Only one call site passes a constant
large enough to dominate every weight outright; the rest pass a computed urgency, so whether
the weight binds is a fact about play, not about the source.

Usage:

    PYTHONHASHSEED=0 python3 -m runtime.weight_audit examples/world.json --runs 1
"""
from __future__ import annotations

import argparse
import collections
import json
import sys


def audit(world_json: str, runs: int = 1, agents=None) -> dict:
    """Run each profile and tally weight-binds per (line, key) call site.

    Wraps `_score` itself, keyed on the caller's line number via `sys._getframe`, which is
    cheap enough to sit in the hot path where `inspect` would not be.
    """
    import runtime.agent as agent_mod
    from runtime.agent_eval import AGENT_NAMES, run_agent

    agents = list(agents or AGENT_NAMES)
    tally: dict = collections.defaultdict(collections.Counter)
    orig = agent_mod._score

    def scored(profile, key, state_bonus, turn_bonus, reachable=True):
        if reachable:
            t = tally[(sys._getframe(1).f_lineno, key)]
            t["calls"] += 1
            if profile.get(key, 0) > state_bonus:
                t["weight_binds"] += 1
        return orig(profile, key, state_bonus, turn_bonus, reachable)

    agent_mod._score = scored
    try:
        for name in agents:
            for i in range(runs):
                run_agent(world_json, name, run_seed=f"bind-{i}")
    finally:
        agent_mod._score = orig

    return {"world": world_json, "runs": runs,
            "sites": [{"line": line, "key": key, "calls": t["calls"],
                       "weight_binds": t["weight_binds"]}
                      for (line, key), t in tally.items()]}


def report(data: dict) -> None:
    sites = sorted(data["sites"], key=lambda s: -s["calls"])
    hdr = f"  {'LINE':>5}  {'KEY':22} {'CALLS':>9} {'WEIGHT BINDS':>13} {'SHARE':>8}"
    print("Where a profile weight decided the score, per _score call site\n")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    dead = []
    for s in sites:
        calls, binds = s["calls"], s["weight_binds"]
        share = f"{binds / calls:.1%}" if calls else "n/a"
        if calls and binds == 0:
            dead.append(s)
        print(f"  {s['line']:5}  {s['key']:22} {calls:9} {binds:13} {share:>8}")
    print("  " + "-" * (len(hdr) - 2))
    print(f"\n  {len(dead)} of {len(sites)} sites never once had a weight decide the score.")
    if dead:
        keys = sorted({s["key"] for s in dead})
        print(f"  Inert keys at those sites: {', '.join(keys)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("world", help="path to world.json")
    ap.add_argument("--runs", type=int, default=1, help="runs per profile (default 1)")
    ap.add_argument("--agents", default="", help="comma-separated profiles (default all six)")
    ap.add_argument("--json", default="", help="also write the raw tallies here")
    args = ap.parse_args(argv)

    agents = [a.strip() for a in args.agents.split(",") if a.strip()] or None
    data = audit(args.world, runs=args.runs, agents=agents)
    report(data)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        print(f"\nSaved -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
