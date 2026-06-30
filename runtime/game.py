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


class Game:
    def __init__(self, manifest: dict, width: int = MAP_W, height: int = MAP_H,
                 upheaval=None, systems=None):
        self.m = manifest
        self.up = upheaval or Upheaval.empty()
        self.systems = systems or []
        self.announced: set = set()
        self.seed = manifest["seed"]
        self.width, self.height = width, height
        self.floor = 0
        self.max_floor = max((b["depth"] for b in manifest["bosses"]), default=1)
        self.final_boss_source = max(manifest["bosses"], key=lambda b: b["depth"])["sourceNoteId"]
        self.enemies_by_region: dict = {}
        for e in manifest["enemies"]:
            self.enemies_by_region.setdefault(e["regionId"], []).append(e)
        self.messages: list = []
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
        self._build_zones()
        for s in self.systems:
            s.on_world_start(self)
        if self.up.total:
            self.messages.append(
                f"~ The world has shifted since you last descended: {self.up.total} upheaval(s). ~")
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
        for depth, r in self._zones:
            if floor <= depth:
                return r
        if self._zones:
            return self._zones[-1][1]
        return self.m["regions"][0]

    def log(self, msg: str):
        self.messages.append(msg)

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
            en = make_enemy(spec, *free.pop())
            src = spec["sourceNoteId"]
            if src in self.up.ascended:        # your note grew -> the monster grew
                empower(en)
            elif src in self.up.waned:
                diminish(en)
            self.actors.append(en)

        for b in self.m["bosses"]:
            if b["depth"] == self.floor and free:
                boss = make_boss(b, *free.pop())
                if b["sourceNoteId"] == self.up.throne:
                    boss.name = "Ascendant " + boss.name
                    self.log(f"♛ {boss.name} has newly claimed the throne.")
                self.actors.append(boss)
                self.log(f"!! {boss.name} — {b.get('title', '')} — guards this depth.")

        # Vanilla stat-loot only exists in the bare game. With the systems layer on,
        # the sigil economy (configuration, not creep) replaces it entirely.
        if not self.systems:
            bonus = 1 if anchor in self.up.risen_regions else 0
            for _ in range(rng.randint(1, 2) + bonus):
                if not free or not self.m["items"]:
                    break
                self.items.append(make_item(rng.choice(self.m["items"]), *free.pop()))

        # lost notes haunt the floors they used to seed
        for note in self.up.lost_floor.get(self.floor, []):
            if not free:
                break
            self.actors.append(make_echo(note, *free.pop()))
            self.log(f"† The ruins of '{_title(note)}' stir here.")

        self.log(f"-- Floor {self.floor}: {self.region_name} --")
        for s in self.systems:
            s.on_floor_enter(self)

    # ---- actions ----
    def actor_at(self, x: int, y: int):
        for a in self.actors:
            if a.x == x and a.y == y:
                return a
        return None

    def on_stairs(self) -> bool:
        return (self.player.x, self.player.y) == self.level.stairs

    def try_move(self, dx: int, dy: int):
        if not self.alive or self.won:
            return
        self.turn += 1
        nx, ny = self.player.x + dx, self.player.y + dy
        target = self.actor_at(nx, ny)
        if target is not None:
            if getattr(target, "allegiance", "") == "npc":
                self.emit("interact", target=target, pos=(nx, ny))   # parley, don't attack
            else:
                self.attack(self.player, target)
        elif self.level.walkable(nx, ny):
            self.player.x, self.player.y = nx, ny
            self._pickup()
            self.emit("noise", pos=(nx, ny), volume=3)   # footsteps carry
        self.enemies_act()
        for s in self.systems:
            s.on_player_act(self)

    def _pickup(self):
        for it in list(self.items):
            if it.x == self.player.x and it.y == self.player.y:
                self.log(apply_item(self.player, it))
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
        if a == b:
            return False
        if "npc" in (a, b):
            return False                       # NPCs are neutral — you parley, not fight
        return {a, b} != {"wild", "player"}   # wildlife and the player ignore each other

    def attack(self, att, dfn):
        self.emit("noise", pos=(dfn.x, dfn.y), volume=8)   # combat is loud
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
            self.log(f"{att.name} strikes you down. You die on floor {self.floor}.")
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
        or a move."""
        if not self.alive:
            return
        for a in list(self.actors):
            if a not in self.actors:
                continue
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
                if not self.alive:
                    return

    def _npc_step(self, a, dx, dy):
        tx, ty = a.x + dx, a.y + dy
        if (tx, ty) == (self.player.x, self.player.y):
            if self._hostile(a.allegiance, "player"):
                self.attack(a, self.player)
            return
        t = self.actor_at(tx, ty)
        if t is not None:
            if self._hostile(a.allegiance, t.allegiance):
                self.attack(a, t)
            return
        if self.level.walkable(tx, ty):
            a.x, a.y = tx, ty

    # ---- rendering ----
    def render(self, last_n: int = 6) -> str:
        grid = [row[:] for row in self.level.tiles]
        for it in self.items:
            grid[it.y][it.x] = it.glyph
        for a in self.actors:
            grid[a.y][a.x] = a.glyph
        grid[self.player.y][self.player.x] = "@"
        for s in self.systems:
            s.render_overlay(self, grid)
        body = "\n".join("".join(r) for r in grid)
        p = self.player
        hud = (f"Floor {self.floor}/{self.max_floor}  HP {max(0, p.hp)}/{p.max_hp}  "
               f"ATK {p.atk}  DEF {p.defense}  | {self.region_name}")
        extras = "  ·  ".join(e for e in (s.status_line(self) for s in self.systems) if e)
        tail = ("\n" + extras) if extras else ""
        return f"{body}\n{hud}{tail}\n" + "\n".join(self.messages[-last_n:])


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
