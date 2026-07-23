"""Interaction-aware NPC brains — the lower rungs of the capability ladder.

Four `Brain` subclasses built entirely on the None-guarded perception toolkit in
`runtime.sense`, each registered under the exact tier name the engine's
`brain_for` policy expects:

    survivor    — tier-2 monsters: chase, but self-preserve (flee low, route around fire).
    opportunist — tier-3 monsters / wild predators: survivor + let terrain finish foes.
    forager     — wild grazers: skittish prey that flees any hostile in sight.
    scavenger   — wild scavengers: same flee reflex; otherwise idle for the fauna driver.

Determinism: every decision is a pure function of (game, actor) state — no `random`,
no clock. The only tie-break (opportunist choosing among several doomed neighbours)
is resolved by tile coordinate, so it is reproducible across runs and independent of
iteration order. Tolerance: all system reads go through `sense` (already None-guarded),
and anything uncertain falls back to `(0, 0)` (wait) rather than raising.

INTEGRATOR NOTE: importing this module is what registers the tiers. The lead imports
`runtime.brains` (alongside `runtime.tactics`) in play.py so `brain_for` can resolve
them; until then the registry's fallback ladder degrades these names to a built-in.
"""
from __future__ import annotations

from runtime.sense import (
    Brain, register_brain,
    hostiles, nearest_hostile, is_dangerous,
    step_toward, step_away, adjacent, attack_dir,
)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

def _low_hp(actor) -> bool:
    """Self-preservation threshold: strictly below 35% of max hp."""
    max_hp = getattr(actor, "max_hp", 0) or 0
    return actor.hp * 100 < max_hp * 35


def _adjacent_hostiles(game, actor):
    """Hostiles standing within one tile (chebyshev <= 1) of `actor`."""
    return [h for h in hostiles(game, actor)
            if adjacent(actor.x, actor.y, h.x, h.y)]


# --------------------------------------------------------------------------- #
# Tier 2 — survivor
# --------------------------------------------------------------------------- #

class SurvivorBrain(Brain):
    """Chases the nearest hostile but never suicides:

    1. no hostile -> wait.
    2. low HP -> flee to a safe tile.
    3. adjacent -> bump-attack.
    4. else -> approach along hazard-free tiles (never volunteers onto fire/acid).
    """
    name = "survivor"

    def decide(self, game, actor):
        target, dist = nearest_hostile(game, actor)
        if target is None or dist is None:
            return (0, 0)
        if _low_hp(actor):
            return step_away(game, actor, target.x, target.y, safe=True)
        if dist <= 1:
            return attack_dir(actor, target)
        return step_toward(game, actor, target.x, target.y, safe=True)


# --------------------------------------------------------------------------- #
# Tier 3 — opportunist
# --------------------------------------------------------------------------- #

class OpportunistBrain(SurvivorBrain):
    """A survivor that lets the environment do the work: among the hostiles already
    adjacent, it strikes one standing on a hazard first (it is dying anyway). Low-HP
    flight still wins; with no doomed neighbour it falls back to survivor behaviour.
    """
    name = "opportunist"

    def decide(self, game, actor):
        target, dist = nearest_hostile(game, actor)
        if target is None or dist is None:
            return (0, 0)
        if _low_hp(actor):
            return step_away(game, actor, target.x, target.y, safe=True)
        doomed = [h for h in _adjacent_hostiles(game, actor)
                  if is_dangerous(game, h.x, h.y)]
        if doomed:
            # deterministic tie-break by coordinate (order-independent, seed-free)
            victim = min(doomed, key=lambda h: (h.x, h.y))
            return attack_dir(actor, victim)
        if dist <= 1:
            return attack_dir(actor, target)
        return step_toward(game, actor, target.x, target.y, safe=True)


# --------------------------------------------------------------------------- #
# Wild fauna — forager / scavenger
# --------------------------------------------------------------------------- #

class ForagerBrain(Brain):
    """Skittish grazer: if any hostile is within sight (~5) flee to a safe tile;
    otherwise wait so the fauna system can drive the grazing. Never charges.
    """
    name = "forager"
    sight = 5

    def decide(self, game, actor):
        target, dist = nearest_hostile(game, actor)
        if target is None or dist is None:
            return (0, 0)
        if dist <= self.sight:
            return step_away(game, actor, target.x, target.y, safe=True)
        return (0, 0)


class ScavengerBrain(ForagerBrain):
    """Same skittish flee-from-hostiles reflex as the forager; otherwise idle so the
    fauna system can lead it to corpses."""
    name = "scavenger"


# --------------------------------------------------------------------------- #
# Registration (runs at import time)
# --------------------------------------------------------------------------- #

register_brain("survivor", SurvivorBrain)
register_brain("opportunist", OpportunistBrain)
register_brain("forager", ForagerBrain)
register_brain("scavenger", ScavengerBrain)


# --------------------------------------------------------------------------- #
# Companion — walks with whoever you control, fights what you fight
# --------------------------------------------------------------------------- #

def _panic_flee(game, actor):
    """Flee toward stairs or the player, whichever is closer."""
    stairs = getattr(game.level, "stairs", None) if getattr(game, "level", None) else None
    p = game.player
    to_stairs = (
        max(abs(actor.x - stairs[0]), abs(actor.y - stairs[1])) if stairs else None
    )
    to_player = max(abs(actor.x - p.x), abs(actor.y - p.y))
    if to_stairs is not None and to_stairs < to_player:
        return step_toward(game, actor, stairs[0], stairs[1], safe=True)
    return step_away(game, actor, p.x, p.y, safe=True)


class CompanionBrain(SurvivorBrain):
    """A recruited creature: reads its command from game._companions and obeys,
    fighting like a survivor. Panics below 25% hp, fleeing toward safety."""
    name = "companion"

    def decide(self, game, actor):
        name = getattr(actor, "name", "")
        comps = getattr(game, "_companions", {}) or {}
        state = comps.get(name, {})
        command = state.get("state", "follow")

        # panic overrides everything
        max_hp = getattr(actor, "max_hp", 0) or 0
        if max_hp and actor.hp * 100 < max_hp * 25:
            return _panic_flee(game, actor)

        if command == "stay":
            adj = [h for h in hostiles(game, actor)
                   if adjacent(actor.x, actor.y, h.x, h.y)]
            if adj:
                victim = min(adj, key=lambda h: (h.x, h.y))
                return attack_dir(actor, victim)
            return (0, 0)

        if command == "guard":
            guard_pos = state.get("pos")
            if guard_pos is None:
                return (0, 0)
            gx, gy = guard_pos
            nearby = [h for h in hostiles(game, actor)
                      if max(abs(gx - h.x), abs(gy - h.y)) <= 3]
            if nearby:
                target = min(nearby, key=lambda h: max(abs(actor.x - h.x), abs(actor.y - h.y)))
                if adjacent(actor.x, actor.y, target.x, target.y):
                    return attack_dir(actor, target)
                return step_toward(game, actor, target.x, target.y, safe=True)
            if max(abs(actor.x - gx), abs(actor.y - gy)) > 3:
                return step_toward(game, actor, gx, gy, safe=True)
            return (0, 0)

        if command == "scout":
            scout_pos = state.get("pos")
            if scout_pos is None:
                return (0, 0)
            nearby = [h for h in hostiles(game, actor)
                      if max(abs(actor.x - h.x), abs(actor.y - h.y)) <= 5]
            if nearby:
                p = game.player
                return step_toward(game, actor, p.x, p.y, safe=True)
            sx, sy = scout_pos
            return step_toward(game, actor, sx, sy, safe=True)

        # follow (default)
        step = super().decide(game, actor)
        if step != (0, 0):
            return step
        p = game.player
        if max(abs(actor.x - p.x), abs(actor.y - p.y)) > 2:
            return step_toward(game, actor, p.x, p.y, safe=True)
        return (0, 0)


register_brain("companion", CompanionBrain)
