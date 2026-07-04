"""Area kinds: a region is a KIND of place (labyrinth, grove, flooded, ...), picked
by a nature-biased roll, folding blocks + shape + sight + voice into the region."""
from __future__ import annotations

from collections import deque

from runtime.arch import areakinds
from runtime.game import Game, load_manifest


def _game():
    p = "examples/world.json"
    return Game(load_manifest(p), sandbox=True, sprawl=3.0,
                site_cache=p + ".site.json")


def test_kind_is_deterministic_and_nature_biased():
    # same region + node + seed -> same kind, every time
    region = {"id": "r0"}
    node = {"role": "orphan", "degree": 0}     # bound to nothing -> leans labyrinth
    a = areakinds.kind_for(region, node, "s")
    b = areakinds.kind_for(region, node, "s")
    assert a == b, "a region's kind is stable"
    # the bias is real: over many seeds an orphan hits labyrinth far more than a hub
    orphan_maze = sum(areakinds.kind_for({"id": f"r{i}"}, node, i) == "labyrinth"
                      for i in range(200))
    hub = {"role": "hub", "degree": 9}
    hub_maze = sum(areakinds.kind_for({"id": f"r{i}"}, hub, i) == "labyrinth"
                   for i in range(200))
    assert orphan_maze > hub_maze, "orphans get lost more than hubs do"


def test_every_kind_declares_the_four_channels():
    for name, k in areakinds.KINDS.items():
        assert isinstance(areakinds.favors(name), list)
        assert isinstance(areakinds.voice(name), list)
        assert isinstance(areakinds.sight_mod(name), int)
        # shape is either None or callable
        assert areakinds.shape(name) is None or callable(areakinds.shape(name))


def test_shapes_keep_the_world_connected():
    g = _game()
    tiles = g.level.tiles
    start = next((x, y) for y in range(g.level.h) for x in range(g.level.w)
                 if tiles[y][x] != "#")
    seen, q = {start}, deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if (0 <= n[0] < g.level.w and 0 <= n[1] < g.level.h
                    and tiles[n[1]][n[0]] != "#" and n not in seen):
                seen.add(n)
                q.append(n)
    walk = sum(1 for row in tiles for c in row if c != "#")
    assert len(seen) == walk, "area-kind shapes (maze/flood) never sever the world"


def test_kinds_are_assigned_to_regions():
    g = _game()
    assert g._region_kind, "regions get area kinds"
    assert all(v in areakinds.KINDS for v in g._region_kind.values())


if __name__ == "__main__":
    for fn in (test_kind_is_deterministic_and_nature_biased,
               test_every_kind_declares_the_four_channels,
               test_shapes_keep_the_world_connected,
               test_kinds_are_assigned_to_regions):
        fn()
        print(f"ok {fn.__name__}")
