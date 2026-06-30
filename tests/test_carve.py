"""Phase 4: carving a grown SitePlan yields a connected, playable Level whose geometry
IS the pattern language (ARCHITECTURE_SPEC §7), not just stamped blobs.

Two layers of contract are checked here.

STRUCTURE (the hard floor -- a carve that fails these is broken):
  * carve() returns a real dungeon.Level (tiles/walkable/player_start/stairs);
  * CONNECTIVITY (the one hard invariant): a flood-fill from player_start reaches
    every walkable tile -- stairs always reachable, no stranded rooms, even after
    focal voids and edge-nibbling carve holes into the map;
  * start/stairs walkable, distinct, in bounds; Level.walkable agrees with tiles;
  * deterministic: same plan + seed -> byte-identical tilemap.

QUALITY (the §7 patterns actually rendered into geometry -- the point of Phase 4):
  * grid_wholeness >= a floor, and strictly above a plain "stamp + straight corridors"
    carve, so a regression to featureless geometry is caught;
  * P10/P13 focal voids exist: interior wall cells fully ringed by floor (a strong
    center hollowed to a field-around-a-centre, the great center keeping the Void).

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_carve
"""
import json

from runtime.arch import grow as G
from runtime.arch.carve import (carve, grid_wholeness, _reachable,
                                _stamp, _carve_corridor, _int)
from runtime.dungeon import Level, WALL, FLOOR, STAIRS

WORLDS = ("examples/world.json", "examples/world_v2.json")
GRID_WHOLENESS_FLOOR = 0.80      # generated maps must stay this alive (regression guard, §11)


def _floor_count(lvl):
    return sum(row.count(FLOOR) + row.count(STAIRS) for row in lvl.tiles)


def _interior_voids(lvl):
    """Count interior wall cells fully ringed by floor -- the focal voids (P10/P13)."""
    t, w, h = lvl.tiles, lvl.w, lvl.h
    n = 0
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if t[y][x] == WALL and all(t[y + dy][x + dx] != WALL
                                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                n += 1
    return n


def _plain_carve(plan):
    """Baseline: stamp footprints + straight corridors, NO §7 operators. The pattern
    carve must beat this on grid_wholeness, or the patterns aren't earning their place."""
    placed = plan.placed()
    w, h = plan.bounds
    tiles = [[WALL] * w for _ in range(h)]
    for c in placed:
        _stamp(tiles, c.footprint, w, h)
    for s in plan.seams:
        a, b = plan.centers.get(s.a), plan.centers.get(s.b)
        if a and b and a.pos and b.pos:
            _carve_corridor(tiles, _int(a.pos), _int(b.pos), w, h, 1)
    ps = _int(max(placed, key=lambda c: (c.flow, c.id)).pos)
    st = _int(max(placed, key=lambda c: (c.intensity, c.id)).pos)
    return Level(w=w, h=h, tiles=tiles, rooms=[], player_start=ps, stairs=st)


def _check_structure(world):
    plan = G.grow(json.load(open(world))["graph"], seed="t")
    lvl = carve(plan, seed="t")

    assert isinstance(lvl, Level), "carve must return a dungeon.Level"
    assert len(lvl.tiles) == lvl.h and all(len(r) == lvl.w for r in lvl.tiles), \
        "tilemap dimensions match w/h"

    sx, sy = lvl.player_start
    tx, ty = lvl.stairs
    assert 0 <= sx < lvl.w and 0 <= sy < lvl.h, "start in bounds"
    assert 0 <= tx < lvl.w and 0 <= ty < lvl.h, "stairs in bounds"
    assert (sx, sy) != (tx, ty), "start and stairs distinct"
    assert lvl.walkable(sx, sy) and lvl.walkable(tx, ty), "start + stairs walkable"
    assert lvl.tiles[ty][tx] == STAIRS, "stairs glyph placed"

    # the hard invariant: nothing walkable is stranded from the entrance
    reached = _reachable(lvl.tiles, lvl.player_start, lvl.w, lvl.h)
    stranded = [(x, y) for y in range(lvl.h) for x in range(lvl.w)
                if lvl.tiles[y][x] != WALL and (x, y) not in reached]
    assert not stranded, f"{len(stranded)} walkable tiles unreachable from entrance"
    assert lvl.stairs in reached, "stairs reachable (solvable)"

    # drop-in: walkable agrees with tiles, so the runtime consumes it like dungeon output
    for y in range(lvl.h):
        for x in range(lvl.w):
            assert lvl.walkable(x, y) == (lvl.tiles[y][x] != WALL), \
                f"walkable disagrees with tiles at {(x, y)}"

    floors = _floor_count(lvl)
    assert floors >= 4 * len(plan.placed()), "each room contributes floor area"
    assert floors < lvl.w * lvl.h, "not a solid slab of floor"
    return plan, lvl


def main():
    for world in WORLDS:
        plan, lvl = _check_structure(world)

        # determinism
        lvl2 = carve(G.grow(json.load(open(world))["graph"], seed="t"), seed="t")
        assert lvl.tiles == lvl2.tiles, f"carve must be deterministic ({world})"

        # --- QUALITY: the §7 patterns actually rendered ---
        gw, terms = grid_wholeness(lvl, breakdown=True)
        assert gw >= GRID_WHOLENESS_FLOOR, \
            f"{world}: grid_wholeness {gw:.3f} below floor {GRID_WHOLENESS_FLOOR}: {terms}"

        plain_gw = grid_wholeness(_plain_carve(plan))
        assert gw > plain_gw + 0.05, \
            f"{world}: §7 carve ({gw:.3f}) must beat a plain stamp ({plain_gw:.3f})"

        # focal voids: P10/P13 must have hollowed at least the great center
        voids = _interior_voids(lvl)
        assert voids >= 1, f"{world}: no focal void carved (P10/P13 did not fire)"

        print(f"OK  {world}: {lvl.w}x{lvl.h} floor={_floor_count(lvl)} "
              f"grid_wholeness={gw:.3f} (plain {plain_gw:.3f}) voids={voids} connected")


if __name__ == "__main__":
    main()
