"""Reactive structures — pressure-plate traps and volatile crystal clusters.

This is part of the autonomous *ecology* layer: structures are inert objects that
pursue no one's interest. A pressure plate fires under the weight of *whatever*
steps on it — the player, a faction monster, or a wild critter alike — and a
crystal cluster grows on charged ground until fire or a live shock makes it burst.
They are indifferent to allegiance; the player and the factions can exploit them
or get caught in them, but the structures themselves take no side.

Self-contained ``System`` subclass: it reads game state, mutates the world only
through the public Game API (``game.kill``, ``game.log``) and the reactions
write/query API (``ignite`` / ``add_prop`` / ``props_at`` / ``is_hazard``), and
draws through ``render_overlay``. Every cross-system call is None-guarded, so the
floor still runs when the reactions system is absent.

Determinism: all placement randomness comes from
``random.Random(f"{game.seed}:{game.floor}:structures")``, created once per floor.

Glyphs (overlay, floor cells only): ``&`` crystal cluster, ``_`` armed trap.
A sprung trap reverts to plain floor (it is removed from ``self.traps``).
"""
from __future__ import annotations

import random

from runtime.systems import System
from runtime.dungeon import free_floor_tiles

# orthogonal neighbours + self — the blast / gas footprint (edge-to-edge, plus origin)
_PLUS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))

# Modest, lossy numbers — pressure and positioning, never instant-death spam.
SPIKE_DMG = 4      # a spike plate's bite
DET_DMG = 3        # crystal detonation splash (3x3 around the burst)
DET_FIRE_LIFE = 3  # short-lived flames seeded by a detonation

# Floor + the reactions element overlays a physical structure may legitimately sit
# atop. We draw over these but NEVER over an actor / item / '@' / '>' glyph.
_OVERDRAW = set(".~,+")   # never draw over a live hazard glyph (fire ^, acid :, charged /)


class StructureSystem(System):
    name = "structures"

    def __init__(self):
        self.traps: dict = {}       # (x, y) -> kind ("spike" | "gas"), armed plates
        self.crystals: dict = {}    # (x, y) -> growth (int), volatile clusters
        self.rng = None

    # ---- helpers ---------------------------------------------------------
    def _is_floor(self, game, pos) -> bool:
        x, y = pos
        lvl = game.level
        return 0 <= x < lvl.w and 0 <= y < lvl.h and lvl.tiles[y][x] == "."

    def _charged(self, reactions, pos) -> bool:
        if reactions is None:
            return False
        return "charged" in reactions.props_at(*pos)

    # ---- seeding ---------------------------------------------------------
    def on_floor_enter(self, game):
        self.rng = random.Random(f"{game.seed}:{game.floor}:structures")
        self.traps = {}
        self.crystals = {}

        exclude = {(game.player.x, game.player.y), game.level.stairs}
        free = free_floor_tiles(game.level, exclude)
        if not free:
            return
        self.rng.shuffle(free)
        reactions = game.system("reactions")   # may be None — guarded everywhere

        # --- a few armed pressure plates (spike or gas) ---
        n_traps = min(len(free), self.rng.randint(2, 4))
        for _ in range(n_traps):
            pos = free.pop()
            self.traps[pos] = self.rng.choice(("spike", "gas"))

        # --- a few crystal clusters, preferring already-charged ground ---
        n_cryst = min(len(free), self.rng.randint(2, 3))
        if n_cryst:
            charged = [p for p in free if self._charged(reactions, p)]
            charged_set = set(charged)
            others = [p for p in free if p not in charged_set]
            for pos in (charged + others)[:n_cryst]:    # charged-first, then fill
                self.crystals[pos] = 0

    # ---- per-turn processing --------------------------------------------
    def on_player_act(self, game):
        if self.rng is None:
            return
        reactions = game.system("reactions")
        self._trigger_traps(game, reactions)
        self._update_crystals(game, reactions)

    def _occupants(self, game):
        """Every actor that can stand on a tile this turn — the player plus all
        enemies and wild critters. Allegiance is irrelevant: structures react to
        anyone. Returns a snapshot list (safe to kill while iterating)."""
        out = []
        if getattr(game, "alive", True) and game.player is not None:
            out.append(game.player)
        out.extend(list(game.actors))
        return out

    def _trigger_traps(self, game, reactions):
        if not self.traps:
            return
        for a in self._occupants(game):
            if a is None:
                continue
            pos = (a.x, a.y)
            kind = self.traps.get(pos)
            if kind is None:
                continue
            del self.traps[pos]                 # the plate is spent -> reverts to floor
            game.log("A pressure plate clicks —")
            if kind == "spike":
                a.hp -= SPIKE_DMG
                if a.is_player:
                    if a.hp <= 0:
                        game.alive = False
                        game.log(f"Spikes run you through. You die on floor {game.floor}.")
                    else:
                        game.log("Spikes stab up at you!")
                else:
                    if a.hp <= 0:
                        game.kill(a, "trap")    # universal death -> actor_died on the bus
                    else:
                        game.log(f"Spikes stab {a.name}!")
            else:  # gas: a caustic burst that lingers on the plate and its neighbours
                game.log("Caustic gas hisses out.")
                if reactions is not None:
                    for dx, dy in _PLUS:
                        nb = (pos[0] + dx, pos[1] + dy)
                        if self._is_floor(game, nb):
                            reactions.add_prop(nb[0], nb[1], "acid")

    def _update_crystals(self, game, reactions):
        if not self.crystals:
            return
        detonate = []
        for pos, growth in list(self.crystals.items()):
            props = reactions.props_at(*pos) if reactions is not None else set()
            # A live charged/shock tile is a *charged* tile the reactions layer rates
            # as an active hazard (i.e. part of a charged+wet chain-shock). A lone
            # charged tile only feeds growth; fire or a live shock makes it burst.
            live_shock = ("charged" in props and reactions is not None
                          and reactions.is_hazard(*pos))
            if "fire" in props or live_shock:
                detonate.append(pos)
            elif "charged" in props:
                self.crystals[pos] = growth + 1     # grows over time on charged ground
        for pos in detonate:
            self._detonate(game, reactions, pos)

    def _detonate(self, game, reactions, pos):
        self.crystals.pop(pos, None)
        game.log("A crystal detonates!")
        game.emit("broke", kind="crystal", source="", name="crystal", tier=2, pos=pos)
        x, y = pos
        # seed a short-lived blast: fire + charge across a small radius (floor only)
        if reactions is not None:
            for dx, dy in _PLUS:
                nx, ny = x + dx, y + dy
                if self._is_floor(game, (nx, ny)):
                    reactions.ignite(nx, ny, life=DET_FIRE_LIFE)
                    reactions.add_prop(nx, ny, "charged")
        # splash damage to anyone in the 3x3 (small, allegiance-blind)
        for a in self._occupants(game):
            if a is None:
                continue
            if max(abs(a.x - x), abs(a.y - y)) <= 1:
                a.hp -= DET_DMG
                if a.is_player:
                    if a.hp <= 0:
                        game.alive = False
                        game.log(f"The blast tears through you. You die on floor {game.floor}.")
                elif a.hp <= 0:
                    game.kill(a, "crystal")

    # ---- rendering / HUD -------------------------------------------------
    def render_overlay(self, game, grid):
        h = len(grid)
        tiles = game.level.tiles
        for glyph, cells in (("&", self.crystals), ("_", self.traps)):
            for (x, y) in cells:
                if not (0 <= y < h and 0 <= x < len(grid[y])):
                    continue
                # only ever sit on a floor tile, and never clobber an actor/item/@/>
                if tiles[y][x] == "." and grid[y][x] in _OVERDRAW:
                    grid[y][x] = glyph

    def status_line(self, game):
        if not self.traps and not self.crystals:
            return None
        return f"Traps: {len(self.traps)} · Crystals: {len(self.crystals)}"

    # ---- query API (auto-agent / other systems call via game.system) -----
    def hazard_tiles(self, game) -> list:
        """Armed pressure-plate positions — tiles an autonomous agent should avoid
        stepping on. (Crystals are not listed: they are only dangerous once a fire
        or shock reaches them, which the reactions hazard map already surfaces.)"""
        return list(self.traps.keys())

    def on_interact(self, game) -> bool:
        pos = (game.player.x, game.player.y)
        if pos in self.crystals:
            self._detonate(game, game.system("reactions"), pos)
            game.log("You strike the crystal — it erupts! Your blow yields to the burst.")
            game.player.hp = min(game.player.hp, game.player.hp + 1)  # half-damage mitigation
            return True
        if pos in self.traps:
            del self.traps[pos]
            game.log("You disarm the trap — it clacks harmlessly into the floor.")
            return True
        return False
