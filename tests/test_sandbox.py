"""Sandbox mode: the whole vault as one grown semilattice structure (ARCHITECTURE_SPEC §8)."""
from __future__ import annotations

from runtime.game import Game, load_manifest


def _game():
    return Game(load_manifest("examples/world.json"), sandbox=True)


def test_one_grown_world():
    g = _game()
    assert g.level.w > g.width or g.level.h > g.height, "the world outsizes the viewport"
    assert g.room_notes, "centers carry note identities natively"
    assert g._gates, "each district's heart holds a door to its depths"
    assert not any(a.is_boss for a in g.actors), \
        "wardens no longer stand in the open; they wait below"


def test_everything_dwells_at_its_own_note():
    g = _game()
    for a in g.actors:
        place = g.room_of_note(a.source)
        if place is not None:
            # inside its building, or camped just beside it when the interior
            # is too small to hold a body
            near = (place.contains(a.x, a.y)
                    or max(abs(a.x - place.center[0]),
                           abs(a.y - place.center[1])) <= 6)
            assert near, f"{a.name} strayed from its center"


def test_region_is_where_you_stand():
    g = _game()
    seen = set()
    for idx, nid in g.room_notes.items():
        tiles = g.room_tiles(idx)
        if not tiles:
            continue   # a sealed or empty pad: nowhere to stand
        g.player.x, g.player.y = tiles[0]
        seen.add(g.region_for(1)["id"])
    assert len(seen) == len(g.m["regions"]), "walking the districts visits every region"


def test_no_descent_in_the_sandbox():
    g = _game()
    g.descend()
    assert g.floor == 1 and g.alive


def test_viewport_follows_the_player():
    g = _game()
    body = g.render().split("\n")[0]
    assert len(body) <= g.width


def test_sandbox_is_deterministic():
    a, b = _game(), _game()
    assert [(x.name, x.x, x.y) for x in a.actors] == \
           [(x.name, x.x, x.y) for x in b.actors]


def test_places_carry_their_regions_palette():
    g = _game()
    assert g._tint, "footprint cells carry an element tint"
    nodes = g.m["graph"]["nodes"]
    for idx, nid in g.room_notes.items():
        region = g._region_by_comm.get(nodes[nid]["community"])
        if not region or region["element"] == "inert":
            continue
        for cell in list(g._places[idx][0].cells)[:3]:
            assert g._tint.get(cell) == region["element"]
    # corridors stay neutral: some walkable tile has no tint
    untinted = [(x, y) for y in range(g.level.h) for x in range(g.level.w)
                if g.level.walkable(x, y) and (x, y) not in g._tint]
    assert untinted, "the ways between places stay neutral"


if __name__ == "__main__":
    for fn in (test_one_grown_world, test_everything_dwells_at_its_own_note,
               test_region_is_where_you_stand, test_no_descent_in_the_sandbox,
               test_viewport_follows_the_player, test_sandbox_is_deterministic,
               test_places_carry_their_regions_palette):
        fn()
        print(f"ok {fn.__name__}")


def test_sprawl_stretches_the_land_between_districts():
    from runtime.game import load_manifest
    m = load_manifest("examples/world.json")
    compact = Game(m, sandbox=True, sprawl=1.0)
    wide = Game(m, sandbox=True, sprawl=2.5)
    assert wide.level.w * wide.level.h > compact.level.w * compact.level.h
    assert len(wide.room_notes) == len(compact.room_notes), \
        "every place survives the stretch"
