"""The ambient narrator: the world acting near you, while you stand still.

`DESIGN_PLACE_PANEL.md` step 5, and its acceptance test is one sentence:

    every ambient line must point at a reachable thing or it's a lying screen.

So this system never describes mood, and never describes standing state. It diffs the
world each turn and speaks about what CHANGED, and it re-checks the thing still exists at
the moment it opens its mouth. A line that named a corpse already rotted away, or a fire
already out, is the cardinal place-breaker the spec names, and the structure here is
chosen so that it cannot happen: a percept holds a live `still_there` predicate, not a
remembered string.

Three design notes worth keeping, because each was measured rather than assumed.

**Deltas, not inventory.** Over 150 turns on the sample world the player has, within their
own sense ranges, about 24 elemental props within earshot and 16 within sight at any
moment. A narrator that reported what is there would babble every turn forever. The spec
says "fired only when a perceivable EVENT happens", and an event is a difference.

**The senses profile is the falloff.** The registered "player" profile is
SIGHT 9, SOUND 14, SMELL 6 (`senses.py`). That is already three bands, so this asks for no
new distance model. Identification needs line of sight, per `SENSES_SPEC.md`: sight names
the thing, sound and smell are LOCATING senses and give a bearing without an identity. A
struggle you can only hear is "a wet struggle to the east", never a creature's name.

**The map is not the competition.** `compose_frame` composites the whole level and `draw`
only dims beyond the knowledge radius rather than hiding, so the player can already see
WHAT is out there. Gating this on sense range is therefore not a contradiction with the
map: the map answers "what is there", the narrator answers "what just happened", which is
the located-in-time axis the design panel says is missing. Do not "fix" the gate to match
the map.

The budget matters more than it looks: the message pane is five lines, so one ambient line
is a fifth of everything the player can see. Hence the cooldown, and hence one line per
turn at the absolute most.
"""
from __future__ import annotations

from .det import droll
from .systems import System
from . import senses

# Turns that must pass between two ambient lines. Standing still is the verb that should
# let a place breathe (step 6b), so it listens harder: a shorter silence and a much better
# chance of hearing something when the silence is over.
_GAP_MOVING = 7
_GAP_STILL = 3
_CHANCE_MOVING = 40      # percent, rolled deterministically
_CHANCE_STILL = 85

# What a percept is worth when several land on the same turn. The spec never says what
# wins when weather, fauna and decay all have something to report, which is its single
# biggest omission for an implementer. Death outranks fire outranks weather outranks
# growth, and nearer outranks further within a kind.
_WEIGHT = {"struggle": 5.0, "corpse": 4.0, "fire": 3.0, "acid": 2.5,
           "charged": 2.0, "ice": 1.5, "sacred": 1.5}

# The elements worth a line when one appears on a tile that had none. Not every prop the
# reaction system knows: `wet` spreads constantly and is closer to terrain than to news.
# Each is a real, persistent, walkable-to tile, which is what the acceptance test needs.
_ELEMENTS = ("fire", "acid", "charged", "ice", "sacred")

# What each element looks, smells and sounds like. Sight names the element; sound and
# smell give a bearing and stay ignorant, per the identifying/locating split.
#
# Several phrasings per band, chosen deterministically from the tile, because one region's
# element dominates its whole floor: read by eye over three seeds, the first draft said
# "Something hisses" in eighteen of twenty-four distinct lines. A channel whose job is to
# make a place feel inhabited cannot say the same four words all run. The choice is keyed
# on position so the same event always reads the same way, and two different events in the
# same breath read differently.
_ELEMENT_VOICE = {
    "fire": (
        ("Fire takes hold", "Something is burning", "A flame stands up"),
        ("Smoke reaches you from", "You smell burning from", "Char on the air"),
        ("You hear something catch", "A dry crackle", "Something takes light"),
    ),
    "acid": (
        ("The stone pits and hisses", "Something eats into the floor", "The ground blisters"),
        ("A sour bite in the air", "Something sour reaches you", "A thin, bitter smell"),
        ("Something hisses", "A slow fizzing", "Stone gives with a hiss"),
    ),
    "charged": (
        ("The ground sparks", "Light crawls over the stone", "The floor throws a spark"),
        ("The air turns sharp", "A metal taste on the air", "The air goes thin and sharp"),
        ("A crack of static", "Something snaps, and is gone", "A dry snap"),
    ),
    "ice": (
        ("Frost creeps over the ground", "The floor goes white", "Ice takes the stone"),
        ("The air runs cold", "Cold reaches you", "The air bites"),
        ("Something cracks, brittle", "A thin creak of ice", "Something settles, hard"),
    ),
    "sacred": (
        ("The ground goes quiet and clean", "The stone comes clear", "Something settles, clean"),
        ("The air turns clean", "The air lightens", "Something clean on the air"),
        ("A held note", "A sound like held breath", "One quiet note"),
    ),
}

_DEAD_VOICE = {
    senses.SIGHT: ("Something lies dead", "A body, not moving", "Something is down"),
    senses.SMELL: ("You catch the smell of something dead",
                   "Something dead reaches you", "The smell of a kill"),
    senses.SOUND: ("Something falls still", "Something stops moving", "A last scuffle, then nothing"),
}

_STRUGGLE_SOUND = ("A wet struggle", "Something is being killed", "A short, wet commotion")

_BEARINGS = (
    ("east", 1, 0), ("south-east", 1, 1), ("south", 0, 1), ("south-west", -1, 1),
    ("west", -1, 0), ("north-west", -1, -1), ("north", 0, -1), ("north-east", 1, -1),
)


def bearing(dx: int, dy: int) -> str:
    """An eight-point compass word for an offset. Screen coordinates, so +y is south.

    Both vectors are normalised to unit LENGTH, not to their largest component. Using the
    largest component gives a diagonal the vector (1, 1), which ties with due south for
    an offset of (0, 5) and hands it to whichever candidate the table lists first. Due
    south then read as south-east: within 45 degrees, so walking still worked and the
    error hid, which is precisely why the compass gets its own test.
    """
    if dx == 0 and dy == 0:
        return "underfoot"
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    best, score = "east", -2.0
    for name, bx, by in _BEARINGS:
        blen = (bx * bx + by * by) ** 0.5
        dot = ux * (bx / blen) + uy * (by / blen)
        if dot > score:
            best, score = name, dot
    return best


class Percept:
    """One thing that just happened, somewhere real.

    `still_there` is a predicate over live game state, not a snapshot. It is what makes
    the no-lying-line rule structural instead of aspirational.
    """

    __slots__ = ("kind", "pos", "still_there", "actor")

    def __init__(self, kind, pos, still_there, actor=None):
        self.kind = kind
        self.pos = pos
        self.still_there = still_there
        self.actor = actor


class NarratorSystem(System):
    name = "narrator"

    def __init__(self):
        self._corpses: set = set()
        self._elements: dict = {e: set() for e in _ELEMENTS}
        self._last_line_turn = -99
        self._last_pos = None
        self._started = False
        # What the last line was about: (turn, line, kind, pos, sense). The point of the
        # whole system is that a line is a pointer, so the pointer is inspectable. The
        # acceptance test walks toward `pos` and expects to arrive.
        self.last = None

    # ---- lifecycle ---------------------------------------------------------------

    def on_world_start(self, game):
        # The player does not exist yet at this hook, so there is nothing to be near.
        # The first on_player_act takes the baseline instead.
        self._started = False

    def on_floor_enter(self, game):
        # A new floor is entirely new, so every tile on it would read as an event.
        # Resync silently: arrival is its own moment and the panel spends it on the
        # place name, not on a report of the local weather.
        self._resync(game)

    def _resync(self, game):
        decay = game.system("decay")
        react = game.system("reactions")
        self._corpses = set(getattr(decay, "corpses", {}) or ())
        props = getattr(react, "props", {}) or {}
        self._elements = {e: {p for p, k in props.items() if k and e in k}
                          for e in _ELEMENTS}
        player = getattr(game, "player", None)
        self._last_pos = (player.x, player.y) if player is not None else None
        self._started = player is not None

    # ---- the turn ----------------------------------------------------------------

    def on_player_act(self, game):
        if not self._started:
            self._resync(game)
            return
        if not getattr(game, "alive", True) or getattr(game, "won", False):
            return

        percepts = self._diff(game)
        here = (game.player.x, game.player.y)
        stood_still = here == self._last_pos
        self._last_pos = here

        if not percepts:
            return

        if not self._may_speak(game, stood_still):
            return

        spoken = self._speak(game, percepts)
        if spoken:
            line, percept, sense = spoken
            # rank 2: outranks the place-voice timer, which has no referent to walk to.
            game.log(line, ambient=True, ambient_rank=2)
            self._last_line_turn = game.turn
            self.last = (game.turn, line, percept.kind, percept.pos, sense)

    def _may_speak(self, game, stood_still: bool) -> bool:
        """Is the budget open this turn? Step 6b lives here.

        Standing still gets a shorter silence and a much better chance of breaking it,
        which is the whole of "in wait(), raise the narrator's fire chance". It is a
        separate method because the rate difference cannot be demonstrated by comparing
        two playthroughs: waiting also rests, heals and ticks tension, so no walking
        control holds everything else equal. The decision can be tested; the emergent
        rate cannot.
        """
        gap = _GAP_STILL if stood_still else _GAP_MOVING
        if game.turn - self._last_line_turn < gap:
            return False
        chance = _CHANCE_STILL if stood_still else _CHANCE_MOVING
        key = f"{getattr(game, 'run_seed', '')}:narrator:{game.floor}:{game.turn}"
        return droll(key, 100) < chance

    def _diff(self, game):
        """What changed since last turn, as percepts over live state."""
        decay = game.system("decay")
        react = game.system("reactions")

        corpses = getattr(decay, "corpses", None)
        props = getattr(react, "props", None)

        now_corpses = set(corpses or ())
        now_props = props if props is not None else {}
        now_elements = {e: {p for p, k in now_props.items() if k and e in k}
                        for e in _ELEMENTS}

        out = []

        for pos in sorted(now_corpses - self._corpses):
            # A kill the wild made, rather than one you made, reads differently and is
            # the panel's own worked example ("a wet struggle to the east").
            hunter = self._wild_beside(game, pos)
            kind = "struggle" if hunter is not None else "corpse"
            out.append(Percept(kind, pos,
                               lambda p=pos: corpses is not None and p in corpses,
                               actor=hunter))

        for elem in _ELEMENTS:
            for pos in sorted(now_elements[elem] - self._elements.get(elem, set())):
                out.append(Percept(elem, pos,
                                   lambda p=pos, e=elem: e in (now_props.get(p) or ())))

        # Flora is deliberately NOT a percept. It spreads one to three plants every single
        # turn, so reporting it is reporting inventory, not an event, and it drowned
        # everything else in the first measurement. The design panel names Weather, Fauna
        # and Decay as the budget holders, and flora reaches the log through them anyway:
        # when a plant burns, that is a fire.
        self._corpses = now_corpses
        self._elements = now_elements
        return out

    @staticmethod
    def _wild_beside(game, pos):
        for a in game.actors:
            if getattr(a, "allegiance", "") != "wild" or getattr(a, "hp", 0) <= 0:
                continue
            if max(abs(a.x - pos[0]), abs(a.y - pos[1])) <= 1:
                return a
        return None

    # ---- perception --------------------------------------------------------------

    @staticmethod
    def _sense_of(game, pos):
        """Which sense carries this, or None if it is out of reach entirely.

        Identification needs line of sight (SENSES_SPEC's identifying vs locating split).
        Without it, near things are smelled and far things are heard, and neither may name
        what it found.
        """
        prof = senses.PROFILES.get("player")
        if prof is None:
            return None
        px, py = game.player.x, game.player.y
        dist = max(abs(pos[0] - px), abs(pos[1] - py))
        if dist <= prof.rng(senses.SIGHT) and senses.has_los(game, px, py, pos[0], pos[1]):
            return senses.SIGHT
        if dist <= prof.rng(senses.SMELL):
            return senses.SMELL
        if dist <= prof.rng(senses.SOUND):
            return senses.SOUND
        return None

    def _speak(self, game, percepts):
        px, py = game.player.x, game.player.y
        best, best_score = None, -1.0
        for p in percepts:
            sense = self._sense_of(game, p.pos)
            if sense is None:
                continue
            dist = max(abs(p.pos[0] - px), abs(p.pos[1] - py))
            score = _WEIGHT.get(p.kind, 1.0) - dist * 0.05
            if score > best_score:
                best, best_score = (p, sense), score
        if best is None:
            return None

        percept, sense = best
        # The guard. Everything above worked from a diff taken earlier in the turn; this
        # asks the world, right now, whether the thing is still there to be walked to.
        if not percept.still_there():
            return None

        where = self._place_of(game, percept.pos)
        heading = bearing(percept.pos[0] - px, percept.pos[1] - py)
        # A thing on your own tile has no bearing, and "to the underfoot" is nonsense.
        toward = "underfoot" if heading == "underfoot" else f"to the {heading}"
        return _phrase(percept, sense, toward, where), percept, sense

    @staticmethod
    def _place_of(game, pos):
        """A note-derived proper noun for wherever the thing is, per the spec."""
        try:
            idx = game.room_at(pos[0], pos[1])
            if idx is not None:
                label = game.room_label(idx)
                if label:
                    return label
        except Exception:
            pass
        return getattr(game, "region_name", "") or "the dark"


def _phrase(percept, sense, toward, where) -> str:
    """One line. Sight may name what it is; sound and smell may not.

    That is not decoration. SENSES_SPEC makes SOUND and SMELL locating senses, which
    convey a position and no identity, and the panel asks for exactly that difference
    ("routed through sight/sound/smell so smell-only reads differently"). So the creature's
    name appears in exactly one branch below, the one that had line of sight to it.
    """
    kind = percept.kind
    name = getattr(percept.actor, "name", None)

    def pick(options):
        return options[droll(f"{percept.pos}:{kind}:{sense}", len(options))]

    if sense == senses.SIGHT:
        if kind == "struggle" and name:
            return f"{name} brings something down {toward}, in {where}."
        if kind in ("struggle", "corpse"):
            return f"{pick(_DEAD_VOICE[senses.SIGHT])} {toward}, in {where}."
        return f"{pick(_ELEMENT_VOICE[kind][0])} {toward}, in {where}."

    if sense == senses.SMELL:
        if kind in ("struggle", "corpse"):
            return f"{pick(_DEAD_VOICE[senses.SMELL])} {toward}, out of {where}."
        return f"{pick(_ELEMENT_VOICE[kind][1])} {toward}, out of {where}."

    # sound: a bearing, and nothing about what it was
    if kind == "struggle":
        return f"{pick(_STRUGGLE_SOUND)} {toward}, toward {where}."
    if kind == "corpse":
        return f"{pick(_DEAD_VOICE[senses.SOUND])} {toward}, toward {where}."
    return f"{pick(_ELEMENT_VOICE[kind][2])} {toward}, toward {where}."
