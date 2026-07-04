"""Fauna — an autonomous wildlife ecology, indifferent to the player.

Wild critters live by drives, not by hostility to the hero. Three kinds share the
floor:

  * grazer    (glyph ``n``, low atk) — wanders to the nearest plant and eats it;
               a fed grazer may breed (population capped).
  * scavenger (glyph ``z``)          — wanders to the nearest corpse and eats it.
  * predator  (glyph ``Y``, high atk)— hunts grazers (intra-wild predation the
               core loop won't do, since both are ``wild``); predator-vs-monster
               is already handled for free by the allegiance-aware turn loop.

All critters are built with ``make_critter`` (allegiance ``"wild"``) and appended
to ``game.actors`` so the core renders/animates them as real actors. They never
path to or attack the player.

Cross-talk is bus/query-only and fully None-guarded — flora (``flora_at`` /
``consume``) and decay (``corpse_at`` / ``consume``) may both be absent and the
world must still run. Critters this system owns are tagged ``source="fauna:<kind>"``.

Determinism: a per-floor rng seeded ``random.Random(f"{seed}:{floor}:fauna")``.
"""
from __future__ import annotations

import random

from runtime.systems import System
from runtime.entities import make_critter
from runtime.dungeon import free_floor_tiles

# glyphs (real actors, drawn by the core — no overlay)
KIND_GLYPH = {"grazer": "n", "scavenger": "z", "predator": "Y"}
# (hp, atk, defense) — small numbers; power is interaction, not stats
KIND_STATS = {
    "grazer": (6, 1, 0),
    "scavenger": (5, 1, 0),
    "predator": (9, 3, 0),
}

_SENSE_RADIUS = 12     # how far a critter can "smell" a resource tile
_GRAZER_CAP = 6        # bound on living grazers per floor (incl. breeding)
_BREED_CHANCE = 0.5    # a fed grazer breeds with this probability, under the cap


def _call(sys, meth, *args):
    """None-guarded partner call: returns None if the system or method is absent."""
    if sys is None:
        return None
    fn = getattr(sys, meth, None)
    if not callable(fn):
        return None
    return fn(*args)


class FaunaSystem(System):
    name = "fauna"

    def __init__(self):
        self.rng = random.Random(0)   # replaced per floor for determinism

    # ---- identity -------------------------------------------------------
    def _mine(self, a) -> bool:
        return (getattr(a, "allegiance", None) == "wild"
                and isinstance(getattr(a, "source", ""), str)
                and a.source.startswith("fauna:"))

    @staticmethod
    def _kind(a) -> str:
        return a.source.split(":", 1)[1]

    def _count(self, game, kind=None) -> int:
        return sum(1 for a in game.actors
                   if a.alive and self._mine(a)
                   and (kind is None or self._kind(a) == kind))

    # ---- lifecycle ------------------------------------------------------
    def on_floor_enter(self, game):
        self.rng = random.Random(f"{game.seed}:{game.floor}:fauna")
        rng = self.rng
        exclude = {(game.player.x, game.player.y), game.level.stairs}
        for a in game.actors:                 # don't stack on freshly-spawned enemies
            exclude.add((a.x, a.y))
        free = free_floor_tiles(game.level, exclude)
        rng.shuffle(free)

        shallow = game.floor <= 2
        # herds scale with the land: a grown overworld is ~90k open tiles, and a
        # flat 4-7 critters left it a still-life. One herd unit per ~1500 open
        # tiles keeps classic small floors unchanged while filling the wide between.
        self._scale = max(1, len(free) // 1500)
        counts = {
            "grazer": (rng.randint(1, 2) if shallow else rng.randint(2, 3)) * self._scale,
            "scavenger": (1 if shallow else rng.randint(1, 2)) * self._scale,
            "predator": (1 if shallow else rng.randint(1, 2)) * self._scale,
        }
        for kind, n in counts.items():
            for _ in range(n):
                if not free:
                    return
                x, y = free.pop()
                self._spawn(game, kind, x, y)

    def _spawn(self, game, kind, x, y):
        glyph = KIND_GLYPH[kind]
        hp, atk, dfn = KIND_STATS[kind]
        a = make_critter(kind, glyph, x, y, hp, atk, defense=dfn,
                         source="fauna:" + kind)
        game.actors.append(a)
        return a

    # ---- per-turn drives ------------------------------------------------
    # only critters this close to the player run their (scan-heavy) drives; the far
    # herd drifts cheaply instead. What you can't see needs ambience, not fidelity.
    _ACTIVE_RADIUS = 40

    def on_player_act(self, game):
        flora = game.system("flora")
        decay = game.system("decay")
        px, py = game.player.x, game.player.y
        for a in list(game.actors):
            # skip dead / removed (e.g. eaten by a predator mid-iteration)
            if a not in game.actors or not a.alive or not self._mine(a):
                continue
            if getattr(a, "_acted_turn", None) == game.turn:
                continue   # its brain already moved it (fled / fought) this turn
            if max(abs(a.x - px), abs(a.y - py)) > self._ACTIVE_RADIUS:
                self._idle(game, a)     # far herd: drift, don't scan
                continue
            kind = self._kind(a)
            if kind == "grazer":
                acted = self._drive_grazer(game, a, flora)
            elif kind == "scavenger":
                acted = self._drive_scavenger(game, a, decay)
            else:
                acted = self._drive_predator(game, a)
            if not acted:
                # nothing to eat, hunt, or scavenge in range: a living thing still
                # moves. Idle wandering is what makes a watched field breathe.
                self._idle(game, a)

    def _idle(self, game, a):
        if self.rng.random() >= 0.45:
            return
        dx, dy = self.rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1),
                                  (1, 1), (-1, 1), (1, -1), (-1, -1)))
        tx, ty = a.x + dx, a.y + dy
        if (game.level.walkable(tx, ty) and game.actor_at(tx, ty) is None
                and (tx, ty) != (game.player.x, game.player.y)):
            a.x, a.y = tx, ty

    def _drive_grazer(self, game, a, flora) -> bool:
        best, dist = self._nearest_tile(
            game, a, lambda x, y: bool(_call(flora, "flora_at", x, y)))
        if best is None:
            return False
        if dist <= 1:                                   # adjacent or standing on it
            if _call(flora, "consume", best[0], best[1]):
                self._maybe_breed(game, a)
        else:
            self._step_toward(game, a, best[0], best[1])
        return True

    def _drive_scavenger(self, game, a, decay) -> bool:
        best, dist = self._nearest_tile(
            game, a, lambda x, y: bool(_call(decay, "corpse_at", x, y)))
        if best is None:
            return False
        if dist <= 1:
            _call(decay, "consume", best[0], best[1])
        else:
            self._step_toward(game, a, best[0], best[1])
        return True

    def _drive_predator(self, game, a) -> bool:
        prey, dist = None, 999
        for o in game.actors:
            if o is a or not o.alive or not self._mine(o):
                continue
            if self._kind(o) != "grazer":
                continue
            d = max(abs(a.x - o.x), abs(a.y - o.y))
            if d < dist:
                prey, dist = o, d
        if prey is None or dist > _SENSE_RADIUS:
            return False
        if dist <= 1:
            game.attack(a, prey)        # intra-wild predation -> game.kill -> corpse
        else:
            self._step_toward(game, a, prey.x, prey.y)
        return True

    # ---- helpers --------------------------------------------------------
    def _maybe_breed(self, game, parent):
        if self._count(game, "grazer") >= _GRAZER_CAP * getattr(self, "_scale", 1):
            return
        if self.rng.random() >= _BREED_CHANCE:
            return
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (-1, -1), (1, -1), (-1, 1)):
            nx, ny = parent.x + dx, parent.y + dy
            if (game.level.walkable(nx, ny) and not game.actor_at(nx, ny)
                    and (nx, ny) != (game.player.x, game.player.y)):
                self._spawn(game, "grazer", nx, ny)
                return

    def _nearest_tile(self, game, a, pred, radius=_SENSE_RADIUS):
        """Nearest walkable tile (within `radius`) satisfying `pred(x, y)`."""
        lvl = game.level
        best, bd = None, 999
        y0, y1 = max(0, a.y - radius), min(lvl.h, a.y + radius + 1)
        x0, x1 = max(0, a.x - radius), min(lvl.w, a.x + radius + 1)
        for y in range(y0, y1):
            for x in range(x0, x1):
                if not lvl.walkable(x, y) or not pred(x, y):
                    continue
                d = max(abs(a.x - x), abs(a.y - y))
                if d < bd:
                    best, bd = (x, y), d
        return best, bd

    def _step_toward(self, game, a, tx, ty):
        """Greedy single step toward (tx,ty), avoiding walls, actors and the player."""
        sx = (tx > a.x) - (tx < a.x)
        sy = (ty > a.y) - (ty < a.y)
        opts = []
        if sx and sy:
            opts.append((a.x + sx, a.y + sy))
        if sx:
            opts.append((a.x + sx, a.y))
        if sy:
            opts.append((a.x, a.y + sy))
        for nx, ny in opts:
            if (nx, ny) == (a.x, a.y):
                continue
            if not game.level.walkable(nx, ny):
                continue
            if game.actor_at(nx, ny) is not None:
                continue
            if (nx, ny) == (game.player.x, game.player.y):
                continue
            a.x, a.y = nx, ny
            return True
        return False

    # ---- HUD ------------------------------------------------------------
    def status_line(self, game):
        n = self._count(game)
        return "Wild: %d" % n if n else None
