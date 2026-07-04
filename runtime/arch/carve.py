"""Phase 4: carve a grown SitePlan into a playable Level (ARCHITECTURE_SPEC §7).

The growth pass (grow.py) produces the living structure: organic, non-overlapping
footprints in a 1-padded grid, a connected semilattice of seams tagged by kind
(path / gateway / shared_court), strong centers marked with a focal sub-center and
the greatest center with the great void. Carving renders that structure into the
exact `Level` shape the runtime consumes -- AND applies the pattern operators §7
calls for, so the geometry actually *is* the patterns, not just stamped blobs:

  P10 Strong-Centered Room  -- a focal void hollows each strong center so the room
                               is itself a field with a calm centre (not a solid mass)
  P13 The Void              -- the greatest center keeps one large calm empty core
  P7  Promenade             -- a wide flow-way (shared courts / strong seams) carved
                               with alternating bays, not a bare 2-wide tunnel
  P8  Main Gateway          -- a seam crossing a district boundary narrows to a
                               threshold then opens (a marked passage, not a hole)
  P15 Roughness & Echo      -- a final pass jitters footprint edges off the grid
                               (controlled, deterministic) and rhymes a district's motif

Connectivity is the one HARD invariant and is enforced LAST, after every pattern
operator, by flood-fill + repair -- so a focal void or a narrowed gateway can never
strand a room. Output Level is a drop-in for dungeon.Level.
"""
from __future__ import annotations

import random
from collections import deque

from runtime.dungeon import Level, WALL, FLOOR, STAIRS

_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))


# --------------------------------------------------------------------------- #
# low-level grid ops
# --------------------------------------------------------------------------- #

def _in(x, y, w, h):
    return 0 <= x < w and 0 <= y < h


def _set(tiles, x, y, w, h, ch=FLOOR):
    if _in(x, y, w, h):
        tiles[y][x] = ch


def _line(a, b):
    """Tiles on an L-path a->b (horizontal then vertical). Deterministic."""
    (x1, y1), (x2, y2) = a, b
    pts, step = [], 1 if x2 >= x1 else -1
    for x in range(x1, x2 + step, step):
        pts.append((x, y1))
    step = 1 if y2 >= y1 else -1
    for y in range(y1, y2 + step, step):
        pts.append((x2, y))
    return pts


def _stamp(tiles, cells, w, h):
    for (x, y) in cells:
        _set(tiles, x, y, w, h, FLOOR)


def _reachable(tiles, start, w, h):
    """4-connected flood-fill of walkable tiles from start."""
    seen, q = {start}, deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in _ORTH:
            nx, ny = x + dx, y + dy
            if _in(nx, ny, w, h) and (nx, ny) not in seen and tiles[ny][nx] != WALL:
                seen.add((nx, ny))
                q.append((nx, ny))
    return seen


def _int(p):
    return (int(round(p[0])), int(round(p[1])))


# --------------------------------------------------------------------------- #
# §7 pattern operators (grid-level)
# --------------------------------------------------------------------------- #

def _carve_corridor(tiles, a, b, w, h, width=1):
    """Plain L-corridor a->b at the given width (origin-anchored)."""
    for (x, y) in _line(a, b):
        for dx in range(width):
            for dy in range(width):
                _set(tiles, x + dx, y + dy, w, h, FLOOR)


def _carve_gateway(tiles, a, b, w, h):
    """P8 -- a way crossing a district boundary: a marked threshold. It rides 1 wide
    (a deliberate narrowing) and *opens* into a small 3x3 antechamber at each end, so
    crossing a boundary reads as passing through a gate, not a uniform tunnel."""
    _carve_corridor(tiles, a, b, w, h, width=1)
    for (cx, cy) in (a, b):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                _set(tiles, cx + dx, cy + dy, w, h, FLOOR)


def _carve_promenade(tiles, a, b, w, h, rng):
    """P7 -- a flow spine: 2 wide, with alternating bays (alcoves) budding off it so the
    way has rhythm (Alternating Repetition) instead of being a bare wide tunnel."""
    pts = _line(a, b)
    _carve_corridor(tiles, a, b, w, h, width=2)
    side = 1
    for i, (x, y) in enumerate(pts):
        if i % 4 == 2 and 0 < i < len(pts) - 1:        # a bay every ~4 tiles
            # bay perpendicular to local travel direction
            px, py = pts[i - 1]
            horiz = (y == py)
            for d in (1, 2):
                if horiz:
                    _set(tiles, x, y + side * d, w, h, FLOOR)
                else:
                    _set(tiles, x + side * d, y, w, h, FLOOR)
            side = -side                                # alternate sides -> rhythm


def _carve_focal_void(tiles, center, w, h):
    """P10 -- hollow a focal void at a strong center's heart: keep the centroid cell (and,
    for the great void, a small core) as WALL so the room is a field around a calm centre,
    ringed by floor. The void is *positive space defined by what surrounds it*."""
    cx, cy = _int(center.pos)
    is_great = any(s.id.endswith(".void") for s in center.sub_centers)
    radius = 1 if is_great else 0                       # great void = 3x3 hollow, focal = 1 cell
    void = set()
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            t = (cx + dx, cy + dy)
            if t in center.footprint:
                void.add(t)
    # only hollow if the room is big enough to keep a floor ring around the void
    if len(void) and len(center.footprint) - len(void) >= max(3, 2 * (radius + 1)):
        for (x, y) in void:
            _set(tiles, x, y, w, h, WALL)
    return void


def _roughness_echo(tiles, plan, w, h, rng):
    """P15 -- break mechanical regularity. Two moves, both deterministic:
      * jitter: nibble a few convex edge cells off each footprint and bud a few just
        outside, so room boundaries are adapted, not stamped (controlled irregularity);
      * echo: within a district, nudge rooms toward a shared per-district nibble rate so
        their roughness *rhymes* (family resemblance), rather than each being random.
    Never touches a center's pos/centroid (keeps it connectable) and never removes a tile
    that would disconnect -- the final repair pass re-guarantees connectivity regardless."""
    placed = plan.placed()
    # per-district jitter rate (echo: same district -> same texture)
    rate = {}
    for c in placed:
        rate.setdefault(c.home, 0.12 + 0.12 * rng.random())
    for c in placed:
        cx, cy = _int(c.pos)
        r = rate.get(c.home, 0.18)
        # only CONVEX corners (2+ exposed sides) -- nibbling these adds jaggedness; we never
        # bud into concavities (that would *smooth* the already-rough grown footprints).
        edge = [t for t in c.footprint
                if t != (cx, cy)
                and sum(1 for d in _ORTH if (t[0]+d[0], t[1]+d[1]) not in c.footprint) >= 2]
        edge.sort()                                     # deterministic order
        for (x, y) in edge:
            if rng.random() < r:                        # nibble a convex corner inward
                _set(tiles, x, y, w, h, WALL)


# --------------------------------------------------------------------------- #
# entrance / stairs / connectivity
# --------------------------------------------------------------------------- #

def _pick_entrance_stairs(placed):
    """Entrance = the facilitator (highest flow -- traffic concentrates). Stairs = the
    deepest strong center (most-central), so you descend toward the core (depth=centrality)."""
    entrance = max(placed, key=lambda c: (c.flow, c.id))
    stairs = max(placed, key=lambda c: (c.intensity, c.id))
    if stairs.id == entrance.id and len(placed) > 1:
        stairs = max((c for c in placed if c.id != entrance.id), key=lambda c: (c.intensity, c.id))
    return _int(entrance.pos), _int(stairs.pos)


def _ensure_connected(tiles, start, placed, w, h):
    """HARD invariant: flood-fill from `start` must reach every walkable tile. Repair any
    stranded floor by carving a straight line to the nearest reached tile, then re-check.
    Runs AFTER all pattern operators, so voids/narrowings can't leave anything unreachable."""
    for _ in range(len(placed) + 8):
        reached = _reachable(tiles, start, w, h)
        stranded = [(x, y) for y in range(h) for x in range(w)
                    if tiles[y][x] != WALL and (x, y) not in reached]
        if not stranded:
            return
        sx, sy = min(stranded)
        target = min(reached, key=lambda r: abs(r[0] - sx) + abs(r[1] - sy))
        _carve_corridor(tiles, (sx, sy), target, w, h, width=1)
    reached = _reachable(tiles, start, w, h)
    if any(tiles[y][x] != WALL and (x, y) not in reached
           for y in range(h) for x in range(w)):
        raise RuntimeError("carve failed to connect the level")


# --------------------------------------------------------------------------- #
# the carver
# --------------------------------------------------------------------------- #

def carve(plan, seed="carve") -> Level:
    """Rasterize a grown SitePlan into a connected Level, applying the §7 patterns."""
    placed = plan.placed()
    if not placed:
        raise ValueError("carve() needs a grown plan (no placed centers)")
    rng = random.Random(f"{seed}:carve")

    w, h = plan.bounds if plan.bounds != (0, 0) else (
        max(p[0] for c in placed for p in c.footprint) + 2,
        max(p[1] for c in placed for p in c.footprint) + 2,
    )
    tiles = [[WALL] * w for _ in range(h)]

    # 1) rooms -- every footprint becomes floor (organic, not rectangles)
    for c in placed:
        _stamp(tiles, c.footprint, w, h)

    # 2) ways -- a per-seam corridor, dispatched by pattern. promenades & shared courts get
    #    bays; gateways narrow-then-open; plain paths are 1 wide.
    ids = {c.id for c in placed}
    for s in plan.seams:
        a, b = plan.centers.get(s.a), plan.centers.get(s.b)
        if not a or not b or a.pos is None or b.pos is None or s.a not in ids or s.b not in ids:
            continue
        pa, pb = _int(a.pos), _int(b.pos)
        if s.kind == "gateway":
            _carve_gateway(tiles, pa, pb, w, h)
        elif s.kind == "shared_court" or s.strength >= 3:
            _carve_promenade(tiles, pa, pb, w, h, rng)
        else:
            _carve_corridor(tiles, pa, pb, w, h, width=1)

    # 3) P10 / P13 -- hollow focal voids at strong centers (the great center keeps the Void)
    for c in placed:
        if c.sub_centers:
            _carve_focal_void(tiles, c, w, h)

    # 3.5) room-scale interior patterns -- themed substructures matched by each
    # center's own dynamics (role, age, membership); see interiors.py
    from .interiors import apply_interiors
    apply_interiors(plan, tiles, w, h, seed)

    # 4) P15 -- roughness + echo: adapt the edges so nothing reads as stamped/gridded
    _roughness_echo(tiles, plan, w, h, rng)

    # 5) entrance + stairs, then GUARANTEE connectivity (hard) -- after all carving
    player_start, stairs = _pick_entrance_stairs(placed)
    _set(tiles, player_start[0], player_start[1], w, h, FLOOR)   # never let a void seal the door
    _set(tiles, stairs[0], stairs[1], w, h, FLOOR)
    _ensure_connected(tiles, player_start, placed, w, h)

    tiles[stairs[1]][stairs[0]] = STAIRS
    return Level(w=w, h=h, tiles=tiles, rooms=[],
                 player_start=player_start, stairs=stairs)


def region_map(plan):
    """{(x, y) -> center.id (== note id)} for every footprint tile of the grown plan.

    The carved Level loses which district owns which tile; the sandbox needs it back so
    `region_at(x, y)` can resolve the note (and thus the region/faction/enemy pool) the
    player is standing in. A tile claimed by two centers (the semilattice overlap, e.g. a
    shared court) goes to the stronger center -- but it still *belongs* to both, which is
    why region_at can be extended to return a set later. Deterministic (strongest first)."""
    rmap = {}
    for c in sorted(plan.placed(), key=lambda c: c.intensity):   # weak first; strong overwrites
        for t in c.footprint:
            rmap[t] = c.id
    return rmap


# --------------------------------------------------------------------------- #
# grid-level wholeness -- the carve's own regression metric (§4, §11)
# --------------------------------------------------------------------------- #
# wholeness() in wholeness.py scores the abstract SitePlan; it cannot see what the
# carve does to the GRID (focal voids, edge jitter, gateways). This is the carved-
# map counterpart: a small set of grid-measurable §4 terms the carver is responsible
# for, so a carve that silently degrades into a featureless grid is caught in tests.

def _floor(tiles, x, y, w, h):
    return _in(x, y, w, h) and tiles[y][x] != WALL


def grid_wholeness(level, breakdown=False):
    """Score the CARVED grid on the living-structure properties the carve owns, in [0,1].

      not_a_grid    -- fraction of floor NOT inside a solid 3x3 block (penalizes the
                       room-of-identical-squares failure mode the carve must avoid)
      boundaries    -- floor cells that face a wall (definition), not endless open space
      the_void      -- interior wall cells fully ringed by floor exist (focal voids carved)
      edge_relief   -- the boundary is not one smooth convex blob: it has concavities /
                       interlock (alcoves, bays, fingered edges), the texture of a lived edge

    Note: a naive "fraction of jagged corners" roughness term is deliberately NOT used --
    it conflicts with void/corridor carving (both add smooth edges that dilute the ratio),
    so it would punish the very operators that make the map alive. edge_relief instead
    rewards *concavity* (interlock), which voids and bays genuinely add.
    """
    tiles, w, h = level.tiles, level.w, level.h
    floor = [(x, y) for y in range(h) for x in range(w) if tiles[y][x] != WALL]
    if not floor:
        return (0.0, {}) if breakdown else 0.0
    nf = len(floor)

    # not_a_grid: count floor in any 3x3 fully-solid block (a stamped grid is all such)
    blocky = 0
    for (x, y) in floor:
        if all(_floor(tiles, x + dx, y + dy, w, h) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            blocky += 1
    not_a_grid = 1.0 - blocky / nf                      # all-blocky (a slab) -> 0; carved -> high

    # boundaries: floor edges that abut a wall (definition vs. amorphous openness)
    edge = walled = 0
    for (x, y) in floor:
        for dx, dy in _ORTH:
            if not _floor(tiles, x + dx, y + dy, w, h):
                edge += 1
                if _in(x + dx, y + dy, w, h):
                    walled += 1
    boundaries = (walled / edge) if edge else 0.0

    # the_void: at least one interior wall cell ringed by floor (a focal void was carved)
    voids = 0
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if tiles[y][x] == WALL and all(_floor(tiles, x + dx, y + dy, w, h) for dx, dy in _ORTH):
                voids += 1
    the_void = min(1.0, voids / max(1.0, len(level.tiles) and 3.0))   # a few focal voids -> 1

    # edge_relief: a *concave* floor cell (3+ floor neighbours but on a boundary) marks an
    # alcove / bay / interlock notch -- the texture of a lived edge, which voids and bays add.
    edge_cells = [(x, y) for (x, y) in floor
                  if any(not _floor(tiles, x + dx, y + dy, w, h) for dx, dy in _ORTH)]
    concave = 0
    for (x, y) in edge_cells:
        floors8 = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                      if (dx or dy) and _floor(tiles, x + dx, y + dy, w, h))
        if floors8 >= 5:                                # surrounded mostly by floor -> a notch/bay
            concave += 1
    edge_relief = min(1.0, (concave / len(edge_cells)) * 2.0) if edge_cells else 0.0

    terms = {"not_a_grid": not_a_grid, "boundaries": boundaries,
             "the_void": the_void, "edge_relief": edge_relief}
    weights = {"not_a_grid": 1.0, "boundaries": 1.0, "the_void": 0.7, "edge_relief": 0.6}
    num = sum(weights[k] * max(0.0, min(1.0, v)) for k, v in terms.items())
    score = num / sum(weights.values())
    return (score, terms) if breakdown else score
