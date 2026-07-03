"""Creature special-action library for the quality (elite) system.

Each action is `fn(game, actor) -> bool` (True iff it actually did something). They are
registered into `quality.SPECIAL_ACTIONS` at import time; the `QualitySystem` then drives
them on a cadence for quality (elite) creatures via `on_player_act`.

INVARIANT SAFETY -- the property the integration test enforces:
  * No actor (existing or freshly spawned) is ever placed on a non-walkable tile.
  * No actor is ever placed on a tile already occupied by another actor or the player.
  * The player is never moved or overwritten.
All placement flows through `_free_tiles`, which derives its candidate set from
`dungeon.free_floor_tiles` (FLOOR tiles only -- hence walkable by construction) minus the
full occupancy set (every actor in `game.actors` plus the player). If that set is empty
the action declines (`return False`) -- nothing is placed.

DETERMINISM -- no clock, no global rng. Every choice is a pure function of board state:
candidate tiles are ranked by a fully-ordered key (distance, then y, then x), so two
identically-seeded games make byte-identical decisions.

CAPS -- every stat buff is bounded so an elite can't snowball: enrage/shield/rally each
cap their cumulative bonus at +3; split only fires above an HP threshold and its offspring
are flagged so they can never split again (no chain explosion); summon spawns a single
tier-1 body with no actions of its own.
"""
from __future__ import annotations

from . import quality
from .dungeon import free_floor_tiles
from .entities import Actor, make_critter, make_enemy

# ---- tunable caps (kept deliberately modest) ------------------------------- #
ENRAGE_CAP = 3        # max cumulative +atk from enrage
SHIELD_CAP = 3        # max cumulative +defense from shield (then it self-heals)
SHIELD_HEAL = 2       # self-heal once defense is capped
RALLY_CAP = 3         # max cumulative +atk an ally can receive from rally
SPIT_RANGE = 5        # max orthogonal range for a spit
SPIT_DAMAGE = 3       # base spit damage (reduced by the target's defense, min 1)
SPLIT_MIN_HP = 6      # an actor must have at least this much hp to split
SUMMON_HP = 4         # hp of a summoned wild whelp


# --------------------------------------------------------------------------- #
# Helpers -- all placement safety lives here.
# --------------------------------------------------------------------------- #

def _player(game):
    """The player, but only while the run is live; else None (so actions decline)."""
    p = getattr(game, "player", None)
    if p is None or not getattr(game, "alive", True):
        return None
    return p


def _occupied(game) -> set:
    """Every tile currently claimed by an actor or the player -- never spawn here."""
    occ = {(a.x, a.y) for a in getattr(game, "actors", [])}
    p = getattr(game, "player", None)
    if p is not None:
        occ.add((p.x, p.y))
    return occ


def _free_tiles(game) -> list:
    """Walkable, unoccupied FLOOR tiles. Empty list => caller must decline."""
    level = getattr(game, "level", None)
    if level is None:
        return []
    return free_floor_tiles(level, _occupied(game))


def _nearest(tiles, x, y):
    """Pick the tile closest to (x, y); deterministic tie-break by (dist2, y, x)."""
    return min(tiles, key=lambda t: ((t[0] - x) ** 2 + (t[1] - y) ** 2, t[1], t[0]))


def _tame(child: Actor, allegiance: str) -> Actor:
    """Stamp a spawned creature so it can never recursively spawn/act as an elite."""
    child.allegiance = allegiance
    child.quality = 0
    child._special_actions = []
    child._qualified = True       # the QualitySystem must not re-roll it into an elite
    return child


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #

def act_enrage(game, actor) -> bool:
    """Small, capped attack bump. Repeated use stacks only up to ENRAGE_CAP."""
    stacks = getattr(actor, "_enrage_stacks", 0)
    if stacks >= ENRAGE_CAP:
        return False
    actor._enrage_stacks = stacks + 1
    actor.atk += 1
    return True


def act_shield(game, actor) -> bool:
    """Raise own defense a little (capped at SHIELD_CAP); once capped, small self-heal."""
    bonus = getattr(actor, "_shield_bonus", 0)
    if bonus < SHIELD_CAP:
        actor._shield_bonus = bonus + 1
        actor.defense = getattr(actor, "defense", 0) + 1
        return True
    if actor.hp < actor.max_hp:
        actor.hp = min(actor.max_hp, actor.hp + SHIELD_HEAL)
        return True
    return False


def act_rally(game, actor) -> bool:
    """Buff one adjacent same-allegiance ally's attack (per-ally cap RALLY_CAP)."""
    al = getattr(actor, "allegiance", "monster")
    for a in getattr(game, "actors", []):
        if a is actor or getattr(a, "allegiance", "monster") != al:
            continue
        if max(abs(a.x - actor.x), abs(a.y - actor.y)) != 1:   # must be adjacent
            continue
        stacks = getattr(a, "_rally_stacks", 0)
        if stacks >= RALLY_CAP:
            continue
        a._rally_stacks = stacks + 1
        a.atk += 1
        return True
    return False


def act_spit(game, actor) -> bool:
    """Ranged attack: if the player is on a clear orthogonal line within SPIT_RANGE,
    deal a small amount of damage. Placement-free, so trivially invariant-safe."""
    p = _player(game)
    if p is None:
        return False
    dx, dy = p.x - actor.x, p.y - actor.y
    if (dx != 0 and dy != 0) or (dx == 0 and dy == 0):
        return False                                   # not a straight orthogonal line
    dist = abs(dx) + abs(dy)
    if dist > SPIT_RANGE:
        return False
    sx = (dx > 0) - (dx < 0)
    sy = (dy > 0) - (dy < 0)
    cx, cy = actor.x + sx, actor.y + sy
    while (cx, cy) != (p.x, p.y):                      # path must be clear
        if not game.level.walkable(cx, cy) or game.actor_at(cx, cy) is not None:
            return False
        cx += sx
        cy += sy
    dmg = max(1, SPIT_DAMAGE - getattr(p, "defense", 0))
    p.hp -= dmg
    if p.hp <= 0:                                      # mirror engine death semantics
        game.alive = False
    return True


def act_blink(game, actor) -> bool:
    """Teleport the actor to a free, walkable, unoccupied tile strictly nearer the player."""
    p = _player(game)
    if p is None:
        return False
    cur = max(abs(actor.x - p.x), abs(actor.y - p.y))   # current Chebyshev distance
    nearer = [t for t in _free_tiles(game)
              if max(abs(t[0] - p.x), abs(t[1] - p.y)) < cur]
    if not nearer:
        return False
    tx, ty = min(nearer, key=lambda t: (max(abs(t[0] - p.x), abs(t[1] - p.y)),
                                        (t[0] - p.x) ** 2 + (t[1] - p.y) ** 2, t[1], t[0]))
    actor.x, actor.y = tx, ty
    return True


def act_summon(game, actor) -> bool:
    """Spawn ONE weak ally of the SAME allegiance on a free tile near the actor."""
    tiles = _free_tiles(game)
    if not tiles:
        return False
    tx, ty = _nearest(tiles, actor.x, actor.y)
    al = getattr(actor, "allegiance", "monster")
    src = getattr(actor, "source", "")
    if al == "wild":
        ally = make_critter(f"{actor.name} whelp", getattr(actor, "glyph", "w"),
                            tx, ty, hp=SUMMON_HP, atk=1, defense=0, source=src)
    else:
        ally = make_enemy({"tier": 1, "archetype": "swarm",
                           "name": f"{actor.name} thrall", "sourceNoteId": src}, tx, ty)
    _tame(ally, al)
    game.actors.append(ally)
    return True


def act_split(game, actor) -> bool:
    """Spawn a half-HP copy of the actor (same allegiance + glyph) on a free tile.

    Capped two ways: the actor must hold at least SPLIT_MIN_HP, and the offspring is
    flagged `_is_split_spawn` (with no actions) so it can never split again -- no chain
    explosion. The parent gives up the copied half of its HP but stays alive.
    """
    if getattr(actor, "_is_split_spawn", False):
        return False
    if getattr(actor, "hp", 0) < SPLIT_MIN_HP:
        return False
    tiles = _free_tiles(game)
    if not tiles:
        return False
    tx, ty = _nearest(tiles, actor.x, actor.y)
    half = max(1, actor.hp // 2)
    actor.hp = max(1, actor.hp - half)                 # parent keeps the remainder
    copy = Actor(x=tx, y=ty, glyph=actor.glyph, name=actor.name,
                 hp=half, max_hp=half, atk=actor.atk, defense=getattr(actor, "defense", 0),
                 tier=getattr(actor, "tier", 1), source=getattr(actor, "source", ""),
                 allegiance=getattr(actor, "allegiance", "monster"))
    _tame(copy, copy.allegiance)
    copy._is_split_spawn = True
    game.actors.append(copy)
    return True


# --------------------------------------------------------------------------- #
# Registration (side-effect on import)
# --------------------------------------------------------------------------- #

quality.register_action("enrage", act_enrage)
quality.register_action("shield", act_shield)
quality.register_action("rally", act_rally)
quality.register_action("spit", act_spit)
quality.register_action("blink", act_blink)
quality.register_action("summon", act_summon)
quality.register_action("split", act_split)


# --------------------------------------------------------------------------- #
# Player-cast body verbs -- the same actions, aimed symmetrically.
# --------------------------------------------------------------------------- #

def player_cast(game, name: str) -> bool:
    """Cast one of the controlled body's special actions (Qud mutations: the body
    IS the build). Self-buffs share the elite code path; targeted verbs aim at
    your nearest perceived hostile (who stands where the player stands for
    elites); spawners ally their offspring to you as companions."""
    p = game.player
    if name == "enrage":
        return act_enrage(game, p)
    if name == "shield":
        return act_shield(game, p)
    if name == "rally":
        for a in getattr(game, "actors", []):
            if a.allegiance != "companion":
                continue
            if max(abs(a.x - p.x), abs(a.y - p.y)) != 1:
                continue
            stacks = getattr(a, "_rally_stacks", 0)
            if stacks >= RALLY_CAP:
                continue
            a._rally_stacks = stacks + 1
            a.atk += 1
            game.log(f"You rally {a.name} (+1 ATK).")
            return True
        return False
    if name in ("summon", "split"):
        before = len(game.actors)
        done = (act_summon if name == "summon" else act_split)(game, p)
        for child in game.actors[before:]:
            child.allegiance = "companion"       # your offspring walk with you
            child.faction = getattr(p, "faction", "")
            child.brain = None
            game.log(f"{child.name} takes shape beside you.")
        return done
    from .sense import nearest_hostile
    t, _d = nearest_hostile(game, p)
    if t is None:
        return False
    if name == "blink":
        cur = max(abs(p.x - t.x), abs(p.y - t.y))
        nearer = [c for c in _free_tiles(game)
                  if max(abs(c[0] - t.x), abs(c[1] - t.y)) < cur]
        if not nearer:
            return False
        p.x, p.y = min(nearer, key=lambda c: (max(abs(c[0] - t.x), abs(c[1] - t.y)),
                                              (c[0] - t.x) ** 2 + (c[1] - t.y) ** 2,
                                              c[1], c[0]))
        game.log(f"You blink toward {t.name}.")
        return True
    if name == "spit":
        dx, dy = t.x - p.x, t.y - p.y
        if (dx != 0 and dy != 0) or (dx == 0 and dy == 0) or abs(dx) + abs(dy) > SPIT_RANGE:
            return False
        sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
        cx, cy = p.x + sx, p.y + sy
        while (cx, cy) != (t.x, t.y):
            if not game.level.walkable(cx, cy) or game.actor_at(cx, cy) is not None:
                return False
            cx += sx
            cy += sy
        dmg = max(1, SPIT_DAMAGE - getattr(t, "defense", 0))
        t.hp -= dmg
        game.log(f"You spit at {t.name} for {dmg}.")
        if t.hp <= 0:
            if getattr(t, "is_boss", False) and t.source == game.final_boss_source:
                game.won = True
                game.log("The deepest thought in the vault falls silent. You win.")
            if t.allegiance == "monster":
                game.kills += 1
                game.log(f"You destroy {t.name}.")
                for s in game.systems:
                    s.on_enemy_killed(game, t)
                game.emit("enemy_killed", enemy=t, cause="spit")
            game.kill(t, "spit")
        return True
    return False
