"""Deliberate planning brains — minds that scheme over several turns.

Every other brain on the ladder is *reactive*: it reads the current instant and returns
one step. The agents here are **deliberate** — they form a multi-step ``plan`` toward a
``goal``, execute one waypoint per turn, monitor the plan, and **replan** when it is no
longer valid or a better opening appears. The flagship is :class:`MastermindBrain`, the
capability tier for bosses / tier-4+ foes; :class:`StrategistBrain` is the optional
player-side counterpart that herds a foe onto a hazard.

Plan representation (inspectable via ``self.plan`` / ``self.goal``):

* a **move waypoint** is a bare ``(x, y)`` tile (ints) — "walk here next";
* a **tagged step** is a tuple whose first element is a string —
  ``("kite", hazard)``, ``("engage",)``, ``("probe", tile)`` — "do this manoeuvre".

``self.goal`` is ``("lure", hazard) | ("engage", foe_id) | ("search", spot) | None``.

Three plan kinds, chosen deterministically by the situation:

1. **Lure-combo** — a hazard sits near the perceived foe: route to a *bait* tile on the
   far side of the hazard (so the foe's greedy chase crosses it), then ``("kite", H)`` via
   :func:`lure_step` until the foe stands on the hazard. A genuine multi-turn setup.
2. **Search** — no perceived foe but ``recalled_spot`` is set: path to the last-known
   spot, probe a couple of adjacent tiles, then give up once the belief fades to None.
3. **Approach / engage** — a perceived foe with no usable hazard: safe-path toward it and
   bump-attack when adjacent.

Everything reads the world only through the None-guarded ``sense``/``memory`` toolkits, so
with no ``SenseField``/``MemorySystem`` registered the planner still works (omniscient
targeting, no beliefs) and falls back to a tactician-style reaction when it cannot form a
plan. Pure stdlib, deterministic: no ``random`` and no clock — given identical state the
same step comes out every time.

INTEGRATOR NOTE: importing this module registers the ``"mastermind"`` and ``"strategist"``
tiers. The lead wires them in via ``sense.brain_for`` — boss / tier-4+ monsters should map
to ``"mastermind"`` (today they resolve to ``"tactician"``; adding a ``"mastermind"`` rung
above it, with ``_FALLBACK["mastermind"] = "tactician"``, upgrades them without breaking the
fallback ladder when this module is not loaded).
"""
from __future__ import annotations

from collections import deque

from runtime.sense import (
    Brain, register_brain,
    nearest_hostile, is_dangerous, danger_tiles, lure_step,
    step_toward, step_away, adjacent, element_at, greedy_dir, attack_dir,
)
from runtime.memory import recalled_spot, alert_of, fears, mem

WAIT = (0, 0)
_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))

_LURE_RADIUS = 6     # a hazard counts as "near" the foe within this Chebyshev range
_DRIFT = 3           # foe wandered this far from the plan's assumption -> replan
_BAIT_REACH = 3      # how far past the hazard to look for a bait tile (far -> near)


# --------------------------------------------------------------------------- #
# small deterministic helpers
# --------------------------------------------------------------------------- #

def _sign(a, b):
    return (b > a) - (b < a)


def _cheb(ax, ay, bx, by):
    return max(abs(ax - bx), abs(ay - by))


def _walkable_for(game, actor, x, y, avoid):
    """A tile `actor` may legally stand on while planning: in bounds, not a wall, not
    occupied by another actor or the player, and not in the `avoid` set."""
    lvl = getattr(game, "level", None)
    if lvl is None or not lvl.walkable(x, y):
        return False
    if (x, y) in avoid:
        return False
    player = getattr(game, "player", None)
    if player is not None and (player.x, player.y) == (x, y) and actor is not player:
        return False
    occ = game.actor_at(x, y) if hasattr(game, "actor_at") else None
    return occ is None or occ is actor


def _bfs_path(game, actor, goal, avoid):
    """Full shortest-path tile list from `actor` to `goal` (excluding the start),
    avoiding `avoid`, or None if unreachable. Deterministic (fixed neighbour order)."""
    start = (actor.x, actor.y)
    goal = (int(goal[0]), int(goal[1]))
    if start == goal:
        return []
    prev = {start: None}
    q = deque([start])
    found = False
    while q:
        cur = q.popleft()
        if cur == goal:
            found = True
            break
        cx, cy = cur
        for dx, dy in _ORTH:
            nxt = (cx + dx, cy + dy)
            if nxt in prev or not _walkable_for(game, actor, nxt[0], nxt[1], avoid):
                continue
            prev[nxt] = cur
            q.append(nxt)
    if not found:
        return None
    path = []
    cur = goal
    while cur != start:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path


def _avoid_tiles(game, actor):
    """Tiles the planner refuses to route through: every danger tile, plus any tile whose
    element this creature has *learned to fear* (so a foe that fears acid routes around
    acid even when it is not strictly lethal)."""
    avoid = set(danger_tiles(game))
    r = game.system("reactions") if hasattr(game, "system") else None
    props = getattr(r, "props", None) if r is not None else None
    if props:
        for (x, y), kinds in props.items():
            for k in kinds:
                if fears(actor, k):
                    avoid.add((x, y))
                    break
    return avoid


# --------------------------------------------------------------------------- #
# Mastermind — the deliberate schemer (bosses / tier-4+ foes)
# --------------------------------------------------------------------------- #

class MastermindBrain(Brain):
    """Forms a multi-step plan toward a goal, executes one step per turn, and replans when
    the plan goes stale or a better opening appears. `self.plan` and `self.goal` are kept
    inspectable for tests/debuggers."""
    name = "mastermind"

    def __init__(self):
        self.plan = []
        self.goal = None
        self._hazard = None        # the hazard tile a lure plan is built around
        self._bait = None          # the bait tile a lure plan routes to
        self._assume_foe = None    # foe position the current plan assumed

    # ---- perception wrapper (None-safe) ----
    def _foe(self, game, actor):
        try:
            t, d = nearest_hostile(game, actor)
            return t, d
        except Exception:
            return None, None

    @staticmethod
    def _is_move(step):
        return (isinstance(step, tuple) and len(step) == 2
                and isinstance(step[0], int) and isinstance(step[1], int))

    def _tile_open(self, game, actor, x, y):
        return _walkable_for(game, actor, x, y, frozenset())

    # ---- the decision loop ----
    def decide(self, game, actor):
        try:
            if not self.plan or not self._valid(game, actor):
                self.replan(game, actor)
            # consume any move waypoints already standing on
            while self.plan and self._is_move(self.plan[0]) and \
                    (actor.x, actor.y) == self.plan[0]:
                self.plan.pop(0)
            if not self.plan:
                self.replan(game, actor)
            if not self.plan:
                return self._react(game, actor)

            step = self.plan[0]
            if self._is_move(step):
                d = self._move_step(game, actor, step[0], step[1])
                if d == WAIT:                  # waypoint unreachable -> the plan is stale
                    self.replan(game, actor)
                    return self._react(game, actor)
                return d
            return self._exec_tag(game, actor, step)
        except Exception:
            return WAIT

    # ---- plan validity (the replan triggers) ----
    def _valid(self, game, actor):
        goal = self.goal
        if not goal:
            return False
        kind = goal[0]
        if kind == "lure":
            H = self._hazard
            if H is None or not is_dangerous(game, *H):
                return False                    # the hazard was cleared / quenched
            t, _ = self._foe(game, actor)
            if t is None:
                return False                    # lost the foe entirely
            if self._assume_foe is not None:
                allow = _DRIFT + (2 if alert_of(actor) >= 0.5 else 0)
                near_assume = _cheb(t.x, t.y, *self._assume_foe) <= allow
                near_haz = is_dangerous(game, t.x, t.y) or _cheb(t.x, t.y, *H) <= 1
                if not (near_assume or near_haz):
                    return False                # foe bolted off the trap line
            if self.plan and self._is_move(self.plan[0]):
                wx, wy = self.plan[0]
                if not self._tile_open(game, actor, wx, wy):
                    return False                # the next waypoint got blocked/occupied
            return True
        if kind == "engage":
            t, _ = self._foe(game, actor)
            return t is not None
        if kind == "search":
            return recalled_spot(game, actor) is not None
        return False

    # ---- replanning: choose a plan kind by situation ----
    def replan(self, game, actor):
        self.plan = []
        self.goal = None
        self._hazard = None
        self._bait = None
        self._assume_foe = None

        t, _ = self._foe(game, actor)
        if t is not None:
            if self._plan_lure(game, actor, t):     # 1) lure-combo if a hazard is usable
                return
            self.goal = ("engage", id(t))           # 3) otherwise just engage
            self._assume_foe = (t.x, t.y)
            self.plan = [("engage",)]
            return

        spot = recalled_spot(game, actor)            # 2) hunt a remembered sighting
        if spot is not None:
            self._plan_search(game, actor, spot)
            return
        # nothing perceived and nothing remembered -> empty plan (idle)

    # ---- plan kind 1: lure-combo ----
    def _plan_lure(self, game, actor, foe):
        avoid = _avoid_tiles(game, actor)
        hazards = [h for h in danger_tiles(game)
                   if _cheb(foe.x, foe.y, h[0], h[1]) <= _LURE_RADIUS
                   and (h[0], h[1]) != (foe.x, foe.y)]
        hazards.sort(key=lambda h: (_cheb(foe.x, foe.y, *h), h))   # nearest, then coord
        for H in hazards:
            bait = self._bait_for(game, actor, foe, H, avoid)
            if bait is None:
                continue
            path = _bfs_path(game, actor, bait, avoid)
            if path is None:
                continue
            self.plan = list(path) + [("kite", H)]
            self.goal = ("lure", H)
            self._hazard = H
            self._bait = bait
            self._assume_foe = (foe.x, foe.y)
            return True
        return False

    def _bait_for(self, game, actor, foe, H, avoid):
        """A safe tile on the far side of `H` from the foe: standing here makes the foe's
        greedy chase step onto the hazard. Tries farther tiles first so the route — and
        therefore the plan — is a genuine multi-turn setup rather than a one-step nudge."""
        hx, hy = H
        dx, dy = _sign(foe.x, hx), _sign(foe.y, hy)
        if dx == 0 and dy == 0:
            return None
        for k in range(_BAIT_REACH, 0, -1):
            bx, by = hx + dx * k, hy + dy * k
            if (bx, by) == (foe.x, foe.y):
                continue
            if not _walkable_for(game, actor, bx, by, avoid):
                continue
            # the foe's greedy chase toward the bait must head into the hazard
            gx, gy = greedy_dir(foe.x, foe.y, bx, by)
            if (foe.x + gx, foe.y + gy) == (hx, hy) or _cheb(foe.x + gx, foe.y + gy, hx, hy) < _cheb(foe.x, foe.y, hx, hy):
                return (bx, by)
        return None

    # ---- plan kind 2: search a remembered spot ----
    def _plan_search(self, game, actor, spot):
        spot = (int(spot[0]), int(spot[1]))
        avoid = _avoid_tiles(game, actor)
        path = _bfs_path(game, actor, spot, avoid) or []
        searched = getattr(mem(actor), "searched", set())
        probes = []
        budget = 3 if alert_of(actor) >= 0.5 else 2   # an aroused hunter probes harder
        for dx, dy in _ORTH:
            px, py = spot[0] + dx, spot[1] + dy
            if self._tile_open(game, actor, px, py) and (px, py) not in searched:
                probes.append(("probe", (px, py)))
            if len(probes) >= budget:
                break
        self.plan = list(path) + probes
        self.goal = ("search", spot)
        self._assume_foe = spot

    # ---- step executors ----
    def _move_step(self, game, actor, gx, gy):
        path = _bfs_path(game, actor, (gx, gy), _avoid_tiles(game, actor))
        if path:
            nx, ny = path[0]
            return (nx - actor.x, ny - actor.y)
        return step_toward(game, actor, gx, gy, safe=True)   # fall back: ignore fear-only

    def _exec_tag(self, game, actor, step):
        tag = step[0]
        if tag == "kite":
            return self._exec_kite(game, actor, step[1])
        if tag == "engage":
            return self._exec_engage(game, actor)
        if tag == "probe":
            return self._exec_probe(game, actor, step[1])
        return self._react(game, actor)

    def _exec_kite(self, game, actor, H):
        t, d = self._foe(game, actor)
        if t is None:
            self.plan = []
            return self._react(game, actor)
        # the trap sprang: the foe is on a hazard -> close in for the kill while it burns
        if is_dangerous(game, t.x, t.y):
            if d is not None and d <= 1:
                return attack_dir(actor, t)
            return self._move_step(game, actor, t.x, t.y)
        # precise kite: a step that lands the foe's next greedy chase on a hazard
        lure = lure_step(game, actor, t)
        if lure is not None:
            return lure
        # foe not yet adjacent to the hazard -> lead it along the trap line
        led = step_away(game, actor, t.x, t.y, safe=True)
        if led != WAIT:
            return led
        if d is not None and d <= 1:
            return attack_dir(actor, t)
        return self._move_step(game, actor, t.x, t.y)

    def _exec_engage(self, game, actor):
        t, d = self._foe(game, actor)
        if t is None:
            self.plan = []
            return self._react(game, actor)
        if d is not None and d <= 1:
            return attack_dir(actor, t)
        lure = lure_step(game, actor, t)       # a new opening may appear mid-approach
        if lure is not None:
            return lure
        return self._move_step(game, actor, t.x, t.y)

    def _exec_probe(self, game, actor, tile):
        t, _ = self._foe(game, actor)
        if t is not None:                       # spotted the quarry -> drop search, fight
            self.replan(game, actor)
            return self._react(game, actor)
        mem(actor).searched.add((actor.x, actor.y))
        if (actor.x, actor.y) == tuple(tile):
            self.plan.pop(0)                    # probed here; move to the next lead
            return self.decide(game, actor)
        return self._move_step(game, actor, tile[0], tile[1])

    # ---- degraded fallback: a tactician-style reaction (no plan / no memory+senses) ----
    def _react(self, game, actor):
        t, d = self._foe(game, actor)
        if t is None or d is None:
            return WAIT
        if d <= 1 and is_dangerous(game, t.x, t.y):
            return attack_dir(actor, t)
        lure = lure_step(game, actor, t)
        if lure is not None:
            return lure
        if d <= 1:
            return attack_dir(actor, t)
        return self._move_step(game, actor, t.x, t.y)


# --------------------------------------------------------------------------- #
# Strategist — the deliberate PLAYER brain (optional bonus)
# --------------------------------------------------------------------------- #

class StrategistBrain(MastermindBrain):
    """A deliberate player: the same plan-and-replan engine (its hostiles are the monsters),
    but it bails to the stairs when badly wounded rather than pressing a doomed kite."""
    name = "strategist"

    def decide(self, game, actor):
        try:
            mx = getattr(actor, "max_hp", 0) or 0
            if mx and actor.hp * 100 < mx * 30:
                st = getattr(getattr(game, "level", None), "stairs", None)
                if st:
                    s = step_toward(game, actor, st[0], st[1], safe=True)
                    if s != WAIT:
                        self.plan, self.goal = [], ("flee", st)
                        return s
            return super().decide(game, actor)
        except Exception:
            return WAIT


register_brain("mastermind", MastermindBrain)
register_brain("strategist", StrategistBrain)
