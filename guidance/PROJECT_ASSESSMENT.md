<!-- Status: Current | Written: 2026-07-24 | Empirical audit of HEAD (937beea) against the guidance/ spec corpus | Balance pass appended 2026-07-24 -->
# Project assessment: specs versus running code

> **Update.** A balance pass has since landed on top of this audit and changed several of
> the numbers below. F10 in particular was written before the livelock underneath it was
> found. See "Balance pass" at the end for what moved, what the new baseline is, and which
> findings here are now closed.

## Verdict

Vaultcrawl is a stronger project than its current verification layer can prove. The core
idea is intact and the hardest engineering in it is real: the deterministic-skeleton /
LLM-skin seam is structurally enforced rather than merely promised, the bake pipeline's
determinism discipline is genuinely clean, and the 15-document spec corpus in `guidance/`
is better than most production codebases carry.

What has decayed is the loop that keeps the specs honest. There is no CI running tests. The
documented test command silently skips a third of the suite. Sixteen collected tests fail on
HEAD. Four player keybindings are unreachable dead code. Several invariants stated in
`CLAUDE.md` are not enforced anywhere and are broadly violated.

None of this is a rewrite. Every finding below is a bounded fix. The distance between what
this project believes about itself and what is actually running is the whole problem, and it
is closable in a few focused passes.

## Method

Everything here was verified by running it, not only by reading:

- Baked `sample_vault` twice and compared bytes. Baked two copies with divergent mtimes and
  diffed the resulting worlds field by field.
- Ran all six agent profiles headless against `examples/world.json`.
- Instrumented a live run to record which brain classes are actually constructed.
- Ran all 65 test modules under pytest, then again as direct scripts with `PYTHONPATH=.`.
- Diffed the system stacks built by `play.py`, `agent_eval.py`, and the scenario demos.

Line numbers are current as of commit `937beea`.

---

## What is genuinely strong

**The LLM seam is enforced, not conventional.** `CLAUDE.md` undersells this. Pass-2 results
are merged mechanical-dict-first with only named keys pulled from model output
(`vaultcrawl/generate.py:94-121`), `_`-prefixed keys are stripped both on the way in and on
the way out (`generate.py:16,71`), and `validate()` range-checks every mechanical field
fatally before write (`vaultcrawl/bake.py:26-28`). A model that returns `{"tier": 5}` has it
silently dropped. The seam holds by construction.

**Bake determinism is disciplined.** No bare `hash()`, no wall clock, no `random.seed()`.
RNG is seeded from SHA-256 of stable keys (`vaultcrawl/llm.py:50-52`), `os.walk` output is
sorted (`ingest.py:90`), edge order is sorted (`mapping.py:222`). Re-baking on the same
machine is byte-identical, confirmed. One leak remains (F6), and it is the exception.

**The spec corpus is an asset.** These documents state contracts, acceptance tests, and
cross-system interaction rules. Several self-report their own gaps honestly
(`ARCHITECTURE_SPEC.md:396-398`, `DESIGN_PLACE_PANEL.md:51-53`). That is rare and worth
protecting.

**Berlin compliance holds structurally.** A single `decide` in `runtime/agent.py`, candidates
appended unconditionally, no `if agent_name ==` gating in candidate construction. The
architecture does what invariant 1 requires.

**`runtime/arch/` is well covered.** Roughly 10 of 12 modules have tests, better than the
rest of the runtime.

**Exception hygiene is specific, not general.** Zero bare `except:`, zero
`NotImplementedError`. The problems in F12 are one identifiable pattern in one block, not
codebase-wide sloppiness.

---

## Severity table

| # | Finding | Evidence |
|---|---------|----------|
| F1 | Four player verbs are unreachable dead code | `runtime/play.py:1135,1145,1160,1162` |
| F2 | 20 of 65 test modules collect zero tests under pytest | `tests/test_integration.py` et al |
| F3 | 16 collected tests fail on HEAD | 7 modules, see below |
| F4 | No CI runs any test | `.github/workflows/pages.yml` is the only workflow |
| F5 | Stated invariants unenforced and broadly violated | `CLAUDE.md:79,80,85` |
| F6 | mtime reaches the mechanical layer of the bake | `vaultcrawl/mapping.py:103,291` |
| F7 | Brain registry collision makes `ExploiterBrain` unreachable | `runtime/tactics.py:145` vs `runtime/agent.py:637` |
| F8 | Eval harness runs 26 systems, the game runs 28 | `runtime/agent_eval.py:57` vs `runtime/play.py:1274` |
| F9 | Sandbox versus classic selected by TTY detection | `runtime/play.py:1288-1290` |
| F10 | Agent win rate is unreproducible and every win is an escape | `runtime/game.py:1317` |
| F11 | Verb vocabulary has drifted from every document | `AGENT_SPEC.md:83` vs `agent_action.py` |
| F12 | Event-bus logic lives in `Game` and fails silently | `runtime/game.py:1204-1297` |
| F13 | Real-LLM path has no on switch | `vaultcrawl/bake.py:76` |
| F14 | Spec hygiene drift | 9 specs, see below |

---

## Correctness

### F1. Four player verbs are unreachable dead code

`runtime/play.py`. The `f` (forge) handler opens at line 1123. Inside it, `if i is not None:`
at line 1128. The next four branches are indented as `elif`s of *that* conditional rather
than of the outer key chain:

```
1123    elif k == ord("f"):
1128        if i is not None:
1135        elif k == ord("b"):     <- break down a sigil
1145        elif k == ord("a"):     <- sacrifice shrine
1160        elif k == ord("d"):     <- shield
1162        elif k == ord("p"):     <- shove
1166    elif k == ord("V"):         <- outer chain resumes here
```

Those four bodies are reachable only when `k == ord("f")` and the forge prompt was cancelled,
at which point `k == ord("b")` is necessarily false. They are unconditionally dead. Pressing
`b`, `a`, `d`, or `p` at the top level matches no branch and does nothing.

This falsifies two claims in `SYSTEMS_GAP.md`: gap 3 (break down a sigil) is marked DONE at
`SYSTEMS_GAP.md:95`, and SacrificeSystem is filed PLAYER-REACHABLE at `SYSTEMS_GAP.md:72`.
Neither holds.

The auto agent reaches all four (`runtime/agent_action.py:81,86,164`). So the document's own
central thesis, that "the auto-demo AI reaches more of the engine than a human can"
(`SYSTEMS_GAP.md:36`), is not closed. It is wider than the document admits: `shield`, `shove`,
`breakdown`, `becalm`, `craft_consumable`, `deploy`, `recover`, and `negotiate` are all agent
verbs with no working human binding.

**This is the single highest-value fix in the repo.** It is a four-line dedent.

### F3. Sixteen collected tests fail on HEAD

```
tests/test_becalm.py       test_understanding_disarms_for_free, test_offering_placates
tests/test_body_parts.py   test_init_body, test_damage_part, test_leg_break_immobilizes,
                           test_heal_restores_legs, test_heal_worst_first
tests/test_commune.py      test_unknown_refuses, test_offering_path_spends_matter,
                           test_the_old_way_still_works
tests/test_forge.py        test_forge_quality_floor, test_forge_additive_steers_perk,
                           test_forge_quality_deterministic
tests/test_machines.py     test_fabricator_forges_and_consumes
tests/test_salvage.py      test_salvage
tests/test_ux.py           test_rest_camp
```

These are behavioral regressions in shipped systems, not stale assertions about renamed
helpers. Notable ones:

- `game.becalm()` returns False where the test expects a successful disarm.
- Body-part counts drifted from 8 to 25 and 4 to 21, and leg-break no longer immobilizes.
- `game.commune()` returns True where the test expects a refusal, and one assertion fails
  with the message "felling the deepest boss still wins", meaning a win-condition invariant
  is broken.
- Forged sigils come back with no `perks` key at all (`KeyError: 'perks'`), so the entire
  quality-additive path from `QUALITY_SPEC.md` is inert on forged items.

---

## Verification

### F2. A third of the test suite is invisible to the documented command

`CLAUDE.md:26` and `CLAUDE.md:82-83` say `python3 -m pytest tests/ -q` runs "64 test modules".
It collects **45 of 65**. Twenty modules use a `_check_*` plus `main()` plus
`if __name__ == "__main__"` script style that pytest cannot discover. They report
"no tests collected" and the run stays green.

Silently skipped:

```
test_integration.py   test_reactions.py   test_quality.py     test_tactics.py
test_planner.py       test_instincts.py   test_brains.py      test_grow.py
test_wholeness.py     test_carve.py       test_visualize.py   test_flora.py
test_weather.py       test_decay.py       test_fauna.py       test_knowledge.py
test_history.py       test_structures.py  test_abilities.py   test_metrics.py
```

That list includes `test_integration.py` (495 lines: descent invariants, determinism,
perception opt-in) and the entire brain-ladder suite.

All 20 pass when run as `PYTHONPATH=. python3 tests/<name>.py`. So this is a harness split,
not rot, and the coverage is better than the pytest run suggests. But the invariant suite is
not enforced by the command the project documents, which means a regression in any of those
twenty modules ships silently.

`CLAUDE.md:83`'s remark that "`unittest discover` finds nothing" is exactly backwards about
where the risk lies.

### F4. No CI runs any test

`.github/workflows/pages.yml` is the only workflow. It bakes the sample world and captures the
demo SVG for GitHub Pages, which is a nice touch (the published animation cannot drift from
the build). But nothing runs pytest, checks determinism, or enforces any invariant.

F2, F3, and F5 all survive in `main` for this reason. Everything else in this document is
downstream of it.

### F8. The evaluation harness runs a different game than the game

`runtime/agent_eval.py:57-70` builds 26 systems. `runtime/play.py:1274-1286` builds 28. The
harness is missing `CraftSystem` and `LocusSystem`. Every balance number the project quotes
was produced without the craft rituals and without loci.

Add the eight `*_scenario.py` demos (2,661 lines, 11.5% of `runtime/`), each hand-rolling its
own subset, and there are roughly ten distinct system stacks in the repo. One of them is the
game. They should all derive from a single factory.

### F9. Sandbox versus classic is selected by TTY detection

`runtime/play.py:1288-1290`:

```python
headless = a.auto or not sys.stdin.isatty() or not sys.stdout.isatty()
sandbox  = not headless and not a.descent
```

Every human session runs the `runtime/arch/` sandbox. Every `--auto` run, every `agent_eval`
run, and every pytest or CI run takes the classic generator. The path humans use is the path
nothing tests, and the path tests exercise is the path humans never see.

Commit `bf08e72` ("Wild landmarks in classic") is a manual backport of a sandbox feature.
That is the drift mechanism: features are hand-ported one at a time because the two
generators share no interface. Both live inside `game.py`, interleaved
(`_build_sandbox()` at 509, `descend()` at 1300, with `descend()` itself branching on
`self.sandbox` at its first line).

---

## Invariant drift

### F5. Invariants stated in CLAUDE.md, enforced nowhere

**No em dashes (`CLAUDE.md:79`, "ever, in anything").** 558 occurrences across 100 `.py`
files. 374 across 24 `.md` files. Six in `CLAUDE.md` itself. Eight in commit subjects. The
rule is dead letter. Either enforce it in CI with a one-line grep or delete it.

**`ponytail:` convention (`CLAUDE.md:85`).** Zero occurrences in the codebase. The rule
documents a convention that does not exist.

**Determinism, no `hash()`-seeded ordering (`CLAUDE.md:80`).** The bake path is clean. The
runtime is not: 21 or more sites use `hash()` on strings, which is `PYTHONHASHSEED`-salted and
therefore varies across processes. Load-bearing ones:

| Site | What it controls |
|---|---|
| `runtime/loci.py:25,29` | locus RNG seed and per-floor locus count (5-8) |
| `runtime/loci.py:141,191` | locus activation and per-tile rolls |
| `runtime/game.py:1239,1247` | lore-chain reveal chance and which note is revealed |
| `runtime/game.py:1849,1853` | becalm outcome thresholds |
| `runtime/game.py:1800,3089` | ripple propagation, static chain target |
| `runtime/wear.py:31-32,54` | wear roll and restore amount |
| `runtime/recipes.py:24` | recipe roll |
| `runtime/persistence.py:118` | cross-run artifact chance |

The invariant is scoped to "the bake path" in its wording, so this is arguably compliant by
the letter. It is not compliant with the spirit, and it means a seeded run is not reproducible
across processes. `test_integration.py` has a determinism section; it is one of the twenty
modules pytest never collects.

### F6. mtime reaches the mechanical layer of the bake

Verified experimentally: copy `sample_vault` twice, `touch -d "2020-01-01"` one copy, bake
both, diff. Result: 24 field differences, 11 of them numeric. `activity` diverges on every
node and region, and enemy **archetypes** change with it (gloom to scribe, revenant to wisp,
swarm to myriad).

The path:

```
ingest.py:122       mtime=os.path.getmtime(path)
mapping.py:246-249  activity = (mtime - lo) / span      # vault-wide min/max
mapping.py:291-292  _archetype_for(role, activity.get(m, 0.5), degree, m)
mapping.py:103      score += 0 if age >= 0.5 else 1
```

`archetype` is not flavor. It is enum-validated (`vaultcrawl/validate.py:56`) and drives
inherited combat actions (`mapping.py:76-86`).

Two amplifiers make this worse than a single-field leak:

1. Normalization is vault-wide min/max, so touching **one** note rescales `activity` for
   **every** note and can flip archetype thresholds across the whole bestiary.
2. A fresh `git clone` or archive extraction flattens all mtimes, so `span` falls back to
   `1.0`, every note lands at `activity` 0.0, and every note takes the `+1` branch. The world
   you get from a clone is not the world the author baked.

`vaultcrawl/ingest.py:8` states that "mtimes are used solely for the per-region `activity`
signal" and `ingest.py:6-7` that "copying the vault to another machine yields the identical
world". Both are false as written.

`CLAUDE.md`'s "Known issues" entry undersells this by describing it as a flavor field.

---

## Architecture

### F7. Brain registry collision makes `ExploiterBrain` unreachable

`runtime/tactics.py:145` and `runtime/agent.py:637` both call
`register_brain("exploiter", ...)`. `agent.py` imports last, so `UniversalBrain` wins.
Confirmed at runtime: `BRAIN_REGISTRY["exploiter"]` resolves to `runtime.agent.UniversalBrain`.

`BRAINS_SPEC.md:38` assigns the player the `exploiter` tier owned by `tactics.py`.
`AGENT_SPEC.md` makes `exploiter` one of six UniversalBrain profiles. The specs never
reconcile, and no monster maps to `exploiter` via `brain_for`, so `tactics.ExploiterBrain`
(`runtime/tactics.py:93`) never executes in the game. It survives only in `test_tactics.py`,
which instantiates it directly, and in `brain_scenario.py`.

Worth stating plainly, because it would be easy to over-read this finding: **the rest of the
capability ladder is live.** An instrumented run constructs `ForagerBrain`,
`OpportunistBrain`, `ScavengerBrain`, `SurvivorBrain`, `HunterBrain`, `WanderBrain`, and
`UniversalBrain`. Only the `exploiter` name is shadowed.

### F12. Event-bus logic lives in `Game`, and its failures are silent

`Game.emit` (`runtime/game.py:1204-1297`) broadcasts to every `on_event` at 1206-1207, then
runs 90 lines of `if/elif` on event type inside `Game` itself. Lines 1251-1297 are labelled
"Orphaned event listeners (Phase 1d: wire dormant hooks)". The `becalmed` handler
(`game.py:1262-1268`) reaches out and mutates every monster within 8 tiles, flipping
allegiance and nulling brains, from inside the dispatcher.

`runtime/systems.py:5-6` states that systems "never edit each other or game.py". The bus
violates the contract its own base class declares.

Of 86 `except Exception` in `runtime/`, the consequential ones are concentrated in this block:

- `game.py:1238` silently disables lore-driven recipe discovery for an entire run.
- `game.py:1217,1229` silently stop chronicle writes, so Upheaval quietly stops accumulating.
- `game.py:1259` silently drops faction standing increments mid-loop.
- `game.py:1295` silently drops flora regrowth per tile.

The block added to wire up dormant hooks is the same block where every failure mode is
silenced, and no test covers `emit` directly.

`game.py` is 3,544 lines, 15% of the package, spanning both level generators, combat,
rendering, persistence, the bus, social verbs, and roughly fifteen player verbs. It is the
natural place to start decomposing.

### F10. The agent works, but its win rate is not reproducible and not what it looks like

The agent stack does complete the descent end to end. A 30-run `agent_eval` pass on
`examples/world.json`:

| Agent | Win% | Avg floor | Avg kills | Caches | Turns |
|---|---|---|---|---|---|
| artisan | 80% | 25.2 | 4.8 | 0.0 | 6449 |
| cartographer | 60% | 22.8 | 3.4 | 0.0 | 4737 |
| emergent | 100% | 27.0 | 1.2 | 0.0 | 8354 |
| exploiter | 100% | 27.0 | 0.0 | 0.0 | 10018 |
| seeker | 100% | 27.0 | 0.0 | 0.0 | 9049 |
| whisper | 100% | 27.0 | 0.0 | 0.0 | 9521 |

Aggregate 27 of 30, so 90%, not 100%. Three findings sit inside that table.

**Every win is an escape victory.** `DEEPEST` is 27 for every agent, and floor 27 is the
`self.floor > self.max_floor` branch at `runtime/game.py:1317-1318` ("you slip past the final
warden"). Across 30 runs, not one win came from the boss-commune path
(`game.py:1742`) or the boss-kill path (`game.py:2702`). The victory the project describes as
its climax is never the victory the harness records.

**Three profiles win 100% with 0.0 kills and 0.0 caches.** `exploiter`, `seeker`, and
`whisper` beat the game by descending 27 times and touching almost nothing. Whatever the
20-branch scoring cascade is doing, on this world the winning policy is "find the stairs",
and the commune/forge/salvage economy is not what produces the wins.

**The result is not reproducible across invocations.** `run_agents.py` from a clean
`~/.vaultcrawl` gives 6 wins out of 6. Running the identical command a second time, with the
state directory now warm, gives 4 out of 6 with two deaths. The harness carries cross-run
state: `~/.vaultcrawl/graves.json` (`game.py:438,450`), the forge cache
(`run_agents.py:28`), and the chronicle. Within a fixed state the run is deterministic
(repeated `run_one("seeker")` reproduced floor 18, 6336 turns, 7 kills exactly), so this is
persistence, not RNG.

Upheaval and death artifacts are a designed feature (`runtime/persistence.py`), so the
coupling is intentional. The problem is that no reported win rate is meaningful without
stating the state of `~/.vaultcrawl`, and nothing in the harness output records it.
Benchmarks taken from a cold directory and a warm one are different experiments.

Two consequences worth acting on: `agent_eval` should report or reset the persistence state
it ran against, and the six profiles should be distinguishable by more than turn count. Four
identical 100% / 0-kill rows is not six playstyles. This also compounds with F8: the harness
producing these numbers is missing `CraftSystem` and `LocusSystem`, so the craft and locus
economies are absent from every figure above.

**Correction to an earlier draft of this document.** A previous version reported that all six
profiles "reach floor 3 of 26 and stop". That was wrong. `runtime/play.py:1205` defaults
`--floors` to 3, so `python3 -m runtime.play <world> --auto` descends three floors because
that is what was asked of it, not because the agent stalls. The agent is far more capable
than that measurement implied.

### F11. Verb vocabulary has drifted from every document

`AGENT_SPEC.md:83` says 14 verbs. Its own list at `:86-87` enumerates 16. The dataclass
docstring at `runtime/agent_action.py:15-16` lists a *different* 16. `dispatch()` implements
19. `CLAUDE.md` repeats the stale 14.

- `talk` (`agent_action.py:131`) and `ascend` are implemented but emitted by no brain. `talk`
  duplicates logic the cascade already reaches via `becalm` and `commune`.
- `deploy` and `recover` are emitted (`runtime/agent.py:468,615`) but appear in no spec.
- `negotiate` from the agent runs a single round with a hardcoded last move
  (`agent_action.py:157`: `parley.hear(game, target_actor, moves[-1])`) against
  `DEEPEN_SPEC.md:52-60`'s four-round temperament-weighted exchange. The agent never plays the
  negotiation minigame.

---

## Spec fidelity

### F13. The real-LLM path is closer than documented, but has no on switch

`CLAUDE.md` calls this "unproven". The contract side is in better shape than that: prompts and
structured-output schemas are already written and production-shaped
(`vaultcrawl/prompts.py:19-152`), and the seam holds by construction (see "What is genuinely
strong").

The blocker is mundane. `bake()` accepts `llm=` (`vaultcrawl/bake.py:22`) but `main()` calls
`bake(args.vault, args.out)` (`bake.py:76`) and exposes no `--llm` or `--model` flag. There is
no user-facing path to a model at all; you have to import `bake()` from Python.

Four gaps to close alongside the adapter:

1. LLM output is never schema-validated. `complete_json(system, user, schema, context)`
   (`llm.py:62`) receives the schema and the stub reads only `schema["x-kind"]` (`llm.py:64`)
   to dispatch. A real model's output is structurally unchecked.
2. `_named()` (`generate.py:86-88`) falls back for `name` only. Boss `title` defaults to `""`
   (`generate.py:100`) and `validate()` never asserts it non-empty, so a refusing model yields
   blank titles that the summary printer displays. Same for `flavor`.
3. Region-name uniqueness lives inside the offline stub's mutable set (`llm.py:138-143`).
   `validate.py:22-27` checks duplicate ids, never duplicate names. Swap in a real model and
   the uniqueness property silently disappears. This belongs in `validate.py`.
4. Pass 2 is strictly serial, one call per slot (`generate.py:92-121`), with no concurrency,
   batching, caching, or retry.

Separately, `OfflineStubLLM._used_region_names` is mutable instance state, so reusing one
stub instance across two `bake()` calls in a single process yields different region names for
the second world.

### F14. Spec hygiene

- **`schema/world.schema.json` exists (8,953 bytes) and nothing reads it.** No module imports
  `jsonschema`; no test validates an emitted world against it. `validate.py:3-5` states this
  as a deliberate split (the formal contract is the schema, `validate.py` covers only
  game-meaningful invariants), which is defensible, but with no validator in CI the schema
  can drift from the emitter undetected. Note also that `corpus` is injected after
  `generate_world` returns (`bake.py:24`), so it is easy to omit from a hand-written schema.
- **`SYSTEMS_SPEC.md` documents 6 base-class hooks; `runtime/systems.py` defines 10.**
  `on_event`, `on_interact`, `points_of_interest`, and `hazard_tiles` are undocumented in the
  base-class spec, and the last three are load bearing (the auto agent's POI navigation
  depends on them). A contributor following `SYSTEMS_SPEC.md` alone would not know they exist.
  Two smaller smells in the same file: `System.name = "system"` means any system that forgets
  to override `name` is what `Game.system("system")` returns, and `hazard_tiles` hardcodes
  `{"fire", "acid", "charged"}` in the base class, so adding a damaging element means editing
  `systems.py` rather than the system that owns the element.
- **`INTERACTIONS_SPEC.md:31-34` describes a migration** off `on_enemy_killed` and onto
  `on_event`, noting that "game.py calls both during this transition". Both hooks still exist.
  The transition was never completed or closed out, and any system still overriding
  `on_enemy_killed` double-counts.
- **Nine specs cite project root `/mnt/workspace/output/vaultcrawl`.** Wrong path, repo-wide.
- **`DESIGN_PLACE_PANEL.md` steps 5 and 6b are self-reported as not built** (ambient narrator,
  wait-to-listen). This compounds badly with the twelve ambient systems a human cannot
  address: without the narrator those systems are not merely undirectable, they are largely
  imperceptible. Weather, flora, decay, scent, and fauna all run every turn and produce almost
  nothing the player can perceive or act on. The spec's own acceptance test is the right one:
  "every ambient line must point at a reachable thing or it's a lying screen."
- **`ARCHITECTURE_SPEC.md` contradicts itself.** §8 makes continuous-megastructure the default
  architecture path; §13's realms model says depths use "the classic rooms+MST generator".
  Both cannot be the shipped design. Separately, `CLAUDE.md`'s listing of "§10 word-level flow"
  as unwired is a mischaracterization: `ARCHITECTURE_SPEC.md:348-355` defers §10 by design
  until the graph-level architecture reads as alive. It was never promised for this phase.
- **`runtime/arch/` has outgrown its spec.** `settle.py`, `vaults.py`, `areakinds.py`,
  `interiors.py`, and `blocks.py` are unmentioned by `ARCHITECTURE_SPEC.md`.
- **`SYSTEMS_GAP.md`'s keybinding table is stale in both directions.** Beyond F1, it omits
  keys that do work: `g` travel, `o` autoexplore, `<` ascend, `m`/`P`/`M` log views, `e` wear
  effects, `V` overlook, `i` inspect, `Q` quest log, and the debug menu.
- **`runtime/sense.py` (499 lines) and `runtime/senses.py` (331 lines)** are two modules with
  near-identical names, both defining perception and brain machinery. Rename or merge.

---

## Potential

The project is close to several things it has not quite reached. Ordered by leverage:

**1. A trustworthy build.** This is the prerequisite for everything else. CI that runs both
test harnesses, a determinism check that bakes twice and diffs, and a grep for em dashes.
Roughly a day of work, and it converts the spec corpus from documentation into enforcement.

**2. A human game as deep as the agent's.** F1 alone restores four verbs. Beyond that, the
agent has eight verbs the human lacks. The engine is already there; the binding layer is the
gap, and it is the difference between "a 4-verb roguelike wearing a 28-system coat" and the
thing the specs describe. `SYSTEMS_GAP.md` was written to close exactly this and needs one
more pass.

**3. A perceptible world.** The ambient narrator (`DESIGN_PLACE_PANEL.md` step 5) is the
highest-value unbuilt feature in the repo. Twelve systems currently run every turn and are
invisible. A sensory budget routed through the senses radius would make the ecology, weather,
and decay work that already exists actually land. This is the cheapest large increase in
perceived depth available.

**4. The real-LLM path.** An `AnthropicLLM.complete_json` honoring the existing schemas, a
`--llm` flag, output validation with retry, name uniqueness moved into `validate.py`, and
concurrency across pass-2 slots. The prompts are already written. This is the feature that
makes the project's premise land for a stranger with their own vault, and it is closer than
`CLAUDE.md` suggests.

**5. Agent depth.** The agent already finishes the game, which is more than `AGENT_SPEC.md`
can currently prove. What is missing is meaning in the result: every win is an escape past
floor 26 rather than a confrontation, three profiles win with zero kills, and the reported
rate moves depending on what is in `~/.vaultcrawl`. Fixing F8 is a precondition (the harness
has to run the real game), then making the escape victory harder to fall into by default
would force the commune, forge, and salvage economies to actually carry a run.

**6. One generator interface.** F9's TTY split and the manual sandbox-to-classic backports are
a recurring tax. A shared layout interface, with the two generators behind it, ends the drift
and lets tests cover the path humans actually run.

---

## Suggested sequence

**Tranche 1: make the build tell the truth.**
Dedent the four `elif`s in `play.py` (F1). Fix or explicitly quarantine the 16 failing tests
(F3). Make pytest collect all 65 modules, or add a runner that invokes both harnesses (F2).
Add a CI workflow that runs it (F4). Correct the "64 test modules" claim in `CLAUDE.md`.

**Tranche 2: close the invariant gaps.**
Either enforce the em-dash rule in CI or delete it; same for the `ponytail:` convention (F5).
Replace `hash()` with SHA-256-derived seeds at the load-bearing sites (F5). Decide what
`activity` is for and either exclude it from mechanical inputs or seed archetype from
something stable, then correct `ingest.py:6-8` (F6).

**Tranche 3: reconcile stacks and specs.**
One system-stack factory shared by `play.py`, `agent_eval.py`, and the scenarios (F8). Rename
one of the two `exploiter` registrations (F7). Move the orphaned listeners out of `Game.emit`
into their owning systems and stop swallowing their failures (F12). Reconcile the verb count
across `AGENT_SPEC.md`, the dataclass docstring, `CLAUDE.md`, and `dispatch()` (F11). Refresh
`SYSTEMS_SPEC.md` to 10 hooks, close out the `on_enemy_killed` migration, fix the nine stale
root paths, and resolve the `ARCHITECTURE_SPEC.md` §8/§13 contradiction (F14).

**Tranche 4: build the things worth building.**
The ambient narrator. The real-LLM adapter. Agent depth. A shared generator interface.

---

## Appendix: reproducing the numbers

```bash
# 45 of 65 modules collected, 16 failures
pip install pytest && python3 -m pytest tests/ -q

# the 20 modules pytest cannot see all pass directly
PYTHONPATH=. python3 tests/test_integration.py

# same-machine bake is byte-identical
python3 -m vaultcrawl.bake sample_vault -o /tmp/w1.json
python3 -m vaultcrawl.bake sample_vault -o /tmp/w2.json && cmp /tmp/w1.json /tmp/w2.json

# mtime changes archetypes
cp -r sample_vault /tmp/va && cp -r sample_vault /tmp/vb
touch -d "2020-01-01" /tmp/vb/*.md
python3 -m vaultcrawl.bake /tmp/va -o /tmp/a.json
python3 -m vaultcrawl.bake /tmp/vb -o /tmp/b.json && diff /tmp/a.json /tmp/b.json

# win rate depends on cross-run persistence state, not just the agent
rm -rf ~/.vaultcrawl && python3 run_agents.py    # 6 wins of 6
python3 run_agents.py                            # 4 wins of 6, same command

# 30-run statistics: 90% aggregate, every win an escape at floor 27
python3 -m runtime.agent_eval examples/world.json --runs 5

# note: `runtime.play --auto` defaults to --floors 3 (play.py:1205),
# so it is not a full descent unless you ask for one
python3 -m runtime.play examples/world.json --auto --brain seeker --floors 26
```

---

# Balance pass

Everything above describes HEAD `937beea`. This section describes what changed after it,
and supersedes F10.

## The finding F10 missed: 83% of every run was a livelock

F10 reported that agents win by escaping and that three profiles win with zero kills. True,
but it did not ask why 87-93% of turns were `rest` or `wait`. The answer is not that resting
was attractive. It is that the agent was stuck.

`runtime/agent.py` adds an `absorb_hazard` candidate whenever the player stands on a hazard
tile with no hostiles nearby: flat score 15, no HP gate, dispatching `rest`. Its comment
promises a buff after three rests. The buff could not arrive. `Game.absorb_aspect` was called
only from inside the `can_rest` branch of `wait()`, so a rester at full HP never advanced its
counter, and it read tile props from `WeatherSystem` alone while the agent's candidate reads
`System.hazard_tiles` across the whole stack. The agent would hold a reaction-laid acid tile
forever, waiting on something only a weather tile could give.

Measured on `exploiter` before the fix: **7,688 rest calls, `_rest_tile_turns` never once
reaching 3, zero aspects absorbed.** The loop only ever broke because the harness abandons a
floor after 500 turns, which is what "(no progress, abandoning floor)" was.

So every balance number this project has ever published, including the ones in F10, described
a livelock rather than a strategy.

A second contributor: `decide()` collapsed to `wait` whenever the winning candidate resolved
to no step. Cartographer, whose `rest` weight is 0, still called `game.wait()` 3,299 times a
run, and because `wait` healed, **the agent was paid 3 HP for getting stuck.**

## What changed

Ordered as it was applied, each step measured against the last.

**R0, the livelock.** `absorb_aspect` runs on every rest turn and unions props from every
system that writes them; the brain caps the attempt at three turns. `decide()` walks the
sorted candidate list and takes the first that resolves, instead of collapsing to `wait`.
`_score` breaks ties by state urgency, which unstuck `salvage`, `cache`, `interact` and
`poi`: they share the `explore` key with `explore_unseen`, and a stable sort meant that for
any profile with `explore >= 4` they could never be chosen at all.

**Instrumentation.** `runtime/pressure.py` measures whether choices are hard rather than
whether the agent won: decision margin and the share of turns that are genuine contests,
label share by candidate name rather than dispatched verb, the resource floor, and pairwise
policy divergence between profiles. `Game.win_path` records which of the four routes ended a
run. `eval_stats.json` stamps the persistence fingerprint and `PYTHONHASHSEED`, without which
no two win rates are comparable.

**R1-R4, the healing economy.** `wait` and `rest` were the same call; they are now separate,
and only `rest` heals. The dormant `_tension` counter is live, ticks on the activity it
exists to price, and past its cap the ground stops giving anything back; it also decays on
action instead of ratcheting (it had been measured at 1,709 against a threshold of 200). The
descend refund is halved, auto-forge is off by default, the per-craft heal is gone.
`FactionSystem.rest_modifier` sets the rest rate from standing with the house that owns the
floor, identical for all six profiles.

**R5, the escape victory.** Kept, because a kill-only win makes a pacifist profile strictly
inferior. Priced: the last stair opens on any of four routes (warden dead, warden communed,
enough truths, or standing 3 with its house). Truths are finite now, which they were not:
marginalia re-scattered on every floor entry so a loop could print them, and
`breakdown_sigil` minted one per call.

## New baseline

5 runs per agent, clean `~/.vaultcrawl`, `PYTHONHASHSEED=0`:

| agent | win% | turns | kills | caches | top choice | contested | min HP | win paths |
|---|---|---|---|---|---|---|---|---|
| artisan | 100% | 1979 | 4.8 | 4.4 | deploy 31% | 2% | 9 | escape 4, commune 1 |
| cartographer | 0% | 1210 | 4.0 | 1.0 | deploy 36% | 8% | 0 | none |
| emergent | 100% | 1058 | 15.0 | 6.0 | deesc_stairs 48% | 6% | 4 | escape 5 |
| exploiter | 0% | 4554 | 5.0 | 2.0 | locus 26% | 11% | 2 | none |
| seeker | 0% | 2891 | 4.0 | 3.0 | deploy 34% | 1% | 3 | none |
| whisper | 100% | 4181 | 2.0 | 3.0 | deploy 30% | 1% | 0 | escape 5 |

Against the pre-pass numbers: aggregate win rate 90% to 50%, turns 4,700-10,000 down to
1,000-4,600, kills off zero for every profile, caches off zero (they had been unreachable and
the metric read a field that does not exist), and agents now reach 0-9% HP where before every
run ended at 100/100.

## What is still open

- **Outcomes are bimodal.** Three profiles win every run and three win none. The aggregate
  sits in the target band by averaging two extremes, which is not the same as being balanced.
  Cartographer in particular dies around floor 11-13 in every configuration tried.
- **Contested decisions run 1-11%.** The agent is still almost never choosing between
  comparable options. This is the number that most directly says "the choices are not hard
  yet", and it moved least.
- **Escape still dominates.** The win path is no longer unanimous, but the other three routes
  are rare. The truths route in particular is not reached on the ten-note sample vault: agents
  peak at 3-4 truths against a requirement of 5.
- **Cross-process determinism is not complete.** All 21 `hash()` sites are converted to
  SHA-256 seeding and two set-iteration sites are sorted, but runs still differ across
  `PYTHONHASHSEED` values, traced to set-iteration order in the knowledge-to-sigil-slot path.
  Within a fixed hash seed, runs reproduce exactly.
- **The sixteen failing tests from F3 are untouched.** They are now stable rather than flaky:
  `test_becalm` used to report 1 or 2 failures depending on the interpreter's hash seed.

## Reproducing

```bash
rm -rf ~/.vaultcrawl
PYTHONHASHSEED=0 python3 -m runtime.agent_eval examples/world.json --runs 5
python3 -m pytest tests/test_pressure.py -q     # the rules this pass added
```
