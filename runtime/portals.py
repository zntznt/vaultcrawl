"""Timed realm portals — collapsing gates with urgency.

Gates that spawn temporarily in the overworld, providing shortcuts to deeper
regions. LOS-accelerated timer: countdown speeds up 3× when the player sees
the portal. Auditory urgency cues at ttl thresholds. Gates remain traversable
until they collapse.

Deterministic placement seeded per floor.
"""
from __future__ import annotations

import random

from runtime.systems import System

_PORTAL_DURATION = 500     # base turns a portal lasts
_PORTAL_SPREAD = 200       # random range added to base
_ACCELERATION = 2          # decay multiplier when in sight


class PortalSystem(System):
    name = "portals"

    def __init__(self):
        self.portals: dict[tuple, dict] = {}  # (x,y) -> {ttl, max_ttl, realm_id, seen}

    def on_world_start(self, game):
        self.portals = {}

    def on_floor_enter(self, game):
        self.portals = {}
        rng = random.Random(f"{game.seed}:{game.floor}:portals")
        if rng.random() >= 0.50:  # 50% chance per floor
            return
        from runtime.dungeon import free_floor_tiles
        free = free_floor_tiles(game.level, {(game.player.x, game.player.y)})
        if not free:
            return
        pos = rng.choice(free)
        duration = _PORTAL_DURATION + rng.randint(0, _PORTAL_SPREAD)
        rid = next((r["id"] for r in game.m.get("regions", []) if r.get("depthBand", [0,0])[0] > game.floor), "")
        if not rid:
            return
        self.portals[pos] = {"ttl": duration, "max_ttl": duration, "realm_id": rid, "seen": False}
        game._gates[pos] = rid
        if hasattr(game, "_overlay"):
            game._overlay[pos] = "◉"
        game.log("A shimmering gate flickers into existence nearby.")

    def on_player_act(self, game):
        expired = []
        for pos, p in list(self.portals.items()):
            in_sight = (max(abs(game.player.x - pos[0]),
                           abs(game.player.y - pos[1])) <= 12)
            if in_sight and not p["seen"]:
                p["seen"] = True
                game.log("You spot a flickering gate — it won't hold long.")
            decay = _ACCELERATION if in_sight else 1
            p["ttl"] -= decay
            if p["ttl"] <= 0:
                expired.append(pos)
            elif p["ttl"] <= 50 and p["ttl"] + decay > 50:
                game.log("The gate sputters — it will collapse soon.")
        for pos in expired:
            self.portals.pop(pos)
            if pos in game._gates:
                del game._gates[pos]
            if hasattr(game, "_overlay"):
                game._overlay.pop(pos, None)
            game.log("The gate collapses with a sigh.")

    def status_line(self, game):
        if not self.portals:
            return None
        ttl = min(p["ttl"] for p in self.portals.values())
        return f"Portal: {ttl}t"

    def render_overlay(self, game, grid):
        for (x, y), p in self.portals.items():
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]) and grid[y][x] in (".",):
                grid[y][x] = "◉"
