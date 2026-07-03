"""Figure-ground surface rasterizer — the overworld is a LANDSCAPE, not a cave.

The classic carve is the cave paradigm: solid rock, carved rooms, bored tunnels —
which reads as Generic Roguelike no matter how it is scored. Alexander's figure
and ground are the other way around: BUILDINGS stand in OPEN LAND, outdoor space
is positive, roads cross fields, walls enclose. settle() rasterizes the same
grown SitePlan that way:

  open ground   everywhere (the land)
  buildings     each center's footprint: a WALLED enclosure, floor within,
                DOORS facing its linked neighbours (the graph decides the doors)
  roads         seams drawn as visible ways (ROAD tiles) across the ground —
                travel has a surface, not a tunnel
  interiors     the room-scale pattern catalogue applies inside, as below

The depths keep the classic cave carve on purpose: settled land above, dark
dungeon below — the intimacy gradient as a paradigm contrast you can feel.
"""
from __future__ import annotations

import random
from collections import defaultdict

from runtime.dungeon import FLOOR, Level, STAIRS, WALL

ROAD = "░"
_DIRS8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def _line(a, b):
    (x1, y1), (x2, y2) = a, b
    pts, step = [], 1 if x2 >= x1 else -1
    for x in range(x1, x2 + step, step):
        pts.append((x, y1))
    step = 1 if y2 >= y1 else -1
    for y in range(y1, y2 + step, step):
        pts.append((x2, y))
    return pts


def _way(a, b, rng):
    """A path that WALKS from a to b in slow arcs. The old L-connector (_line) drew
    ruler-straight rails with right angles and the world read as a circuit board.
    High-frequency jitter is no better (a straight rail with pimples): what a real
    path has is a LEAN that wanders slowly, so the way drifts off the true line,
    holds the curve a while, and swings back. Tapers to the goal at both ends."""
    (x, y), (x2, y2) = a, b
    pts = [(x, y)]
    lean = 0
    guard = 4 * (abs(x2 - x) + abs(y2 - y)) + 32
    while (x, y) != (x2, y2) and guard:
        guard -= 1
        if rng.random() < 0.2:                 # the lean drifts slowly: arcs, not noise
            lean = max(-3, min(3, lean + rng.choice((-1, 1))))
        adx, ady = abs(x2 - x), abs(y2 - y)
        if ady >= adx:                         # mostly-vertical course
            y += (y2 > y) - (y2 < y)
            tx = x2 + (lean if ady > 4 else 0)
            x += (tx > x) - (tx < x)
        else:                                  # mostly-horizontal course
            x += (x2 > x) - (x2 < x)
            ty = y2 + (lean if adx > 4 else 0)
            y += (ty > y) - (ty < y)
        pts.append((x, y))
    return pts


def settle(plan, seed="settle") -> Level:
    placed = plan.placed()
    if not placed:
        raise ValueError("settle() needs a grown plan")
    w, h = plan.bounds if plan.bounds != (0, 0) else (
        max(p[0] for c in placed for p in c.footprint) + 2,
        max(p[1] for c in placed for p in c.footprint) + 2)
    tiles = [[FLOOR] * w for _ in range(h)]
    for x in range(w):
        tiles[0][x] = tiles[h - 1][x] = WALL
    for y in range(h):
        tiles[y][0] = tiles[y][w - 1] = WALL

    # buildings: perimeter walls, floor within. A footprint too small to hold a
    # real interior stays an OPEN pad (a shrine, not a sealed cairn).
    interiors: set = set()
    for c in placed:
        fp = set(map(tuple, c.footprint))
        inner = {t for t in fp
                 if all((t[0] + dx, t[1] + dy) in fp for dx, dy in _DIRS8)}
        if len(inner) < 2:
            interiors |= fp
            continue
        for (x, y) in fp:
            if (x, y) in inner:
                interiors.add((x, y))
            elif 0 <= x < w and 0 <= y < h:
                tiles[y][x] = WALL

    # doors: the graph decides them — each seam opens the wall facing its partner
    centers = {c.id: c for c in placed}
    doors = defaultdict(int)

    def _carve_door(c, toward):
        fp = set(map(tuple, c.footprint))
        walls = [t for t in sorted(fp) if tiles[t[1]][t[0]] == WALL
                 and any((t[0] + dx, t[1] + dy) in interiors for dx, dy in _DIRS8)]
        if not walls:
            return False
        tx, ty = toward
        x, y = min(walls, key=lambda t: (t[0] - tx) ** 2 + (t[1] - ty) ** 2)
        tiles[y][x] = FLOOR
        interiors.add((x, y))
        return True

    for s in plan.seams:
        for a, b in ((s.a, s.b), (s.b, s.a)):
            ca, cb = centers.get(a), centers.get(b)
            if (ca is None or cb is None or ca.pos is None or cb.pos is None
                    or doors[a] >= 3):
                continue
            if _carve_door(ca, (int(cb.pos[0]), int(cb.pos[1]))):
                doors[a] += 1
    for c in placed:                      # a building with no line still needs a door
        if doors[c.id] == 0 and c.pos is not None:
            _carve_door(c, (int(c.pos[0]) + 1, int(c.pos[1]) + 7))

    # roads: seams as visible ways across the open land (never through walls),
    # each walked with its own gait, not drawn with a ruler
    import random as _random
    for s in plan.seams:
        ca, cb = centers.get(s.a), centers.get(s.b)
        if ca is None or cb is None or ca.pos is None or cb.pos is None:
            continue
        wrng = _random.Random(f"{seed}:way:{s.a}:{s.b}")
        for (x, y) in _way((int(ca.pos[0]), int(ca.pos[1])),
                           (int(cb.pos[0]), int(cb.pos[1])), wrng):
            if 0 <= x < w and 0 <= y < h and tiles[y][x] == FLOOR \
                    and (x, y) not in interiors:
                tiles[y][x] = ROAD

    # the room-scale pattern catalogue applies within, exactly as below ground
    from .interiors import apply_interiors
    apply_interiors(plan, tiles, w, h, seed)

    from .carve import _ensure_connected, _pick_entrance_stairs
    player_start, stairs = _pick_entrance_stairs(placed)
    tiles[player_start[1]][player_start[0]] = FLOOR
    tiles[stairs[1]][stairs[0]] = FLOOR
    _ensure_connected(tiles, player_start, placed, w, h)
    tiles[stairs[1]][stairs[0]] = STAIRS
    return Level(w=w, h=h, tiles=tiles, rooms=[],
                 player_start=player_start, stairs=stairs)
