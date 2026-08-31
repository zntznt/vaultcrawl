"""Drive the real Game through the SalvageSystem and assert the contract.

Covers the salvage/inventory loop from SALVAGE_SPEC.md (Agent A):
  death -> ground salvage, collection into the persistent Inventory, sigil shatter ->
  salvage, voluntary sigil breakdown -> matter, salvage tiles as points-of-interest,
  and per-floor ground reset while carried matter persists.

A SigilSystem rides along so `breakdown_sigil` has a real `game.system("sigils").slots`
to pull from. Everything is positional / hash-derived, so the run is deterministic.

Run: python3 -m tests.test_salvage   (from the vaultcrawl project root)
"""
from runtime.components import inv, world_materials
from runtime.entities import make_enemy
from runtime.game import Game, load_manifest
from runtime.salvage import SALVAGE_GLYPH, SalvageSystem
from runtime.sigils import SigilSystem


def _carve_arena(g, cx, cy, rad=2):
    """Clear a deterministic floor patch so geometry doesn't depend on layout."""
    for yy in range(cy - rad, cy + rad + 1):
        for xx in range(cx - rad, cx + rad + 1):
            g.level.tiles[yy][xx] = "."


def _new_game():
    sal = SalvageSystem()
    sig = SigilSystem()
    g = Game(load_manifest("examples/world.json"), systems=[sal, sig])
    return g, sal, sig


def test_salvage():
    g, sal, sig = _new_game()

    # systems are registered -> ground starts empty after the floor-enter hook fired
    assert sal.ground == {}, "ground salvage starts empty on a fresh floor"
    assert sal.matter(g) == 0, "the player carries no matter yet"

    cx, cy = 10, 6
    _carve_arena(g, cx, cy)
    g.player.x, g.player.y = cx, cy
    g.alive = True

    mats = set(world_materials(g))
    assert mats, "the world must define a material vocabulary"

    # --- 1) death -> ground salvage, drawn from the world's materials --------
    spec = g.m["enemies"][0]
    enemy = make_enemy(spec, cx + 1, cy)
    drop_pos = (cx + 1, cy)
    g.emit("actor_died", actor=enemy, cause="test", pos=drop_pos)

    assert drop_pos in sal.ground, "a fallen creature leaves a salvage tile"
    corpse = sal.ground[drop_pos]
    assert corpse, "the salvage tile carries materials"
    assert set(corpse) <= mats, f"salvage materials {set(corpse)} must be world materials {mats}"

    # --- 2) walk onto it -> matter pours into the persistent Inventory -------
    before = sal.matter(g)
    expected = sum(corpse.values())
    g.player.x, g.player.y = drop_pos
    sal.on_player_act(g)

    assert drop_pos not in sal.ground, "stood-on salvage is removed from the ground"
    assert sal.matter(g) == before + expected, "collected matter grew the inventory total"
    assert sal.inventory(g) is inv(g.player), "the query API returns the player's Inventory"
    assert any(m.startswith("Salvaged ") for m in g.messages), "collection is logged"

    # --- 3) a sigil shatter (broke, kind='sigil') also drops salvage ---------
    broke_pos = (cx, cy + 1)
    g.emit("broke", kind="sigil", source=spec["sourceNoteId"], name="Ward",
           tier=1, pos=broke_pos)
    assert broke_pos in sal.ground, "a shattered sigil leaves salvage"
    assert set(sal.ground[broke_pos]) <= mats, "shard materials are world materials"

    # --- 4) breakdown_sigil: melt a slotted sigil back into matter -----------
    sigsys = g.system("sigils")
    sigsys.slots.append({"note": spec["sourceNoteId"], "role": "leaf",
                         "ability": "Ward", "durability": 2})
    slots_before = len(sigsys.slots)
    matter_before = sal.matter(g)

    comps = sal.breakdown_sigil(g)
    assert comps is not None, "breakdown returns the recovered components"
    assert len(sigsys.slots) == slots_before - 1, "the slot was freed"
    assert sal.matter(g) == matter_before + sum(comps.values()), "matter rose by the recovered comps"

    # None-guard: no sigils left to break / no sigil system -> None
    g.system("sigils").slots = []
    assert sal.breakdown_sigil(g) is None, "no slotted sigils -> None"
    lone = SalvageSystem()
    g_bare = Game(load_manifest("examples/world.json"), systems=[lone])
    assert lone.breakdown_sigil(g_bare) is None, "no sigil system -> None"

    # --- 5) salvage tiles are points-of-interest (for the auto-agent) --------
    poi = sal.points_of_interest(g)
    assert set(poi) == set(sal.ground), "points_of_interest lists exactly the salvage tiles"
    assert broke_pos in poi, "the remaining shard tile is a point of interest"

    # --- 6) render: salvage draws '*' on a floor cell ------------------------
    grid = [row[:] for row in g.level.tiles]
    sal.render_overlay(g, grid)
    for (x, y) in sal.ground:
        if g.level.tiles[y][x] == "." and g.actor_at(x, y) is None and (x, y) != (g.player.x, g.player.y):
            assert grid[y][x] == SALVAGE_GLYPH, "ground salvage renders as '*'"

    # --- 7) inventory PERSISTS across a floor change; ground is per-floor ----
    carried = sal.matter(g)
    assert carried > 0, "the player is carrying matter to test persistence"
    assert sal.ground, "there is ground salvage to be cleared by the floor change"
    sal.on_floor_enter(g)
    assert sal.ground == {}, "on_floor_enter clears the per-floor ground salvage"
    assert sal.matter(g) == carried, "carried matter persists across floors"

    # status line reflects the carried matter
    line = sal.status_line(g)
    assert isinstance(line, str) and line.startswith("Matter: "), line


def main():
    test_salvage()
    print("OK")


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------- #
# Salvage yield knobs. The forge floor is the grade of the units spent, and 81% of banked
# matter is Normal, so the graded share of the pool is the thing an arm has to move. These
# two multipliers exist to move it and to separate "more grade" from "more matter".
# --------------------------------------------------------------------------- #

def _bank_one_tile(monkeypatch_env, quality, qty=4):
    """Run one _collect against a hand-placed tile and report what got banked."""
    import importlib
    import runtime.salvage as S
    from runtime.stack import reset_run_state
    importlib.reload(S)
    # foraging is per-run module state and it grants +1 matter per tier, so without this the
    # second tile in a test is scored against the skill the first one exercised
    reset_run_state()
    from runtime.components import Inventory

    class _Player:
        x = y = 1

    class _Game:
        player = _Player()

        def log(self, *a, **k):
            pass

    sal = S.SalvageSystem()
    game = _Game()
    sal.ground[(1, 1)] = {"brass": qty}
    if quality:
        sal.ground_q[(1, 1)] = quality
    bag = Inventory()
    game.player._inv = bag
    sal._collect(game)
    return bag


def test_yield_knobs_default_to_the_shipped_game(monkeypatch):
    monkeypatch.delenv("VC_SALVAGE_GRADED_MULT", raising=False)
    monkeypatch.delenv("VC_SALVAGE_PLAIN_MULT", raising=False)
    assert _bank_one_tile(monkeypatch, quality=2).comp["brass"] == 4
    assert _bank_one_tile(monkeypatch, quality=0).comp["brass"] == 4


def test_the_graded_knob_lifts_only_graded_salvage(monkeypatch):
    monkeypatch.setenv("VC_SALVAGE_GRADED_MULT", "3.0")
    monkeypatch.delenv("VC_SALVAGE_PLAIN_MULT", raising=False)
    graded = _bank_one_tile(monkeypatch, quality=2)
    plain = _bank_one_tile(monkeypatch, quality=0)
    assert graded.comp["brass"] == 12, "graded salvage scales"
    assert graded.quality_of("brass") == 2, "and the extra units carry the grade"
    assert plain.comp["brass"] == 4, "ungraded salvage must not move with it"


def test_the_plain_knob_adds_quantity_without_adding_grade(monkeypatch):
    monkeypatch.delenv("VC_SALVAGE_GRADED_MULT", raising=False)
    monkeypatch.setenv("VC_SALVAGE_PLAIN_MULT", "1.5")
    plain = _bank_one_tile(monkeypatch, quality=0)
    graded = _bank_one_tile(monkeypatch, quality=2)
    assert plain.comp["brass"] == 6 and plain.quality_of("brass") == 0
    assert graded.comp["brass"] == 4, "graded salvage must not move with it"


def test_scaling_never_erases_a_unit(monkeypatch):
    """A multiplier below 1 must not round a one-unit tile away to nothing: an arm that
    silently deletes salvage is measuring a different game than the one it names."""
    import importlib
    import runtime.salvage as S
    monkeypatch.setenv("VC_SALVAGE_PLAIN_MULT", "0.1")
    importlib.reload(S)
    assert S._scaled({"brass": 1, "moss": 2}, S.PLAIN_YIELD) == {"brass": 1, "moss": 1}
