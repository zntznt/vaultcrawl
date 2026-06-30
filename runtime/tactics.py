"""The two top-of-the-ladder brains: the schemer and the player.

`tactician` and `exploiter` are the cleverest agents on the capability ladder — they
don't just chase, they *use the ecology against their target*: kiting a foe onto acid,
finishing one the terrain is already dissolving, or (for the player) leading a monster
onto a hazard, grabbing loot, and bailing to the stairs when wounded.

Both read the world only through the None-guarded perception toolkit in `sense.py`, so
they degrade gracefully when a system (reactions/structures/...) is absent and never
crash. Everything here is deterministic: no rng, no clock — given identical state the
same step comes out every time. The engine maps entities to these tiers via
`sense.brain_for` (monster tier4+/boss/hunter -> `tactician`; the player -> `exploiter`),
but this module must be *imported* for the tiers to register (the lead imports it in
play.py alongside `brains`).
"""
from __future__ import annotations

from runtime.sense import (
    Brain, register_brain,
    hostiles, nearest_hostile, is_dangerous, lure_step, step_toward, step_away,
    points_of_interest, adjacent, attack_dir,
)

WAIT = (0, 0)


def _low_hp(actor, pct):
    """True when actor.hp is below `pct`% of max (integer-safe, None-guarded)."""
    mx = getattr(actor, "max_hp", 0) or 0
    hp = getattr(actor, "hp", 0) or 0
    return mx > 0 and hp * 100 < mx * pct


def _stairs(game):
    lvl = getattr(game, "level", None)
    return getattr(lvl, "stairs", None) if lvl is not None else None


def _nearest_xy(actor, tiles):
    """Nearest (Chebyshev) tile to `actor`; ties broken by (x,y) for determinism."""
    best, bd = None, None
    for t in tiles:
        try:
            x, y = t
        except (TypeError, ValueError):
            continue
        d = max(abs(actor.x - x), abs(actor.y - y))
        if bd is None or d < bd or (d == bd and (x, y) < best):
            best, bd = (x, y), d
    return best


# --------------------------------------------------------------------------- #
# Tactician — the schemer (tough foes, hunters, bosses)
# --------------------------------------------------------------------------- #

class TacticianBrain(Brain):
    """Kites its target onto a hazard, finishes foes the terrain is already killing,
    and flees when wounded. The smartest monster on the ladder."""
    name = "tactician"

    def decide(self, game, actor):
        try:
            # 1) nobody to fight -> hold position
            t, d = nearest_hostile(game, actor)
            if t is None or d is None:
                return WAIT
            # 2) wounded -> break off to a safe tile
            if _low_hp(actor, 35):
                return step_away(game, actor, t.x, t.y, safe=True)
            # 3) target is adjacent AND already standing in a hazard -> land the killing
            #    blow while the terrain finishes the job
            if d <= 1 and is_dangerous(game, t.x, t.y):
                return attack_dir(actor, t)
            # 4) the signature move: a safe step that makes the target's greedy chase
            #    next land it on a danger tile (kite onto the hazard)
            lure = lure_step(game, actor, t)
            if lure is not None:
                return lure
            # 5) adjacent with no kite available -> just attack
            if d <= 1:
                return attack_dir(actor, t)
            # 6) close the gap without volunteering to stand in fire/acid
            return step_toward(game, actor, t.x, t.y, safe=True)
        except Exception:
            return WAIT


# --------------------------------------------------------------------------- #
# Exploiter — the player brain (hostiles = monsters)
# --------------------------------------------------------------------------- #

class ExploiterBrain(Brain):
    """The player: flee to the exit when low, lead monsters onto hazards, grab loot,
    then descend. Plays the ecology rather than trading blows."""
    name = "exploiter"

    def _loot_goal(self, game, actor):
        goals = list(points_of_interest(game) or [])
        for it in (getattr(game, "items", None) or []):
            ix, iy = getattr(it, "x", None), getattr(it, "y", None)
            if ix is not None and iy is not None:
                goals.append((ix, iy))
        return _nearest_xy(actor, goals)

    def _to_stairs(self, game, actor):
        st = _stairs(game)
        if not st:
            return WAIT
        return step_toward(game, actor, st[0], st[1], safe=True)

    def decide(self, game, actor):
        try:
            # 1) wounded -> retreat to the exit, dodging hazards
            if _low_hp(actor, 40):
                return self._to_stairs(game, actor)

            t, d = nearest_hostile(game, actor)
            if t is not None and d is not None:
                # 2) an adjacent monster that is already on a danger tile -> finish it
                for h in hostiles(game, actor):
                    if adjacent(actor.x, actor.y, h.x, h.y) and is_dangerous(game, h.x, h.y):
                        return attack_dir(actor, h)
                # 3) a monster within reach -> try to lead it onto a hazard
                if d <= 2:
                    lure = lure_step(game, actor, t)
                    if lure is not None:
                        return lure
                # 4) cornered by an adjacent monster -> attack
                if d <= 1:
                    return attack_dir(actor, t)

            # 5) no threat worth handling -> go grab the nearest sigil / loot
            goal = self._loot_goal(game, actor)
            if goal is not None:
                return step_toward(game, actor, goal[0], goal[1], safe=True)

            # 6) nothing left here -> head for the stairs (the loop descends on arrival)
            return self._to_stairs(game, actor)
        except Exception:
            return WAIT


register_brain("tactician", TacticianBrain)
register_brain("exploiter", ExploiterBrain)
