"""Salvage / inventory — everything that breaks leaves the world's matter on the floor.

Opt-in System (registered explicitly; without it nothing here runs, so the bare game and
existing tests are untouched). It listens on the bus for the two ways a thing can break —
`actor_died` (a fallen creature) and `broke` (a shattered sigil / detonated crystal) — turns
each into `components_of(...)` (the world's own `aesthetic` materials), and scatters that
matter on the ground. Standing on salvage pours it into the player's persistent `Inventory`.

`breakdown_sigil` is the player-driven counterpart: voluntarily melt a slotted sigil back
into matter (feeding the forge's shatter -> salvage -> forge loop).

Self-contained: reads game state, mutates only through the public Game API + the player's
`Inventory`, draws via `render_overlay`. Every cross-system call is None-guarded. Deterministic
(`components_of` is a pure hash of source identity; collection is positional).
"""
from __future__ import annotations

import random

from runtime.components import Inventory, components_of, inv, world_materials
from runtime.systems import System

SALVAGE_GLYPH = "*"   # vanilla relic glyph, free because stat-loot is suppressed under systems
HEAP_GLYPH = "%"      # trash heaps — non-combat matter sources


def _summary(comps: dict) -> str:
    """Compact, deterministic 'mat xN ...' rendering of a materials dict."""
    if not comps:
        return "nothing"
    items = sorted(comps.items(), key=lambda kv: (-kv[1], kv[0]))
    return " ".join(f"{m}x{q}" for m, q in items)


class SalvageSystem(System):
    name = "salvage"

    def __init__(self):
        # per-floor ground salvage: (x, y) -> {material: qty}
        self.ground: dict = {}
        self.ground_q: dict = {}   # (x, y) -> quality tier of that salvage (from its source)
        self.game = None   # stashed so the query API works param-less if needed
        self.heaps: dict = {}         # (x, y) -> {"matter": int, "depleted": bool}
        self._heap_timers: dict = {}  # (x, y) -> turn when heap respawns
        self._scrapped: set = set()   # (x, y) ruin tiles already scraped this floor

    # ---- lifecycle ----------------------------------------------------------
    def on_world_start(self, game):
        self.game = game
        self.ground = {}
        self.ground_q = {}

    def on_floor_enter(self, game):
        # Ground salvage is per-floor; the player's Inventory (attached to the player
        # object via inv()) persists across floors and is deliberately left untouched.
        self.game = game
        self.ground = {}
        self.heaps = {}
        self._heap_timers = {}
        self._scrapped = set()
        rng = random.Random(f"{game.seed}:{game.floor}:heaps")
        count = rng.randint(1, 2)  # 1-2 heaps per floor
        for _ in range(count):
            for _ in range(50):
                x = rng.randint(2, game.level.w - 3)
                y = rng.randint(2, game.level.h - 3)
                if game.level.walkable(x, y) and game.actor_at(x, y) is None:
                    self.heaps[(x, y)] = {"matter": rng.randint(1, 3), "depleted": False}
                    break

    def on_player_act(self, game):
        self.game = game
        self._collect(game)
        self._collect_heaps(game)
        self._respawn_heaps(game)
        self._scrap_ruins(game)

    # ---- event bus ----------------------------------------------------------
    def on_event(self, game, etype, data):
        self.game = game
        data = data or {}
        if etype == "actor_died":
            actor = data.get("actor")
            pos = data.get("pos")
            if actor is None or pos is None:
                return
            comps = components_of(
                game, kind="creature",
                source=getattr(actor, "source", ""),
                tier=getattr(actor, "tier", 1),
                name=getattr(actor, "name", ""),
            )
            self._drop(pos, comps, getattr(actor, "quality", 0))   # elites yield graded matter
        elif etype == "broke":
            pos = data.get("pos")
            if pos is None:
                return
            comps = components_of(
                game, kind=data.get("kind", "thing"),
                source=data.get("source", ""),
                tier=data.get("tier", 1),
                name=data.get("name", ""),
            )
            self._drop(pos, comps, data.get("quality", 0))

    # ---- ground salvage -----------------------------------------------------
    def _drop(self, pos, comps: dict, quality: int = 0):
        if not comps:
            return
        try:
            x, y = pos
        except (TypeError, ValueError):
            return
        tile = self.ground.setdefault((x, y), {})
        for m, q in comps.items():            # merge if a tile already holds salvage
            tile[m] = tile.get(m, 0) + q
        if quality > self.ground_q.get((x, y), 0):
            self.ground_q[(x, y)] = quality

    def _collect(self, game):
        player = getattr(game, "player", None)
        if player is None:
            return
        tile = self.ground.pop((player.x, player.y), None)
        if not tile:
            return
        q = self.ground_q.pop((player.x, player.y), 0)
        inv(player).add(tile, quality=q)       # banks the matter's grade for the forge floor
        game.log(f"Salvaged {_summary(tile)}.")

    # ---- trash heaps --------------------------------------------------------
    def _collect_heaps(self, game):
        player = getattr(game, "player", None)
        if player is None:
            return
        pos = (player.x, player.y)
        heap = self.heaps.get(pos)
        if heap is None or heap["depleted"]:
            return
        heap["depleted"] = True
        inv(player).add({"scrap": heap["matter"]})
        rng = random.Random(f"{game.seed}:{game.floor}:heaps:{pos}")
        self._heap_timers[pos] = game.turn + rng.randint(80, 120)
        game.log(f"You pick through the trash ({heap['matter']} scrap).")

    def _respawn_heaps(self, game):
        for pos, timer in list(self._heap_timers.items()):
            if game.turn >= timer:
                del self._heap_timers[pos]
                heap = self.heaps.get(pos)
                if heap is not None:
                    heap["depleted"] = False

    # ---- environmental scrap ------------------------------------------------
    def _scrap_ruins(self, game):
        player = getattr(game, "player", None)
        if player is None:
            return
        px, py = player.x, player.y
        pos = (px, py)
        if pos in self._scrapped:
            return
        try:
            glyph = game.level.tiles[py][px]
        except (IndexError, AttributeError, TypeError):
            return
        if glyph != "░":
            return
        rng = random.Random(f"{game.seed}:{game.floor}:scrap:{pos}")
        if rng.random() >= 0.10:
            return
        self._scrapped.add(pos)
        inv(player).add({"scrap": 1})
        game.log("You find usable scrap in the rubble.")

    # ---- player command: melt a slotted sigil back into matter --------------
    def breakdown_sigil(self, game, ability=None):
        """Pull a slotted sigil (the chosen `ability`, else the first) from the sigil
        system, remove it, and pour its matter into the player's inventory. Returns the
        components dict, or None if there is no sigil system / no matching sigil."""
        self.game = game
        sigsys = game.system("sigils") if game is not None else None
        if sigsys is None:
            return None
        slots = getattr(sigsys, "slots", None)
        if not slots:
            return None
        if ability is None:
            s = slots[0]
        else:
            s = next((x for x in slots if x.get("ability") == ability), None)
            if s is None:
                return None
        slots.remove(s)
        comps = components_of(game, kind="sigil",
                              source=s.get("note", ""), name=s.get("ability", ""))
        inv(game.player).add(comps, quality=s.get("quality", 0))
        game.log(f"You break down the {s.get('ability', 'sigil')} sigil ({_summary(comps)}).")
        return comps

    # ---- query API ----------------------------------------------------------
    def inventory(self, game=None) -> Inventory:
        """The player's persistent Inventory."""
        g = game or self.game
        player = getattr(g, "player", None) if g is not None else None
        if player is None:
            return Inventory()
        return inv(player)

    def matter(self, game=None) -> int:
        """Total matter the player is currently carrying."""
        return self.inventory(game).total()

    def materials(self, game=None) -> list:
        """The world's material vocabulary (passthrough for HUD / partners)."""
        g = game or self.game
        if g is None:
            return []
        return world_materials(g)

    # ---- presentation -------------------------------------------------------
    def render_overlay(self, game, grid):
        h = len(grid)
        w = len(grid[0]) if h else 0
        for (x, y) in self.ground:
            if 0 <= y < h and 0 <= x < w and grid[y][x] == ".":
                grid[y][x] = SALVAGE_GLYPH
        for (x, y), heap in self.heaps.items():
            if not heap["depleted"]:
                if 0 <= y < h and 0 <= x < w and grid[y][x] == ".":
                    grid[y][x] = HEAP_GLYPH

    def points_of_interest(self, game):
        # expose salvage tiles so the exploiter auto-agent walks over and grabs them
        pts = list(self.ground)
        for pos, heap in self.heaps.items():
            if not heap["depleted"]:
                pts.append(pos)
        return pts

    def status_line(self, game):
        i = inv(game.player)
        heap_count = sum(1 for h in self.heaps.values() if not h["depleted"])
        parts = [f"Matter: {i.total()} ({i.summary()})"]
        if heap_count > 0:
            parts.append(f"Heaps: {heap_count}")
        return "  ".join(parts)
