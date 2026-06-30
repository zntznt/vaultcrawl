"""Phase 2: the wholeness scorer ranks a LIVING plan above a DEAD one, responds
monotonically to individual properties, and every term stays in [0,1].

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_wholeness
"""
import json

from runtime.arch import wholeness, from_graph, PROPERTIES
from runtime.arch.model import Center, Seam, SitePlan


def rect(x0, y0, w, h):
    return {(x0 + i, y0 + j) for i in range(w) for j in range(h)}


def dead_plan():
    """Six identical rooms strung on a chain (a TREE). Uniform, sub-centerless, no overlap."""
    centers = {}
    for i in range(6):
        c = Center(id=f"d{i}", intensity=0.5, members=(0,), role="cluster")
        c.footprint = rect(i * 5, 0, 3, 3)
        c.pos = (i * 5 + 1, 1)
        centers[c.id] = c
    seams = [Seam(f"d{i}", f"d{i+1}") for i in range(5)]          # chain == tree
    return SitePlan(centers=centers, seams=seams,
                    growth_order=[f"d{i}" for i in range(6)])


def living_plan():
    """A field of centers: a size ladder, a great void with a focal center, majors with
    sub-centers, a shared court spanning two districts, an intensity gradient, modest loops."""
    spec = [
        # id   x   y   w  h  intensity members      role
        ("L0",  0,  0, 6, 6, 1.00, (0,),   "hub"),       # the great void
        ("L1", 10,  0, 4, 4, 0.70, (0,),   "cluster"),
        ("L2", 10,  7, 4, 3, 0.55, (0, 1), "bridge"),    # SHARED COURT (members 0 & 1)
        ("L3", 17,  0, 3, 3, 0.40, (1,),   "cluster"),
        ("L4", 17,  5, 3, 2, 0.30, (1,),   "cluster"),
        ("L5", 22,  0, 2, 2, 0.20, (1,),   "leaf"),
        ("L6", 22,  4, 2, 1, 0.10, (1,),   "leaf"),
    ]
    centers = {}
    for cid, x, y, w, h, inten, members, role in spec:
        c = Center(id=cid, intensity=inten, members=members, role=role)
        c.footprint = rect(x, y, w, h)
        c.pos = (x + w / 2.0, y + h / 2.0)
        centers[cid] = c
    # strong centers: the majors (area >= median) each get a focal sub-center
    areas = sorted(c.area for c in centers.values())
    med = areas[len(areas) // 2]
    for c in centers.values():
        if c.area >= med:
            c.sub_centers = [Center(id=c.id + ".focal")]
    seams = [
        Seam("L0", "L1"), Seam("L1", "L2", kind="shared_court"), Seam("L2", "L3"),
        Seam("L3", "L4"), Seam("L4", "L5"), Seam("L5", "L6"),
        Seam("L0", "L2"), Seam("L1", "L3"),                       # loops -> a SEMILATTICE
    ]
    return SitePlan(centers=centers, seams=seams,
                    growth_order=[s[0] for s in spec])


def main():
    dead, living = dead_plan(), living_plan()
    wd, td = wholeness(dead, breakdown=True)
    wl, tl = wholeness(living, breakdown=True)

    # --- every term stays in range (or None) ---
    for name, fn in PROPERTIES.items():
        for plan in (dead, living):
            v = fn(plan)
            assert v is None or 0.0 <= v <= 1.0, f"{name} out of range: {v}"

    # --- the living plan is decisively more whole ---
    assert wl > wd + 0.12, f"living ({wl:.3f}) must clearly beat dead ({wd:.3f})"
    # the properties that should separate them, do:
    assert tl["levels_of_scale"] > td["levels_of_scale"], "ladder of scales beats uniformity"
    assert tl["strong_centers"] > td["strong_centers"], "focal sub-centers beat bare rooms"
    assert tl["contrast"] > td["contrast"], "differentiated neighbours beat clones"
    assert tl["roughness"] > td["roughness"], "varied shapes beat a grid"
    assert (tl["deep_interlock"] or 0) >= 0.99, "the shared court realizes the overlap"
    assert td["deep_interlock"] is None, "a tree has no overlap to realize"
    assert tl["gradients"] > 0.3, "intensity falls off with distance (a gradient)"

    # --- monotonic responses ---
    from runtime.arch.wholeness import strong_centers, deep_interlock, not_separateness, \
        levels_of_scale, roughness
    # 1) adding sub-centers raises Strong Centers
    p = dead_plan()
    before = strong_centers(p)
    for c in p.centers.values():
        c.sub_centers = [Center(id="f")]
    assert strong_centers(p) > before, "adding focal sub-centers must raise strong_centers"
    # 2) flattening to one size lowers Levels of Scale and Roughness
    p = living_plan()
    los0, rgh0 = levels_of_scale(p), roughness(p)
    for c in p.centers.values():
        c.footprint = rect(0, 0, 3, 3)   # all identical
    assert levels_of_scale(p) < los0 and roughness(p) < rgh0, "uniformity must lower both"
    # 3) isolating a center drops Not-Separateness to the disconnected floor
    p = living_plan()
    p.seams = [s for s in p.seams if "L6" not in (s.a, s.b)]   # orphan L6
    assert not_separateness(p) == 0.0, "a disconnected center must zero not_separateness"

    # --- from_graph on the real baked world yields a usable (partial) plan ---
    g = json.load(open("examples/world.json"))["graph"]
    plan = from_graph(g)
    assert plan.centers and plan.seams, "from_graph must build centers + seams"
    assert any(len(c.members) >= 2 for c in plan.centers.values()), \
        "the real corpus has shared-court candidates (the semilattice)"
    w = wholeness(plan)   # geometry terms are None pre-growth; graph terms still score
    assert 0.0 <= w <= 1.0

    print(f"OK  (dead={wd:.3f}  living={wl:.3f})")


if __name__ == "__main__":
    main()
