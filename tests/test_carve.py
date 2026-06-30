"""Phase 4: carving a grown SitePlan yields a connected, playable Level.

The contract (ARCHITECTURE_SPEC §7) checked here:
  * carve() returns a real dungeon.Level (tiles/walkable/player_start/stairs);
  * CONNECTIVITY (the one hard invariant): a flood-fill from player_start reaches
    every walkable tile -- so the stairs are always reachable, no stranded rooms;
  * start and stairs are walkable, distinct, and in bounds;
  * the level is organic, not a grid and not noise: it has real floor area but is
    not a solid rectangle of floor;
  * deterministic: same plan -> byte-identical tilemap;
  * drop-in: Level.walkable agrees with the tilemap, so the runtime consumes it
    exactly like a dungeon-generated level.

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_carve
"""
import json

from runtime.arch import grow as G
from runtime.arch.carve import carve, _reachable
from runtime.dungeon import Level, WALL, FLOOR, STAIRS


def _floor_count(lvl):
    return sum(row.count(FLOOR) + row.count(STAIRS) for row in lvl.tiles)


def _check(world):
    plan = G.grow(json.load(open(world))["graph"], seed="t")
    lvl = carve(plan)

    assert isinstance(lvl, Level), "carve must return a dungeon.Level"
    assert lvl.w > 0 and lvl.h > 0, "level has size"
    assert len(lvl.tiles) == lvl.h and all(len(r) == lvl.w for r in lvl.tiles), \
        "tilemap dimensions match w/h"

    sx, sy = lvl.player_start
    tx, ty = lvl.stairs
    assert 0 <= sx < lvl.w and 0 <= sy < lvl.h, "start in bounds"
    assert 0 <= tx < lvl.w and 0 <= ty < lvl.h, "stairs in bounds"
    assert (sx, sy) != (tx, ty), "start and stairs are distinct"
    assert lvl.walkable(sx, sy), "start is walkable"
    assert lvl.walkable(tx, ty), "stairs are walkable"
    assert lvl.tiles[ty][tx] == STAIRS, "stairs glyph placed"

    # --- the hard invariant: everything walkable is reachable from the entrance ---
    reached = _reachable(lvl.tiles, lvl.player_start, lvl.w, lvl.h)
    stranded = [(x, y) for y in range(lvl.h) for x in range(lvl.w)
                if lvl.tiles[y][x] != WALL and (x, y) not in reached]
    assert not stranded, f"{len(stranded)} walkable tiles unreachable from entrance"
    assert lvl.stairs in reached, "stairs must be reachable (solvable)"

    # --- organic: real floor area, but neither a solid rectangle nor near-empty ---
    floors = _floor_count(lvl)
    total = lvl.w * lvl.h
    assert floors >= 4 * len(plan.placed()), "each room should contribute floor area"
    assert floors < total, "the level is not solid floor (it has walls / shape)"

    # --- Level.walkable agrees with the raw tiles (drop-in for the runtime) ---
    for y in range(lvl.h):
        for x in range(lvl.w):
            assert lvl.walkable(x, y) == (lvl.tiles[y][x] != WALL), \
                f"walkable disagrees with tiles at {(x, y)}"

    return lvl


def main():
    for world in ("examples/world.json", "examples/world_v2.json"):
        lvl = _check(world)

        # --- determinism: re-grow + re-carve is byte-identical ---
        plan2 = G.grow(json.load(open(world))["graph"], seed="t")
        lvl2 = carve(plan2)
        assert lvl.tiles == lvl2.tiles, f"carve must be deterministic ({world})"
        assert (lvl.player_start, lvl.stairs) == (lvl2.player_start, lvl2.stairs), \
            "entrance/stairs must be deterministic"

        print(f"OK  {world}: {lvl.w}x{lvl.h}  floor={_floor_count(lvl)}  "
              f"start={lvl.player_start} stairs={lvl.stairs}  fully connected")


if __name__ == "__main__":
    main()
