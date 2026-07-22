"""Renunciation Shrine — permanent sacrifices for lasting power.

Found in deep z-levels (rare). Interacting offers 3 choices from a pool.
Each is a permanent trade-off: lose something now for a lasting benefit.
Rejecting all 3 causes the shrine to crumble — no second chance at that shrine.

Deterministic: shrine placement and offerings are seeded.
"""
from __future__ import annotations

import random

from runtime.systems import System

_OFFERINGS = [
    ("Renounce a Sigil Slot", "sigil", "Lose 1 max sigil capacity — gain +8 max HP"),
    ("Renounce a Learned Note", "note", "Unlearn a note — gain permanent +1 ATK"),
    ("Renounce Matter", "matter", "Lose all carried matter — gain permanent +3 DEF"),
    ("Renounce Rest", "rest", "Can no longer camp — gain +5 HP and +1 speed"),
    ("Renounce an Effect", "effect", "Lose one effect — gain permanent +2 sight radius"),
]


class SacrificeSystem(System):
    name = "sacrifice"

    def __init__(self):
        self.shrines: dict[tuple, list] = {}  # (x,y) -> list of offering texts
        self._done: set = set()               # positions already used

    def on_world_start(self, game):
        self.shrines = {}
        self._done = set()

    def on_floor_enter(self, game):
        self.shrines = {}
        z = getattr(game, "current_z", 0)
        if z > -2:  # only in deeper levels
            return
        rng = random.Random(f"{game.seed}:{game.floor}:sacrifice")
        if rng.random() > 0.30:
            return
        from runtime.dungeon import free_floor_tiles
        free = free_floor_tiles(game.level, {(game.player.x, game.player.y)})
        if not free:
            return
        pos = rng.choice(free)
        if pos in self._done:
            return
        # pick 3 distinct offerings
        picks = rng.sample(_OFFERINGS, min(3, len(_OFFERINGS)))
        self.shrines[pos] = picks
        game._overlay[pos] = "◊"

    def render_overlay(self, game, grid):
        for (x, y) in self.shrines:
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
                grid[y][x] = "◊"

    def on_interact(self, game) -> bool:
        pos = (game.player.x, game.player.y)
        offers = self.shrines.pop(pos, None)
        if offers is None:
            return False
        self._done.add(pos)
        game._overlay.pop(pos, None)
        # the front-end calls a popup to let the player choose
        game._pending_sacrifice = offers
        game.log("A shrine of renunciation hums before you — choose, or reject.")
        return True  # consumed the interact

    def apply(self, game, choice: str):
        """Apply the chosen sacrifice permanently."""
        if choice == "sigil":
            sigs = game.system("sigils")
            if sigs and sigs.slots:
                sigs.slots.pop()
            game.player.max_hp += 8
            game.player.hp += 8
        elif choice == "note":
            know = game.system("knowledge")
            if know and know.known:
                nid = next(iter(know.known), None)
                if nid:
                    know.known.discard(nid)
            game.player.atk += 1
        elif choice == "matter":
            salv = game.system("salvage")
            if salv:
                bag = salv.inventory(game)
                if bag:
                    bag.comp = {}
            game.player.defense += 3
        elif choice == "rest":
            from runtime.game import Game
            game._resting = False
            game._consecutive_rest = 0
            game._cant_camp = True
            game.player.max_hp += 5
            game.player.hp += 5
            game.player.speed += 0.2
            game.player._base_speed = game.player.speed
        elif choice == "effect":
            eff = game.system("effects")
            if eff and eff.collected:
                nid = next(iter(eff.collected), None)
                if nid:
                    eff.collected.discard(nid)
                    if eff.worn == nid:
                        eff.worn = None
            eff_sys = game.system("effects")
            # sight bonus is handled in knowledge.py via _sight()
        game._pending_sacrifice = None
        game.log(f"You accept the {choice} renunciation — the shrine crumbles, and you are changed.")
