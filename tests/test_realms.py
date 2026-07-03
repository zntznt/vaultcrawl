"""The realm semilattice: towns above, depths below, passages beneath borders."""
from __future__ import annotations

from runtime.game import Game, load_manifest


def _game():
    return Game(load_manifest("examples/world.json"), sandbox=True)


def _enter_first_depths(g):
    door, rid = sorted(g._gates.items())[0]
    g.player.x, g.player.y = door
    g.descend()
    return door, rid


def test_towns_are_settled_ground():
    g = _game()
    assert g._town_rooms and g._town_tiles
    from runtime.entities import Actor
    foe = Actor(x=0, y=0, glyph="s", name="raider", hp=5, max_hp=5, atk=1)
    tile = sorted(g._town_tiles)[0]
    foe.x, foe.y = tile[0] - 1, tile[1]
    g.actors = [foe]
    g._npc_step(foe, 1, 0)
    assert (foe.x, foe.y) != tile, "nothing hostile crosses a town threshold"
    g.player.x, g.player.y = tile
    g.player.hp = 10
    g.wait()
    assert g.player.hp > 10, "waiting in town is rest"


def test_depths_hold_the_warden_and_the_way_home():
    g = _game()
    door, rid = _enter_first_depths(g)
    assert g._realm == rid and g._dungeon is not None
    assert any(a.is_boss for a in g.actors), "the region's warden dwells below"
    assert "surface" in g._gates.values(), "a stair climbs home"
    up = next(p for p, d in g._gates.items() if d == "surface")
    g.player.x, g.player.y = up
    g.ascend()
    assert g._realm == "surface" and (g.player.x, g.player.y) == door


def test_realms_persist():
    g = _game()
    door, _rid = _enter_first_depths(g)
    victim = next(a for a in g.actors if a.allegiance == "monster"
                  and not a.is_boss)
    n = len(g.actors)
    g.kill(victim, "debug")
    up = next(p for p, d in g._gates.items() if d == "surface")
    g.player.x, g.player.y = up
    g.ascend()
    g.player.x, g.player.y = door
    g.descend()
    assert len(g.actors) == n - 1 and all(a is not victim for a in g.actors), \
        "what you kill stays dead"


def test_the_map_graph_is_not_a_tree():
    """Down one door, across beneath the border, up ANOTHER door: a cycle."""
    g = _game()
    door, rid = _enter_first_depths(g)
    passage = next(((p, d) for p, d in sorted(g._gates.items())
                    if d not in ("surface",)), None)
    assert passage is not None, "bordering depths interconnect"
    g.player.x, g.player.y = passage[0]
    g.descend()
    assert g._realm == passage[1], "crossed beneath the border"
    up = next(p for p, d in g._gates.items() if d == "surface")
    g.player.x, g.player.y = up
    g.ascend()
    assert g._realm == "surface"
    assert (g.player.x, g.player.y) != door, \
        "surfaced through a DIFFERENT door: the loop no tree contains"


if __name__ == "__main__":
    for fn in (test_towns_are_settled_ground,
               test_depths_hold_the_warden_and_the_way_home,
               test_realms_persist, test_the_map_graph_is_not_a_tree):
        fn()
        print(f"ok {fn.__name__}")
