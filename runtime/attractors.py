"""AttractorTracker — measures system proximity to emergent behavioral regimes.

Six attractors the system can enter:
  1. Industrial Singularity  — matter cycling ratio > 1.0 (forge generates net matter)
  2. Haunted Archive          — ghost-to-note ratio > 0.5 (knowledge creates persistent enemies)
  3. Companion Flux           — companions recruited & died > 5 per run (churn engine)
  4. Pacifist Singularity     — 3+ consecutive floors with zero kills
  5. Echo Cascade             — Echo sigil fires 2+ times in one run (immortality attractor)
  6. Standing Range           — max(standing) - min(standing) > 8 across factions

Each metric is scored 0.0 (no proximity) to 1.0 (fully in attractor).
"""
from __future__ import annotations


class AttractorTracker:
    def __init__(self):
        self.matter_collected: int = 0
        self.matter_forged: int = 0
        self.ghosts_seen: int = 0
        self.notes_learned: int = 0
        self.companions_recruited: int = 0
        self.companions_died: int = 0
        self.pacifist_floors: int = 0
        self.max_consecutive_pacifist: int = 0
        self._consecutive_pacifist: int = 0
        self.echo_fires: int = 0
        self.standing_max: float = 0
        self.standing_min: float = 0
        self.total_floors: int = 0
        self.total_kills: int = 0
        self.total_turns: int = 0

    def record_floor(self, floor, kills):
        self.total_floors += 1
        if kills == 0:
            self._consecutive_pacifist += 1
        else:
            self._consecutive_pacifist = 0
        if self._consecutive_pacifist > self.max_consecutive_pacifist:
            self.max_consecutive_pacifist = self._consecutive_pacifist

    def record_matter_collected(self, amount):
        self.matter_collected += amount

    def record_matter_forged(self, amount):
        self.matter_forged += amount

    def record_ghost_seen(self):
        self.ghosts_seen += 1

    def record_note_learned(self):
        self.notes_learned += 1

    def record_companion_recruited(self):
        self.companions_recruited += 1

    def record_companion_died(self):
        self.companions_died += 1

    def record_echo_fire(self):
        self.echo_fires += 1

    def record_standing(self, faction_scores: dict):
        if faction_scores:
            self.standing_max = max(max(faction_scores.values(), default=0), self.standing_max)
            self.standing_min = min(min(faction_scores.values(), default=0), self.standing_min)

    def record_run_stats(self, kills, turns):
        self.total_kills = kills
        self.total_turns = turns

    def scores(self) -> dict:
        """Return attractor scores 0.0-1.0."""
        return {
            "industrial": self._industrial_score(),
            "haunted": self._haunted_score(),
            "companion_flux": self._companion_flux_score(),
            "pacifist": self._pacifist_score(),
            "echo_cascade": self._echo_cascade_score(),
            "standing_range": self._standing_range_score(),
        }

    def _industrial_score(self) -> float:
        if self.matter_collected == 0:
            return 0.0
        ratio = self.matter_forged / self.matter_collected
        # Score: 0 at ratio 0.5, 0.5 at ratio 0.75, 1.0 at ratio 1.0+
        return min(1.0, max(0.0, (ratio - 0.5) * 2.0))

    def _haunted_score(self) -> float:
        if self.notes_learned == 0:
            return 0.0
        ratio = self.ghosts_seen / self.notes_learned
        return min(1.0, ratio / 0.5)  # 1.0 at ratio 0.5

    def _companion_flux_score(self) -> float:
        flux = self.companions_recruited + self.companions_died
        return min(1.0, flux / 5.0)  # 1.0 at 5 flux events

    def _pacifist_score(self) -> float:
        return min(1.0, self.max_consecutive_pacifist / 3.0)  # 1.0 at 3 floors

    def _echo_cascade_score(self) -> float:
        return min(1.0, self.echo_fires / 2.0)  # 1.0 at 2 echoes

    def _standing_range_score(self) -> float:
        rng = self.standing_max - self.standing_min
        return min(1.0, rng / 8.0)  # 1.0 at range 8

    def narrative(self) -> str:
        """Generate a one-sentence narrative summary of this run."""
        parts = []
        s = self.scores()

        if self.total_turns <= 50:
            parts.append(f"A brief {self.total_turns}-turn descent")
        elif self.total_floors > 10:
            parts.append(f"A deep {self.total_floors}-floor expedition")
        elif self.total_floors > 3:
            parts.append(f"A {self.total_floors}-floor journey")
        else:
            parts.append(f"A short {self.total_floors}-floor run")

        if self.total_kills > 30:
            parts.append("drenched in blood")
        elif self.total_kills > 10:
            parts.append("with significant combat")
        elif self.total_kills > 0:
            parts.append("with scattered skirmishes")

        if s["industrial"] > 0.7:
            parts.append(", the forge running hot enough to reshape the economy")
        if s["haunted"] > 0.5:
            parts.append(", curiosity summoning ghosts from between the notes")
        if s["companion_flux"] > 0.5:
            parts.append(", allies cycling through the revolving door of loyalty")
        if s["pacifist"] > 0.7:
            parts.append(", long stretches of tense silence between kills")
        if s["echo_cascade"] > 0.5:
            parts.append(", pulled back from death more than once")

        if not parts:
            return "An unremarkable descent."
        return " ".join(parts) + "."


# module-level factory
def tracker() -> AttractorTracker:
    return AttractorTracker()


class Dampener:
    @staticmethod
    def compute_mods(scores: dict) -> dict:
        """Given attractor scores (0.0-1.0), return parameter mods for next run.
        Each mod is additive -- applied by the game setup before descent."""
        mods = {}
        if scores.get("industrial", 0) > 0.7:
            mods["forge_cost_penalty"] = min(3, int((scores["industrial"] - 0.5) * 6))
        if scores.get("echo_cascade", 0) > 0.5:
            mods["echo_durability_penalty"] = max(0, int((scores["echo_cascade"] - 0.25) * 4))
        if scores.get("pacifist", 0) > 0.7:
            mods["standing_decay_accel"] = min(3, int((scores["pacifist"] - 0.5) * 4))
        if scores.get("standing_range", 0) > 0.8:
            mods["standing_dampen"] = int(scores["standing_range"] * 2)
        return mods
