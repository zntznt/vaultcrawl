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


def _area_of(intensity: float) -> int:
    return int(round(_AREA_MIN + (_AREA_MAX - _AREA_MIN) * (max(0.0, intensity) ** 1.6)))


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
    """Grow an organic blob of ~`area` cells from `seed`, staying compact with a little
    jitter (roughness), never touching another room (a 1-cell boundary is kept)."""
    sx, sy = seed
    if not _free((sx, sy), occupied, set(), _GAP):
        return None
    fp = {(sx, sy)}
    while len(fp) < area:
        cands = set()
        for (x, y) in fp:
            for dx, dy in _ORTH:
                c = (x + dx, y + dy)
                if c not in fp and _free(c, occupied, fp, _GAP):
                    cands.add(c)
        if not cands:
            break
        # prefer cells that keep the blob compact (near the seed); jitter for roughness
        ranked = sorted(cands, key=lambda c: (abs(c[0] - sx) + abs(c[1] - sy), rng.random()))
        fp.add(ranked[0])
    return fp if len(fp) >= max(1, int(area * 0.7)) else None


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
            d = rn + rc + _GAP + 1
            seeds.append((int(round(nx + ux * d)), int(round(ny + uy * d))))
    # fallback: spiral around the global core so a disconnected piece can still land
    cx, cy = (plan.centers[plan.growth_order[0]].pos if plan.growth_order
              and plan.centers[plan.growth_order[0]].footprint else (0, 0))
    for ring in range(2, 40, 3):
        for ux, uy in _ANGLES:
            seeds.append((int(round(cx + ux * ring * 3)), int(round(cy + uy * ring * 3))))
        if len(seeds) > 80:
            break
    return seeds


def grow(graph: dict, seed="arch") -> SitePlan:
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
