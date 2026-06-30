"""Phase 4: carve a grown SitePlan into a playable Level (ARCHITECTURE_SPEC §7).

The growth pass (grow.py) already did the hard part: every center owns an organic,
non-overlapping footprint in a 1-padded positive grid (plan.bounds), and the seams
form a connected semilattice over the centers. Carving is the rasterizer that turns
that living structure into the exact `Level` shape the runtime consumes
(`tiles[y][x]`, `walkable`, `player_start`, `stairs`):

  1. stamp every footprint as FLOOR  (the rooms — organic, not rectangles)
  2. carve a corridor along every seam, center-to-center (the ways)
  3. carve focal voids for sub-centers (the calm centre of a strong center)
  4. pick entrance (highest-flow center) + stairs (deepest / most-central)
  5. GUARANTEE connectivity: flood-fill from the entrance; if anything is stranded,
     carve a straight corridor to the nearest reached floor and repeat. This is the
     one hard invariant -- a carve that doesn't connect is a bug, not a style.

Connectivity is enforced by construction + verified, so the carver can never emit a
level where the stairs are unreachable. Output Level is a drop-in for dungeon.Level.
"""
from __future__ import annotations

from collections import deque

from runtime.dungeon import Level, WALL, FLOOR, STAIRS


def _line(a, b):
    """Tiles on an L-shaped path a->b (horizontal then vertical). Deterministic."""
    (x1, y1), (x2, y2) = a, b
    pts = []
    step = 1 if x2 >= x1 else -1
    for x in range(x1, x2 + step, step):
        pts.append((x, y1))
    step = 1 if y2 >= y1 else -1
    for y in range(y1, y2 + step, step):
        pts.append((x2, y))
    return pts


def _stamp(tiles, cells, w, h):
    for (x, y) in cells:
        if 0 <= x < w and 0 <= y < h:
            tiles[y][x] = FLOOR


def _corridor(tiles, a, b, w, h, width=1):
    """Carve an L-corridor a->b. width=1 is a path, 2 a promenade."""
    for (x, y) in _line(a, b):
        for dx in range(width):
            for dy in range(width):
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h:
                    tiles[yy][xx] = FLOOR


def _reachable(tiles, start, w, h):
    """Flood-fill of walkable tiles from start (4-connected)."""
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and tiles[ny][nx] != WALL:
                seen.add((nx, ny))
                q.append((nx, ny))
    return seen


def _int(p):
    return (int(round(p[0])), int(round(p[1])))


def carve(plan) -> Level:
    """Rasterize a grown SitePlan into a connected Level."""
    placed = plan.placed()
    if not placed:
        raise ValueError("carve() needs a grown plan (no placed centers)")

    w, h = plan.bounds if plan.bounds != (0, 0) else (
        max(p[0] for c in placed for p in c.footprint) + 2,
        max(p[1] for c in placed for p in c.footprint) + 2,
    )
    tiles = [[WALL] * w for _ in range(h)]

    # 1) rooms: every footprint becomes floor
    for c in placed:
        _stamp(tiles, c.footprint, w, h)

    # 2) ways: a corridor per seam. promenades (strong, high-flow) ride 2 wide.
    ids = {c.id for c in placed}
    for s in plan.seams:
        if s.a not in plan.centers or s.b not in plan.centers:
            continue
        a, b = plan.centers[s.a], plan.centers[s.b]
        if a.pos is None or b.pos is None or s.a not in ids or s.b not in ids:
            continue
        width = 2 if (s.kind in ("shared_court",) or s.strength >= 3) else 1
        _corridor(tiles, _int(a.pos), _int(b.pos), w, h, width=width)

    # 3) focal voids: a strong center's sub-center is a calm 1-tile gap kept as floor
    #    (already floor; the void is *positive space* -- we just ensure pos is floor).
    for c in placed:
        cx, cy = _int(c.pos)
        if 0 <= cx < w and 0 <= cy < h:
            tiles[cy][cx] = FLOOR

    # 4) entrance + stairs. Entrance = the facilitator (highest flow); a player enters
    #    where the world's traffic concentrates. Stairs = the deepest strong center
    #    (most-central) -- you descend toward the core, consistent with depth=centrality.
    entrance_c = max(placed, key=lambda c: (c.flow, -ord(c.id[0]) if c.id else 0, c.id))
    stairs_c = max(placed, key=lambda c: (c.intensity, c.id))
    if stairs_c.id == entrance_c.id and len(placed) > 1:
        stairs_c = max((c for c in placed if c.id != entrance_c.id),
                       key=lambda c: (c.intensity, c.id))
    player_start = _int(entrance_c.pos)
    stairs = _int(stairs_c.pos)

    # 5) HARD INVARIANT: flood-fill from the entrance must reach everything walkable;
    #    repair any stranded floor by carving a straight line to the nearest reached tile.
    for _ in range(len(placed) + 4):
        reached = _reachable(tiles, player_start, w, h)
        stranded = [(x, y) for y in range(h) for x in range(w)
                    if tiles[y][x] != WALL and (x, y) not in reached]
        if not stranded:
            break
        # connect the nearest stranded tile to the nearest reached tile
        sx, sy = min(stranded)  # deterministic
        target = min(reached, key=lambda r: abs(r[0] - sx) + abs(r[1] - sy))
        _corridor(tiles, (sx, sy), target, w, h, width=1)
    else:
        # exhausted repairs -- should never happen, but never ship a broken level
        reached = _reachable(tiles, player_start, w, h)
        if any(tiles[y][x] != WALL and (x, y) not in reached
               for y in range(h) for x in range(w)):
            raise RuntimeError("carve failed to connect the level")

    tiles[stairs[1]][stairs[0]] = STAIRS
    return Level(w=w, h=h, tiles=tiles, rooms=[],
                 player_start=player_start, stairs=stairs)
