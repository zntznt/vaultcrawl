"""Proficiency tracking — exercise queue for skill practice.

A rolling ring buffer of recent sigil-related actions. Proficiency is measured
by how many times you've recently practiced a specific ability. Used by the
forge system to gate crafting behind demonstrated competence, not just
note-knowledge. Diminishing returns: early practice counts fully, later
practice counts less.

Deterministic — no RNG, pure counter tracking.
"""
from __future__ import annotations

_BUF_SIZE = 20         # recent-action ring buffer size
_FULL_CREDIT = 5       # first 5 exercises count fully
_HALF_CREDIT = 10      # next 10 count at 0.5×
# after 15 total exercises, no further credit (mastered)


class ProficiencyTracker:
    def __init__(self):
        self._buf: list[str] = []
        self._total: dict[str, int] = {}  # lifetime exercise count per ability

    def exercise(self, ability: str):
        """Record one practice of a sigil ability."""
        self._buf.append(ability)
        if len(self._buf) > _BUF_SIZE:
            self._buf.pop(0)
        self._total[ability] = self._total.get(ability, 0) + 1

    def level(self, ability: str) -> float:
        """Effective proficiency level (0.0 .. _FULL_CREDIT).
        Weighted: recent exercises in the buffer, plus diminishing returns from total."""
        recent = self._buf.count(ability)
        total = self._total.get(ability, 0)
        if total <= _FULL_CREDIT:
            weight = 1.0
        elif total <= _FULL_CREDIT + _HALF_CREDIT:
            weight = 0.5
        else:
            weight = 0.0
        return recent * weight

    def can_craft(self, ability: str, required: float = 2.0) -> bool:
        """True if proficiency is sufficient to forge the given ability."""
        return self.level(ability) >= required

    def reset(self):
        self._buf = []
        self._total = {}


# global tracker (one per run)
_tracker: ProficiencyTracker | None = None


def ptracker() -> ProficiencyTracker:
    global _tracker
    if _tracker is None:
        _tracker = ProficiencyTracker()
    return _tracker


def exercise(ability: str):
    ptracker().exercise(ability)
