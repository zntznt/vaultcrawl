"""Renunciation Shrine — permanent sacrifices for lasting power.

Found in deep z-levels (rare). Interacting offers 3 choices from a pool.
Each is a permanent trade-off: lose something now for a lasting benefit.
Rejecting all 3 causes the shrine to crumble — no second chance at that shrine.

Deterministic: shrine placement and offerings are seeded.
"""
from __future__ import annotations

import os
import random

from runtime.systems import System

_OFFERINGS = [
    ("Renounce a Sigil Slot", "sigil", "Lose 1 max sigil capacity — gain +8 max HP"),
    ("Renounce a Learned Note", "note", "Unlearn a note — gain permanent +1 ATK"),
    ("Renounce Matter", "matter", "Lose all carried matter — gain permanent +3 DEF"),
    ("Renounce Rest", "rest", "Can no longer camp — gain +5 HP and +1 speed"),
    ("Renounce an Effect", "effect", "Lose one effect, gain permanent +2 sight radius"),
]

# Named, because the offering text quotes it and the two drifted apart once already.
SIGHT_PER_RENUNCIATION = 2

# What each renunciation is WORTH, before the cost of what it takes from you. These were five
# literals inside `_worth` chosen to be state-driven rather than measured, which was said
# plainly at the time and is now swept.
#
# `GAIN_PCT` scales all five together. That is deliberate: five gains swept independently is a
# five-dimensional space and roughly 1 shrine fires per run, so the arms would be
# indistinguishable long before the space was covered. One scalar asks the question the design
# actually has, which is whether the shrine is too eager or too reluctant, and the per-kind
# uptake table below says which individual gain to move next if any.
SHRINE_GAIN = {"sigil": 8, "note": 6, "matter": 9, "rest": 7, "effect": 5}
GAIN_PCT = int(os.environ.get("VC_SHRINE_GAIN_PCT", "100"))


def _gain(kind: str) -> int:
    return SHRINE_GAIN.get(kind, 0) * GAIN_PCT // 100


class SacrificeSystem(System):
    name = "sacrifice"

    def __init__(self):
        self.shrines: dict[tuple, list] = {}  # (x,y) -> list of offering texts
        self._done: set = set()               # positions already used
        # "Renounce an Effect" promises "+2 sight radius" in its own offering text and
        # granted nothing: `apply` left a comment saying the bonus was "handled in
        # knowledge.py via _sight()", and `_sight()` had no such term. The offering was pure
        # loss. `knowledge._sight()` now reads this.
        self.sight_bonus: int = 0

    def on_world_start(self, game):
        self.shrines = {}
        self._done = set()
        self.sight_bonus = 0

    # Fraction of the descent below which no shrine appears. "Deep levels (rare)" needs a
    # depth axis, and the two modes do not share one.
    DEPTH_FRACTION = 0.5
    SANDBOX_MIN_DEPTH = 2

    def _is_deep(self, game) -> bool:
        """Deep enough for a shrine, in whichever axis this mode actually moves.

        This used to be `if getattr(game, "current_z", 0) > -2: return`. `current_z` comes
        from `level.z` and is only ever non-zero in sandbox, so in CLASSIC DESCENT it is 0 on
        every floor and the guard rejected every one. The whole system was unreachable in the
        mode every measurement this project has ever taken was run in: 288-run baselines,
        three ablation sweeps, both quality sweeps. `ablate.py` reported dropping `sacrifice`
        as inert, which was true and told us nothing, because it was already inert.
        """
        z = getattr(game, "current_z", 0)
        if z < 0:                                    # sandbox: depth is the z axis
            return z <= -self.SANDBOX_MIN_DEPTH
        floor = getattr(game, "floor", 0)            # classic: depth is the floor number
        bottom = getattr(game, "max_floor", 0) or 0
        if bottom <= 0:
            return False
        return floor >= max(2, int(bottom * self.DEPTH_FRACTION))

    def on_floor_enter(self, game):
        self.shrines = {}
        if not self._is_deep(game):
            return
        rng = random.Random(f"{game.seed}:{game.floor}:sacrifice")
        if rng.random() > 0.30:
            return
        from runtime.dungeon import free_floor_tiles
        free = free_floor_tiles(game.level, {(game.player.x, game.player.y)})
        if not free:
            return
        pos = rng.choice(free)
        if pos in self._done:
            return
        # pick 3 distinct offerings
        picks = rng.sample(_OFFERINGS, min(3, len(_OFFERINGS)))
        self.shrines[pos] = picks
        game._overlay[pos] = "◊"

    def points_of_interest(self, game):
        """Tiles an autonomous agent may want to visit.

        The shrine had none, so once the depth gate was fixed it was placed on the map and
        still never reached: an agent has no reason to walk to a tile nothing advertises, and
        `interact` only fires on the tile you are standing on. Placement is not reachability,
        and a system can be revived into being just as dead as before.
        """
        return list(self.shrines)

    def render_overlay(self, game, grid):
        for (x, y) in self.shrines:
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
                grid[y][x] = "◊"

    def on_interact(self, game) -> bool:
        pos = (game.player.x, game.player.y)
        offers = self.shrines.pop(pos, None)
        if offers is None:
            return False
        self._done.add(pos)
        game._overlay.pop(pos, None)
        game._pending_sacrifice = offers
        game.log("A shrine of renunciation hums before you. Choose, or reject.")
        # A curses front end answers this popup synchronously (runtime/play.py, key "a").
        # Nothing else does. An agent reaching the shrine therefore had it consumed, popped
        # from `self.shrines` and added to `_done` above, and received nothing at all: the
        # verb was strictly worse than not pressing it, and no agent could take a choice a
        # human walks through. That is a Berlin violation, and it is the second one found in
        # this codebase of the same shape.
        if not getattr(game, "has_ui", False):
            self.resolve(game, offers)
        return True  # consumed the interact

    def _worth(self, game, kind: str) -> int:
        """Score one offering from GAME STATE, never from the agent's identity.

        Every profile runs this identical function. What differs is what each arrives
        holding, which is exactly where this project's differentiation is allowed to come
        from: starting state and what the run has done since, never a class. An agent
        carrying nothing finds `matter` nearly free; one with five sigils finds `sigil`
        cheap; one that never camps loses nothing to `rest`.

        Returns gain minus cost. Non-positive means walk away, and walking away stays
        reachable: a shrine offering nothing this agent wants crumbles unspent.
        """
        if kind == "sigil":
            sigs = game.system("sigils")
            slots = len(getattr(sigs, "slots", []) or [])
            return _gain("sigil") - max(0, 12 - 2 * slots)     # a spare slot is cheap, the last is not
        if kind == "note":
            know = game.system("knowledge")
            known = len(getattr(know, "known", ()) or ())
            return _gain("note") - max(0, 10 - known)
        if kind == "matter":
            salv = game.system("salvage")
            held = salv.inventory(game).total() if salv else 0
            return _gain("matter") - min(9, held)               # free when broke, dear when rich
        if kind == "rest":
            # Camping is worth most to an agent that is hurt and has been using it.
            hp_pct = game.player.hp * 100 // max(1, getattr(game.player, "max_hp", 1))
            return _gain("rest") - (0 if hp_pct >= 70 else 10)
        if kind == "effect":
            eff = game.system("effects")
            held = len(getattr(eff, "collected", ()) or ())
            return _gain("effect") - max(0, 8 - 3 * held)
        return 0

    def resolve(self, game, offers) -> str:
        """Take the best offering on state, or reject all. Returns what was chosen ("" if
        rejected). Deterministic: ties break on the offering's own key, not on iteration
        order, so the same run makes the same choice on any machine."""
        scored = sorted(((self._worth(game, kind), kind) for _, kind, _ in offers),
                        key=lambda sk: (-sk[0], sk[1]))
        best, kind = scored[0] if scored else (0, "")
        # Every resolution is recorded, taken or not. `shrine_used` alone counts only the
        # takes, so a build where the agent refuses every shrine and one where it never
        # reaches a shrine report the same number, and those are opposite problems. Uptake is
        # a rate and a rate needs its denominator.
        self._record("shrine_offered")
        # Which kinds were on the table, not only which won. Without this, an offering that
        # never wins is indistinguishable from one the pool rarely deals, and the fix for
        # each is the opposite: raise its gain, or change what `_OFFERINGS` samples.
        for _n, k, _t in offers:
            self._record("", k, table="shrine_pool")
        if best <= 0 or not kind:
            self._record("shrine_rejected")
            game._pending_sacrifice = None
            game.log("You weigh the shrine's offer and turn away. It crumbles to dust.")
            return ""
        self.apply(game, kind)
        return kind

    @staticmethod
    def _record(key: str, kind: str = "", table: str = "shrine_choice"):
        try:
            from runtime.metrics import metrics
            m = metrics()
            if kind:
                d = m.systems.setdefault(table, {})
                d[kind] = d.get(kind, 0) + 1
            else:
                m.systems[key] = m.systems.get(key, 0) + 1
        except Exception:
            pass

    def apply(self, game, choice: str):
        """Apply the chosen sacrifice permanently."""
        if choice == "sigil":
            sigs = game.system("sigils")
            if sigs and sigs.slots:
                sigs.slots.pop()
            game.player.max_hp += 8
            game.player.hp += 8
        elif choice == "note":
            know = game.system("knowledge")
            if know and know.known:
                # sorted: `known` is a set, so next(iter(...)) picked a different note
                # per process rather than per game seed.
                nid = next(iter(sorted(know.known)), None)
                if nid:
                    know.known.discard(nid)
            game.player.atk += 1
        elif choice == "matter":
            salv = game.system("salvage")
            if salv:
                bag = salv.inventory(game)
                if bag:
                    bag.comp = {}
            game.player.defense += 3
        elif choice == "rest":
            from runtime.game import Game
            game._resting = False
            game._consecutive_rest = 0
            game._cant_camp = True
            game.player.max_hp += 5
            game.player.hp += 5
            game.player.speed += 0.2
            game.player._base_speed = game.player.speed
        elif choice == "effect":
            eff = game.system("effects")
            if eff and eff.collected:
                nid = next(iter(sorted(eff.collected)), None)
                if nid:
                    eff.collected.discard(nid)
                    if eff.worn == nid:
                        eff.worn = None
            self.sight_bonus += SIGHT_PER_RENUNCIATION
        # `shrine_used` existed in MetricsTracker from the start and nothing ever
        # incremented it, so "did a shrine fire" was unanswerable from any run's output.
        self._record("shrine_used")
        self._record("", choice)
        game._pending_sacrifice = None
        game.log(f"You accept the {choice} renunciation — the shrine crumbles, and you are changed.")
