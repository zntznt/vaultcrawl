"""Actors and items, with stats derived deterministically from manifest mechanics.

The manifest owns tier / powerBudget; these functions are the single place that turns
those abstract numbers into concrete hp/atk/def, so balance stays in one spot.
"""
from __future__ import annotations

from dataclasses import dataclass

ARCH_GLYPH = {"scribe": "s", "golem": "g", "swarm": "w", "warden": "r",
              "echo": "e", "beast": "b", "construct": "c", "shade": "h"}
ITEM_GLYPH = {"weapon": ")", "armor": "[", "trinket": "=", "relic": "*", "consumable": "!"}


@dataclass
class Actor:
    x: int
    y: int
    glyph: str
    name: str
    hp: int
    max_hp: int
    atk: int
    defense: int = 0
    tier: int = 1
    is_player: bool = False
    is_boss: bool = False
    source: str = ""
    allegiance: str = "monster"   # "player" | "monster" (faction foes) | "wild" (fauna)
    quality: int = 0              # Factorio-style grade 0..4 (set by the QualitySystem)

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class Item:
    x: int
    y: int
    glyph: str
    name: str
    slot: str
    power: int
    flavor: str = ""
    source: str = ""
    quality: int = 0


def enemy_stats(tier: int):
    return 4 + 3 * tier, 1 + tier          # (hp, atk)


def boss_stats(tier: int):
    return 12 + 8 * tier, 2 + 2 * tier      # (hp, atk)


def make_player(x: int, y: int) -> Actor:
    # A fixed baseline -- the player never gains stats during a run (no power creep);
    # progression is configuration (sigils), positioning (reactions), and knowledge.
    return Actor(x=x, y=y, glyph="@", name="you", hp=32, max_hp=32, atk=4,
                 defense=0, is_player=True, allegiance="player")


def make_npc(name: str, glyph: str, x: int, y: int, source: str = "") -> Actor:
    """A neutral, talkable inhabitant — a personified note. Never fights; you parley."""
    return Actor(x=x, y=y, glyph=glyph, name=name, hp=10, max_hp=10, atk=0,
                 defense=0, source=source, allegiance="npc")


def make_critter(name: str, glyph: str, x: int, y: int, hp: int, atk: int,
                 defense: int = 0, source: str = "") -> Actor:
    """A wild creature — part of the autonomous ecology, indifferent to the player.
    Wild actors fight `monster`s (and vice versa) but ignore the player unless the
    fauna system says otherwise."""
    return Actor(x=x, y=y, glyph=glyph, name=name, hp=hp, max_hp=hp, atk=atk,
                 defense=defense, source=source, allegiance="wild")


def make_enemy(spec: dict, x: int, y: int) -> Actor:
    hp, atk = enemy_stats(spec["tier"])
    return Actor(x=x, y=y, glyph=ARCH_GLYPH.get(spec["archetype"], "?"),
                 name=spec["name"], hp=hp, max_hp=hp, atk=atk,
                 tier=spec["tier"], source=spec["sourceNoteId"])


def make_boss(spec: dict, x: int, y: int) -> Actor:
    hp, atk = boss_stats(spec["tier"])
    return Actor(x=x, y=y, glyph="M", name=spec["name"], hp=hp, max_hp=hp, atk=atk,
                 tier=spec["tier"], is_boss=True, source=spec["sourceNoteId"])


def make_item(spec: dict, x: int, y: int) -> Item:
    return Item(x=x, y=y, glyph=ITEM_GLYPH.get(spec["slot"], "?"), name=spec["name"],
                slot=spec["slot"], power=spec["powerBudget"],
                flavor=spec.get("flavor", ""), source=spec["sourceNoteId"])


def apply_item(player: Actor, item: Item) -> str:
    """Mutates the player, returns a log line. Power scales by slot."""
    if item.slot == "weapon":
        gain = max(1, item.power // 4)
        player.atk += gain
        return f"You wield {item.name} (+{gain} ATK)."
    if item.slot == "armor":
        gain = max(1, item.power // 6)
        player.defense += gain
        return f"You don {item.name} (+{gain} DEF)."
    if item.slot in ("trinket", "relic"):
        player.max_hp += item.power
        player.hp += item.power
        return f"{item.name} binds to you (+{item.power} max HP)."
    # consumable
    heal = item.power
    player.hp = min(player.max_hp, player.hp + heal)
    return f"You consume {item.name} (+{heal} HP)."
