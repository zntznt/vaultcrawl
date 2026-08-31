"""Scent diffusion — scent map for tracking and evasion.

A 2D grid that diffuses and decays player scent. Creatures with the SMELL sense detect
scent trails and follow them toward the source. Scent is blocked by walls, reduced by
furniture, and decays each turn. Player movement leaves scent trails; standing still
("wait") does not.

Deterministic: diffusion uses seeded RNG for tie-breaks, not randomness.
"""
from __future__ import annotations

import random

from runtime.systems import System
from .det import drng

_SCENT_DECAY = 1         # amount scent drops per turn
_DIFFUSIVITY = 100        # parts per thousand — how much spreads to neighbours
_RADIUS = 40               # computation radius around player
# How strong an adjacent trail must be before a tracker commits to it. Below this the grid is
# mostly diffusion haze rather than a path anything walked.
SCENT_TRACK_MIN = 2

# Eight-directional, because the game is. See `strongest_neighbour`.
_ADJ8 = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0))


class ScentSystem(System):
    name = "scent"

    def __init__(self):
        self.grid: dict[tuple[int, int], int] = {}   # (x, y) -> scent intensity
        self._prev_player: tuple[int, int] | None = None

    def on_floor_enter(self, game):
        self.grid = {}
        self._prev_player = None

    def on_player_act(self, game):
        self._decay_and_diffuse(game)
        px, py = game.player.x, game.player.y
        # standing still: no new scent (quiet movement is stealth)
        if self._prev_player is not None and (px, py) != self._prev_player:
            self.grid[(px, py)] = self.grid.get((px, py), 0) + 3
            # trail: also mark the step behind with lighter scent
            self.grid[self._prev_player] = self.grid.get(self._prev_player, 0) + 1
        self._prev_player = (px, py)
        # scent leaks across z-levels at stair tiles
        if getattr(game, "current_z", 0) < 0:
            below = getattr(game, "_levels", {}).get(game.current_z + 1)
            tile = game.level.tiles[py][px] if game.level else "."
            if below is not None and tile in "<>":
                # propagate scent to matching position on adjacent z-level
                self.grid[(px, py)] = self.grid.get((px, py), 0)
                # also seed adjacent z with reduced intensity
                below_grid = getattr(game, "_scent_below", None)
                if below_grid is None:
                    game._scent_below = {}
                game._scent_below[(px, py)] = game._scent_below.get((px, py), 0) + 1

    def _decay_and_diffuse(self, game):
        """Decay all scent values, then diffuse from high to low neighbours."""
        if not self.grid:
            return
        rng = drng(f"{sorted(self.grid)}:decay")
        # decay
        for pos in list(self.grid):
            self.grid[pos] = max(0, self.grid[pos] - _SCENT_DECAY)
            if self.grid[pos] <= 0:
                del self.grid[pos]
        # diffuse: each cell contributes DIFFUSIVITY/1000 of its value to neighbours
        new = dict(self.grid)
        for (x, y), val in list(self.grid.items()):
            if val <= 0:
                continue
            spread = val * _DIFFUSIVITY // 1000
            if spread <= 0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not self._is_walkable(game, nx, ny):
                    continue
                if self._is_blocked(game, nx, ny):
                    continue
                new[(nx, ny)] = new.get((nx, ny), 0) + spread
        self.grid = dict((k, v) for k, v in new.items() if v > 0)

    def _is_walkable(self, game, x, y):
        lvl = game.level
        return 0 <= x < lvl.w and 0 <= y < lvl.h and lvl.tiles[y][x] != "#"

    def _is_blocked(self, game, x, y):
        lvl = game.level
        if not (0 <= y < lvl.h and 0 <= x < lvl.w):
            return True
        ch = lvl.tiles[y][x]
        return ch == "#"

    def scent_at(self, x, y) -> int:
        return self.grid.get((x, y), 0)

    def strongest_neighbour(self, game, ax, ay) -> tuple[int, int] | None:
        """Adjacent tile with the highest scent value, over all EIGHT neighbours.

        It scanned only the four orthogonals, which in an eight-directional game is not a
        stylistic choice: a tracker that can only step orthogonally along a trail is strictly
        slower than the prey that laid it, so it loses ground on every diagonal the player
        takes and can never close. `agent_action._ADJ8` carries the same correction for the
        same reason, where scanning four neighbours made a diagonally adjacent creature
        invisible to talk, becalm and negotiate.

        Diffusion below stays orthogonal on purpose: that is a kernel, and diagonals are
        reached in two steps, which is what a diffusion should do. Movement is the thing that
        needs all eight.

        Ties break on the offset order, which is sorted, so two equal neighbours resolve the
        same way on every machine.
        """
        best, bv = None, 0
        for dx, dy in _ADJ8:
            nx, ny = ax + dx, ay + dy
            if self._is_walkable(game, nx, ny):
                sv = self.scent_at(nx, ny)
                if sv > bv:
                    best, bv = (nx, ny), sv
        return best

    def gradient_step(self, game, ax, ay, floor: int = 0):
        """One step UPHILL along the trail, or None when there is nothing to follow.

        A nose does not know where its prey is. It knows which way the smell strengthens,
        which is why this returns a step rather than a destination: following a gradient
        rounds corners and walks the path the prey actually walked, where pathing straight at
        a remembered position does not.

        `floor` is the minimum a neighbour must beat, so a tracker does not chase the ambient
        haze of a trail that has almost decayed away.
        """
        nbr = self.strongest_neighbour(game, ax, ay)
        if nbr is None:
            return None
        if self.scent_at(*nbr) <= max(self.scent_at(ax, ay), floor):
            return None          # flat or downhill: the trail leads nowhere from here
        return (nbr[0] - ax, nbr[1] - ay)

    def status_line(self, game):
        return None
