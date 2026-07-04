"""Turn-based game state: spawning from the manifest, bump combat, permadeath, descent.

Rendering returns a plain string so the engine is front-end agnostic (the auto-demo
prints it; the curses front-end draws the same buffer).
"""
from __future__ import annotations

import json
import random

from .dungeon import free_floor_tiles, generate_level
from .entities import apply_item, make_boss, make_enemy, make_item, make_player
from .sense import make_brain
from .upheaval import Upheaval, diminish, empower, make_echo, title as _title

MAP_W, MAP_H = 56, 20

# a room's noun follows its note's graph role, so the map reads as the vault's shape
ROOM_NOUN = {"hub": "Hall", "bridge": "Gallery", "orphan": "Sealed Alcove",
             "leaf": "Cell", "cluster": "Chamber"}

# communion with the deepest thought: either path resolves the run without violence
COMMUNE_TRUTHS = 3   # marginalia + lore fragments read
COMMUNE_COST = 8     # total salvaged matter, any mix
BECALM_COST = 2      # matter per tier to placate a lesser hostile
LEASH = 3            # sandbox: a creature's territory (and pursuit range) around home
FRIEND_STANDING = 4  # reputation at which a house stops fighting the one you control


def _spend_matter(bag, total: int) -> dict:
    """Build and pay a cost of `total` matter from the richest materials first.
    Caller must have checked bag.total() >= total."""
    cost, need = {}, total
    for m, q in sorted(bag.comp.items(), key=lambda kv: (-kv[1], kv[0])):
        cost[m] = min(q, need)
        need -= cost[m]
        if not need:
            break
    bag.pay(cost)
    return cost


class _Place:
    """A grown center's footprint, quacking like a dungeon.Room for the systems
    that ask a place for `contains` / `center` (sigils, machines, dialogue)."""

    def __init__(self, cells, focus):
        self.cells = cells          # set[(x, y)]
        self.center = focus         # a representative interior tile

    def contains(self, x: int, y: int) -> bool:
        return (x, y) in self.cells


class Game:
    def __init__(self, manifest: dict, width: int = MAP_W, height: int = MAP_H,
                 upheaval=None, systems=None, sandbox: bool = False,
                 site_cache: str = None, sprawl: float = 1.0):
        self.site_cache = site_cache   # path for the grown-world cache (sandbox)
        self.sprawl = max(1.0, float(sprawl))
        self.m = manifest
        self.up = upheaval or Upheaval()
        self.systems = systems or []
        self.sandbox = sandbox
        self.announced: set = set()
        self._flavored: set = set()   # note ids whose flavor has been shown once
        self._truths_spent = 0        # read truths traded away via confide()
        self.seed = manifest["seed"]
        self.width, self.height = width, height
        self.floor = 0
        self.max_floor = max((b["depth"] for b in manifest["bosses"]), default=1)
        self.final_boss_source = max(manifest["bosses"], key=lambda b: b["depth"])["sourceNoteId"]
        self.enemies_by_region: dict = {}
        for e in manifest["enemies"]:
            self.enemies_by_region.setdefault(e["regionId"], []).append(e)
        self.messages: list = []
        self._last_logged = None   # dedup: last line appended (folds repeats to "xN")
        self._dup_n = 1
        self._last_was_ambient = False   # newest log line was mood, not an event
        self.turn = 0           # advances each player action; drives perception caching
        self.kills = 0
        self.items_taken = 0
        self.alive = True
        self.won = False
        self.player = None
        self.level = None
        self.actors: list = []
        self.items: list = []
        self.region_name = ""
        self._places: list = []       # sandbox: [(cells, note_id)] per grown center
        self._dungeon = None          # {"region": r} while in a depths-realm
        self._realm = "surface"       # current node of the realm semilattice
        self._realms: dict = {}       # realm id -> persisted snapshot
        self._gates: dict = {}        # (x, y) -> destination realm id, current map
        self._town_rooms: set = set()
        self._town_tiles: set = set()
        self._tint: dict = {}         # (x, y) -> region element, for place-local palettes
        self._cell_region: dict = {}  # (x, y) -> region id (border detection)
        self._glow_cells: dict = {}   # (x, y) -> intensity (light rises toward the heart)
        self._landmarks: dict = {}    # (x, y) -> "heart" | "town" | "gate" (seen through fog)
        self._frictions: dict = {}    # wall (x, y) -> stance between the regions it parts
        self._overlay: dict = {}      # (x, y) -> biome/structure glyph, drawn over floor
        self._region_env: dict = {}   # region id -> Environment (blended design blocks)
        self._region_kind: dict = {}  # region id -> area kind (labyrinth/grove/...)
        self._region_by_comm = {self._region_community(r): r
                                for r in manifest["regions"]}
        self._region_faction = {r["id"]: r.get("factionId", "")
                                for r in manifest["regions"]}
        self._rel: dict = {}          # (factionA, factionB) -> stance, both ways
        for f in manifest.get("bible", {}).get("factions", []):
            for r in f.get("relations", []):
                self._rel[(f["id"], r["factionId"])] = r["stance"]
                self._rel[(r["factionId"], f["id"])] = r["stance"]
        self._build_zones()
        for s in self.systems:
            s.on_world_start(self)
        if self.up.total:
            self.messages.append(
                f"~ The world has shifted since you last descended: {self.up.total} upheaval(s). ~")
        if sandbox:
            self._build_sandbox()
        else:
            self.descend()  # enter floor 1

    # ---- content selection ----
    def _build_zones(self):
        # Region depth bands (min..max member depth) can overlap and even span the whole
        # descent, so "first band that contains the floor" lets one region monopolize
        # everything. Instead, carve contiguous zones: each region owns the floors up to
        # its boss's depth. This guarantees every region -- including newly risen ones --
        # is reachable, and that each boss sits inside its own zone.
        region_by_id = {r["id"]: r for r in self.m["regions"]}
        zones = [(b["depth"], region_by_id[b["regionId"]])
                 for b in self.m["bosses"] if b["regionId"] in region_by_id]
        zones.sort(key=lambda z: z[0])
        self._zones = zones

    def region_for(self, floor: int) -> dict:
        if self._dungeon is not None:
            return self._dungeon["region"]
        if self.sandbox and self.player is not None:
            # positional: the region of the district you stand in
            idx = self.room_at(self.player.x, self.player.y)
            nid = self.room_notes.get(idx) if idx is not None else None
            node = self.m["graph"]["nodes"].get(nid) if nid else None
            if node is not None:
                r = self._region_by_comm.get(node.get("community"))
                if r is not None:
                    return r
            # between districts: keep the last named region
            for r in self.m["regions"]:
                if r["name"] == self.region_name:
                    return r
            return self.m["regions"][0]
        for depth, r in self._zones:
            if floor <= depth:
                return r
        if self._zones:
            return self._zones[-1][1]
        return self.m["regions"][0]

    def _ambient_tick(self):
        """Once in a while, the place you stand in murmurs its atmosphere — a
        sensory line from its blended environment (blocks.py voice). Deterministic
        by turn, gentle (roughly 1 in 11 steps), so the world feels alive without
        spamming. Silence is used, not filled."""
        if not self._on_surface() or self.turn % 11 != 0:
            return
        r = self.region_for(self.floor)
        env = self._region_env.get(r["id"]) if r else None
        if env is None:
            return
        lines = list(env.voice())
        # the AREA KIND speaks too: a labyrinth's disorientation, a market's crowd —
        # its lines join the region's own so a place-of-a-kind sounds like one.
        if r:
            from .arch import areakinds
            lines += areakinds.voice(self._region_kind.get(r["id"], "wilds"))
        if lines:
            self.log(lines[(self.turn // 11) % len(lines)], ambient=True)

    def _connected_graph(self) -> dict:
        """The graph with unlinked orphans removed, so only connected notes grow
        into buildings. Orphans (degree 0) are placed as wild landmarks instead.
        If a vault is ALL orphans, keep them all (never grow an empty world)."""
        g = self.m["graph"]
        nodes = g.get("nodes", {})
        keep = {nid for nid, n in nodes.items() if n.get("degree", 0) > 0}
        if len(keep) < 3:
            return g   # too sparse to prune; let everything be a building
        return {
            "nodes": {nid: n for nid, n in nodes.items() if nid in keep},
            "edges": [e for e in g.get("edges", [])
                      if e.get("a") in keep and e.get("b") in keep],
        }

    # ---- sandbox: one grown world (ARCHITECTURE_SPEC §8) ----
    def _load_site(self):
        """Cached grown world, if fresh (same seed). Growth on a large vault takes
        ~20s; the cache makes every later launch instant."""
        if not self.site_cache:
            return None
        try:
            with open(self.site_cache, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if (d.get("seed") != self.seed or d.get("sprawl", 1.0) != self.sprawl
                    or d.get("fmt") != 9):
                return None
            from .dungeon import Level
            level = Level(w=d["w"], h=d["h"],
                          tiles=[list(row) for row in d["tiles"]], rooms=[],
                          player_start=tuple(d["player_start"]),
                          stairs=tuple(d["stairs"]))

            class C:   # a cached center quacks enough like arch.model.Center
                pass
            placed = []
            for cd in d["centers"]:
                c = C()
                c.id = cd["id"]
                c.pos = tuple(cd["pos"])
                c.footprint = [tuple(t) for t in cd["footprint"]]
                c.intensity = cd["intensity"]
                c.motifs = [tuple(m) for m in cd["motifs"]]
                placed.append(c)
            return level, placed
        except Exception:
            return None   # any staleness/corruption: just regrow

    def _save_site(self, level, placed):
        if not self.site_cache:
            return
        try:
            with open(self.site_cache, "w", encoding="utf-8") as fh:
                json.dump({"seed": self.seed, "sprawl": self.sprawl, "fmt": 9,
                           "w": level.w, "h": level.h,
                           "tiles": ["".join(r) for r in level.tiles],
                           "player_start": list(level.player_start),
                           "stairs": list(level.stairs),
                           "centers": [{"id": c.id, "pos": list(map(int, c.pos)),
                                        "footprint": [list(t) for t in c.footprint],
                                        "intensity": c.intensity,
                                        "motifs": [list(m) for m in
                                                   getattr(c, "motifs", [])]}
                                       for c in placed]}, fh)
        except OSError:
            pass   # an unwritable cache dir costs a regrow next time, nothing more

    def _build_sandbox(self):
        """The whole vault as a single grown semilattice structure. No floors:
        depth = centrality becomes SPATIAL. You start at the periphery; the
        deepest thought holds the greatest center. Walk inward."""
        self.floor = 1
        # each region's AREA KIND (labyrinth, grove, flooded, ...) — a nature-biased
        # roll from its anchor note. Kinds fold favored blocks into the environment
        # (flavor), add ambient voice, modify sight, and may reshape the region's
        # LAYOUT. Deterministic; computed before settle so shapes bake into the cache.
        from .arch import areakinds
        self._region_kind = {}
        for r in self.m["regions"]:
            node = self.m["graph"]["nodes"].get(r.get("sourceNoteId"), {})
            self._region_kind[r["id"]] = areakinds.kind_for(r, node, self.seed)

        cached = self._load_site()
        if cached is not None:
            self.level, placed = cached
        else:
            from .arch.grow import grow
            from .arch.settle import settle
            # only CONNECTED notes become buildings; unlinked orphans are strewn
            # across the wild as landmarks (below), so the settlements are the real
            # structure of your vault and the between is full of discoveries.
            plan = grow(self._connected_graph(), seed=self.seed, sprawl=self.sprawl)
            self.level = settle(plan, seed=self.seed)
            placed = sorted(plan.placed(), key=lambda c: c.id)
            self._save_site(self.level, placed)
        self.room_notes = {}
        self._motifs = {}     # room idx -> phrases from the interior patterns
        self._fixtures = {}   # room idx -> [(x, y)] focal-feature tiles (altar, shelf…)
        self._fixture_room = {}  # (x, y) -> room idx, for examine / anchoring
        for i, c in enumerate(placed):
            cells = set(map(tuple, c.footprint))
            focus = tuple(map(int, c.pos)) if c.pos else next(iter(sorted(cells)))
            self._places.append((_Place(cells, focus), c))
            self.room_notes[i] = c.id
            self._motifs[i] = [m[1] for m in getattr(c, "motifs", [])]
            feats = [tuple(t) for m in getattr(c, "motifs", [])
                     for t in (m[2] if len(m) > 2 else [])]
            self._fixtures[i] = feats
            for t in feats:
                self._fixture_room[t] = i
        self._rooms_seen = set()

        px, py = self.level.player_start
        self.player = make_player(px, py)
        self.actors, self.items = [], []
        self.region_name = self.region_for(1)["name"]
        self._build_tint()

        rng = random.Random(f"{self.seed}:sandbox")
        intensity = {c.id: c.intensity for c in placed}
        free = free_floor_tiles(self.level, {(px, py), self.level.stairs})
        rng.shuffle(free)

        # every foe dwells at its own note's center; power grows toward the heart
        # (quadratic in intensity, so the periphery stays genuinely gentle). The
        # entrance center keeps no dweller: where you arrive is yours.
        start_note = self.room_notes.get(self.room_at(px, py))
        for spec in sorted(self.m["enemies"], key=lambda e: e["id"]):
            if not free:
                break
            if spec["sourceNoteId"] == start_note:
                continue
            inten = intensity.get(spec["sourceNoteId"], 0.0)
            cap = 1 + int(3 * inten * inten)
            spec = {**spec, "tier": max(1, min(spec["tier"], cap))}
            en = make_enemy(spec, *self.spot_for(spec["sourceNoteId"], free))
            en.faction = self._region_faction.get(spec.get("regionId", ""), "")
            en._home = (en.x, en.y)   # territorial: it belongs to its note's ground
            if spec["sourceNoteId"] in self.up.ascended:
                empower(en)
            elif spec["sourceNoteId"] in self.up.waned:
                diminish(en)
            self.actors.append(en)
        # towns & doors (the JRPG realms; Alexander: activity nodes + the intimacy
        # gradient): each district's anchor room is SETTLED ground -- safe, restful,
        # kept -- and holds the door (>) down into the region's depths, where its
        # warden waits at the bottom. Bosses no longer stand in the open.
        self._town_rooms, self._town_tiles = set(), set()
        self._gates = {}
        for r in self.m["regions"]:
            anchor = r.get("sourceNoteId", "")
            idx = next((i for i, nid in self.room_notes.items() if nid == anchor),
                       None)
            if idx is None:
                continue
            self._town_rooms.add(idx)
            tiles = self.room_tiles(idx)
            self._town_tiles |= set(tiles)
            room = self._places[idx][0]
            door = (room.center if self.level.walkable(*room.center)
                    else tiles[len(tiles) // 2])
            self.level.tiles[door[1]][door[0]] = ">"
            self._gates[door] = r["id"]
        # where you WAKE is settled ground too — nothing ambushes you at the start
        start_idx = self.room_at(px, py)
        if start_idx is not None:
            self._town_rooms.add(start_idx)
            self._town_tiles |= set(self.room_tiles(start_idx))
        free = [t for t in free if t not in self._town_tiles]
        self._build_felt()
        # the WILD breathes: biome-paint the whole between so travelling through
        # your vault's regions feels different underfoot (charged waste / wet fen /
        # sacred grove...), not a dead uniform plain. Voronoi region map is reused
        # by the structure/scene/ambient layers.
        from .arch.terrain import paint_biomes, place_wild_structures
        from .arch.blocks import environment_for
        # each region's ATMOSPHERE is a blend of design blocks (element + biome + anchor
        # role), ordered by dominance — the "playset" that permutes into a distinct vibe
        # per region. Kept for the renderer (palette) and ambient voice.
        from .arch import areakinds
        self._region_env = {}
        for r in self.m["regions"]:
            anchor = self.m["graph"]["nodes"].get(r.get("sourceNoteId"), {})
            kind = self._region_kind.get(r["id"], "wilds")
            self._region_env[r["id"]] = environment_for(
                r.get("element", "inert"), r.get("biome"), anchor.get("role"),
                favors=areakinds.favors(kind))
        # an area kind may RESHAPE its region's layout (a labyrinth's maze walls, a
        # flooded ruin's pools). Deterministic, re-applied on cached loads too, and
        # only ever touches a region's own INTERIOR floor, so the world stays whole
        # (settle already ran _ensure_connected; we re-verify after).
        self._apply_area_shapes()
        # biomes + wild structures are OVERLAYS (drawn by the renderer), never baked
        # into level.tiles, so spawning/pathing/cache stay identical fresh-vs-cached.
        # Buildings anchor the fill: settled ground is dense, deep wild tapers to open.
        building_cells = [t for pl, _c in self._places for t in pl.cells]
        biome, self._region_of = paint_biomes(self.level, self._cell_region,
                                              self._region_env, building_cells,
                                              seed=f"{self.seed}:biome")
        reserved = {(px, py)} | set(self._gates) | {(a.x, a.y) for a in self.actors}
        homed = set(self.room_notes.values())
        orphans = [(nid, n) for nid, n in sorted(self.m["graph"]["nodes"].items())
                   if nid not in homed and n.get("degree", 0) == 0]
        sglyphs, self._wild_structs = place_wild_structures(
            self.level, self._region_of, orphans, reserved, seed=self.seed)
        # one overlay the renderer paints over floor: biome terrain + wild landmarks.
        # Deterministic from the seed, so it regenerates identically fresh-or-cached.
        self._overlay = dict(biome)
        self._overlay.update(sglyphs)
        from .arch.blocks import BLOCK_GLYPHS, BLOCK_NOUN
        self._block_glyphs = BLOCK_GLYPHS
        self._block_noun = BLOCK_NOUN
        # BEACONS: wild landmarks show through the fog as faint targets to walk toward,
        # so a shrine two screens off is a reason to go THERE (orientation, not blind
        # wandering). Reuses the _landmarks-through-fog loop the hearts/gates use.
        for pos in self._wild_structs:
            self._landmarks[pos] = "wild"
        # you should WAKE where you can walk out — not boxed in a building interior.
        # relocate the spawn to open ground on/beside a road at the settlement edge, so
        # the whole world is reachable from step one (exploration, not a cell).
        self._relocate_spawn()
        for note in sorted(n for ns in self.up.lost_floor.values() for n in ns):
            if not free:
                break
            self.actors.append(make_echo(note, *self.spot_for(note, free)))

        # arrival is a threshold, not a manual: the world's name, where you stand,
        # and ONE line in the note's own voice. Rules live in the sidebar/help.
        # (design-panel step 6: stop opening with an exposition dump.)
        world = self.m.get("bible", {}).get("worldName", "the vault")
        self.log(f"-- {world} --")
        idx = self.room_at(self.player.x, self.player.y)
        if idx is not None:
            self._rooms_seen.add(idx)
            label = self.room_label(idx)
            if label:
                self.log(f"You wake in {label}.")
            voice = self._weave_note(self.room_notes.get(idx))
        else:
            # you wake on open ground now: the first voice is the region's own
            # anchor note. Recognition from minute zero, in the author's words.
            region = self.region_for(1)
            voice = self._weave_note(region.get("sourceNoteId", ""))
        if voice:
            self.log(f'It murmurs: "{voice}"')
        for s in self.systems:
            s.on_floor_enter(self)

    def _apply_area_shapes(self):
        """Run each region's area-kind layout transform (maze walls, flooding) on its
        own cells, then re-verify the whole level stays connected. Deterministic:
        seeded per region; re-applied identically on cached loads."""
        from .arch import areakinds
        from .arch.terrain import region_map_only
        # flood region ids to every floor tile (the transform needs full region cells)
        region_of = region_map_only(self.level, self._cell_region)
        cells_by_region: dict = {}
        for cell, rid in region_of.items():
            if self.level.tiles[cell[1]][cell[0]] != "#":
                cells_by_region.setdefault(rid, []).append(cell)
        shaped = False
        for rid, cells in sorted(cells_by_region.items(), key=lambda kv: str(kv[0])):
            fn = areakinds.shape(self._region_kind.get(rid, "wilds"))
            if fn is None:
                continue
            rng = random.Random(f"{self.seed}:areashape:{rid}")
            fn(self.level.tiles, sorted(cells), rng, self.level.w, self.level.h)
            shaped = True
        if shaped:
            # the maze/flood is walls; guarantee the world is still one body
            from .arch.carve import _ensure_connected
            placed = [c for _pl, c in self._places]
            _ensure_connected(self.level.tiles, (self.player.x, self.player.y),
                              placed, self.level.w, self.level.h)

    def _relocate_spawn(self):
        """Move the player to open ground beside a road, at the edge of the start
        settlement, so you wake somewhere you can immediately explore FROM (not walled
        into a building). Prefers a road-adjacent open floor tile with room to move."""
        px, py = self.player.x, self.player.y
        roads = [(x, y) for y in range(self.level.h) for x in range(self.level.w)
                 if self.level.tiles[y][x] == "░"]
        if not roads:
            return
        # candidate: open floor tiles adjacent to a road, not inside a building
        def open_around(t):
            return sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                       if self.level.walkable(t[0] + dx, t[1] + dy)
                       and self.level.tiles[t[1] + dy][t[0] + dx] not in "#")
        monsters = [(a.x, a.y) for a in self.actors if a.allegiance == "monster"]

        def foe_dist(t):
            return min((abs(t[0] - mx) + abs(t[1] - my) for mx, my in monsters),
                       default=999)
        best = None
        # strict first (roomy, well clear of creatures); relax on small/cramped
        # worlds rather than silently leaving the player boxed in a building
        for min_open, min_foe in ((6, 8), (5, 4), (3, 2)):
            for rx, ry in roads:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    t = (rx + dx, ry + dy)
                    if (0 <= t[0] < self.level.w and 0 <= t[1] < self.level.h
                            and self.level.tiles[t[1]][t[0]] == "."
                            and self.room_at(*t) is None
                            and open_around(t) >= min_open
                            and foe_dist(t) >= min_foe):   # wake clear of creatures
                        d = abs(t[0] - px) + abs(t[1] - py)
                        if best is None or d < best[0]:
                            best = (d, t)
            if best is not None:
                break
        if best is not None:
            self.player.x, self.player.y = best[1]
            # the spot was already chosen clear of creatures (foe_dist filter above);
            # mark the clearing around it settled so nothing hostile crosses in while
            # you get your bearings.
            bx, by = best[1]
            for dx in range(-4, 5):
                for dy in range(-4, 5):
                    t = (bx + dx, by + dy)
                    if self.level.walkable(*t) and self.room_at(*t) is None:
                        self._town_tiles.add(t)

    def _interest_near(self, x, y) -> bool:
        """True if a discovery is adjacent to (x,y): a cache, a wild landmark, a gate,
        a system ground-point, or an actor — the stride slows so you don't glide past."""
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                t = (x + dx, y + dy)
                if (t in self._gates or t in getattr(self, "_wild_structs", {})
                        or self.actor_at(*t) is not None):
                    return True
                for s in self.systems:
                    if t in getattr(s, "caches", {}) or t in getattr(s, "ground", {}):
                        return True
        return False

    def log(self, msg: str, ambient: bool = False):
        # every log line is a sentence; names now begin with "the ..." so the first
        # letter is capitalized here, once, instead of at 16 call sites
        for i, ch in enumerate(msg):
            if ch != " ":
                if ch.islower():
                    msg = msg[:i] + ch.upper() + msg[i + 1:]
                break
        # ambient (weather/atmosphere) lines are mood, not events: they don't halt a
        # travel-glide. Track the count so a front-end can tell if the newest line is one.
        self._last_was_ambient = ambient
        # dedup consecutive identical lines (ambient systems can repeat verbatim):
        # fold a run into a "(xN)" suffix so it reads as one event, not a stuck machine.
        if self.messages and (self.messages[-1] == msg or self._last_logged == msg):
            self._dup_n += 1
            self.messages[-1] = msg if self._dup_n == 1 else f"{msg} (x{self._dup_n})"
            return
        self._last_logged = msg
        self._dup_n = 1
        self.messages.append(msg)

    # ---- realms & thresholds: the world is a SEMILATTICE of maps -------------
    # One flat map is still a tree (branches on a plane); a chain of floors is
    # still a tree. The realm graph is neither: the surface plus one
    # depths-realm per region, where town doors (>) go down, stairs (<) come
    # back up, and underground PASSAGES (>) join the depths of BORDERING
    # regions -- the bridge notes made spatial. Loops abound: down in one
    # district, across below, up in another. Realms persist: what you kill
    # stays dead. (Alexander: gateways as thresholds, the intimacy gradient,
    # and a city that is not a tree -- now true of the map-graph itself.)

    def _region_adjacency(self) -> dict:
        nodes = self.m.get("graph", {}).get("nodes", {})
        adj: dict = {}
        for e in self.m.get("graph", {}).get("edges", []):
            ra = self._region_by_comm.get(nodes.get(e["a"], {}).get("community"))
            rb = self._region_by_comm.get(nodes.get(e["b"], {}).get("community"))
            if ra is None or rb is None or ra["id"] == rb["id"]:
                continue
            adj.setdefault(ra["id"], set()).add(rb["id"])
            adj.setdefault(rb["id"], set()).add(ra["id"])
        return adj

    def _snapshot(self) -> dict:
        return {"level": self.level, "actors": self.actors, "items": self.items,
                "room_notes": self.room_notes, "places": self._places,
                "motifs": self._motifs, "tint": self._tint,
                "rooms_seen": self._rooms_seen, "region_name": self.region_name,
                "gates": self._gates, "towns": (self._town_rooms, self._town_tiles),
                "dungeon": self._dungeon, "floor": self.floor,
                "felt": (self._glow_cells, self._landmarks, self._frictions,
                         self._cell_region),
                "wild": (getattr(self, "_wild_structs", {}),
                         getattr(self, "_region_of", {}),
                         getattr(self, "_fixtures", {}),
                         getattr(self, "_fixture_room", {})),
                # the render overlay + per-region environments are realm-specific
                # (depths clears _overlay to {}); without these a surface return
                # comes back with blank biome terrain and the wrong ambient voice.
                "overlay": (getattr(self, "_overlay", {}),
                            getattr(self, "_region_env", {})),
                "pos": (self.player.x, self.player.y)}

    def _restore(self, s: dict, arrive=None):
        self.level, self.actors, self.items = s["level"], s["actors"], s["items"]
        self.room_notes, self._places = s["room_notes"], s["places"]
        self._motifs, self._tint = s["motifs"], s["tint"]
        self._rooms_seen, self.region_name = s["rooms_seen"], s["region_name"]
        self._gates = s["gates"]
        self._town_rooms, self._town_tiles = s["towns"]
        self._dungeon, self.floor = s["dungeon"], s["floor"]
        (self._glow_cells, self._landmarks,
         self._frictions, self._cell_region) = s["felt"]
        (self._wild_structs, self._region_of,
         self._fixtures, self._fixture_room) = s.get("wild", ({}, {}, {}, {}))
        self._overlay, self._region_env = s.get("overlay", ({}, {}))
        self.player.x, self.player.y = arrive or s["pos"]

    def traverse(self) -> bool:
        """Pass through the gate underfoot to its realm. Returns False if there
        is no gate here."""
        target = self._gates.get((self.player.x, self.player.y))
        if target is None:
            return False
        here = self._realm
        self._realms[here] = self._snapshot()
        self._realm = target
        if target in self._realms:
            snap = self._realms[target]
            arrive = next((p for p, dst in sorted(snap["gates"].items())
                           if dst == here), None)
            self._restore(snap, arrive=arrive)
        else:
            self._generate_depths(target, from_realm=here)
        self.log(f"-- You cross the threshold into {self.region_name}. --")
        for s in self.systems:
            s.on_floor_enter(self)
        return True

    def _generate_depths(self, region_id: str, from_realm: str):
        """First visit to a region's depths: one map, its notes as rooms, its
        warden in the anchor room, a stair up (<) and a passage (>) to each
        bordering region's depths."""
        region = next(r for r in self.m["regions"] if r["id"] == region_id)
        self._dungeon = {"region": region}
        order = sorted(r["id"] for r in self.m["regions"])
        self.floor = 2 + order.index(region_id)   # a stable seed-space per realm
        self.level = generate_level(max(64, self.width), max(26, self.height),
                                    f"{self.seed}:depths:{region_id}", 1,
                                    max_rooms=10)
        self._town_rooms, self._town_tiles = set(), set()
        self.region_name = region["name"]
        self._assign_rooms(region)
        self._motifs, self._fixtures, self._fixture_room = {}, {}, {}
        self._wild_structs, self._region_of, self._overlay = {}, {}, {}
        rng = random.Random(f"{self.seed}:depths:{region_id}:spawn")
        px, py = self.level.player_start
        free = free_floor_tiles(self.level, {(px, py), self.level.stairs})
        rng.shuffle(free)
        self.actors, self.items = [], []
        boss_spec = next((b for b in self.m["bosses"]
                          if b["regionId"] == region_id), None)
        cap = max(2, boss_spec["tier"] if boss_spec else 3)
        pool = self.enemies_by_region.get(region_id) or self.m["enemies"]
        for _ in range(min(4 + len(self.level.rooms), len(free) // 4)):
            if not free:
                break
            spec = rng.choice(pool)
            spec = {**spec, "tier": max(1, min(spec["tier"], cap))}
            en = make_enemy(spec, *self.spot_for(spec["sourceNoteId"], free))
            en.faction = self._region_faction.get(region_id, "")
            self.actors.append(en)
        if boss_spec is not None and free:
            boss = make_boss(boss_spec, *self.spot_for(boss_spec["sourceNoteId"], free))
            boss.faction = self._region_faction.get(region_id, "")
            if boss_spec["sourceNoteId"] == self.up.throne:
                boss.name = "Ascendant " + boss.name
            self.actors.append(boss)
            self.log(f"!! {boss.name} — {boss_spec.get('title', '')} — "
                     "dwells in these depths.")
            hist = self._note_history(boss.source, salt="boss")
            if hist:
                self.log(f"  {hist}")
        # gates: the stair up, then one passage per bordering region's depths
        self._gates = {(px, py): "surface"}
        self.level.tiles[py][px] = "<"
        exits = [self.level.stairs] + [r.center for r in self.level.rooms[1:-1]]
        exits = [t for t in exits if self.level.walkable(*t) and t != (px, py)]
        for i, adj in enumerate(sorted(self._region_adjacency().get(region_id, ()))):
            if i >= len(exits):
                break
            t = exits[i]
            self._gates[t] = adj
            self.level.tiles[t[1]][t[0]] = ">"
        if self.level.stairs not in self._gates:
            sx, sy = self.level.stairs      # an exit no border claimed: just floor
            self.level.tiles[sy][sx] = "."
        self._build_felt()
        if len(self._gates) > 1:
            self.log("Passages (>) lead beneath the borders; (<) climbs home.")
        arrive = next((p for p, dst in sorted(self._gates.items())
                       if dst == from_realm), (px, py))
        self.player.x, self.player.y = arrive

    # ---- rooms are places: each room carries a note's identity ----
    def _region_community(self, region):
        fid = region.get("factionId", "")
        if isinstance(fid, str) and fid.startswith("faction_"):
            try:
                return int(fid[len("faction_"):])
            except ValueError:
                pass
        node = self.m["graph"]["nodes"].get(region.get("sourceNoteId"))
        return node.get("community") if node else None

    def _assign_rooms(self, region):
        """Give each room a note from the region's community. The region's anchor
        note claims the deepest room (the stairs end); the rest are dealt by a
        per-floor seeded shuffle, so different floors feature different notes."""
        nodes = self.m["graph"]["nodes"]
        comm = self._region_community(region)
        cands = sorted(nid for nid, n in nodes.items()
                       if comm is None or n.get("community") == comm)
        anchor = region.get("sourceNoteId")
        rest = [nid for nid in cands if nid != anchor]
        random.Random(f"{self.seed}:rooms:{self.floor}").shuffle(rest)
        order = ([anchor] if anchor in nodes else []) + rest
        rooms = self.level.rooms
        room_order = [len(rooms) - 1] + list(range(len(rooms) - 1))
        self.room_notes = dict(zip(room_order, order))
        self._rooms_seen = set()
        self._build_tint()

    def _build_tint(self):
        """Per-cell region element for the current map: each place carries its own
        region's palette (corridors and outer walls stay neutral). Covers every
        footprint cell, so interior structure (pillars, rubble) is tinted too.
        Also records per-cell region ids so borders can be found and colored."""
        self._tint = {}
        self._cell_region = {}
        nodes = self.m.get("graph", {}).get("nodes", {})
        for idx, nid in self.room_notes.items():
            node = nodes.get(nid)
            region = self._region_by_comm.get(node.get("community")) if node else None
            if self._on_surface():
                cells = list(self._places[idx][0].cells)
            else:
                r = self.level.rooms[idx]
                cells = [(x, y) for y in range(r.y, r.y + r.h)
                         for x in range(r.x, r.x + r.w)]
            if region is not None:
                for cell in cells:
                    self._cell_region[cell] = region["id"]
            element = (region or {}).get("element")
            if not element or element == "inert":
                continue
            for cell in cells:
                self._tint[cell] = element

    def _build_felt(self):
        """The felt architecture: what makes the philosophy PERCEPTIBLE.
        - glow: per-cell intensity, so light rises toward the heart (Gradients)
        - landmarks: hearts and town doors visible through the fog (Strong Centers)
        - frictions: border walls colored by the houses' stance (Boundaries)"""
        self._glow_cells = {}
        self._landmarks = {}
        self._frictions = {}
        if not self._on_surface():
            self._landmarks = {pos: "gate" for pos in self._gates}
            return
        # the land BELONGS: each region's color field spreads a short way past its
        # buildings, so districts read as lands and meeting fields as boundaries
        frontier = [(cell, self._tint[cell], self._cell_region.get(cell))
                    for cell in sorted(self._tint)]
        seen = set(self._tint)
        for _ in range(5):
            nxt = []
            for (x, y), el, rid in frontier:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (x + dx, y + dy)
                    if n in seen or not self.level.walkable(*n):
                        continue
                    seen.add(n)
                    self._tint[n] = el
                    if rid:
                        self._cell_region[n] = rid
                    nxt.append((n, el, rid))
            frontier = nxt
        for i, (pl, c) in enumerate(self._places):
            for cell in pl.cells:
                self._glow_cells[cell] = c.intensity
            if c.intensity >= 0.6:
                self._landmarks[pl.center] = "heart"
        for door in self._gates:
            self._landmarks[door] = "town"
        # a wall between two regions is a BORDER; its color is their stance
        walls: dict = {}
        for (x, y), rid in self._cell_region.items():
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                wx, wy = x + dx, y + dy
                if (0 <= wx < self.level.w and 0 <= wy < self.level.h
                        and self.level.tiles[wy][wx] == "#"):
                    walls.setdefault((wx, wy), set()).add(rid)
        for wall, rids in walls.items():
            if len(rids) < 2:
                continue
            fa, fb = [self._region_faction.get(r, "") for r in sorted(rids)[:2]]
            stance = self._rel.get((fa, fb), "neutral")
            self._frictions[wall] = stance

    def _on_surface(self) -> bool:
        """True when walking the grown overworld (not inside a dungeon)."""
        return self.sandbox and self._dungeon is None

    def room_at(self, x: int, y: int):
        if self._on_surface():
            for i, (place, _c) in enumerate(self._places):
                if place.contains(x, y):
                    return i
            return None
        for i, r in enumerate(self.level.rooms):
            if r.contains(x, y):
                return i
        return None

    def room_of_note(self, note_id: str):
        for i, nid in self.room_notes.items():
            if nid == note_id:
                return (self._places[i][0] if self._on_surface()
                        else self.level.rooms[i])
        return None

    def room_tiles(self, idx) -> list:
        """Walkable tiles of room `idx`, in either mode."""
        if self._on_surface():
            return sorted(t for t in self._places[idx][0].cells
                          if self.level.walkable(*t))
        r = self.level.rooms[idx]
        return [(x, y) for y in range(r.y, r.y + r.h) for x in range(r.x, r.x + r.w)
                if self.level.walkable(x, y)]

    def room_label(self, idx):
        nid = self.room_notes.get(idx)
        if nid is None:
            return None
        node = self.m["graph"]["nodes"].get(nid, {})
        noun = ROOM_NOUN.get(node.get("role"), "Chamber")
        return f"the {noun} of '{node.get('title', nid)}'"

    def spot_for(self, note_id: str, free: list):
        """Pop a spawn tile for note_id's room. Prefer a tile ADJACENT to the room's
        focal fixture (altar/shelf/stones), so the guardian rings its feature and the
        room reads as one inhabited center (design-panel step 3); else any room tile;
        else the shuffled tail. This is what makes contents contextual to place."""
        room = self.room_of_note(note_id)
        if room is not None:
            ridx = next((i for i, nid in self.room_notes.items()
                         if nid == note_id), None)
            feats = getattr(self, "_fixtures", {}).get(ridx) or []
            near = {(fx + dx, fy + dy) for (fx, fy) in feats
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
            for i, t in enumerate(free):
                if t in near and room.contains(*t):
                    return free.pop(i)
            for i, (x, y) in enumerate(free):
                if room.contains(x, y):
                    return free.pop(i)
        return free.pop() if free else None

    # ---- cross-system bus (see INTERACTIONS_SPEC.md) ----
    def system(self, name: str):
        """Service locator: fetch a registered system by its `name`, or None."""
        for s in self.systems:
            if getattr(s, "name", None) == name:
                return s
        return None

    def emit(self, etype: str, **data):
        """Broadcast a semantic event to every system's on_event hook."""
        for s in self.systems:
            s.on_event(self, etype, data)

    # ---- floor lifecycle ----
    def descend(self):
        if self.sandbox:
            t = self.level.tiles[self.player.y][self.player.x]
            if t in "><" and self.traverse():
                return
            self.log("No way through here; doors (>) wait in each district's "
                     "heart, stairs (<) climb home.")
            return
        self.floor += 1
        rng = random.Random(f"{self.seed}:spawn:{self.floor}")
        self.level = generate_level(self.width, self.height, self.seed, self.floor)
        px, py = self.level.player_start
        if self.player is None:
            self.player = make_player(px, py)
        else:
            self.player.x, self.player.y = px, py
            # rest between floors: a fixed fraction, not a stat gain (no power creep)
            self.player.hp = min(self.player.max_hp, self.player.hp + self.player.max_hp // 5)
        self.actors, self.items = [], []
        free = free_floor_tiles(self.level, {(px, py), self.level.stairs})
        rng.shuffle(free)

        region = self.region_for(self.floor)
        self.region_name = region["name"]
        self._assign_rooms(region)
        anchor = region["sourceNoteId"]
        pool = self.enemies_by_region.get(region["id"]) or self.m["enemies"]

        # --- upheaval announcements (once per region) ---
        if anchor in self.up.risen_regions and anchor not in self.announced:
            self.announced.add(anchor)
            self.log(f"✦ New territory — {self.region_name} has risen into the world.")
        if anchor in self.up.contested and ("c:" + anchor) not in self.announced:
            self.announced.add("c:" + anchor)
            self.log(f"⚔ {self.region_name} is contested ground; its borders bleed.")

        n = 2 + self.floor // 4 + round(region.get("activity", 0) * 2)
        n = max(1, min(n, len(free) // 4))
        # An enemy's note-derived tier sets its *identity*; the floor caps its *power*,
        # so early floors stay gentle even when a region's anchor note is highly central.
        cap = 1 + self.floor // 3
        for _ in range(n):
            if not free:
                break
            spec = rng.choice(pool)
            spec = {**spec, "tier": max(1, min(spec["tier"], cap))}
            en = make_enemy(spec, *self.spot_for(spec["sourceNoteId"], free))
            en.faction = self._region_faction.get(spec.get("regionId", ""), "")
            src = spec["sourceNoteId"]
            if src in self.up.ascended:        # your note grew -> the monster grew
                empower(en)
            elif src in self.up.waned:
                diminish(en)
            self.actors.append(en)

        for b in self.m["bosses"]:
            if b["depth"] == self.floor and free:
                boss = make_boss(b, *self.spot_for(b["sourceNoteId"], free))
                boss.faction = self._region_faction.get(b.get("regionId", ""), "")
                if b["sourceNoteId"] == self.up.throne:
                    boss.name = "Ascendant " + boss.name
                    self.log(f"♛ {boss.name} has newly claimed the throne.")
                self.actors.append(boss)
                self.log(f"!! {boss.name} — {b.get('title', '')} — guards this depth.")
                if boss.flavor:
                    self.log(boss.flavor)
                    self._flavored.add(boss.source)

        # Vanilla stat-loot only exists in the bare game. With the systems layer on,
        # the sigil economy (configuration, not creep) replaces it entirely.
        if not self.systems:
            bonus = 1 if anchor in self.up.risen_regions else 0
            for _ in range(rng.randint(1, 2) + bonus):
                if not free or not self.m["items"]:
                    break
                spec = rng.choice(self.m["items"])
                self.items.append(make_item(spec, *self.spot_for(spec["sourceNoteId"], free)))

        # lost notes haunt the floors they used to seed
        for note in self.up.lost_floor.get(self.floor, []):
            if not free:
                break
            self.actors.append(make_echo(note, *self.spot_for(note, free)))
            self.log(f"† The ruins of '{_title(note)}' stir here.")

        self.log(f"-- Floor {self.floor}: {self.region_name} --")
        start_room = self.room_at(px, py)
        if start_room is not None:
            self._rooms_seen.add(start_room)
            label = self.room_label(start_room)
            if label:
                self.log(f"You stand in {label}.")
        if region.get("flavor") and ("fl:" + region["id"]) not in self.announced:
            self.announced.add("fl:" + region["id"])
            self.log(region["flavor"])
        for s in self.systems:
            s.on_floor_enter(self)

    # ---- actions ----
    def actor_at(self, x: int, y: int):
        for a in self.actors:
            if a.x == x and a.y == y:
                return a
        return None

    def on_stairs(self) -> bool:
        if self.sandbox:
            return self.level.tiles[self.player.y][self.player.x] in "><"
        return (self.player.x, self.player.y) == self.level.stairs

    def ascend(self):
        if self.sandbox and self.level.tiles[self.player.y][self.player.x] in "<>":
            if self.traverse():
                return
        self.log("There is no way up from here.")

    def try_move(self, dx: int, dy: int):
        if not self.alive or self.won:
            return
        self.turn += 1
        nx, ny = self.player.x + dx, self.player.y + dy
        target = self.actor_at(nx, ny)
        if target is not None and self.hostile(self.player, target):
            self.attack(self.player, target)
        elif target is not None or self.level.walkable(nx, ny):
            if target is not None:
                # a friendly body never blocks a way: switch places (talk is `t`)
                target.x, target.y = self.player.x, self.player.y
                self.log(f"You slip past {target.name}.")
            self.player.x, self.player.y = nx, ny
            idx = self.room_at(nx, ny)
            if idx is not None and idx not in self._rooms_seen:
                self._rooms_seen.add(idx)
                label = self.room_label(idx)
                if label:
                    # a quiet arrival: the place, and its one truest feature. The
                    # rest (rules, full motif list) waits for `x`. No log dump.
                    motifs = getattr(self, "_motifs", {}).get(idx, [])
                    tag = f", where {motifs[0]}" if motifs else ""
                    kept = " (settled)" if (idx in self._town_rooms
                                            and self._on_surface()) else ""
                    self.log(f"You enter {label}{tag}{kept}.")
            if self.sandbox:
                r = self.region_for(self.floor)
                if r["name"] != self.region_name:
                    self.region_name = r["name"]
                    self.log(f"You cross into {self.region_name}.")
                    # the atmosphere announces itself: the environment's leading voice
                    env = self._region_env.get(r["id"])
                    if env is not None:
                        self.log(env.voice()[0])
                    elif r.get("flavor") and ("fl:" + r["id"]) not in self.announced:
                        self.announced.add("fl:" + r["id"])
                        self.log(r["flavor"])
                    self.announced.add("fl:" + r["id"])
            # ambient murmur: occasionally a place speaks its vibe as you move through
            self._ambient_tick()
            # one move is one tile — always. Speed governs how OFTEN you act relative
            # to other actors, never how far a single step carries you. (Crossing the
            # country fast is the `g` travel verb repeating a normal step, not a tile
            # of teleport baked into try_move.)
            self._pickup()
            self.emit("noise", pos=(nx, ny), volume=3)   # footsteps carry
        self.enemies_act()
        for s in self.systems:
            s.on_player_act(self)

    def commune_landmark(self):
        """Yume-Nikki effects: standing on or beside a wild landmark (a solitary
        orphan-note out in the world), take its EFFECT into yourself — a way of
        being that changes how you explore, never a weapon. Returns True if a
        landmark was here (whether or not it was new), None if none is adjacent."""
        eff_sys = self.system("effects")
        px, py = self.player.x, self.player.y
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                nid = getattr(self, "_wild_structs", {}).get((px + dx, py + dy))
                if nid is None:
                    continue
                title = self.m["graph"]["nodes"].get(nid, {}).get("title", nid)
                if eff_sys is None:
                    self.log(f"You commune with '{title}', but nothing takes hold.")
                    return True
                got = eff_sys.acquire(self, nid)
                if got is None:
                    from .effects import effect_for
                    self.log(f"'{title}' offers the {effect_for(nid)} you already carry.")
                return True
        return None

    def commune(self):
        """Resolve the deepest thought without violence. Standing before the final
        boss you may integrate it: by speaking enough read truths (marginalia +
        lore), or by an offering of salvaged matter. Fighting it remains the old
        way. Returns True on communion, False on refusal, None when the final
        boss is not beside you (so a front-end can fall through to plain talk)."""
        p = self.player
        boss = next((a for a in self.actors if a.is_boss
                     and a.source == self.final_boss_source), None)
        if boss is None or max(abs(boss.x - p.x), abs(boss.y - p.y)) > 1:
            return None
        truths = sum(getattr(self.system(n), "read", 0)
                     for n in ("marginalia", "history") if self.system(n))
        salv = self.system("salvage")
        bag = salv.inventory(self) if salv is not None else None
        if truths >= COMMUNE_TRUTHS:
            self.log(f"You speak what the vault has written; {boss.name} listens.")
        elif bag is not None and bag.total() >= COMMUNE_COST:
            cost = _spend_matter(bag, COMMUNE_COST)
            offered = " ".join(f"{m}x{q}" for m, q in sorted(cost.items()))
            self.log(f"You lay down your offering ({offered}); {boss.name} accepts.")
        else:
            self.log(f"{boss.name} does not know you yet. Read {COMMUNE_TRUTHS} of "
                     f"the vault's truths, or gather {COMMUNE_COST} matter to offer.")
            return False
        self.actors.remove(boss)
        self.won = True
        self.emit("communed", boss=boss, pos=(boss.x, boss.y))
        self.log("You integrate the deepest thought in the vault. "
                 "You surface changed. You win.")
        return True

    def becalm(self, target) -> bool:
        """Approach a hostile without violence. If you have DIRECTLY learned its
        source note, understanding disarms it for free; otherwise an offering of
        matter (BECALM_COST x tier) placates it. Either way it joins the wild:
        indifferent to you, part of the ecology, and the factions hear nothing.
        Bosses are commune()'s business."""
        if target.is_boss or target.allegiance != "monster":
            return False
        know = self.system("knowledge")
        if know is not None and target.source in getattr(know, "learned", set()):
            self.log(f"You speak its own thought back to it; {target.name} stills.")
        else:
            salv = self.system("salvage")
            bag = salv.inventory(self) if salv is not None else None
            total = BECALM_COST * max(1, target.tier)
            if bag is None or bag.total() < total:
                self.log(f"{target.name} is not moved. "
                         f"(Know its note, or offer {total} matter.)")
                return False
            cost = _spend_matter(bag, total)
            offered = " ".join(f"{m}x{q}" for m, q in sorted(cost.items()))
            self.log(f"You share what you have gathered ({offered}); "
                     f"{target.name} is placated.")
        self._join_wild(target)
        return True

    def _join_wild(self, target):
        """A stood-down hostile joins the ecology: indifferent to you, no faction
        alarm, and it re-picks a brain fitting its new nature."""
        target.allegiance = "wild"
        target.brain = None
        self.emit("becalmed", actor=target, pos=(target.x, target.y))

    def recruit(self, target):
        """A swayed creature chooses to walk with you: it mirrors your hostilities
        (its own kin stay kin), leaves its territory behind, and keeps your side."""
        target.allegiance = "companion"
        target._home = None                    # its road is yours now
        from .sense import make_brain
        target.brain = make_brain(self, target, name="companion")
        self.emit("recruited", actor=target, pos=(target.x, target.y))
        self.log(f"{target.name} falls in beside you.")

    def confide(self, target) -> bool:
        """Trade a read truth with a friendly creature (becalmed or companion):
        it opens its source note to you in return, once each. The water-ritual
        heart: secrets for secrets."""
        if target.allegiance not in ("wild", "companion") or not target.source:
            return False
        if getattr(target, "_confided", False):
            self.log(f"{target.name} has nothing more to share.")
            return False
        have = sum(getattr(self.system(n), "read", 0)
                   for n in ("marginalia", "history") if self.system(n))
        if have - self._truths_spent < 1:
            self.log("You have nothing read to trade.")
            return False
        self._truths_spent += 1
        target._confided = True
        know = self.system("knowledge")
        if know is not None:
            know._reveal(self, target.source, direct=True)
        fs = self.system("factions")
        f = getattr(target, "faction", "")
        if fs is not None and f:
            fs.standing[f] = fs.standing.get(f, 0) + 1
        self.log(f"You trade what you have read; {target.name} opens its "
                 "note to you in turn.")
        return True

    def toss(self, dx: int, dy: int) -> bool:
        """Throw a scrap of matter: it clatters down up to 4 tiles away, and the
        noise draws hearing creatures to investigate. Costs 1 matter. Stealth's
        active verb: you spend the world's substance to bend attention."""
        salv = self.system("salvage")
        bag = salv.inventory(self) if salv is not None else None
        if bag is None or bag.total() < 1:
            self.log("You have no matter to toss.")
            return False
        x, y = self.player.x, self.player.y
        for _ in range(4):
            nx, ny = x + dx, y + dy
            if not self.level.walkable(nx, ny) or self.actor_at(nx, ny) is not None:
                break
            x, y = nx, ny
        if (x, y) == (self.player.x, self.player.y):
            self.log("There is no room to throw.")
            return False
        _spend_matter(bag, 1)
        self.log("You toss a scrap of matter; it clatters in the dark.")
        self.emit("noise", pos=(x, y), volume=10)
        return True

    def wait(self):
        """Pass the turn in place. Quiet: no footstep noise, so waiting is also hiding.
        The ambient world (fire, fauna, weather) advances around you. On settled
        town ground, waiting is REST."""
        if not self.alive or self.won:
            return
        if (self._on_surface()
                and (self.player.x, self.player.y) in self._town_tiles
                and self.player.hp < self.player.max_hp):
            self.player.hp = min(self.player.max_hp, self.player.hp + 2)
            self.log("You rest on settled ground (+2 HP).")
        self.turn += 1
        self.enemies_act()
        for s in self.systems:
            s.on_player_act(self)

    def _fixture_here(self):
        """The fixture tile the player stands on or beside, and its room idx, or None."""
        from .arch.interiors import FIXTURES
        px, py = self.player.x, self.player.y
        best = None
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                t = (px + dx, py + dy)
                if (0 <= t[1] < self.level.h and 0 <= t[0] < self.level.w
                        and self.level.tiles[t[1]][t[0]] in FIXTURES):
                    ridx = getattr(self, "_fixture_room", {}).get(t)
                    if ridx is not None:
                        return t, ridx
                    if best is None:
                        best = (t, self.room_at(*t))
        return best

    def _examine_wild(self):
        """A wild landmark (orphan note) names and voices itself when you reach it."""
        from .arch.terrain import WILD_STRUCT
        px, py = self.player.x, self.player.y
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                t = (px + dx, py + dy)
                nid = getattr(self, "_wild_structs", {}).get(t)
                if nid is None:
                    continue
                glyph = getattr(self, "_overlay", {}).get(t, "")
                noun = WILD_STRUCT.get(glyph, "a lonely marker")
                title = self.m["graph"]["nodes"].get(nid, {}).get("title", nid)
                self.log(f"{noun[0].upper() + noun[1:]}, '{title}'.")
                # the landmark tells its note's HISTORY, then speaks in its words
                hist = self._note_history(nid, salt=f"{t[0]},{t[1]}")
                if hist:
                    self.log(f"  {hist}")
                line = self._weave_note(nid, salt=f"{t[0]},{t[1]}")
                if line:
                    self.log(f'  It murmurs: "{line}"')
                return True
        return False

    def _examine_fixture(self):
        """When on or beside a fixture, voice it in the room note's own words."""
        if self._examine_wild():
            return
        found = self._fixture_here()
        if found is None:
            return
        (fx, fy), ridx = found
        from .arch.interiors import FIXTURE_NOUN
        noun = FIXTURE_NOUN.get(self.level.tiles[fy][fx], "a made thing")
        nid = self.room_notes.get(ridx) if ridx is not None else None
        line = self._weave_note(nid, salt=f"{fx},{fy}") if nid else ""
        if line:
            self.log(f"{noun[0].upper() + noun[1:]}: \"{line}\"")
        else:
            self.log(f"You stand by {noun}.")

    def _weave_note(self, nid: str, salt: str = "") -> str:
        """One line woven from a note's own corpus (shared marginalia machinery),
        seeded per note+turn(+salt) so different fixtures and re-reads speak
        differently, but deterministically."""
        node = self.m.get("graph", {}).get("nodes", {}).get(nid, {})
        comm = (self.m.get("corpus") or {}).get(str(node.get("community", -1)))
        if not comm:
            return ""
        try:
            from .marginalia import weave
            return weave(comm, nid, random.Random(
                f"{self.seed}:weave:{nid}:{self.turn}:{salt}"), max_words=14)
        except Exception:
            return ""

    def _note_history(self, nid: str, salt: str = "") -> str:
        """One line of a note's own biography, read from its graph facts. Different
        tellers (by salt) recount different true facts about the same note."""
        node = self.m.get("graph", {}).get("nodes", {}).get(nid)
        if not node:
            return ""
        from .notehistory import one_fact
        return one_fact(node, node.get("title", nid), salt=salt)

    def region_palette(self, rid) -> str:
        """The COLOR lean a region's ground wears: its AREA KIND's palette if the kind
        declares one (a grove is verdant, a necropolis ashen), else the region's
        blended-environment palette. This is what makes a place colorful — or not."""
        if rid is None:
            return ""
        from .arch import areakinds
        kind = self._region_kind.get(rid, "wilds")
        lean = areakinds.palette(kind)
        if lean:
            return lean
        env = self._region_env.get(rid)
        return env.palette() if env is not None else ""

    def creature_stats(self, target) -> list:
        """A few READABLE metrics about a creature, surfaced in the talk window (which
        otherwise wastes the space under the name). All plain fact, no combat spoilers
        beyond 'wounded': its stance toward you, its grade, its house, its standing in
        the graph. Returns short strings the frame lays out as one status line."""
        out = []
        # stance toward you (the thing you most want to read before you act)
        al = getattr(target, "allegiance", "monster")
        stance = {"companion": "at your side", "wild": "indifferent",
                  "npc": "watchful", "monster": "hostile"}.get(al, al)
        if al == "monster" and getattr(target, "_enraged", False):
            stance = "enraged"
        out.append(stance)
        # grade + tier (its weight in the world), only when notable
        from .quality import name as _qname
        if getattr(target, "quality", 0) > 0:
            out.append(_qname(target.quality).lower())
        if getattr(target, "tier", 1) >= 3:
            out.append(f"tier {target.tier}")
        # condition — surfaced only when it actually matters
        hp, mhp = getattr(target, "hp", 0), getattr(target, "max_hp", 1)
        if hp < mhp:
            out.append("wounded" if hp > mhp // 3 else "near death")
        # its house, and how that house regards you
        fs = self.system("factions")
        fac = getattr(target, "faction", "")
        if fs is not None and fac:
            fname = getattr(fs, "faction_name", None)
            label = fname(fac) if callable(fname) else fac
            st = fs.standing_of(fac) if hasattr(fs, "standing_of") else 0
            regard = "allied" if st >= 2 else "wary" if st <= -2 else "neutral"
            out.append(f"{label} ({regard})")
        # its standing in the vault graph (how central the note is)
        node = self.m.get("graph", {}).get("nodes", {}).get(
            getattr(target, "source", ""), {})
        deg = node.get("degree", 0)
        if deg:
            out.append(f"{deg} link{'s' if deg != 1 else ''}")
        return out

    def creature_look(self, target) -> tuple:
        """(archetype, damage_type) for a creature's PORTRAIT — read from the baked
        enemy/boss spec by its source note, falling back to the map glyph's archetype
        so wildlife and NPCs still get a face. Deterministic, manifest-derived."""
        src = getattr(target, "source", "")
        for group in ("enemies", "bosses"):
            for e in self.m.get(group, []):
                if e.get("sourceNoteId") == src:
                    return e.get("archetype", "construct"), e.get("damageType", "")
        from .entities import ARCH_GLYPH
        g2a = {v: k for k, v in ARCH_GLYPH.items()}
        return g2a.get(getattr(target, "glyph", ""), "construct"), ""

    def dialogue_topics(self, nid: str) -> list:
        """DIALOGUE options exclusive to this creature's note — distinct from the
        mechanical verbs (offer/confide/truce) that every creature shares. These are
        conversation branches born from what THIS note is: what it links to, its
        concerns, its place in the vault. Returns [(label, response_line)]."""
        node = self.m.get("graph", {}).get("nodes", {}).get(nid)
        if not node:
            return []
        title = node.get("title", nid)
        nodes = self.m.get("graph", {}).get("nodes", {})
        out = []
        nbrs = node.get("neighbors") or []
        if nbrs:
            named = ", ".join(nodes.get(n, {}).get("title", n) for n in nbrs[:3])
            out.append((f"Ask what '{title}' connects to",
                        f'It speaks of ways that run to {named}.'))
        tags = node.get("tags") or []
        if tags:
            concerns = ", ".join(t.replace("-", " ") for t in tags[:3])
            out.append(("Ask what it cares about",
                        f'"My concerns," it says, "are {concerns}."'))
        if node.get("bridge"):
            out.append(("Ask why it stands between",
                        "It stands athwart a border; two worlds meet in it, "
                        "and it has learned to keep both their secrets."))
        elif node.get("role") == "hub":
            out.append(("Ask why so many seek it",
                        "Much turns around it. It is a center others orbit, "
                        "and it wears the weight lightly."))
        elif node.get("role") == "orphan":
            out.append(("Ask how it came to be alone",
                        "Nothing points to it and it points to nothing. "
                        "It drifted here, and stayed."))
        return out

    def examine(self, radius: int = 6):
        """Look around (free action): the region's nature, then whatever is nearby.
        This is where the baked note-derived flavor reaches the player on demand."""
        region = self.region_for(self.floor)
        desc = region.get("flavor", "")
        env = self._region_env.get(region["id"]) if region else None
        idx = self.room_at(self.player.x, self.player.y)
        label = self.room_label(idx) if idx is not None else None
        where = (f"You stand in {label}, within {self.region_name}."
                 if label else f"{self.region_name}.")
        # the atmosphere itself, and the block-terrain features nearby (read the vibe)
        if env is not None:
            self.log(env.voice()[0])
        px, py = self.player.x, self.player.y
        nouns = {}
        for (bx, by), gph in getattr(self, "_overlay", {}).items():
            if (max(abs(bx - px), abs(by - py)) <= radius
                    and gph in getattr(self, "_block_noun", {})):
                nouns[self._block_noun[gph]] = nouns.get(self._block_noun[gph], 0) + 1
        if nouns:
            top = sorted(nouns.items(), key=lambda kv: -kv[1])[:4]
            self.log("Around you: " + ", ".join(n for n, _c in top) + ".")
        self.log(f"{where} {desc}".rstrip())
        if idx is not None:
            for phrase in getattr(self, "_motifs", {}).get(idx, []):
                self.log(f"Here, {phrase}.")

        # the fixture answers in the note's own voice — a made thing you can approach
        # and that speaks. (design-panel step 2: a pillar you can only look past is
        # decoration; one that answers you is a place.)
        self._examine_fixture()

        def dist(o):
            return max(abs(o.x - self.player.x), abs(o.y - self.player.y))

        near_actors = sorted((a for a in self.actors if dist(a) <= radius),
                             key=lambda a: (dist(a), a.name))
        for i, a in enumerate(near_actors):
            line = f"{a.name} ({max(0, a.hp)}/{a.max_hp} HP)"
            if a.flavor:
                line += f" {a.flavor}"
            self.log(line)
            self._flavored.add(a.source)
            # the nearest creature recounts the HISTORY of the note it sprang from
            if i == 0 and getattr(a, "source", ""):
                h = self._note_history(a.source, salt=f"{a.x},{a.y}")
                if h:
                    self.log(f"  Of its origin: {h}")
        for it in self.items:
            if dist(it) <= radius:
                self.log(f"{it.name} lies nearby. {it.flavor}".rstrip())

        # walkable-to points of interest, by system (keepers are actors, listed above)
        labels = {"sigils": "sigil slot", "history": "lore fragment",
                  "salvage": "salvage", "machines": "machine",
                  "marginalia": "marginalia", "caches": "cache"}
        found = []
        for s in self.systems:
            label = labels.get(getattr(s, "name", ""))
            if not label:
                continue
            n = sum(1 for (tx, ty) in (s.points_of_interest(self) or [])
                    if max(abs(tx - self.player.x), abs(ty - self.player.y)) <= radius)
            if n:
                plural = "s" if n > 1 and label not in ("salvage", "marginalia") else ""
                found.append(f"{n} {label}{plural}")
        if found:
            self.log("Nearby: " + ", ".join(found) + ".")
        caches = self.system("caches")
        if caches is not None:
            for line in caches.describe_near(self, radius):
                self.log(line)
        if self.sandbox and self._gates:
            gx, gy = min(self._gates,
                         key=lambda t: abs(t[0] - self.player.x) + abs(t[1] - self.player.y))
            d = abs(gx - self.player.x) + abs(gy - self.player.y)
            if d == 0:
                self.log("A gate lies underfoot; (>) or (<) passes through.")
            else:
                ns = "south" if gy > self.player.y else "north" if gy < self.player.y else ""
                ew = "east" if gx > self.player.x else "west" if gx < self.player.x else ""
                self.log(f"The nearest gate lies {d} paces {ns}{ew or ''}.")

    def _pickup(self):
        for it in list(self.items):
            if it.x == self.player.x and it.y == self.player.y:
                self.log(apply_item(self.player, it))
                if it.flavor:
                    self.log(it.flavor)
                self.items.remove(it)
                self.items_taken += 1

    def kill(self, actor, cause="other"):
        """Universal death: remove the actor and announce it on the bus as `actor_died`
        (corpses, scavengers, ecology). `enemy_killed` is emitted separately, only for
        player/environment kills the factions care about."""
        if actor in self.actors:
            self.actors.remove(actor)
        self.emit("actor_died", actor=actor, cause=cause, pos=(actor.x, actor.y))

    @staticmethod
    def _hostile(a: str, b: str) -> bool:
        """The legacy allegiance table (strings). Engine paths use hostile()
        below, which layers faction relations and reputation on top of this."""
        if a == b:
            return False
        if "npc" in (a, b):
            return False                       # NPCs are neutral — you parley, not fight
        return {a, b} != {"wild", "player"}   # wildlife and the player ignore each other

    def hostile(self, a, b) -> bool:
        """Faction-aware hostility between two ACTORS (Qud-style). Kin never
        fight; rival houses do; reputation can befriend a house to whoever you
        control. The controlled actor is not special: control any entity and
        these same rules decide your friends and enemies."""
        if a is b:
            return False
        # Yume-Nikki effects: worn 'small' makes you unseen, 'hush' calms wild things —
        # either way nothing menaces the player while it is worn (exploration, not combat)
        if getattr(a, "is_player", False) or getattr(b, "is_player", False):
            eff = self.system("effects")
            if eff is not None and (eff.unseen(self) or eff.calms(self)):
                return False
        al, bl = a.allegiance, b.allegiance
        al = "player" if al == "companion" else al   # companions mirror you
        bl = "player" if bl == "companion" else bl
        if "npc" in (al, bl):
            return False
        fa, fb = getattr(a, "faction", ""), getattr(b, "faction", "")
        if fa and fa == fb:
            return False                       # kin never fight
        if al == "monster" and bl == "monster":
            # houses war only when the bible says rival (evolve can ignite this)
            return bool(fa and fb) and self._rel.get((fa, fb)) == "rival"
        if "player" in (al, bl):
            other = b if al == "player" else a
            if other.allegiance == "monster":
                fs = self.system("factions")
                f = getattr(other, "faction", "")
                if f and fs is not None:
                    try:
                        if fs.standing_of(f) >= FRIEND_STANDING:
                            return False       # this house counts you a friend
                    except Exception:
                        pass
                return True
        return self._hostile(al, bl)

    def attack(self, att, dfn):
        self.emit("noise", pos=(dfn.x, dfn.y), volume=8)   # combat is loud
        if att.is_player:
            dfn._provoked = True   # a struck creature forgets its territory
        # first blood reveals what a foe is: its baked note-derived flavor, once
        if att.is_player or dfn.is_player:
            foe = att if dfn.is_player else dfn
            if foe.flavor and foe.source not in self._flavored:
                self._flavored.add(foe.source)
                self.log(foe.flavor)
        dmg = max(1, att.atk - dfn.defense)
        dfn.hp -= dmg
        if dfn.hp > 0:
            if att.is_player:
                self.log(f"You hit {dfn.name} for {dmg} ({max(0, dfn.hp)} HP left).")
            elif dfn.is_player:
                self.log(f"{att.name} hits you for {dmg} ({max(0, dfn.hp)} HP left).")
            return
        if dfn.is_player:
            self.alive = False
            where = (f"in {self.region_name}" if self.sandbox
                     else f"on floor {self.floor}")
            self.log(f"{att.name} strikes you down. You die {where}.")
            return
        # a non-player actor died
        if dfn.is_boss and dfn.source == self.final_boss_source:
            self.won = True
            self.log("The deepest thought in the vault falls silent. You win.")
        if att.is_player and dfn.allegiance == "monster":
            self.kills += 1
            self.log(f"You destroy {dfn.name}{' [BOSS]' if dfn.is_boss else ''}.")
            for s in self.systems:
                s.on_enemy_killed(self, dfn)
            self.emit("enemy_killed", enemy=dfn, cause="melee")
            self.kill(dfn, "melee")
        else:
            # critter vs monster (or the reverse): a world event, never a player kill,
            # so no `enemy_killed` — the factions don't credit/blame you for the wild.
            self.log(f"{att.name} fells {dfn.name}.")
            self.kill(dfn, "predation")

    def enemies_act(self):
        """Every non-player actor acts through its brain (lazily assigned by capability
        tier). A brain returns a step direction; `_npc_step` resolves it to a bump-attack
        or a move.

        SPEED: the world ticks at rate 1 (one player action = one tick). Each actor
        gains `speed` energy per tick and acts once per whole unit of energy it holds,
        so speed 1 acts every tick (the default, unchanged), 0.5 every other tick, 2.0
        twice a tick. Nobody moves two TILES in one action; a faster thing simply gets
        more actions. Energy carries over, so fractional speeds average out exactly."""
        if not self.alive:
            return
        for a in list(self.actors):
            if a not in self.actors:
                continue
            a.energy = getattr(a, "energy", 0.0) + getattr(a, "speed", 1.0)
            while a.energy >= 1.0 and a in self.actors and self.alive:
                a.energy -= 1.0
                self._act_once(a)

    def _act_once(self, a):
        """One action for one actor (one tile of movement, one attack, or a mill).
        Returning early just means 'this action is spent'; the energy loop in
        enemies_act decides whether the actor gets another this tick."""
        # territorial (sandbox): a creature belongs to its note's ground. It
        # stirs only if you stand on that ground, press in close, or provoked
        # it -- and drawn too far from home, it gives up and drifts back.
        home = getattr(a, "_home", None)
        if self.sandbox and a.allegiance == "npc":
            # townsfolk stroll their square (anchored where they were placed):
            # a settlement with still people reads as a diorama, not a town
            if home is None:
                home = a._home = (a.x, a.y)
            r = random.Random(f"{self.seed}:mill:{a.name}:{self.turn}")
            if r.random() < 0.3:
                mdx, mdy = r.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
                tx, ty = a.x + mdx, a.y + mdy
                if (max(abs(tx - home[0]), abs(ty - home[1])) <= 3
                        and self.level.walkable(tx, ty)
                        and self.actor_at(tx, ty) is None
                        and (tx, ty) != (self.player.x, self.player.y)):
                    a.x, a.y = tx, ty
            return
        if self.sandbox and home is not None and a.allegiance == "monster":
            pd = max(abs(self.player.x - a.x), abs(self.player.y - a.y))
            on_its_ground = max(abs(self.player.x - home[0]),
                                abs(self.player.y - home[1])) <= LEASH
            if not on_its_ground and pd > 2 and not getattr(a, "_provoked", False):
                # it keeps to its own ground, but it is not a statue: it MILLS
                # about its home, so a watched town square visibly lives. Never
                # a bump (target tile must be empty): milling is ambience, the
                # real dynamics still come from brains when you are close.
                r = random.Random(f"{self.seed}:mill:{a.source}:{self.turn}")
                if r.random() < 0.4:
                    mdx, mdy = r.choice(((1, 0), (-1, 0), (0, 1), (0, -1),
                                         (1, 1), (-1, 1), (1, -1), (-1, -1)))
                    tx, ty = a.x + mdx, a.y + mdy
                    if (max(abs(tx - home[0]), abs(ty - home[1])) <= LEASH
                            and self.level.walkable(tx, ty)
                            and self.actor_at(tx, ty) is None
                            and (tx, ty) != (self.player.x, self.player.y)):
                        a._acted_turn = self.turn
                        a.x, a.y = tx, ty
                return
            if max(abs(a.x - home[0]), abs(a.y - home[1])) > LEASH and pd > 1:
                hx = (home[0] > a.x) - (home[0] < a.x)
                hy = (home[1] > a.y) - (home[1] < a.y)
                if abs(home[0] - a.x) >= abs(home[1] - a.y):
                    step = (hx, 0) if hx else (0, hy)
                else:
                    step = (0, hy) if hy else (hx, 0)
                a._acted_turn = self.turn
                self._npc_step(a, *step)
                return
        if (self.sandbox and not getattr(a, "_provoked", False)
                and max(abs(self.player.x - a.x),
                        abs(self.player.y - a.y)) > 40):
            return   # beyond earshot: brains sleep; mill/idle keeps it drifting
        if getattr(a, "brain", None) is None:
            a.brain = make_brain(self, a)
        dx, dy = a.brain.decide(self, a)
        if dx == 0 and dy == 0 and a.allegiance == "monster" and self.system("senses") is not None:
            # only hunters investigate sounds/scents; wildlife follows its own drives
            from .senses import investigate_step
            dx, dy = investigate_step(self, a)
        if dx or dy:
            a._acted_turn = self.turn   # claim the turn so fauna won't move it again
            self._npc_step(a, dx, dy)

    def _npc_step(self, a, dx, dy):
        tx, ty = a.x + dx, a.y + dy
        if (tx, ty) == (self.player.x, self.player.y):
            if self.hostile(a, self.player):
                self.attack(a, self.player)
            return
        t = self.actor_at(tx, ty)
        if t is not None:
            if self.hostile(a, t):
                self.attack(a, t)
            return
        if (self._on_surface() and a.allegiance == "monster"
                and (tx, ty) in self._town_tiles):
            return   # settled ground: nothing hostile crosses the threshold
        if self.level.walkable(tx, ty):
            a.x, a.y = tx, ty

    # ---- rendering ----
    def compose_frame(self):
        """The composited, viewport-sliced glyph grid plus the viewport origin.
        Front-ends colorize this; render() joins it into the plain string the
        headless demo prints."""
        grid = [row[:] for row in self.level.tiles]
        # biome terrain + wild landmarks paint over open floor (under everything else)
        for (x, y), gph in self._overlay.items():
            if grid[y][x] == ".":
                grid[y][x] = gph
        for it in self.items:
            grid[it.y][it.x] = it.glyph
        for a in self.actors:
            grid[a.y][a.x] = a.glyph
        grid[self.player.y][self.player.x] = "@"
        for s in self.systems:
            s.render_overlay(self, grid)
        # the grown world outsizes the terminal: follow the player with a viewport
        x0 = y0 = 0
        if self.level.w > self.width or self.level.h > self.height:
            x0 = max(0, min(self.player.x - self.width // 2, self.level.w - self.width))
            y0 = max(0, min(self.player.y - self.height // 2, self.level.h - self.height))
            grid = [row[x0:x0 + self.width] for row in grid[y0:y0 + self.height]]
        return grid, (x0, y0)

    def render(self, last_n: int = 6) -> str:
        grid, _origin = self.compose_frame()
        body = "\n".join("".join(r) for r in grid)
        p = self.player
        if self._dungeon is not None:
            where = f"Depths of {self.region_name}"
        elif self.sandbox:
            where = self.region_name
        else:
            where = f"Floor {self.floor}/{self.max_floor}"
        hud = (f"{where}  HP {max(0, p.hp)}/{p.max_hp}  "
               f"ATK {p.atk}  DEF {p.defense}"
               + ("" if self.sandbox else f"  | {self.region_name}"))
        extras = "  ·  ".join(e for e in (s.status_line(self) for s in self.systems) if e)
        tail = ("\n" + extras) if extras else ""
        return f"{body}\n{hud}{tail}\n" + "\n".join(self.messages[-last_n:])


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
