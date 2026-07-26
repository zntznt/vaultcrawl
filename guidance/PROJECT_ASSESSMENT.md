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

---

# Depth and emergence pass

The balance pass above made the game press on the agents. It did not make the game deep:
contested decisions ran 1-11% of turns. This section records why, and what changed.

## The decision space was rich and the scoring collapsed it

Measured before any change: the brain offers a **median of 10 live candidates per turn** and
**27 distinct labels** across a run. That is not a thin game. But three labels took **80% of
all choices**, and the dominant consecutive pattern was `deploy -> locus -> deploy -> locus`:

```
locus 1250 (31%) · deploy 1119 (27%) · absorb_hazard 900 (22%)
```

## Three verbs had never worked

**`deploy` had a 100% failure rate for the life of the project.** `Game.deploy` constructed
`Actor("deployed_sigil", *deployed_pos)`, but `Actor.__init__` takes
`(x, y, glyph, name, hp, max_hp, atk)`. It raised `TypeError` on the first statement and
`dispatch`'s blanket `except Exception: return False` swallowed it. Measured: 1,119 dispatches
per run, 1,119 `False`, zero reaching the method body. It was still winning 27% of decisions,
because nothing ever told the scorer it had failed.

**`recover` could never succeed.** It required the player to stand on the deployed sigil's tile,
but `deploy` places the entity on a neighbouring tile and a deployed sigil is an Actor, so it
blocks movement. Unreachable by construction.

**`negotiate` could never succeed.** `_adjacent_monster_matching` scanned only the four
orthogonals while the rest of the game uses eight-directional adjacency, and it required an
exact name match against a target the brain chose a turn earlier.

All three are the same failure: the brain gets no feedback about whether the action it chose
actually worked, so a permanently broken candidate keeps its score and keeps winning. The
absorb-hazard livelock fixed in the previous pass was the first instance; these are the second,
third and fourth.

## The systems mostly do not touch

- A full run emits **4,028 events across 11 kinds**, and `noise` is 90% of them. becalmed 5,
  communed 5, lore_read 4, aspect_absorbed 3, standing_changed 2 in an entire 27-floor descent.
- **17 of 28 systems never receive a bus event.** **11 have in-degree 0** in the
  `game.system("x")` graph, so nothing in the game can observe them.
- `portals.py` has no bus traffic and no queries in either direction.
  (**Correction:** an earlier draft of this section called `scent.py` a total isolate too and
  proposed deleting it. That was wrong. `behavior.py:73` uses it for creature tracking and
  `recipes.py:105` for the scent-mask consumable. It does duplicate a scent map in
  `senses.py:288-317`, which is worth reconciling, but it is load-bearing and a test now
  guards against deleting it.)
- `dialogue.py` is fully authored and unreachable: its `on_event` fires only on `"interact"`,
  which nothing in real play emits.
- **6 of 13 event types have zero system listeners**, serviced by a 90-line if/elif inside
  `Game.emit` that writes faction standing directly, nulls monster brains, and reaches into
  `flora.plants`, behind five silent excepts.
  (**Correction:** an earlier draft called the `aspect_absorbed` handler dead because it guards
  on `_weather_suppressed`. That attribute is lazily initialized in three places
  (`game.py:2963,3039`, `machines.py:237`), so the handler ran whenever absorption had
  happened first. It now lives in WeatherSystem, which is whose state it was writing.)
- **Chemistry: 2 of 15 element pairs interact.** Affinity covers 8 of 24 cells, and half the
  opposite-pairs are unreachable because ice and sacred deal no damage. **Nothing carries an
  element**: every `ignite()` writes to a tile, never to an actor.

## The runaway layer is a facade

`RunChronicle` has 33 fields and zero readers; 9 of 14 recorders are never called, and one
(`record_companion_recruited`) is called but not defined, raising into a silent except.
`to_upheaval_events()` has zero callers and would crash if wired, because `from_events` reads
`e["note"]` while 5 of 10 producible kinds have no such key (verified `KeyError`). Six of
Upheaval's 13 kinds have no live producer. Three of six attractor scores are permanently 0.0.
`Dampener` has zero callers. `arch/vaults.py` has zero callers and a path that cannot resolve.
Graves cannot escalate because `_load_graves` overwrites by position.

The bake-play-bake circuit is structurally open: `bake.py` reads only the markdown directory.

**Fourteen feedback loops exist and every one is capped or subcritical.** The codebase is well
defended against runaway and, as a direct consequence, has none.

## Correction to the balance pass

`proficiency._tracker` and `_skills` were module globals with no reset, and the harness runs
hundreds of games per process. Measured on a fixed agent, world and seed: runs 1 and 2 reach
floor 27 and win; runs 3 through 6 stall at floor 20 and die as skill tiers climb to 5. **Every
per-agent aggregate in the balance pass was confounded with position in the batch**, and the
bimodal result reported there is partly an artifact of ordering. It was invisible to
`persistence_fingerprint()` because it lives in RAM, not in `~/.vaultcrawl`.

`runtime/stack.py:reset_run_state()` now clears proficiency, skills, the chronicle and metrics
at the start of every run in all three harnesses. Six consecutive runs of one agent now produce
byte-identical results.

## What changed, and what it moved

Fixed: the deploy crash, the recover adjacency, the negotiate targeting, the proficiency leak.
Added: fatigue, so an objective chosen repeatedly costs a little more each time and the cost
decays once the agent does something else, plus `note_result` so a dispatch failure charges the
candidate that caused it. Added `EmergenceLog`, which counts event kinds and per-verb success
and flags any verb attempted often that never once worked.

Measured over 2 runs per agent from a clean state at `PYTHONHASHSEED=0`:

| metric | before | after |
|---|---|---|
| top-3 label share | 80% | 37-53% |
| distinct labels chosen | 3 dominant | 20-29 |
| contested decisions | 1-11% | 24-76% |
| win paths across 6 agents | escape, unanimous | commune, unanimous |
| broken verbs | 4 undetected | 0 |

The broken-verb detector caught `negotiate` and `recover` on its very first run and `forge` on
its second, which is the whole point of it: it is the check that would have caught all four of
these plus the absorb-hazard livelock from the previous pass.

Note the inversion in the last row. Before this pass every win in thirty runs was an escape.
Now every win is a commune. That is not obviously better, and it is worth saying plainly: a
unanimous win path is a smell whichever path it is. What changed is that the agents now reach
the boss with the resources to talk to it, where before they walked past. The next pass should
aim for a split rather than a different monoculture.

## Still open

- The emergence surface itself is untouched: 11 systems remain unobservable, `dialogue` remains
  unreachable, and 2 of 15 element pairs still interact. Nothing carries an element.
- The runaway layer is still a facade. Closing it needs the Upheaval schema normalised and
  `to_upheaval_events` given a caller, which is roughly three edits.
- Win rate sits at 2 of 6 agents, just under the 40-60% band the balance pass targeted. The
  forge proficiency gate, previously masked by the leak, is the likeliest cause and is worth
  re-pricing now that it is visible.
- The win path is unanimous again, in the other direction. See above.


## Emergence pass: the bus

`Game.emit` is now a broadcast and nothing else. The ninety lines of if/elif that followed the
three-line dispatch moved to the systems whose state they were writing:

| event | now owned by | what it does |
|---|---|---|
| `forge_used` | ForgeSystem | its own noise, and the chronicle write |
| `corpse_spawned` | DecaySystem | the noise, at the site that already announced the corpse |
| `lore_read` | HistorySystem | chronicle, and recipe discovery |
| `lore_read` | KnowledgeSystem | the neighbour-reveal chain |
| `communed` | FactionSystem | the standing bump, and it now emits `standing_changed` |
| `becalmed` | FactionSystem | pacifying nearby creatures |
| `weather_cleared` | WeatherSystem | flora regrowth, by asking flora rather than writing its set |
| `aspect_absorbed` | WeatherSystem | weather suppression, which was always its state |

`recruited` settles its room at the emit site, because town tiles are Game's own state and a
listener reaching back into Game would be the same mistake in the other direction.

The broadcast loop is guarded per system. It was unguarded, so one system raising silenced
every system after it in the list, which is the opposite of the policy `on_interact` uses.

**`dialogue` is reachable for the first time.** Its `on_event` listens for `interact`, and
nothing in play emitted it. `Game.interact` now speaks to an adjacent Keeper before anything
else, and the brain has a `keeper` candidate scored off the existing `parley` weight, so whisper
reaches for it and emergent rarely does, by preference rather than by any lock. Measured: 5
quests and 8 offerings per run in a tree that had never once executed outside a demo.

Scoping matters here and cost a measurement: the first version preempted on any actor with
allegiance `npc`, which includes every creature pacified by a parley. That hijacked the other
things `interact` does, most visibly clearing weather, and took the win rate to 0 of 6. It is
now scoped to Keepers the dialogue system actually owns.

| metric | before pass | after |
|---|---|---|
| event kinds per run | 11 | 13 |
| systems with a live `on_event` | 11 | 15 |
| `Game.emit` non-broadcast lines | 90 | 0 |
| dialogue tree activations per run | 0 | 13 |

## The win-rate regression, diagnosed and fixed

Win rate had fallen 3, then 2, then 1 of 6 across three passes while every other number
improved. The first hypothesis, that talking to Keepers costs turns, was wrong: disabling the
keeper candidate entirely changes nothing (identical floors for all six profiles), because
Keepers are rarely adjacent. The second, that healing had been over-tightened, was also wrong:
artisan healed 1,119 HP over a run and still died on floor 12, with rests refused only 31 times
out of 351.

The actual cause is structural. `entities.py` is explicit that **the player never gains stats
during a run**, so there is no power curve at all. The floor-enter mend is the only resource in
the game that scales with depth. A previous pass halved it from `max_hp//5` to `//10` on the
argument that it was the largest heal in the game and was handed to the exact action that wins.
That argument was correct in isolation and incomplete in context: with no power curve, halving
it made a twenty-six floor descent unsurvivable.

Swept against the harness, one run per agent:

| mend | wins |
|---|---|
| `max_hp//10` | 1 of 6 |
| `max_hp//6` | 1 of 6 |
| `max_hp//4` | **3 of 6** |
| `max_hp//3` | 4 of 6 |

`DESCEND_MEND_DIV = 4` is now a named constant with the sweep recorded next to it, and a test
pins the band rather than the value, so cutting it again requires re-running the sweep.
Confirmed at two runs per agent: **3 of 6, 50%**, the middle of the 40-60% target band, with
every emergence number from this pass held.

## The bimodality was a measurement artifact

`artisan` and `exploiter` "never winning" was not a property of the game. **`run_agent` never
varied anything**, so every run of one agent on one world was byte-identical. `--runs 100`
played the same game a hundred times, and a per-agent win rate could only ever be 0% or 100%.
Every win rate this project has ever reported, including the ones earlier in this document,
was a binary dressed as a rate.

`Game` now takes a `run_seed` that varies the run without touching the baked world, and
`evaluate_agents` passes the run index. artisan wins on run seed 0 and loses on 2 and 3.

First honest win rates, 5 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | win rate | avg floor | deepest |
|---|---|---|---|
| artisan | 20% | 16.0 | 26 |
| cartographer | 0% | 7.0 | 12 |
| emergent | 20% | 8.6 | 26 |
| exploiter | 20% | 15.2 | 26 |
| seeker | 40% | 20.8 | 26 |
| whisper | 80% | 25.6 | 27 |

Aggregate 30%. Five of six profiles win at least sometimes and every profile has reached floor
26, so there is no bimodality left to fix. The win path also stopped being unanimous for the
first time: escape 3, commune 6.

Two environmental findings came out of the same investigation, because the first hypotheses
were wrong. Combat is not what kills agents: artisan took 116 points of combat damage across an
entire run and still died. Attributing every point of HP loss to its source shows **hazard
tiles and weather are roughly ninety percent of it**, and combat a tenth. The `absorb_hazard`
candidate was parking the agent on damaging tiles for an aspect, and `Game.absorb_aspect`
refuses past three aspects, so once the budget was full it was paying HP for nothing at all.
That is the same bug class as `deploy`, in its fourth variant. The candidate now respects the
aspect cap, refuses below 55% HP, and scores lower the more the tile is costing. `clear_weather`
scored a flat 3, so agents stood in acrid haze for thousands of turns rather than spend one
matter; its urgency now rises with the damage taken.

The mend was re-swept against a distribution rather than the one scenario: //4 gives 33%,
//3 gives 38%, //2 also gives 38%. It saturates at //3, so anything more generous buys nothing.
`DESCEND_MEND_DIV` is 3.

Final, 4 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | win rate | avg floor | deepest | contested | labels |
|---|---|---|---|---|---|
| artisan | 25% | 19.3 | 26 | 29% | 28 |
| cartographer | 0% | 9.8 | 18 | 77% | 20 |
| emergent | 25% | 9.8 | 26 | 30% | 25 |
| exploiter | 25% | 15.3 | 26 | 26% | 26 |
| seeker | 50% | 20.0 | 26 | 45% | 29 |
| whisper | 75% | 25.3 | 27 | 38% | 29 |

Aggregate 33%. Win paths: commune 6, escape 2.

## Cartographer had no way out of a fight

The last profile that never won. Two attempts, and the failed one is as informative as the fix.

**Raising its `flee` weight did nothing.** From 3 to 6 to 8 produced byte-identical runs. That
exposes a property of the scoring formula worth knowing before anyone tunes a profile:
`score = max(profile_floor, state_urgency) + turn_bonus`, so **a profile weight beneath the
typical state urgency for its candidate is inert**. Most of cartographer's weights sit in that
dead zone. A test documents it.

**The starting kit was the real gap.** Laying the six kits side by side:

| profile | escape sigil | DEF | fight weight |
|---|---|---|---|
| artisan | Recall | | 1 |
| **cartographer** | **none** | | **-5** |
| emergent | | +2 | 15 |
| exploiter | Phase + Ward | | 10 |
| seeker | Recall | | 8 |
| whisper | **Phase** | | **-5** |

The brain's panic branch has exactly one escape: cast a Phase sigil. Cartographer was the only
profile that started with **no sigil at all**, and one of only two whose `fight` weight is
negative. So the one profile that refuses to fight was also the one with no way out of a fight.
The other pacifist, whisper, starts with Phase and wins most of its runs.

Measured over four run seeds: no sigil wins 0 of 4, adding Phase wins 3 of 4. The +8 max HP it
used to carry was compensating for the missing escape and bought nothing once the escape
existed (+8 and +4 give byte-identical runs), so it is trimmed to +4, matching seeker's shape
of a sigil plus a modest stat. This is starting state, which is the Berlin-legal lever; nothing
branches on the profile at decision time, and a test asserts every profile starts with a sigil
and that every combat-refusing profile starts with the panic escape.

## Final

4 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | win rate | avg floor | contested | labels | win paths |
|---|---|---|---|---|---|
| artisan | 25% | 19.3 | 29% | 28 | commune 1 |
| cartographer | 75% | 21.3 | 72% | 26 | escape 2, commune 1 |
| emergent | 25% | 9.8 | 30% | 25 | commune 1 |
| exploiter | 25% | 15.3 | 28% | 26 | commune 1 |
| seeker | 50% | 20.0 | 45% | 29 | commune 2 |
| whisper | 75% | 25.3 | 38% | 29 | escape 2, commune 1 |

**Aggregate 46%, inside the 40-60% target band for the first time.** Every profile wins
sometimes. Win paths are spread across escape 4 and commune 7. Contested decisions run 28-72%
against the 1-11% this work started from, and 25-29 of the 27-plus candidate labels are in use
per profile against three labels owning 80% of turns at the start.

The one profile change did not disturb any other: artisan, emergent, exploiter, seeker and
whisper report numbers identical to the previous run.

## Tranche C: the chemistry is combinatorial

Six tile props existed and two of the fifteen possible pairs did anything: fire was quenched by
adjacent ice, and charged plus wet made a live chain. Water did not put out fire. Acid, despite
the module docstring saying it corroded, corroded nothing. Ice and hallowed ground dealt no
damage at all, which made half the elemental affinity table unreachable. And nothing carried an
element: every `ignite()` and `add_prop()` call in the codebase writes to a *tile*, never to an
actor, so the chemistry was strictly one step deep.

### C1. A pair table

`_PAIR_REACTIONS` in `reactions.py` is keyed by `frozenset`, so the rule is symmetric by
construction and order cannot matter. Same-tile only, which keeps it something a player can
predict by looking at one square.

| pair | result |
|---|---|
| fire + wet | both spent, steam |
| fire + ice | fire and ice spent, tile left wet |
| fire + sacred | fire spent, hallowed ground will not burn |
| acid + wet | acid runs off |
| acid + ice | acid crusts over, both spent |
| acid + sacred | opposites, both unmade |
| charged + sacred | the charge earths itself |
| charged + wet | the live chain, unchanged (a property of a component, not a tile) |

**8 of 15 pairs interact, from 2.** That is the plan's target, hit exactly. The seven that remain
inert are the ones with no physical story worth inventing.

### C2. Ice and hallowed ground bite

Ice now deals `_CHILL_DAMAGE` to the player and to creatures, scaled by affinity. Hallowed ground
now damages what it is the opposite of rather than healing it: it used to mend corrosive natives
too, which made `sacred` the one element that could not matter to anything.

Measured across six home elements and four hazard columns, **20 of 24 affinity cells now deal
damage**. The four that do not are exactly the correct self-immunities, so that is the ceiling.
All three opposite pairs are now live in both directions, from one.

### C3. Actors carry fire

The seam that turns tile-local chemistry into propagating chemistry. A creature standing in
flame catches at `BURN_CATCH_P`; while alight it takes damage scaled by its own affinity and
**sets light to the ground it walks over**; standing in water or on ice puts it out. Verified: a
burning creature moved three tiles and left fire on all three.

It is deliberately subcritical, and measured as such rather than argued: a burning creature
parked on ground it keeps re-lighting burns out and does not restart a self-feeding fire. Peak
fire tiles over 300 turns with an immortal creature standing in its own flame: 2.

One bug came out of writing it. Hazard tile damage is capped and clamped so the environment can
never kill the player, which means it can leave the player on 0 HP and still `alive`. Burning is
not capped, so a burning player was walking around dead. It now routes through the same death
path the bleeding tick uses, and a test pins it.

### What it cost, measured

Exploiter went from 1 win in 8 to 0 in 8. Isolating it by running the profile with and without
the tranche: **seven of the eight run seeds are identical outcomes**, and one flipped from a
floor-26 win to a floor-18 death. That run died to a monster with an average HP of 81.6, not to
the chemistry. Tranche C perturbed a seeded stream on a knife-edge run. The honest reading is
not that the chemistry is too harsh, it is that exploiter had no headroom to lose.

## Exploiter shielded hardest and had nothing to shield with

The same shape as cartographer, one profile over. `shield` is exploiter's highest weight by a
wide margin at 15, and its starting kit gave it two escape sigils and **no defensive stat at
all**. It took the most damage per floor of any profile, ground the middle floors, and won 0 of
8 run seeds.

Swept over eight run seeds:

| DEF bonus | wins |
|---|---|
| +0 | 0 of 8 |
| +1 | **3 of 8** |
| +2 | 5 of 8 |

Taking +1 rather than +2: 5 of 8 puts the fight-first profile above the target band and second
overall, which is not what a balance fix should produce. +1 clears "never wins" and leaves
emergent at +2 as the defensive profile. Starting state, which is the Berlin-legal lever; nothing
branches on the profile at decision time. The test generalises it: a profile whose top weight is
a defensive verb must not start with zero of that stat, or the weight is decoration.

The change is isolated. Artisan, cartographer, emergent, seeker and whisper report byte-identical
outcomes across all eight seeds before and after.

## Post-C baseline

8 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | win rate | avg floor | contested | labels | win paths |
|---|---|---|---|---|---|
| artisan | 50% | 20.4 | 29% | 29 | commune 2, escape 2 |
| cartographer | 50% | 18.1 | 70% | 25 | escape 3, commune 1 |
| emergent | 12.5% | 11.9 | 31% | 26 | commune 1 |
| exploiter | 37.5% | 20.4 | 23% | 28 | commune 3 |
| seeker | 50% | 21.1 | 41% | 29 | commune 3, boss_killed 1 |
| whisper | 87.5% | 24.0 | 36% | 28 | escape 5, commune 2 |

**Aggregate 23 of 48, 47.9%, inside the 40-60% band.** No verb has a 100% failure rate. All three
victory routes now appear in a single batch: escape 10, commune 12, and the first `boss_killed`
win the harness has ever recorded.

A measurement correction is owed here. The previous pass reported `negotiate` as a broken verb.
It was not: the aggregator took the **union of per-run verdicts**, so a verb that happened to
fail every attempt in one unlucky run was reported as globally broken. `negotiate` succeeds 20.9%
of the time in the very run that flagged it. The detector now sums attempts across runs and
judges on the totals, and `runtime/pressure.py` exposes the raw `verb_ok`/`verb_fail` counts so
an aggregate can do that.

## Still open after C

- **Emergent wins 1 of 8** and averages floor 11.9 with 24.8 kills, the most of any profile by a
  distance. It is the next profile with the cartographer/exploiter shape: it fights everything
  and dies in the first third. It has not been swept.
- **Emergent is the next profile to sweep** (see above).
- **Tranche D is untouched.** The runaway loop is still open: `to_upheaval_events` has no caller,
  grave escalation still cannot escalate (`game.py:455`), three of six attractor scores are
  structurally 0.0, and no feedback loop in the codebase has gain above 1.
- **The eighteen failing tests are unchanged.** They fail identically on `HEAD`, so nothing in
  this pass caused any of them. They are the body-parts, commune, becalm, forge, machines, qud,
  salvage, felt and ux-rest failures already recorded under F3. Spot-checked one of them,
  `test_ux.py::test_rest_camp`, against the commit before any of this work began: it fails there
  too, on a fixture that parks the player next to a hostile and then expects an uninterrupted
  camp.

## The sandbox could not build the world it ships with

Found while trying to run the suite, and worth its own section because it is the most serious
defect in this document. `python3 -m pytest tests/ -q` did not finish. It got OOM-killed twice
and then sat on one test for over ten minutes on an idle four-core machine with 15 GB free.

The stack, sampled with `faulthandler`:

```
runtime/arch/areakinds.py, line 78 in _flood
runtime/game.py, line 776 in _apply_area_shapes
runtime/game.py, line 699 in _build_sandbox
runtime/game.py, line 173 in __init__
```

`_flood` grows a blob of water from a seed cell. It expanded its frontier through **any**
neighbour:

```python
for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
    n = (x + dx, y + dy)
    if n not in seen and rng.random() < 0.75:
        seen.add(n); frontier.append(n)
```

Nothing bounds `n` to the region, or to the map. The blob walks off onto the open integer plane,
`seen` grows without bound, and at a 0.75 expansion chance in four directions the frontier gains
about three entries per pop, so it never empties. The loop's only other exit is `body` reaching
20 to 60, and `body` counts only cells that are inside the region and still floor. Once the
frontier is mostly off-map, that stops advancing.

One clause fixes it: expand only into `cellset`. Then `seen` is bounded by the region and the
loop has to terminate.

**`Game(examples/world.json, sandbox=True)` went from not finishing in ten minutes to 0.6
seconds. The full pytest suite went from unrunnable to 62 seconds, 265 collected, 247 passed.**

This is not a small bug in a corner. `runtime/arch/` is live, sandbox is the **default
interactive mode**, and the effect was that the game could not construct the world in
`examples/`. It went unnoticed because the interactive entry point passes
`site_cache=world.json.site.json` and there is a pre-grown cache file checked in beside the
world, so play loads the answer instead of computing it. Every test constructs `Game(sandbox=True)`
without a cache and paid the real cost. Two tests now pin it: one structural (the blob may not
write outside its own region), one end to end (a sandbox world can be built).

It also revises F3. The suite was never "45 of 65 modules, 16 failing". It was: pytest collects
265 tests, and it could not get through them.

## Tranche D: closing the runaway loop

The last open tranche, and the one the earlier audit was harshest about. Fourteen feedback
loops existed and every one was capped or subcritical; the cross-run layer was a facade of
thirty-three fields with no external readers; and the bake-to-play-to-bake circuit was
structurally open, because `bake.py` reads one input, the markdown directory, so nothing play
produced could reach a later world.

### D1. The circuit has a return arrow

`to_upheaval_events()` had zero callers, and wiring it up would have crashed:
`Upheaval.from_events` did `e["kind"], e["note"]` unconditionally while **six of the ten kinds
the producer emits carry no note key**. `from_events` now uses `e.get("note", "")`, and the
producer carries a note wherever a consumer keys on one.

The arrow itself is deliberately the small version: a run appends its events to
`~/.vaultcrawl/chronicle.json` under its world's seed, and the next run on that world loads
them as its Upheaval. The bake is untouched, so the deterministic skeleton is untouched.

Two runs, cold state, no notes edited and nothing re-baked:

```
=== descended 6 floor(s) | reached floor 7 | 1 kills | 0 items ===
--- run 2 ---
The vault remembers 1 thing(s) from before.
  ccee0b8af9afe4f7  1 events: ['forge_grown']
```

**That is the first Upheaval event this project has ever produced by playing it.**

Three things are load-bearing and each has a test:

- **It is bounded.** Events dedupe on identity and the store is capped at `CHRONICLE_MAX`, so a
  hundred runs on one world cannot accumulate a hundred ascended notes. A return arrow is not
  licence for unbounded growth.
- **It is opt-in.** `Game(chronicle_out=...)` defaults to False and the evaluation harness never
  turns it on. Cross-run state leaking into the benchmarks is the bug that invalidated an entire
  balance pass; this is the same class of state and it does not get to do that silently.
  `--no-chronicle` turns it off for play too.
- **Walking away counts as an ending.** Death and victory close the chronicle themselves, and a
  session that simply stops now closes it as well. The first version only recorded runs that
  ended badly, which was visible immediately: a six-floor demo wrote nothing at all.

### D2. Graves can escalate

The graves *file* has always appended every death. `_load_graves` assigned into a dict keyed by
position, so five deaths on one tile loaded as one record, and `_animate_graves` reads its scale
off `text.count("slain by") + 1`. **`deaths` was the constant 2, forever**: same HP, same attack,
same two specials, no matter how many times that tile had killed you. The loader accumulates now
and the count is exact.

### D3. The attractor frame is resolved rather than left half-built

The root cause was one line. `tracker()` was a factory returning a **new** `AttractorTracker` on
every call, so anything recording from inside the game wrote into a throwaway and dropped it.
That is why three of six scores were structurally 0.0: their recorders had nowhere to write even
if someone had called them. It is now a per-run singleton on the same pattern as
`persistence.chronicle()`, cleared by `reset_run_state()`.

With somewhere to write, the four dead recorders are wired: `record_note_learned` from
`knowledge._reveal`, `record_ghost_seen` from both ghost sources, `record_companion_died` from
`Game.kill`, `record_echo_fire` from the Echo sigil's death-save.

`record_companion_recruited` was worse than uncalled. It was called, on
`chronicle()`, and **RunChronicle has never had that method**, so it raised AttributeError into
a silent except from the day it was written. The method is on `AttractorTracker`, which is what
`companion_flux` actually scores.

`industrial` was directionally backwards. It divided by `inventory.total()` read at the end of
the run, which is a **residual**, so spending matter shrank the denominator and pushed the score
*up*. Intake is now counted cumulatively in `Inventory.add`, the only place matter enters an
inventory, and the forge records what it actually consumed rather than the harness guessing
`sigils_forged * 3` afterwards. Measured on one run: 171 collected, 56 forged, ratio 0.33.

`Dampener` is deleted. Both methods had zero callers and one was a declared no-op.

### D4. One loop with gain above 1

The alert track was the clearest subcritical case in the codebase. Four disturbance dispatched
1 to 2 hunters; killing both loudly returned 2 disturbance, so the loop gave back half of what
it cost and always died out. Hunter tier read the floor and nothing else, so provoking a house
repeatedly in its own country produced the same two guards forever.

`pursuit` is a per-faction memory of how many times that house has had to come after you. Each
dispatch deepens it, and a deeper grudge sends **more** hunters while needing **less** alert to
send them:

| grudge | hunters dispatched | alert needed | loop gain |
|---|---|---|---|
| 0 | 1 to 2 | 4 | 0.38 |
| 1 | 2 to 3 | 3 | 0.83 |
| 2 | 3 to 4 | 2 | **1.75** |
| 3 | 4 to 5 | 2 | **2.25** |
| 4 | 5 to 6 | 2 | **2.75** |

Past grudge 2 a wave returns more disturbance than the next wave costs. It compounds instead of
settling, and it reaches that depth in real play: one 26-floor run produced **16 waves and 71
hunters against roughly 24 under the old rule**, hitting the ceiling. (The 24 is the old rule's expected value over the same 16 waves,
`randint(1, 2)`, not a second measured run.)

Gain above 1 with no exit is a crash, not a game, so it terminates four ways and all four are
the player's to reach:

1. **Leave.** Pursuit decays every floor spent outside that house's country.
2. **Go quiet.** An environment kill is a thread the search loses, so it cools the grudge as
   well as the alert. The house cannot pursue what it never saw.
3. **Make peace.** A friend calling the hunters off already existed; it cleared the current wave
   and left the escalation running underneath. It now ends the grudge.
4. **A ceiling**, so a player who does none of the above still meets something finite.

Berlin holds: the escalation answers what you did, never who is playing, and a test asserts
`on_floor_enter` branches on no profile.

### What it cost, measured

8 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | post-C | post-D | win paths after D |
|---|---|---|---|
| artisan | 50% | 50% | commune 2, boss_killed 1, escape 1 |
| cartographer | 50% | 37.5% | escape 3 |
| emergent | 12.5% | **25%** | commune 1, escape 1 |
| exploiter | 37.5% | **12.5%** | commune 1 |
| seeker | 50% | 62.5% | commune 5 |
| whisper | 87.5% | 75% | escape 3, commune 3 |

**Aggregate 21 of 48, 43.75%, still inside the 40-60% band**, and the spread tightened at both
ends: the best profile came down from 87.5% and the worst came up from 12.5%. Emergent, flagged
last pass as the next profile to sweep, **doubled without being touched**: the escalation gave
the profile that fights everything something worth fighting. Event kinds per run went 12 to 13.

The cost lands on exploiter, 37.5% down to 12.5%. That is the profile that fights loud and stays
put, which is exactly the behaviour the escalation is built to punish, and its own weights put
every de-escalation tool near zero (`commune` 0, `parley` 1, `becalm` 1). Berlin-legal, since
those are preferences and not locks, but it undoes half of the previous pass's fix.

The obvious knob does not fix it. Sweeping the ceiling against exploiter over eight run seeds:

| `PURSUIT_MAX` | exploiter | peak loop gain |
|---|---|---|
| 4 | 1 of 8 | 2.75 |
| 3 | 1 of 8 | 2.25 |
| 2 | 2 of 8 | 1.75 |

Dropping to 2 buys back one win and costs the loop a third of its headroom. The ceiling is not
the lever, so it stays at 4 and exploiter goes on the open list rather than being papered over.

## Still open after D

- **Exploiter at 1 of 8** under the escalation. The lever is not the pursuit ceiling; the
  candidate is its own starting state again, or giving the loud playstyle a de-escalation route
  it will actually take.
- **The eighteen failing tests** are still the eighteen failing tests. They fail identically on
  every commit checked, including the one before this work began.
- **`arch/vaults.py`** still has zero callers and a data path resolving to a file that does not
  exist (plan item B5, deferred).
- **The bake still reads one input.** D1 closes the play-to-play circuit, not the play-to-bake
  one. Whether a chronicle should be able to change a bake is a design question, not a bug, and
  it is the one place the deterministic skeleton would actually be at risk.

## The ratchet under exploiter

Exploiter was the last profile that barely won, at 1 run in 8. Four levers were tried and
measured before the actual cause turned up, and the negative results are the useful part of
this section, because each one was a plausible story that the numbers refused.

### What it was not

**Not the escalation.** The obvious suspect, since D4 had just made hunters compound and
exploiter fights loud and stays put. Instrumented against seeker over 8 seeds each:

| | waves | hunters faced | loud kills | quiet kills |
|---|---|---|---|---|
| exploiter (1 win) | 87 | 387 | 135 | 590 |
| seeker (5 wins) | 119 | **522** | 155 | 530 |

Seeker faces a third more hunters and is the *louder* of the two in absolute terms, and wins
five times as often. The escalation is not what separates them.

**Not defence.** +2 DEF won 5 of 8 before Tranche D and 1 of 8 after. Whatever it was
compensating for, the game moved past it.

**Not the rest weight.** Raising exploiter's `rest` from 3 to 5 bought one win, and the
mechanism is not the one it looks like: rest urgency is `(100 - hp) // 3`, which runs 10 to 30
inside the window the branch is reachable at all, and every profile's rest floor is at most 5.
The floor never decides a heal for anybody. It is not a dead weight, though, which is a trap
worth recording: `clear_weather` and `absorb_hazard` score off the same `rest` key at much
lower urgencies, so tuning it changes what the agent does about weather and hazard tiles and
not how often it heals.

**Not a reputation thaw.** Standing had no decay at all while D4 had just given the faction's
pursuit one, so the asymmetry was real and worth closing. It is worth almost nothing:
21, 22, 21 of 48 at thaw 0, 1, 2. Kept at 1 because it closes a genuine one-way ratchet, not
because it moved the game.

**Not the inverted parley urgency**, though that is a real bug. Parley's urgency was
`standing * 3`, which goes negative exactly when a house dislikes you, so the one action that
buys standing back became least attractive precisely when it was most needed. Building that
into a proper amends ladder measured **exactly zero** over 48 runs, because the branch needs a
tier-3 encounter option that rarely appears. The ladder is not shipped; a one-line `max(0, ...)`
guard is, as insurance against the sign error returning, and it is provably behaviour-neutral
given the floor below.

### What it was

Standing measured at the end of every run told the story at once:

| | standing at end of run |
|---|---|
| exploiter | -10, -10, -22, -20, -3, and **+7 on its one win** |
| seeker | -2, 0, +2, +6, +3, +3 |
| whisper | +4, +6, +9, +12, +14, +6 |

Standing fell 1 per heard kill with **nothing underneath it**, and `rest_modifier` returns 0
below standing -3. Past that point resting in that house's country restores nothing at all. So
the loop closes: kill loudly, lose the heal, have to keep killing to survive, lose more
standing. That is a feedback loop with gain above 1 and no terminating condition, which is
precisely the thing D4 was careful to give four exits to, sitting unnoticed on the player's
side of the same system.

Confirmed by probe rather than by argument. Removing the standing gate outright, which is far
too strong to ship and was never meant to be:

| | wins | avg floor |
|---|---|---|
| as shipped | 1 of 8 | 15.1 |
| standing gate removed | **5 of 8** | **21.8** |

That is the constraint.

### The fix, swept

`STANDING_MIN` bottoms out what heard kills can cost you. The penalty stays and the lockout
goes: at the floor a rest still restores 1 against a friendly 3, so being hated costs two
thirds of the heal rather than all of it. Same shape as the pursuit decay in D4, which is a
steep loop given a terminating condition rather than a cap.

| floor | aggregate | artisan | cartographer | emergent | exploiter | seeker | whisper |
|---|---|---|---|---|---|---|---|
| none | 21/48 (43.8%) | 4 | 3 | 2 | **1** | 5 | 6 |
| -3 | 23/48 (47.9%) | 4 | 3 | 1 | 3 | 6 | 6 |
| **-2** | **24/48 (50.0%)** | 4 | 3 | 3 | **5** | 3 | 6 |
| -1 | 27/48 (56.2%) | 4 | 4 | 3 | 6 | 4 | 6 |

**-2 is taken.** The aggregate lands dead centre of the 40-60 band, the spread closes to 3-6
from 1-6, and exploiter is fixed without becoming the strongest profile, which -1 does. -3 is
worth noting for a reason I got wrong beforehand: I expected it to behave like no floor at all,
since `rest_modifier` is 0 at -3 either way. It does not, because standing also feeds parley
urgency, the faction perk ladder and the hunters-stand-down check. Standing is worth more than
its healing.

Berlin holds throughout. The floor is a property of the reputation system, identical for all
six profiles, and it lands hardest on whoever spends the most reputation, which is a
consequence of how a run is played rather than of who is playing it.

One test changed with the rule: `test_factions.py` asserted standing falls exactly 1 per loud
kill forever. It now asserts it falls per kill down to the floor.

### Baseline after the floor

8 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | win rate | avg floor | deepest | contested | labels | win paths |
|---|---|---|---|---|---|---|
| artisan | 50% | 21.1 | 27 | 30% | 29 | commune 2, boss_killed 1, escape 1 |
| cartographer | 37.5% | 16.4 | 27 | 72% | 26 | escape 3 |
| emergent | 37.5% | 13.8 | 27 | 28% | 26 | escape 2, commune 1 |
| exploiter | **62.5%** | 22.5 | 27 | 24% | 28 | commune 3, escape 2 |
| seeker | 37.5% | 21.5 | 27 | 36% | 29 | escape 2, commune 1 |
| whisper | 75% | 22.0 | 27 | 36% | 27 | escape 3, commune 3 |

**24 of 48, 50.0%**, the centre of the target band, and the spread is 37.5 to 75 against the
12.5 to 87.5 this pass started from. Three things worth noting beyond the aggregate:

- **Every profile now reaches floor 27**, the first time that has been true of all six.
- **Every profile now has more than one victory route** except cartographer. Exploiter in
  particular went from commune-only to commune 3 and escape 2: it is not winning one way by
  luck, it has two.
- Across the batch: escape 13, commune 10, boss_killed 1.

The cost is spread across the middle rather than concentrated. Seeker fell 62.5 to 37.5 and
cartographer 50 to 37.5, both of which were partly living off being the only profiles that
could keep their standing out of the dead zone. That advantage was an artifact of a broken
ratchet, so losing it is the fix working rather than a regression, but it is a real change to
two profiles that were not the target and it is recorded as such.

## Still open

- **The eighteen failing tests.** Unchanged, and they fail identically on the commit before
  any of this work began. `test_factions.py` was updated deliberately with the standing floor
  and passes.
- **`arch/vaults.py`** still has zero callers and an unresolvable data path (plan item B5).
- **The bake still reads one input.** D1 closed the play-to-play circuit, not play-to-bake.
- **Cartographer is the only profile with a single win route**, all three of its wins by
  escape. It is not failing, but it is the least robust of the six.

## Cartographer dies early or wins late

The last profile on the open list, at 3 wins in 8 and the only one with a single victory
route. End-of-run state across 8 seeds says the two facts are the same fact:

| | outcome |
|---|---|
| wins (3) | floor 27, standing 7 to 22, escape, 3,900 to 6,900 turns |
| losses (5) | floors 5, 5, 12, 13, 15, and three of them inside 1,600 turns |

There is no middle. When it survives the first third its standing compounds and the escape
route opens comfortably; when it does not, it is dead on floor 5. That is a profile with a
strong late game and no early game, not one that is weak overall.

The cause is in its own weights rather than in the world. `fight` at -5 sets its flee cutoff
to `40 + (5 - fight) * 5`, which is **90 percent HP**: it runs from almost everything, and it
kills 2 to 6 things in a whole run. So it can never clear a threat, only outrun one, and an
early elite that corners it before its standing is worth anything simply kills it.

### Swept

Four starting-state arms over 8 run seeds:

| arm | wins | avg floor | routes |
|---|---|---|---|
| baseline | 3/8 | 16.4 | escape 3 |
| +4 more max HP | 3/8 | 16.4 | escape 3 |
| Phase durability 2 to 4 | 3/8 | 17.1 | escape 3 |
| **+1 DEF** | **4/8** | **20.2** | **escape 3, boss_killed 1** |
| +2 DEF | 4/8 | 20.2 | escape 4 |
| +3 DEF | 2/8 | 15.9 | escape 2 |

**More HP is byte-identical to the baseline.** That is the second time raw HP has measured
inert for this profile, the first being when its old +8 was trimmed to +4. What it lacked was
never a bigger pool, it was any ability to take a hit at all: at 90 percent flee it is barely
ever in a fight long enough for HP to be what runs out.

**+1 DEF is taken.** It matches the best win count and it is the only arm that produced a
second victory route, which is the actual complaint about the profile. Two caveats stated
rather than hidden: the response is **not monotonic**, since +3 is worse than +0, so eight
seeds is a coarse instrument here and +1 wins the tiebreak on route diversity and not on a
clean gradient.

### Baseline after both profile fixes

8 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | win rate | avg floor | deepest | contested | win paths |
|---|---|---|---|---|---|
| artisan | 50% | 21.1 | 27 | 30% | commune 2, boss_killed 1, escape 1 |
| cartographer | **50%** | 20.3 | 27 | 68% | escape 3, boss_killed 1 |
| emergent | 37.5% | 13.8 | 27 | 28% | escape 2, commune 1 |
| exploiter | 62.5% | 22.5 | 27 | 24% | commune 3, escape 2 |
| seeker | 37.5% | 21.5 | 27 | 36% | escape 2, commune 1 |
| whisper | 75% | 22.0 | 27 | 36% | escape 3, commune 3 |

**25 of 48, 52.1%.** The change is isolated: the other five profiles report identical numbers
to the previous run across all eight seeds.

Two properties hold for the first time in this project:

- **Every profile reaches floor 27**, and
- **every profile wins by at least two different routes.** Across the batch: escape 12,
  commune 7, boss_killed 2. At the start of this work the win path was a monoculture and three
  profiles never won at all.

The spread is 37.5 to 75 percent. Seeker and emergent are now the low pair, both at 37.5, and
both for reasons that have not been investigated; they are inside the target band, so they are
noted rather than swept.

## Seeker and emergent: the same score, two different faults

Both sat at 37.5 percent, and the shape of the two runs said immediately they were not the
same problem.

| | avg floor | kills | losses |
|---|---|---|---|
| seeker | 21.5 | 13.2 | floors 24, 21, 18, 15, 14 |
| emergent | 13.8 | 21.9 | floors 13, 6, 5, 4, 2 |

Seeker gets deep and fails to close. Emergent dies in the first sixth or snowballs to floor 26
with 46 kills, with nothing in between.

### Seeker had no way to panic

The brain's panic branch, taken at low HP with hostiles near, can do exactly one thing: cast a
Phase sigil. Seeker started with **Ward and Recall**, so it could not take that branch at all,
which is the gap cartographer once had. Three of its five losses ended with its standing at the
floor and a hunter finishing it, which is precisely what the panic branch exists for.

| arm | wins | avg floor |
|---|---|---|
| baseline (Ward, Recall) | 4/8 | 22.5 |
| **+ Phase** | **5/8** | **23.6** |
| +2 DEF | 4/8 | 22.1 |

Defence on the same seeds changed nothing, so this is about having an escape and not about
durability.

**A correction, caught by its own test.** Writing this up I claimed the two profiles at the
bottom of the table were exactly the two without Phase. They were not: **artisan has never
carried Phase and sits mid-table at 50 percent**. A missing escape does not by itself explain a
weak profile. It explained this one. The test now names the profiles without Phase as a
deliberate list rather than asserting a rule that does not hold.

### Emergent was never descending

Its `stairs` weight was 1, the joint lowest in the table, and unlike `rest` that floor is live:
the stairs candidate's base state urgency is 2, so the profile weight genuinely decides. Dying
on floor 2 after 625 turns is 300 turns spent on a single floor. It was not a descent going
wrong, it was no descent at all.

| arm | wins | avg floor | routes |
|---|---|---|---|
| baseline (`stairs` 1) | 3/8 | 13.8 | commune 1, escape 2 |
| **`stairs` 3** | **5/8** | **18.5** | commune 2, escape 3 |
| `stairs` 6 | 2/8 | 13.5 | commune 1, escape 1 |
| `explore` 5 | 4/8 | 17.9 | commune 1, escape 3 |
| Phase + 2 DEF | 5/8 | 18.9 | commune 2, escape 3 |
| `stairs` 3 + Phase | 4/8 | 20.6 | commune 2, escape 2 |

`stairs` 3 and Phase-plus-defence tie at 5 of 8. The weight is taken: one number against two
grants, and it is what the diagnosis predicted. `stairs` 6 overshoots badly, arriving
underlevelled, and doing both fixes at once is worse than either alone, which is another
reminder that eight seeds is a coarse instrument.

Berlin holds. A weight is a preference and never a lock, `fight` stays at 15, and emergent
still fights everything it meets. It just stops parking on floor 2 to do it. Note also that
`stairs` 2 would be identical to `stairs` 1, since both lose to the base urgency of 2, so this
knob has no intermediate setting.

### Baseline, and an overshoot to report

8 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | before | after | win paths |
|---|---|---|---|
| artisan | 50% | 50% | commune 2, boss_killed 1, escape 1 |
| cartographer | 50% | 50% | escape 3, boss_killed 1 |
| emergent | 37.5% | **62.5%** | escape 3, commune 2 |
| exploiter | 62.5% | 75% | commune 4, escape 2 |
| seeker | 37.5% | **62.5%** | commune 4, escape 1 |
| whisper | 75% | 75% | escape 3, commune 3 |

**30 of 48, 62.5%, which is above the stated 40-60 band.** Two things have to be said plainly
about that number rather than buried:

- **Exploiter appeared to gain a win without being touched.** The explanation given here at
  first was wrong twice over and is corrected below, under "the extra win was neither".
- **The band is now the open problem, not the profiles.** Every profile is between 50 and 75
  percent, which is the tightest the table has ever been, and the game as a whole is easier
  than the target. Restoring the band means tightening something global.

`event kinds per run` rose 12 to 13. Every profile still reaches floor 27 and still wins by at
least two routes.

## The extra win was neither contamination nor order

Exploiter came out of one eval at 75 percent and out of the next, on identical code, at 62.5.
The first explanation offered here was that profiles run sequentially against a shared
`~/.vaultcrawl` and an earlier profile surviving longer warms the forge cache for a later one,
making the aggregate order-dependent. **Both halves of that are wrong**, and the second attempt
was wrong too. Recorded in full, because a balance instrument that is trusted while it is
wrong is worse than no instrument.

**There is no forge cache.** Nothing writes one. In descent mode the only file the runtime puts
under `~/.vaultcrawl` is `graves.json`, and `_load_graves` is called only on the sandbox branch,
so a descent run can write graves and can never read them back.

**It is not order.** Measured directly: exploiter run first in a fresh process, and exploiter
run after artisan, cartographer and emergent in the order the harness actually uses, give
**byte-identical floors**, `[24, 26, 27, 26, 27, 26, 12, 12]`, 5 of 8 both ways.

**It is not `max_floor` either**, which is the next thing that looked suspicious: every sweep in
this document passes `max_floor=27` while the harness defaults to 99. Also byte-identical, since
the world's own floor count binds first.

What it actually is: comparing the two evals run by run, **exactly one of the 48 differs**. Run
25, exploiter on run seed 0, is `F26 WON` in one and `F24 DIED` in the other, and the other 47
match. Two independent reproductions of that seed outside the harness both give F24. So the
harness carries a residual non-determinism of roughly **one run in 48, about 2 percent**, which
is consistent with the known-issues note about cross-process variance, except that the note
claims runs reproduce exactly at a fixed `PYTHONHASHSEED` and they do not.

Two consequences worth carrying forward:

- **A single run is not evidence.** An 8-seed arm carries roughly plus or minus one win of
  noise on its own, which is 12.5 percentage points. Several arms in this document tie or
  invert inside that margin (cartographer's +3 DEF, emergent's stairs-plus-Phase), and the
  right reading of those is "not distinguishable", not "worse".
- **The real aggregate is 29 of 48, 60.4 percent**, not the 62.5 first reported. That is at
  the top edge of the target band rather than clearly outside it.

## Restoring the band

Four passes of repair had left the aggregate at **29 of 48, 60.4 percent**, at the top edge of
the 40-60 target. Fixing it needed a global knob rather than another profile patch, since the
profiles themselves were now the tightest they have ever been.

The descent mend is the right lever, and for a specific reason: `entities.py` says outright
that the player never gains stats during a run, so the mend is the **only resource in the game
that scales with depth**. Every profile depends on it equally. A profile-side knob would have
moved one agent and called it balance.

Swept over 8 seeds per agent across all six profiles:

| mend | aggregate | artisan | cartographer | emergent | exploiter | seeker | whisper |
|---|---|---|---|---|---|---|---|
| `//3` | 29/48 (60.4%) | 4 | 4 | 5 | 5 | 5 | 6 |
| **`//4`** | **27/48 (56.2%)** | 5 | 4 | 4 | 3 | 6 | 5 |
| `//5` | 27/48 (56.2%) | 5 | 3 | 4 | 5 | 5 | 5 |

**It saturates in this direction as well.** `//4` and `//5` give the same aggregate, so `//4`
is taken as the smaller change. The knob had already been shown to saturate the other way at
`//3`, which means the mend has a usable range of exactly one step, and pushing further would
buy nothing.

### Confirmed baseline

8 runs per agent, clean state, `PYTHONHASHSEED=0`. The confirming eval reproduces the sweep
exactly:

| agent | win rate | avg floor | contested | win paths |
|---|---|---|---|---|
| artisan | 62.5% | 20.4 | 34% | escape 3, commune 1, boss_killed 1 |
| cartographer | 50% | 20.0 | 62% | escape 2, commune 2 |
| emergent | 50% | 17.9 | 29% | escape 2, commune 2 |
| exploiter | 37.5% | 19.5 | 23% | commune 3 |
| seeker | 75% | 24.3 | 36% | commune 6 |
| whisper | 62.5% | 21.4 | 32% | escape 2, commune 2 |

**27 of 48, 56.25 percent, inside the band.** Every profile is between 37.5 and 75 percent and
every profile still reaches floor 27.

Two things to hold honestly against that:

- **Exploiter and seeker each show a single route in this batch**, where the previous baseline
  had every profile winning at least two ways. Four of the six still do. At one win of harness
  noise per arm this is not clearly a real loss of route diversity, but it is a real change from
  what was reported last pass and it should not be quietly dropped.
- **The win mix tilted toward commune**: escape 9, commune 16, boss_killed 2, against escape 13,
  commune 10, boss_killed 2 before. A smaller mend hurts the long grind that the escape route
  rewards more than it hurts talking to the warden.

### The instrument's own error bar, stated

Everything above is 8 seeds per arm, and the harness flips about **one run in 48** between
processes on identical code. That is roughly **plus or minus 12.5 points on a single profile's
8-seed arm** and about 2 points on the aggregate. Differences smaller than that in this document
are not differences. The aggregate figures are the ones worth trusting, because they average
six arms; the per-profile columns should be read as approximate.

## The route diversity regression was mostly noise, and the real defect resisted the fix

Two profiles came out of the band-restoring eval showing a single win route where the
previous baseline had all six winning at least two ways. Re-measured at **16 seeds**, which
halves the error bar:

| profile | 8 seeds | 16 seeds |
|---|---|---|
| exploiter | commune 3 | commune 4, escape 4 |
| seeker | commune 6 | **commune 8** |
| artisan | escape 3, commune 1, boss_killed 1 | boss_killed 1, commune 2, escape 4 |

**Exploiter's single route was an artifact of the sample size**, exactly as the error bar
predicted. Seeker's is real and holds at 16 seeds.

### The finding underneath it

Recording, for every run, which egress route was satisfied by the end whether it won or not,
turned up something the win-path column cannot show. Across **48 runs and three profiles**:

| route satisfied | count |
|---|---|
| the warden dealt with | 15 |
| standing with its house | 10 |
| **truths** | **0** |
| nothing | 23 |

**The truths route is dead.** It is one of the four authored ways to open the last stair, and
in 48 runs it never once opened it. The immediate cause looked obvious and matched a bug class
this project has hit before: `agent_state` reported `truths_read` as a bare count and **never
said where a mark was**, so the agent could only read one by walking over it by accident. That
is the same shape as `dialogue` before Tranche B, a fully authored system with no hand to knock.

### The fix failed, and the negative result is the useful part

Perception gained the mark positions and the brain gained a `read_mark` candidate scored off
`explore`. Three configurations were measured, each over a full slate:

| configuration | truths satisfied /48 | aggregate |
|---|---|---|
| no candidate | 0 | 27/48 (56.2%) |
| range 14, urgency opens at 4 | 2 | 33/48 (68.8%) |
| range 14, urgency opens at 3 | 1 | (not run to slate) |
| range 6, urgency opens at 3 | 0 to 1 | 31/48 (64.6%) |

**It never revived the route it exists for, and it broke the band every time.** The reason is
visible once stated: walking up to fourteen tiles to a mark is fourteen tiles of free map
coverage, so the candidate worked as a general exploration buff rather than as a route to the
last stair. Narrowing it to six did not restore the band either, and cartographer swung 4, then
6, then 2 wins in eight across the three configurations, which is most of the whole range the
profile has.

One useful piece of it survived as a rule rather than as code: the first version opened at
urgency 10, which is above four of the six `explore` weights, so the profile gradient it
claimed to inherit was a fiction and every profile detoured equally.

**Reverted.** A change that fails its stated purpose while moving the aggregate 8 points is not
a fix, and shipping it because it happens to improve a metric it was not aiming at is the exact
habit invariant 7 exists to prevent. The tree is back to 27 of 48, 56.25 percent.

### What is actually open

- **The truths route needs a design decision, not a scoring tweak.** Giving the agent eyes and
  a candidate for marks did not move it, so the constraint is elsewhere: `on_floor_enter`
  scatters at most 2 marks per floor and only from notes not yet spent, against a threshold of
  `notes // 2`, bounded to 3 to 8, which is 5 on the sample vault. Whether that is a supply
  problem, a threshold problem, or a geometry problem is measurable, and none of it was
  measured here.
- **Seeker really does win one way**, communing with the warden in 8 of 8 wins at 16 seeds.
  That is a genuine single route and it is still open.
- **The game-level mix is healthy** even so: escape 9, commune 16, boss_killed 2 across the
  batch, so all three win paths are live and it is one profile, not the game, that is
  monolithic.

## Measuring the truths route: supply, threshold, placement

Four measurements, and the first one retracts a claim from the previous section.

### Correction: it is not 0 of 48, it is 3 of 48

The earlier census recorded which egress route each run had satisfied using an **elif
chain**, so a run that satisfied truths *and* had dealt with the warden was recorded only as
"boss". The four routes are a **disjunction, not a partition**, and counting them as one
produced "the truths route is satisfied 0 times in 48 runs".

Counted independently, over the same 48 runs:

| route | runs satisfying it |
|---|---|
| standing with the warden's house | 33 (69%) |
| the warden dealt with | 18 (37.5%) |
| **truths** | **3 (6.3%)** |
| at least one | 34 (71%) |

The route is rare, not dead. That materially changes the previous section: the `read_mark`
experiment was aimed at a problem that was overstated by my own instrument. Reverting it was
still right, since it failed to move even the corrected number and cost 8 points of aggregate,
but the reasoning is corrected here.

### Supply: adequate, with a wrinkle

Walking a full 26-floor descent and counting what is offered without reading any of it:

| | |
|---|---|
| notes in the vault | 10 |
| notes with a community (eligible to yield a mark) | 10 |
| marks scattered per floor | exactly 2 |
| total mark-slots over the descent | 52 |
| **distinct notes ever offered** | **8** |
| threshold (`notes // 2`) | 5 |
| headroom | 3 |

**Supply is not the constraint.** But note the wrinkle: the threshold is computed from the
vault's 10 notes while only **8** are ever placed. Two, `grocery list` and `rust`, never
appear on any floor in a full descent. So the route asks for 5 of the 8 that can actually be
had, which is 63% of the real supply rather than the 50% the formula intends.

### Payout: exactly 1:1, and 100%

The suspicion was that `on_player_act` consumes a mark unconditionally (popped from `ground`,
added to `spent` forever) while granting the truth only if `weave()` returns a non-empty line,
which would burn supply without paying. Measured at the source inside real runs:

```
cartographer s0  scattered 45  stepped on 6  truths granted 6
whisper      s3  scattered 37  stepped on 8  truths granted 8
```

**Stepped-on equals granted in every run**, and probing `weave()` 100 times per note across
all ten notes gives a **100% pay rate**. The conditional is real but never fires on this
vault. It remains a latent hazard for a vault whose corpus is thinner, and it is worth a
guard, but it is not what is happening here.

### Placement: this is the constraint

Distance from the tile a run arrives on to the marks on that floor, over all 26 floors:

| | |
|---|---|
| min | 1 |
| **median** | **13** |
| max | 41 |
| marks within 6 tiles of arrival | 14 of 52 (27%) |
| marks within 14 tiles | 28 of 52 (54%) |

And what runs actually collect: **0 to 8 marks stepped on** out of 10 to 52 scattered, median
about 4, against a threshold of 5.

### The answer

Not under-supplied. Not broken. **Mis-priced, and the price is geometric.**

To open the stair by truths you must step on 5 of the 8 distinct notes the run will ever
place, each sitting a median 13 tiles off your arrival point, while the two routes it competes
with cost nothing extra: standing accrues from the fighting and talking a run does anyway, and
the warden is directly on the way down. That is why it lands at 6% against 69% and 37.5%.

Two changes follow from this, and **neither is made here, because a threshold change needs a
full-slate sweep and this was a measuring exercise**:

- **Scale the threshold to the notes that can actually appear**, not to the vault's note
  count. `egress_truths_needed()` intends half the vault and delivers 63% of the reachable
  supply. Basing it on placed notes would restore the intent without touching the geometry.
- **Guard the payout conditional.** A mark should not be spent when `weave()` returns nothing.
  It never fires on this corpus, so the change is free here and prevents a thin-corpus vault
  from silently destroying its own route.

## Shipping both truths-route fixes

Both changes from the measurement above, swept and taken.

### The payout guard

`on_player_act` added the note to `spent` **before `weave` was even called**, so a note that
wove nothing was gone from every later floor and paid nothing for it. With the route needing
most of the roughly 8 notes a descent places, each silent step cost it an eighth of its own
supply. The note is now spent only when it actually says something; the mark still leaves the
floor, so standing on it does not re-roll every turn.

It never fires on this corpus, where `weave` pays 100 times out of 100 on all ten notes, so it
is behaviourally free here. It is a guard for a vault too thin to weave from, which is exactly
the vault that can least afford to lose a route. Two tests pin it: a silent mark pays nothing
and is not burned, and a speaking mark is still spent exactly once, which was the
unbounded-truths bug and must stay fixed.

### The threshold basis

`egress_truths_needed()` intended half the vault's notes and delivered 63 percent of the
obtainable supply, because only 8 of 10 notes are ever placed. Swept over 8 seeds per agent
across all six profiles, judged on both axes, since a cheaper threshold revives the route and
also raises the win rate:

| tenths | threshold | aggregate | truths route | profile spread |
|---|---|---|---|---|
| 5 (old) | 5 | 27/48 (56.2%) | 3/48 (6.3%) | 3 to 6 wins |
| **4** | **4** | **26/48 (54.2%)** | **6/47 (12.8%)** | **4 to 5 wins** |
| 3 | 3 | 23/48 (47.9%) | 9/46 (19.6%) | 2 to 6 wins |

**4 is taken.** The route doubles, the aggregate is unchanged inside the instrument's own
noise and stays in the band, and the profile spread is the tightest this project has measured.
3 revives the route further and puts the aggregate nearer the middle of the band, but it widens
the spread back to 25-75 percent and drops exploiter to 2 of 8, undoing an earlier fix. A route
is not worth a profile.

The denominators differ (48, 47, 46) because a run that neither wins nor dies never closes its
chronicle and so reports no end-state snapshot.

### Confirmed baseline

The confirming eval reproduces the sweep exactly. 8 runs per agent, clean state,
`PYTHONHASHSEED=0`:

| agent | win rate | avg floor | contested | win paths |
|---|---|---|---|---|
| artisan | 50% | 19.0 | 31% | escape 3, boss_killed 1 |
| cartographer | 50% | 20.0 | 62% | escape 2, commune 2 |
| emergent | 50% | 17.9 | 29% | escape 2, commune 2 |
| exploiter | 50% | 19.8 | 23% | commune 4 |
| seeker | 62.5% | 23.0 | 37% | commune 5 |
| whisper | 62.5% | 21.5 | 33% | escape 3, commune 2 |

**26 of 48, 54.2 percent**, and **every profile sits between 50 and 62.5 percent**, a spread of
one win. Four of six win by two routes; exploiter's single route in this batch is the
sample-size artifact already characterised, and seeker's is the genuine one still open.

For the record, where the four egress routes now stand across 47 snapshots: standing 32,
warden 16, truths 6. The truths route is no longer a rounding error, and it is still the
expensive one, which is the right shape for a route whose price is paid in detours.
