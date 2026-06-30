"""Knowledge fog — the knowledge graph IS the fog of war.

Cogmind information-warfare meets Qud secrets: knowing a note reveals its linked
neighbors, so exploration is literally traversing your vault's real link graph.
Knowledge is a *resource* (navigation / information), never damage and never bigger
numbers. The only on-map glyph this system writes is `' '` (space) — it hides cells
you have neither walked near nor learned about, painting the unknown as empty void.

A region becomes "mapped" once its anchor note is in `self.known`; a mapped region is
shown in full, while an unknown region is veiled to a radius-4 window around the player
plus whatever tiles you have already explored on this floor.

Deterministic: no randomness is used. (If any were added, it would be seeded from
`game.seed` per the systems contract.)
"""
from __future__ import annotations

from .systems import System

RADIUS = 4  # Chebyshev sight radius around the player


class KnowledgeSystem(System):
    name = "knowledge"

    def __init__(self):
        # revealed note ids (the navigable knowledge frontier)
        self.known: set[str] = set()
        # explored tiles, per floor: {floor: {(x, y), ...}}
        self.seen: dict[int, set[tuple[int, int]]] = {}
        # last game we were attached to, so the param-less query API
        # (reveal / is_known, called by other systems) can resolve regions + graph.
        self.game = None

    # ---- helpers ----
    def _reveal(self, game, note_id):
        """Reveal a note and its graph neighbors. Guards missing / falsy ids."""
        if not note_id:
            return
        nodes = game.m.get("graph", {}).get("nodes", {})
        self.known.add(note_id)
        node = nodes.get(note_id)
        if not node:
            return
        for nb in node.get("neighbors", []):
            self.known.add(nb)

    def _region_by_id(self, game, target):
        """Return the region dict whose `id` == target, or None."""
        if game is None or not target:
            return None
        for r in game.m.get("regions", []):
            if r.get("id") == target:
                return r
        return None

    def _anchor(self, game):
        """sourceNoteId of the region owning the current floor."""
        region = game.region_for(game.floor)
        return region.get("sourceNoteId", "")

    def region_mapped(self, game) -> bool:
        """A region is 'mapped' once its anchor note has been learned."""
        return self._anchor(game) in self.known

    # ---- query API (other systems call these via game.system("knowledge")) ----
    def reveal(self, target) -> None:
        """Reveal a target that is EITHER a region id OR a note id.

        - region id (matches some `region["id"]`): mark that region mapped by
          learning its anchor `sourceNoteId` (+ that note's neighbors), so its
          floor renders in full once you arrive.
        - note id: learn the note (and its neighbors), extending the frontier.

        Param-less by contract; resolves the manifest via the stashed `self.game`.
        Degrades gracefully (no game / falsy target / unknown id)."""
        if not target:
            return
        game = self.game
        if game is None:
            # No world attached yet: best effort, just remember the raw id.
            self.known.add(target)
            return
        region = self._region_by_id(game, target)
        if region is not None:
            self._reveal(game, region.get("sourceNoteId", ""))
            return
        self._reveal(game, target)

    def is_known(self, note_id) -> bool:
        """True once `note_id` is on the revealed knowledge frontier."""
        return note_id in self.known

    # ---- lifecycle hooks ----
    def on_world_start(self, game):
        self.game = game
        self.known = set()
        self.seen = {}

    def on_floor_enter(self, game):
        self.game = game
        # Fog is real: you do NOT automatically know the floor you stand on — you reveal it
        # by exploring (line-of-sight radius below) or by *intel* (lore fragments, scavenged
        # hunter sensors, a trusting faction's map), which pre-light regions you've yet to
        # reach. Auto-revealing the anchor here would make the fog — and those rewards — moot.
        self.seen.setdefault(game.floor, set())

    def on_player_act(self, game):
        self.game = game
        seen = self.seen.setdefault(game.floor, set())
        px, py = game.player.x, game.player.y
        for dy in range(-RADIUS, RADIUS + 1):
            for dx in range(-RADIUS, RADIUS + 1):
                seen.add((px + dx, py + dy))

    # ---- cross-system bus ----
    def on_event(self, game, etype, data):
        """Knowledge is fed by the bus: kills scavenge sensors, lore names places."""
        self.game = game
        data = data or {}
        if etype == "enemy_killed":
            # you learn from the kill: the foe's source note (+ neighbors) light up
            enemy = data.get("enemy")
            if enemy is not None:
                self._reveal(game, getattr(enemy, "source", ""))
        elif etype == "lore_read":
            # a fragment names a region/boss -> reveal it (and the note that named it)
            self.reveal(data.get("region_id"))
            note = data.get("note")
            if note:
                self.reveal(note)

    # ---- rendering ----
    def render_overlay(self, game, grid):
        # mapped region -> the whole floor is legible; fog does nothing
        if self.region_mapped(game):
            return
        seen = self.seen.get(game.floor, set())
        px, py = game.player.x, game.player.y
        for y, row in enumerate(grid):
            for x in range(len(row)):
                near = abs(x - px) <= RADIUS and abs(y - py) <= RADIUS
                if not near and (x, y) not in seen:
                    row[x] = " "
        # the player can always see their own tile
        if 0 <= py < len(grid) and 0 <= px < len(grid[py]):
            grid[py][px] = game.player.glyph

    def status_line(self, game):
        nodes = game.m["graph"]["nodes"]
        # count only real notes (kills of lost-note echoes can inject ghost ids)
        mapped = len(self.known & set(nodes))
        return f"Mapped: {mapped}/{len(nodes)} ideas"
