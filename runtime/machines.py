"""Hackable map machines — Cogmind-style Fabricators and Terminals.

Two single-use props the dungeon seeds on every floor, grounding the matter +
information economies in physical map furniture you walk onto:

  Fabricator (glyph ``F``) — a forge bench. Stand on it and it spends salvaged
    *matter* to forge a sigil into a free slot (it calls the ``forge`` system),
    then burns out. No matter / no free slot -> it stays, inert, for later.
  Terminal  (glyph ``T``) — an info node. Stand on it and it *hacks*: it loads a
    region ahead onto your knowledge frontier (``knowledge.reveal``) and, if a
    structures layer is present, disarms one armed trap beside you. Then it dies.

Both are single-use so they can't be farmed by pacing back and forth.

Self-contained ``System`` subclass: it reads game state, mutates the world only
through the public Game API (``game.log``) and partner query/command APIs
(``forge.forge`` / ``knowledge.reveal`` / ``structures.traps``), and draws through
``render_overlay``. Every cross-system call is None-guarded, so a floor still runs
with any partner absent.

Determinism: all placement randomness comes from
``random.Random(f"{game.seed}:{game.floor}:machines")``, created fresh per floor.
"""
from __future__ import annotations

import random

from runtime.dungeon import free_floor_tiles
from runtime.sigils import ROLE_ABILITY
from runtime.systems import System

# Glyphs (overlay, floor '.' cells only).
FAB_GLYPH = "F"
TERM_GLYPH = "T"

# Deterministic preference order when auto-picking an ability to fabricate — the
# first un-slotted one, mirroring ForgeSystem so the logged ability matches what
# the forge actually crafts. (hub->Recall, bridge->Phase, ... orphan->Echo.)
_ABILITY_ORDER = list(dict.fromkeys(ROLE_ABILITY.values()))


class MachineSystem(System):
    name = "machines"

    def __init__(self):
        self.fabricators: set = set()   # {(x, y)} single-use forge benches
        self.terminals: set = set()     # {(x, y)} single-use info nodes
        self.rng = None

    # ---- placement ----------------------------------------------------------
    def _region_community(self, game, region):
        """The graph community owning the current region (so we can find its
        hub/bridge notes). Mirrors SigilSystem's resolution."""
        fid = region.get("factionId", "") if region else ""
        if isinstance(fid, str) and fid.startswith("faction_"):
            try:
                return int(fid[len("faction_"):])
            except ValueError:
                pass
        src = region.get("sourceNoteId") if region else None
        node = game.m.get("graph", {}).get("nodes", {}).get(src)
        if node is not None:
            return node.get("community")
        return None

    def _role_notes(self, game, role):
        """Note ids of the given graph `role`, preferring the current region's
        community, then falling back to any note of that role in the vault."""
        region = game.region_for(game.floor)
        comm = self._region_community(game, region)
        nodes = game.m.get("graph", {}).get("nodes", {})
        local = [nid for nid, n in nodes.items()
                 if n.get("role") == role and n.get("community") == comm]
        if local:
            return local
        return [nid for nid, n in nodes.items() if n.get("role") == role]

    def _anchor_for_role(self, game, role):
        """A map anchor for a note of `role` — its 'neighbourhood'. Notes carry no
        tile of their own, so we ground the neighbourhood in a deterministically
        chosen room center (F near a hub room, T near a bridge room). None when no
        such note or no rooms exist, in which case placement is purely free-tile."""
        notes = self._role_notes(game, role)
        if not notes:
            return None
        # the machine belongs in its note's own room when that note holds one here
        room_of = getattr(game, "room_of_note", None)
        if room_of:
            for nid in sorted(notes):
                room = room_of(nid)
                if room is not None:
                    return room.center
        rooms = list(getattr(game.level, "rooms", []) or [])
        if not rooms:
            return None
        return self.rng.choice(rooms).center

    def _free_tiles(self, game):
        """Open floor tiles, excluding the player, the stairs, and any actor/item."""
        exclude = {(game.player.x, game.player.y), game.level.stairs}
        exclude |= {(a.x, a.y) for a in game.actors}
        exclude |= {(it.x, it.y) for it in game.items}
        return free_floor_tiles(game.level, exclude)

    def _choose(self, tiles, anchor):
        """Pick a tile: the one nearest `anchor` (deterministic tie-break on the
        coordinate), or the first of the already-shuffled list when anchor is None."""
        if not tiles:
            return None
        if anchor is None:
            return tiles[0]
        ax, ay = anchor
        return min(tiles, key=lambda t: ((t[0] - ax) ** 2 + (t[1] - ay) ** 2, t))

    def on_floor_enter(self, game):
        self.rng = random.Random(f"{game.seed}:{game.floor}:machines")
        self.fabricators = set()
        self.terminals = set()

        tiles = self._free_tiles(game)
        if not tiles:
            return
        self.rng.shuffle(tiles)

        # Fabricator near a hub note's neighbourhood; Terminal near a bridge's.
        f_pos = self._choose(tiles, self._anchor_for_role(game, "hub"))
        if f_pos is not None:
            tiles.remove(f_pos)
            self.fabricators.add(f_pos)
        t_pos = self._choose(tiles, self._anchor_for_role(game, "bridge"))
        if t_pos is not None:
            self.terminals.add(t_pos)

    # ---- ability choice -----------------------------------------------------
    def _pick_ability(self, game):
        """The first ability not currently slotted (so the bench refills a verb you
        lack), matching ForgeSystem's default so the logged name is what's crafted."""
        sigils = game.system("sigils")
        slotted = ({s.get("ability") for s in getattr(sigils, "slots", [])}
                   if sigils else set())
        for ability in _ABILITY_ORDER:
            if ability not in slotted:
                return ability
        return _ABILITY_ORDER[0] if _ABILITY_ORDER else "Recall"

    # ---- use: fabricator ----------------------------------------------------
    def _use_fabricator(self, game, pos):
        forge = game.system("forge")
        if forge is None:
            return                                   # no forge -> bench inert
        ability = self._pick_ability(game)
        # forge() is atomic + fully guarded: False (changing nothing) when there's
        # no free slot or not enough matter, in which case the bench is NOT spent.
        if forge.forge(game, ability):
            game.log(f"The fabricator forges a {ability} sigil.")
            self.fabricators.discard(pos)

    # ---- use: terminal ------------------------------------------------------
    def region_ahead(self, game):
        """A deeper/neighbour region id to load, computed from regions' depthBand:
        the shallowest *other* region whose band starts at or below the current
        region's, else any other region, else the current one. None if no regions."""
        regions = game.m.get("regions", [])
        if not regions:
            return None
        cur = game.region_for(game.floor)
        cur_id = cur.get("id") if cur else None
        cur_min = (cur.get("depthBand") or [0])[0] if cur else 0

        def band_key(r):
            band = r.get("depthBand") or [0, 0]
            return (band[0], band[-1], str(r.get("id")))

        ordered = sorted(regions, key=band_key)
        # a region strictly ahead: different region, band starting no shallower
        for r in ordered:
            if r.get("id") != cur_id and (r.get("depthBand") or [0])[0] >= cur_min:
                return r.get("id")
        # fall back to any neighbour region, else the current region
        for r in ordered:
            if r.get("id") != cur_id:
                return r.get("id")
        return cur_id

    def _disarm_nearby(self, game):
        """If a structures layer is present, disarm one armed trap in the 3x3
        around the player. Returns True if a trap was cleared."""
        structures = game.system("structures")
        traps = getattr(structures, "traps", None) if structures else None
        if not traps:
            return False
        px, py = game.player.x, game.player.y
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                cell = (px + dx, py + dy)
                if cell in traps:
                    del traps[cell]
                    game.log("The terminal disarms a nearby trap.")
                    return True
        return False

    def _use_terminal(self, game, pos):
        weather = game.system("weather")
        if weather:
            props = getattr(weather, 'props', {})
            if props:
                self._scramble_weather(game, pos)
                return
        knowledge = game.system("knowledge")
        region_id = self.region_ahead(game)
        if knowledge is None or region_id is None:
            # primary effect impossible -> still try a disarm, but only spend the
            # terminal (and log the hack) if *something* happened.
            if self._disarm_nearby(game):
                game.log("You hack the terminal — a region ahead loads.")
                self.terminals.discard(pos)
            return
        knowledge.reveal(region_id)
        self._disarm_nearby(game)                    # opportunistic, guarded
        game.log("You hack the terminal — a region ahead loads.")
        self.terminals.discard(pos)

    def _scramble_weather(self, game, pos):
        """Terminal option: scramble weather in the current region for 30 turns."""
        weather = game.system("weather")
        if weather is None:
            return
        from runtime.components import inv as get_inv
        game.log("You hack the terminal — the weather pattern scrambles.")
        if not hasattr(game, '_weather_suppressed'):
            game._weather_suppressed = {}
        for y in range(game.level.h):
            for x in range(game.level.w):
                game._weather_suppressed[(x, y)] = 30
        self.terminals.discard(pos)
        game.emit("weather_cleared", pos=pos, radius=999)

    # ---- per-turn -----------------------------------------------------------
    def on_player_act(self, game):
        if not getattr(game, "alive", True):
            return
        pos = (game.player.x, game.player.y)
        if pos in self.fabricators:
            self._use_fabricator(game, pos)
        elif pos in self.terminals:
            self._use_terminal(game, pos)

    # ---- agent hooks / presentation -----------------------------------------
    def points_of_interest(self, game):
        """Machine tiles, so an autonomous exploiter walks over to use them."""
        return sorted(self.fabricators) + sorted(self.terminals)

    def render_overlay(self, game, grid):
        h = len(grid)
        tiles = game.level.tiles
        for glyph, cells in ((FAB_GLYPH, self.fabricators), (TERM_GLYPH, self.terminals)):
            for (x, y) in cells:
                if not (0 <= y < h and 0 <= x < len(grid[y])):
                    continue
                # floor cells only — never clobber an actor / item / '@' / '>' / fog.
                if tiles[y][x] == "." and grid[y][x] == ".":
                    grid[y][x] = glyph

    def status_line(self, game):
        n = len(self.fabricators) + len(self.terminals)
        if not n:
            return None
        return f"Machines: {len(self.fabricators)}F {len(self.terminals)}T"
