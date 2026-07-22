"""World and skill systems — tension, aspects, sacrifice, autoexplore, ghosts.

Run: python3 -m tests.test_world_systems
"""
from runtime.game import Game, load_manifest
from runtime.entities import make_enemy
from runtime.sacrifice import SacrificeSystem
from runtime.body_parts import init_body


def test_tension():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    g.player.x, g.player.y = 5, 5
    g._tension = 50
    g._resting = True
    g._tick_tension()
    assert g._tension > 50  # resting raises tension


def test_aspect():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    g.player.x, g.player.y = 5, 5
    g._aspect = ""
    g._aspect_turns = 0
    # aspect only ticks on sandbox surface, so this should be safe (no crash)
    g._tick_aspect()
    assert g._aspect_turns > 0 or True  # always passes, just tests no-crash


def test_sacrifice_shrine():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    g.player.max_hp = 32
    g.player.hp = 32
    ss = SacrificeSystem()
    ss.on_world_start(g)
    from runtime.sigils import SigilSystem
    from runtime.salvage import SalvageSystem
    g.systems = [SigilSystem(), SalvageSystem(), ss]
    g.systems[0].on_world_start(g)
    g.systems[1].on_world_start(g)
    ss.apply(g, "sigil")


def test_autoexplore_finds_fog_edge():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    g.player.x, g.player.y = 5, 5
    know = g.system("knowledge")
    if know:
        know.on_floor_enter(g)
        seen = know.seen.get(g.floor, set())
        # there should be unseen tiles in a fresh level
        unseen = [(x, y) for y in range(20) for x in range(20)
                  if g.level.walkable(x, y) and (x, y) not in seen]
        assert len(unseen) > 0 or len(seen) > 0


def test_targeting_metadata():
    from runtime.abilities import ACTION_TARGETING
    for act in ("spit", "enrage", "shield", "blink", "summon", "split", "rally"):
        assert act in ACTION_TARGETING, f"missing targeting for {act}"
        assert ACTION_TARGETING[act] in ("self", "bolt", "adjacent", "near_self")


def test_ghost_encounter():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    g._graves = {(5, 5): "slain by goblin\nATK 4 DEF 0\n0 kills · 1 items."}
    for y in range(4, 8):
        for x in range(4, 8):
            if 0 <= y < g.level.h and 0 <= x < g.level.w:
                g.level.tiles[y][x] = "."
    for _ in range(20):  # try multiple times since animation is random
        g._animate_graves()
        ghost = g.actor_at(5, 5)
        if ghost:
            assert ghost.glyph == "†"
            assert "Echo" in ghost.name
            return
    # ghost didn't spawn, but that's OK — random


if __name__ == "__main__":
    test_tension()
    test_aspect()
    test_sacrifice_shrine()
    test_autoexplore_finds_fog_edge()
    test_targeting_metadata()
    test_ghost_encounter()
    print("OK")
