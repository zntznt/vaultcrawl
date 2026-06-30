"""Perception + the Brain interface — the shared toolkit every agent reasons with.

An actor's *brain* decides one thing per turn: `decide(game, actor) -> (dx, dy)`, a step
direction (stepping into a hostile = a bump attack; `(0,0)` = wait). Intelligence lives in
how cleverly a brain picks that direction using the affordances below.

This module is dependency-free of the systems: every system query is None-guarded, so a
brain degrades gracefully when reactions/structures/etc. are absent. It owns the brain
registry and the `brain_for` policy (which entity gets which capability tier), plus two
built-ins — WanderBrain and HunterBrain — so the engine always has a working default even
before the richer tiers (brains.py / tactics.py) are loaded.
"""
from __future__ import annotations

from collections import deque

_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))


# --------------------------------------------------------------------------- #
# Brain interface
# --------------------------------------------------------------------------- #

class Brain:
    name = "brain"

    def decide(self, game, actor):
        """Return a step direction (dx, dy) in {-1,0,1}. (0,0) waits."""
        return (0, 0)


# --------------------------------------------------------------------------- #
# Perception — affordances every brain can read (all system calls None-guarded)
# --------------------------------------------------------------------------- #

def hostiles(game, actor):
    out = []
    if game.alive and game._hostile(actor.allegiance, "player"):
        out.append(game.player)
    for o in game.actors:
        if o is not actor and o.hp > 0 and game._hostile(actor.allegiance, o.allegiance):
            out.append(o)
    return out


def nearest(actor, things):
    best, bd = None, 10 ** 9
    for t in things:
        d = max(abs(actor.x - t.x), abs(actor.y - t.y))
        if d < bd:
            best, bd = t, d
    return best, (bd if best is not None else None)


def nearest_hostile(game, actor):
    # When a senses system is registered, targeting is perception-limited (you can only
    # engage what you can actually perceive + identify). Otherwise it stays omniscient,
    # so every test/scenario without a SenseField behaves exactly as before.
    if getattr(game, "system", None) is not None and game.system("senses") is not None:
        from . import senses
        return senses.nearest_perceived_hostile(game, actor)
    return nearest(actor, hostiles(game, actor))


def danger_tiles(game):
    """Union of every system's hazard tiles (reactions fire/acid/charged, armed traps)."""
    d = set()
    for name in ("reactions", "structures"):
        s = game.system(name) if hasattr(game, "system") else None
        if s is None:
            continue
        try:
            d |= set(s.hazard_tiles(game))
        except Exception:
            pass
    return d


def is_dangerous(game, x, y):
    return (x, y) in danger_tiles(game)


def element_at(game, x, y):
    r = game.system("reactions") if hasattr(game, "system") else None
    if r is None:
        return None
    try:
        return r.element_at(x, y)
    except Exception:
        return None


def points_of_interest(game):
    out = []
    for s in getattr(game, "systems", []):
        try:
            out.extend(s.points_of_interest(game))
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# Movement primitives
# --------------------------------------------------------------------------- #

def _passable(game, actor, x, y, goal):
    if (x, y) == goal:
        return True
    if not game.level.walkable(x, y):
        return False
    if (x, y) == (game.player.x, game.player.y) and actor is not game.player:
        return False
    return game.actor_at(x, y) is None


def bfs_step(game, actor, goal, avoid=frozenset()):
    """First (dx,dy) of the shortest path to `goal` avoiding `avoid` tiles, or None."""
    start = (actor.x, actor.y)
    if start == goal:
        return (0, 0)
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for dx, dy in _ORTH:
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in prev or (nxt in avoid and nxt != goal):
                continue
            if _passable(game, actor, nxt[0], nxt[1], goal):
                prev[nxt] = cur
                q.append(nxt)
    if goal not in prev:
        return None
    cur = goal
    while prev[cur] != start:
        cur = prev[cur]
    return (cur[0] - start[0], cur[1] - start[1])


def step_toward(game, actor, tx, ty, safe=True):
    """Step toward (tx,ty). If safe, avoid danger tiles; fall back to reckless if boxed in."""
    goal = (tx, ty)
    if safe:
        s = bfs_step(game, actor, goal, danger_tiles(game))
        if s is not None:
            return s
    s = bfs_step(game, actor, goal)
    return s or (0, 0)


def greedy_dir(fx, fy, tx, ty):
    """Old-style single step: larger axis first (no pathfinding)."""
    sx = (tx > fx) - (tx < fx)
    sy = (ty > fy) - (ty < fy)
    if abs(tx - fx) >= abs(ty - fy):
        return (sx, 0) if sx else (0, sy)
    return (0, sy) if sy else (sx, 0)


def greedy_step_toward(game, actor, tx, ty):
    """Reproduces the legacy chaser: try the larger axis, fall back to the other."""
    sx = (tx > actor.x) - (tx < actor.x)
    sy = (ty > actor.y) - (ty < actor.y)
    opts = sorted([(abs(actor.x - tx), (sx, 0)), (abs(actor.y - ty), (0, sy))], reverse=True)
    for _, (mx, my) in opts:
        nx, ny = actor.x + mx, actor.y + my
        if (mx or my) and game.level.walkable(nx, ny) and game.actor_at(nx, ny) is None \
                and (nx, ny) != (game.player.x, game.player.y):
            return (mx, my)
    return (0, 0)


def step_away(game, actor, fx, fy, safe=True):
    """Pick the walkable neighbour that maximizes distance from (fx,fy); prefer safe tiles."""
    danger = danger_tiles(game) if safe else set()
    best, bd = (0, 0), -1
    for dx, dy in _ORTH:
        nx, ny = actor.x + dx, actor.y + dy
        if not game.level.walkable(nx, ny) or game.actor_at(nx, ny) is not None:
            continue
        if (nx, ny) == (game.player.x, game.player.y):
            continue
        if (nx, ny) in danger:
            continue
        d = max(abs(nx - fx), abs(ny - fy))
        if d > bd:
            best, bd = (dx, dy), d
    return best


def adjacent(ax, ay, bx, by):
    return max(abs(ax - bx), abs(ay - by)) <= 1


def attack_dir(a, t):
    """Unit step from `a` toward an adjacent target `t` (resolved as a bump attack)."""
    return ((t.x > a.x) - (t.x < a.x), (t.y > a.y) - (t.y < a.y))


def lure_step(game, actor, target):
    """1-ply kite: pick a safe step for `actor` such that `target`'s greedy chase next lands
    it on a danger tile. Returns the luring direction, or None if no such step exists."""
    danger = danger_tiles(game)
    if not danger:
        return None
    for dx, dy in _ORTH:
        px, py = actor.x + dx, actor.y + dy
        if not game.level.walkable(px, py) or game.actor_at(px, py) is not None:
            continue
        if (px, py) in danger or (px, py) == (game.player.x, game.player.y):
            continue
        tdx, tdy = greedy_dir(target.x, target.y, px, py)
        if (target.x + tdx, target.y + tdy) in danger:
            return (dx, dy)
    return None


# --------------------------------------------------------------------------- #
# Built-in brains (defaults) + the registry / policy
# --------------------------------------------------------------------------- #

class WanderBrain(Brain):
    name = "wander"

    def decide(self, game, actor):
        # deterministic idle drift; only reacts if a hostile is adjacent
        tgt, d = nearest_hostile(game, actor)
        if tgt is not None and d is not None and d <= 1:
            return (tgt.x - actor.x and (tgt.x > actor.x) - (tgt.x < actor.x),
                    tgt.y - actor.y and (tgt.y > actor.y) - (tgt.y < actor.y))
        return (0, 0)


class HunterBrain(Brain):
    """The legacy chaser: beeline to the nearest hostile and bump it. No self-preservation."""
    name = "hunter"

    sight = 6

    def decide(self, game, actor):
        tgt, d = nearest_hostile(game, actor)
        if tgt is None or d is None:
            return (0, 0)
        if d <= 1:
            return ((tgt.x > actor.x) - (tgt.x < actor.x),
                    (tgt.y > actor.y) - (tgt.y < actor.y))
        if d <= self.sight:
            return greedy_step_toward(game, actor, tgt.x, tgt.y)
        return (0, 0)


BRAIN_REGISTRY: dict = {}


def register_brain(name, cls):
    BRAIN_REGISTRY[name] = cls


register_brain("wander", WanderBrain)
register_brain("hunter", HunterBrain)

# When a richer tier isn't loaded yet, fall back down the ladder to a built-in.
_FALLBACK = {
    "mastermind": "tactician", "tracker": "survivor", "wary": "opportunist",
    "exploiter": "tactician", "tactician": "opportunist", "opportunist": "survivor",
    "survivor": "hunter", "forager": "survivor", "scavenger": "survivor",
    "hunter": "wander",
}


def brain_for(actor) -> str:
    """Policy: which capability tier an entity deserves (resolved against the registry)."""
    al = getattr(actor, "allegiance", "monster")
    if al == "player":
        return "exploiter"
    if al == "npc":
        return "wander"          # NPCs idle peacefully; you approach and parley
    if al == "wild":
        src = getattr(actor, "source", "") or ""
        if "grazer" in src:
            return "forager"
        if "scavenger" in src:
            return "scavenger"
        if "predator" in src:
            return "opportunist"
        return "survivor"
    # monster: the mind tiers — bosses/elites plan deliberately, hunters track from memory,
    # mid-tier foes grow wary of what's burned them; grunts just charge.
    if getattr(actor, "is_boss", False):
        return "mastermind"
    if getattr(actor, "is_hunter", False):
        return "tracker"
    t = getattr(actor, "tier", 1)
    if t >= 4:
        return "mastermind"
    if t == 3:
        return "wary"
    if t == 2:
        return "survivor"
    return "hunter"


def make_brain(game, actor, name=None):
    """Resolve a brain for an actor, descending the fallback ladder until one is registered."""
    name = name or brain_for(actor)
    seen = set()
    while name and name not in BRAIN_REGISTRY and name not in seen:
        seen.add(name)
        name = _FALLBACK.get(name)
    cls = BRAIN_REGISTRY.get(name, HunterBrain)
    return cls()
