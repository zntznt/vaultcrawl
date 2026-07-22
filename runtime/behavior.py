"""Behavior oracle — utility-based action selection for creature brains.

Each oracle is a predicate that scores how desirable an action is given the current
state (0.0 = inappropriate, 1.0 = urgent). Brains query oracles and pick the
highest-scoring action. This replaces linear if-chains with composable evaluation.

Deterministic: scores are pure functions of board state, no RNG.
"""
from __future__ import annotations


def oracles_for(game, actor) -> list[tuple[str, float]]:
    """Evaluate all oracles and return (action_name, score) sorted by score descending."""
    scores = []
    for name, fn in _ORACLES:
        s = fn(game, actor)
        if s > 0:
            scores.append((name, s))
    scores.sort(key=lambda x: -x[1])
    return scores


def best_action(game, actor) -> str | None:
    """Highest-scoring oracle's action name, or None if all score 0."""
    scored = oracles_for(game, actor)
    return scored[0][0] if scored else None


# ---- oracle predicates (each returns float 0..1) ----------------------------


def _flee_when_fearful(game, actor) -> float:
    from .sense import is_fearful
    return 0.8 if is_fearful(actor) else 0.0


def _charge_when_enraged(game, actor) -> float:
    from .sense import is_enraged
    return 0.7 if is_enraged(actor) else 0.0


def _avoid_fire(game, actor) -> float:
    r = game.system("reactions")
    if r is None:
        return 0.0
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            nx, ny = actor.x + dx, actor.y + dy
            if r.is_hazard(nx, ny):
                return 0.6
    return 0.0


def _chase_hostile(game, actor) -> float:
    from .sense import nearest_hostile
    t, d = nearest_hostile(game, actor)
    if t is None:
        return 0.0
    return min(1.0, 0.5 + (len(game.actors) > 1) * 0.2)


def _lure_onto_hazard(game, actor) -> float:
    from .sense import lure_step, nearest_hostile
    t, _d = nearest_hostile(game, actor)
    if t is None:
        return 0.0
    if lure_step(game, actor, t) is not None:
        return 0.5
    return 0.0


def _scent_track(game, actor) -> float:
    ss = game.system("scent")
    if ss is None:
        return 0.0
    nbr = ss.strongest_neighbour(game, actor.x, actor.y)
    if nbr is not None and ss.scent_at(*nbr) > 2:
        return 0.4
    return 0.0


def _patrol_home(game, actor) -> float:
    home = getattr(actor, "_home", None)
    if home is None:
        return 0.0
    d = max(abs(actor.x - home[0]), abs(actor.y - home[1]))
    if d > 5:
        return 0.3
    return 0.0


def _attack_adjacent(game, actor) -> float:
    from .sense import adjacent
    from .sense import nearest_hostile
    t, d = nearest_hostile(game, actor)
    if t is not None and d is not None and d <= 1:
        return 0.9
    return 0.0


# ---- registry (ordered by name for determinism) -----------------------------

_ORACLES: list[tuple[str, callable]] = sorted([
    ("attack_adjacent", _attack_adjacent),
    ("flee_when_fearful", _flee_when_fearful),
    ("charge_when_enraged", _charge_when_enraged),
    ("avoid_fire", _avoid_fire),
    ("chase_hostile", _chase_hostile),
    ("lure_onto_hazard", _lure_onto_hazard),
    ("scent_track", _scent_track),
    ("patrol_home", _patrol_home),
], key=lambda x: x[0])
