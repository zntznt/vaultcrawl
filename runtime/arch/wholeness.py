"""Wholeness — Alexander's 15 properties of living structure, operationalized
(ARCHITECTURE_SPEC.md §4).

Each property is a function `plan -> float in [0,1] | None` (None = not measurable for this
plan, e.g. no geometry yet). `wholeness(plan)` is the weighted average over the measurable
terms. It is the objective the growth algorithm maximizes (§5) AND a regression metric on
generated maps (§11). Pure, deterministic, stdlib only.

This is a *principled v1* meant to rank a living plan above a dead one and respond
monotonically to each property — to be tuned against *seen* maps in Phase 5, not before.
"""
from __future__ import annotations

import math

_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _gauss(x, mu, sigma):
    return math.exp(-((x - mu) ** 2) / (2.0 * sigma * sigma))


# ---- geometry helpers (on a footprint = set of (x,y)) ---------------------- #

def _perimeter(fp: set) -> int:
    return sum(1 for c in fp for d in _ORTH if (c[0] + d[0], c[1] + d[1]) not in fp)


def _compactness(fp: set) -> float:
    """Isoperimetric compactness in [0,1]: a disk -> ~1, a thin sliver -> ~0."""
    a = len(fp)
    if a <= 1:
        return 1.0 if a == 1 else 0.0
    p = _perimeter(fp)
    if p == 0:
        return 1.0
    return min(1.0, 4.0 * math.pi * a / (p * p))


def _symmetric(fp: set) -> bool:
    if not fp:
        return False
    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    vert = all((x1 + x0 - x, y) in fp for (x, y) in fp)      # mirror about vertical axis
    horiz = all((x, y1 + y0 - y) in fp for (x, y) in fp)     # mirror about horizontal axis
    return vert or horiz


def _shape_sig(fp: set):
    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    w, h = (max(xs) - min(xs) + 1), (max(ys) - min(ys) + 1)
    return (len(fp), w, h, round(_compactness(fp), 1))


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def _value(c):
    """A scalar 'size' for a center: its area if placed, else its intensity (scaled)."""
    return float(c.area) if c.footprint else c.intensity * 100.0


def _connected(adj) -> bool:
    nodes = list(adj)
    if not nodes:
        return True
    seen, stack = set(), [nodes[0]]
    while stack:
        v = stack.pop()
        if v in seen:
            continue
        seen.add(v)
        stack.extend(adj[v])
    return len(seen) == len(nodes)


# ---- the 15 properties ----------------------------------------------------- #

def levels_of_scale(plan):
    placed = plan.placed()
    if len(placed) < 2:
        return None
    sizes = sorted({c.area for c in placed}, reverse=True)
    if len(sizes) < 2:
        return 0.15                                   # one flat scale -> nearly dead
    ratios = [sizes[i] / sizes[i + 1] for i in range(len(sizes) - 1) if sizes[i + 1] > 0]
    smooth = sum(_gauss(r, 2.2, 1.3) for r in ratios) / len(ratios) if ratios else 0.0
    band = min(1.0, len(sizes) / 4.0)                 # reward several distinct scale-bands
    return smooth * band


def strong_centers(plan):
    placed = plan.placed()
    if not placed:
        return None
    areas = sorted(c.area for c in placed)
    med = areas[len(areas) // 2]
    majors = [c for c in placed if c.area >= med]
    if not majors:
        return None
    return sum(1.0 for c in majors if c.sub_centers) / len(majors)


def boundaries(plan):
    placed = plan.placed()
    if not placed:
        return None
    occ = {}
    for c in placed:
        for t in c.footprint:
            occ[t] = c.id
    scores = []
    for c in placed:
        per, walled = 0, 0
        for t in c.footprint:
            for d in _ORTH:
                nb = (t[0] + d[0], t[1] + d[1])
                if nb not in c.footprint:
                    per += 1
                    if nb not in occ:                 # edge faces empty/wall, not another room
                        walled += 1
        if per:
            scores.append(walled / per)
    return sum(scores) / len(scores) if scores else None


def alternating_repetition(plan):
    """Rhythm in SPACE: size alternates as you walk the connected map (big room ->
    small court -> big room), not along the growth order (which is size-sorted, so it
    can never alternate -- the old bug that pinned this to 0). We BFS the seam graph
    from the strongest center and score sign-flips of the size delta along that walk."""
    placed = plan.placed()
    if len(placed) < 3:
        return None
    adj = plan.adjacency()
    start = max(placed, key=lambda c: c.intensity).id
    seen, order, q = {start}, [start], [start]
    while q:                                            # deterministic BFS
        cur = q.pop(0)
        for nb in adj.get(cur, []):
            if nb not in seen and nb in plan.centers and plan.centers[nb].footprint:
                seen.add(nb)
                order.append(nb)
                q.append(nb)
    vals = [_value(plan.centers[c]) for c in order]
    if len(vals) < 3:
        return None
    deltas = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
    flips = sum(1 for i in range(len(deltas) - 1)
                if deltas[i] != 0 and deltas[i + 1] != 0 and (deltas[i] > 0) != (deltas[i + 1] > 0))
    return flips / (len(deltas) - 1) if len(deltas) > 1 else None


def positive_space(plan):
    placed = plan.placed()
    if not placed:
        return None
    total = sum(c.area for c in placed)
    good = sum(c.area for c in placed if _compactness(c.footprint) >= 0.45)
    return good / total if total else None


def good_shape(plan):
    placed = plan.placed()
    if not placed:
        return None
    return sum(_compactness(c.footprint) for c in placed) / len(placed)


def local_symmetries(plan):
    placed = plan.placed()
    if not placed:
        return None
    return sum(1.0 for c in placed if _symmetric(c.footprint)) / len(placed)


def deep_interlock(plan):
    multi = [c for c in plan.centers.values() if len(c.members) >= 2]
    if not multi:
        return None                                   # no overlap to realize -> not penalized
    adj = plan.adjacency()
    realized = 0
    for c in multi:
        if any(s.kind == "shared_court" and c.id in (s.a, s.b) for s in plan.seams):
            realized += 1
            continue
        comms = {plan.centers[n].home for n in adj.get(c.id, []) if n in plan.centers}
        if len({x for x in comms if x >= 0}) >= 2:    # spatially touches >=2 districts
            realized += 1
    return realized / len(multi)


def contrast(plan):
    if not plan.seams:
        return None
    scores = []
    for s in plan.seams:
        a, b = plan.centers.get(s.a), plan.centers.get(s.b)
        if not a or not b:
            continue
        va, vb = _value(a), _value(b)
        size_c = abs(va - vb) / (max(va, vb) + 1e-9)
        role_c = 1.0 if a.role != b.role else 0.0
        scores.append(min(1.0, 0.7 * size_c + 0.3 * role_c))
    return sum(scores) / len(scores) if scores else None


def gradients(plan):
    placed = [c for c in plan.placed() if c.centroid() is not None]
    if len(placed) < 3:
        return None
    core = max(placed, key=lambda c: c.intensity)
    ox, oy = core.centroid()
    dists, inten = [], []
    for c in placed:
        cx, cy = c.centroid()
        dists.append(math.hypot(cx - ox, cy - oy))
        inten.append(c.intensity)
    return max(0.0, -_pearson(dists, inten))          # intensity falls off with distance


def roughness(plan):
    placed = plan.placed()
    if len(placed) < 2:
        return None
    sigs = {}
    for c in placed:
        sig = _shape_sig(c.footprint)
        sigs[sig] = sigs.get(sig, 0) + 1
    most = max(sigs.values())
    return 1.0 - most / len(placed)                   # all identical (a grid) -> 0; varied -> high


def echoes(plan):
    placed = plan.placed()
    groups = {}
    for c in placed:
        groups.setdefault(c.home, []).append(c)
    sims = []
    for g in groups.values():
        if len(g) < 2:
            continue
        areas = [c.area for c in g]
        mean = sum(areas) / len(areas)
        if mean <= 0:
            continue
        cv = (sum((a - mean) ** 2 for a in areas) / len(areas)) ** 0.5 / mean
        sims.append(max(0.0, 1.0 - cv))               # low intra-district variance -> rhyme
    return sum(sims) / len(sims) if sims else None


def the_void(plan):
    placed = plan.placed()
    if len(placed) < 2:
        return None
    areas = sorted((c.area for c in placed), reverse=True)
    if areas[1] <= 0:
        return None
    ratio = areas[0] / areas[1]
    return _gauss(ratio, 3.0, 2.0)                     # one space ~3x the next = a clear great void


def simplicity_and_calm(plan):
    n = len(plan.centers)
    if n < 2:
        return None
    e = len({tuple(sorted((s.a, s.b))) for s in plan.seams if s.a != s.b})
    extra = e - (n - 1)                               # loops beyond a spanning tree
    target = 0.3 * n
    return _gauss(extra, target, max(1.0, 0.5 * n))   # some loops good; spaghetti & tree both worse


def not_separateness(plan):
    adj = plan.adjacency()
    if not adj:
        return None
    if not _connected(adj):
        return 0.0                                    # also a hard solvability constraint
    soft = sum(min(1.0, len(adj[c]) / 2.0) for c in adj) / len(adj)
    return 0.5 + 0.5 * soft                           # connected baseline, up with good joining


# ---- aggregate ------------------------------------------------------------- #

PROPERTIES = {
    "levels_of_scale": levels_of_scale,
    "strong_centers": strong_centers,
    "boundaries": boundaries,
    "alternating_repetition": alternating_repetition,
    "positive_space": positive_space,
    "good_shape": good_shape,
    "local_symmetries": local_symmetries,
    "deep_interlock": deep_interlock,
    "contrast": contrast,
    "gradients": gradients,
    "roughness": roughness,
    "echoes": echoes,
    "the_void": the_void,
    "simplicity_and_calm": simplicity_and_calm,
    "not_separateness": not_separateness,
}

WEIGHTS = {
    "levels_of_scale": 1.0, "strong_centers": 1.0, "boundaries": 0.7,
    "alternating_repetition": 0.5, "positive_space": 1.0, "good_shape": 0.8,
    "local_symmetries": 0.4, "deep_interlock": 1.0, "contrast": 0.6,
    "gradients": 0.8, "roughness": 0.5, "echoes": 0.5, "the_void": 0.7,
    "simplicity_and_calm": 0.8, "not_separateness": 1.2,
}


def wholeness(plan, weights=None, breakdown=False):
    """Weighted average of the measurable living-structure properties, in [0,1]."""
    weights = weights or WEIGHTS
    terms = {name: fn(plan) for name, fn in PROPERTIES.items()}
    num = den = 0.0
    for name, val in terms.items():
        if val is None:
            continue
        w = weights.get(name, 0.0)
        num += w * max(0.0, min(1.0, val))
        den += w
    score = num / den if den else 0.0
    return (score, terms) if breakdown else score
