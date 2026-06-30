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
        self.lost_floor: dict = {}   # floor -> [note ids]

    @classmethod
    def from_events(cls, events: list, echo_span: int = 6):
        u = cls()
        for e in events:
            k, note = e["kind"], e["note"]
            if k == "idea_ascends":
                u.ascended.add(note)
            elif k == "power_wanes":
                u.waned.add(note)
            elif k == "note_lost":
                u.lost.add(note)
            elif k == "kingdom_rises":
                u.risen_regions.add(note)
            elif k == "throne_taken":
                u.throne = note
            elif k in ("border_shifts", "border_opens"):
                u.contested.add(note)
        # scatter lost notes across the early floors, deterministically
        for n in sorted(u.lost):
            h = int(hashlib.sha256(n.encode()).hexdigest()[:8], 16)
            u.lost_floor.setdefault(1 + h % echo_span, []).append(n)
        return u

    @property
    def total(self) -> int:
        return (len(self.ascended) + len(self.waned) + len(self.lost)
                + len(self.risen_regions) + len(self.contested) + (1 if self.throne else 0))


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
