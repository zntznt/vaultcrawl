"""MetricsTracker — quantifies every verb, activation, and mechanic usage per run.
Detects overused and underused systems. Output alongside eval stats for comparison."""
from __future__ import annotations


class MetricsTracker:
    """Tracks every mechanic/verb/activation across a single run."""

    def __init__(self):
        # Verbs used (AgentAction kinds)
        self.verbs: dict[str, int] = {
            "move": 0, "wait": 0, "cast": 0, "shield": 0, "shove": 0,
            "interact": 0, "descend": 0, "ascend": 0, "forge": 0,
            "rest": 0, "talk": 0, "toss": 0, "negotiate": 0,
            "breakdown": 0, "commune": 0, "becalm": 0, "craft_consumable": 0,
        }
        # System activations
        self.systems: dict[str, int] = {
            "locus_activated": 0, "locus_type": {},  # {"forge": N, "parley": N, ...}
            "craft_fabricator": 0, "craft_terminal": 0,
            "craft_locus": 0, "craft_camp": 0,
            "effect_collected": 0, "effect_worn": "",
            "portal_entered": 0, "portal_skipped": 0,
            "recipe_discovered": 0, "consumable_crafted": 0,
            "skill_exercised": {},  # {"tinkering": N, "scholarship": N, ...}
            "shrine_used": 0,
            "companion_recruited": 0, "companion_died": 0,
        }
        # Encounter outcomes
        self.encounters: dict[str, int] = {
            "fight": 0, "coerce": 0, "parley": 0, "flee": 0, "appease": 0, "commune": 0,
        }
        # Misc
        self.turns_survived: int = 0
        self.floors_visited: int = 0
        self.total_matter_collected: int = 0
        self.total_matter_spent: int = 0

    def record_verb(self, verb: str):
        if verb in self.verbs:
            self.verbs[verb] += 1

    def record_locus(self, locus_type: str):
        self.systems["locus_activated"] += 1
        self.systems["locus_type"][locus_type] = self.systems["locus_type"].get(locus_type, 0) + 1

    def record_craft(self, craft_type: str):
        key = f"craft_{craft_type}"
        if key in self.systems:
            self.systems[key] += 1

    def record_encounter(self, outcome: str):
        if outcome in self.encounters:
            self.encounters[outcome] += 1

    def record_skill(self, skill_name: str):
        self.systems["skill_exercised"][skill_name] = \
            self.systems["skill_exercised"].get(skill_name, 0) + 1

    def summary(self) -> dict:
        """Return a compact summary for eval stats output."""
        # Top verbs
        active_verbs = {k: v for k, v in self.verbs.items() if v > 0}
        # Locus type distribution
        locus_dist = self.systems.get("locus_type", {})
        # Skills exercised
        skills = self.systems.get("skill_exercised", {})
        # Compute underuse score: what % of available mechanics were used at least once
        verb_usage = sum(1 for v in self.verbs.values() if v > 0)
        verb_total = len(self.verbs)
        system_usage = sum(1 for k, v in self.systems.items()
                           if isinstance(v, int) and v > 0 and k not in ("locus_type", "skill_exercised"))
        return {
            "verbs": active_verbs,
            "verb_diversity": round(verb_usage / max(1, verb_total), 3),  # 0-1, higher=more varied
            "system_activations": {
                k: v for k, v in self.systems.items()
                if isinstance(v, int) and v > 0
            },
            "locus_distribution": locus_dist,
            "encounter_outcomes": {k: v for k, v in self.encounters.items() if v > 0},
            "skills": skills,
            "matter_cycled": self.total_matter_collected + self.total_matter_spent,
        }


# Global singleton
_metrics: MetricsTracker | None = None


def metrics() -> MetricsTracker:
    global _metrics
    if _metrics is None:
        _metrics = MetricsTracker()
    return _metrics


def reset_metrics():
    global _metrics
    _metrics = MetricsTracker()
