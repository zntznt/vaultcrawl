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

    # --- scale_creature's HP boost must survive the body system ---
    #
    # It did not, for the life of the project. `BodySystem` is stack index 21 and
    # `QualitySystem` is 22, so by the time a creature is graded its body is already built
    # from the UNSCALED hp. `scale_creature` raised `max_hp`, called `init_body`, which
    # returns immediately when `actor.body` exists, and the first `sync_hp` reset `max_hp` to
    # the sum of the unscaled parts. Measured on a tier-2 warden at Rare: 10 -> 20 -> 10.
    #
    # The test above (`quality must raise stats`) passed throughout, because it never built a
    # body first, so it exercised the one arrangement that does not happen in a real game.
    # Every quality sweep this project has run therefore moved attack, defence and
    # special-action count and NOT durability, while being read as difficulty as a whole.
    from runtime.body_parts import init_body as _init, sync_hp as _sync
    for t in (Q.UNCOMMON, Q.RARE, Q.EPIC, Q.LEGENDARY):
        a = make_enemy({"tier": 2, "archetype": "warden", "name": "W",
                        "sourceNoteId": "stoicism"}, 1, 1)
        start = a.max_hp
        _init(a)                 # BodySystem, index 21, from unscaled hp
        Q.scale_creature(a, t)   # QualitySystem, index 22
        _sync(a)                 # any hit or heal
        want = int(start * (1.0 + 0.5 * t))
        assert a.max_hp == want, (
            f"tier {t}: max_hp {start} -> {a.max_hp}, wanted {want}. The body was rebuilt "
            f"from the unscaled hp, so the quality HP boost is being reverted")
        assert sum(p["max"] for p in a.body.values()) == a.max_hp, \
            "parts and max_hp disagree, so the next sync_hp will revert the scaling again"

    print("OK")




# --------------------------------------------------------------------------- #
# The leverage instrument models `roll()` analytically, so it can price a base without
# spending an evaluation on it. A model that drifts from the code it models is worse than
# no model, so pin them together and pin the two facts the item-base sweep turned on.
# --------------------------------------------------------------------------- #

def test_exact_matches_roll_over_the_shapes_the_forge_actually_passes():
    """`quality_leverage.exact` must reproduce `roll` to sampling error at every (floor,
    bias) the forge emits. Empirically the forge passes floor 0..4 and bias 0.15*floor
    upward, so walk that grid rather than only the unbiased case."""
    from runtime.quality_leverage import exact

    for floor in range(0, Q.LEGENDARY + 1):
        for bias in (0.0, 0.15 * floor, 0.15 * floor + 0.1):
            for base in (5, 15, 30):
                predicted = exact(base, floor, bias)
                rng = random.Random(f"{floor}:{bias}:{base}")
                n = 20000
                seen = [0] * (Q.LEGENDARY + 1)
                for _ in range(n):
                    seen[Q.roll(rng, floor=floor, bias=bias, base=base)] += 1
                for tier in range(Q.LEGENDARY + 1):
                    assert abs(seen[tier] / n - predicted.get(tier, 0.0)) < 0.02, (
                        f"exact() disagrees with roll() at floor={floor} bias={bias} "
                        f"base={base} tier={tier}")


def test_the_floor_is_additive_and_clamped_so_a_high_floor_ignores_the_base():
    """`roll` ends `max(0, min(LEGENDARY, floor + successes))`. At floor 4 that pins the
    result to Legendary whatever the base is, which is why 19% of real rolls cannot be moved
    by `ITEM_QUALITY_BASE` at all. If the floor ever stops being additive this fails."""
    for base in (4, 15, 90):
        rng = random.Random(f"clamp:{base}")
        assert {Q.roll(rng, floor=Q.LEGENDARY, base=base) for _ in range(200)} == {Q.LEGENDARY}
    # and one tier down, the base is still only able to push upward from the floor
    rng = random.Random("floor3")
    assert min(Q.roll(rng, floor=Q.EPIC, base=4) for _ in range(200)) == Q.EPIC


def test_banked_grade_is_spent_with_the_matter_it_came_on():
    """The forge floor used to be a high-water mark: one Legendary scrap set that
    material's floor for the rest of the run, even after the scrap was spent and replaced
    with Normal stock. Grades now live on the units, so they deplete."""
    from runtime.components import Inventory

    bag = Inventory()
    bag.add({"scrap": 1}, quality=Q.LEGENDARY)
    assert bag.min_quality({"scrap": 1}) == Q.LEGENDARY
    assert bag.pay({"scrap": 1})
    assert bag.quality_of("scrap") == Q.NORMAL, "spent grade must not linger"
    bag.add({"scrap": 40}, quality=Q.NORMAL)
    assert bag.min_quality({"scrap": 1}) == Q.NORMAL, "forty Normal scrap is Normal scrap"


def test_the_floor_counts_units_not_just_materials():
    """A recipe wanting two units of a material it holds one graded unit of pays for the
    second out of the Normal pile, so the floor is Normal. This is the difference between
    "I own something good" and "this craft is made of something good"."""
    from runtime.components import Inventory

    bag = Inventory()
    bag.add({"scrap": 1}, quality=Q.LEGENDARY)
    bag.add({"scrap": 20}, quality=Q.NORMAL)
    assert bag.min_quality({"scrap": 1}) == Q.LEGENDARY
    assert bag.min_quality({"scrap": 2}) == Q.NORMAL
    # and the floor is the worst material in the recipe, not the worst overall
    bag.add({"ash": 5}, quality=Q.RARE)
    assert bag.min_quality({"ash": 3}) == Q.RARE
    assert bag.min_quality({"ash": 3, "scrap": 2}) == Q.NORMAL


def test_the_quoted_floor_and_the_matter_burned_cannot_disagree():
    """`min_quality` and `pay` both read `spend_plan`, so a craft can never be quoted a
    grade it does not then consume. Spend best-first until the graded stock is gone."""
    from runtime.components import Inventory

    bag = Inventory()
    bag.add({"scrap": 2}, quality=Q.EPIC)
    bag.add({"scrap": 2}, quality=Q.NORMAL)
    quoted = []
    for _ in range(2):
        quoted.append(bag.min_quality({"scrap": 2}))
        assert bag.pay({"scrap": 2})
    assert quoted == [Q.EPIC, Q.NORMAL], quoted
    assert bag.total() == 0 and not bag.tiers


def test_the_graded_ledger_stays_in_step_with_the_count():
    """`tiers` must sum to `comp` for every material after any sequence of adds and pays,
    or the floor and the affordability check are reading different inventories."""
    from runtime.components import Inventory

    bag = Inventory()
    for tier, qty in ((0, 7), (2, 3), (4, 1), (1, 5)):
        bag.add({"scrap": qty, "ash": qty}, quality=tier)
    bag.pay({"scrap": 9, "ash": 2})
    assert not bag.pay({"scrap": 99}), "an unaffordable cost must not disturb the ledger"
    for mat, count in bag.comp.items():
        assert sum(bag.tiers.get(mat, {}).values()) == count, mat
    assert bag.min_quality({"scrap": 99}) == 0, "an unaffordable recipe quotes no grade"


if __name__ == "__main__":
    main()
