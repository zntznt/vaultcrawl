"""The pattern-architecture compiler (ARCHITECTURE_SPEC.md).

Phase 2 = the data model + the wholeness scorer. Later phases add growth (§5),
the semilattice connection (§6), the pattern catalogue (§3) and the carver (§7).
"""
from .model import Center, Seam, SitePlan, from_graph
from .wholeness import wholeness, PROPERTIES, WEIGHTS

__all__ = ["Center", "Seam", "SitePlan", "from_graph", "wholeness", "PROPERTIES", "WEIGHTS"]
