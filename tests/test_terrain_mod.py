"""Terrain modification tests.

Run: python3 -m tests.test_terrain_mod
"""
from runtime.game import Game, load_manifest
from runtime.entities import make_enemy, Actor
from runtime.terrain_mod import TerrainModSystem
from runtime.factions import FactionSystem


def test_boss_kill_creates_monument():
    g = Game(load_manifest("examples/world.json"))
    tm = TerrainModSystem()
    tm.on_world_start(g)
    g.alive = True
    boss = Actor(5, 5, "M", "Warden", hp=20, max_hp=20, atk=5, is_boss=True, source="stoicism", allegiance="monster")
    g.actors = [boss]
    g._overlay = {}
    g._landmarks = {}

    tm.on_event(g, "enemy_killed", {"enemy": boss})
    assert (5, 5) in g._landmarks
    assert g._landmarks[(5, 5)] == "monument"
    assert g._overlay.get((5, 5)) == "▲"


def test_kill_scar_creates_overlay():
    g = Game(load_manifest("examples/world.json"))
    # carve an open arena at a known walkable spot
    for yy in range(5, 12):
        for xx in range(5, 12):
            g.level.tiles[yy][xx] = "."
    tm = TerrainModSystem()
    tm.on_world_start(g)
    g.alive = True
    e = make_enemy({"tier": 1, "archetype": "warden", "name": "goblin", "sourceNoteId": "x"}, 8, 8)
    g.actors = [e]
    g._overlay = {}
    for _ in range(5):
        tm.on_event(g, "enemy_killed", {"enemy": e})
    scarred = any(v == "†" for v in g._overlay.values())
    assert scarred, "expected scar overlay after 5 kills"


def test_forge_triggers_event():
    g = Game(load_manifest("examples/world.json"))
    tm = TerrainModSystem()
    tm.on_world_start(g)
    g.alive = True
    g.player.x, g.player.y = 10, 10
    # forge_used event should not crash
    tm.on_event(g, "forge_used", {"ability": "Ward"})


def test_lore_reveal_triggers_on_third_read():
    g = Game(load_manifest("examples/world.json"), systems=[TerrainModSystem()])
    tm = g.system("terrain")
    assert tm is not None
    g.alive = True
    g.up = type("u", (), {"revealed_notes": set()})()
    # lore_read events should not crash even without history/marginalia registered
    for _ in range(3):
        tm.on_event(g, "lore_read", {"note": "stoicism"})


def test_scar_fade():
    g = Game(load_manifest("examples/world.json"))
    tm = TerrainModSystem()
    tm.on_world_start(g)
    g.alive = True
    e = make_enemy({"tier": 1, "archetype": "warden", "name": "goblin", "sourceNoteId": "x"}, 10, 10)
    g.actors = [e]
    g._overlay = {}
    for _ in range(5):
        tm.on_event(g, "enemy_killed", {"enemy": e})
    # tick many times to fade scars
    for _ in range(250):
        tm.on_player_act(g)
    scarred = any(v == "†" for v in g._overlay.values())
    assert not scarred, "scars should fade after TTL expires"


if __name__ == "__main__":
    test_boss_kill_creates_monument()
    test_kill_scar_creates_overlay()
    test_forge_triggers_event()
    test_lore_reveal_triggers_on_third_read()
    test_scar_fade()
    print("OK")
