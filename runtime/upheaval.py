"""Turn a chronicle (evolve events) into live in-game modifiers.

This closes the loop: editing your notes between bakes produces events, and those events
become things you encounter mid-descent in the *new* world.

    kingdom_rises  -> the region is "new territory": announced + a frontier loot drop
    idea_ascends   -> that note's enemy spawns EMPOWERED (a mini-boss spike)
    power_wanes    -> that note's enemy spawns DIMINISHED (a fading shade)
    note_lost      -> the note is gone from the new world, so it haunts the floors as a
                      ruin-echo (a roaming ghost) on a deterministic floor
    throne_taken   -> the new deepest boss is marked Ascendant
    border_shifts  -> the region is contested ground
"""
from __future__ import annotations

import hashlib

from .entities import Actor


def title(note_id: str) -> str:
    return " ".join(w.capitalize() for w in str(note_id).replace("-", " ").replace("_", " ").split()) or "?"


class Upheaval:
    def __init__(self):
        self.ascended: set = set()
        self.waned: set = set()
        self.lost: set = set()
        self.risen_regions: set = set()
        self.contested: set = set()
        self.throne = None
        self.lost_floor: dict = {}
        # terrain-modifying events
        self.sanctums: set = set()             # note ids whose bosses are slain → monument
        self.opened_thresholds: dict = {}      # faction_id → (x, y) gate tile
        self.unsealed_alcoves: dict = {}       # region_id → [(x, y)] wall tiles opened
        self.bridges_built: list = []          # [(x, y), ...] road tiles bridging regions
        self.forge_sanctums: set = set()       # note ids of forge-grown rooms
        self.revealed_notes: set = set()       # note ids fully illuminated

    @classmethod
    def from_events(cls, events: list, echo_span: int = 6):
        u = cls()
        for e in events:
            # `e["note"]` unconditionally. Six of the ten kinds `to_upheaval_events`
            # produces carry no note key, so wiring the two halves together raised
            # KeyError on the first faction or terraforming event. The producer now sets
            # `note` wherever a kind's consumer needs one; this stays tolerant so a
            # chronicle written by an older build still loads.
            k, note = e["kind"], e.get("note", "")
            # Ascend and wane are mutually exclusive verdicts on one note, and the last
            # word wins. Without the discards they accumulate as two standing facts, and
            # since every consumer tests `ascended` before `waned` the ascendancy would
            # win forever: a note could be empowered once and never fade again however
            # many times you put it down. Events arrive oldest first (`save_chronicle`
            # merges old + new and its dedup keeps the earlier copy), so sequential
            # processing gives the most recent verdict.
            if k == "idea_ascends":
                u.ascended.add(note)
                u.waned.discard(note)
            elif k == "power_wanes":
                u.waned.add(note)
                u.ascended.discard(note)
            elif k == "note_lost":
                u.lost.add(note)
            elif k == "kingdom_rises":
                u.risen_regions.add(note)
            elif k == "throne_taken":
                u.throne = note
            elif k in ("border_shifts", "border_opens"):
                u.contested.add(note)
            # terrain-modifying events
            elif k == "sanctum_cleared":
                u.sanctums.add(note)
                tile = e.get("tile")
                if tile and len(tile) == 2:
                    u._monuments = getattr(u, "_monuments", {})
                    u._monuments[tuple(tile)] = note
            elif k == "threshold_opened":
                fac = e.get("faction", "")
                tile = e.get("tile")
                if fac and tile and len(tile) == 2:
                    u.opened_thresholds[fac] = tuple(tile)
            elif k == "alcove_unsealed":
                rid = e.get("region", "")
                tiles = e.get("tiles", [])
                if rid and tiles:
                    u.unsealed_alcoves.setdefault(rid, []).extend(tuple(t) for t in tiles if len(t) == 2)
            elif k == "bridge_built":
                tiles = e.get("tiles", [])
                if tiles:
                    u.bridges_built.append([tuple(t) for t in tiles if len(t) == 2])
            elif k == "forge_grown":
                u.forge_sanctums.add(note)
            elif k == "thought_revealed":
                u.revealed_notes.add(note)
        # scatter lost notes across the early floors, deterministically
        for n in sorted(u.lost):
            h = int(hashlib.sha256(n.encode()).hexdigest()[:8], 16)
            u.lost_floor.setdefault(1 + h % echo_span, []).append(n)
        return u

    @property
    def total(self) -> int:
        return (len(self.ascended) + len(self.waned) + len(self.lost)
                + len(self.risen_regions) + len(self.contested) + (1 if self.throne else 0)
                + len(self.sanctums) + len(self.opened_thresholds)
                + sum(len(v) for v in self.unsealed_alcoves.values())
                + len(self.bridges_built) + len(self.forge_sanctums)
                + len(self.revealed_notes))


def empower(actor: Actor):
    """A note that grew in influence -> a tougher, brighter foe."""
    actor.max_hp = int(actor.max_hp * 1.6) + 2
    actor.hp = actor.max_hp
    actor.atk += 2
    actor.glyph = actor.glyph.upper()
    actor.name = "Ascendant " + actor.name


def diminish(actor: Actor):
    """A note that lost influence -> a fading remnant."""
    actor.max_hp = max(1, actor.max_hp // 2)
    actor.hp = actor.max_hp
    actor.atk = max(1, actor.atk - 1)
    actor.name = "Fading " + actor.name


def make_echo(note: str, x: int, y: int) -> Actor:
    """A deleted note, haunting the world it used to seed."""
    return Actor(x=x, y=y, glyph="X", name=f"Echo of {title(note)}",
                 hp=8, max_hp=8, atk=2, source=note)
