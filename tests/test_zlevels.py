"""Z-level architecture integration test.

Run: python3 -m tests.test_zlevels
"""
from runtime.game import Game, load_manifest
from runtime.dungeon import Level, generate_level
from runtime.entities import Actor, Item


def test_z_fields():
    """All core types carry z: int = 0."""
    a = Actor(0, 0, "@", "test", 10, 10, 1)
    assert a.z == 0
    assert Actor(0, 0, "@", "test", 10, 10, 1, z=-1).z == -1
    assert Item(0, 0, ")", "sword", "weapon", 5).z == 0


def test_game_z_init():
    """Game has current_z and _levels z-stack."""
    g = Game(load_manifest("examples/world.json"))
    assert g.current_z == 0
    assert isinstance(g._levels, dict)


def test_z_descend_ascend():
    """Z-level movement: descending changes level, ascending returns."""
    g = Game(load_manifest("examples/world.json"))
    lvl0 = g.level
    lvl0.z = 0
    lvlm1 = generate_level(40, 20, "test:z:-1", 0)
    lvlm1.z = -1
    g._set_level(lvl0, z=0)
    g._levels = {0: lvl0, -1: lvlm1}
    g._dungeon = {"region": g.m["regions"][0]}
    g.player.x, g.player.y = lvl0.player_start
    g.alive = True
    g._z_descend()
    assert g.current_z == -1
    g._z_ascend()
    assert g.current_z == 0


def test_snapshot_restores_z():
    """Snapshots preserve z-stack and restore it."""
    g = Game(load_manifest("examples/world.json"))
    g._levels = {0: g.level}
    snap = g._snapshot()
    assert "levels" in snap
    assert snap["current_z"] == 0

    g2 = Game(load_manifest("examples/world.json"))
    g2._restore(snap)
    assert g2.current_z == snap["current_z"]


def test_hud_shows_z():
    """Render shows z-level tag when in dungeon depths."""
    g = Game(load_manifest("examples/world.json"))
    g._dungeon = {"region": g.m["regions"][0]}
    g.region_name = "Test Depths"
    g.current_z = -2
    r2 = g.render()
    assert "z=-2" in r2, f"z=-2 not found in: {r2[:300]}"


def test_multi_z_generation():
    """_generate_depths creates a z-stack with multiple levels."""
    g = Game(load_manifest("examples/world.json"), sandbox=True)
    region = g.m["regions"][0]
    g._levels = {0: g.level}
    g._generate_depths(region["id"], "surface")
    neg_levels = [z for z in g._levels if z < 0]
    assert len(neg_levels) >= 1
    for z in neg_levels:
        lvl = g._levels[z]
        assert lvl is not None
        has_stair = any(">" in "".join(r) or "<" in "".join(r) for r in lvl.tiles)
        assert has_stair, f"z={z} has no stair glyphs"


if __name__ == "__main__":
    test_z_fields()
    test_game_z_init()
    test_z_descend_ascend()
    test_snapshot_restores_z()
    test_hud_shows_z()
    test_multi_z_generation()
    print("OK")
