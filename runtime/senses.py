"""A tactical senses layer — perception, not omniscience.

Two layers, per your design:

1. **Detection / exploration.** Locating senses (SOUND, SMELL) give a *position* with no
   identity. A creature that only hears/smells something doesn't know what it is — it
   *investigates* (the engine walks it toward the percept to gain line-of-sight).
2. **Identification / adequate reaction.** Identifying senses (SIGHT+line-of-sight, TOUCH
   when adjacent, or the supernatural LIFE/MIND/MAGIC) confirm *what* a stimulus is. Only an
   identified **hostile actor** becomes a target; fire is perceived as a hazard and avoided,
   never attacked — because it is never a hostile actor.

Creatures perceive by *capacity*: each has a `SenseProfile`. A blind echolocator can't
identify by sight and must close to touch; a life-wraith senses the living through walls; a
mind-seer feels thought but is blind to mindless constructs.

**Opt-in.** Perception is active only when a `SenseField` system is registered (the live
game adds it). With no `SenseField`, `nearest_hostile` stays omniscient — so every existing
test and showcase is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import sense as _S
from .systems import System

# sense modalities
SIGHT, SOUND, SMELL, TOUCH, LIFE, MIND, MAGIC = \
    "sight", "sound", "smell", "touch", "life", "mind", "magic"

_IDENTIFYING = {SIGHT, TOUCH, LIFE, MIND, MAGIC}   # convey *what* it is
_LOCATING = {SOUND, SMELL}                          # convey only *where*

_MACHINE = {"g", "c"}      # golem, construct — not alive, no scent of life
_SPECTRAL = {"h", "e", "j", "u", "k"}   # shade, echo, revenant, wisp, gloom — unliving/magical


# --------------------------------------------------------------------------- #
# What a creature emits (drives the supernatural senses)
# --------------------------------------------------------------------------- #

def is_alive(a) -> bool:
    g = getattr(a, "glyph", "")
    return g not in _MACHINE and g not in _SPECTRAL


def is_minded(a) -> bool:
    if getattr(a, "is_player", False) or getattr(a, "is_boss", False):
        return True
    if getattr(a, "allegiance", "") == "wild":
        return "predator" in (getattr(a, "source", "") or "")
    return getattr(a, "tier", 1) >= 4


def is_magical(a, game=None) -> bool:
    if getattr(a, "glyph", "") in _SPECTRAL:
        return True
    if getattr(a, "is_player", False) and game is not None:
        s = game.system("sigils")
        return bool(s is not None and getattr(s, "slots", None))
    return False


def _emits(a, modality, game):
    if modality == LIFE:
        return is_alive(a)
    if modality == MIND:
        return is_minded(a)
    if modality == MAGIC:
        return is_magical(a, game)
    return True  # SIGHT/TOUCH: any body


# --------------------------------------------------------------------------- #
# Sense profiles (capacity) — registry + policy
# --------------------------------------------------------------------------- #

@dataclass
class SenseProfile:
    ranges: dict   # modality -> range (tiles)

    def has(self, m):
        return m in self.ranges

    def rng(self, m):
        return self.ranges.get(m, 0)


PROFILES: dict = {
    # the default: eyes + ears + a little nose, touch when adjacent
    "sighted": SenseProfile({SIGHT: 8, TOUCH: 1, SOUND: 12, SMELL: 5}),
    "player": SenseProfile({SIGHT: 9, TOUCH: 1, SOUND: 14, SMELL: 6}),
}


def register_profile(name, profile):
    PROFILES[name] = profile


def profile_name_for(actor) -> str:
    """Policy: which sense profile an entity *wants* (resolved against the registry; the
    richer archetypes are registered by creatures.py — until then everything falls back to
    'sighted')."""
    if getattr(actor, "is_player", False):
        return "player"
    if getattr(actor, "allegiance", "") == "wild":
        return "scent_hound"
    g = getattr(actor, "glyph", "")
    return {
        "h": "life_wraith",   # shade — senses the living through walls
        "e": "echolocator",   # echo — blind, hears all
        "b": "scent_hound",   # beast — follows its nose
        "s": "mind_seer",     # scribe — feels thought
        # expanded bestiary: each new kind perceives the world its own way
        "j": "life_wraith",   # revenant — a risen thing, feels the living
        "u": "life_wraith",   # wisp — spectral, senses life
        "k": "echolocator",   # gloom — blind, hears in the dark
        "f": "scent_hound",   # hound — a nose, unbound
        "d": "scent_hound",   # drifter — feral wanderer
        "q": "mind_seer",     # seraph — feels thought from on high
        "m": "echolocator",   # chorus — a swarm-voice, hears all
        "v": "echolocator",   # myriad — the many, hears all
    }.get(g, "sighted")


def profile(actor) -> SenseProfile:
    name = profile_name_for(actor)
    return PROFILES.get(name) or PROFILES["sighted"]


# --------------------------------------------------------------------------- #
# Line of sight (walls block)
# --------------------------------------------------------------------------- #

def has_los(game, x0, y0, x1, y1) -> bool:
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    while (x, y) != (x1, y1):
        if (x, y) != (x0, y0) and not game.level.walkable(x, y):
            return False
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return True


def _cheb(ax, ay, bx, by):
    return max(abs(ax - bx), abs(ay - by))


# --------------------------------------------------------------------------- #
# Perception
# --------------------------------------------------------------------------- #

@dataclass
class Perception:
    identified: list = field(default_factory=list)   # actors recognized this turn
    leads: list = field(default_factory=list)        # (x, y, salience) — investigate these
    hazards: list = field(default_factory=list)      # (x, y) seen fire/acid

    def hostiles(self, game, observer):
        hostile = getattr(game, "hostile", None) or (
            lambda a, b: game._hostile(a.allegiance, b.allegiance))
        return [t for t in self.identified if hostile(observer, t)]

    def nearest_hostile(self, game, observer):
        best, bd = None, 10 ** 9
        for t in self.hostiles(game, observer):
            d = _cheb(observer.x, observer.y, t.x, t.y)
            if d < bd:
                best, bd = t, d
        return best, (bd if best else None)

    def best_lead(self, observer):
        best, bs = None, -1.0
        for (x, y, sal) in self.leads:
            # prefer salient + near
            score = sal - 0.1 * _cheb(observer.x, observer.y, x, y)
            if score > bs:
                best, bs = (x, y), score
        return best


def perceive(game, observer) -> Perception:
    """Compute (and cache per turn) what `observer` perceives, by its sense profile."""
    turn = getattr(game, "turn", 0)
    cached = getattr(observer, "_perc", None)
    if cached is not None and cached[0] == turn:
        return cached[1]

    prof = profile(observer)
    sf = game.system("senses")
    p = Perception()
    seen = getattr(observer, "_last_seen", None)
    if seen is None:
        seen = observer._last_seen = {}

    candidates = [game.player] + [a for a in game.actors if a is not observer]
    for t in candidates:
        if getattr(t, "hp", 1) <= 0:
            continue
        d = _cheb(observer.x, observer.y, t.x, t.y)
        ident = False
        if prof.has(TOUCH) and d <= 1:
            ident = True
        elif prof.has(SIGHT) and d <= prof.rng(SIGHT) and has_los(game, observer.x, observer.y, t.x, t.y):
            ident = True
        elif prof.has(LIFE) and d <= prof.rng(LIFE) and _emits(t, LIFE, game):
            ident = True
        elif prof.has(MIND) and d <= prof.rng(MIND) and _emits(t, MIND, game):
            ident = True
        elif prof.has(MAGIC) and d <= prof.rng(MAGIC) and _emits(t, MAGIC, game):
            ident = True
        if ident:
            p.identified.append(t)
            seen[id(t)] = ((t.x, t.y), turn)

    # locating senses -> unidentified leads
    if sf is not None and prof.has(SOUND):
        for (x, y, vol, _ttl) in sf.sounds:
            if _cheb(observer.x, observer.y, x, y) <= prof.rng(SOUND) + vol:
                p.leads.append((x, y, float(vol)))
    if sf is not None and prof.has(SMELL):
        lead = sf.strongest_scent(observer, prof.rng(SMELL))
        if lead is not None:
            p.leads.append((lead[0], lead[1], lead[2] * 0.5))

    # memory: a hostile seen before but not seen now is still worth investigating
    ident_ids = {id(t) for t in p.identified}
    for tid, (pos, when) in list(seen.items()):
        age = turn - when
        if age > 14:
            del seen[tid]
        elif tid not in ident_ids:
            p.leads.append((pos[0], pos[1], 2.0 / (age + 1)))

    # seen hazards (so a sighted creature knows the fire it must route around)
    if prof.has(SIGHT):
        r = game.system("reactions")
        if r is not None:
            try:
                for (hx, hy) in r.hazard_tiles(game):
                    if _cheb(observer.x, observer.y, hx, hy) <= prof.rng(SIGHT) \
                            and has_los(game, observer.x, observer.y, hx, hy):
                        p.hazards.append((hx, hy))
            except Exception:
                pass

    observer._perc = (turn, p)
    return p


def nearest_perceived_hostile(game, observer):
    return perceive(game, observer).nearest_hostile(game, observer)


def scent_step(game, observer):
    """One step along the player's diffused trail, for a nose standing on it.

    This is `runtime/scent.py`'s consumer, and it had none. `ScentSystem` diffuses the
    player's trail through walkable space, decays it, blocks it on walls and exposes both
    `scent_at` and `strongest_neighbour`; the two things that called any of it were
    `behavior.py`, a utility-oracle module imported by nothing but two tests, and the
    `scent_mask` consumable. So the grid was computed every turn of every run and read by
    nobody. `system_activity.py` has the shape of it: busy and mute, acting on 11.1% of its
    classic calls while emitting and logging nothing, which is why dropping it left all 24
    ablation arms unchanged.

    The signal was never the problem. Measured over one classic seeker run: 23,770
    investigation steps, of which the observer stood on a live scent tile in 12,022 and had a
    followable trail adjacent in 12,163. Half of every creature's investigating happened on
    top of a path it could not smell.

    The division of labour with `SenseField.scent` is deliberate and they are not duplicates.
    `SenseField` lays a mark per actor and answers "something passed near here", which is
    DETECTION and already feeds `p.leads` above. `ScentSystem` answers "and it went that
    way", which is a GRADIENT. Straight-lining at a detection walks into the wall between you
    and it; following a gradient rounds the corner the prey rounded.

    Gated on standing ON the trail, not on being near one, which keeps it narrow: a creature
    that has merely caught a whiff still uses the ordinary lead machinery.
    """
    prof = profile(observer)
    if not prof.has(SMELL):
        return None
    ss = game.system("scent")
    if ss is None:
        return None
    from runtime.scent import SCENT_TRACK_MIN
    if ss.scent_at(observer.x, observer.y) <= 0:
        return None          # not on a trail; a whiff is the lead system's business
    return ss.gradient_step(game, observer.x, observer.y, SCENT_TRACK_MIN)


def investigate_step(game, observer):
    """Exploratory layer: with no identified target, walk toward the most salient percept
    (a heard noise, a scent, a remembered sighting). Returns a step or (0,0)."""
    p = perceive(game, observer)
    if p.hostiles(game, observer):
        return (0, 0)   # has a real target; the brain handles it
    # A trail underfoot beats a remembered position, and only for a nose. It is the fresher
    # and more precise signal: the prey was HERE, and the gradient says which way it left.
    step = scent_step(game, observer)
    if step is not None:
        return step
    lead = p.best_lead(observer)
    if lead is None:
        return (0, 0)
    if (observer.x, observer.y) == lead:
        return (0, 0)   # arrived; nothing here — drop interest next turn as memory ages
    return _S.step_toward(game, observer, lead[0], lead[1], safe=True)


# --------------------------------------------------------------------------- #
# The SenseField system — gathers transient stimuli (sound) and the scent map
# --------------------------------------------------------------------------- #

class SenseField(System):
    name = "senses"

    def __init__(self):
        self.sounds: list = []           # (x, y, volume, ttl)
        self.scent: dict = {}            # (x, y) -> [intensity, owner_id]
        self._last_player = None

    def on_world_start(self, game):
        self.sounds, self.scent = [], {}

    def on_floor_enter(self, game):
        self.sounds, self.scent = [], {}
        self._last_player = (game.player.x, game.player.y)

    def on_event(self, game, etype, data):
        # deaths, detonations, traps already flow through the bus as loud moments
        if etype in ("noise", "enemy_killed", "actor_died"):
            pos = data.get("pos")
            if pos is None:
                a = data.get("enemy") or data.get("actor")
                pos = (a.x, a.y) if a is not None else None
            if pos is not None:
                vol = data.get("volume", 6)
                self.sounds.append((pos[0], pos[1], vol, 2))

    def on_player_act(self, game):
        # decay sounds
        self.sounds = [(x, y, v, t - 1) for (x, y, v, t) in self.sounds if t - 1 > 0]
        # lay down scent for every actor; decay the field
        for a in [game.player] + list(game.actors):
            cur = self.scent.get((a.x, a.y))
            base = 12 if getattr(a, "is_player", False) else 9
            if cur is None or cur[0] < base:
                self.scent[(a.x, a.y)] = [base, id(a)]
        for k in list(self.scent.keys()):
            self.scent[k][0] -= 1
            if self.scent[k][0] <= 0:
                del self.scent[k]

    def strongest_scent(self, observer, rng):
        """The strongest *foreign* scent within range — a lead toward where prey passed."""
        best, bi = None, 0
        for (x, y), (inten, owner) in self.scent.items():
            if owner == id(observer):
                continue
            if _cheb(observer.x, observer.y, x, y) <= rng and inten > bi:
                best, bi = (x, y, inten), inten
        return best
