"""Quality core test: tiers, the rare cascading roll, creature scaling, and the
QualitySystem assigning quality (stats + special actions) to spawned foes.

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_quality
"""
import random

from runtime import quality as Q
from runtime import sigils  # noqa: F401  -- import side-effect: registers the perks into Q.PERKS
from runtime.game import Game, load_manifest
from runtime.entities import make_enemy


def main():
    # --- roll: rare, monotonically thinning, deterministic, floor-respecting ---
    rng = random.Random(1)
    dist = [0] * 5
    for _ in range(4000):
        dist[Q.roll(rng)] += 1
    assert dist[Q.NORMAL] > sum(dist[1:]), "Normal must dominate (quality is rare)"
    assert dist[Q.UNCOMMON] >= dist[Q.RARE] >= dist[Q.EPIC], "tiers must thin out"
    assert all(Q.roll(random.Random(i), floor=Q.RARE) >= Q.RARE for i in range(40)), \
        "roll must never fall below its floor"
    assert Q.roll(random.Random(2)) == Q.roll(random.Random(2)), "roll must be deterministic"

    # --- creature scaling: a graded creature is strictly tougher + renamed once ---
    base = make_enemy({"tier": 2, "archetype": "warden", "name": "Warden",
                       "sourceNoteId": "stoicism"}, 1, 1)
    elite = make_enemy({"tier": 2, "archetype": "warden", "name": "Warden",
                        "sourceNoteId": "stoicism"}, 2, 2)
    Q.scale_creature(elite, Q.RARE)
    assert elite.max_hp > base.max_hp and elite.atk > base.atk, "quality must raise stats"
    assert elite.name.startswith("Rare "), "name should carry the tier prefix"
    Q.scale_creature(elite, Q.RARE)   # idempotent-ish: must not double-prefix
    assert not elite.name.startswith("Rare Rare "), "must not double-prefix the name"

    # --- qualify_sigil: one perk per tier, stat perks take effect ---
    g = Game(load_manifest("examples/world.json"), systems=[Q.QualitySystem()])
    qs = g.system("quality")
    sig = {"note": "stoicism", "role": "leaf", "ability": "Ward", "durability": 2}
    tier = qs.qualify_sigil(g, sig, floor=Q.EPIC)
    assert tier >= Q.EPIC, "floor must hold"
    assert len(sig["perks"]) == tier, "one perk per tier"
    assert sig["durability"] >= 2, "stat perks (if any) only ever help"

    # --- QualitySystem qualifies spawned foes (rare, but bias the roll up to force one) ---
    g2 = Game(load_manifest("examples/world.json"), systems=[Q.QualitySystem()])
    g2.actors = []
    mon = make_enemy({"tier": 1, "archetype": "shade", "name": "Shade",
                      "sourceNoteId": "stoicism"}, 6, 6)
    g2.actors = [mon]
    # find a position seed that yields an elite, to exercise the assignment path
    for x in range(3, 40):
        mon.x, mon._qualified, mon.quality = x, False, 0
        mon.name = "Shade"
        qs2 = g2.system("quality")
        qs2._qualify_actor(g2, mon)
        if mon.quality > 0:
            break
    assert mon.quality > 0, "expected at least one seed to produce an elite"
    assert len(mon._special_actions) == mon.quality, "one special action per tier"
    assert all(a in Q.SPECIAL_ACTIONS for a in mon._special_actions), "actions must be registered"

    print("OK")


if __name__ == "__main__":
    main()
