"""The pattern-architecture compiler (ARCHITECTURE_SPEC.md).

The pipeline so far: from_graph (§4 inputs) -> grow (§5 growth + §6 semilattice
connection) -> carve (§7 -> a playable dungeon.Level). wholeness (§4) scores any
SitePlan. Still to come: word-level flow (§10) and wiring into the live game (§8).
"""
from .model import Center, Seam, SitePlan, from_graph
from .wholeness import wholeness, PROPERTIES, WEIGHTS
# grow() and carve() live in the like-named submodules (runtime.arch.grow / .carve);
# they are NOT re-exported here to avoid shadowing those modules' names.

__all__ = ["Center", "Seam", "SitePlan", "from_graph", "wholeness", "PROPERTIES", "WEIGHTS"]
