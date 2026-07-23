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
        """Return an AgentAction or legacy (dx, dy) tuple in {-1,0,1}. (0,0) waits.
        The auto_play dispatch loop auto-wraps legacy tuples for backward compat."""
        return (0, 0)


# --------------------------------------------------------------------------- #
# Perception — affordances every brain can read (all system calls None-guarded)
# --------------------------------------------------------------------------- #

def hostiles(game, actor):
    hostile = getattr(game, "hostile", None) or (
        lambda a, b: game._hostile(a.allegiance, b.allegiance))
    out = []
    if game.alive and hostile(actor, game.player):
        out.append(game.player)
    for o in game.actors:
        if o is not actor and o.hp > 0 and hostile(actor, o):
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


def step_toward_safe(game, actor, tx, ty):
    """Step toward (tx,ty) avoiding hazards AND unrevealed tiles (potential traps)."""
    danger = danger_tiles(game)
    know = game.system("knowledge") if hasattr(game, "system") else None
    if know is not None:
        seen = know.seen.get(game.floor, set())
        px, py = actor.x, actor.y
        for y in range(max(0, py-10), min(game.level.h, py+11)):
            for x in range(max(0, px-10), min(game.level.w, px+11)):
                if game.level.walkable(x, y) and (x, y) not in seen:
                    danger.add((x, y))
    s = bfs_step(game, actor, (tx, ty), danger)
    if s is not None:
        return s
    s = bfs_step(game, actor, (tx, ty), danger_tiles(game))
    if s is not None:
        return s
    s = bfs_step(game, actor, (tx, ty))
    return s or (0, 0)


def step_toward_avoiding_elites(game, actor, tx, ty):
    """Like step_toward_safe but also routes around elites with non-fight encounter
    options available. The agent sees the elite and takes the long way."""
    # Start with standard safe path
    s = step_toward_safe(game, actor, tx, ty)
    if s is None or s == (0, 0):
        return (0, 0)
    nx, ny = actor.x + s[0], actor.y + s[1]
    # Check if we're walking toward an elite with non-fight options
    for a in game.actors:
        tier = getattr(a, "tier", 1)
        if tier < 3 or a is actor or getattr(a, "hp", 0) <= 0:
            continue
        apos = (a.x, a.y)
        d_to_actor = max(abs(nx - a.x), abs(ny - a.y))
        if d_to_actor > 2:
            continue
        # Check if this elite offers non-fight options
        if _has_non_fight_options(game, actor, a):
            # Route around: add elite's position to danger set
            avoid = danger_tiles(game) | {apos}
            alt = bfs_step(game, actor, (tx, ty), avoid)
            if alt is not None:
                return alt
    return s


def _has_non_fight_options(game, actor, target) -> bool:
    """Check if the agent has any non-fight encounter option for this elite."""
    fcs = game.system("factions")
    faction = getattr(target, "faction", "")
    standing = getattr(fcs, "standing", {}).get(faction, 0) if fcs else 0
    know = game.system("knowledge")
    source_known = know.is_known(getattr(target, "source", "")) if know else False
    salv = game.system("salvage")
    matter = salv.inventory(game).total() if salv else 0
    # Whisper always has parley
    if getattr(getattr(game, "player", None), "_agent_name", "") == "whisper":
        return True
    # Any non-fight gate accessible?
    return standing >= 1 or source_known or matter >= 1


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
    "artisan": "exploiter", "cartographer": "exploiter", "emergent": "exploiter",
    "seeker": "exploiter", "whisper": "exploiter",
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
    cls = BRAIN_REGISTRY.get(name) or BRAIN_REGISTRY.get("hunter", HunterBrain)
    return cls()


# --------------------------------------------------------------------------- #
# Trigger / emotion system — anger and fear tracking for creature brains.
# --------------------------------------------------------------------------- #
#
# Each monster has anger (0..1) and fear (0..1) that decay toward base values.
# Triggers modify them; brains query them to pick behaviour (charge harder,
# flee, ignore, etc.). Deterministic: derived from board state + actor memory.

def anger_of(actor) -> float:
    return getattr(actor, "_anger", 0.0)


def fear_of(actor) -> float:
    return getattr(actor, "_fear", 0.0)


def apply_trigger(game, actor, trigger: str, amount: float = 0.3):
    """Modify a creature's emotion state from a named trigger.
    Triggers: hurt, friend_died, fire_near, sound_heard, kin_hurt, weak_foe_seen."""
    trig = {
        "hurt": ("_anger", 0.3),
        "friend_died": ("_anger", 0.5),
        "fire_near": ("_fear", 0.2),
        "sound_heard": ("_anger", 0.15),
        "kin_hurt": ("_anger", 0.4),
        "weak_foe_seen": ("_anger", 0.25),
        "player_close": ("_anger", 0.2),
    }.get(trigger)
    if trig is None:
        return
    attr, base = trig
    cur = getattr(actor, attr, 0.0)
    setattr(actor, attr, min(1.0, cur + base * amount))


def decay_emotions(actor):
    """Call each turn: emotions drift toward baseline."""
    for attr in ("_anger", "_fear"):
        v = getattr(actor, attr, 0.0)
        if v > 0.01:
            setattr(actor, attr, max(0.0, v - 0.05))


def is_enraged(actor) -> bool:
    return anger_of(actor) > 0.6


def is_fearful(actor) -> bool:
    return fear_of(actor) > 0.5
