# CLAUDE.md

<!-- Status: Current | Last updated: 2026-07-23 -->

## What this is

Two codebases under one roof:

- **`vaultcrawl/`**: the bake pipeline. Markdown vault → graph metrics → mechanical slots
  (deterministic) → LLM names/lore (the "skin", can never move a number) → `world.json`.
  Entry: `python3 -m vaultcrawl.bake <vault> -o world.json`. Zero deps, stock Python.
- **`runtime/`**: a terminal roguelike rendering a baked `world.json`, with a 29-system
  stack, 6 AI agent profiles, and 25 consumable recipes.
  Entry: `python3 -m runtime.play world.json` (interactive) or `--auto` (headless).

Run both from the repo root so the packages import.

## Commands

```bash
python3 -m vaultcrawl.bake sample_vault -o examples/world.json   # bake a world
python3 -m runtime.play examples/world.json                       # interactive play
python3 -m runtime.play examples/world.json --auto --brain seeker # headless agent
python3 -m runtime.agent_eval examples/world.json --runs 20       # evaluation harness
python3 run_agents.py                                             # multi-agent runner
python3 -m pytest tests/ -q                                       # 336 tests, 50 of 70 modules
PYTHONPATH=. python3 tests/test_integration.py                    # the other 20 are scripts
```

## Process: read this before touching anything

**Every domain has a spec. Find your task below, read the spec first, then work.**

| If your task is... | Read this first | What it covers |
|---|---|---|
| Understanding systems, the event bus, or System base class | `guidance/SYSTEMS_SPEC.md`, `guidance/INTERACTIONS_SPEC.md` | System hooks, canonical events, query API, contracts |
| Working on enemy/monster AI or NPC behavior | `guidance/BRAINS_SPEC.md`, `guidance/MIND_SPEC.md` | Brain interface, capability ladder, memory/planning tiers |
| Working on player-agent AI or agent profiles | `guidance/AGENT_SPEC.md` | UniversalBrain, 6 profiles, scoring formula, perception, what the win rate is for |
| Working on ecology (flora, fauna, weather, structures, decay) | `guidance/ECOLOGY_SPEC.md` | Autonomous world-layer, allegiance model, terrain write-API |
| Working on sigils, forge, salvage, or the matter economy | `guidance/SALVAGE_SPEC.md`, `guidance/QUALITY_SPEC.md` | Shatter→salvage→forge loop, quality grades, proficiency |
| Working on senses, perception, or creature detection | `guidance/SENSES_SPEC.md` | Two-layer perception (detection/identification), sense profiles |
| Working on quests, dialogue, Keepers, or machines | `guidance/DEEPEN_SPEC.md` | Quest lifecycle, NPC parley, Fabricator/Terminal placement |
| Working on loci, crafting, wear, recipes, or skills | `guidance/CRAFT_SPEC.md`, `guidance/LOCI_SPEC.md` | LocusSystem type-casting, 4 workspace rituals, 25 consumables, 5 skill trees |
| Working on level gen, architecture compiler, or sandbox mode | `guidance/ARCHITECTURE_SPEC.md` | Pattern-language compiler, semilattice world, wholeness scoring |
| Working on room fixtures, scenery, or sense-of-place | `guidance/DESIGN_PLACE_PANEL.md` | Fixture placement, examinable voice, ambient narrator |
| Working on cross-run persistence or Upheaval | `runtime/persistence.py` (docstring) | RunChronicle, terraforming events, death artifacts |
| Working on knowledge, fog-of-war, or map mechanics | `runtime/knowledge.py` (docstring) | Known/learned notes, region mapping, faction insight |
| Understanding what player verbs exist and what's missing | `guidance/SYSTEMS_GAP.md` | 28-system reachability audit, verb binding gaps |

**Rule:** Before touching any file in a domain, read the spec for that domain. Specs contain contracts, test recipes, and cross-system interaction rules. Skipping the spec produces work that breaks invariants.

## Agent architecture

Six agent profiles (artisan, cartographer, emergent, exploiter, seeker, whisper) share one
`UniversalBrain` class in `runtime/agent.py`. Profiles are scoring weight dicts. The identity
formula is: `score = max(profile_weight, state_urgency) + turn_bonus`. Berlin-compliant:
every agent CAN do everything. Starting state determines which branches are reachable.

The agent communicates with the game via a 19-verb `AgentAction` vocabulary
(`runtime/agent_action.py`) and reads the world through `agent_state()` in
`runtime/agent_perception.py`. See `guidance/AGENT_SPEC.md` for the full architecture.

## Core invariants

1. **Berlin Interpretation compliance is mandatory, project-wide.** Per the Berlin
   Interpretation of roguelikes: the game must have no class-locked features. Every
   agent must be able to do everything. Every system must be reachable by anyone.
   No ability gates. No personality-gated code paths. No hardcoded character differences.
   Differentiation comes exclusively from *starting state* (HP, DEF, matter, sigils,
   knowledge, standing, recipes) and *preference biases* (scoring weights, never locks).
   If you add a system, every profile must be able to interact with it. If you add an
   item, every profile must be able to craft or acquire it. If you add a locus activation
   type, it must be reachable through the universal tree. The six profiles are starting
   states plus preference biases, never character classes. See `guidance/AGENT_SPEC.md`
   §Berlin Interpretation for the architectural contract. **Violating this is a design
   regression of the highest order.**
2. **Deterministic skeleton vs. LLM skin.** The LLM gets only `_`-prefixed flavor inputs
   and returns only `name`/`flavor`/`title`/`objective`. It cannot move a tier, depth, or
   power number. Do not break this seam.
3. **No em dashes**, ever, in anything (code, comments, docs, UI, commit messages).
   Rephrase. Enforced on pull requests, but only on the lines a change *adds*
   (`.github/workflows/ci.yml`, job `house-style`). The back catalogue is untouched and
   large, 550 occurrences across 99 `.py` files and 350 across 22 `.md` files, so the rule
   is real going forward and a lie about the past. Do not cite existing files as precedent.
4. **Determinism first.** No `random.seed()`, no `hash()`-seeded ordering, no wall-clock
   in the bake path. Seed RNG from SHA-256 of stable keys.
5. **The suite is split, and pytest only sees two thirds of it.** `python3 -m pytest tests/ -q`
   collects 336 tests across 50 of 70 modules and runs in about 90 seconds. The other 20,
   including `test_integration.py` and the whole brain ladder, use a `main()` plus
   `if __name__` script style pytest cannot discover; run those as
   `PYTHONPATH=. python3 tests/<name>.py`. **16 collected tests currently fail**, and they
   fail identically on every commit checked back to before the assessment work began (see
   `guidance/PROJECT_ASSESSMENT.md` F3). They are listed in `tests/known_failures.txt` and
   marked `xfail(strict=True)` by `tests/conftest.py`, so a green run means "the same 16 are
   broken", not "everything works". That list may only shrink: fixing a bug and leaving the
   line in place turns the pass into an `XPASS(strict)` failure, and an entry that matches
   no collected test is a collection error. CI runs both halves plus a determinism check
   (`.github/workflows/ci.yml`); `agent_eval` is deliberately not in it, being slow and
   1-run-in-48 flaky.
   Do not run the suite concurrently with `agent_eval`: together they OOM.
6. `ponytail:` comments mark deliberate shortcuts. Prefer deleting over adding.
   (Two: `vaultcrawl/evolve.py` and `vaultcrawl/corpus.py`. This said zero, which was wrong.)
7. **Balance changes must be measured, not argued, and 8 seeds is not a measurement.**
   `runtime/pressure.py` reports decision margin, label share, win-path split and policy
   divergence. Run the eval from a clean `~/.vaultcrawl` with `PYTHONHASHSEED=0` or the
   numbers are not comparable to anyone else's. **Use `--runs 48`, not 8.** Measured on one
   world and one commit, going from 8 to 48 seeds moved every profile, four of them by two
   or three wins' worth: artisan 37.5 to 18.8%, cartographer 50 to 22.9%, emergent 12.5 to
   29.2%, whisper 75 to 50%. The old "+/-1 win per 8-seed arm" guidance understated the
   spread by about three times. The current baseline is **130 of 288, 45.1%, 95% interval
   [39.4, 50.9]**, measured after the egress-gate fix. The step before it was 123 of 288,
   42.7%, [37.0, 48.4], and those two overlap heavily: **that change is not visible in the
   aggregate and should not be claimed from it.** What it is visible in is the per-run label
   histograms, where runs with one label above 60% fell from 15 to 2 and all 13 egress stalls
   ended, 8 of them becoming wins. Both are up from 77 of 288, 26.7%, [22.0, 32.1] and not
   overlapping it. Two
   livelock fixes are most of that, and **a livelocked run is a guaranteed loss rather than a
   badly played one**, so a large part of the gain is runs that now finish rather than runs
   that now play better. Those are different claims and only the first is evidenced here.
   Deaths are now 90.3% of losses, up from 74%, which is the same fact seen from the other
   side: the turn-capped non-deaths were mostly loops. **There is no target win rate**, and the 40-60 band that was treated as
   one for most of this project's life appears in no spec; health is the seven structural
   conditions in `guidance/AGENT_SPEC.md` §What the win rate is for, and the aggregate is a
   tripwire read against its own history in `guidance/PROJECT_ASSESSMENT.md`.
   `agent_eval` writes per-run rows into `eval_stats.json`, so use those for spread rather
   than quoting a mean. **Deaths are 74% of losses and they are attrition, not burst**: median
   worst single-turn fall is 17% of max HP, no run in 288 ever took a 50% hit, and every dying
   run spent dozens of turns below 25% HP. **The long-standing `recall` at 0.00% claim was
   three separate things and the headline number was never evidence of any of them.** A label
   share puts every decision in the run in the denominator, and the agent is below 60% HP on
   under 1% of its decisions, so an emergency verb reads as 0.0% no matter how well it works.
   Use `python3 -m runtime.availability <world>`, whose UPTAKE section reports the conditional
   rate: what the agent chose on the decisions where a Recall was genuinely castable. On that
   instrument the defect was real and large, 13 casts in 187 chances, 7.0%, against locus 25%
   and explore_unseen 16%. The three causes, all now fixed and none of them the one this
   paragraph used to name: `deploy` and `recover` borrowed the `explore` key (`efd591b`);
   `deploy` opened at an unconditional state of 8 that outranked every `sigil` weight
   (`a59a500`); and HEAL's urgency was `(100 - hp%) // 4`, which cleared the exploration
   identity floor of 15 only below 40% HP while PANIC hard-overrides at 35, leaving the heal a
   five-point window. **Raising the `recall` weight could never have worked**: it is 3 to 6 and
   `runtime/weight_audit.py` measures it at 84 calls and 0 binds, so it has never once been the
   term that decided anything. A fourth cause surfaced only once the third was fixed: PANIC
   returns before the candidate list is built and knew about `Phase` but not `Recall`, so the
   agent fled at low HP with an unspent heal (`16de718`). Uptake went 7.0%, then 17.7%, then
   **90.5%**, and the castable-decision count fell from 187 to 21 because an agent that heals
   promptly stops accumulating wounded turns. **Each fix promoted the next bottleneck from
   negligible to dominant, so re-measure after every one rather than trusting the ranking you
   started with.**
   The rows also carry `egress_open`/`egress_route`/`egress_why`, which
   record what the last stair wanted at the moment the run ended, so **price a threshold from
   an evaluation you already have before spending an hour on an arm.** Counting the stalled
   runs a candidate value would have released predicted all three arms of the
   `EGRESS_STANDING` sweep: exact at one point of gate, within a win at two, four wins
   optimistic at four, because a bigger change also alters the run rather than only its
   ending. That sweep, 4 arms of 144, is also the answer on the escape gate: **7, 6, 5 and 3
   all overlap, so the gate is not the lever and it stays at 7.** Deaths are 82, 82, 81, 82
   across the arms, and 69 of 82 of them happen at standing 0.

## Known issues

- **Bake determinism, fixed.** The bake is a pure function of vault content: same notes,
  same world, on any machine. `activity` no longer comes from file mtimes (a clone rewrites
  them, and min-max amplified the surviving write-order jitter to the full range), and
  `generatedFrom.vaultPath` is a basename rather than the baking machine's absolute path.
  Pass `--mtime-activity` to get edit-recency back on your own vault; that world is not
  portable and says so in the manifest. CI asserts a fresh bake equals the committed
  `examples/world.json`, so the demo page, the tests and a stranger's clone all describe the
  same game. See `vaultcrawl/mapping.py` `activity_map()` and `tests/test_bake_determinism.py`.
  If you change `sample_vault`, regenerate `examples/world.json` and re-measure the balance
  baseline in the same commit.
- **Runtime determinism, mostly fixed.** The 21 `hash()`-seeded sites are now SHA-256 via
  `runtime/det.py`. Residual cross-process variance remains in the knowledge-to-sigil-slot
  path. It does **not** reproduce exactly at a fixed `PYTHONHASHSEED`: measured over two
  48-run evals on identical code, one run in 48 flipped outcome. Budget about +/-1 win of
  noise per 8-seed arm, which is 12.5 points, before calling two arms different.
- **Cross-run state leaks into benchmarks.** `~/.vaultcrawl` carries graves, the forge
  cache and the chronicle. A clean directory and a warm one give different win rates from
  the same command; `eval_stats.json` now records which it ran against.
- **In-process run isolation, fixed.** The other half of the above, and a fresh `HOME` did
  not help because it lived in RAM. `reset_run_state()` was called only by `agent_eval` and
  `run_agents.py`, so anything else building two games in one process inherited the first
  run's skill tiers: eight runs of one config gave matter 3, 4, 5, 7, 7, 7, 9, 9 where a
  fresh interpreter always gave 3. `Game.__init__` now calls it, because a Game is a run.
  If you add per-run module state, reset it there and add a case to
  `tests/test_run_isolation.py`.
- **Privacy is enforced.** `#nogame`/`#private` tags exclude notes at ingest.
- **Real-LLM path is unproven.** No Anthropic-backed `complete_json` exists. The offline
  stub is the default. A `_named()` fallback prevents crashes when LLM output is missing keys.
- **`runtime/arch/` is LIVE.** The Alexander compiler powers sandbox mode
  (`Game(sandbox=True)`, the default interactive mode). Classic descent (`--descent`,
  `--auto`) still uses the original dungeon generator. Still unwired: §10 word-level
  flow, the `siteplan` bake block, continuous-megastructure mode.
- **Every number in this file describes classic descent, not the mode people play.**
  `agent_eval` hardcodes `sandbox=False`, so the 130 of 288 baseline, the seven health
  conditions and every sweep are all classic. Sandbox is the default interactive mode and had
  never been run with an agent until `runtime/sandbox_eval.py`. The first batch that did found
  **533 decisions per game turn**, three stacked defects deep, plus a sixth instance of the
  reachability-versus-precondition class and a Berlin gap where no agent could take a portal a
  human walks through. Fixed and pinned in `tests/test_sandbox_stairs.py`. Measured after, 48
  runs per arm on the same seeds: sandbox **10/48** against classic **25/48**, McNemar exact
  **p = 0.004**, mean floor **1.6** against **20.1**, and **33 of 48 sandbox runs burn the
  harness budget without resolving**, all of them losses. Coupling density is the one number
  that favours sandbox, 0.749 against 0.678. Read
  `guidance/PROJECT_ASSESSMENT.md` §Sandbox mode before touching either mode; the shortfall is
  a missing descent gradient, not a tuning gap, and there is still no target win rate.
- **The stall tripwire needs two terms, not one.** Decisions-per-turn above 1.05 catches loops
  that fail to spend a turn, which was all five of them before sandbox. seeker/sbx-0 spent
  **87.1% of its decisions on `keeper` at 1.00 d/t**: a loop that pays for every iteration and
  reads perfectly healthy. Check the per-run top-label share too, and treat above roughly 60%
  as its own signal.
