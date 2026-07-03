"""Ambient weather — an autonomous elemental process indifferent to everyone.

The region's ``element`` sets a *mood* over the whole floor: a charged region
crackles with a **static storm**, a wet one suffers **rising damp**, flammable
ground sees **ember drift**, and so on. On a slow cadence the weather reaches
into the elemental substrate (the reactions system) and nudges a few random
tiles — a stray charged patch, a creeping damp, a lightning strike. It pursues
no one's interest: the player, monsters and wildlife are all equally exposed to
(or spared by) whatever the sky is doing.

Self-contained ``System`` subclass. It only ever *names* itself (``status_line``,
``current``) and *writes* to the terrain through the reactions write-API
(``ignite`` / ``add_prop`` / ``clear_prop``), every call None-guarded so the world
still runs when reactions is absent — the weather then just names itself and
leaves the (nonexistent) substrate alone. It owns no glyph: the props it sows are
drawn by reactions.

Determinism: all randomness comes from ``random.Random(f"{seed}:{floor}:weather")``,
created once per floor, so a floor's weather is reproducible. No wall-clock time.
"""
from __future__ import annotations

import random

from runtime.systems import System
from runtime.dungeon import free_floor_tiles

# orthogonal neighbours (damp creeps edge-to-edge, like the reactions chemistry)
_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))

# region element -> the weather word it expresses
_WEATHER = {
    "charged": "static storm",
    "wet": "rising damp",
    "flammable": "ember drift",
    "frozen": "cold snap",
    "sacred": "hallowed calm",
    "corrosive": "acrid haze",
    "inert": "still air",
}
_DEFAULT_WEATHER = "still air"

# which tile props each weather can introduce (documentation + lets a test attribute
# a substrate change to the weather without reaching into its internals)
WEATHER_PROPS = {
    "static storm": {"charged", "fire"},
    "rising damp": {"wet"},
    "ember drift": {"fire"},
    "cold snap": {"ice"},
    "acrid haze": {"acid"},
    "hallowed calm": set(),
    "still air": set(),
}

_CADENCE = 3            # the weather only stirs the substrate every Nth player action
_LIGHTNING_P = 0.5     # chance a static storm throws a bolt on a given cadence tick
_EMBER_LIFE = 4         # a drifting ember is a shorter-lived flame than a seeded one
_BOLT_LIFE = 3          # a lightning strike is a brief, hot flash


class WeatherSystem(System):
    name = "weather"

    def __init__(self):
        self.weather = _DEFAULT_WEATHER
        self.rng = None
        self._turn = 0

    # ---- floor lifecycle ----
    def on_floor_enter(self, game):
        element = game.region_for(game.floor).get("element", "inert")
        self.weather = _WEATHER.get(element, _DEFAULT_WEATHER)
        self.rng = random.Random(f"{game.seed}:{game.floor}:weather")
        self._turn = 0

    # ---- per-turn ambient process ----
    def on_player_act(self, game):
        if self.rng is None or not getattr(game, "alive", True) or getattr(game, "won", False):
            return
        self._turn += 1
        if self._turn % _CADENCE != 0:           # sparse: most turns the sky just sits there
            return

        r = game.system("reactions")
        if r is None:                            # no substrate to shape — weather is only a name
            return

        exclude = {(game.player.x, game.player.y), game.level.stairs}
        free = free_floor_tiles(game.level, exclude)
        if not free:
            return

        handler = {
            "static storm": self._static_storm,
            "rising damp": self._rising_damp,
            "ember drift": self._ember_drift,
            "cold snap": self._cold_snap,
            "acrid haze": self._acrid_haze,
        }.get(self.weather)
        if handler is not None:                  # hallowed calm / still air do nothing
            handler(game, r, free)

    # ---- weather handlers (each keeps its touch sparse: atmosphere, not a death sentence) ----
    def _static_storm(self, game, r, free):
        # a couple of fresh charged patches, and now and then a bolt that sets one alight
        for (x, y) in self._pick_fresh(r, free, "charged", 2):
            r.add_prop(x, y, "charged")
        if self.rng.random() < _LIGHTNING_P:
            x, y = self.rng.choice(free)
            r.ignite(x, y, _BOLT_LIFE)
            game.log("Lightning splits the dark.", ambient=True)

    def _rising_damp(self, game, r, free):
        # damp creeps out from whatever is already wet, plus one fresh seep so it keeps rising
        wet = [p for p in free if "wet" in r.props_at(*p)]
        if wet:
            sx, sy = self.rng.choice(wet)
            dry = [(sx + dx, sy + dy) for dx, dy in _ORTH
                   if self._is_floor(game, (sx + dx, sy + dy))
                   and "wet" not in r.props_at(sx + dx, sy + dy)]
            if dry:
                x, y = self.rng.choice(dry)
                r.add_prop(x, y, "wet")
        x, y = self.rng.choice(free)
        r.add_prop(x, y, "wet")

    def _ember_drift(self, game, r, free):
        # one stray ember drifts down onto dry floor (fire then spreads on its own in reactions)
        picks = self._pick_fresh(r, free, "fire", 1)
        if picks:
            x, y = picks[0]
            r.ignite(x, y, _EMBER_LIFE)

    def _cold_snap(self, game, r, free):
        # the cold snuffs any open flame it can reach, then leaves a little ice behind
        for (x, y) in free:
            if "fire" in r.props_at(x, y):
                r.clear_prop(x, y, "fire")
        for (x, y) in self._pick_fresh(r, free, "ice", 2):
            r.add_prop(x, y, "ice")

    def _acrid_haze(self, game, r, free):
        # a thin corrosive mist settles on a fresh tile
        for (x, y) in self._pick_fresh(r, free, "acid", 1):
            r.add_prop(x, y, "acid")

    # ---- helpers ----
    def _is_floor(self, game, pos) -> bool:
        x, y = pos
        lvl = game.level
        return 0 <= x < lvl.w and 0 <= y < lvl.h and lvl.tiles[y][x] == "."

    def _pick_fresh(self, r, free, prop, k):
        """Sample up to k floor tiles, preferring ones that don't already carry `prop`,
        so the weather keeps reaching new ground instead of re-marking the same cells."""
        fresh = [p for p in free if prop not in r.props_at(*p)]
        pool = fresh or free
        k = min(k, len(pool))
        if k <= 0:
            return []
        return self.rng.sample(pool, k)

    # ---- query API / HUD ----
    def current(self, game) -> str:
        """The active weather word (for the HUD and any onlooker).

        Always set: __init__ seeds _DEFAULT_WEATHER, on_floor_enter resets it."""
        return self.weather

    def status_line(self, game):
        return f"Weather: {self.current(game)}"
