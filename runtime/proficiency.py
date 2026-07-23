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
            weight = 0.25   # soft cap: mastered but still craftable with recent practice
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


class SkillTracker:
    """Tracks proficiency for one skill. Same mechanics as ProficiencyTracker."""
    def __init__(self):
        self._buf: list[str] = []       # ring buffer of recent actions
        self._total: int = 0            # lifetime count
        self._tier: int = 0             # 0-5 mastery tier

    def exercise(self):
        self._buf.append("x")
        if len(self._buf) > 20:
            self._buf.pop(0)
        self._total += 1
        self._recalc_tier()

    def _recalc_tier(self):
        total = self._total
        if total >= 100:     self._tier = 5
        elif total >= 60:    self._tier = 4
        elif total >= 30:    self._tier = 3
        elif total >= 15:    self._tier = 2
        elif total >= 5:     self._tier = 1
        else:                self._tier = 0

    def tier(self) -> int:
        return self._tier

    def recent(self) -> int:
        return len(self._buf)


class Skills:
    """Five skill trees for the universal agent."""
    def __init__(self):
        self.tinkering = SkillTracker()
        self.foraging = SkillTracker()
        self.husbandry = SkillTracker()
        self.scholarship = SkillTracker()
        self.diplomacy = SkillTracker()

    def exercise(self, skill_name: str):
        tracker = getattr(self, skill_name, None)
        if tracker:
            tracker.exercise()

    def tier(self, skill_name: str) -> int:
        tracker = getattr(self, skill_name, None)
        return tracker.tier() if tracker else 0

    def recent(self, skill_name: str) -> int:
        tracker = getattr(self, skill_name, None)
        return tracker.recent() if tracker else 0


_skills: Skills | None = None


def skills() -> Skills:
    global _skills
    if _skills is None:
        _skills = Skills()
    return _skills


def exercise_skill(name: str):
    skills().exercise(name)
