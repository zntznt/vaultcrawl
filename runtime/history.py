"""History & lore — the vault is its own sultan-history generator.

Caves of Qud grows a dynasty by simulating sultans; here the *knowledge graph* is the
chronicle. The world's deep past is read straight off the graph, deterministically:

  - Note `activity` is recency, so LOW activity = OLD. Each `community` is a cluster
    founded by its oldest member; ordering communities by their founder's age gives the
    succession of Ages.
  - A `bridge` node links two clusters: the Schism, the heresy that still bleeds.
  - An `orphan` (and any note `game.up.lost` swallowed) is a lost age, forgotten.
  - Live upheaval (`risen_regions`, `throne`) layers the newest Ages on top.

Lore fragments (`?`) scatter through the dungeon. Reading one teaches a line of history
AND a navigational fact — the floor a boss sleeps on, or the shape of a hidden secret.
This system adds *knowledge*, never power: nothing it does touches hp/atk/def.

Deterministic: fragment placement is seeded `f"{seed}:{floor}:history"`; the lore itself
is a pure function of the manifest. No real-time, no global RNG.
"""
from __future__ import annotations

import random

from .dungeon import free_floor_tiles
from .systems import System

ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh",
            "Eighth", "Ninth", "Tenth", "Eleventh", "Twelfth"]


class HistorySystem(System):
    name = "history"

    GLYPH = "?"  # lore fragment on the ground

    def __init__(self):
        self.lore: list[str] = []          # the synthesized chronicle, oldest -> newest
        self.ground: dict = {}             # (x, y) -> the lore line buried on this floor
        self.read: int = 0                 # how many fragments the player has read
        self._knowledge: list = []         # bosses + secrets, revealed one per fragment
        self._kidx: int = 0                # cursor into _knowledge (so-far-unmentioned)

    # ---- title helpers ----
    @staticmethod
    def _titlecase(note_id: str) -> str:
        s = str(note_id).replace("-", " ").replace("_", " ").split()
        return " ".join(w.capitalize() for w in s) or "?"

    def _title(self, game, note_id: str) -> str:
        node = game.m.get("graph", {}).get("nodes", {}).get(note_id)
        if node and node.get("title"):
            return node["title"]
        return self._titlecase(note_id)

    def _community_label(self, game, community) -> str:
        """A community's name in the world: the region whose anchor note lives in it,
        else the faction that owns the cluster, else a generic titled fallback."""
        nodes = game.m.get("graph", {}).get("nodes", {})
        for r in game.m.get("regions", []):
            node = nodes.get(r.get("sourceNoteId"))
            if node and node.get("community") == community:
                return r.get("name", self._titlecase(r.get("id", "?")))
        for f in game.m.get("bible", {}).get("factions", []):
            if f.get("clusterId") == community or f.get("id") == f"faction_{community}":
                return f.get("name", f"House {community}")
        return f"the realm of the {self._ordinal(community)} cluster"

    @staticmethod
    def _ordinal(i: int) -> str:
        return ORDINALS[i] if 0 <= i < len(ORDINALS) else f"{i + 1}th"

    # ---- lore synthesis ----
    def _synthesize(self, game) -> list[str]:
        nodes = game.m.get("graph", {}).get("nodes", {})
        lore: list[str] = []

        # 1) Foundings: group by community (ignore -1); oldest member founds it; order
        #    the Ages by founder age (ascending activity).
        communities: dict = {}
        for nid, nd in nodes.items():
            c = nd.get("community", -1)
            if c == -1:
                continue
            communities.setdefault(c, []).append(nid)
        founders = {
            c: min(members, key=lambda n: (nodes[n].get("activity", 0.0), n))
            for c, members in communities.items()
        }
        epoch_order = sorted(
            founders, key=lambda c: (nodes[founders[c]].get("activity", 0.0), c))
        for i, c in enumerate(epoch_order):
            founder = founders[c]
            lore.append(
                f"In the {self._ordinal(i)} Age, {self._title(game, founder)} "
                f"raised what would become {self._community_label(game, c)}.")

        # 2) Schisms: every bridge node opened a way between realms.
        for nid in sorted(n for n, nd in nodes.items() if nd.get("bridge")):
            lore.append(
                f"{self._title(game, nid)} opened the way between two realms — "
                f"the Schism that still bleeds.")

        # 3) Lost ages: orphan-role notes, plus anything upheaval swallowed.
        lost_ids = {n for n, nd in nodes.items() if nd.get("role") == "orphan"}
        lost_ids |= set(getattr(game.up, "lost", set()) or set())
        for nid in sorted(lost_ids):
            lore.append(
                f"{self._title(game, nid)} was lost to the dark; an age forgotten.")

        # 4) New Ages from live upheaval (only present when the world has shifted).
        for nid in sorted(getattr(game.up, "risen_regions", set()) or set()):
            lore.append(f"A new age dawns: {self._title(game, nid)} rises.")
        throne = getattr(game.up, "throne", None)
        if throne:
            lore.append(
                f"{self._title(game, throne)} ascends the throne of the deep.")

        return lore

    def _lore_target(self, game, item: dict):
        """Resolve the (note_id, region_id) a knowledge fragment points at.

        Bosses carry an explicit ``regionId``; a secret has none, so map its
        ``sourceNoteId``'s graph community -> the region whose faction owns that
        cluster (``faction_{community}``), or ``None`` if unowned/missing.
        Everything guarded: returns (note_or_None, region_id_or_None)."""
        note = None
        region_id = None
        try:
            note = item.get("sourceNoteId")
        except Exception:
            return None, None
        # Boss: a place is already known (depth-bearing item carries regionId).
        if "depth" in item or item.get("regionId"):
            return note, item.get("regionId")
        # Secret: derive a region from the note's community via its faction.
        community = None
        try:
            node = game.m.get("graph", {}).get("nodes", {}).get(note)
            if node is not None:
                community = node.get("community")
        except Exception:
            community = None
        if community is not None:
            fid = f"faction_{community}"
            try:
                for r in game.m.get("regions", []):
                    if r.get("factionId") == fid:
                        region_id = r.get("id")
                        break
            except Exception:
                region_id = None
        return note, region_id

    def _knowledge_line(self, item: dict) -> str:
        """Found lore also yields a navigational fact about a boss or secret."""
        if "depth" in item:  # boss
            return (f"The fragment tells of {item.get('name', 'a sleeper')}, "
                    f"sleeping on floor {item['depth']}.")
        # secret (no depth): describe its shape so the player knows what to hunt
        kind = str(item.get("kind", "secret")).replace("_", " ")
        flavor = item.get("flavor")
        if flavor:
            return f"The fragment whispers of a {kind}: {flavor}"
        return (f"The fragment whispers of a {kind} bound to "
                f"'{self._titlecase(item.get('sourceNoteId', '?'))}'.")

    # ---- lifecycle hooks ----
    def on_world_start(self, game):
        self.lore = self._synthesize(game)
        self.read = 0
        self._kidx = 0
        self.ground = {}
        # Bosses carry a depth (a place); secrets are shapes to seek. Reveal in order.
        self._knowledge = list(game.m.get("bosses", [])) + list(game.m.get("secrets", []))

    def on_floor_enter(self, game):
        self.ground = {}
        if self.read >= len(self.lore):  # the whole chronicle has been read
            return
        rng = random.Random(f"{game.seed}:{game.floor}:history")
        # A fragment surfaces on most floors, but not all — some ages stay buried.
        if rng.random() < 0.15:
            return
        free = free_floor_tiles(
            game.level, {(game.player.x, game.player.y), game.level.stairs})
        if not free:
            return
        x, y = rng.choice(free)
        self.ground[(x, y)] = self.lore[self.read]  # the next unread line

    def on_player_act(self, game):
        tile = (game.player.x, game.player.y)
        line = self.ground.pop(tile, None)
        if line is None:
            return
        game.log(f"You read a lore fragment: {line}")
        self.read += 1
        # Grant a piece of knowledge: the location/shape of an as-yet-unmentioned power.
        if self._knowledge:
            item = self._knowledge[self._kidx % len(self._knowledge)]
            game.log(self._knowledge_line(item))
            self._kidx += 1
            # Lore reveals the map: hand the named boss/secret region to the
            # knowledge system via the bus. Knowledge, never power. Guard the
            # whole thing so a busless/older Game still reads fragments fine.
            try:
                note, region_id = self._lore_target(game, item)
                emit = getattr(game, "emit", None)
                if callable(emit):
                    emit("lore_read", note=note, region_id=region_id)
            except Exception:
                pass

    # ---- rendering ----
    def render_overlay(self, game, grid):
        for (x, y) in self.ground:
            if 0 <= y < len(grid) and 0 <= x < len(grid[y]) and grid[y][x] == ".":
                grid[y][x] = self.GLYPH

    def status_line(self, game):
        return f"Lore: {self.read} read"
