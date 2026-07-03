"""Knowledge fog — the knowledge graph IS the fog of war.

Cogmind information-warfare meets Qud secrets: knowing a note reveals its linked
neighbors, so exploration is literally traversing your vault's real link graph.
Knowledge is a *resource* (navigation / information), never damage and never bigger
numbers. The only on-map glyph this system writes is `' '` (space) — it hides cells
you have neither walked near nor learned about, painting the unknown as empty void.

A region becomes "mapped" once its anchor note is DIRECTLY learned (`self.learned`):
by intel that names it (lore, a hacked terminal, scavenged sensors) or by felling its
boss. Intel only pre-maps regions AHEAD; naming the region you stand in extends the
frontier without mapping, so the fog where you are is walked off, never read off.
Ordinary kills, anchor-sourced or not, only extend the navigable frontier
(`self.known`); they never map. And mapped means MAPPED, not omniscient: the region's
terrain renders in full, while actors, loot, and overlays beyond your sight radius
stay fogged. An unknown region is veiled to a radius-4 window around the player plus
whatever tiles you have already explored on this floor.

Deterministic: no randomness is used. (If any were added, it would be seeded from
`game.seed` per the systems contract.)
"""
from __future__ import annotations

from .systems import System

RADIUS = 4          # base Chebyshev sight radius (the dark DEPTHS: fog is tension)
SURFACE_RADIUS = 12  # the open SURFACE: you see the vista you wander (exploration)


class KnowledgeSystem(System):
    name = "knowledge"

    def __init__(self):
        # revealed note ids (the navigable knowledge frontier)
        self.known: set[str] = set()
        # ids revealed DIRECTLY (intel / the note's own kill), not by neighbor splash;
        # only these can map a region and lift its fog
        self.learned: set[str] = set()
        # explored tiles, per floor: {floor: {(x, y), ...}}
        self.seen: dict[int, set[tuple[int, int]]] = {}
        # last game we were attached to, so the param-less query API
        # (reveal / is_known, called by other systems) can resolve regions + graph.
        self.game = None

    # ---- helpers ----
    def _reveal(self, game, note_id, direct=True):
        """Reveal a note and its graph neighbors. Guards missing / falsy ids.
        `direct=False` (an ordinary kill) extends the frontier without the
        map-granting `learned` mark; splash never maps a region either way."""
        if not note_id:
            return
        nodes = game.m.get("graph", {}).get("nodes", {})
        self.known.add(note_id)
        if direct:
            self.learned.add(note_id)
        node = nodes.get(note_id)
        if not node:
            return
        for nb in node.get("neighbors", []):
            self.known.add(nb)   # frontier only: splash never maps a region

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
        """A region is 'mapped' once its anchor note has been DIRECTLY learned."""
        anchor = self._anchor(game)
        return anchor in self.learned and anchor in self.known

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
            self.learned.add(target)
            return
        # Intel pre-maps the road AHEAD; the ground you stand on must be walked
        # (or taken from its boss). Without this, a lore fragment naming the
        # current region would delete the fog for its whole depth band.
        current_anchor = self._anchor(game)
        region = self._region_by_id(game, target)
        if region is not None:
            nid = region.get("sourceNoteId", "")
            self._reveal(game, nid, direct=(nid != current_anchor))
            return
        self._reveal(game, target, direct=(target != current_anchor))

    def is_known(self, note_id) -> bool:
        """True once `note_id` is on the revealed knowledge frontier."""
        return note_id in self.known

    # ---- lifecycle hooks ----
    def on_world_start(self, game):
        self.game = game
        self.known = set()
        self.learned = set()
        self.seen = {}

    def on_floor_enter(self, game):
        self.game = game
        # Fog is real: you do NOT automatically know the floor you stand on — you reveal it
        # by exploring (line-of-sight radius below) or by *intel* (lore fragments, scavenged
        # hunter sensors, a trusting faction's map), which pre-light regions you've yet to
        # reach. Auto-revealing the anchor here would make the fog — and those rewards — moot.
        self.seen.setdefault(game.floor, set())
        if self.region_mapped(game):
            # tell the player WHY this floor arrives already legible
            game.log("You know this ground's shape; its map unfurls in your mind.")

    def _sight(self, game) -> int:
        """Sight radius. Generous on the open SURFACE (you wander a vista), tighter in
        the dark DEPTHS (fog is dread); widened further by the 'lantern' effect."""
        base = SURFACE_RADIUS if getattr(game, "_on_surface", lambda: False)() else RADIUS
        eff = game.system("effects")
        return base + (eff.perception_bonus(game) if eff is not None else 0)

    def on_player_act(self, game):
        self.game = game
        seen = self.seen.setdefault(game.floor, set())
        px, py = game.player.x, game.player.y
        r = self._sight(game)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                seen.add((px + dx, py + dy))

    # ---- cross-system bus ----
    def on_event(self, game, etype, data):
        """Knowledge is fed by the bus: kills scavenge sensors, lore names places."""
        self.game = game
        data = data or {}
        if etype == "enemy_killed":
            # you learn from the kill: the foe's source note (+ neighbors) join the
            # frontier. Only a BOSS kill is intel deep enough to map its region.
            enemy = data.get("enemy")
            if enemy is not None:
                self._reveal(game, getattr(enemy, "source", ""),
                             direct=getattr(enemy, "is_boss", False))
        elif etype == "lore_read":
            # a fragment names a region/boss -> reveal it (and the note that named it)
            self.reveal(data.get("region_id"))
            note = data.get("note")
            if note:
                self.reveal(note)

    # ---- rendering ----
    def render_overlay(self, game, grid):
        # A mapped region shows its TERRAIN (that is what a map gives you); actors,
        # loot, and overlays beyond your sight stay fogged, so intel never becomes
        # a wallhack. An unmapped region blanks the far unknown entirely.
        eff = game.system("effects")
        if eff is not None and eff.all_seen(game):
            return   # 'eyeless': you dream the whole place; no fog at all
        mapped = self.region_mapped(game)
        tiles = game.level.tiles
        seen = self.seen.get(game.floor, set())
        px, py = game.player.x, game.player.y
        r = self._sight(game)
        # the SURFACE is a daylit vista: open sky hides no terrain, so the far world
        # shows its ground and standing structures (things to walk TOWARD). What stays
        # veiled beyond sight is everything that lives, moves, or can be taken. The
        # depths keep hard fog: there, the dark is the point.
        surface = getattr(game, "_on_surface", lambda: False)()
        overlay = getattr(game, "_overlay", {})
        for y, row in enumerate(grid):
            for x in range(len(row)):
                near = abs(x - px) <= r and abs(y - py) <= r
                if not near and (x, y) not in seen:
                    if surface:
                        row[x] = overlay.get((x, y)) if tiles[y][x] == "." else None
                        row[x] = row[x] or tiles[y][x]
                    else:
                        row[x] = tiles[y][x] if mapped else " "
        # the player can always see their own tile
        if 0 <= py < len(grid) and 0 <= px < len(grid[py]):
            grid[py][px] = game.player.glyph

    def status_line(self, game):
        nodes = game.m["graph"]["nodes"]
        # count only real notes (kills of lost-note echoes can inject ghost ids)
        mapped = len(self.known & set(nodes))
        return f"Mapped: {mapped}/{len(nodes)} ideas"
