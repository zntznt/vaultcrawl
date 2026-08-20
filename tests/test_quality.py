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
    pc = sum(v for v in (sig.get("props") or []))
    assert pc >= tier, f"prop sum >= tier: {sig.get('props')}"
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

    # --- the two bases are separate knobs, and the creature side is actually wired ---
    #
    # This exists because a 432-run sweep lives on one keyword argument. `roll()` was a single
    # literal read by monsters, by ground sigils and by the forge; the split gave creatures
    # their own base and set it to 7. Delete `base=CREATURE_QUALITY_BASE` from `_qualify_actor`
    # and nothing raises, no test above fails, and the game silently reverts to the arm the
    # sweep rejected. So the check is behavioural: move the creature constant and the creature
    # distribution must move with it, while the item side must not.
    assert Q.CREATURE_QUALITY_BASE != Q.ITEM_QUALITY_BASE, \
        "the split has collapsed back to one value; the sweep chose 7 against 15"

    g3 = Game(load_manifest("examples/world.json"), systems=[Q.QualitySystem()])
    qs3 = g3.system("quality")

    def graded_share(base):
        """Fraction of 120 distinct spawn positions that come out above Normal."""
        saved, Q.CREATURE_QUALITY_BASE = Q.CREATURE_QUALITY_BASE, base
        try:
            n = 0
            for i in range(120):
                a = make_enemy({"tier": 1, "archetype": "shade", "name": "Shade",
                                "sourceNoteId": "stoicism"}, 3 + i % 30, 3 + i // 30)
                qs3._qualify_actor(g3, a)
                n += a.quality > 0
            return n / 120.0
        finally:
            Q.CREATURE_QUALITY_BASE = saved

    hot, cold = graded_share(90), graded_share(4)
    assert hot > cold + 0.5, (
        f"creature base 90 graded {hot:.0%} and base 4 graded {cold:.0%}, which are too close "
        f"to be two different settings: `_qualify_actor` is ignoring CREATURE_QUALITY_BASE and "
        f"still rolling on the item default")

    # And the item side must not follow it. Same extreme creature base, sigils unmoved.
    def sigil_tiers():
        return [qs3.qualify_sigil(g3, {"note": f"n{i}", "role": "leaf", "ability": "Ward",
                                       "durability": 2})
                for i in range(60)]

    before = sigil_tiers()
    saved, Q.CREATURE_QUALITY_BASE = Q.CREATURE_QUALITY_BASE, 90
    try:
        after = sigil_tiers()
    finally:
        Q.CREATURE_QUALITY_BASE = saved
    assert before == after, \
        "the creature base moved sigil grading, so the two sides are still coupled"

    # `roll()` with no `base=` is the item side. A caller that forgets the kwarg must land on
    # items, never on creatures, or the default silently becomes the creature setting.
    assert Q.roll(random.Random(7)) == Q.roll(random.Random(7), base=Q.ITEM_QUALITY_BASE)

    print("OK")


if __name__ == "__main__":
    main()
