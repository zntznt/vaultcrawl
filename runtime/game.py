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
COMMUNE_TRUTHS = 2   # marginalia + lore fragments read
COMMUNE_COST = 4     # total salvaged matter, any mix
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
        self._in_overworld: bool = False        # Zen View map mode
        self._ow_cursor: tuple = (0, 0)         # cursor position in overworld grid
        self._ow_waypoint: tuple | None = None  # travel target set in overworld
        self.current_z: int = 0                # spatial z-coordinate (0=surface, negative=depths)
        self._levels: dict[int, object] = {}   # z -> Level for the current realm's z-stack
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
        self._last_logged = None
        self._dup_n = 1
        self._last_was_ambient = False
        self.turn = 0
        self.kills = 0
        self.items_taken = 0
        self.messages: list = []
        self.message_tags: list[str] = []
        self.alive = True
        self.won = False
        self._resting = False
        self._consecutive_rest = 0
        self._tension: int = 0              # complacency counter — rises on idle, decays on action
        self._aspect: str = ""              # region-granted temporary trait
        self._aspect_turns: int = 0         # turns spent in current region
        self._cant_camp: bool = False       # true if Renounce Rest was chosen
        self.player = None
        self.level = None
        self._levels = {}
        self.current_z = 0
        self.actors: list = []
        self.items: list = []
        self.region_name = ""
        self._places: list = []
        self._dungeon = None
        self._realm = "surface"
        self._realms: dict = {}
        self._gates: dict = {}
        self._town_rooms: set = set()
        # visual/UX features
        self._pulses: list = []           # Pulse Wave: [(x, y, ttl, glyph)] sound rings
        self._stains: dict = {}           # Memory Stains: (x,y) -> (glyph, event_text)
        self._graves: dict = {}           # Gravestone Glyphs: (x,y) -> death_record
        self._town_tiles: set = set()
        self._tint: dict = {}
        self._cell_region: dict = {}
        self._glow_cells: dict = {}
        self._landmarks: dict = {}
        self._frictions: dict = {}
        self._overlay: dict = {}
        self._region_env: dict = {}
        self._region_kind: dict = {}
        self._scarred_tiles: dict = {}      # terrain mod: scar glyphs with TTL
        self._bridges: list = []            # terrain mod: added road bridge tiles
        self._monuments: dict = {}          # terrain mod: boss-death landmarks
        self._region_by_comm = {self._region_community(r): r
                                for r in manifest["regions"]}
        self._region_faction = {r["id"]: r.get("factionId", "")
                                for r in manifest["regions"]}
        self._rel: dict = {}
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
            self._load_graves()
            self._build_sandbox()
        else:
            self.descend()

    def starting_kit(self, agent_name: str):
        """Provide each agent a personality-matched starting economic seed."""
        know = self.system("knowledge")
        salv = self.system("salvage")
        fcs = self.system("factions")

        if agent_name == "artisan":
            if salv:
                salv.inventory(self).add({"lamplight": 2}, quality=2)
            if know:
                nodes = self.m.get("graph", {}).get("nodes", {})
                hubs = [nid for nid, n in nodes.items() if n.get("role") == "hub"]
                if hubs:
                    know._reveal(self, hubs[0])
            # Pre-forged Recall sigil for immediate healing
            sigs = self.system("sigils")
            if sigs and len(sigs.slots) < sigs.max_slots(self):
                sigs.slots.append({"ability": "Recall", "base": "Recall",
                                   "durability": 2, "note": "forged", "role": "hub"})
                self.log("You start with a freshly forged Recall sigil.")

        elif agent_name == "cartographer":
            if salv:
                salv.inventory(self).add({"vellum": 1}, quality=1)
            if know:
                nodes = self.m.get("graph", {}).get("nodes", {})
                bridge = [nid for nid, n in nodes.items() if n.get("role") == "bridge"]
                if len(bridge) >= 2:
                    know._reveal(self, bridge[0])
                    know._reveal(self, bridge[1])
            self.player.max_hp += 8
            self.player.hp += 8
            self.log("You feel the resilience of countless maps.")

        elif agent_name == "emergent":
            if salv:
                salv.inventory(self).add({"iron": 1}, quality=2)
            self.player.hp = min(self.player.max_hp, self.player.hp + 4)
            # Combat readiness: start with defense
            self.player.defense = getattr(self.player, "defense", 0) + 2
            self.log("You stand ready. +2 DEF.")

        elif agent_name == "exploiter":
            if salv:
                salv.inventory(self).add({"brass": 1}, quality=2)
            sigs = self.system("sigils")
            if sigs and sigs.slots:
                for s in sigs.slots:
                    if s.get("ability") == "Ward":
                        s["durability"] = 3
                        break
            # Pre-forged Phase sigil for escape
            if sigs and len(sigs.slots) < sigs.max_slots(self):
                sigs.slots.append({"ability": "Phase", "base": "Phase",
                                   "durability": 2, "note": "forged", "role": "bridge"})
                self.log("A Phase sigil thrums — escape awaits.")

        elif agent_name == "seeker":
            if salv:
                salv.inventory(self).add({"moss": 1}, quality=1)
            if know:
                nodes = self.m.get("graph", {}).get("nodes", {})
                non_player = [nid for nid in nodes if nid != self.player.source]
                if non_player:
                    choice = non_player[hash(agent_name + "seed") % len(non_player)]
                    know._reveal(self, choice)
            # Balanced survival: extra HP + Recall sigil
            self.player.max_hp += 4
            self.player.hp += 4
            sigs = self.system("sigils")
            if sigs and len(sigs.slots) < sigs.max_slots(self):
                sigs.slots.append({"ability": "Recall", "base": "Recall",
                                   "durability": 2, "note": "forged", "role": "hub"})

        elif agent_name == "whisper":
            if salv:
                salv.inventory(self).add({"vellum": 1}, quality=1)
            if fcs:
                factions_list = list(getattr(fcs, "standing", {}).keys())
                if factions_list:
                    target = factions_list[hash(agent_name) % len(factions_list)]
                    current = fcs.standing.get(target, 0)
                    fcs.standing[target] = min(4, current + 1)
            # Phase sigil: flee when diplomacy fails
            sigs = self.system("sigils")
            if sigs and len(sigs.slots) < sigs.max_slots(self):
                sigs.slots.append({"ability": "Phase", "base": "Phase",
                                   "durability": 2, "note": "forged", "role": "bridge"})

    def _set_level(self, level, z: int = 0):
        self.level = level
        level.z = getattr(level, "z", z)
        self._levels[level.z] = level
        self.current_z = level.z

    def _depth_count(self, region: dict) -> int:
        if not self.sandbox:
            bos = max((b["depth"] for b in self.m["bosses"]
                       if b.get("regionId") == region["id"]), default=3)
            return max(1, min(4, bos // 6 + 1))
        return 1

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
                    or d.get("fmt") not in (9, 10)):
                return None
            from .dungeon import Level
            level = Level(w=d["w"], h=d["h"],
                          tiles=[list(row) for row in d["tiles"]], rooms=[],
                          player_start=tuple(d["player_start"]),
                          stairs=tuple(d["stairs"]))

            class C:
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
            return None

    def _load_graves(self):
        """Load cross-run death records from a graves file keyed by world seed."""
        import os, json as j
        path = os.path.expanduser("~/.vaultcrawl/graves.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = j.load(fh)
            for entry in data.get(self.seed, []):
                self._graves[tuple(entry["pos"])] = entry["text"]
        except (OSError, ValueError, KeyError):
            pass

    def _save_death(self, cause: str = "unknown"):
        """Record this death to the graves file for future runs."""
        import os, json as j
        path = os.path.expanduser("~/.vaultcrawl/graves.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = j.load(fh)
        except (OSError, ValueError):
            pass
        entry = {"pos": [self.player.x, self.player.y],
                 "text": f"Here lies you, slain by {cause} on floor {self.floor}"
                         f" in {self.region_name}.\n"
                         f"ATK {self.player.atk}  DEF {self.player.defense}  "
                         f"{self.kills} kills · {self.items_taken} items taken."}
        data.setdefault(self.seed, []).append(entry)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                j.dump(data, fh)
        except OSError:
            pass
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
                json.dump({"seed": self.seed, "sprawl": self.sprawl, "fmt": 10,
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
            self._set_level(settle(plan, seed=self.seed), z=0)
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
        self.player._base_max_hp = self.player.max_hp
        penalty = self._companion_penalty()
        self.player.max_hp = max(4, self.player._base_max_hp - penalty)
        self.player.hp = min(self.player.hp, self.player.max_hp)
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
        if self._graves:
            self._animate_graves()

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
        # dedup consecutive identical lines — but never dedup combat messages
        tag = "ambient" if ambient else self._tag_for(msg)
        if tag != "combat" and self.messages and (self.messages[-1] == msg or self._last_logged == msg):
            self._dup_n += 1
            self.messages[-1] = msg if self._dup_n == 1 else f"{msg} (x{self._dup_n})"
            return
        self._last_logged = msg
        self._dup_n = 1
        tag = "ambient" if ambient else self._tag_for(msg)
        getattr(self, "message_tags", []).extend([tag])
        self.messages.append(msg)

    def _tag_for(self, msg: str) -> str:
        """Categorize a message for filtered log display."""
        combat_kw = ("hits you", "strikes you", "You destroy", "You win",
                     "stands down", "fells", "You strike", "HP left",
                     "You die", "bleeds", "staggers", "wounded",
                     "shove", "blow", "Crystal", "detonates")
        discovery_kw = ("You enter", "You cross", "You stand in",
                        "You read", "cache", "lore fragment", "sigil slot",
                        "You feel", "New charge", "Quest complete",
                        "You integrate", "✦", "♛", "⚔", "~ The world",
                        "You slot", "You forge", "You know", "learned",
                        "You harvest", "You honour", "You hunker",
                        "You rest", "settle", "You settle")
        for kw in combat_kw:
            if kw in msg:
                return "combat"
        for kw in discovery_kw:
            if kw in msg:
                return "discovery"
        return ""

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
        return {"levels": dict(self._levels), "current_z": self.current_z,
                "actors": self.actors, "items": self.items,
                "room_notes": getattr(self, "room_notes", {}),
                "places": getattr(self, "_places", []),
                "motifs": getattr(self, "_motifs", {}),
                "tint": getattr(self, "_tint", {}),
                "rooms_seen": self._rooms_seen, "region_name": self.region_name,
                "gates": self._gates, "towns": (self._town_rooms, self._town_tiles),
                "dungeon": self._dungeon, "floor": self.floor,
                "felt": (self._glow_cells, self._landmarks, self._frictions,
                         self._cell_region),
                "wild": (getattr(self, "_wild_structs", {}),
                         getattr(self, "_region_of", {}),
                         getattr(self, "_fixtures", {}),
                         getattr(self, "_fixture_room", {})),
                "overlay": (getattr(self, "_overlay", {}),
                            getattr(self, "_region_env", {})),
                "terrains": (getattr(self, "_scarred_tiles", {}),
                             getattr(self, "_bridges", []),
                             getattr(self, "_monuments", {})),
                "pos": (self.player.x, self.player.y)}

    def _restore(self, s: dict, arrive=None):
        self._levels = s.get("levels", {})
        self.current_z = s.get("current_z", 0)
        self.level = self._levels.get(self.current_z)
        self.actors, self.items = s["actors"], s["items"]
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
        ter = s.get("terrains", ({}, [], {}))
        self._scarred_tiles, self._bridges, self._monuments = ter
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
        """First visit to a region's depths: generates a z-stack of deepening floors.
        Each z-level is an independent Level; stairs connect adjacent z-levels.
        The warden dwells at the deepest z-level."""
        region = next(r for r in self.m["regions"] if r["id"] == region_id)
        self._dungeon = {"region": region}
        order = sorted(r["id"] for r in self.m["regions"])
        self.floor = 2 + order.index(region_id)
        self.region_name = region["name"]
        nz = self._depth_count(region)
        self._town_rooms, self._town_tiles = set(), set()
        self._motifs, self._fixtures, self._fixture_room = {}, {}, {}
        self._wild_structs, self._region_of, self._overlay = {}, {}, {}
        self.actors, self.items = [], []
        self._gates = {}
        boss_spec = next((b for b in self.m["bosses"]
                          if b["regionId"] == region_id), None)
        cap = max(2, boss_spec["tier"] if boss_spec else 3)
        pool = self.enemies_by_region.get(region_id) or self.m["enemies"]

        # generate from z=-1 (shallowest) down to z=-nz (deepest)
        for depth in range(1, nz + 1):
            z = -depth
            seed_str = f"{self.seed}:depths:{region_id}:z:{z}"
            lvl = generate_level(max(64, self.width), max(26, self.height),
                                 seed_str, 1, max_rooms=8 + depth)  # deeper=more rooms
            lvl.z = z
            self._levels[z] = lvl

            # place stairs: < up (except z=-1 gets surface gate), > down (except deepest)
            px, py = lvl.player_start
            if depth == 1:
                self._gates[(px, py)] = "surface"
                lvl.tiles[py][px] = "<"
            else:
                lvl.tiles[py][px] = "<"   # stair to z=-depth+1
            if depth < nz:
                # stair down at the bottom of this floor
                door = lvl.rooms[-1].center if lvl.rooms else (lvl.w // 2, lvl.h // 2)
                lvl.tiles[door[1]][door[0]] = ">"
                # link the stair-down to the Level below's player_start
                lower = self._levels.get(z - 1)
                if lower:
                    # match stairs: down-stair at (door[0], door[1]) on this level
                    # corresponds to the player_start on the level below
                    lower.tiles[lower.player_start[1]][lower.player_start[0]] = "<"
                    # also add a return stair at the lower level's end
                    low_door = lower.rooms[-1].center if lower.rooms else (lower.w//2, lower.h//2)
                    lower.tiles[low_door[1]][low_door[0]] = ">"
                    # put a stair-up in the lower level matching this level's down
                    # find a tile above or below
                    if 0 <= door[1] < lower.h and 0 <= door[0] < lower.w:
                        lower.tiles[door[1]][door[0]] = "<"

            # spawn enemies on this z-level (sparser on shallower, denser on deeper)
            free_tiles = free_floor_tiles(lvl, {(lvl.player_start[0], lvl.player_start[1])})
            rng = random.Random(f"{seed_str}:spawn")
            rng.shuffle(free_tiles)
            n_enemies = min(2 + depth, len(free_tiles) // 4)
            for _ in range(n_enemies):
                if not free_tiles:
                    break
                spec = rng.choice(pool)
                tier_cap = max(1, min(spec["tier"], cap + depth - 1))
                spec = {**spec, "tier": tier_cap}
                en = make_enemy(spec, *free_tiles.pop())
                en.faction = self._region_faction.get(region_id, "")
                en.z = z
                self.actors.append(en)

        # boss at deepest level
        deepest = self._levels.get(-nz)
        if boss_spec is not None and deepest is not None:
            free = free_floor_tiles(deepest, {(deepest.player_start[0], deepest.player_start[1])})
            if free:
                rng = random.Random(f"{self.seed}:depths:{region_id}:boss")
                bx, by = rng.choice(free)
                boss = make_boss(boss_spec, bx, by)
                boss.faction = self._region_faction.get(region_id, "")
                boss.z = -nz
                if boss_spec["sourceNoteId"] == self.up.throne:
                    boss.name = "Ascendant " + boss.name
                self.actors.append(boss)
                self.log(f"!! {boss.name} — {boss_spec.get('title', '')} — "
                         f"dwells in the deep (z={-nz}).")
                hist = self._note_history(boss.source, salt="boss")
                if hist:
                    self.log(f"  {hist}")

        # passages to bordering regions at each z-level
        adj_regions = sorted(self._region_adjacency().get(region_id, ()))
        for z, lvl in sorted(self._levels.items()):
            exits = sorted(lvl.rooms[1:-1] if len(lvl.rooms) > 2 else [],
                           key=lambda r: r.center)
            for i, adj in enumerate(adj_regions):
                if i >= len(exits):
                    break
                t = exits[i].center
                if lvl.walkable(*t) and t not in self._gates:
                    self._gates[t] = adj
                    lvl.tiles[t[1]][t[0]] = ">"

        # set current level to z=-1 (shallowest entry)
        self._set_level(self._levels.get(-1, deepest), z=-1)
        self._build_felt()

        if nz > 1:
            self.log(f"The depths descend {nz} floors; (<) climbs, (>) goes deeper.")
        elif self.sandbox:
            self.log("Passages (>) lead beneath the borders; (<) climbs home.")

        arrive = next((p for p, dst in sorted(self._gates.items())
                       if dst == from_realm), self.level.player_start)
        self.player.x, self.player.y = arrive
        self.player.z = self.current_z

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
        if etype == "forge_used":
            pos = data.get("pos", (self.player.x, self.player.y))
            self.emit("noise", pos=pos, volume=6)
            # Chronicle: forge activity persists between runs (Upheaval sanctums)
            try:
                from runtime.persistence import chronicle
                r = self.region_for(self.floor)
                if r:
                    chronicle().record_forge(r["id"])
            except Exception:
                pass
        elif etype == "corpse_spawned":
            pos = data.get("pos")
            if pos:
                self.emit("noise", pos=pos, volume=4)
        elif etype == "lore_read":
            note_id = data.get("note", "")
            # Chronicle: lore-reading creates ghosts in future runs
            try:
                from runtime.persistence import chronicle
                chronicle().record_lore(note_id)
            except Exception:
                pass
            if note_id and hash(f"{self.seed}:{self.turn}:lore_chain") % 100 < 30:
                know = self.system("knowledge")
                if know:
                    nodes = self.m.get("graph", {}).get("nodes", {})
                    if note_id in nodes:
                        neighbors = nodes[note_id].get("neighbors", [])
                        unrevealed = [n for n in neighbors if not know.is_known(n)]
                        if unrevealed:
                            choice_idx = hash(f"{self.seed}:{self.turn}:lore_chain:{note_id}") % len(unrevealed)
                            choice = unrevealed[choice_idx]
                            know.reveal(choice)

    # ---- floor lifecycle ----
    def descend(self):
        if self.sandbox:
            t = self.level.tiles[self.player.y][self.player.x]
            if t in "><":
                from .body_parts import is_immobilized
                if is_immobilized(self.player):
                    self.log("Your legs won't hold; you cannot descend.")
                    return
                if self.traverse():
                    return
                self._z_descend()
                return
            self.log("No way through here; doors (>) wait in each district's "
                     "heart, stairs (<) climb home.")
            return
        self.floor += 1
        rng = random.Random(f"{self.seed}:spawn:{self.floor}")
        lvl = generate_level(self.width, self.height, self.seed, self.floor)
        self._set_level(lvl, z=0)
        px, py = self.level.player_start
        if self.player is None:
            self.player = make_player(px, py)
            self.player._base_max_hp = self.player.max_hp
        else:
            self.player.x, self.player.y = px, py
            # rest between floors: a fixed fraction, not a stat gain (no power creep)
            self.player.hp = min(self.player.max_hp, self.player.hp + self.player.max_hp // 5)
        penalty = self._companion_penalty()
        self.player.max_hp = max(4, self.player._base_max_hp - penalty)
        self.player.hp = min(self.player.hp, self.player.max_hp)
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
        # Early floors: limit quality so agents can build their economy
        if self.floor <= 3:
            n = max(1, n // 2)  # fewer enemies on tutorial floors
        for _ in range(n):
            if not free:
                break
            spec = rng.choice(pool)
            spec = {**spec, "tier": max(1, min(spec["tier"], cap))}
            en = make_enemy(spec, *self.spot_for(spec["sourceNoteId"], free))
            en.faction = self._region_faction.get(spec.get("regionId", ""), "")
            # Early floors: cap quality so agents survive long enough to build economy
            if self.floor <= 3:
                q = getattr(en, 'quality', 0)
                if q > self.floor:  # floor 1: max Normal(0), floor 2: max Uncommon(1), floor 3: max Rare(2)
                    en.quality = self.floor
                    if hasattr(en, 'hp'):
                        en.hp = en.max_hp = min(en.hp, en.max_hp)
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
                hist = self.system("history")
                if hist is not None and hist.read >= 3:
                    boss._telegraphed = True
                    self.log("You've read of this one before — you know its rhythm.")

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

        # Early-floor safety: no elite blocks the path to stairs
        if self.floor <= 3:
            stairs = getattr(self.level, 'stairs', None)
            if stairs:
                from collections import deque
                start = (self.player.x, self.player.y)
                prev = {start: None}
                q = deque([start])
                found = False
                while q:
                    cur = q.popleft()
                    if cur == stairs:
                        found = True
                        break
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nxt = (cur[0] + dx, cur[1] + dy)
                        if nxt not in prev and self.level.walkable(*nxt):
                            prev[nxt] = cur
                            q.append(nxt)
                if found:
                    path = set()
                    cur = stairs
                    while cur != start:
                        path.add(cur)
                        cur = prev.get(cur)
                        if cur is None:
                            break
                    for a in list(self.actors):
                        tier = getattr(a, 'tier', 1)
                        if tier >= 3 and (a.x, a.y) in path and not getattr(a, 'is_player', False):
                            non_elites = [o for o in self.actors
                                          if getattr(o, 'tier', 1) < 3
                                          and not getattr(o, 'is_player', False)]
                            if non_elites:
                                furthest = max(non_elites,
                                               key=lambda o: abs(o.x - stairs[0]) + abs(o.y - stairs[1]))
                                ax, ay = a.x, a.y
                                a.x, a.y = furthest.x, furthest.y
                                furthest.x, furthest.y = ax, ay
                                break

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
        if self._graves:
            self._animate_graves()

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
            from .body_parts import is_immobilized
            if is_immobilized(self.player):
                self.log("Your legs won't hold; you cannot climb.")
                return
            if self.traverse():
                return
            self._z_ascend()
            return
        self.log("There is no way up from here.")

    def _z_descend(self):
        """Move one z-level deeper within the current realm."""
        if not self._dungeon:
            return
        nxt = self.current_z - 1
        if nxt not in self._levels:
            self.log("There is no way deeper from here.")
            return
        self._set_level(self._levels[nxt], z=nxt)
        self.player.x, self.player.y = self.level.player_start
        self.player.z = nxt
        self.log(f"-- You descend deeper (z={nxt}). --")
        for s in self.systems:
            s.on_floor_enter(self)

    def _z_ascend(self):
        """Move one z-level upward within the current realm."""
        if not self._dungeon:
            return
        nxt = self.current_z + 1
        if nxt not in self._levels:
            self.log("There is no way up from here.")
            return
        self._set_level(self._levels[nxt], z=nxt)
        self.player.x, self.player.y = self.level.player_start
        self.player.z = nxt
        self.log(f"-- You climb back up (z={nxt}). --")
        for s in self.systems:
            s.on_floor_enter(self)

    def try_move(self, dx: int, dy: int):
        if not self.alive or self.won:
            return
        if dx != 0 or dy != 0:
            if self._resting:
                self.log("You break camp.")
            self._resting = False
            self._consecutive_rest = 0
        self.turn += 1
        self._tick_pulses()
        self._tick_tension()
        self._tick_aspect()
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
                    # aspect resets on region change
                    if self._aspect:
                        self.log(f"The {self._aspect.split(':')[0]} fades as you leave.")
                        self._aspect = ""
                    self._aspect_turns = 0
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
            self.encounter_resolve(self.player)
        self._tick_effects()
        self.enemies_act()
        self._restore_winded()
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
        """Approach a hostile without violence. Success rate scales with faction
        standing: allied houses always hear you, neutral ones may be swayed, and
        hostile houses never stand down. Cost is BECALM_COST x tier matter.
        Bosses are commune()'s business."""
        if target.is_boss or target.allegiance != "monster":
            return False
        fcs = self.system("factions")
        faction = getattr(target, "faction", "")
        standing = fcs.standing.get(faction, 0) if fcs else 0
        if standing < 0:
            self.log(f"{target.name} bristles; your houses are at war.")
            return False
        total = BECALM_COST * max(1, target.tier)
        salv = self.system("salvage")
        bag = salv.inventory(self) if salv is not None else None
        if bag is None or bag.total() < total:
            self.log(f"{target.name} is not moved. (Offer {total} matter.)")
            return False
        if standing >= 3:
            self.log(f"You speak its own thought back to it; {target.name} stills.")
        elif standing >= 1:
            if hash(f"{self.seed}:{self.turn}:becalm:{target.source}") % 100 >= 50:
                self.log(f"{target.name} remains wary of you.")
                return False
        else:
            if hash(f"{self.seed}:{self.turn}:becalm:{target.source}") % 100 >= 25:
                self.log(f"{target.name} refuses your gesture.")
                return False
        cost = _spend_matter(bag, total)
        offered = " ".join(f"{m}x{q}" for m, q in sorted(cost.items()))
        self.log(f"You share what you have gathered ({offered}); "
                 f"{target.name} is placated.")
        self._join_wild(target)
        self._tension = max(0, self._tension - 15)
        return True

    def _join_wild(self, target):
        """A stood-down hostile joins the ecology: indifferent to you, no faction
        alarm, and it re-picks a brain fitting its new nature."""
        target.allegiance = "wild"
        target.brain = None
        self.emit("becalmed", actor=target, pos=(target.x, target.y))

    def encounter_resolve(self, actor) -> str | None:
        """Called when player approaches an elite/boss. Returns an encounter outcome
        or None if no encounter triggers (already resolved, or no elite present)."""
        nearby = []
        for a in self.actors:
            if a is self.player or a.hp <= 0:
                continue
            d = max(abs(a.x - self.player.x), abs(a.y - self.player.y))
            if d <= 6 and (getattr(a, "is_boss", False) or getattr(a, "tier", 1) >= 3):
                nearby.append((d, a))
        if not nearby:
            return None
        _, target = min(nearby, key=lambda x: x[0])

        if hasattr(target, "_encountered"):
            return None
        target._encountered = True

        hp_pct = self.player.hp * 100 // max(1, getattr(self.player, "max_hp", self.player.hp))
        salv = self.system("salvage")
        matter = salv.inventory(self).total() if salv else 0
        fcs = self.system("factions")
        faction = getattr(target, "faction", "")
        standing = fcs.standing.get(faction, 0) if fcs else 0
        know = self.system("knowledge")
        source_known = know.is_known(getattr(target, "source", "")) if know else False
        truths = (getattr(self.system("marginalia"), "read", 0) or 0) + \
                 (getattr(self.system("history"), "read", 0) or 0)

        options = []

        if standing >= 1:
            options.append("coerce")
        # Whisper always gets parley — personality, not a resource gate
        if source_known or getattr(self.player, "_agent_name", "") == "whisper":
            options.append("parley")
        if matter >= 1:
            options.append("flee")
        if truths >= 1:
            options.append("appease")
        if hp_pct >= 30:
            options.append("fight")

        # Mercy: desperate agents always get a way out
        if hp_pct < 30 and not options:
            if matter >= 1:
                options.append("flee")
            else:
                options.append("appease")

        if not options:
            options.append("fight")

        # Weaken early-floor elites so agents survive long enough to reach emergence
        if self.floor <= self.max_floor * 0.15 and not getattr(target, "is_boss", False):
            target.hp = max(1, target.hp * 3 // 4)
            target.max_hp = target.hp

        preferred = [o for o in options if o != "fight"]
        choice = preferred[0] if preferred else "fight"

        if choice == "coerce":
            if salv and salv.inventory(self).total() >= 1:
                from .components import inv
                bag = inv(self.player)
                richest = max(bag.comp.keys(), key=lambda k: bag.comp[k]) if bag.comp else "scrap"
                bag.pay({richest: 1})
                self.log(f"You offer {richest} to {target.name}. It steps aside.")
                target.allegiance = "wild"
                target.brain = None
        elif choice == "parley":
            self.log(f"{target.name} regards you with recognition.")
            target.allegiance = "npc"
            if getattr(target, 'is_boss', False) and target.source == self.final_boss_source:
                self.won = True
                self.log("The final boss lays down its arms. You have won through diplomacy.")
        elif choice == "flee":
            if salv and salv.inventory(self).total() >= 2:
                self._spend_matter(salv.inventory(self), 2)
                self.log(f"You toss matter as a distraction. {target.name} chases the clatter.")
                for dx, dy in ((5, 0), (-5, 0), (0, 5), (0, -5)):
                    nx, ny = target.x + dx, target.y + dy
                    if self.level.walkable(nx, ny):
                        target.x, target.y = nx, ny
                        self.emit("noise", pos=(nx, ny), volume=8)
                        break
        elif choice == "appease":
            self.log(f"You commune briefly. {target.name} lowers its guard.")
            target.allegiance = "wild"
            target.brain = None

        return choice

    def recruit(self, target):
        """A swayed creature chooses to walk with you: it mirrors your hostilities
        (its own kin stay kin), leaves its territory behind, and keeps your side."""
        target.allegiance = "companion"
        target._home = None                    # its road is yours now
        from .sense import make_brain
        target.brain = make_brain(self, target, name="companion")
        self.emit("recruited", actor=target, pos=(target.x, target.y))
        fcs = self.system("factions")
        faction = getattr(target, "faction", "")
        if fcs and faction:
            try:
                current = getattr(fcs, "standing", {}).get(faction, 0)
                fcs.standing[faction] = current + 2
                self.emit("standing_changed", faction=faction, standing=current + 2, cause="recruited")
            except Exception:
                pass
        try:
            from runtime.persistence import chronicle
            chronicle().record_companion_recruited()
        except Exception:
            pass
        if hasattr(self.player, '_base_max_hp'):
            penalty = self._companion_penalty()
            self.player.max_hp = max(4, self.player._base_max_hp - penalty)
            self.player.hp = min(self.player.hp, self.player.max_hp)
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
        """Pass the turn in place. On settled ground, waiting is REST.
        Three consecutive waits enter camp mode: faster healing, status recovery.
        Outside towns, resting still provides a small heal if no hostiles are near.
        Cleared rooms (no hostiles) provide safer rest. Emergency heal: spend matter."""
        if not self.alive or self.won:
            return
        on_town = (self._on_surface()
                   and (self.player.x, self.player.y) in self._town_tiles
                   and not getattr(self, "_cant_camp", False))
        near_hostile = any(self.hostile(self.player, a)
                           and max(abs(a.x - self.player.x), abs(a.y - self.player.y)) <= 4
                           for a in self.actors)
        # Room-clearing check: is the current room free of hostiles?
        room_idx = self.room_at(self.player.x, self.player.y)
        room_clear = False
        if room_idx is not None:
            room_tiles = self.room_tiles(room_idx) if hasattr(self, 'room_tiles') else set()
            room_clear = all(
                not self.hostile(self.player, a) or max(abs(a.x-self.player.x), abs(a.y-self.player.y)) > 4
                for a in self.actors
            ) if room_tiles else False

        if on_town and near_hostile:
            self.log("Hostiles too near; you cannot rest.")
            on_town = False
            self._resting = False
            self._consecutive_rest = 0

        # Kill-confidence decays on rest: each rest reduces the bonus by 1
        if hasattr(self.player, '_kill_confidence') and self.player._kill_confidence > 0:
            self.player._kill_confidence -= 1
            self.player.max_hp -= 1
            self.player.hp = min(self.player.hp, self.player.max_hp)

        # non-town resting: small heal if safe and no hostiles nearby
        can_rest = on_town or (not near_hostile and self.player.hp < self.player.max_hp)
        if can_rest:
            if on_town:
                self._consecutive_rest += 1
                if self._consecutive_rest >= 3 and not self._resting:
                    self._resting = True
                    self.log("You settle in to rest...")
                    if getattr(self.player, "_bleeding", 0) > 0:
                        self.player._bleeding = 0
                        self.log("Your bleeding stops.")
                    if getattr(self.player, "_slowed", 0) > 0:
                        self.player._slowed = 0
                        self.player.speed = getattr(self.player, "_base_speed", 1.0)
            from .body_parts import heal_body
            # Healing: cleared room (3 HP), town rest (2-3 HP), otherwise 1 HP
            heal = 1
            if room_clear:
                heal = 3
                self.log("The room is clear. You rest deeply.")
            if on_town:
                heal = 3 if self._resting else 2
                if self._aspect and "Hallowed" in self._aspect:
                    heal *= 2
            heal_body(self.player, heal)
            tag = f"+{heal} HP"
            self.log(f"You rest ({tag}).")
            self.absorb_aspect()
        # Emergency heal: spend 1 matter for +3 HP when below 50% and no hostiles near
        elif not near_hostile and self.player.hp * 100 < self.player.max_hp * 50:
            salv = self.system("salvage")
            if salv and salv.inventory(self).total() >= 1:
                bag = salv.inventory(self)
                richest = max(bag.comp.keys(), key=lambda k: bag.comp[k]) if bag.comp else "scrap"
                bag.pay({richest: 1})
                heal_body(self.player, 3)
                self.log(f"You spend {richest} to staunch your wounds (+3 HP).")
        self.turn += 1
        self._tick_effects()
        self.enemies_act()
        self._restore_winded()
        for s in self.systems:
            s.on_player_act(self)

    def interact(self):
        """Contextual interaction with what's underfoot: flora, structures, decay, etc.
        Iterates all systems, collects handlers, and consumes the turn if any fire."""
        if not self.alive or self.won:
            return
        weather = self.system("weather")
        if weather:
            props = getattr(weather, 'props_at', None)
            if props and props(self.player.x, self.player.y):
                self.clear_weather()
                return
        decay = self.system("decay")
        if decay and hasattr(decay, 'corpses') and (self.player.x, self.player.y) in decay.corpses:
            if (hasattr(self.player, 'body') and self.player.body and
                any(p['hp'] < p['max'] for p in self.player.body.values())):
                self.repair_part()
                return
        handled = False
        for s in self.systems:
            try:
                if s.on_interact(self):
                    handled = True
            except Exception:
                pass
        if handled:
            self.turn += 1
            self._tick_effects()
            self.enemies_act()
            self._restore_winded()
        for s in self.systems:
            s.on_player_act(self)
        # Craft wires: auto-cast and condition triggers
        try:
            hp = self.player.hp
            mx = getattr(self.player, "max_hp", hp)
            hp_pct = hp * 100 // mx if mx > 0 else 100
            from runtime.craft import CraftSystem
            CraftSystem.apply_wires(self, "player_hp_check", hp_pct=hp_pct)
        except Exception:
            pass
        else:
            self.log("Nothing here to interact with.")

    def repair_part(self):
        """Cogmind-style: salvage a corpse at your feet to repair your worst body part.
        Costs 1 matter from inventory. Heals the most-damaged part by 2 HP."""
        if not self.alive or self.won:
            return
        corpse = None
        decay = self.system("decay")
        if decay and hasattr(decay, 'corpses'):
            corpse = decay.corpses.get((self.player.x, self.player.y))
        if corpse is None:
            self.log("Nothing to salvage here.")
            return
        if not hasattr(self.player, 'body') or not self.player.body:
            self.log("You have nothing to mend.")
            return
        parts = self.player.body
        worst_name = min(parts.keys(), key=lambda p: parts[p]['hp'] / max(1, parts[p]['max']))
        worst_part = parts[worst_name]
        if worst_part['hp'] >= worst_part['max']:
            self.log("Your body is whole.")
            return
        salv = self.system("salvage")
        if salv is None:
            return
        inv = salv.inventory(self)
        if inv.total() < 1:
            self.log("You need matter to salvage.")
            return
        _spend_matter(inv, 1)
        from .body_parts import heal_body
        heal_body(self.player, 2)
        self.log(f"You salvage the corpse, mending your {worst_name} (+2 HP).")
        if hasattr(decay, 'corpses'):
            decay.corpses.pop((self.player.x, self.player.y), None)
        self.turn += 1
        self._tick_effects()
        self.enemies_act()
        self._restore_winded()
        for s in self.systems:
            s.on_player_act(self)

    def shield(self):
        """Raise your guard: +1 defense (capped) or a small self-heal once capped.
        Uses the invariant-safe act_shield from abilities, so this costs no new
        ability code."""
        if not self.alive or self.won:
            return
        from .abilities import act_shield, SHIELD_CAP
        if self.player.defense >= SHIELD_CAP and self.player.hp >= self.player.max_hp:
            self.log("Your guard is already at its peak.")
            return
        act_shield(self, self.player)
        self.turn += 1
        self._tick_effects()
        self.enemies_act()
        self._restore_winded()
        for s in self.systems:
            s.on_player_act(self)

    def shove(self, dx: int, dy: int):
        """Push an adjacent enemy one tile in the given direction. Deals no direct
        damage — only environmental damage if the destination is a hazard tile."""
        if not self.alive or self.won:
            return
        target = self.actor_at(self.player.x + dx, self.player.y + dy)
        if target is None or not self.hostile(self.player, target):
            self.log("Nothing to shove there.")
            return
        dest = (target.x + dx, target.y + dy)
        if not self.level.walkable(*dest) or self.actor_at(*dest) is not None or dest == (self.player.x, self.player.y):
            self.log(f"{target.name} has no room to be pushed.")
            return
        target.x, target.y = dest
        self.log(f"You shove {target.name}.")
        self.turn += 1
        self._tick_effects()
        self.enemies_act()
        self._restore_winded()
        for s in self.systems:
            s.on_player_act(self)

    def _companion_penalty(self) -> int:
        comps = [a for a in self.actors if getattr(a, 'allegiance', '') == 'companion']
        extra = max(0, len(comps) - 1)
        return extra * 4

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
        """(archetype, damage_type) for a creature's PORTRAIT."""
        src = getattr(target, "source", "")
        for group in ("enemies", "bosses"):
            for e in self.m.get(group, []):
                if e.get("sourceNoteId") == src:
                    return e.get("archetype", "construct"), e.get("damageType", "")
        from .entities import ARCH_GLYPH
        g2a = {v: k for k, v in ARCH_GLYPH.items()}
        return g2a.get(getattr(target, "glyph", ""), "construct"), ""

    def inspect_actor(self, actor) -> list[str]:
        """Return formatted lines describing one actor in detail (free action)."""
        lines = [f"HP {max(0, actor.hp)}/{actor.max_hp}  ·  ATK {actor.atk}  ·  DEF {actor.defense}"]
        tier = getattr(actor, "tier", 1)
        if tier > 1:
            lines[-1] += f"  ·  tier {tier}"
        body = getattr(actor, "body", None)
        if body:
            parts = [f"{p[:1]}{body[p]['hp']}" for p in ("head", "torso", "legs")]
            lines.append("body: " + " ".join(parts))
        arch, dmg = self.creature_look(actor)
        lines.append(f"damage: {dmg or 'physical'}  ·  faction: {actor.faction or 'none'}"
                     + (f" ({actor.allegiance})" if actor.allegiance != "monster" else ""))
        nid = getattr(actor, "source", "")
        if nid:
            voice = self._weave_note(nid, salt=f"inspect:{self.turn}")
            if voice:
                lines.append("")
                lines.append(f'"{voice}"')
        return lines

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
            # Flavor Window: the note's own words from the vault corpus
            nid = self.room_notes.get(idx)
            if nid not in self._flavored:
                corpus = self.m.get("corpus", {})
                lines = corpus.get("lines", {}).get(nid, [])
                if lines:
                    self.log(f"  \"{lines[0][:80]}\"")
                    if len(lines) > 1:
                        self.log(f"  \"{lines[1][:80]}\"")
                self._flavored.add(nid)

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
        if getattr(actor, 'is_boss', False) and actor.source == self.final_boss_source and not self.won:
            self.won = True
            self.log("The deepest thought in the vault falls silent. You win.")
        if getattr(actor, 'is_player', False):
            try:
                from runtime.persistence import chronicle
                pos = (actor.x, actor.y)
                hp = actor.hp
                salv = self.system("salvage")
                inv = dict(getattr(salv.inventory(self), 'comp', {})) if salv else {}
                last_act = self.messages[-1] if self.messages else ""
                had_comp = any(getattr(a, 'allegiance', '') == 'companion' for a in self.actors)
                resting = getattr(self, '_resting', False)
                chronicle().record_death(pos, hp, inv, last_act, had_comp, resting, self.floor)
            except Exception:
                pass
        if getattr(actor, 'allegiance', '') == 'companion':
            fcs = self.system("factions")
            faction = getattr(actor, 'faction', '')
            if fcs and faction:
                try:
                    current = getattr(fcs, 'standing', {}).get(faction, 0)
                    fcs.standing[faction] = current - 2
                    self.emit("standing_changed", faction=faction, standing=current - 2, cause="companion_died")
                except Exception:
                    pass
            try:
                from runtime.persistence import chronicle
                chronicle().record_companion_death(actor.name, cause)
            except Exception:
                pass
        if hasattr(self.player, '_base_max_hp'):
            penalty = self._companion_penalty()
            self.player.max_hp = max(4, self.player._base_max_hp - penalty)
            self.player.hp = min(self.player.hp, self.player.max_hp)
        self.emit("actor_died", actor=actor, cause=cause, pos=(actor.x, actor.y))
        decay = self.system("decay")
        if decay and hasattr(decay, 'corpses'):
            pos = (actor.x, actor.y)
            if pos in decay.corpses:
                aspect = getattr(self, '_aspect', '')
                if 'acid' in aspect.lower() or 'corrosive' in aspect.lower():
                    decay.corpses[pos] = 2
                elif 'hallowed' in aspect.lower() or 'sacred' in aspect.lower():
                    decay.corpses[pos] = 20

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

    def _tick_effects(self):
        """Per-turn decay of status effects: bleeding deals damage, counters tick.
        Also decay creature emotions each turn (anger/fear drift)."""
        self._tick_weather_suppression()
        from .sense import decay_emotions, apply_trigger
        for a in list(self.actors):
            bleed = getattr(a, "_bleeding", 0)
            if bleed > 0:
                a.hp -= bleed
                if a.hp <= 0:
                    self.kill(a, "bleeding")
                    if a.is_player:
                        self.alive = False
                        self._save_death(cause="bleeding")
                        self.log("You bleed out.")
            decay_emotions(a)
            # fire_near trigger: standing on or adjacent to fire
            r = self.system("reactions")
            if r is not None:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if r.is_hazard(a.x + dx, a.y + dy):
                            apply_trigger(self, a, "fire_near", 0.4)
                            break

    def clear_weather(self, radius: int = 5):
        """Spend 1 matter to clear weather hazards in a radius around the player.
        Lasts 20 turns before weather returns."""
        if not self.alive or self.won:
            return
        salv = self.system("salvage")
        if salv is None or salv.inventory(self).total() < 1:
            structures = self.system("structures")
            crystal_consumed = False
            if structures and hasattr(structures, 'crystals'):
                px, py = self.player.x, self.player.y
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (0, 0)):
                    if (px + dx, py + dy) in getattr(structures, 'crystals', set()):
                        structures.crystals.discard((px + dx, py + dy))
                        crystal_consumed = True
                        self.log("You channel the crystal's energy — the air clears.")
                        break
            if not crystal_consumed:
                self.log("You need matter or a nearby crystal to clear the weather.")
                return
        else:
            from .components import inv as get_inv
            bag = get_inv(self.player) if hasattr(self.player, '_inv') else salv.inventory(self)
            richest = max(bag.comp.keys(), key=lambda k: bag.comp[k]) if bag.comp else "scrap"
            bag.pay({richest: 1})
            self.log(f"You spend {richest} to clear the sky.")
        weather = self.system("weather")
        if weather is None:
            return
        if not hasattr(self, '_weather_suppressed'):
            self._weather_suppressed = {}
        px, py = self.player.x, self.player.y
        for y in range(max(0, py - radius), min(self.level.h, py + radius + 1)):
            for x in range(max(0, px - radius), min(self.level.w, px + radius + 1)):
                self._weather_suppressed[(x, y)] = 20
        self.log(f"The weather clears in a {radius}-tile radius for 20 turns.")
        self.emit("weather_cleared", pos=(self.player.x, self.player.y), radius=radius)
        self.turn += 1
        self._tick_effects()
        self.enemies_act()
        for s in self.systems:
            s.on_player_act(self)

    def is_weather_suppressed(self, x: int, y: int) -> bool:
        """Check if weather is suppressed at a given position."""
        return getattr(self, '_weather_suppressed', {}).get((x, y), 0) > 0

    def absorb_aspect(self):
        """Absorb weather aspect for permanent power after 3 consecutive rests in weather.
        Clears the weather on this tile permanently and grants a buff."""
        if not self.alive or self.won:
            return
        if not getattr(self, '_rest_tile', None):
            self._rest_tile = (self.player.x, self.player.y)
            self._rest_tile_turns = 1
            return
        current_tile = (self.player.x, self.player.y)
        if current_tile == self._rest_tile:
            self._rest_tile_turns += 1
        else:
            self._rest_tile = current_tile
            self._rest_tile_turns = 1
            return

        if self._rest_tile_turns < 3:
            return

        weather = self.system("weather")
        if weather is None:
            self._rest_tile_turns = 0
            return
        props = getattr(weather, 'props', {})
        tile_props = props.get(current_tile, set()) if isinstance(props, dict) else set()
        if not tile_props:
            self._rest_tile_turns = 0
            return

        aspect_buff = None
        aspect_name = ""
        if "acid" in str(tile_props).lower() or "corrosive" in str(tile_props).lower():
            aspect_buff = "corrosive_touch"
            aspect_name = "Corrosive Touch"
        elif "chill" in str(tile_props).lower() or "frozen" in str(tile_props).lower() or "cold" in str(tile_props).lower():
            aspect_buff = "cold_endurance"
            aspect_name = "Cold Endurance"
        elif "static" in str(tile_props).lower() or "charged" in str(tile_props).lower():
            aspect_buff = "static_discharge"
            aspect_name = "Static Discharge"

        if aspect_buff is None:
            self._rest_tile_turns = 0
            return

        if not hasattr(self.player, '_absorbed_aspects'):
            self.player._absorbed_aspects = []
        if len(self.player._absorbed_aspects) >= 3:
            self.log("You cannot absorb any more of the weather.")
            self._rest_tile_turns = 0
            return
        self.player._absorbed_aspects.append(aspect_buff)
        self.log(f"You have absorbed the weather. You gain {aspect_name}.")

        if not hasattr(self, '_weather_suppressed'):
            self._weather_suppressed = {}
        self._weather_suppressed[current_tile] = 9999

        if aspect_buff == "corrosive_touch":
            if hasattr(self.player, 'attack'):
                self.player.attack = getattr(self.player, 'attack', 4) + 1
                self.log("Your attacks deal +1 corrosive damage.")
        elif aspect_buff == "cold_endurance":
            self.player.defense = getattr(self.player, 'defense', 0) + 2
            self.log("Your skin hardens against the cold. +2 DEF.")
        elif aspect_buff == "static_discharge":
            if not hasattr(self.player, '_static_discharge'):
                self.player._static_discharge = True
                self.log("Static crackles across your fingertips.")

        self._rest_tile_turns = 0
        self.emit("aspect_absorbed", pos=current_tile, buff=aspect_buff)

    def _tick_weather_suppression(self):
        """Decrement weather suppression timers by 1 each turn."""
        if not hasattr(self, '_weather_suppressed') or not self._weather_suppressed:
            return
        expired = []
        for pos in list(self._weather_suppressed):
            self._weather_suppressed[pos] -= 1
            if self._weather_suppressed[pos] <= 0:
                expired.append(pos)
        for pos in expired:
            del self._weather_suppressed[pos]

    def _restore_winded(self):
        """Restore ATK for creatures that were temporarily winded this turn."""
        for a in self.actors:
            if getattr(a, "_was_winded", False):
                a.atk = getattr(a, "_prewind_atk", a.atk)
                a._was_winded = False

    def _apply_onhit(self, victim, dmg: int, part: str = "torso"):
        """On-hit effects: heavy blows inflict status conditions.
        Mapped to body parts: head->stagger, torso->winded/bleed, legs->slowed."""
        from random import Random
        rng = Random(f"{self.seed}:{self.turn}:{victim.x}:{victim.y}")
        if part == "head" and dmg >= 6 and rng.random() < 0.30:
            v = getattr(victim, "_staggered", 0)
            victim._staggered = v + 1
            self.log(f"The blow to {victim.name}'s head leaves it reeling!")
        elif part == "torso":
            if dmg >= 5 and rng.random() < 0.15:
                v = getattr(victim, "_winded", 0)
                victim._winded = v + 1
                self.log(f"{victim.name} is winded by the hit to its chest.")
            if dmg >= 4 and rng.random() < 0.20:
                v = getattr(victim, "_bleeding", 0)
                victim._bleeding = v + 1
                self.log(f"{victim.name} bleeds from its torso.")
        elif part == "legs" and dmg >= 4 and rng.random() < 0.25:
            v = getattr(victim, "_slowed", 0)
            victim._slowed = v + 2
            if not getattr(victim, "_base_speed", 0):
                victim._base_speed = getattr(victim, "speed", 1.0)
            victim.speed = getattr(victim, "_base_speed", 1.0) * 0.5
            self.log(f"{victim.name} is slowed — its legs are battered.")

    def attack(self, att, dfn):
        from random import Random
        from .body_parts import hit_part, damage_part, init_body
        self.emit("noise", pos=(dfn.x, dfn.y), volume=8)
        self._add_pulse(dfn.x, dfn.y)
        if att.is_player:
            dfn._provoked = True
            self._add_stain(dfn.x, dfn.y, "·", f"blood of {dfn.name}")
        if att.is_player or dfn.is_player:
            foe = att if dfn.is_player else dfn
            if foe.flavor and foe.source not in self._flavored:
                self._flavored.add(foe.source)
                self.log(foe.flavor)
        dmg = max(1, att.atk - dfn.defense)
        # aspect combat effects
        if att.is_player and self._aspect:
            if "Fever Heat" in self._aspect:
                dmg += 1
            if "Static Touch" in self._aspect:
                el = self.system("reactions")
                if el is not None:
                    props = el.props_at(dfn.x, dfn.y) if hasattr(el, "props_at") else set()
                    if "wet" in props or "frozen" in props:
                        dmg += 1
            if "Cold Endurance" in self._aspect:
                dmg = max(1, dmg - 1)
        if att.is_player:
            know = self.system("knowledge")
            fac = getattr(dfn, "faction", "")
            if know is not None and fac:
                ab, db = know.faction_insight(self, fac)
                dmg = max(1, dmg + ab)
                # faction standing perk: kin_calm reduces incoming damage by 1
                fs = self.system("factions")
                if fs is not None and fs.faction_perk(fac, "kin_calm"):
                    dmg = max(1, dmg + 1)
        elif dfn.is_player:
            know = self.system("knowledge")
            fac = getattr(att, "faction", "")
            if know is not None and fac:
                ab, db = know.faction_insight(self, fac)
                dmg = max(1, dmg - db)
                fs = self.system("factions")
                if fs is not None and fs.faction_perk(fac, "kin_calm"):
                    dmg = max(1, dmg - 1)
        # body-part hit location
        init_body(dfn)
        rng = Random(f"{self.seed}:{self.turn}:{att.x}:{att.y}:{dfn.x}:{dfn.y}")
        elite = getattr(att, "quality", 0) > 0 and dfn.is_player
        part = hit_part(dfn, rng, elite_aim=elite)
        damage_part(dfn, part, dmg)
        if att.is_player and getattr(self.player, '_static_discharge', False):
            adj_enemies = [e for e in self.actors if e is not dfn and e.hp > 0
                           and self.hostile(self.player, e)
                           and max(abs(e.x - dfn.x), abs(e.y - dfn.y)) <= 1]
            if adj_enemies:
                import random as _rng
                chain = adj_enemies[hash(f"{self.seed}:{self.turn}:static") % len(adj_enemies)]
                chain.hp -= 1
                self.log(f"Static arcs from {dfn.name} to {chain.name}.")
                if chain.hp <= 0 and getattr(chain, 'is_boss', False) and chain.source == self.final_boss_source:
                    self.won = True
                    self.kill(chain, "static discharge")
                    self.log("The deepest thought in the vault falls silent. You win.")
        pname = {"head": "head", "torso": "chest", "legs": "legs"}.get(part, part)
        if dmg >= 4 and dfn.is_player:
            self._apply_onhit(dfn, dmg, part)
        elif dmg >= 4 and att.is_player:
            self._apply_onhit(dfn, dmg, part)
        if dfn.hp > 0:
            if att.is_player:
                self.log(f"You strike {dfn.name}'s {pname} for {dmg} ({max(0, dfn.hp)} HP left).")
            elif dfn.is_player:
                self.log(f"{att.name} hits your {pname} for {dmg} ({max(0, dfn.hp)} HP left).")
            return
        if dfn.is_player:
            self.alive = False
            self._save_death(cause=getattr(att, "name", "a foe"))
            where = (f"in {self.region_name}" if self.sandbox
                     else f"on floor {self.floor}")
            self.log(f"{att.name} strikes you down. You die {where}.")
            return
        # a non-player actor died
        if dfn.is_boss and dfn.source == self.final_boss_source:
            self.won = True
            self.log("The deepest thought in the vault falls silent. You win.")
        # friend_died trigger
        from .sense import apply_trigger as _trig
        if dfn.allegiance == "monster":
            for a in self.actors:
                if a is not dfn and a.allegiance == "monster" and getattr(a, "faction", "") == getattr(dfn, "faction", ""):
                    if max(abs(a.x - dfn.x), abs(a.y - dfn.y)) <= 8:
                        _trig(self, a, "friend_died", 0.6)
        if att.is_player and dfn.allegiance == "monster":
            self.kills += 1
            self._tension = max(0, self._tension - 20)  # action calms the wild
            # Kill-confidence: each kill grants +1 max HP (caps at +5), decays on rest
            if not hasattr(self.player, '_kill_confidence'):
                self.player._kill_confidence = 0
            self.player._kill_confidence = min(5, self.player._kill_confidence + 1)
            self.player.max_hp = max(1, self.player.max_hp + 1)
            self.player.hp = min(self.player.max_hp, self.player.hp + 1)
            self.log(f"You destroy {dfn.name}{' [BOSS]' if dfn.is_boss else ''}.")
            if self.kills == 1:
                sigs = self.system("sigils")
                if sigs is None or not sigs.slots:
                    self.log("You feel something wanting — sigils wait to be found in the rooms ahead.")
            for s in self.systems:
                s.on_enemy_killed(self, dfn)
            self.emit("enemy_killed", enemy=dfn, cause="melee")
            # Craft wire: kill→heal condition trigger
            try:
                from runtime.craft import CraftSystem
                CraftSystem.apply_wires(self, "enemy_killed")
            except Exception:
                pass
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
        # on-hit effects: staggered creatures lose their turn
        if getattr(a, "_staggered", 0) > 0:
            a._staggered -= 1
            return
        winded = getattr(a, "_winded", 0) > 0
        if winded:
            a._winded -= 1
            if not getattr(a, "_was_winded", False):
                a._prewind_atk = a.atk
                a._was_winded = True
            a.atk = max(1, a.atk - 1)
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
        if getattr(a, 'allegiance', '') == 'companion':
            max_hp = getattr(a, 'max_hp', a.hp)
            if a.hp * 100 < max_hp * 25:
                st = getattr(self.level, 'stairs', None)
                if st:
                    from runtime.sense import step_toward
                    dx, dy = step_toward(self, a, st[0], st[1], safe=True)
                    self._npc_step(a, dx, dy)
                    return
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
            if getattr(a, 'allegiance', '') == 'companion':
                structures = self.system("structures")
                if structures and hasattr(structures, 'trigger_trap'):
                    structures.trigger_trap(self, a.x, a.y)

    # ---- rendering ----
    def _add_pulse(self, x: int, y: int):
        """A visible sound ring: concentric circles of ~ fading over turns."""
        self._pulses.append([x, y, 3, "·"])

    def _add_stain(self, x: int, y: int, glyph: str, text: str):
        """A memory stain: tile permanently marked with an event glyph."""
        if self.level and self.level.walkable(x, y):
            self._stains[(x, y)] = (glyph, text)

    def _tick_pulses(self):
        """Decay pulse rings each turn."""
        for p in list(self._pulses):
            p[2] -= 1
            if p[2] <= 0:
                self._pulses.remove(p)

    def _tick_tension(self):
        """Complacency rises on idle, decays on action. High tension = camp risk."""
        rate = 3 if self._resting else 1
        self._tension += rate
        # decay on kills: handled in attack() — subtract 20 per kill
        if self._tension >= 200 and self.sandbox and self._on_surface():
            from random import Random
            rng = Random(f"{self.seed}:tension:{self.turn}")
            if rng.random() < 0.30:
                from .entities import make_enemy
                pool = self.m.get("enemies", [])
                if pool:
                    spec = rng.choice(pool)
                    fcs = self.system("factions")
                    if fcs:
                        for _ in range(10):
                            fid = self._region_faction.get(spec.get("regionId", ""), "")
                            standing = fcs.standing.get(fid, 0)
                            if standing >= 3:
                                spec = rng.choice(pool)
                                continue
                            break
                    free = [(x, y) for y in range(4, self.level.h - 4)
                            for x in range(4, self.level.w - 4)
                            if self.level.walkable(x, y) and self.actor_at(x, y) is None
                            and max(abs(x - self.player.x), abs(y - self.player.y)) > 8]
                    if free:
                        fx, fy = rng.choice(free)
                        e = make_enemy(spec, fx, fy)
                        e.faction = self._region_faction.get(spec.get("regionId", ""), "")
                        self.actors.append(e)
                        self.log("Something stirs in the wild, drawn by your lingering.", ambient=True)

    def _tick_aspect(self):
        """Track time spent in current region. 50+ turns grants the region's aspect."""
        if not self.sandbox or not self._on_surface():
            return
        r = self.region_for(self.floor)
        self._aspect_turns += 1
        if self._aspect_turns >= 50 and not self._aspect:
            el = r.get("element", "")
            asp = {"charged": "Static Touch: +1 ATK vs wet/frozen foes",
                   "wet": "Water Affinity: +2 speed on water tiles",
                   "flammable": "Fever Heat: melee deals +1 fire dmg",
                   "frozen": "Cold Endurance: -1 dmg taken, speed ×0.8",
                   "sacred": "Hallowed: camp heals 2× faster",
                   "corrosive": "Acid Blood: on 5+ dmg taken, splash 2 to attacker"}.get(el, "")
            if asp:
                self._aspect = asp
                self.log(f"The region's nature settles upon you: {asp}.")
                if el == "frozen":
                    self.player.speed = 0.8
                elif el == "sacred":
                    pass  # heal modifier checked in wait()

    def _animate_graves(self):
        """Ghost encounters: gravestone glyphs have chance to animate as combat echoes."""
        from random import Random
        rng = Random(f"{self.seed}:ghosts:{self.turn}")
        for pos, text in list(self._graves.items()):
            if self.actor_at(*pos) is not None:
                continue
            if not self.level.walkable(*pos):
                continue
            deaths = text.count("slain by") + 1
            if rng.random() < 0.08 * deaths:  # more deaths = higher chance
                from .entities import Actor
                echo = Actor(x=pos[0], y=pos[1], glyph="†", name=f"Echo of the Fallen",
                            hp=8 + deaths * 4, max_hp=8 + deaths * 4, atk=2 + deaths,
                            source="ghost", allegiance="monster")
                echo._special_actions = list(rng.sample(
                    ["enrage", "shield", "spit", "blink"], min(2, deaths)))
                echo.quality = min(deaths, 4)
                echo.flavor = text[:80]
                self.actors.append(echo)
                self.log(f"† A grave marker shudders — {echo.name} rises!", ambient=True)

    def compose_frame(self):
        """The composited, viewport-sliced glyph grid plus the viewport origin."""
        grid = [row[:] for row in self.level.tiles]
        # void shaft: tiles that overlook the level below render its floor (dim)
        if self.current_z < 0:
            below = self._levels.get(self.current_z + 1)
            # the deepest level shows a well at center
            shaft_center = (self.level.w // 2, self.level.h // 2) if (
                not self._dungeon and self.current_z < 0 and
                self._levels and min(k for k in self._levels if k < 0) == self.current_z) else None
        else:
            below = None
            shaft_center = None
        for (x, y), gph in self._overlay.items():
            if grid[y][x] == ".":
                grid[y][x] = gph
        # void shaft: a 3x3 well through which you glimpse the level below
        if below is not None and shaft_center is not None:
            cx, cy = shaft_center
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    sx, sy = cx + dx, cy + dy
                    if 0 <= sy < len(grid) and 0 <= sx < len(grid[sy]):
                        if grid[sy][sx] in (".", "#"):
                            if below.walkable(sx, sy):
                                grid[sy][sx] = "@" if dx == 0 and dy == 0 else "·"
        # memory stains: permanent event markers on tiles
        for (x, y), (gph, _) in self._stains.items():
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]) and grid[y][x] in (".", "#"):
                grid[y][x] = gph
        # gravestone glyphs: cross-run death markers
        for (x, y), _ in self._graves.items():
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]) and grid[y][x] in (".",):
                grid[y][x] = "†"
        # pulse waves: fading sound rings
        for (px, py, ttl, gph) in self._pulses:
            for d in (3, 6, 9):
                for dx in (-d, d):
                    for dy in range(-d, d + 1):
                        sx, sy = px + dx, py + dy
                        if 0 <= sy < len(grid) and 0 <= sx < len(grid[0]) and grid[sy][sx] in (".", "░"):
                            grid[sy][sx] = "~" if ttl >= 2 else "·"
                for dy in (-d, d):
                    for dx in range(-d + 1, d):
                        sx, sy = px + dx, py + dy
                        if 0 <= sy < len(grid) and 0 <= sx < len(grid[0]) and grid[sy][sx] in (".", "░"):
                            grid[sy][sx] = "~" if ttl >= 2 else "·"
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
        ztag = f" z={self.current_z}" if self.current_z != 0 else ""
        if self._dungeon is not None:
            where = f"Depths of {self.region_name}{ztag}"
        elif self.sandbox:
            where = f"{self.region_name}{ztag}"
        else:
            where = f"Floor {self.floor}/{self.max_floor}"
        hud = (f"{where}  HP {max(0, p.hp)}/{p.max_hp}  "
               f"ATK {p.atk}  DEF {p.defense}"
               + ("" if self.sandbox else f"  | {self.region_name}"))
        extras = "  ·  ".join(e for e in (s.status_line(self) for s in self.systems) if e)
        tail = ("\n" + extras) if extras else ""
        return f"{body}\n{hud}{tail}\n" + "\n".join(self.messages[-last_n:])

    def compose_overworld(self, width: int, height: int):
        """Downsample the entire surface into a terminal-scale grid.
        Each cell represents a block of world tiles, colored by dominant region.
        Returns (grid, meta) where meta maps cell positions to region names."""
        tiles = self.level.tiles
        w, h = self.level.w, self.level.h
        bw = max(1, (w + width - 1) // width)
        bh = max(1, (h + height - 1) // height)
        grid = [[" " for _ in range(width)] for _ in range(height)]
        meta: dict[tuple[int, int], str] = {}
        region_of = getattr(self, "_region_of", {})
        frictions = getattr(self, "_frictions", {})
        tint = getattr(self, "_tint", {})
        landmarks = getattr(self, "_landmarks", {})
        know = self.system("knowledge")
        mapped_regions = know.region_known_for if know else (lambda rid: True)

        for cy in range(height):
            for cx in range(width):
                x0, y0 = cx * bw, cy * bh
                x1, y1 = min(x0 + bw, w), min(y0 + bh, h)
                counts: dict[str, int] = {}
                roads, walls, voids = 0, 0, 0
                for wy in range(y0, y1):
                    for wx in range(x0, x1):
                        ch = tiles[wy][wx] if 0 <= wy < h and 0 <= wx < w else "#"
                        if ch == "░":
                            roads += 1
                        elif ch == "#":
                            walls += 1
                        rid = region_of.get((wx, wy), "")
                        if rid:
                            counts[rid] = counts.get(rid, 0) + 1
                total = max(1, (x1 - x0) * (y1 - y0))
                if walls > total * 0.6:
                    grid[cy][cx] = "#"
                elif roads > total * 0.2 and roads >= walls:
                    grid[cy][cx] = "░"
                    rid = max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""
                elif counts:
                    rid, _cnt = max(counts.items(), key=lambda kv: kv[1])
                    grid[cy][cx] = "·"
                    if rid:
                        r = self._region_by_id(rid)
                        if r:
                            meta[(cx, cy)] = r.get("name", rid)
                        if know and not mapped_regions(rid):
                            grid[cy][cx] = "?"
                else:
                    grid[cy][cx] = " "

        # overlay landmarks at scaled positions
        for (lx, ly), kind in landmarks.items():
            ocx, ocy = lx // bw, ly // bh
            if 0 <= ocx < width and 0 <= ocy < height:
                glyph = {"heart": "◆", "town": ">", "wild": "*"}.get(kind, "*")
                if grid[ocy][ocx] not in ("·", "?", " "):
                    grid[ocy][ocx] = glyph

        # player marker
        px, py = self.player.x, self.player.y
        pcx, pcy = px // bw, py // bh
        if 0 <= pcx < width and 0 <= pcy < height:
            grid[pcy][pcx] = "@"

        return grid, meta

    def _region_by_id(self, target):
        for r in self.m.get("regions", []):
            if r.get("id") == target:
                return r
        return None


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
