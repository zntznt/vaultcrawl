"""Drive the real Game through the ForgeSystem and assert the shatter->salvage->forge loop.

Forge is the third beat of the matter cycle: it spends salvaged matter from the player's
Inventory to re-craft a sigil into a free slot. This test uses only SigilSystem + ForgeSystem
(no hard dependency on the parallel salvage system); it seeds the player's Inventory directly
with materials drawn from the world's own vocabulary (`world_materials`).

Run: python3 -m tests.test_forge   (from the vaultcrawl project root)
"""
from runtime.game import Game, load_manifest
from runtime.components import inv, world_materials
from runtime.sigils import MAX_SLOTS, SigilSystem
from runtime.forge import ForgeSystem
from runtime import quality


def _fresh():
    g = Game(load_manifest("examples/world.json"),
             systems=[SigilSystem(), ForgeSystem()])
    sig = g.system("sigils")
    forge = g.system("forge")
    sig.slots = []                       # guarantee free slots, no leftover placement
    return g, sig, forge


def _fresh_quality():
    """A game with the opt-in QualitySystem registered alongside sigils + forge."""
    g = Game(load_manifest("examples/world.json"),
             systems=[SigilSystem(), ForgeSystem(), quality.QualitySystem()])
    sig = g.system("sigils")
    forge = g.system("forge")
    sig.slots = []                       # guarantee free slots, no leftover placement
    return g, sig, forge


def _seed_quality(game, qual=2, qty=12):
    """Seed the player's inventory with high-quality matter (banks a per-material tier)."""
    mats = world_materials(game)
    assert len(mats) >= 2, "world must define >= 2 materials"
    pinv = inv(game.player)
    pinv.comp = {}
    pinv.qual = {}
    pinv.add({mats[0]: qty, mats[1]: qty}, quality=qual)
    return mats


def _seed(game, qty=12):
    """Seed the player's inventory with ample matter from the world's real materials."""
    mats = world_materials(game)
    assert mats, "world must define a material vocabulary"
    inv(game.player).comp = {}           # start from a clean, deterministic pool
    # uneven amounts so 'most-abundant-first' cost selection is exercised
    inv(game.player).add({mats[0]: qty, mats[1 % len(mats)]: max(1, qty // 2)})
    return mats


def test_forge_success():
    g, sig, forge = _fresh()
    mats = _seed(g)

    total_before = inv(g.player).total()
    slots_before = len(sig.slots)

    cost = forge.cost(g)
    assert sum(cost.values()) == forge._COST, ("cost spends exactly _COST matter", cost)
    assert all(m in mats for m in cost), ("cost uses only world materials", cost)
    assert inv(g.player).can_pay(cost), "seeded inventory must cover the cost"

    assert forge.forge(g, "Ward") is True, "forge should succeed with slot + matter"

    # a Ward sigil now occupies a slot, slot count rose by exactly one
    assert len(sig.slots) == slots_before + 1, "slot count rose by 1"
    ward = [s for s in sig.slots if s["ability"] == "Ward"]
    assert ward, "a Ward sigil is now slotted"
    w = ward[0]
    assert w["durability"] == forge._FULL_DURABILITY, "forged at full durability"
    assert w["note"] == "forged" and w["role"] == "leaf", ("sensible role/note", w)

    # matter dropped by exactly the cost total
    assert inv(g.player).total() == total_before - forge._COST, "matter dropped by the cost"
    assert any("forge a Ward sigil" in m for m in g.messages), "forge logged"


def test_forge_slots_full_noop():
    g, sig, forge = _fresh()
    _seed(g)
    # fill every slot
    sig.slots = [{"note": "x", "role": "leaf", "ability": "Ward", "durability": 2}
                 for _ in range(MAX_SLOTS)]
    assert len(sig.slots) == MAX_SLOTS

    slots_snapshot = list(sig.slots)
    matter_before = inv(g.player).total()

    assert forge.forge(g, "Ward") is False, "no free slot -> False"
    assert sig.slots == slots_snapshot, "slots unchanged when full"
    assert inv(g.player).total() == matter_before, "no matter spent when full"


def test_forge_no_matter_noop():
    g, sig, forge = _fresh()
    inv(g.player).comp = {}              # drain all matter
    sig.slots = []                       # free slot available

    assert inv(g.player).total() == 0
    assert forge.forge(g, "Ward") is False, "no matter -> False"
    assert sig.slots == [], "no sigil forged without matter"
    assert inv(g.player).total() == 0, "nothing spent"


def test_forge_no_sigils_system_noop():
    # forge must be a None-guarded no-op when sigils isn't registered
    g = Game(load_manifest("examples/world.json"), systems=[ForgeSystem()])
    forge = g.system("forge")
    inv(g.player).add({world_materials(g)[0]: 20})
    assert forge.forge(g, "Ward") is False, "no sigils system -> False"
    assert forge.status_line(g) is None, "no sigils system -> no status line"


def test_auto_forge_recovers_loop():
    g, sig, forge = _fresh()
    _seed(g)
    sig.slots = []                       # a sigil just shattered: free slot
    assert g.alive

    matter_before = inv(g.player).total()
    slots_before = len(sig.slots)
    assert forge.status_line(g) == "Forge: ready", "affordable craft advertises readiness"

    forge.on_player_act(g)               # auto-forge fires the loop

    assert len(sig.slots) == slots_before + 1, "auto-forge crafted a sigil"
    assert inv(g.player).total() == matter_before - forge._COST, "auto-forge spent the cost"
    # default ability is the first un-slotted one (Recall, deterministically)
    assert sig.slots[-1]["ability"] == "Recall", ("deterministic default ability",
                                                  sig.slots[-1])


def test_deterministic():
    # same seeded state forges the same sigil + same cost, twice
    runs = []
    for _ in range(2):
        g, sig, forge = _fresh()
        _seed(g)
        sig.slots = []
        c = dict(forge.cost(g))
        forge.forge(g)
        runs.append((c, sig.slots[-1]["ability"], inv(g.player).total()))
    assert runs[0] == runs[1], ("forge is deterministic", runs)


def test_forge_quality_floor():
    # with a QualitySystem + high-quality matter, the forged sigil's tier respects the
    # crafting floor (never below the lowest-quality ingredient).
    import runtime.sigils                       # let Agent A's perks register (if present)
    g, sig, forge = _fresh_quality()
    _seed_quality(g, qual=2)                     # all ingredients banked at Rare(2)

    assert forge.forge(g, "Ward") is True, "quality forge should still succeed"
    s = sig.slots[-1]
    assert s["quality"] >= 2, ("forge floor honored: output >= lowest ingredient", s)
    # quality grants one perk per tier, recorded on the sigil
    assert len(s.get("perks", [])) == s["quality"], ("one perk per tier", s)


def test_forge_additive_steers_perk():
    # an additive whose affinity favours perk P makes the forged sigil gain P, vs a control
    # forged without that additive. Uses the two quality.py built-in perks (keen/reinforced)
    # so the assertion holds regardless of whether Agent A's pool is loaded.
    import runtime.sigils                       # register Agent A's perks too (harmless)

    probe = _fresh_quality()[0]
    mats = world_materials(probe)
    keen_mat, reinf_mat = mats[0], mats[1]
    quality.register_additive(keen_mat, "keen")
    quality.register_additive(reinf_mat, "reinforced")
    assert "keen" in quality.PERKS and "reinforced" in quality.PERKS, "built-in perks exist"

    # forge WITH the 'keen' additive
    g1, sig1, forge1 = _fresh_quality()
    _seed_quality(g1)
    assert forge1.forge(g1, "Ward", additives=[keen_mat]) is True
    perks_keen = sig1.slots[-1]["perks"]

    # control: forge WITHOUT the 'keen' additive (a different additive -> 'reinforced')
    g2, sig2, forge2 = _fresh_quality()
    _seed_quality(g2)
    assert forge2.forge(g2, "Ward", additives=[reinf_mat]) is True
    perks_ctrl = sig2.slots[-1]["perks"]

    assert "keen" in perks_keen, ("keen additive steers the keen perk", perks_keen)
    assert "keen" not in perks_ctrl, ("control lacks the keen perk", perks_ctrl)
    assert "reinforced" in perks_ctrl, ("reinforced additive steers its perk", perks_ctrl)


def test_forge_quality_deterministic():
    # the same seeded quality state forges the same tier + perks, twice.
    import runtime.sigils
    runs = []
    for _ in range(2):
        g, sig, forge = _fresh_quality()
        _seed_quality(g, qual=2)
        forge.forge(g, "Ward", additives=[world_materials(g)[0]])
        s = sig.slots[-1]
        runs.append((s["quality"], tuple(s["perks"])))
    assert runs[0] == runs[1], ("quality forge is deterministic", runs)


def main():
    test_forge_success()
    test_forge_slots_full_noop()
    test_forge_no_matter_noop()
    test_forge_no_sigils_system_noop()
    test_auto_forge_recovers_loop()
    test_deterministic()
    test_forge_quality_floor()
    test_forge_additive_steers_perk()
    test_forge_quality_deterministic()
    print("OK")


if __name__ == "__main__":
    main()
