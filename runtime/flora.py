"""Flora — the world's autonomous vegetation (player/faction-independent).

A floor is seeded with one "weed": the vault's single most-common note tag. A
handful of plants sprout on bare floor when you enter a floor, then creep slowly
to neighbouring tiles each turn. The vegetation is *indifferent* — it targets no
one. It only answers to the elemental substrate (the reactions layer):

  * a plant standing on a ``fire`` tile **burns** — it is removed and the fire
    leaps to one adjacent floor tile (flame runs through dry growth);
  * on a ``wet`` tile it spreads **faster** (damp ground accelerates growth);
  * on an ``acid`` tile it **dies** (corrosion eats the roots);
  * on a ``sacred`` tile it **blooms**, mending any actor standing on it (+1 hp).

Self-contained ``System`` subclass: it reads game state, talks to other systems
only through the bus / the reactions write+query API, and draws through
``render_overlay``. Every cross-system call is None-guarded so the world still
runs if the reactions layer is absent.

Determinism: all randomness comes from ``random.Random(f"{seed}:{floor}:flora")``,
created once per floor so the spread pattern is reproducible.
"""
from __future__ import annotations

import collections
import random

from runtime.systems import System
from runtime.dungeon import free_floor_tiles

# vegetation creeps edge-to-edge, never diagonally
_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))

_GLYPH = ";"            # overlay glyph for a plant on a floor cell
_SPROUT_N = 5           # plants seeded on floor enter ("a handful")
_BASE_SPREAD = 1        # new plants per turn before any wet bonus (slow)
_WET_BONUS_CAP = 2      # extra spread attempts when growth sits on wet ground
_CAP_DIVISOR = 4        # cap total plants at free_floor // this (never fill the map)


class FloraSystem(System):
    name = "flora"

    def __init__(self):
        self.plants: set = set()       # {(x, y)} of living plants
        self.weed: str | None = None   # the dominant tag this vegetation grows from
        self.cap = 0                   # max plants this floor
        self.rng = None

    # ---- seeding -------------------------------------------------------------
    def _dominant_tag(self, game) -> str | None:
        """The vault's single most-common note tag (deterministic tie-break)."""
        counts: collections.Counter = collections.Counter()
        nodes = (game.m.get("graph") or {}).get("nodes") or {}
        # nodes is a dict keyed by note id; tags live on each node
        iterable = nodes.values() if isinstance(nodes, dict) else nodes
        for node in iterable:
            for tag in (node.get("tags") or []):
                counts[tag] += 1
        if not counts:
            return None
        # most frequent wins; ties broken by tag name so it is reproducible
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def on_world_start(self, game):
        self.weed = self._dominant_tag(game)

    def on_floor_enter(self, game):
        if self.weed is None:                 # defensive: world_start may be skipped
            self.weed = self._dominant_tag(game)
        self.plants = set()
        self.rng = random.Random(f"{game.seed}:{game.floor}:flora")

        if self.weed is None:                 # a vault with no tags grows nothing
            self.cap = 0
            return

        exclude = {(game.player.x, game.player.y), game.level.stairs}
        free = free_floor_tiles(game.level, exclude)
        if not free:
            self.cap = 0
            return
        self.cap = max(_SPROUT_N, len(free) // _CAP_DIVISOR)
        n = min(_SPROUT_N, len(free))
        for pos in self.rng.sample(free, n):
            self.plants.add(pos)

    # ---- helpers -------------------------------------------------------------
    def _is_floor(self, game, x, y) -> bool:
        lvl = game.level
        return 0 <= x < lvl.w and 0 <= y < lvl.h and lvl.tiles[y][x] == "."

    def _floor_neighbors(self, game, x, y) -> list:
        return [(x + dx, y + dy) for dx, dy in _ORTH if self._is_floor(game, x + dx, y + dy)]

    def _actors_at(self, game, x, y) -> list:
        out = []
        p = getattr(game, "player", None)
        if p is not None and p.x == x and p.y == y:
            out.append(p)
        for a in getattr(game, "actors", []):
            if a.x == x and a.y == y:
                out.append(a)
        return out

    # ---- per-turn life -------------------------------------------------------
    def on_player_act(self, game):
        if self.rng is None or not self.plants or not getattr(game, "alive", True):
            return
        r = game.system("reactions")           # may be absent — None-guard everything

        # 1) react to the substrate ------------------------------------------------
        burned, dead, wet = set(), set(), set()
        for pos in sorted(self.plants):
            props = r.props_at(*pos) if r is not None else set()
            if not props:
                continue
            if "fire" in props:
                # the plant is kindling: it dies and the flame jumps onward
                burned.add(pos)
                nbrs = [n for n in self._floor_neighbors(game, *pos)
                        if "fire" not in (r.props_at(*n) if r is not None else set())]
                if nbrs and r is not None:
                    r.ignite(*self.rng.choice(sorted(nbrs)))
                continue
            if "acid" in props:                # corrosion kills the roots
                dead.add(pos)
                continue
            if "sacred" in props:              # hallowed bloom mends whoever stands here
                for a in self._actors_at(game, *pos):
                    a.hp = min(a.max_hp, a.hp + 1)
            if "wet" in props:                 # damp ground accelerates spread
                wet.add(pos)
        if burned:
            self.plants -= burned
            game.log("Flora burns away.")
        self.plants -= dead

        # 2) creep to neighbouring bare floor (slow, capped) -----------------------
        attempts = _BASE_SPREAD + min(_WET_BONUS_CAP, len(wet))
        added = set()
        for src in sorted(self.plants):
            if attempts <= 0 or len(self.plants) + len(added) >= self.cap:
                break
            free = [n for n in self._floor_neighbors(game, *src)
                    if n not in self.plants and n not in added]
            if not free:
                continue
            added.add(self.rng.choice(sorted(free)))
            attempts -= 1
        self.plants |= added

    # ---- ecology query API (callers None-guard these) ------------------------
    def flora_at(self, x, y) -> bool:
        """True if a living plant occupies this tile."""
        return (x, y) in self.plants

    def consume(self, x, y) -> bool:
        """A grazer eats the plant here: remove it, True if one was present."""
        if (x, y) in self.plants:
            self.plants.discard((x, y))
            return True
        return False

    # ---- rendering / HUD -----------------------------------------------------
    def render_overlay(self, game, grid):
        h = len(grid)
        for (x, y) in self.plants:
            if 0 <= y < h and 0 <= x < len(grid[y]) and grid[y][x] == ".":
                grid[y][x] = _GLYPH

    def status_line(self, game):
        return f"Flora: {len(self.plants)}"
