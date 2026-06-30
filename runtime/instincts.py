"""Memory-driven REACTIVE brains — instinct, not deliberation.

Two tiers that sit one notch above the plain reactive ladder by reading the per-entity
`Memory` (`runtime/memory.py`) as well as the perception toolkit (`runtime/sense.py`):

- **`TrackerBrain`** (``name="tracker"``) — a faction hunter that does not forget you the
  instant you slip out of view. It engages a perceived foe, otherwise heads for the
  last-known spot (`recalled_spot`) and *searches* nearby tiles (remembering which it has
  probed so it never loops), and finally **gives up** — returns ``(0, 0)`` — once the
  belief fades. A high `alert_of` makes it search a wider radius and keep pressing.

- **`WaryBrain`** (``name="wary"``) — a tier-3 survivor with *learned aversion*. It flees
  when wounded and closes on a foe like a careful fighter, but it will **never** step onto
  an element it `fears` (e.g. acid once it has been corroded twice), routing around it or
  waiting even when cornered. When `alert_of` is high it commits harder and will brave a
  *non-feared* hazard to reach the foe — but a feared element is refused regardless.

Everything is read through None-guarded APIs, so with no `MemorySystem`/`SenseField`
registered (`recalled_spot` -> None, `alert_of` -> 0, `fears` -> False, omniscient
targeting) both brains collapse cleanly to plain reactive behaviour. No rng, no clock:
given identical state the same step comes out every time.

The engine maps entities to tiers via `sense.brain_for`; importing this module registers
the two tiers so the integrator can route `is_hunter` -> "tracker" and tier-3 -> "wary".
"""
from __future__ import annotations

from runtime.sense import (
    Brain, register_brain,
    nearest_hostile, step_toward, step_away, greedy_step_toward,
    is_dangerous, element_at, adjacent,
)
from runtime.memory import mem, recalled_spot, alert_of, fears

WAIT = (0, 0)
_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))   # deterministic probe / scan order
_HIGH_ALERT = 0.5      # `alert_of` at/above this == aroused: search wider, commit harder
_FLEE_HP_PCT = 35      # below this fraction of max hp a wary creature breaks off

# A reactions tile exposes a *tile property* word (`element_at` -> "acid"/"fire"/"ice"...),
# but memory/`fears` are keyed by the *region element* word the affinity model uses
# ("corrosive"/"flammable"/"frozen"...). This is the same table reactions.py keeps as
# `_TILEPROP_ELEMENT`; we mirror it here (own-file only) so a feared tile is recognised
# whether memory learned the tile word (live MemorySystem -> element_at) or the region
# word (the spec / tests -> mem.hurt("corrosive")).
_TILEPROP_ELEMENT = {
    "acid": "corrosive",
    "fire": "flammable",
    "ice": "frozen",
    "charged": "charged",
    "wet": "wet",
    "sacred": "sacred",
}


# --------------------------------------------------------------------------- #
# Small deterministic helpers
# --------------------------------------------------------------------------- #

def _attack_dir(a, t):
    """Unit step from `a` toward an adjacent target `t` (a bump attack)."""
    return ((t.x > a.x) - (t.x < a.x), (t.y > a.y) - (t.y < a.y))


def _low_hp(actor, pct):
    mx = getattr(actor, "max_hp", 0) or 0
    hp = getattr(actor, "hp", 0) or 0
    return mx > 0 and hp * 100 < mx * pct


def _cheb(ax, ay, bx, by):
    return max(abs(ax - bx), abs(ay - by))


def _feared_at(game, actor, x, y):
    """True if the element on tile (x, y) is one `actor` has learned to fear.

    `element_at` yields the tile-property word; we check `fears` against both that word
    and its region-element name so the refusal holds no matter which space taught memory.
    """
    el = element_at(game, x, y)
    if not el:
        return False
    if fears(actor, el):
        return True
    region = _TILEPROP_ELEMENT.get(el)
    return bool(region) and fears(actor, region)


def _walkable_step(game, actor, x, y):
    """Can `actor` actually move onto (x, y) this turn (wall / occupant / player guard)?"""
    lvl = getattr(game, "level", None)
    if lvl is None or not lvl.walkable(x, y):
        return False
    if actor is not getattr(game, "player", None) and (x, y) == (game.player.x, game.player.y):
        return False
    return game.actor_at(x, y) is None


# --------------------------------------------------------------------------- #
# Tracker — a faction hunter that remembers and searches
# --------------------------------------------------------------------------- #

class TrackerBrain(Brain):
    """Engage what it perceives; otherwise hunt the last-known spot and search around it,
    giving up only once the belief has faded."""
    name = "tracker"

    def decide(self, game, actor):
        try:
            t, d = nearest_hostile(game, actor)
            if t is not None and d is not None:
                # perceived foe -> engage: bump if adjacent, else close in safely
                if d <= 1:
                    return _attack_dir(actor, t)
                return step_toward(game, actor, t.x, t.y, safe=True)
            spot = recalled_spot(game, actor)
            if spot is None:
                return WAIT                       # belief faded -> give up
            return self._search(game, actor, spot)
        except Exception:
            return WAIT

    def _search(self, game, actor, spot):
        """Move to the last-known spot; once on/near it, probe an unsearched neighbour
        (tracked in `mem(actor).searched` so the hunt never loops)."""
        m = mem(actor)
        radius = 2 if alert_of(actor) >= _HIGH_ALERT else 1   # aroused -> wider sweep
        if _cheb(actor.x, actor.y, spot[0], spot[1]) > radius:
            return step_toward(game, actor, spot[0], spot[1], safe=True)
        # standing on/near the spot with nothing in view: check off the current tile and
        # step onto the first unsearched, reachable neighbour.
        m.searched.add((actor.x, actor.y))
        for dx, dy in _ORTH:
            nx, ny = actor.x + dx, actor.y + dy
            if (nx, ny) in m.searched or not _walkable_step(game, actor, nx, ny):
                continue
            m.searched.add((nx, ny))
            return (dx, dy)
        # neighbourhood exhausted: an aroused hunter keeps pressing toward the spot,
        # a calm one holds (and the engine may then investigate a fresh sensed lead).
        if alert_of(actor) >= _HIGH_ALERT:
            s = step_toward(game, actor, spot[0], spot[1], safe=True)
            if s != WAIT:
                return s
        return WAIT


# --------------------------------------------------------------------------- #
# Wary — a tier-3 survivor with learned aversion
# --------------------------------------------------------------------------- #

class WaryBrain(Brain):
    """A careful fighter that refuses to enter an element it `fears` — even when cornered —
    flees when wounded, and only braves a *non-feared* hazard when its grudge runs hot."""
    name = "wary"

    def decide(self, game, actor):
        try:
            t, d = nearest_hostile(game, actor)
            high = alert_of(actor) >= _HIGH_ALERT
            if _low_hp(actor, _FLEE_HP_PCT):
                return self._flee(game, actor, t)
            if t is None or d is None:
                return WAIT
            if d <= 1:
                return _attack_dir(actor, t)      # a bump attack never enters a new tile
            return self._advance(game, actor, t, high)
        except Exception:
            return WAIT

    def _flee(self, game, actor, t):
        if t is None:
            return WAIT
        s = step_away(game, actor, t.x, t.y, safe=True)
        if s != WAIT and not _feared_at(game, actor, actor.x + s[0], actor.y + s[1]):
            return s
        # safe retreat blocked or would land on a feared tile: take any non-feared step
        # that opens distance, else hold ground (never volunteer onto the feared element).
        best, bd = WAIT, _cheb(actor.x, actor.y, t.x, t.y)
        for dx, dy in _ORTH:
            nx, ny = actor.x + dx, actor.y + dy
            if not _walkable_step(game, actor, nx, ny) or _feared_at(game, actor, nx, ny):
                continue
            dd = _cheb(nx, ny, t.x, t.y)
            if dd > bd:
                best, bd = (dx, dy), dd
        return best

    def _advance(self, game, actor, t, high):
        # Aroused: commit. Charge the straight line, braving a NON-feared hazard if that's
        # the way through — but still never onto a feared element.
        if high:
            charge = greedy_step_toward(game, actor, t.x, t.y)
            if charge != WAIT and not _feared_at(game, actor,
                                                 actor.x + charge[0], actor.y + charge[1]):
                return charge
        # Careful default: a safe path. `step_toward(safe=True)` avoids every hazard when it
        # can and only falls back to a reckless step when boxed in; we accept that step
        # unless it would enter a FEARED element.
        step = step_toward(game, actor, t.x, t.y, safe=True)
        if step != WAIT and not _feared_at(game, actor, actor.x + step[0], actor.y + step[1]):
            return step
        # The natural step crosses a feared element -> route around it, or wait it out.
        return self._detour(game, actor, t, high)

    def _detour(self, game, actor, t, high):
        """A non-feared neighbour that makes progress toward `t`; prefers safe tiles and
        only crosses a non-feared hazard when aroused. WAIT if nothing qualifies."""
        cur = _cheb(actor.x, actor.y, t.x, t.y)
        best = None   # (rank, dir): rank 0 = safe tile, 1 = non-feared hazard
        for dx, dy in _ORTH:
            nx, ny = actor.x + dx, actor.y + dy
            if not _walkable_step(game, actor, nx, ny) or _feared_at(game, actor, nx, ny):
                continue
            danger = is_dangerous(game, nx, ny)
            if danger and not high:
                continue
            if _cheb(nx, ny, t.x, t.y) >= cur:
                continue
            rank = 1 if danger else 0
            if best is None or rank < best[0]:
                best = (rank, (dx, dy))
        return best[1] if best else WAIT


register_brain("tracker", TrackerBrain)
register_brain("wary", WaryBrain)
