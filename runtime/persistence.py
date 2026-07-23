"""Persistence bridge — converts run-time events into Upheaval chronicle events
for world-state mutation between runs.

Wire: lore_read → lost_note (ghost), standing extremes → faction shifts,
       forge_used → sanctum persistence (terrain_mod + Upheaval).
"""
from __future__ import annotations


class RunChronicle:
    """Accumulates events during a run that should persist to the next run."""

    def __init__(self):
        self.lore_read_notes: set = set()        # note ids read this run
        self.forge_regions: dict = {}             # region_id -> forge count
        self.faction_endings: dict = {}           # faction_id -> final standing
        self.companion_deaths: list = []           # (companion_name, killer_name)
        self.boss_killed: bool = False
        self.floor_reached: int = 0
        self.kills: int = 0

    def record_lore(self, note_id: str):
        self.lore_read_notes.add(note_id)

    def record_forge(self, region_id: str):
        self.forge_regions[region_id] = self.forge_regions.get(region_id, 0) + 1

    def record_faction_end(self, faction_id: str, standing: int):
        self.faction_endings[faction_id] = standing

    def record_companion_death(self, companion_name: str, killer_name: str):
        self.companion_deaths.append((companion_name, killer_name))

    def record_boss_kill(self):
        self.boss_killed = True

    def to_upheaval_events(self) -> list[dict]:
        """Convert chronicle to Upheaval-compatible event list."""
        events = []

        # Lore → lost notes (ghosts). Each read note has a chance to become a ghost.
        for note_id in self.lore_read_notes:
            # Only some notes become ghosts (deterministic by note id hash)
            if hash(note_id) % 3 == 0:  # ~33% chance
                events.append({
                    "kind": "note_lost",
                    "note": note_id,
                    "cause": "read_and_remembered",
                })

        # Forge regions → sanctums (persist forge-used rooms)
        for region_id, count in self.forge_regions.items():
            if count >= 3:  # 3+ forges in a region = sanctum
                events.append({
                    "kind": "forge_grown",
                    "region": region_id,
                    "count": count,
                })

        # Faction standings → faction shifts
        for faction_id, standing in self.faction_endings.items():
            if standing >= 5:
                events.append({
                    "kind": "border_opens",
                    "faction": faction_id,
                    "standing": standing,
                })
            elif standing <= -5:
                events.append({
                    "kind": "border_closes",
                    "faction": faction_id,
                    "standing": standing,
                })

        # Companion deaths → ascended vengeance
        for comp_name, killer_name in self.companion_deaths:
            events.append({
                "kind": "idea_ascends",
                "note": killer_name,
                "cause": f"slain_{comp_name}",
            })

        return events


# Global chronicle for the current run
_chronicle: RunChronicle | None = None


def chronicle() -> RunChronicle:
    global _chronicle
    if _chronicle is None:
        _chronicle = RunChronicle()
    return _chronicle


def reset_chronicle():
    global _chronicle
    _chronicle = RunChronicle()
