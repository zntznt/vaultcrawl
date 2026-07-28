<!-- Status: Current (post-Berlin) | Written: 2026-07-23 -->
# Agent contract — player-agent AI architecture

One brain class (`UniversalBrain`), six profiles, one scoring formula. Every agent
CAN do everything; profile weight biases which actions fire first. Berlin-compliant:
identity is a floor, survival is a ceiling, and turn bonus seeds initial divergence.

**What this covers:** `runtime/agent.py`, `runtime/agent_action.py`,
`runtime/agent_perception.py`, `runtime/agent_eval.py`

## Berlin Interpretation — mandatory compliance

Per the Berlin Interpretation of roguelikes, this architecture MUST NOT introduce
hardcoded differences between agents. The contract is:

- **No class-locked abilities.** Every action (forge, parley, commune, fight, explore,
  becalm, shield, craft_consumable, etc.) must be reachable by every agent given the
  right starting resources. No `if agent_name == "whisper": return parley()` style branches.
- **Differentiation through starting state only.** The six profiles differ in HP, DEF,
  starting matter, pre-slotted sigils, known notes, faction standing, and known recipes —
  never in which actions they can take.
- **Differentiation through preference biases only.** The `PROFILES` dict assigns
  scoring *weights* (higher = preferred) and never scoring *gates* (0 = forbidden).
  A whisper with `fight: -5` CAN still fight — it just won't unless survival demands it.
  An artisan with `forge: 15` forges by choice, not by exclusive access.
- **One universal decide() function.** There is exactly one `decide(self, game, actor)`
  method. No per-agent overrides. No personality-gated code paths. The `_score()` formula
  applies identically to all profiles.
- **All actions scored for all agents.** The priority cascade adds every reachable
  action as a candidate for every agent. Profile weights act as FLOORS via
  `max(profile_weight, state_urgency)` — identity actions are always viable, never
  exclusive.
- **If you add an action, every agent must be able to reach it.** Adding a new verb to
  `AgentAction` or a new candidate to the cascade must not gate it behind agent-specific
  conditions. Use existing resource checks (matter, standing, knowledge, HP) that any
  agent can satisfy.

**Violating any of these is a design regression.** The architecture was rebuilt from
six separate agent files (personality-gated) into one universal tree explicitly to
satisfy Berlin. Do not reintroduce the split.

## What the win rate is for

**There is no target win rate. Do not tune toward one.** This section exists because a 40-60%
band was treated as a standard for most of this project's life while appearing in no spec, and
five constants were moved to chase it on samples that could not tell their arms apart. See
`guidance/PROJECT_ASSESSMENT.md`, "Correcting the record".

The agents are an instrument for showing that the systems are reachable and the decisions are
real. They are **not** a difficulty proxy for a human player, and three facts make that concrete
rather than rhetorical:

- **They do not play the same game.** `Game(sandbox=True)` and the pattern compiler in
  `runtime/arch/` are the default interactive mode. `agent_eval` builds `sandbox=False`
  (`agent_eval.py:100`) and runs classic descent, so the win rate is measured on a level
  generator the default human session never sees.
- **They have no memory across runs.** `decide()` is a per-turn scoring pass over
  `agent_state()`, and `Game.__init__` calls `reset_run_state()`. A person accumulates knowledge
  of a world across deaths; the agent is denied that by construction.
- **They are harness-shaped.** The 500-turn floor abandonment and the anti-stall BFS in
  `run_agent` (`agent_eval.py:126`, `:201`) are properties of the evaluation, not of the game.

So 50% would not mean the game is fairly tuned for a person, and the low twenties does not mean
it is punishing. The number means something in two ways only: compared against its own recorded
history, and read through the conditions below.

### The health checklist

This is the actual contract. Every line is checkable from one `eval_stats.json` at 144 runs or
more. Current readings are the 288-run pass after the graded-name fix, six profiles, on the
corrected telemetry: before it, panic turns were recorded as repeats of the previous decision and
`label_share` was truncated to the top 8 of about 30 before `policy_divergence` was computed
from it, so every figure in this table older than that was drawn from a contaminated
distribution.

| condition | field | limit | current |
|---|---|---|---|
| every profile can win | `agent_stats[a].win_rate` | above 0 for all six | 6 of 6 |
| every route is used | pooled `agent_stats[a].win_paths` | all present | 5 of 5 |
| no route dominates | pooled `win_paths` | top route at most 60% | 44% |
| no verb is broken | `agent_stats[a].emergence.broken_verbs` | empty | empty |
| decisions are contested | `pressure.uncontested_share` | at most 0.05 | 0.000 |
| the decision space is used | `pressure.labels_used` | at least 20 | 23.0 to 29.9 |
| profiles actually differ | `policy_divergence` | every pair above 0.10 | 0.114 to 0.562 |

`diplomacy`, the final warden laying down its arms at parley, fired for the first time in the
run recorded here, which is why the route count is five rather than four.

The first three and the last are Berlin conditions wearing measurement clothes. A profile that
cannot win is class-locked in effect whatever the code says; a route nobody takes is a system
that exists only in the source; six profiles that produce one policy are decorative. The
`policy_divergence` block is already computed and already in the dump.

**A change that breaks one of these is a regression regardless of what it does to the win rate.
A change that moves the win rate while all seven hold is not, by itself, a problem.**

### The aggregate

Report it as wins over runs with a Wilson interval, at 288 runs or more, never as a bare
percentage. Compare it against the history recorded in `PROJECT_ASSESSMENT.md`, not against a
band. The only absolute call is degeneracy: sustained below 10% or above 80% means something is
broken rather than mistuned, because at those extremes the runs stop discriminating between
designs at all.

Current: **63 of 288, 21.9%, [17.5, 27.0]**, against 76 of 288, 26.4% before the graded-name
fix, 77 of 288, 26.7% before the telemetry corrections, and 34 of 144, 23.6% [17.4, 31.2] as an
independent reproduction. The last of those steps is a measured cost of unblocking a mis-scored
branch, not noise being chased; see `PROJECT_ASSESSMENT.md`.

### When it moves, diagnose before you tune

The order that worked, on the sweep and the death measurement that produced the numbers above:

1. **Split the losses.** In `per_run`, a truthy `cause_of_death` means the run died; everything
   else that did not win stalled. Deaths and stalls answer to completely different levers, and
   at present deaths are about 74% of losses and no threshold touches them.
2. **Read what the stalls were short of.** `egress_why` enumerates all four routes with the
   counts that run actually held.
3. **Read the shape of the deaths.** `max_drop_pct` and `hp_tail` separate a burst from an
   attrition, and they are not the same problem. Measured: median worst single-turn fall is 17%
   of max HP, no run in 288 ever took a 50% hit, and every dying run spent dozens of turns below
   25% HP. Beware `hurt_share` on its own: it divides by runs of five to ten thousand turns, so
   hundreds of desperate turns vanish into thousands of healthy ones.
4. **Price the candidate before running an arm.** Count the runs a new threshold would have
   released. Measured against a 576-run sweep, that prediction was exact at one point of gate,
   within a win at two, and four wins optimistic at four, since a larger change opens the stair
   earlier and the run diverges rather than merely being re-scored.

An arm is 144 runs and about an hour. Most candidates can be rejected for free.

## UniversalBrain & profiles (`runtime/agent.py`)

`class UniversalBrain(Brain)` — single class; `name` property sets the active profile.
Registered via `register_brain` for all six names. **`PROFILES`** (at `agent.py:16`)
are scoring-weight dicts:

| Profile       | Top-drive                     | Negatives  |
|---------------|-------------------------------|------------|
| `artisan`     | forge:15, workspaces:12      | —          |
| `cartographer`| explore:15, terminals:12     | fight:-5   |
| `emergent`    | fight:15, shield:10          | commune:0  |
| `exploiter`   | shield:15, fight:10, camp:10 | commune:0  |
| `seeker`      | all ≈6–8 (balanced)          | —          |
| `whisper`     | parley:15, commune:10, becalm:10 | fight:-5 |

## Scoring formula

```python
score = max(profile_weight, state_urgency) + turn_bonus
```
Defined in `_score()` at `agent.py:91`. Profile weight = **identity floor** (artisan
always scores ≥15 on forge when reachable). State urgency exceeds the floor for survival
(low hp, danger). `_starting_bonus(turn)` returns `12, 8, 4, 0` over turns 1–6, decaying
to zero — initial push for divergence before the floor dominates.

`decide(self, game, actor)` calls `agent_state(game, actor)` once per turn, then walks a
**priority cascade** scoring each candidate, picking the highest.

## Priority cascade

PANIC (hp<25%: cast Phase or descend/flee) → COMMUNE (truths≥2 or matter≥4 near boss,
`_score("commune", 25)`) → BEACON (beacon on floor, walk to it) → HEAL (hp<60%: cast
Recall, urgency=(100-hp%)/4) → PARLEY (elite/boss, agent has option, standing bonus) →
BECALM (adjacent hostiles, matter≥2, knowledge bonus) → FORGE (free slots, matter≥2,
unslotted ability preferred) → BREAKDOWN (durability≤1 sigil) → SHIELD (no adjacent
hostiles, defense<3) → CONSUMABLE (known recipes, affordable, safe) → FLEE (adjacent
hostiles, hp<40%, step_away) → EXPLORE (unseen tiles, salvage ground, caches, POIs,
commune landmarks) → WORKSPACES (fabricator/terminal/depleted/camp within 6, safe) →
REST (safe, hp<70%) → WEATHER CLEAR → FIGHT (adjacent hostiles, weighted by hp/defense)
→ DE-ESCALATION (kills≥4: descend or move to stairs) → STAIRS (on or toward).

## AgentAction, a 19-verb vocabulary (`runtime/agent_action.py`)

`@dataclass AgentAction(kind, dx, dy, index, target, additive)` at `agent_action.py:14`.
Kinds: **move, wait, cast, shield, shove, interact, descend, ascend, forge, rest, talk,
toss, negotiate, breakdown, becalm, craft_consumable, commune, deploy, recover.**

Nineteen, counted off `dispatch()`. This heading said fourteen and then listed sixteen,
a different sixteen from the one the dataclass comment listed. Two of the nineteen,
`talk` and `ascend`, are dispatched but emitted by no brain. Every one of the nineteen is
now also reachable from the keyboard; see `guidance/SYSTEMS_GAP.md`.

`dispatch(game, action)` at `agent_action.py:44` routes each verb — `"forge"` →
`forge.forge(game, ability=target)`, `"negotiate"` → `Parley(...).hear(...)`,
`"breakdown"` → `salvage.breakdown_sigil(game, target)`, `"craft_consumable"` →
`craft_consumable(game, target)`, `"commune"` → `game.commune()`, etc. All None-guarded;
exceptions return False.

## agent_state() — perception snapshot (`runtime/agent_perception.py`)

`agent_state(game, actor) -> dict` at `agent_perception.py:18` returns 40+ fields:
**vitals** (hp, hp_pct, defense, body per-part, `can_heal_meaningfully`), **status**
(bleeding, slowed, staggered, speed), **effects** (worn_effect, collected), **position**
(on_stairs, on_town, on_surface, region, floor), **weather_hazard**, **danger_ahead**
(elite/boss within 8), **hostiles** (sorted by dist, each with name/hp/tier/faction/
is_boss/source/body/allegiance/enraged/on_hazard), **adjacent_hostiles** (dist≤1),
**near_hostiles** (dist≤3), **sigils** (ability/base/durability per slot), **matter**
(total, comp, forge_ready), **caches** (within 20 tiles), **pois**, **tension**,
**noise_near**, **faction_kills / kills_on**, **factions** (standings, `standing_critical`,
`reputation_sum`), **knowledge** (known/learned notes, `truths_read` =
`marginalia.read + history.read`), **nav** (stairs_pos, max_sigils, free_sigil_slots,
`any_boss_near`, lantern/small flags), **loci/beacons/workspaces** (nearest_locus,
beacon_on_floor, nearest_beacon, nearest_fabricator, nearest_terminal, nearest_depleted,
nearest_camp), **encounter_options** (parley/coerce/flee/appease/fight — built from
standing + knowledge + matter), **companions** (hp/dist/command, `companion_penalty`,
`can_recruit`), plus `can_becalm`, `becalm_discount`, `has_trap_near`, `spawn_threat`,
`spawn_allies`.

## agent_eval.py — evaluation harness

`@dataclass RunResult` at `agent_eval.py:45`: agent, seed, floor_reached, max_floor, won, kills,
items_collected, sigils_forged, caches_opened, turns_survived, hp_ended, `run_seed`,
`egress_open`/`egress_route`/`egress_why`, cause_of_death, floors_cleared, average_hp,
attractor_scores, narrative, metrics, `win_path`, `pressure`, `emergence`.

`run_seed` is the per-run varier and `seed` is the world's, so a row identifies its own game:
`run_agent(world, agent, floors, run_seed=<row's>)` replays it. The three `egress_*` fields
record what the last stair wanted at the moment the run ended.

`run_agent(world_json, agent_name, max_floor, max_turns_per_floor, run_seed)` at
`agent_eval.py:79`: builds all systems via `_build_systems()`, builds `Game(..., sandbox=False)`
so this is classic descent rather than the sandbox the interactive mode uses, assigns brain via
`make_brain`, loops `brain.decide` → `dispatch` → anti-stall BFS. Records `AttractorTracker` per
floor. `max_turns_per_floor` defaults to 500 and abandoning a floor at that limit is a harness
behaviour, not a game rule.

`evaluate_agents(world_json, n_runs, max_floor)` at `agent_eval.py:313`: runs each of 6
profiles `n_runs` times, computes per-agent aggregates (win_rate, avg_floor, deepest_floor,
avg_kills, avg_sigils_forged, avg_caches_opened, avg_turns, avg_hp_ended, deaths, win_paths,
pressure, emergence), builds **per-floor survival curves** (`surv_curve[f] = count reaching ≥f`),
collects attractor metric averages + narrative samples, and emits `per_run` (one row per run),
`policy_divergence` (all 15 profile pairs), `persistence` and `hash_seed`. Output →
`~/.vaultcrawl/eval_stats.json`.

`DEFAULT_RUNS = 100`, `DEFAULT_MAX_FLOOR = 99`. CLI: `python3 -m runtime.agent_eval
world.json --runs 20 --agent whisper`. `AGENT_NAMES = ["artisan", "cartographer",
"emergent", "exploiter", "seeker", "whisper"]`.

`--runs` is **per profile**, so `--runs 48` is a 288-run evaluation. Anything quoted as a
measurement needs at least that; 8 seeds moves by up to three wins per profile. Use `per_run`
for spread rather than quoting a mean, run from a clean `~/.vaultcrawl` at a fixed
`PYTHONHASHSEED`, and never alongside the test suite.
