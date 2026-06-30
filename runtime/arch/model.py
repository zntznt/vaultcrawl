"""The SitePlan data model (ARCHITECTURE_SPEC.md §2).

A `SitePlan` is the *living structure* before carving: a field of `Center`s joined by a
SEMILATTICE of `Seam`s (loops + overlap, never a tree). Growth (§5) fills each center's
placed geometry (`pos`, `footprint`, `sub_centers`); the wholeness scorer (§4) reads it.

Pure data — no rng, no I/O. `footprint` is a set of (x, y) tiles.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Center:
    id: str
    source_note: str = ""
    intensity: float = 0.0          # 0..1 (PageRank)   -> size + importance
    flow: float = 0.0               # 0..1 (betweenness) -> facilitator?
    members: tuple = ()             # communities it belongs to; len>=2 => a shared court
    age: float = 0.0                # 0..1 (mtime)       -> gradients / growth rings
    tags: tuple = ()
    role: str = "cluster"           # hub | bridge | leaf | orphan | cluster
    # placed geometry (filled by growth / carve):
    pos: tuple | None = None        # (x, y) of the center
    footprint: set = field(default_factory=set)   # the tiles it occupies (organic, not a rect)
    sub_centers: list = field(default_factory=list)  # focal void, alcoves (the recursive unfolding)

    @property
    def area(self) -> int:
        return len(self.footprint)

    @property
    def home(self) -> int:
        """Primary community (for grouping); -1 if none."""
        return self.members[0] if self.members else -1

    def centroid(self):
        if self.pos is not None:
            return self.pos
        if not self.footprint:
            return None
        xs = [p[0] for p in self.footprint]
        ys = [p[1] for p in self.footprint]
        return (sum(xs) / len(xs), sum(ys) / len(ys))


@dataclass
class Seam:
    a: str
    b: str
    kind: str = "path"              # path | gateway | shared_court | boundary | void
    strength: float = 1.0           # from interlock weight / friction


@dataclass
class SitePlan:
    centers: dict                   # id -> Center
    seams: list                     # list[Seam]  (a SEMILATTICE: cycles + overlap)
    growth_order: list = field(default_factory=list)
    bounds: tuple = (0, 0)          # (w, h) of the canvas

    def adjacency(self) -> dict:
        """Undirected center-graph induced by the seams."""
        adj = {cid: set() for cid in self.centers}
        for s in self.seams:
            if s.a in adj and s.b in adj and s.a != s.b:
                adj[s.a].add(s.b)
                adj[s.b].add(s.a)
        return {k: sorted(v) for k, v in adj.items()}

    def placed(self) -> list:
        return [c for c in self.centers.values() if c.footprint]


def from_graph(graph: dict) -> SitePlan:
    """Build an abstract SitePlan (no geometry yet) from a baked `world.json["graph"]`.
    Intensity = normalized PageRank; flow = normalized betweenness; seams = the interlock
    edge list (NOT a spanning tree). Growth (Phase 3) will place the geometry."""
    nodes = graph.get("nodes", {})
    pmax = max((n.get("pagerank", 0.0) for n in nodes.values()), default=0.0) or 1.0
    bmax = max((n.get("betweenness", 0.0) for n in nodes.values()), default=0.0) or 1.0
    centers = {}
    for nid, n in nodes.items():
        centers[nid] = Center(
            id=nid, source_note=nid,
            intensity=n.get("pagerank", 0.0) / pmax,
            flow=n.get("betweenness", 0.0) / bmax,
            members=tuple(n.get("members", []) or []),
            age=float(n.get("activity", 0.0)),
            tags=tuple(n.get("tags", []) or []),
            role=n.get("role", "cluster"),
        )
    seams = [Seam(e["a"], e["b"], strength=float(e.get("interlock", 1)))
             for e in graph.get("edges", []) if e.get("a") in centers and e.get("b") in centers]
    return SitePlan(centers=centers, seams=seams)
