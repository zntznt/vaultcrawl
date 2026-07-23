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
        self.death_pos = None
        self.death_hp = 0
        self.death_inventory = {}
        self.death_had_companion = False
        self.death_rested = False
        self.death_floor = 0
        self.death_last_action = ""

        # Healing method tracking (Milestone C: Terraforming)
        self.rest_count: int = 0
        self.forge_count: int = 0
        self.corpse_repair_count: int = 0
        self.shield_count: int = 0
        self.recall_cast_count: int = 0
        self.sacred_ground_ticks: int = 0
        self.flora_harvest_count: int = 0
        self.sacrifice_shrine_count: int = 0
        self.faction_sanctuaries: int = 0

        # Death-time healing snapshots
        self.death_rest_count: int = 0
        self.death_forge_count: int = 0
        self.death_corpse_repair_count: int = 0
        self.death_shield_count: int = 0
        self.death_recall_cast_count: int = 0
        self.death_sacred_ground_ticks: int = 0
        self.death_flora_harvest_count: int = 0
        self.death_sacrifice_shrine_count: int = 0
        self.death_faction_sanctuaries: int = 0

    def record_lore(self, note_id: str):
        self.lore_read_notes.add(note_id)

    def record_forge(self, region_id: str):
        self.forge_regions[region_id] = self.forge_regions.get(region_id, 0) + 1
        self.forge_count += 1

    def record_faction_end(self, faction_id: str, standing: int):
        self.faction_endings[faction_id] = standing

    def record_companion_death(self, companion_name: str, killer_name: str):
        self.companion_deaths.append((companion_name, killer_name))

    def record_boss_kill(self):
        self.boss_killed = True

    def record_rest(self):
        self.rest_count += 1

    def record_corpse_repair(self):
        self.corpse_repair_count += 1

    def record_shield(self):
        self.shield_count += 1

    def record_recall_cast(self):
        self.recall_cast_count += 1

    def record_sacred_tick(self):
        self.sacred_ground_ticks += 1

    def record_flora_harvest(self):
        self.flora_harvest_count += 1

    def record_sacrifice_shrine(self):
        self.sacrifice_shrine_count += 1

    def record_faction_sanctuary(self):
        self.faction_sanctuaries += 1

    def record_death(self, pos, hp, inventory_items, last_action, had_companion, rested_before, floor):
        self.death_pos = pos
        self.death_hp = hp
        self.death_inventory = inventory_items
        self.death_had_companion = had_companion
        self.death_rested = rested_before
        self.death_floor = floor
        self.death_last_action = last_action

        # Snap healing stats for death artifact context
        self.death_rest_count = self.rest_count
        self.death_forge_count = self.forge_count
        self.death_corpse_repair_count = self.corpse_repair_count
        self.death_shield_count = self.shield_count
        self.death_recall_cast_count = self.recall_cast_count
        self.death_sacred_ground_ticks = self.sacred_ground_ticks
        self.death_flora_harvest_count = self.flora_harvest_count
        self.death_sacrifice_shrine_count = self.sacrifice_shrine_count
        self.death_faction_sanctuaries = self.faction_sanctuaries

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

        # Death artifacts: material remains of the agent who died here
        if self.death_pos:
            events.append({
                "kind": "death_artifact",
                "pos": self.death_pos,
                "hp": self.death_hp,
                "inventory": list(self.death_inventory.keys()) if self.death_inventory else [],
                "had_companion": self.death_had_companion,
                "rested": self.death_rested,
                "floor": self.death_floor,
                "last_action": self.death_last_action,
                "healing": {
                    "rest_count": self.death_rest_count,
                    "forge_count": self.death_forge_count,
                    "corpse_repair_count": self.death_corpse_repair_count,
                    "shield_count": self.death_shield_count,
                    "recall_cast_count": self.death_recall_cast_count,
                    "sacred_ground_ticks": self.death_sacred_ground_ticks,
                    "flora_harvest_count": self.death_flora_harvest_count,
                    "sacrifice_shrine_count": self.death_sacrifice_shrine_count,
                    "faction_sanctuaries": self.death_faction_sanctuaries,
                },
            })

        # Healing terraforming events (Milestone C)
        if self.rest_count >= 50:
            events.append({"kind": "town_expanded", "count": self.rest_count})
        if self.corpse_repair_count >= 20:
            events.append({"kind": "marrow_rich", "count": self.corpse_repair_count})
        if self.recall_cast_count >= 15:
            events.append({"kind": "recall_sanctified", "count": self.recall_cast_count})
        if self.sacred_ground_ticks >= 40:
            events.append({"kind": "hallowed_bloom", "count": self.sacred_ground_ticks})
        if self.flora_harvest_count >= 30:
            events.append({"kind": "grove_established", "count": self.flora_harvest_count})
        if self.sacrifice_shrine_count >= 5:
            events.append({"kind": "covenant_sealed", "count": self.sacrifice_shrine_count})
        if self.shield_count >= 50:
            events.append({"kind": "bastion_genesis", "count": self.shield_count})
        if self.faction_sanctuaries >= 3:
            events.append({"kind": "coalition_formed", "count": self.faction_sanctuaries})

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
