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

## AgentAction — 14-verb vocabulary (`runtime/agent_action.py`)

`@dataclass AgentAction(kind, dx, dy, index, target, additive)` at `agent_action.py:14`.
Kinds: **move, wait, cast, shield, shove, interact, descend, forge, rest, talk, toss,
negotiate, breakdown, commune, becalm, craft_consumable.**

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

`@dataclass RunResult` at `agent_eval.py:85`: agent, seed, floor_reached, won, kills,
items_collected, sigils_forged, caches_opened, turns_survived, hp_ended, cause_of_death,
floors_cleared, average_hp, attractor_scores, narrative.

`run_agent(world_json, agent_name, max_floor, max_turns_per_floor)` at `agent_eval.py:104`:
builds all systems via `_build_systems()`, assigns brain via `make_brain`, loops
`brain.decide` → `dispatch` → anti-stall BFS. Records `AttractorTracker` per floor.

`evaluate_agents(world_json, n_runs, max_floor)` at `agent_eval.py:259`: runs each of 6
profiles `n_runs` times, computes per-agent aggregates (win_rate, avg_floor, deepest_floor,
avg_kills, avg_sigils_forged, avg_caches_opened, avg_turns, avg_hp_ended, deaths), builds
**per-floor survival curves** (`surv_curve[f] = count reaching ≥f`), collects attractor
metric averages + narrative samples. Output → `~/.vaultcrawl/eval_stats.json`.

`DEFAULT_RUNS = 100`, `DEFAULT_MAX_FLOOR = 99`. CLI: `python3 -m runtime.agent_eval
world.json --runs 20 --agent whisper`. `AGENT_NAMES = ["artisan", "cartographer",
"emergent", "exploiter", "seeker", "whisper"]`.
