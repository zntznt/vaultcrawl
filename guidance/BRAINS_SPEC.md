<!-- Status: Legacy (pre-Berlin) | Written: 2026-06-29 | Berlin compliance not yet applied to this domain -->
# Brains contract — interaction-aware agents with a capability ladder

Entities now act through a **brain**: `Brain.decide(game, actor) -> (dx, dy)` (a step in
{-1,0,1}; stepping into a hostile is a bump attack; `(0,0)` waits). The engine
(`game.enemies_act`) calls each actor's brain; the player's brain drives the auto-descent.
The point: a spectrum of intelligence, so a tier-1 grunt blindly charges while a boss or a
hunter **lures you onto acid**. You implement tiers on that ladder.

Work in `/mnt/workspace/output/vaultcrawl` (cd every bash; cwd does NOT persist). Pure
stdlib. **Deterministic** (no `random`/clock; derive any tie-break from `game.seed`+coords).

## The perception toolkit (`runtime/sense.py`) — import and use these

```python
from runtime.sense import (Brain, register_brain,
    hostiles, nearest_hostile, nearest, danger_tiles, is_dangerous, element_at,
    points_of_interest, bfs_step, step_toward, greedy_step_toward, step_away,
    lure_step, adjacent)
```
- `nearest_hostile(game, actor) -> (target|None, dist|None)` — respects allegiance (monster↔player↔wild).
- `danger_tiles(game) -> set` / `is_dangerous(game,x,y) -> bool` — union of reactions hazards + armed traps (None-guarded).
- `element_at(game,x,y) -> str|None` — the tile's element word.
- `step_toward(game, actor, tx, ty, safe=True) -> (dx,dy)` — BFS step; `safe=True` avoids danger tiles (falls back to reckless if boxed in).
- `greedy_step_toward(game, actor, tx, ty)` — the legacy 1-axis chaser (no hazard awareness).
- `step_away(game, actor, fx, fy, safe=True)` — flee step, prefers safe tiles.
- `lure_step(game, actor, target) -> (dx,dy)|None` — **the kite primitive**: a safe step for
  `actor` such that `target`'s greedy chase next lands it on a danger tile. None if impossible.
- `points_of_interest(game) -> list[(x,y)]` — sigils/lore the player should grab.
- To **attack** an adjacent target, return `((t.x>a.x)-(t.x<a.x), (t.y>a.y)-(t.y<a.y))`.

A brain MUST tolerate missing systems (everything above is already None-guarded) and never
crash; when unsure, return `(0,0)`.

## Registration

At import time, register each tier by the name the policy expects:
```python
class SurvivorBrain(Brain):
    name = "survivor"
    def decide(self, game, actor): ...
register_brain("survivor", SurvivorBrain)
```
The engine's `brain_for` policy (in sense.py) maps entities → tier names:
monster tier1→`hunter`, tier2→`survivor`, tier3→`opportunist`, tier4+/boss/hunter→`tactician`;
wild grazer→`forager`, scavenger→`scavenger`, predator→`opportunist`; player→`exploiter`.
Unregistered names fall back down the ladder, so partial loads still run.

## You OWN one file

- **Agent A** owns `runtime/brains.py` + `tests/test_brains.py`: implement & register
  `survivor`, `opportunist`, `forager`, `scavenger`.
- **Agent B** owns `runtime/tactics.py` + `tests/test_tactics.py`: implement & register
  `tactician`, `exploiter`.
- **Agent C** owns `runtime/brain_scenario.py`: the showcase (see its own prompt).

Do NOT edit any other file (not sense.py, game.py, or each other's). `tactics.py` may
`from runtime.sense import Brain, ...` (and may `import runtime.brains` if it wants to
subclass a tier, but it's not required).

## Tier behaviors (implement this logic; keep it crisp & deterministic)

**survivor** — chases but preserves itself:
1. `t,d = nearest_hostile`; if none → `(0,0)`.
2. low HP (`actor.hp*100 < actor.max_hp*35`) → `step_away(game, actor, t.x, t.y, safe=True)`.
3. adjacent (`d<=1`) → attack dir.
4. else → `step_toward(game, actor, t.x, t.y, safe=True)` (never volunteers to stand in fire/acid).

**opportunist** — survivor + lets terrain do the work:
- low HP flee as survivor.
- among adjacent hostiles, if one is standing on a danger tile (`is_dangerous`), attack THAT one (it's already dying).
- else behave as survivor (safe approach; attack if adjacent).

**forager** (grazers) — skittish prey: if a hostile is within sight (~5), `step_away` safe;
else `(0,0)` (the fauna system handles grazing). Never attacks unless cornered (optional).

**scavenger** — same skittish flee from hostiles; else `(0,0)` (fauna drives it to corpses).

**tactician** — the schemer (tougher foes, hunters, bosses):
1. `t,d = nearest_hostile`; none → `(0,0)`.
2. low HP → flee safe.
3. if `d<=1` and `is_dangerous(t.x,t.y)` → attack (finish a foe the terrain is already killing).
4. `lure = lure_step(game, actor, t)`; if not None → return it (**kite the target onto a hazard**).
5. if `d<=1` → attack.
6. else → `step_toward` safe.

**exploiter** — the player brain (hostiles = monsters):
1. low HP (`<40%`) → `step_toward(game, actor, *game.level.stairs, safe=True)` (retreat to the exit, dodging hazards).
2. if an adjacent hostile is on a danger tile → attack it.
3. if a hostile is within `d<=2`, try `lure_step` → lead it onto a hazard.
4. if adjacent hostile → attack.
5. else pursue loot: nearest of `points_of_interest(game)` + item tiles via `step_toward` safe.
6. else → `step_toward(game, actor, *game.level.stairs, safe=True)` (the play loop descends when you reach the stairs).

## Tests

Register your tiers, build a real `Game(load_manifest("examples/world.json"), systems=[...])`,
and assert the BEHAVIOR DIFFERENCE that defines each tier — ideally against the legacy
`HunterBrain` as a control. Use `make_enemy`/`make_critter`/`make_player`, place actors,
set `reactions.props` to stage hazards (register a `ReactionSystem`), assign
`actor.brain = SurvivorBrain()` etc., and drive `game.enemies_act()` (or call
`brain.decide` directly). Examples:
- survivor vs hunter: with an acid tile on the straight-line path, the hunter steps onto it
  (or toward it) while the survivor's chosen step is NOT a danger tile.
- opportunist: given two adjacent hostiles, one on acid, it attacks the one on acid.
- tactician: with the player adjacent to a hazard, `decide` returns a `lure_step` (the
  player's greedy chase would then land on danger); or it attacks a hostile already on danger.
- exploiter: with a sigil/POI on the floor and no adjacent threat, it steps toward the POI;
  at low HP it steps toward the stairs.
- forager: a grazer flees an adjacent monster (moves away), doesn't charge it.

Run `cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_<file>` → print `OK`, exit 0, deterministic.

Report: tiers registered, the sense helpers you used, any tie-break determinism notes, and
integrator notes (your module must be imported for its tiers to register — the lead imports
`brains`/`tactics` in play.py).
