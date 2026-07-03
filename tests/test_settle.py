"""settle(): buildings become connected complexes, roads arc, interior stays whole."""
from __future__ import annotations

import json
from collections import deque

from runtime.arch.grow import grow
from runtime.arch.settle import settle, _partition_complex
from runtime.dungeon import FLOOR, WALL


def _level():
    m = json.load(open("examples/world.json"))
    return settle(grow(m["graph"], seed=m["seed"], sprawl=2.5), seed=m["seed"])


def test_big_footprints_become_multi_room_complexes():
    lvl = _level()
    tiles = lvl.tiles
    # an internal (dividing) wall has floor on two-plus orthogonal sides
    dividing = 0
    for y in range(1, lvl.h - 1):
        for x in range(1, lvl.w - 1):
            if tiles[y][x] == WALL:
                nb = [tiles[y + dy][x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
                if sum(1 for c in nb if c != WALL) >= 2:
                    dividing += 1
    assert dividing > 20, f"buildings should subdivide into complexes, got {dividing}"


def test_partition_keeps_the_interior_connected():
    # a solid 14x14 interior, partitioned, must stay one connected floor region
    import random
    W = H = 20
    tiles = [[WALL] * W for _ in range(H)]
    inner = set()
    for y in range(3, 17):
        for x in range(3, 17):
            tiles[y][x] = FLOOR
            inner.add((x, y))
    _partition_complex(tiles, inner, W, H, random.Random(1))
    floor = {t for t in inner if tiles[t[1]][t[0]] != WALL}
    start = min(floor)
    seen, stack = {start}, [start]
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in floor and n not in seen:
                seen.add(n)
                stack.append(n)
    assert seen == floor, f"{len(floor - seen)} interior tiles were stranded"
    assert len(floor) < len(inner), "the partition raised at least one internal wall"


def test_partition_is_deterministic():
    import random
    def run():
        W = H = 20
        tiles = [[WALL] * W for _ in range(H)]
        inner = {(x, y) for y in range(3, 17) for x in range(3, 17)}
        for x, y in inner:
            tiles[y][x] = FLOOR
        _partition_complex(tiles, inner, W, H, random.Random(7))
        return "".join("".join(r) for r in tiles)
    assert run() == run()


def test_whole_level_is_connected():
    lvl = _level()
    tiles = lvl.tiles
    start = next((x, y) for y in range(lvl.h) for x in range(lvl.w)
                 if tiles[y][x] != WALL)
    seen, q = {start}, deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if (0 <= n[0] < lvl.w and 0 <= n[1] < lvl.h
                    and tiles[n[1]][n[0]] != WALL and n not in seen):
                seen.add(n)
                q.append(n)
    walkable = sum(1 for row in tiles for c in row if c != WALL)
    # settle + _ensure_connected guarantee a single reachable body
    assert len(seen) == walkable, f"{walkable - len(seen)} walkable tiles unreachable"


if __name__ == "__main__":
    for fn in (test_big_footprints_become_multi_room_complexes,
               test_partition_keeps_the_interior_connected,
               test_partition_is_deterministic, test_whole_level_is_connected):
        fn()
        print(f"ok {fn.__name__}")
