"""Per-entity memory — beliefs that persist, fade, and teach.

A creature is no longer a pure stimulus-response machine: it carries a `Memory` that
records what it has perceived and suffered, and acts on *beliefs* rather than only the
current instant.

- **Beliefs**: where a target was last perceived, with a confidence that decays each turn.
  A creature that loses sight of you heads for your last-known spot and searches nearby,
  then gives up once confidence runs out — it doesn't teleport-track you forever.
- **Learned aversion**: an element that has hurt it enough times becomes *feared* — it
  will route around that hazard even when desperate.
- **Grudge / alertness**: taking damage raises `alert`; it decays over time. An aroused
  creature searches harder and longer.

This layer is **non-invasive**: the `MemorySystem` *infers* everything from perception and
HP deltas each turn — no edits to combat, reactions, or the bus are needed. It is opt-in:
register `MemorySystem` to enable memory; without it, `mem(actor)` is simply never updated
and memory-aware brains degrade to their reactive behavior.
"""
from __future__ import annotations

from . import senses as _senses

_HORIZON = 18        # turns until a sighting's confidence fades to zero
_FEAR_THRESHOLD = 2  # times hurt by an element before a creature avoids it
_ALERT_DECAY = 0.85  # per-turn grudge/arousal cooldown
_ORTH = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))


class Belief:
    __slots__ = ("pos", "seen_turn")

    def __init__(self, pos, seen_turn):
        self.pos = pos
        self.seen_turn = seen_turn

    def confidence(self, turn):
        return max(0.0, 1.0 - (turn - self.seen_turn) / _HORIZON)


class Memory:
    def __init__(self):
        self.beliefs: dict = {}    # target key -> Belief (last-known position)
        self.feared: dict = {}     # element word -> times hurt by it
        self.alert: float = 0.0    # grudge / arousal in [0, 1]
        self.searched: set = set() # tiles already checked while chasing a stale belief

    def saw(self, key, pos, turn):
        self.beliefs[key] = Belief(pos, turn)
        self.alert = min(1.0, self.alert + 0.34)
        self.searched.clear()

    def hurt(self, element):
        if element:
            self.feared[element] = self.feared.get(element, 0) + 1
        self.alert = min(1.0, self.alert + 0.5)

    def fears(self, element) -> bool:
        return self.feared.get(element, 0) >= _FEAR_THRESHOLD

    def recall(self, turn):
        """Best (pos, confidence) belief still worth chasing, or None."""
        best, bc = None, 0.0
        for b in self.beliefs.values():
            c = b.confidence(turn)
            if c > bc:
                best, bc = b, c
        return (best.pos, bc) if best is not None else None

    def decay(self, turn):
        self.alert *= _ALERT_DECAY
        for k in [k for k, b in self.beliefs.items() if b.confidence(turn) <= 0.0]:
            del self.beliefs[k]


def mem(actor) -> Memory:
    """Lazily attach and return an actor's Memory."""
    m = getattr(actor, "_mem", None)
    if m is None:
        m = actor._mem = Memory()
    return m


# --------------------------------------------------------------------------- #
# Query helpers for brains (None-safe; harmless when MemorySystem isn't running)
# --------------------------------------------------------------------------- #

def recalled_spot(game, actor):
    """Where to search for a foe last perceived, or None (confidence exhausted)."""
    r = mem(actor).recall(getattr(game, "turn", 0))
    return r[0] if (r and r[1] > 0.0) else None


def alert_of(actor) -> float:
    return mem(actor).alert


def fears(actor, element) -> bool:
    return bool(element) and mem(actor).fears(element)


# --------------------------------------------------------------------------- #
# The MemorySystem — infers beliefs + harm + grudge each turn (no core edits)
# --------------------------------------------------------------------------- #

class MemorySystem:
    name = "memory"

    def __init__(self):
        self._hp: dict = {}   # id(actor) -> last seen hp, to detect damage

    def on_world_start(self, game):
        self._hp = {}

    def on_floor_enter(self, game):
        # memory is per-floor: a fresh layout, a fresh slate
        self._hp = {}
        for a in [game.player] + list(game.actors):
            if hasattr(a, "_mem"):
                a._mem = Memory()

    def on_player_act(self, game):
        turn = getattr(game, "turn", 0)
        reactions = game.system("reactions")
        for a in list(game.actors):
            if not getattr(a, "alive", False):
                continue
            # 1) belief update: anything this creature currently identifies is "seen here"
            try:
                p = _senses.perceive(game, a)
                for t in p.identified:
                    mem(a).saw(id(t), (t.x, t.y), turn)
            except Exception:
                pass
            # 2) harm inference: hp dropped this turn -> grudge; near a hazard -> learn fear
            prev = self._hp.get(id(a))
            if prev is not None and a.hp < prev:
                element = self._hazard_element(reactions, a)
                mem(a).hurt(element)
            self._hp[id(a)] = a.hp
        # age the player's tracker too, but the player has no memory-brain by default
        self._hp[id(game.player)] = game.player.hp
        for a in list(game.actors):
            if getattr(a, "alive", False):
                mem(a).decay(turn)

    @staticmethod
    def _hazard_element(reactions, a):
        if reactions is None:
            return None
        for dx, dy in _ORTH:
            x, y = a.x + dx, a.y + dy
            try:
                if reactions.is_hazard(x, y):
                    return reactions.element_at(x, y)
            except Exception:
                pass
        return None

    # full hook surface (no-ops)
    def on_enemy_killed(self, game, enemy):
        pass

    def on_event(self, game, etype, data):
        pass

    def render_overlay(self, game, grid):
        pass

    def status_line(self, game):
        return None

    def points_of_interest(self, game):
        return []

    def hazard_tiles(self, game):
        return []
