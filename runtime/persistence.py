"""Persistence bridge — converts run-time events into Upheaval chronicle events
for world-state mutation between runs.

Wire: lore_read → lost_note (ghost), standing extremes → faction shifts,
       forge_used → sanctum persistence (terrain_mod + Upheaval).
"""
from __future__ import annotations
from .det import droll


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
            if droll(note_id, 3) == 0:  # ~33% chance
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
                    "note": region_id,   # Upheaval keys forge_sanctums by note
                    "region": region_id,
                    "count": count,
                })

        # Faction standings → faction shifts
        for faction_id, standing in self.faction_endings.items():
            if standing >= 5:
                events.append({
                    "kind": "border_opens",
                    "note": faction_id,   # Upheaval keys contested by note
                    "faction": faction_id,
                    "standing": standing,
                })
            elif standing <= -5:
                events.append({
                    "kind": "border_closes",
                    "note": faction_id,
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

        # Healing terraforming events (Milestone C) — lateral only
        if self.rest_count >= 50:
            events.append({"kind": "town_expanded", "count": self.rest_count})
        if self.sacred_ground_ticks >= 40:
            events.append({"kind": "hallowed_bloom", "count": self.sacred_ground_ticks})
        if self.flora_harvest_count >= 30:
            events.append({"kind": "grove_established", "count": self.flora_harvest_count})
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


# --------------------------------------------------------------------------- #
# the return arrow: a run writes what it did, the next run reads it
# --------------------------------------------------------------------------- #
#
# `to_upheaval_events` had zero callers. The bake-to-play-to-bake circuit was open at
# exactly this point: `bake.py` reads one input, the markdown directory, so nothing play
# produced could reach a later world. The only way to get an Upheaval was to edit notes by
# hand and pass `--evolve-from`.
#
# This is the missing arrow, and it is deliberately the small version: a run's events are
# appended to a file keyed by world seed, and the next run on that world loads them as its
# Upheaval. It does not touch the bake, so the deterministic skeleton is untouched.
#
# It is bounded on purpose. Events are deduplicated on their identity and the store is
# capped, so a hundred runs on one world cannot accumulate a hundred ascended notes. The
# loop has a return arrow; it is not licence for unbounded growth.

CHRONICLE_MAX = 24        # most events one world's chronicle will carry forward


def chronicle_path() -> str:
    import os
    return os.path.expanduser("~/.vaultcrawl/chronicle.json")


def _event_key(e: dict) -> tuple:
    """Identity of an event for deduplication: the kind plus whatever it names."""
    return (e.get("kind", ""), e.get("note", ""), e.get("faction", ""),
            e.get("region", ""), str(e.get("pos", "")))


def save_chronicle(seed: str, path: str = None) -> int:
    """Append this run's events to the world's chronicle. Returns the stored count."""
    import json, os
    path = path or chronicle_path()
    events = chronicle().to_upheaval_events()
    if not events:
        return 0
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        pass
    if not isinstance(data, dict):
        data = {}
    merged = list(data.get(seed) or []) + events
    seen, out = set(), []
    for e in merged:
        k = _event_key(e)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    out = out[-CHRONICLE_MAX:]        # newest wins when the cap bites
    data[seed] = out
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        return 0
    return len(out)


def load_chronicle_events(seed: str, path: str = None) -> list:
    """The events earlier runs on this world left behind. Empty if there are none."""
    import json
    path = path or chronicle_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        got = data.get(seed) or []
        return got if isinstance(got, list) else []
    except (OSError, ValueError, AttributeError):
        return []
