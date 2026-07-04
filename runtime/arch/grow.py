"""Growth-by-healing + semilattice connection (ARCHITECTURE_SPEC.md §5, §6).

`grow(graph, seed)` turns an abstract SitePlan (centers + interlock edges) into a *placed*
one: each center carved as an organic footprint, positioned strong-first where it most
increases wholeness (New Theory of Urban Design), then the links woven into a connected
**semilattice** — loops, gateways at district boundaries, shared courts for the overlapping
notes, and orphans hung as discoveries at their nearest inflection point.

Pure + deterministic (seeded). No game dependencies.
"""
from __future__ import annotations

import math
import random

from .model import Center, Seam, SitePlan, from_graph
from .wholeness import WEIGHTS, wholeness, _compactness

_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))
_ANGLES = [(math.cos(a), math.sin(a)) for a in (i * math.pi / 4 for i in range(8))]

# placement is judged on the GEOMETRY/field properties only; the seam-dependent
# properties are scored after §6 connects everything.
GROWTH_WEIGHTS = dict(WEIGHTS)
for _k in ("alternating_repetition", "deep_interlock", "contrast",
           "simplicity_and_calm", "not_separateness"):
    GROWTH_WEIGHTS[_k] = 0.0

_AREA_MIN, _AREA_MAX = 4, 64          # levels of scale: leaf nook .. the great void
_GAP = 1                              # one-cell wall between rooms (boundaries + positive space)
_SPRAWL = 1.0                          # world-scale factor set by grow(sprawl=...): areas
                                       # scale by it, separations by sqrt of it on top of
                                       # the bigger radii, so distance grows ~linearly


def _area_of(intensity: float) -> int:
    base = _AREA_MIN + (_AREA_MAX - _AREA_MIN) * (max(0.0, intensity) ** 1.6)
    return int(round(base * _SPRAWL))


def _radius(area: int) -> float:
    return math.sqrt(max(1, area) / math.pi)


def _free(cell, occupied, fp, margin):
    """A cell is free if neither it nor its margin-ring belongs to another room."""
    x, y = cell
    if cell in occupied or cell in fp:
        return False
    for dx in range(-margin, margin + 1):
        for dy in range(-margin, margin + 1):
            if (x + dx, y + dy) in occupied:
                return False
    return True


def _grow_blob(seed, area, occupied, rng):
    """A building's footprint is a RECTANGLE, not an organic blob. Architecture is
    rectilinear, ASCII reads a rectangle instantly, and a rectangular footprint
    partitions into clean orthogonal wings (settle._partition_complex) instead of a
    ragged mess. Grow the largest clear rectangle around `seed` up to ~`area` cells,
    with an aspect ratio that varies by seed (a hall, a tower, a square) so buildings
    still differ. The wild between stays organic; only the built figure is squared.

    Keeps the same contract as before: never touches another footprint's margin
    (`_free` with `_GAP`), returns None if it can't reach ~70% of the target area."""
    sx, sy = seed
    if not _free((sx, sy), occupied, set(), _GAP):
        return None
    # pick a target aspect: mostly boxy, sometimes a long hall or a tower
    ar = rng.choice((1.0, 1.0, 1.3, 1.6, 0.75, 0.6))
    th = max(2, int(round(math.sqrt(area / ar))))
    tw = max(2, int(round(area / th)))

    def _rect_free(x0, y0, x1, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if not _free((x, y), occupied, set(), _GAP):
                    return False
        return True

    # grow outward from the seed one edge at a time, keeping the whole rect clear;
    # stop an edge when it would collide, so the rectangle fills the local clearing
    x0 = x1 = sx
    y0 = y1 = sy
    grew = True
    while grew and (x1 - x0 + 1) * (y1 - y0 + 1) < area:
        grew = False
        # try each of the four edges, shorter side first so it stays compact
        edges = sorted(
            (("L", x0 - 1, y0, x0 - 1, y1), ("R", x1 + 1, y0, x1 + 1, y1),
             ("T", x0, y0 - 1, x1, y0 - 1), ("B", x0, y1 + 1, x1, y1 + 1)),
            key=lambda e: (x1 - x0) if e[0] in ("T", "B") else (y1 - y0))
        for side, ex0, ey0, ex1, ey1 in edges:
            w_now, h_now = x1 - x0 + 1, y1 - y0 + 1
            # respect the target shape: don't overgrow one dimension
            if side in ("L", "R") and w_now >= tw:
                continue
            if side in ("T", "B") and h_now >= th:
                continue
            if _rect_free(ex0, ey0, ex1, ey1):
                if side == "L":
                    x0 -= 1
                elif side == "R":
                    x1 += 1
                elif side == "T":
                    y0 -= 1
                else:
                    y1 += 1
                grew = True
                break
    fp = {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)}
    return fp if len(fp) >= max(4, int(area * 0.5)) else None


def _centroid(fp):
    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _candidate_seeds(plan, c, link_adj, rng):
    """Anchor points to try: rings around already-placed strong-link neighbours (deep
    interlock), plus a fallback ring around the core/origin."""
    rc = _radius(_area_of(c.intensity))
    seeds = []
    placed_nbrs = [plan.centers[n] for n in link_adj.get(c.id, [])
                   if n in plan.centers and plan.centers[n].footprint]
    placed_nbrs.sort(key=lambda n: -n.intensity)
    for nb in placed_nbrs[:4]:
        nx, ny = nb.pos
        rn = _radius(nb.area)
        for ux, uy in _ANGLES:
            d = (rn + rc + _GAP + 1) * math.sqrt(_SPRAWL)
            seeds.append((int(round(nx + ux * d)), int(round(ny + uy * d))))
    # fallback: spiral around the global core so a disconnected piece can still land
    cx, cy = (plan.centers[plan.growth_order[0]].pos if plan.growth_order
              and plan.centers[plan.growth_order[0]].footprint else (0, 0))
    for ring in range(2, 40, 3):
        for ux, uy in _ANGLES:
            step = ring * 3 * math.sqrt(_SPRAWL)
            seeds.append((int(round(cx + ux * step)), int(round(cy + uy * step))))
        if len(seeds) > 80:
            break
    return seeds


def grow(graph: dict, seed="arch", sprawl: float = 1.0) -> SitePlan:
    global _SPRAWL
    _SPRAWL = max(1.0, float(sprawl))
    plan = from_graph(graph)
    rng = random.Random(f"{seed}:grow")

    link_adj = plan.adjacency()                          # from the interlock edges

    order = sorted(plan.centers.values(), key=lambda c: (-c.intensity, c.id))
    plan.growth_order = [c.id for c in order]
    occupied = set()

    for i, c in enumerate(order):
        area = _area_of(c.intensity)
        if i == 0:
            fp = _grow_blob((0, 0), area, occupied, rng)  # the core / great void at the centre
            best = (fp, _centroid(fp)) if fp else None
        else:
            best, best_score = None, -1.0
            for s in _candidate_seeds(plan, c, link_adj, rng):
                fp = _grow_blob(s, area, occupied, rng)
                if not fp:
                    continue
                c.footprint, c.pos = fp, _centroid(fp)    # tentative
                score = wholeness(plan, weights=GROWTH_WEIGHTS)
                # small nudge toward placed strong-link neighbours (deep interlock, early)
                near = _nearness(plan, c, link_adj)
                score += 0.08 * near
                if score > best_score:
                    best, best_score = (fp, c.pos), score
            c.footprint, c.pos = set(), None              # revert before committing
        if best is None:                                  # last resort: far spiral
            best = _spiral_place(c, area, occupied, rng)
        c.footprint, c.pos = best
        occupied |= c.footprint
        # intensify (§5): the major centres get a focal sub-centre; the greatest is the Void
        if c.area >= _AREA_MAX * 0.35:
            c.sub_centers = [Center(id=c.id + ".focal")]
    order[0].sub_centers = [Center(id=order[0].id + ".void")]   # the great void's calm centre

    _explode(plan)
    _normalize(plan)
    _connect_semilattice(plan, link_adj)
    return plan


def _nearness(plan, c, link_adj):
    nbrs = [plan.centers[n] for n in link_adj.get(c.id, [])
            if n in plan.centers and plan.centers[n].footprint and n != c.id]
    if not nbrs or c.pos is None:
        return 0.0
    d = sum(math.hypot(c.pos[0] - n.pos[0], c.pos[1] - n.pos[1]) for n in nbrs) / len(nbrs)
    return 1.0 / (1.0 + d / 10.0)


def _spiral_place(c, area, occupied, rng):
    for r in range(5, 400, 2):
        for ux, uy in _ANGLES:
            s = (int(round(ux * r)), int(round(uy * r)))
            fp = _grow_blob(s, area, occupied, rng)
            if fp:
                return (fp, _centroid(fp))
    fp = {(rng.randint(500, 600), rng.randint(500, 600))}   # never happens in practice
    return (fp, _centroid(fp))


# how tightly a district's own buildings are pulled toward their local center
# (0 = leave as grown, spread out; 0.55 = gathered into a compact settlement).
_GATHER = 0.55


def _explode(plan):
    """Sprawl AND gather: push each community RADIALLY OUT from the world centroid
    so districts separate (real wilderness between them), while pulling each
    community's own buildings IN toward their local center so a settlement is
    COMPACT — dense towns, sparse wild. Buildings never overlap (gather stops at a
    one-cell gap), so the carve/connectivity stay valid."""
    placed = plan.placed()
    if not placed:
        return
    gx = sum(c.pos[0] for c in placed) / len(placed)
    gy = sum(c.pos[1] for c in placed) / len(placed)
    groups: dict = {}
    for c in placed:
        groups.setdefault(c.members[0] if c.members else -1, []).append(c)
    # ONE occupied set across all districts: a per-district set is blind to other
    # districts, so at low sprawl two districts' buildings gathered onto each other
    # (all overlaps were cross-district). Shared, no building can land on any other.
    occupied: set = set()
    for cs in groups.values():
        cx = sum(c.pos[0] for c in cs) / len(cs)
        cy = sum(c.pos[1] for c in cs) / len(cs)
        sep = (_SPRAWL - 1.0)   # 0 when sprawl==1
        # gather buildings inward toward their local center, then separate districts
        for c in sorted(cs, key=lambda c: (c.pos[0] - cx) ** 2 + (c.pos[1] - cy) ** 2):
            fp0 = c.footprint

            def _clear(dx, dy):
                moved = {(x + dx, y + dy) for (x, y) in fp0}
                return not (moved & occupied) and not _touch(moved, occupied)

            # target offset = outward district-separation + inward gather. Interpolate
            # from the full target back toward the grown position and take the FIRST
            # clear offset.
            tgt_ox = int(round((cx - gx) * sep + (cx - c.pos[0]) * _GATHER))
            tgt_oy = int(round((cy - gy) * sep + (cy - c.pos[1]) * _GATHER))
            steps = max(abs(tgt_ox), abs(tgt_oy), 1)
            ox = oy = None
            for i in range(steps, -1, -1):
                tx = int(round(tgt_ox * i / steps))
                ty = int(round(tgt_oy * i / steps))
                if _clear(tx, ty):
                    ox, oy = tx, ty
                    break
            # even the grown spot may be taken (a shared occupied set spans districts):
            # spiral outward from it for the nearest empty ground. Guaranteed to place.
            if ox is None:
                for radius in range(1, 400):
                    found = False
                    for ux, uy in _ANGLES:
                        tx = int(round(ux * radius))
                        ty = int(round(uy * radius))
                        if _clear(tx, ty):
                            ox, oy, found = tx, ty, True
                            break
                    if found:
                        break
                if ox is None:
                    ox = oy = 0     # last resort; _ensure_connected will still repair
            c.footprint = {(x + ox, y + oy) for (x, y) in fp0}
            c.pos = (c.pos[0] + ox, c.pos[1] + oy)
            occupied |= c.footprint


def _touch(cells, occupied):
    """True if any cell in `cells` is orthogonally adjacent to an occupied cell
    (so we keep a one-tile wall gap between gathered buildings)."""
    for (x, y) in cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) in occupied:
                return True
    return False


def _normalize(plan):
    placed = plan.placed()
    if not placed:
        return
    minx = min(p[0] for c in placed for p in c.footprint)
    miny = min(p[1] for c in placed for p in c.footprint)
    for c in placed:
        c.footprint = {(x - minx + 1, y - miny + 1) for (x, y) in c.footprint}
        c.pos = (c.pos[0] - minx + 1, c.pos[1] - miny + 1)
    maxx = max(p[0] for c in placed for p in c.footprint)
    maxy = max(p[1] for c in placed for p in c.footprint)
    plan.bounds = (maxx + 2, maxy + 2)


# --------------------------------------------------------------------------- #
# §6  Semilattice connection — NOT a tree
# --------------------------------------------------------------------------- #

def _component(adj, start, seen):
    comp, stack = set(), [start]
    while stack:
        v = stack.pop()
        if v in seen or v in comp:
            continue
        comp.add(v)
        stack.extend(adj.get(v, []))
    return comp


def _nearest(plan, cid, pool):
    p = plan.centers[cid].pos
    best, bd = None, 1e18
    for o in pool:
        q = plan.centers[o].pos
        if q is None or o == cid:
            continue
        d = math.hypot(p[0] - q[0], p[1] - q[1])
        if d < bd:
            best, bd = o, d
    return best


def _connect_semilattice(plan, link_adj):
    C = plan.centers
    # (a) the real links are already seams (with cycles). Classify their kind:
    for s in plan.seams:
        a, b = C.get(s.a), C.get(s.b)
        if not a or not b:
            continue
        if len(a.members) >= 2 or len(b.members) >= 2:
            s.kind = "shared_court"                       # P6 — the overlap made spatial
        elif a.home != b.home and a.home >= 0 and b.home >= 0:
            s.kind = "gateway"                            # P8 — crossing a district boundary

    # (b) discoveries: orphans (no links) hang off their nearest inflection point (P12)
    placed = [c.id for c in plan.placed()]
    linked = {s.a for s in plan.seams} | {s.b for s in plan.seams}
    for cid in placed:
        if cid in linked:
            continue
        # inflection point: the nearest *bridge/hub*; fall back to nearest placed center
        bridges = [o for o in placed if o != cid and C[o].role in ("bridge", "hub")]
        anchor = _nearest(plan, cid, bridges or [o for o in placed if o != cid])
        if anchor:
            plan.seams.append(Seam(cid, anchor, kind="path", strength=1.0))
            C[cid].role = "discovery"

    # (c) Not-Separateness (hard): join any remaining components at their nearest centers
    adj = plan.adjacency()
    seen, comps = set(), []
    for cid in plan.centers:
        if cid not in seen:
            comp = _component(adj, cid, seen)
            seen |= comp
            comps.append(comp)
    comps.sort(key=len, reverse=True)
    main = comps[0] if comps else set()
    for comp in comps[1:]:
        a = min(comp)                                     # deterministic representative
        b = _nearest(plan, a, main)
        if b:
            plan.seams.append(Seam(a, b, kind="path", strength=1.0))
            main |= comp
    return plan
