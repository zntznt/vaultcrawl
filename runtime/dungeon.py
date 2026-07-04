"""Procedural floor layout with GUARANTEED connectivity.

Rooms are placed without overlap, then connected with a minimum spanning tree over their
centers (Prim's). Because an MST spans every room, there is always a path from the
entrance to the stairs -- this is the "definite structure" the generative layer is never
allowed to break. Seeded by (vault seed, floor) so a floor is reproducible.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

WALL, FLOOR, STAIRS = "#", ".", ">"


@dataclass
class Room:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def intersects(self, o: "Room", pad: int = 1) -> bool:
        return (self.x - pad < o.x + o.w and self.x + self.w + pad > o.x and
                self.y - pad < o.y + o.h and self.y + self.h + pad > o.y)


@dataclass
class Level:
    w: int
    h: int
    tiles: list
    rooms: list
    player_start: tuple
    stairs: tuple

    def walkable(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h and self.tiles[y][x] != WALL


def _carve_room(tiles, r: Room):
    for yy in range(r.y, r.y + r.h):
        for xx in range(r.x, r.x + r.w):
            tiles[yy][xx] = FLOOR


def _carve_h(tiles, x1, x2, y):
    for x in range(min(x1, x2), max(x1, x2) + 1):
        tiles[y][x] = FLOOR


def _carve_v(tiles, y1, y2, x):
    for y in range(min(y1, y2), max(y1, y2) + 1):
        tiles[y][x] = FLOOR


def _connect_mst(tiles, rooms, rng):
    if len(rooms) < 2:
        return
    centers = [r.center for r in rooms]
    connected = {0}
    while len(connected) < len(rooms):
        best = None
        for i in sorted(connected):
            for j in range(len(rooms)):
                if j in connected:
                    continue
                (xi, yi), (xj, yj) = centers[i], centers[j]
                d = (xi - xj) ** 2 + (yi - yj) ** 2
                if best is None or d < best[0]:
                    best = (d, i, j)
        _, i, j = best
        (x1, y1), (x2, y2) = centers[i], centers[j]
        if rng.random() < 0.5:
            _carve_h(tiles, x1, x2, y1)
            _carve_v(tiles, y1, y2, x2)
        else:
            _carve_v(tiles, y1, y2, x1)
            _carve_h(tiles, x1, x2, y2)
        connected.add(j)


def _architecture_level(graph: dict, seed: str, floor: int) -> Level:
    """Grow + carve a living level from the vault graph (ARCHITECTURE_SPEC, Phase 6).
    Seeded by (seed, floor) so each floor is a distinct living layout from the same
    corpus. Imports lazily: runtime.arch.carve imports dungeon.Level, so a top-level
    import here would be circular."""
    from runtime.arch import grow as _grow
    from runtime.arch.carve import carve as _carve
    plan = _grow.grow(graph, seed=f"{seed}:floor:{floor}")
    return _carve(plan, seed=f"{seed}:floor:{floor}")


def build_world(graph: dict, seed: str):
    """Sandbox: grow + carve the WHOLE vault as ONE persistent world (no floors).
    Returns (level, region_map, plan) where region_map is {(x,y) -> note id} so the
    game can resolve which district the player stands in. Lazy import (circular)."""
    from runtime.arch import grow as _grow
    from runtime.arch.carve import carve as _carve, region_map as _region_map
    plan = _grow.grow(graph, seed=f"{seed}:world")
    level = _carve(plan, seed=f"{seed}:world")
    return level, _region_map(plan), plan


def generate_level(width: int, height: int, seed: str, floor: int,
                   max_rooms: int = 8, graph: dict | None = None) -> Level:
    # Architecture path: if the manifest carries a vault graph, grow+carve a living
    # level. Falls back to rooms+MST on any failure (and when no graph is present), so
    # the bare game always produces a playable, connected level.
    if graph and graph.get("nodes"):
        try:
            return _architecture_level(graph, seed, floor)
        except Exception:
            pass  # fall through to the proven rooms+MST generator
    rng = random.Random(f"{seed}:floor:{floor}")
    tiles = [[WALL] * width for _ in range(height)]
    rooms: list = []
    for _ in range(max_rooms * 4):
        if len(rooms) >= max_rooms:
            break
        w = rng.randint(4, 8)
        h = rng.randint(3, 6)
        x = rng.randint(1, width - w - 2)
        y = rng.randint(1, height - h - 2)
        r = Room(x, y, w, h)
        if any(r.intersects(o) for o in rooms):
            continue
        rooms.append(r)
        _carve_room(tiles, r)

    _connect_mst(tiles, rooms, rng)

    player_start = rooms[0].center
    if len(rooms) >= 2:
        sx, sy = rooms[-1].center
    else:  # single-room fallback: opposite corner
        r = rooms[0]
        sx, sy = (r.x + r.w - 1, r.y + r.h - 1)
    tiles[sy][sx] = STAIRS
    return Level(w=width, h=height, tiles=tiles, rooms=rooms,
                 player_start=player_start, stairs=(sx, sy))


def free_floor_tiles(level: Level, exclude: set) -> list:
    out = []
    for y in range(level.h):
        for x in range(level.w):
            if level.tiles[y][x] == FLOOR and (x, y) not in exclude:
                out.append((x, y))
    return out
