"""Reactive matter — Caves of Qud-style environmental physics/chemistry.

A region's ``element`` seeds the floor with reactive tile properties; those
properties then interact each turn (fire spreads and burns out, charged + wet
becomes a live chain-shock, acid corrodes, ice quenches flame, sacred ground
mends). You fight the *environment* as much as the monster: every effect is a
small bit of positioning pressure, never power creep.

Self-contained ``System`` subclass — reads game state, mutates only through the
public Game API (``game.player.hp``, ``game.actors``, ``game.log``), and draws
through ``render_overlay``. It never edits game.py or another system.

Determinism: all randomness comes from ``random.Random(f"{seed}:{floor}:reactions")``,
created once per floor so the burn pattern is reproducible.
"""
from __future__ import annotations

import random

from runtime.systems import System
from runtime.dungeon import free_floor_tiles

# orthogonal neighbours (chemistry only reacts edge-to-edge, never diagonally)
_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))

# region element -> the tile property it seeds (None = nothing to scatter)
_ELEMENT_PROP = {
    "charged": "charged",
    "wet": "wet",
    "flammable": "fire",
    "frozen": "ice",
    "sacred": "sacred",
    "corrosive": "acid",
    "inert": None,
}

# --- elemental affinity (cross-system: enemies vs. their home region's element) ---
# Opposing region elements. An enemy is immune (0x) to its own element and takes 2x
# from its opposite. Pairs (element space): charged<->wet, flammable<->frozen,
# corrosive<->sacred  -- i.e. tile charged<->wet, fire<->ice, acid<->sacred.
_ELEMENT_OPPOSITE = {
    "charged": "wet", "wet": "charged",
    "flammable": "frozen", "frozen": "flammable",
    "corrosive": "sacred", "sacred": "corrosive",
}

# on-map glyphs (within the reactions glyph budget)
_GLYPH = {
    "fire": "^",
    "wet": "~",
    "charged": "/",
    "acid": ":",
    "ice": ",",
    "sacred": "+",
}
# render priority: the most active/dangerous prop wins a shared cell
_RENDER_ORDER = ("fire", "acid", "charged", "wet", "ice", "sacred")

_PLAYER_CAP = 2        # max environmental damage to the player per turn
# Fire is SUBCRITICAL: each flame spawns fewer than one successor over its life
# (0.06 * 4 neighbours * 3 turns ~= 0.7 < 1), so a fire is a brief flare that
# spreads a tile or two and burns out — never the runaway wildfire that ate the
# whole map (the old 0.20*4*5 ~= 4 successors was supercritical, exponential).
_FIRE_SEED_LIFE = 4    # turns a seeded fire burns before dying out
_FIRE_SPREAD_LIFE = 3  # turns a freshly spread flame burns (shorter, so cascades damp)
_FIRE_SPREAD_P = 0.06  # per-neighbour chance fire jumps to an adjacent floor tile


class ReactionSystem(System):
    name = "reactions"

    def __init__(self):
        self.props: dict = {}          # (x, y) -> set[str] of active properties
        self.fire_life: dict = {}      # (x, y) -> remaining burn turns
        self.rng = None
        self.last_player_env_damage = 0
        self._faction_element = None   # faction_id -> region element (built once)

    # ---- substrate write API (lets the ecology systems shape the terrain) ----
    def ignite(self, x, y, life=_FIRE_SEED_LIFE):
        """Set a tile alight — used by burning flora, weather embers, crystal blasts."""
        self.props.setdefault((x, y), set()).add("fire")
        self.fire_life[(x, y)] = max(self.fire_life.get((x, y), 0), life)

    def add_prop(self, x, y, prop):
        """Add a reactive property to a tile (e.g. weather spreading wet/charged)."""
        self.props.setdefault((x, y), set()).add(prop)

    def clear_prop(self, x, y, prop):
        s = self.props.get((x, y))
        if s:
            s.discard(prop)
            if prop == "fire":
                self.fire_life.pop((x, y), None)

    # ---- elemental affinity ----
    def _build_affinity_map(self, game):
        """Build faction_id -> region element once from the static manifest.

        Combined with a graph node's ``community`` this resolves an enemy's home
        element: ``faction_{community}`` is exactly a region's ``factionId``.
        """
        fe = {}
        for r in (game.m.get("regions") or []):
            fid = r.get("factionId")
            if fid:
                fe[fid] = r.get("element")
        self._faction_element = fe

    def _ensure_affinity(self, game):
        if self._faction_element is None:
            self._build_affinity_map(game)

    def _enemy_home_element(self, game, enemy):
        """enemy.source -> graph node community -> faction_{community} -> element.

        None-guarded at every hop (orphan notes, missing nodes, etc. -> None,
        which the affinity check treats as neutral 1x).
        """
        self._ensure_affinity(game)
        src = getattr(enemy, "source", None)
        if not src:
            return None
        nodes = (game.m.get("graph") or {}).get("nodes") or {}
        node = nodes.get(src)
        if not node:
            return None
        comm = node.get("community")
        if comm is None:
            return None
        return self._faction_element.get(f"faction_{comm}")

    def _affinity(self, home_element, tile_element) -> int:
        """Damage multiplier for a hazard's *tile_element* against an enemy's
        *home_element*: 0x if it matches the enemy's own element, 2x if it is the
        opposite, else 1x. Unknown elements degrade to neutral 1x."""
        if not home_element or not tile_element:
            return 1
        if home_element == tile_element:
            return 0
        if _ELEMENT_OPPOSITE.get(home_element) == tile_element:
            return 2
        return 1

    # ---- helpers ----
    def _is_floor(self, game, pos) -> bool:
        x, y = pos
        lvl = game.level
        return 0 <= x < lvl.w and 0 <= y < lvl.h and lvl.tiles[y][x] == "."

    def _add(self, pos, prop):
        self.props.setdefault(pos, set()).add(prop)

    def _tiles_with(self, prop) -> set:
        return {pos for pos, s in self.props.items() if prop in s}

    # ---- seeding ----
    def on_world_start(self, game):
        self._build_affinity_map(game)

    def on_floor_enter(self, game):
        self.props = {}
        self.fire_life = {}
        self.last_player_env_damage = 0
        self.rng = random.Random(f"{game.seed}:{game.floor}:reactions")
        self._ensure_affinity(game)

        region = game.region_for(game.floor)
        element = region.get("element", "inert")
        prop = _ELEMENT_PROP.get(element)
        if prop is None:                       # inert / unknown -> a still floor
            return

        exclude = {(game.player.x, game.player.y), game.level.stairs}
        free = free_floor_tiles(game.level, exclude)
        if not free:
            return

        area = game.level.w * game.level.h
        n_patches = max(1, area // 55)

        if prop == "fire":
            # a FEW small fires scattered in the wild, not a wall of flame: capped low
            # and absolute, so a large map doesn't get hundreds of ignition points
            # (each would spread; hundreds of subcritical fires still add up).
            n_seed = min(4, max(1, n_patches // 40))
            for pos in self.rng.sample(free, min(n_seed, len(free))):
                self._add(pos, "fire")
                self.fire_life[pos] = _FIRE_SEED_LIFE
        else:
            for pos in self.rng.sample(free, min(n_patches, len(free))):
                self._add(pos, prop)

    # ---- per-turn processing ----
    def on_player_act(self, game):
        if self.rng is None or not getattr(game, "alive", True) or getattr(game, "won", False):
            self.last_player_env_damage = 0
            return

        fire_tiles = self._tiles_with("fire")
        acid_tiles = self._tiles_with("acid")
        ice_tiles = self._tiles_with("ice")
        sacred_tiles = self._tiles_with("sacred")
        live = self._chain_shock_tiles()       # charged+wet groups that are live now

        # 1) resolve damage / healing on every actor standing on a reactive tile
        scorched_player = False
        chained_any = False

        # --- player (capped, never pushed below 0 by the environment alone) ---
        ppos = (game.player.x, game.player.y)
        p_dmg = 0
        if ppos in fire_tiles:
            p_dmg += self.rng.randint(1, 2)
            scorched_player = True
        if ppos in live:
            p_dmg += self.rng.randint(1, 2)
            chained_any = True
        if ppos in acid_tiles:
            p_dmg += 1
        eff = game.system("effects")
        if eff is not None and eff.can_drift(game):
            p_dmg = 0   # 'drift' effect: you go weightless over hazard, unharmed
        if p_dmg:
            applied = min(p_dmg, _PLAYER_CAP, game.player.hp)
            game.player.hp -= applied
            self.last_player_env_damage = applied
            if scorched_player:
                game.log("You are scorched!")
        else:
            self.last_player_env_damage = 0
        if ppos in sacred_tiles:
            game.player.hp = min(game.player.max_hp, game.player.hp + 1)

        # --- enemies (lure them into the hazards; environment can kill them) ---
        for en in list(game.actors):
            epos = (en.x, en.y)
            props = self.props.get(epos, ())
            home = self._enemy_home_element(game, en)   # region element it is native to
            e_dmg = 0
            # Each hazard source is scaled by elemental affinity: 0x against the
            # enemy's own element, 2x against its opposite, 1x otherwise. We draw the
            # rng in the same order/count as before (even when the multiplier is 0)
            # so the seeded stream stays deterministic.
            if epos in fire_tiles:
                e_dmg += self._affinity(home, "flammable") * self.rng.randint(1, 2)
            if epos in live:
                chained_any = True
                # a live chain-shock bites via this tile's own conductor (charged|wet)
                shock_el = "charged" if "charged" in props else "wet"
                e_dmg += self._affinity(home, shock_el) * self.rng.randint(1, 2)
            if epos in acid_tiles:
                e_dmg += self._affinity(home, "corrosive") * 1
            if e_dmg > 0:
                en.hp -= e_dmg
                if en.hp <= 0:
                    # Environmental death is a *quiet* kill the faction never
                    # witnesses (cause="environment"). Route removal through game.kill
                    # so it also emits actor_died -> the decay/ecology layer.
                    game.emit("enemy_killed", enemy=en, cause="environment")
                    word = self.element_at(*epos) or self._element_word(game)
                    game.log(f"The {en.name} is undone by the {word}, unnoticed.")
                    game.kill(en, "environment")
                    continue
            if epos in sacred_tiles:
                en.hp = min(en.max_hp, en.hp + 1)

        if chained_any:
            game.log("Chain shock!")

        # 2) evolve fire: quench against ice, decay, then spread to dry floor
        self._evolve_fire(game, fire_tiles, ice_tiles)

    def _chain_shock_tiles(self) -> set:
        """Connected charged|wet components that contain BOTH are live this turn."""
        nodes = {pos for pos, s in self.props.items() if "charged" in s or "wet" in s}
        seen = set()
        live = set()
        for start in nodes:
            if start in seen:
                continue
            stack = [start]
            seen.add(start)
            comp = []
            while stack:
                cur = stack.pop()
                comp.append(cur)
                cx, cy = cur
                for dx, dy in _ORTH:
                    nb = (cx + dx, cy + dy)
                    if nb in nodes and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            has_charged = any("charged" in self.props[p] for p in comp)
            has_wet = any("wet" in self.props[p] for p in comp)
            if has_charged and has_wet:
                live.update(comp)
        return live

    def _evolve_fire(self, game, fire_tiles, ice_tiles):
        remove = set()
        spread = {}
        for pos in fire_tiles:
            x, y = pos
            # ice quenches any flame it touches
            if any((x + dx, y + dy) in ice_tiles for dx, dy in _ORTH):
                remove.add(pos)
                continue
            self.fire_life[pos] = self.fire_life.get(pos, 1) - 1
            if self.fire_life[pos] <= 0:
                remove.add(pos)
                continue
            for dx, dy in _ORTH:
                nb = (x + dx, y + dy)
                if nb in fire_tiles or nb in ice_tiles:
                    continue
                if self._is_floor(game, nb) and self.rng.random() < _FIRE_SPREAD_P:
                    spread[nb] = _FIRE_SPREAD_LIFE
        for pos in remove:
            if pos in self.props:
                self.props[pos].discard("fire")
                if not self.props[pos]:
                    del self.props[pos]
            self.fire_life.pop(pos, None)
        for pos, life in spread.items():
            self._add(pos, "fire")
            self.fire_life[pos] = max(self.fire_life.get(pos, 0), life)

    def _element_word(self, game) -> str:
        return game.region_for(game.floor).get("element", "elements")

    # ---- rendering / HUD ----
    def render_overlay(self, game, grid):
        h = len(grid)
        for (x, y), s in self.props.items():
            if not (0 <= y < h and 0 <= x < len(grid[y])):
                continue
            if grid[y][x] != ".":              # never overwrite actors/items/@/>
                continue
            for prop in _RENDER_ORDER:
                if prop in s:
                    grid[y][x] = _GLYPH[prop]
                    break

    # ---- query API (other systems call these via game.system("reactions")) ----
    def props_at(self, x, y) -> set:
        """The full set of reactive properties on a tile (a copy)."""
        return set(self.props.get((x, y), ()))

    def element_at(self, x, y):
        """The dominant reactive property at a tile (by render priority), or None."""
        s = self.props.get((x, y))
        if not s:
            return None
        for prop in _RENDER_ORDER:
            if prop in s:
                return prop
        return next(iter(s), None)

    def is_hazard(self, x, y) -> bool:
        """Would standing here damage an actor? Fire and acid always bite; a charged
        or wet tile only when it is part of a live chain-shock (charged adjacent to
        wet). Ice and sacred are not hazards (sacred heals)."""
        s = self.props.get((x, y))
        if not s:
            return False
        if "fire" in s or "acid" in s:
            return True
        if ("charged" in s or "wet" in s) and (x, y) in self._chain_shock_tiles():
            return True
        return False

    def status_line(self, game):
        return f"Ground: {game.region_for(game.floor).get('element', 'inert')}"
