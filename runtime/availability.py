"""Sigil supply: what the world offers, what the agent is holding, and where it goes.

`pressure.py` reports how the agent *decides*. This reports what it has to decide *with*,
which turned out to be the thing several rounds of scoring work were quietly bounded by.

The question it exists to answer: `recall` and `sigil_escape` fired on 0.00% of decisions
across 288 runs, and the diagnosis kept landing on the scoring. It was not the scoring. The
agent is empty-handed on about 97% of its decisions, so every sigil verb in the game is
capped near zero by supply before any weight is consulted. A candidate can only be chosen on
turns where it exists.

Three things get measured, because they are three different failures and the fixes do not
overlap:

  supply      the graph roles the world contains at all. A sigil's verb is read off the
              role of the note it was forged from (`ROLE_ABILITY`), so a vault with one hub
              note contains exactly one source of Recall. This is a bake-side property: it
              is a fact about someone's notes, not a number to tune.
  occupancy   the share of decisions on which a sigil is actually in the slots, and the
              share on which the agent could genuinely cast a heal (wounded, heal gate open,
              Recall held). The second is the hard ceiling on the `recall` label share.
  flow        forges against shatters against deploys and recovers. Occupancy is a level,
              and a level only moves if inflow and outflow differ. Sigils enter at base
              durability 2 (1 for Echo) and every use spends one, so two uses is the whole
              life of a sigil unless something extends it.

Read them together. Low occupancy with balanced flow means the cap and the cadence are the
problem. Low occupancy with shatters outrunning forges means attrition is, and raising the
forge rate is treating a symptom.

Usage:

    PYTHONHASHSEED=0 python3 -m runtime.availability examples/world.json --runs 2

Runs are slow, since each one is a full descent. Two per profile is enough for occupancy
and flow, which aggregate over tens of thousands of decisions; it is nowhere near enough
for anything about win rate, and this instrument deliberately does not report one.
"""
from __future__ import annotations

import argparse
import collections
import json

from runtime.sigils import ROLE_ABILITY

DEPLOYABLE = ("Recall", "Phase", "Rally", "Ward", "Echo")


def world_supply(world_json: str) -> collections.Counter:
    """The verb supply a world contains, counted by note role."""
    world = json.load(open(world_json, encoding="utf-8"))
    nodes = world.get("graph", {}).get("nodes", {})
    items = nodes.values() if isinstance(nodes, dict) else nodes
    return collections.Counter(n.get("role", "?") for n in items)


def sample(world_json: str, runs: int = 2, agents=None) -> dict:
    """Run each profile `runs` times, sampling slots once per decision.

    Wraps `UniversalBrain.decide`, `Game.emit` and the two sigil verbs rather than
    threading counters through the game, so nothing in the run path knows it is measured
    and the numbers cannot drift from what the agent actually saw.
    """
    from runtime.agent import UniversalBrain
    from runtime.agent_perception import agent_state
    from runtime.agent_eval import AGENT_NAMES, run_agent
    from runtime.game import Game

    agents = list(agents or AGENT_NAMES)
    tally: dict = collections.defaultdict(collections.Counter)
    current = {"agent": agents[0]}

    orig_decide, orig_emit = UniversalBrain.decide, Game.emit
    orig_deploy, orig_recover = Game.deploy, Game.recover

    def decide(self, game, actor):
        t = tally[current["agent"]]
        t["decisions"] += 1
        try:
            s = agent_state(game, actor)
        except Exception:
            # A perception failure is the run's problem, not the sampler's. Count the
            # decision and stay out of the way.
            t["unsampled"] += 1
            return orig_decide(self, game, actor)
        verbs = {sig.get("verb", "") for sig in (s.get("sigils") or [])}
        if verbs:
            t["holding_any"] += 1
        for v in DEPLOYABLE:
            if v in verbs:
                t["holding_" + v] += 1
        vitals = s["vitals"]
        castable = False
        if vitals["hp_pct"] < 60 and vitals["hp"] < vitals["max_hp"]:
            t["wounded"] += 1
            if s.get("can_heal_meaningfully"):
                t["heal_gate_open"] += 1
                if "Recall" in verbs:
                    t["could_cast"] += 1
                    castable = True
        action = orig_decide(self, game, actor)
        if castable:
            # Uptake, not share. A verb that only applies in an emergency has a near-zero
            # label share by construction, because the denominator is every decision in the
            # run. `recall` sat at 0.02% for the life of this project and was read as broken
            # scoring; the agent is simply below 60% HP on under 1% of its decisions. The
            # number that means something is what it chooses when it genuinely could cast.
            try:
                idx = self._last_choice
                label = self._last_candidates[idx][0] if idx is not None else "<none>"
            except Exception:
                label = "<unreadable>"
            t["castable_chose_" + label] += 1
        return action

    def emit(self, etype, **data):
        t = tally[current["agent"]]
        if etype == "forge_used":
            t["forged"] += 1
        elif etype == "broke" and data.get("kind") == "sigil":
            t["shattered"] += 1
        return orig_emit(self, etype, **data)

    def deploy(self, sigil_index):
        ok = orig_deploy(self, sigil_index)
        tally[current["agent"]]["deployed" if ok else "deploy_failed"] += 1
        return ok

    def recover(self):
        ok = orig_recover(self)
        tally[current["agent"]]["recovered" if ok else "recover_failed"] += 1
        return ok

    UniversalBrain.decide, Game.emit = decide, emit
    Game.deploy, Game.recover = deploy, recover
    try:
        for name in agents:
            for i in range(runs):
                current["agent"] = name
                run_agent(world_json, name, run_seed=f"avail-{i}")
    finally:
        UniversalBrain.decide, Game.emit = orig_decide, orig_emit
        Game.deploy, Game.recover = orig_deploy, orig_recover

    return {"world": world_json, "runs": runs,
            "supply": dict(world_supply(world_json)),
            "per_agent": {a: dict(tally[a]) for a in agents}}


def _pct(num, den):
    return f"{num / den:.1%}" if den else "n/a"


def report(data: dict) -> None:
    supply = collections.Counter(data["supply"])
    total = sum(supply.values()) or 1
    print("SUPPLY: note roles in the world, and the verb each one forges\n")
    print(f"  {'ROLE':10} {'NOTES':>6} {'SHARE':>7}  VERB")
    for role, count in supply.most_common():
        print(f"  {role:10} {count:6} {count / total:7.1%}  {ROLE_ABILITY.get(role, '?')}")

    print("\nOCCUPANCY: share of decisions with a sigil in hand\n")
    hdr = (f"  {'AGENT':14} {'DECISIONS':>10} {'HOLDS ANY':>10} {'HOLDS RECALL':>13} "
           f"{'WOUNDED':>8} {'COULD CAST':>11}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    agg = collections.Counter()
    for name, t in data["per_agent"].items():
        agg.update(t)
        n = t.get("decisions", 0)
        print(f"  {name:14} {n:10} {_pct(t.get('holding_any', 0), n):>10} "
              f"{_pct(t.get('holding_Recall', 0), n):>13} {_pct(t.get('wounded', 0), n):>8} "
              f"{_pct(t.get('could_cast', 0), n):>11}")
    n = agg.get("decisions", 0)
    print("  " + "-" * (len(hdr) - 2))
    print(f"  {'ALL':14} {n:10} {_pct(agg.get('holding_any', 0), n):>10} "
          f"{_pct(agg.get('holding_Recall', 0), n):>13} {_pct(agg.get('wounded', 0), n):>8} "
          f"{_pct(agg.get('could_cast', 0), n):>11}")
    print("\n  `could cast` is the ceiling on the `recall` label share: wounded, heal gate")
    print("  open and a Recall in the slots, all on the same decision.")

    uptake = collections.Counter({k[len("castable_chose_"):]: v for k, v in agg.items()
                                  if k.startswith("castable_chose_")})
    total = sum(uptake.values())
    print("\nUPTAKE: what it chose on the decisions where a Recall was castable\n")
    if not total:
        print("  no castable decisions in this sample")
    else:
        print(f"  {total} such decisions\n")
        for label, count in uptake.most_common(10):
            mark = "   <- the heal" if label == "recall" else ""
            print(f"  {label:22} {count:6} {count / total:7.1%}{mark}")
        print("\n  This is the honest instrument for an emergency verb. A label share puts")
        print("  every decision in the run in the denominator, so a verb that only applies")
        print("  below 60% HP reads as 0.0% no matter how well it is working.")

    print("\nFLOW: where sigils come from and where they go\n")
    hdr2 = (f"  {'AGENT':14} {'FORGED':>7} {'SHATTERED':>10} {'DEPLOYED':>9} "
            f"{'RECOVERED':>10} {'NET':>5}")
    print(hdr2)
    print("  " + "-" * (len(hdr2) - 2))
    for name, t in data["per_agent"].items():
        net = t.get("forged", 0) - t.get("shattered", 0)
        print(f"  {name:14} {t.get('forged', 0):7} {t.get('shattered', 0):10} "
              f"{t.get('deployed', 0):9} {t.get('recovered', 0):10} {net:+5}")
    print("  " + "-" * (len(hdr2) - 2))
    net = agg.get("forged", 0) - agg.get("shattered", 0)
    print(f"  {'ALL':14} {agg.get('forged', 0):7} {agg.get('shattered', 0):10} "
          f"{agg.get('deployed', 0):9} {agg.get('recovered', 0):10} {net:+5}")
    print("\n  A sigil enters at durability 2 (1 for Echo) and every use spends one, so a")
    print("  positive net with low occupancy means sigils are being held briefly, not that")
    print("  supply is fine.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("world", help="path to world.json")
    ap.add_argument("--runs", type=int, default=2, help="runs per profile (default 2)")
    ap.add_argument("--agents", default="", help="comma-separated profiles (default all six)")
    ap.add_argument("--json", default="", help="also write the raw tallies here")
    args = ap.parse_args(argv)

    agents = [a.strip() for a in args.agents.split(",") if a.strip()] or None
    data = sample(args.world, runs=args.runs, agents=agents)
    report(data)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        print(f"\nSaved -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
