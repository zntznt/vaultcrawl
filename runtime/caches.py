"""Caches — each place is a distinct opportunity.

A place should advertise a proposition: contents, uses, perils,
all legible before you commit. Here, a note-room may hold a cache (□):

  CONTENTS  its matter is the PLACE'S own — the signature material comes from the
            note's tags/title, not the global aesthetic, so 'rust' ground yields
            rust-matter and Stoicism's chamber yields philosophy-matter.
  USES      place materials register crafting affinities by the note's role
            (hub->keen, bridge->phase_decoy, leaf->ward_reach, orphan->echo_twin,
            cluster->reinforced), so a specific perk LIVES somewhere: to steer
            the forge, go where that matter is. Old thoughts yield seasoned
            (quality-2) matter: ruins are worth the trip.
  PERILS    a cache in charged/flammable/corrosive ground may be warded — and it
            is telegraphed: examine calls it [humming] before you ever touch it.
            A sprung ward bites and RINGS (noise 12): the place hears you loot it.

One search each; deterministic per seed. Self-contained System on the shared bus.
"""
from __future__ import annotations

import random

from .salvage import inv
from .systems import System

GLYPH = "□"
PERIL_DMG = 2
PERIL_ELEMENTS = ("charged", "flammable", "corrosive")
ROLE_PERK = {"hub": "keen", "bridge": "phase_decoy", "leaf": "ward_reach",
             "orphan": "echo_twin", "discovery": "echo_twin",
             "cluster": "reinforced"}


class CacheSystem(System):
    name = "caches"

    def __init__(self):
        self.caches: dict = {}   # (x, y) -> {"note", "material", "peril", "aged"}
        self.searched: int = 0
        self._done: set = set()  # note ids searched: a cache never respawns

    # ---- a place's signature matter ------------------------------------------
    def material_of(self, game, nid: str) -> str:
        node = game.m.get("graph", {}).get("nodes", {}).get(nid, {})
        tags = node.get("tags") or []
        if tags:
            return tags[0].split("/")[-1].lower()
        title = node.get("title", nid) or nid
        return title.split()[0].lower()

    def on_world_start(self, game):
        # crafting has geography: each place's matter favours its role's perk
        from . import quality
        for nid, node in sorted(game.m.get("graph", {}).get("nodes", {}).items()):
            perk = ROLE_PERK.get(node.get("role", ""))
            if perk:
                quality.register_additive(self.material_of(game, nid), perk)

    def on_floor_enter(self, game):
        self.caches = {}
        rng = random.Random(f"{game.seed}:{game.floor}:caches")
        nodes = game.m.get("graph", {}).get("nodes", {})
        taken = {(game.player.x, game.player.y), game.level.stairs}
        taken |= {(a.x, a.y) for a in game.actors}
        for idx, nid in sorted((getattr(game, "room_notes", {}) or {}).items()):
            if nid in self._done:
                continue             # searched once, gone forever (no farming loops)
            node = nodes.get(nid, {})
            age = node.get("activity", 0.5)
            # substance gathers where thought gathered: hubs, orphans, old ruins
            rich = node.get("role") in ("hub", "orphan", "discovery") or age <= 0.15
            if not rich and rng.random() > 0.4:
                continue
            tiles = [t for t in game.room_tiles(idx)
                     if t not in taken and t not in self.caches]
            if not tiles:
                continue
            # anchor the cache BESIDE the room's focal fixture when one exists, so
            # the shelf holds the goods and the room reads as one center (panel step 3)
            feats = getattr(game, "_fixtures", {}).get(idx) or []
            near = [t for t in tiles
                    if any(max(abs(t[0] - fx), abs(t[1] - fy)) <= 1
                           for (fx, fy) in feats)]
            spot = rng.choice(near) if near else rng.choice(tiles)
            region = game._region_by_comm.get(node.get("community")) or {}
            peril = (region.get("element")
                     if region.get("element") in PERIL_ELEMENTS and rng.random() < 0.5
                     else None)
            self.caches[spot] = {
                "note": nid, "material": self.material_of(game, nid),
                "peril": peril, "aged": age <= 0.15}

    def on_player_act(self, game):
        c = self.caches.pop((game.player.x, game.player.y), None)
        if c is None:
            return
        self.searched += 1
        self._done.add(c["note"])
        amount = 3 if c["aged"] else 2
        inv(game.player).add({c["material"]: amount},
                             quality=2 if c["aged"] else 0)
        aged = ", seasoned by long stillness" if c["aged"] else ""
        game.log(f"You search the cache: {c['material']}x{amount}{aged}.")
        if c["peril"]:
            game.player.hp -= PERIL_DMG
            game.log(f"Its ward bites ({c['peril']}): -{PERIL_DMG} HP, and it RINGS.")
            game.emit("noise", pos=(game.player.x, game.player.y), volume=12)
            if game.player.hp <= 0:
                game.alive = False
                game.log("The warded cache is the last thing you touch.")
        know = game.system("knowledge")
        if know is not None and c["note"]:
            know._reveal(game, c["note"], direct=False)   # its contents teach

    # ---- legibility: the opportunity is advertised ---------------------------
    def describe_near(self, game, radius: int = 6) -> list:
        px, py = game.player.x, game.player.y
        out = []
        for (x, y), c in sorted(self.caches.items()):
            if max(abs(x - px), abs(y - py)) > radius:
                continue
            tags = [t for t in (("[humming: warded]" if c["peril"] else ""),
                                ("[ancient]" if c["aged"] else "")) if t]
            out.append(" ".join([f"A cache of {c['material']}"] + tags) + ".")
        return out

    def render_overlay(self, game, grid):
        h = len(grid)
        w = len(grid[0]) if h else 0
        for (x, y) in self.caches:
            if 0 <= y < h and 0 <= x < w and grid[y][x] == ".":
                grid[y][x] = GLYPH

    def points_of_interest(self, game):
        return list(self.caches)

    def status_line(self, game):
        return f"Caches: {len(self.caches)}" if self.caches else None
