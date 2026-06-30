"""Decay — corpses and rot, indifferent to everyone.

The autonomous ecology's mortician. Every death in the game flows through
``game.kill(actor, cause)``, which emits ``actor_died {actor, cause, pos}`` on the
bus. This system listens for that and drops a corpse (glyph ``%``) at the dead
actor's tile with a rot timer. While a corpse rots it seeps a light decay miasma:
it occasionally fouls its own tile with ``acid`` (via the reactions write-API) or,
if a living actor is standing on it, gnaws a single point of health (capped,
never lethal on its own). When the timer elapses the corpse is gone.

This is the substrate that turns ANY death — a faction monster, a wild critter —
into food and terrain: scavengers (fauna) eat corpses through ``consume(x,y)``.

Self-contained ``System`` subclass. It reads game state, talks to the rest of the
world only through the bus + the reactions write-API (every cross-system call
None-guarded), and never edits another system or game.py.

Determinism: all randomness comes from ``random.Random(f"{seed}:{floor}:decay")``,
created once per floor. The acid seep is additionally guaranteed on a fixed
cadence, so behaviour is reproducible regardless of the rng stream.
"""
from __future__ import annotations

import random

from runtime.systems import System

_GLYPH = "%"            # corpse overlay (floor cells only)
_CORPSE_TTL = 12        # turns a corpse lingers before it rots away
_SEEP_PERIOD = 3        # a rotting corpse fouls its own tile every N turns
_SEEP_CHANCE = 0.34     # extra per-turn chance to seep (flavour; cadence guarantees it)
_MIASMA_DMG = 1         # health a living actor loses standing on a rotting corpse
_MIN_HP = 1             # the miasma is light: it never reduces an actor below this


class DecaySystem(System):
    name = "decay"

    def __init__(self, ttl: int = _CORPSE_TTL):
        self.corpses: dict = {}     # (x, y) -> remaining rot turns
        self.ttl = ttl
        self.rng = None

    # ---- lifecycle ----
    def on_world_start(self, game):
        self._ensure_rng(game)

    def on_floor_enter(self, game):
        # corpses are positional, tied to the level; a fresh floor starts clean
        self.corpses = {}
        self.rng = random.Random(f"{game.seed}:{game.floor}:{self.name}")

    def _ensure_rng(self, game):
        if self.rng is None:
            self.rng = random.Random(f"{game.seed}:{game.floor}:{self.name}")

    # ---- bus: every death becomes a corpse ----
    def on_event(self, game, etype, data):
        if etype != "actor_died":
            return
        pos = (data or {}).get("pos")
        if not self._valid_pos(game, pos):
            return                       # missing / malformed / out-of-bounds -> ignore
        x, y = pos
        self.corpses[(x, y)] = self.ttl
        # announce the fresh corpse so scavengers / other ecology can react
        game.emit("corpse_spawned", pos=(x, y))

    def _valid_pos(self, game, pos) -> bool:
        if not pos or not isinstance(pos, (tuple, list)) or len(pos) != 2:
            return False
        x, y = pos
        if not isinstance(x, int) or not isinstance(y, int):
            return False
        lvl = getattr(game, "level", None)
        if lvl is None:
            return True
        return 0 <= x < lvl.w and 0 <= y < lvl.h

    # ---- per-turn rot ----
    def on_player_act(self, game):
        if not self.corpses:
            return
        self._ensure_rng(game)
        reactions = game.system("reactions")     # may be absent -> None-guard every call
        for (x, y) in list(self.corpses.keys()):
            ttl = self.corpses[(x, y)] - 1
            if ttl <= 0:
                del self.corpses[(x, y)]          # fully rotted: the corpse is gone
                continue
            self.corpses[(x, y)] = ttl
            self._seep(game, reactions, x, y, ttl)

    def _seep(self, game, reactions, x, y, ttl):
        """A rotting corpse either gnaws a living actor on its tile OR fouls the
        tile with an acid miasma — a small, capped, indifferent effect."""
        victim = self._living_actor_at(game, x, y)
        if victim is not None:
            # light miasma: shave a point, but never lethal on its own
            if victim.hp > _MIN_HP:
                victim.hp = max(_MIN_HP, victim.hp - _MIASMA_DMG)
            return
        # No one underfoot: the corpse just rots in plain view. (It used to seep acid onto
        # its OWN tile, which hid the '%' beneath a ':' — the miasma is now felt only by a
        # creature standing on it, above, so the corpse stays visible.)

    @staticmethod
    def _living_actor_at(game, x, y):
        p = getattr(game, "player", None)
        if p is not None and getattr(game, "alive", True) and p.x == x and p.y == y:
            return p
        a = game.actor_at(x, y)
        if a is not None and getattr(a, "alive", True):
            return a
        return None

    # ---- query / command API (called by fauna scavengers, None-guarded by them) ----
    def corpse_at(self, x, y) -> bool:
        """Is there a corpse on this tile?"""
        return (x, y) in self.corpses

    def consume(self, x, y) -> bool:
        """A scavenger eats the corpse here. True if one was present (now removed)."""
        if (x, y) in self.corpses:
            del self.corpses[(x, y)]
            return True
        return False

    # ---- rendering / HUD ----
    def render_overlay(self, game, grid):
        h = len(grid)
        for (x, y) in self.corpses:
            if not (0 <= y < h and 0 <= x < len(grid[y])):
                continue
            if grid[y][x] == ".":            # only ever overlay a still-floor cell
                grid[y][x] = _GLYPH

    def status_line(self, game):
        return f"Corpses: {len(self.corpses)}"
