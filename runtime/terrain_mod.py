"""Dynamic terrain modification — the world responds to player actions.

Six event types make the physical architecture change: boss-kill sanctums,
faction threshold doors, quest-unsealed alcoves, knowledge-revealed rooms,
kill-scarred ground, and forge-grown sanctums. Every change is additive —
the world heals, it does not break.

Listens on the cross-system bus for trigger events and mutates live
Game fields (_overlay, _landmarks, _town_tiles, _glow_cells, _gates).
Records chronicle events for persistence via Upheaval.
"""
from __future__ import annotations

from runtime.systems import System

_SCAR_LIFE = 200   # turns a scar persists before fading
_SCAR_RADIUS = 1    # cardinal neighbors scarred around the kill tile


class TerrainModSystem(System):
    name = "terrain"

    def __init__(self):
        self._region_kills: dict[str, int] = {}
        self._room_forges: dict[str, int] = {}
        self._scarred: dict[tuple, int] = {}   # (x,y) -> remaining ttl
        self._events: list = []                # chronicle events to record

    def on_world_start(self, game):
        self._region_kills = {}
        self._room_forges = {}
        self._scarred = {}
        self._events = []

    def on_floor_enter(self, game):
        self._region_kills = {}
        self._room_forges = {}

    def on_player_act(self, game):
        # scar decay: each turn, all scars tick down
        faded = [t for t, ttl in self._scarred.items() if ttl <= 0]
        for t in faded:
            del self._scarred[t]
            ovl = getattr(game, "_overlay", {})
            if t in ovl and ovl[t] == "†":
                del ovl[t]
        for t in list(self._scarred):
            self._scarred[t] -= 1

    def on_event(self, game, etype, data):
        data = data or {}
        if etype == "enemy_killed":
            self._on_kill(game, data)
        elif etype == "forge_used":
            self._on_forge(game, data)
        elif etype == "lore_read":
            self._on_lore(game, data)
        elif etype == "standing_changed":
            self._on_faction(game, data)

    # ---- event handlers ---------------------------------------------------

    def _on_kill(self, game, data):
        enemy = data.get("enemy")
        if enemy is None:
            return
        pos = (enemy.x, enemy.y)
        rid = self._region_of(game, pos)
        # monument on boss kill
        if getattr(enemy, "is_boss", False):
            lm = getattr(game, "_landmarks", {})
            lm[pos] = "monument"
            ovl = getattr(game, "_overlay", {})
            ovl[pos] = "▲"
            game.log(f"▲ The ground holds its breath — the sanctum clears.")
            self._events.append({"kind": "sanctum_cleared", "note": getattr(enemy, "source", ""),
                                 "tile": list(pos)})
            # settle the boss room
            idx = game.room_at(*pos)
            if idx is not None:
                tiles = getattr(game, "_town_tiles", set())
                room_tiles = game.room_tiles(idx) if hasattr(game, "room_tiles") else []
                for t in room_tiles:
                    tiles.add(t)
                game.log("The chamber settles into hallowed ground.")
            return

        # scar on kills
        if getattr(enemy, "allegiance", "") == "monster":
            if rid:
                self._region_kills[rid] = self._region_kills.get(rid, 0) + 1
            else:
                self._region_kills["__global__"] = self._region_kills.get("__global__", 0) + 1
                rid = "__global__"
            if self._region_kills.get(rid, 0) >= 5:
                self._region_kills[rid] = 0
                ovl = getattr(game, "_overlay", {})
                for dx in range(-_SCAR_RADIUS, _SCAR_RADIUS + 1):
                    for dy in range(-_SCAR_RADIUS, _SCAR_RADIUS + 1):
                        if abs(dx) + abs(dy) <= _SCAR_RADIUS:
                            t = (pos[0] + dx, pos[1] + dy)
                            if game.level.walkable(*t):
                                ovl[t] = "†"
                                self._scarred[t] = _SCAR_LIFE
                game.log("† The ground here will remember.")

    def _on_forge(self, game, data):
        px, py = game.player.x, game.player.y
        nid = data.get("ability", "")
        idx = game.room_at(px, py)
        note = game.room_notes.get(idx, "") if hasattr(game, "room_notes") else ""
        key = note or f"{px},{py}"
        self._room_forges[key] = self._room_forges.get(key, 0) + 1
        if self._room_forges[key] >= 3 and note and note not in getattr(game.up, "forge_sanctums", set()):
            game.up.forge_sanctums.add(note)
            if hasattr(game, "_town_tiles"):
                for t in game.room_tiles(idx):
                    game._town_tiles.add(t)
            game.log("The forge-fire has marked this room as its own.")
            self._events.append({"kind": "forge_grown", "note": note})

    def _on_lore(self, game, data):
        note = data.get("note", "")
        if not note:
            return
        hist = game.system("history")
        marg = game.system("marginalia")
        total = (getattr(hist, "read", 0) if hist else 0) + (getattr(marg, "read", 0) if marg else 0)
        if total >= 3 and note not in getattr(game.up, "revealed_notes", set()):
            game.up.revealed_notes.add(note)
            idx = next((i for i, nid in getattr(game, "room_notes", {}).items() if nid == note), None)
            if idx is not None and hasattr(game, "_glow_cells"):
                for t in game.room_tiles(idx):
                    game._glow_cells[t] = max(game._glow_cells.get(t, 0), 0.6)
            game.log(f"★ '{note}' burns bright in your mind — the room remembers.")
            self._events.append({"kind": "thought_revealed", "note": note})

    def _on_faction(self, game, data):
        fac = data.get("faction", "")
        standing = data.get("standing", 0)
        if standing < 4 or not fac:
            return
        if fac in getattr(game.up, "opened_thresholds", {}):
            return
        rid = next((r["id"] for r in game.m["regions"] if r.get("factionId") == fac), "")
        if not rid:
            return
        # find a wall tile on the faction's anchor room to open as a gate
        anchor = next((r["sourceNoteId"] for r in game.m["regions"] if r["id"] == rid), "")
        idx = next((i for i, nid in getattr(game, "room_notes", {}).items() if nid == anchor), None)
        if idx is None:
            return
        # find a wall tile adjacent to floor
        tiles = game.room_tiles(idx)
        walls = set()
        for t in tiles:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nt = (t[0] + dx, t[1] + dy)
                if game.level.tiles[nt[1]][nt[0]] == "#":
                    walls.add(nt)
        if walls:
            door = next(iter(sorted(walls)))
            game.level.tiles[door[1]][door[0]] = ">"
            game._gates[door] = rid
            game.up.opened_thresholds[fac] = door
            game.log(f"✦ The threshold opens — a new passage into the depths.")
            self._events.append({"kind": "threshold_opened", "faction": fac,
                                 "tile": list(door), "region": rid})

    def _region_of(self, game, pos) -> str:
        rof = getattr(game, "_region_of", {})
        cr = getattr(game, "_cell_region", {})
        return rof.get(pos) or cr.get(pos, "")

    def render_overlay(self, game, grid):
        for (x, y), ttl in self._scarred.items():
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]) and grid[y][x] == ".":
                if ttl > 0:
                    grid[y][x] = "†"
