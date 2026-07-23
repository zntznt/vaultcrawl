<!-- Status: Valid (pre-Berlin, creature domain) | Written: 2026-06-29 | Berlin-audited 2026-07-23: describes NPC/enemy systems, no player-class locks -->
# Mind contract — deliberate planning + memory-driven behaviour

Brains so far are *reactive* (one step from current perception). This layer adds creatures
that **remember** and **plan**. Read `BRAINS_SPEC.md` (the Brain interface + `sense.py`
affordances) and `runtime/memory.py` first. Work in `/mnt/workspace/output/vaultcrawl`
(cd every bash; cwd does NOT persist). Pure stdlib, deterministic.

A brain still implements `decide(game, actor) -> (dx, dy)` and registers by tier name. The
engine runs `enemies_act` → `brain.decide`; if it returns `(0,0)` and a `senses` system is
present, the engine investigates a sensed lead. The LIVE game also registers a `MemorySystem`.

## Memory API (`runtime/memory.py`)

```python
from runtime.memory import mem, recalled_spot, alert_of, fears
```
- `recalled_spot(game, actor) -> (x,y) | None` — best-confidence last-known location of a
  foe this creature has seen, or None once the belief fades (~18 turns). Use it to SEARCH.
- `alert_of(actor) -> float` in [0,1] — grudge/arousal; rises when hurt or on sighting,
  decays each turn. Use it to search harder / commit longer.
- `fears(actor, element) -> bool` — True once an element (e.g. `"corrosive"`, `"flammable"`,
  `"charged"`) has hurt this creature enough times. Use it to refuse that hazard.
- `mem(actor) -> Memory` (`.beliefs`, `.alert`, `.feared`, `.searched`) for finer control.

**Memory is opt-in.** It is populated by `MemorySystem` (the live game + your tests register
it). With no `MemorySystem`, `recalled_spot` is None / `alert_of` is 0 / `fears` is False, so
every brain below MUST degrade gracefully to reactive behaviour.

## sense.py affordances (recap)
`nearest_hostile(game,a)->(t,d)` (perception-limited when senses present), `step_toward(game,a,x,y,safe=True)`,
`step_away`, `lure_step(game,a,target)->dir|None`, `danger_tiles(game)`, `is_dangerous(game,x,y)`,
`element_at(game,x,y)`, `adjacent(ax,ay,bx,by)`, `Brain`, `register_brain`. Attack an adjacent
foe by returning `((t.x>a.x)-(t.x<a.x),(t.y>a.y)-(t.y<a.y))`.

## Agent A — `runtime/planner.py` (+ `tests/test_planner.py`)

**`MastermindBrain`** (`name="mastermind"`) — a DELIBERATE agent for bosses / tier-4+: it
forms a multi-step **plan** toward a goal, executes one step per turn, monitors it, and
**replans** when the plan is invalid or a better opening appears. Keep a `self.plan` (a list
of waypoint tiles / tagged steps) and a `self.goal`; expose them so a test can inspect them.
Plan kinds (pick by situation, deterministic):
1. **Lure-combo** — if a hazard tile sits near the perceived foe, plan a route to a *bait*
   tile (a safe tile positioned so the foe's chase crosses the hazard), THEN kite via
   `lure_step` until the foe is on the hazard. This is a genuine multi-turn setup, not a
   one-step reaction.
2. **Search** — no perceived foe but `recalled_spot` is set: plan a path to that spot, then
   probe a couple of adjacent tiles; clear the plan (give up) once `recalled_spot` is None.
3. **Approach/engage** — perceived foe, no usable hazard: safe-path toward it; attack when adjacent.
Replan when: `self.plan` is empty, the next waypoint is blocked, the foe has moved far from
the plan's assumption, or a lure opportunity newly exists. Avoid `fears(actor, …)` elements in
your own pathing. Degrade to a tactician-style reaction if memory/senses are absent.
*(Bonus, optional: also register `"strategist"` — a deliberate PLAYER brain that plans to lead
a group of foes onto a hazard.)*

`tests/test_planner.py`: register `[SenseField(), ReactionSystem(), MemorySystem(), …]` on a
real Game; stage a foe + a hazard so the mastermind builds a **multi-step** plan
(`len(brain.plan) > 1`) and, executed over turns, leads the foe onto the hazard (it takes
environmental damage / ends on a hazard tile). Then invalidate the setup (move the foe or
clear the hazard) and assert the plan **changes** (replanning), not blindly continues. Print `OK`.

## Agent B — `runtime/instincts.py` (+ `tests/test_instincts.py`)

Memory-driven REACTIVE tiers:
- **`TrackerBrain`** (`name="tracker"`) — for faction hunters. Perceived foe → engage. Else,
  if `recalled_spot` → move there and SEARCH (probe nearby tiles, remembering `mem(a).searched`
  so it doesn't loop); GIVE UP (idle / wander) when `recalled_spot` becomes None. While
  `alert_of` is high, search more persistently. The point: it doesn't instantly forget you —
  it hunts your last-known and quits realistically.
- **`WaryBrain`** (`name="wary"`) — for tier-3 monsters. Like a survivor, but **refuses to
  step onto an element it `fears`** (learned aversion) even when cornered, routing around it;
  flees when low HP; when `alert_of` is high it commits harder (will brave a *non-feared*
  hazard to reach you). Demonstrates learned aversion: a wary creature burned by acid twice
  will not path through acid.

`tests/test_instincts.py`: with `MemorySystem` + `SenseField` + `ReactionSystem` registered,
assert: a Tracker with a `recalled_spot` (seed a belief via the MemorySystem seeing the foe,
then break LOS) steps toward the last-known spot and later idles when it fades; a Wary brain,
after `mem(a).hurt("corrosive")` twice (or staged hp-drops on acid), returns a step that
does NOT enter an acid tile it would otherwise cross. Print `OK`.

## Agent C — `runtime/mind_scenario.py`

Narrated, deterministic showcase (model on `runtime/scenario.py`). `import runtime.planner,
runtime.instincts` at top to register tiers. Build fresh `Game(..., systems=[SenseField(),
ReactionSystem(), MemorySystem()])` per piece, stage state, run REAL hooks, judge from live
state with ✓/✗. Demonstrate:
1. **Search & give up** — a tracker sees the player, the player breaks LOS and leaves; the
   tracker heads to the last-known spot, searches, then gives up after the belief fades.
2. **Learned aversion** — a wary creature burned by acid twice now refuses to path through
   acid to reach the player (compare to a naive creature that walks through).
3. **Grudge** — taking damage raises `alert_of`; show it rising then decaying over turns.
4. **Deliberate combo** — a mastermind builds a multi-step plan (`len(plan)>1`) and, over
   several turns, lures a foe onto a hazard (foe takes environmental damage) — print the plan.
5. **Replanning** — invalidate a mastermind's plan mid-execution; show the plan changes.
6. **Memory is per-entity** — two creatures end with different memories (one fears acid / one
   doesn't; one remembers the player / one never saw it).

End with OVERALL PASS only if all ✓; exit 0. Report the transcript + any mismatch. Mark your
task in_progress at start; do NOT mark completed (the lead finalizes).

Report (all agents): tiers registered, memory/sense calls used, determinism notes, integrator notes.
