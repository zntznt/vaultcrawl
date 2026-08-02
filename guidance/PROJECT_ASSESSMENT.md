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
| ~~F1~~ | ~~Four player verbs are unreachable dead code~~ CLOSED, see "F1 closed" below | `runtime/play.py`, `tests/test_keys.py` |
| F2 | 20 of 66 test modules collect zero tests under pytest | `tests/test_integration.py` et al |
| F3 | 16 collected tests fail on HEAD | 7 modules, see below |
| ~~F4~~ | ~~No CI runs any test~~ CLOSED, see "F4 closed" below | `.github/workflows/ci.yml` |
| F5 | Stated invariants unenforced and broadly violated | `CLAUDE.md:79,80,85` |
| ~~F6~~ | ~~mtime reaches the mechanical layer of the bake~~ CLOSED, see "F6 closed" below | `vaultcrawl/mapping.py` `activity_map()` |
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

### F1. Four player verbs are unreachable dead code [CLOSED]

*Closed. The finding as written follows, and it was right about the mechanism and wrong about
the price: it cost seven systems' interaction handlers and the whole quest-acquisition path, not
four verbs. See "F1 closed" at the end of this document.*


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

### F4. No CI runs any test [CLOSED]

*Closed by `.github/workflows/ci.yml`. The finding as originally written follows; what was
built, and what it still does not cover, is in "F4 closed" at the end of this document.*

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

*Partly addressed. The `house-style` job in `.github/workflows/ci.yml` now fails a pull
request whose added lines contain an em dash. The back catalogue is untouched, 552 and 368 as
of this commit, so the rule binds new work only. See "F4 closed".*

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

### F6. mtime reaches the mechanical layer of the bake [CLOSED]

*Closed. The finding as written follows, and it understated the reach: the bake was the
smaller half, and six mechanical consumers in the RUNTIME read `activity` back out of
the manifest. See "F6 closed" at the end of this document.*

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

### F11. Verb vocabulary has drifted from every document [CLOSED]

*Closed. `AGENT_SPEC.md`, `CLAUDE.md`, `README.md` and the `agent_action.py` docstring and
dataclass comment all say 19 now, and all list the same 19. The two dead verbs below are
recorded rather than removed.*

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

*Done. See "F1 closed". The count below was wrong: seven, not eight, and two of the eight
named were already reachable.*

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

## The warden commune was free, and that is why one profile won one way

Seeker won by `commune` in 8 runs of 8. The first instinct was a seeker problem, and the
levers that follow from that reading were swept and did almost nothing:

| arm | wins | routes |
|---|---|---|
| baseline | 5/8 | commune 5 |
| a point of starting standing | 5/8 | commune 5 |
| `becalm` 3 to 6 | 5/8 | commune 4, escape 1 |
| `parley` 3 to 6 | 5/8 | commune 5 |

The standing arm is byte-identical to baseline, which is its own small lesson: `FactionSystem`
builds its standing dict lazily on the first floor, so a starting kit that writes standing
before that runs writes into an empty dict. The measurement that mattered was the other column:
**seeker's standing at end of run reads 7, 3, 8, 0, 4, 5, 19, 0.** It builds standing perfectly
well. It never *needs* it.

### Why

`Game.commune`, on the final boss, said so in its own comment: the win condition was
labelled **always free**, on the grounds that reaching the boss is enough.

Every other commune in the game is priced at `COMMUNE_TRUTHS` with a standing discount, or paid
in matter. **The single commune that ends the run was the one exception.** Walk adjacent to the
warden, and you have won. That is why commune took 16 of 26 wins, and why the profile that most
reliably reaches the warden won that way every time: not a preference, just the cheapest thing
on the board being free.

**Two of the eighteen long-standing test failures were flagging exactly this.**
`test_commune.py::test_unknown_refuses` asserts `commune()` returns **False** with no truths and
no matter. `test_offering_path_spends_matter` asserts it spends `COMMUNE_COST`. Both had been
failing since before this work began. The free path was not a design choice, it was a
regression against a design the test file still documents.

### Fixed

The warden is priced like any other elite. The standing discount still applies, so a house that
vouches for you can still make it free, which is the intended shape. The discount and the
payment are now shared helpers rather than duplicated, so there is no longer a second place for
the two to drift apart.

The value is not a free parameter: `test_truths_path_wins_without_a_kill` wins on exactly 3
truths, which at the standing-0 discount pins `BOSS_COMMUNE_TRUTHS` at **2**. The test file
chose the number; the sweep only confirmed it sits in band.

**`pytest` goes 18 failures to 16.** That is the first time in this entire pass that the count
has moved.

### Measured

8 runs per agent, clean state, `PYTHONHASHSEED=0`. The confirming eval reproduces the sweep
exactly:

| agent | win rate | win paths |
|---|---|---|
| artisan | 50% | escape 3, boss_killed 1 |
| cartographer | 50% | escape 2, commune 2 |
| emergent | 50% | escape 2, commune 2 |
| exploiter | 37.5% | commune 2, boss_killed 1 |
| seeker | 37.5% | **commune 3** |
| whisper | 62.5% | escape 3, commune 2 |

**23 of 48, 47.9 percent**, in band and nearer its middle than before. The win mix moved from
commune 16 / escape 9 / boss 1 to **escape 10 / commune 11 / boss 2**, which is near parity
where it used to be a monoculture, and **five of six profiles now win by two routes** where
four did.

### Seeker is still not fixed, and this is why

It is the one profile the change did not move, and the eval says why in a column that was not
there before: **seeker's top choice is now `commune` at 22 percent of all turns.** It does not
merely accept the commune win when it arrives, it spends a fifth of its decisions steering
toward the warden. Pricing the destination does not deter something that wants the destination
that much.

The next thing to look at is not seeker's kit but the `commune_pull` in the stairs candidate,
which adds 20 to 38 to the score of descending once `commune_ready` is true, a bonus far larger
than any profile weight in the table. That is a global scoring term, it will move every profile,
and it has not been swept.

## Sweeping the commune pull: seeker fixed, and the monoculture moved

The last section left seeker winning one way and named the reason: `commune_pull` adds
`COMMUNE_PULL_BASE` plus 2 per floor of closeness to the stairs candidate once the warden is
reachable. At base 20 that is **20 to 38, against a table whose largest profile weight is 15**.
Once commune came online, nothing any profile wanted could outbid descending.

Swept over 8 seeds per agent across all six profiles, judged on route diversity first:

| base | aggregate | profiles winning 2+ ways | win mix |
|---|---|---|---|
| 20 (old) | 22/48 (45.8%) | 4 of 6 | commune 11, escape 10, boss 1 |
| **12** | **25/48 (52.1%)** | **6 of 6** | commune 9, escape 16 |
| 6 | 22/48 (45.8%) | 6 of 6 | commune 6, escape 14, boss 2 |
| 0 | 21/48 (43.8%) | 4 of 6 | commune 8, escape 13 |

**12 is taken: the only arm that is simultaneously highest on aggregate and unanimous on route
diversity.** Removing the pull entirely is worse than halving it, and for a legible reason: at
base 0 the fight-first profile stops descending at all and wins **nothing**. The pull was never
a bug, it was just louder than every identity in the table.

### Confirmed

8 runs per agent, clean state, `PYTHONHASHSEED=0`:

| agent | win rate | win paths |
|---|---|---|
| artisan | 50% | escape 3, commune 1 |
| cartographer | 62.5% | escape 4, commune 1 |
| emergent | 37.5% | commune 2, escape 1 |
| exploiter | 50% | escape 2, commune 2 |
| seeker | 62.5% | **escape 3, commune 2** |
| whisper | 62.5% | escape 4, commune 1 |

**26 of 48, 54.2 percent, and every one of the six profiles wins by two different routes.**
Seeker's top choice is `locus` again at 18 percent, where the previous baseline had it spending
**22 percent of every turn steering at the warden**. That is the fix, and it is visible in what
the profile spends its turns on rather than only in the outcome column.

### What this did not fix, stated plainly

**The monoculture moved rather than disappeared.** The win mix went commune 16 / escape 9 before
the warden was priced, to commune 11 / escape 10 after it, to **escape 17 / commune 9** now.
Escape is the dominant route today at about two thirds, where commune was at about two thirds
before. Both routes are healthy in absolute terms and every profile uses both, which is the
property that was asked for, but a third of wins on one route and two thirds on another is not
a balanced game, it is a differently-tilted one.

The reason is structural and worth stating for whoever picks this up: `escape` is the *default*
outcome of a completed descent, since it fires whenever the last stair opens by any means and
the player walks through it. Commune and boss-kill are things you must specifically do. So a
tilt toward escape is what you get whenever the other two are priced at all, and the honest
next question is not "how do we rebalance the mix" but "should `escape` be a route at all, or
is it the absence of one".

`pytest` remains at 16 failures, down from the 18 that stood for this whole pass.

## `escape` was not a route, and that is why it looked like one

The instruction was to stop `escape` being the default outcome of a completed descent. The
first thing to establish was what it actually was, and it turned out not to be a route at all.

`egress_ready` is a disjunction of four conditions. `descend` checked it at the last floor and,
if the stair opened, called `_win("escape")` **without recording which condition had opened
it**. The warden routes resolve earlier and win under their own names, so in practice `escape`
was the label worn by two entirely different achievements at once: reading enough of the vault,
and earning the warden's house enough trust. Reported as one thing, that one thing was two
thirds of all wins and looked like a dominant strategy. It was not a strategy. It was a missing
distinction.

`egress_ready` now returns the route that opened the stair and `_win` is named for it. The
change is **behaviour-neutral and measured to be so**: the confirming eval returns the same 26
of 48 and the identical per-profile counts, 4, 5, 3, 4, 5, 5. Only the labels move.

What the labels then show, over the same 26 wins:

| route | wins | share |
|---|---|---|
| **standing** | **16** | **62%** |
| commune | 9 | 35% |
| truths | 1 | 4% |

So the monoculture was real, and it was never `escape`. **It is `standing`.** `EGRESS_STANDING`
is 3, and the earlier independent census found standing at 3 or better in 33 of 48 runs, which
means it is not an achievement the route asks for, it is a thing that happens to a run on its
way past. Two thirds of all victories rest on it.

This also retires my own framing from the previous section. I wrote that escape is "the default
outcome of a completed descent" and that the honest question was whether it should be a route at
all. Both were wrong in the same way: I was reasoning about a label rather than about the four
conditions underneath it. The right question was always which of the four is underpriced, and
naming them answers it immediately.

### Pricing the route that was actually the default

With the routes named, the fix is obvious and it is not about `escape` at all. Sweeping
`EGRESS_STANDING` over 8 seeds per agent across all six profiles, judged on the win mix first:

| gate | aggregate | top route's share | mix |
|---|---|---|---|
| 3 (old) | 26/48 (54.2%) | 65% | commune 8, standing 17, truths 1 |
| 5 | 25/48 (52.1%) | 56% | commune 10, standing 14, truths 1 |
| **7** | **22/48 (45.8%)** | **45%** | **commune 10, standing 6, truths 2, boss_killed 4** |

**7 is taken, and it is the first setting at which all four routes are live in a single
batch.** Felling the warden goes from a rounding error to 4 wins, because a house's trust is no
longer the cheap way past it. The aggregate drops to the lower half of the 40-60 band, which is
the price of the cheapest route no longer being cheap.

The test asserts the property rather than the number: the gate must sit above `FRIEND_STANDING`,
the reputation at which a house merely stops fighting you. A last stair that opens at less than
that is not asking for anything.

### Confirmed

8 runs per agent, clean state, `PYTHONHASHSEED=0`. The eval reproduces the sweep exactly:

| agent | win rate | win paths |
|---|---|---|
| artisan | 25% | standing 1, commune 1 |
| cartographer | 62.5% | **commune 2, standing 1, truths 1, boss_killed 1** |
| emergent | 37.5% | commune 2, boss_killed 1 |
| exploiter | 50% | commune 2, standing 1, boss_killed 1 |
| seeker | 50% | commune 2, truths 1, standing 1 |
| whisper | 50% | standing 2, commune 1, boss_killed 1 |

**22 of 48, 45.8 percent.** Across the batch: **commune 10, standing 6, boss_killed 4,
truths 2.** No route exceeds 45 percent of wins, where one route held 65 percent at the start of
this section and the mislabelled `escape` held two thirds before that. Every profile wins at
least two ways, four of them win three or more, and **cartographer takes all four routes across
its eight runs**.

That is the request satisfied in the strongest available sense: `escape` is not the default
outcome because it is no longer an outcome at all, and nothing has replaced it as a default.

### The cost, and what is now open

**Artisan fell to 25 percent**, 2 wins in 8, and is the new weakest profile. Its top choice is
`commune` at 23 percent of turns, which is the shape seeker had before the pull was swept: a
profile steering hard at one route. It has not been diagnosed.

The aggregate at 45.8 percent sits in the lower half of the band rather than its middle. Both of
those are the same trade: four priced routes are harder than three priced routes and one free
one. Whether to buy some of it back, and with which knob, is a judgement call rather than a
measurement, and it is left open rather than made here.

---

## F4 closed

`.github/workflows/ci.yml` is the second workflow this repo has ever had. It runs on push to
`main`, on every pull request, and on manual dispatch.

### What it checks

**pytest, 304 tests across 46 of the 66 test modules.** About 40 seconds, peak RSS 48 MB.
`HOME` is redirected to a throwaway directory because `test_pressure.py::test_graves_escalate`
genuinely writes `$HOME/.vaultcrawl/graves.json`; it restores what it finds, but CI is not the
place to discover otherwise. pytest is pinned at 9.1.1 and invoked as `python -m pytest`: it is
undeclared anywhere in the repo and only ambiently present, and this environment has two
conflicting versions on `PATH`.

**The 20 modules pytest cannot see.** They use a `main()` plus `if __name__` style with no
`def test_` at module level, so they run nowhere. The step selects them by *asking each file
whether pytest can find anything in it* rather than from a hardcoded list, so it stays correct
as tests are added and never double-runs the 46. The partition was verified rather than
assumed: 46 collected plus 20 script-only is exactly 66, with no file in both sets and none in
neither.

**The bake is valid and deterministic.** Bake `sample_vault` twice, `cmp` the two outputs, and
run the in-repo `vaultcrawl.validate.validate()` over the result. This is `CLAUDE.md`
invariant 4 turned into a gate, and it is the cheapest possible version of it.

**No em dashes on added lines**, pull requests only. Invariant 3, made real going forward.

### The known-failure list, and why it is not a deselect

16 tests fail on HEAD and have failed identically on every commit checked back to before this
assessment began. That left two bad options: ship CI red on its first run, which teaches
everyone to ignore it, or deselect the failures, which hides them permanently.

`tests/known_failures.txt` plus `tests/conftest.py` is the third option. The listed node IDs
get `xfail(strict=True)` applied at collection, so no existing test file is edited and the set
is written down in exactly one place. Two properties make it strictly better than a deselect:

* **A listed test that starts passing fails the build** (`XPASS(strict)`). The list cannot rot
  into a lie about what is broken. Fix the bug, delete the line, same commit.
* **An entry matching no collected test is a collection error**, judged per file rather than
  per run so that `-k`, a single test path, and `--last-failed` all stay usable. A renamed or
  deleted test would otherwise silently widen the hole.

The file only ever shrinks, and every line carries a one-line note on what is actually broken:
`is_immobilized()` returning False on a player with broken legs, forged sigils coming out with
`perks` empty, the fabricator not producing the sigil it advertises. These are mostly not stale
expectations. They are authored features wired to nothing, the same class of defect as the
deploy crash and the unreachable dialogue tree.

All four properties were proved locally before pushing, not reasoned about: listing a passing
test does go red with `XPASS(strict)`; deleting an entry does surface the real assertion
(`assert 25 == 8`); a bogus entry does error collection; and a single-file run and a `-k`
filter both stay green.

### What it does not cover

**The agent eval.** Deliberate. Roughly seventeen minutes for 48 games, and it carries about one
flipped run in 48 between processes, so as a merge gate it would be slow and flaky at once.
Balance is measured on purpose, from a clean `~/.vaultcrawl` at `PYTHONHASHSEED=0`, not on every
push. Nothing in CI will catch a balance regression.

**`balance_test.py` and `run_agents.py`** at the repo root are collected by nothing and run
nowhere, and `balance_test.py` hardcodes its own 27-system list instead of calling
`runtime.stack.build_systems()`, so it will drift from the canonical stack. Related to F8, and a
separate change from standing CI up.

**`schema/world.schema.json`** still has no validator wired to it. The bake step uses the
dependency-free in-repo validator instead; a real JSON Schema check would need a third-party
package and would break the zero-dependency rule.

**The em-dash back catalogue**, 552 in `.py` and 368 in `.md`. Only new lines are checked. F5
is narrowed here, not closed.

**Coverage is not measured**, and the script-style step asserts only that each module exits 0.
A module that silently stopped running its assertions would still pass.

**One interpreter.** Python 3.12, matching `pages.yml`. The failure set was cross-checked at
module level on both 3.11 and 3.12 and is version-stable, so the pin is safe, but nothing tests
any other version.

---

## F1 closed

F1 called itself "the single highest-value fix in the repo" and "a four-line dedent". The first
was right and the second was not, in three ways.

### The dedent was not the whole of it

`b` is the `yubn` down-left diagonal. `moves = dict(_DIRKEYS)` is consulted before the first
`elif`, so dedenting `elif k == ord("b")` into the chain would have left breakdown exactly as
unreachable as before, while looking repaired. It is `B` now, and `test_no_key_is_shadowed`
asserts no key in the table collides with movement.

### `a` was worth far more than a verb

`Game.interact()` is the only site in the runtime that emits `interact`. That is the only
trigger for `DialogueSystem.on_event`, which holds the only call to `quests.offer()`. So while
`a` was dead, **a human could not acquire a quest at all**, and the `on_interact` handler in
`flora`, `decay`, `reactions`, `sacrifice`, `structures`, `fauna` and `factions` had never once
run in interactive play, along with `Game.clear_weather` and `Game.repair_part`. F1 counted four
verbs. The bill was seven systems' interaction handlers and a severed quest economy.

### Two crashes were sitting in the same file, and one outranked F1

Neither is a verb gap. Both were found by building a headless driver for the dispatch chain, and
neither is visible by reading.

- **`draw()` raised NameError on any graded creature in the viewport.** It coloured grades with
  `[(G, BOLD), ...]`, and `G`, `B`, `M`, `Y` and `BOLD` are locals of `_init_palette`, a
  *sibling* function, not an enclosing scope. Python resolved them as module globals and found
  none. `put()` swallows only `curses.error`, so it propagated. With the real system stack this
  fires on the first frame, so **the default interactive mode did not survive to its first
  keypress**. It is keyed on viewport position rather than fog, so a graded creature you could
  not see was enough. This was a worse bug than F1 and no document had it.
- **`g` raised NameError because `travel` had no `def` line.** Deleted at some point, so its
  docstring became a no-op expression and its body became the tail of `autoexplore`. Pressing
  `g`, an advertised key, killed the process. Pressing `o` took one explore step and then asked
  which way you wanted to travel.

A third, quieter: `menu = " ".join(...)` in the debug handler makes `menu` local to the whole
dispatch loop, leaving `interactive()`'s `menu()` unbound for every other caller in it. That
broke `e`, and would have broken the sacrifice shrine the moment `a` was revived.

### The corrections F1 and the Potential section needed

- "The agent has eight verbs the human lacks" is right by accident and wrong in membership.
  `becalm` and `negotiate` were already reachable through the `t` talk window, and the human's
  parley is the better one: it runs every move with a `resolve(recruit=)` branch, while the
  agent gets one round with the last move hardcoded and can never recruit. The correct set is
  **seven**, and it included `interact`, which F1's list omitted.
- The gap runs both ways and nothing had said so. The human has four verbs the agent lacks:
  `confide`, `recruit`, body-action `player_cast`, and `EffectSystem.wear`.

### What was built

Every one of the 19 verbs in `dispatch()` now has a key. `deploy`, `recover` and
`craft_consumable` had none at all; the craft picker needed paging, because both existing
pickers read a single keystroke in 1..9 and there are 25 recipes, so a plain menu would have
left the tail of the list as unreachable as a key nothing dispatches.

`KEY_TABLE` in `runtime/play.py` is now the one place the key set is written down. The status
line and a new `?` screen both render from it. `tests/test_keys.py` parses the dispatch chain
out of the source and asserts set equality with the table in **both** directions, walking each
branch's `test` and never its body, which is exactly what makes it catch the F1 shape.

Eleven tests, and each was proved load-bearing rather than assumed: reintroducing each bug in
turn was measured to turn the module red, and reverting made it green.

| bug put back | tests that failed |
|---|---|
| remove the `travel` def line | 3 |
| re-indent the four keys into the `f` handler | 3 |
| point breakdown back at `b` | 1 |
| put the grade colours back out of scope | 7 |
| restore the `menu` shadow | 1 |
| craft through the unpaged menu | 1 |

### Cost, and what this does not cover

Three files changed: `runtime/play.py`, one docstring in `runtime/game.py`, and the new test
module. `git diff -w` shows exactly ten deleted lines and nothing else, which is the proof that
the dedent moved whitespace and nothing more. Nothing touched `agent_action.py` beyond its
docstring, so the measured balance baseline (22/48, commune 10 / standing 6 / boss_killed 4 /
truths 2) stands and needed no re-run.

Not covered, and now the honest frontier:

- **Perception, not verbs, is where the asymmetry now lives.** `agent_state()` computes
  `predicted_traps`, `boss_weak_element`, `hazard_behind`, `encounter_options` and
  `egress_ready`/`egress_route`, and none has a human equivalent on screen. A human plays the
  endgame without being told which of the four win routes is open. No keybinding fixes that.
- **The two players are not charged the same for the same verb.** `cast`, `toss`, `recover` and
  `craft_consumable` are free for the agent and cost a human a turn, and a human's `wait()` also
  heals. Every cell of that is a balance number and half live in `agent_action.py`.
- **The first press of `o` does nothing**, because `KnowledgeSystem.seen` is written only in
  `on_player_act`, so at turn 0 the player's own tile reads as unexplored at distance 0.
- The dispatch chain is still a 200-line `elif`. It is now covered, which is the precondition
  for restructuring it into a handler registry and knowing nothing moved.

---

## Potential #3 closed: the ambient narrator

"A perceptible world" was ranked third by leverage and called "the highest-value unbuilt
feature in the repo". `DESIGN_PLACE_PANEL.md` steps 5 and 6b are now built
(`runtime/narrator.py`, `tests/test_narrator.py`) and that document is closed.

### The premise in this document was wrong, and worth correcting

"Twelve systems currently run every turn and are invisible" fails three ways:

- **Eleven tick per turn, not twelve.** `FactionSystem` has no `on_player_act`; it is
  event-driven and floor-gated.
- **`render_overlay` and `status_line` are both live.** `compose_frame` calls every
  `render_overlay`, and `play.py` calls `status_line` directly. Six systems already draw to
  the map: flora `;`, decay `%`, reactions, structures, terrain_mod `†`, marginalia `"`.
- **The real mechanism is a deliberate, documented priority order.** `play.py` ranks status
  lines and everything ambient sorts last, so it truncates first, with the reason in a
  comment: "on a short terminal the ambience is what falls off the bottom, never your build,
  wealth, or reputation." That is a design choice, not an oversight.

`ReactionSystem`, which this document listed among the silent, is the **loudest** system in
the stack. What is actually silent is narrower: `SenseField` and `ScentSystem` rewrite
full-map dicts every turn and emit nothing at all; `DecaySystem`'s 1 HP per turn corpse
miasma has no message; all fauna predation and breeding is silent.

### A fairness bug, not an ambience gap

Acrid haze damaged the player **every third turn and mentioned it every fifteenth**, so five
HP went missing per line. Worse, the line was tagged `ambient=True`, and an ambient line is
specifically what tells a travel glide *not* to stop, so a player could be chipped toward
death mid-glide and never be halted. It now speaks whenever it damages, and not as ambience.
Damage is not atmosphere.

### What the narrator is

One system, appended last in the stack, that only ever reads and logs. It diffs corpses and
elemental tiles between turns, gates the result through the player's own sense profile,
takes the single most salient percept, re-asks live state whether the thing is still there,
and speaks at most one line. Sight names what it found; sound and smell give a bearing and
stay ignorant, which is `SENSES_SPEC.md`'s identifying-versus-locating split doing real work.

The cap moved into `Game.log` and is global, because several unrelated producers share the
channel and none can see the others. It sits below the duplicate collapse so four strikes
still read as one "(x4)". Ranked, so a line you can walk to beats a place murmur off a static
corpus, which otherwise won every contested turn by firing earlier in the turn.

### Twelve tests, each proved load-bearing

Reintroducing each bug was measured to turn the module red. Two of the first drafts were
**not** load-bearing and had to be rewritten, which is the part worth recording:

- The cardinal-rule test passed with the guard deleted. In ordinary play the narrator diffs
  and speaks inside one turn, so the referent never has an opportunity to vanish in between:
  the test was checking the invariant, not the guard. The guard is now exercised directly.
- The wait-to-listen test passed with the advantage removed, in two separate drafts, one
  wandering and one pacing in place. `wait` also rests, heals and ticks tension, so no
  walking control holds the world equal and what it measured was geography. The rate is now
  tested at the decision rather than at the outcome.

### The parity test found something bigger than the narrator

The balance guard began by comparing two whole playthroughs, with and without the system,
and reported a difference. The difference was not the narrator. **Four runs of the identical
configuration, each with its own fresh HOME, in one process, gave matter totals of 3, 4, 5
and 7.** An inert system that did nothing at all "changed" the result the same way.

So a playthrough is not a stable measuring stick, even within a process and even with the
documented `~/.vaultcrawl` leak controlled for. This is worse than the "cross-run state
leaks into benchmarks" note above, which is about state carried between processes.

~~The strongest candidate by inspection, not proven: `senses.py` stores `id(a)`, a memory
address, into the scent map and later compares against it to decide whose scent is whose.~~

**That guess was wrong, and it was investigated the next day.** It is not `id()` and it is
not addresses. See "The drift, diagnosed" below. The tell was in the numbers already
printed above and I did not read it: 3, 4, 5, 7 is *monotonic*, and address noise is not.

The test now asserts the property directly, fingerprinting game state around the hook, which
is both immune to that noise and a stronger claim: not "the outcome happened to match" but
"this system wrote nothing".

### Left open

- **Two perceptibility bugs in map rendering**, recorded in the last tranche and still true:
  actors are stamped into the frame before `render_overlay` runs and reactions skips
  non-floor cells, so a hazard under a creature is invisible; and the hazard glyphs collide
  with the step-1 fixture glyphs, so `:` is both acid and stone.
- **Perception parity.** The five things `agent_state()` computes that no human screen shows,
  including which of the four win routes is open, are still agent-only. Deliberately out of
  scope here.
- **The place-voice timer** is still a static corpus on a cadence, which is the shape the
  panel's own Stop-doing section warns about. It now loses the turn to any real perception,
  which is a smaller change than deleting it.

---

## The drift, diagnosed

The previous section guessed that the within-process drift came from `senses.py` storing
`id(a)`, a memory address, into the scent map. **That guess was wrong.** The real cause is
duller and more embarrassing, and the evidence against the guess was already printed in the
same paragraph: 3, 4, 5, 7 is monotonic, and address noise is not.

### What it actually is

`reset_run_state()` in `runtime/stack.py` already existed, already did the right thing, and
its own docstring already said "call this at the start of every run". **Only
`agent_eval.py` and `run_agents.py` ever called it.** `Game.__init__` did not. So every
other path that built two games in one process, which is the entire test suite, every
scenario script and `play.py`, carried the previous run's skill tiers into the next one.

The specific channel: `salvage._collect_heaps` adds the foraging tier to every scrap heap
you pick, and `exercise_skill("foraging")` accumulates that tier in a module-level
singleton with no per-run reset.

### How it was found, since the first two attempts went the wrong way

| step | result |
|---|---|
| Eight runs in one process | 3, 4, 5, 7, 7, 7, 9, 9 |
| One run per fresh interpreter, four times | 3, 3, 3, 3 |
| Diff of module-level container sizes between runs | nothing changed size |
| Diff of the two runs' message traces | **196 entries each, byte-identical** |
| Per-turn fingerprint of actors, corpses, plants, matter | identical until turn 203, where **only** matter differs |
| Spy on every `Inventory.add` | turn 204, `_collect_heaps`: `{'scrap': 1}` in one run, `{'scrap': 2}` in the other |

The monotonic sequence should have been the first clue and was not. The identical message
traces were the second: matter changed with no log line saying so, which pointed straight
at a silent grant rather than at anything to do with pathing or perception.

### The second bug, which is why nobody noticed the first

`_collect_heaps` logged `heap["matter"]`, the base amount, while granting `matter`, the base
plus the foraging tier. So a skilled forager was told a smaller number than they received,
and, worse, **two runs that granted different amounts produced byte-identical logs.** The
leak was invisible to any check that read the transcript, which is what the integration
audit does.

### The fix

One call, moved to where a run actually begins: `reset_run_state()` at the top of
`Game.__init__`. A Game is a run. The two harnesses that already called it are unaffected,
since the call is idempotent. After it, eight runs in one process give 3 every time,
matching a fresh interpreter.

`tests/test_run_isolation.py` pins all three: two games in one process agree, skills do not
survive a new Game, and the heap reports what it gave. Each was proved load-bearing by
reverting its fix.

### Two things this changes about earlier results

- **`tests/test_integration.py`'s determinism section was green for the wrong reason.** It
  built both games up front and played them in sequence, so with the reset in place the
  second inherited the first's skills and it began failing. It now builds each game
  immediately before playing it. Note honestly: that section still passes even with the
  reset removed, because by the time it runs, foraging has saturated during the earlier
  sections and two runs both pinned at the ceiling cannot diverge. It is correct now, but
  it is not the guard. `test_run_isolation.py` is.
- **Every balance number in this document was produced through `agent_eval`**, which did
  call the reset, so the 22 of 48 baseline stands. What was confounded is anything measured
  by building games directly, which includes any ad-hoc comparison run in a shell.

### Still open

The `id(a)` write in `senses.py` is still there and is still a poor idea, since a memory
address is not a stable identifier. It is simply not the cause of this. Left as found.

---

## F6 closed: the bake is a pure function of the vault

`CLAUDE.md` listed this first under Known Issues and framed it as a flavour-layer leak that
happened to touch `_archetype_for`. It was bigger than that in three directions.

### Archetype is not flavour

`entities.py:92` maps archetype to a glyph and `senses.profile_name_for` maps glyph to a
sense profile. A `scribe` is glyph `s`, the **mind_seer** profile that senses thought through
walls at range 10. A `gloom` is glyph `k`, plain **sighted**. Two copies of the same vault
with different file times bake one or the other. A file modification time decided what a
creature could perceive.

### The bake was the smaller half

`activity` is written into the manifest and read back by six mechanical consumers in the
runtime. The loudest is `runtime/game.py`'s `n = 2 + floor//4 + round(region["activity"] * 2)`,
the number of enemies on every floor; the others are the parley goal, whether a room gets a
cache, area-kind weighting, which interior generators fire, and the type of orphan landmarks.
Fixing `_archetype_for` alone, which is what the old wording implies, would have left all six.

### The old numbers were not even degenerate, which is why nobody noticed

The expectation was that a clone flattens every mtime and `activity` collapses to a constant.
It does not. The measured spread across `sample_vault` in this checkout is **5.3
milliseconds** of filesystem write order, and min-max normalisation amplifies that to the
full 0..1 range. The result looks plausibly graded while encoding nothing but the order git
happened to write the files in.

### A second environment leak, previously unrecorded

`bake.py` wrote `os.path.abspath(vault_path)` into `generatedFrom.vaultPath`, so the
committed `examples/world.json` shipped with `/Users/zntznt/Repositories/vaultcrawl/...` in
it. An environment leak into a published artifact, and independently enough to stop any
re-bake elsewhere from matching. It is a basename now.

### The design, including the version that was wrong

`activity` now comes from a stable per-note hash, ranked rather than min-max normalised.

The first attempt derived it from **graph position**, calling the central core "old" and the
leaves "the frontier", which is the story `ARCHITECTURE_SPEC.md` tells about growth rings. It
was reproducible and it collapsed the world. `runtime/arch/areakinds.py` weights an area's
kind from the region's ANCHOR note, which is by definition its most central, and it reads
role, degree **and** activity. Ranking activity by centrality put every anchor in the "old
and quiet" band, every region got the same necropolis bonus, and block-glyph variety in the
sample world fell from four kinds to two. Centrality was already a signal there; activity had
to be a different one. Caught by `tests/test_blocks.py`, which is exactly what that test is
for.

What the mtime version actually supplied was a spread across notes **uncorrelated** with
graph position, since editing a note today says nothing about how many things link to it. A
hash of the note id reproduces that character exactly and is the same on every machine.

Rank rather than min-max applies to both sources: min-max divides by the span, so one note
edited today rescales every other note in the vault.

Edit recency is not deleted, it is opt-in. `--mtime-activity` restores it for someone baking
their own live vault, and stamps `generatedFrom.activitySource` so a world that cannot be
reproduced from the vault alone says so.

### What it unlocks

CI now asserts that a fresh bake **equals the committed `examples/world.json`, byte for
byte**. That check was impossible before and it collapses three worlds into one.

There really were three. `.github/workflows/pages.yml` bakes `sample_vault` over
`examples/world.json` on the runner before capturing the demo, so the published animation was
generated from the runner's checkout order, not from the artifact the tests validate. The job
comment claims the site "can never drift from the current build", which was true about code
and false about the world. It is true about both now.

The old CI determinism gate baked twice **on one runner in one job**, where mtimes are
constant by construction, so it passed unconditionally while this bug was live. It tested the
half `CLAUDE.md` already called fixed. It is replaced by the equality check above plus a
touch-a-note-and-rebake guard.

### Tests, and two of them were weaker than they looked

`tests/test_bake_determinism.py`, six tests, each proved load-bearing by reverting the fix.
Two needed rewriting first, and the reason is worth keeping:

- The two "same content, different mtimes" tests stamped every file to a **single** value per
  arm. That looks like the harsher test and is the weakest one: min-max divides by the span,
  and a span of zero sends every note to the same activity in both arms, so the comparison
  passes whatever the code does. They stamp a spread now, in opposite orders, which is what a
  clone actually produces.
- The opt-in test compared whole manifests and passed with the flag disabled, because the
  `activitySource` marker alone made them unequal. The marker is not the feature; it compares
  activity values now.

### Cost: the new baseline, and a prediction of mine that was wrong

`examples/world.json` is regenerated, so the world every balance number was measured against
is a different world. Re-measured per invariant 7, clean `~/.vaultcrawl`, `PYTHONHASHSEED=0`,
8 runs per profile.

**I predicted the mechanism wrongly.** The plan and the commit message both said region
activity would change `round(activity * 2)` and therefore the enemy count per floor. It does
not: the bonus is `[1, 1]` in the old world and `[1, 1]` in the new one. Activity moved
(`0.501, 0.523` to `0.489, 0.611`) but never across a rounding boundary. What actually changed
is the bestiary, three archetypes of seven (`chorus` to `myriad`, `scribe` to `gloom`, `seraph`
to `warden`, and those carry different family actions, glyphs and sense profiles), plus the
parley goal, cache richness, area kinds, interiors and landmark types, which are the other five
consumers.

| | before (22 of 48) | after (16 of 48) |
|---|---|---|
| aggregate | 45.8% | **33.3%** |
| artisan | 2 | 3 |
| cartographer | 5 | 4 |
| emergent | 3 | 1 |
| exploiter | 4 | 1 |
| seeker | 4 | 1 |
| whisper | 4 | 6 |
| win paths | commune 10, standing 6, boss_killed 4, truths 2 | commune 6, standing 5, boss_killed 3, truths 2 |

**33.3% is below the 40 to 60 band, and it is not being retuned here.** Retuning is a separate
decision and mixing it into a determinism fix would make both unreadable.

**It is also not distinguishable from noise, and saying otherwise would overclaim.** The drop is
12.5 points; the standard error of the difference between two 48-run binomials at these rates is
9.9 points, so `z = 1.26` and two-tailed `p` is about 0.21. Worse for the claim: 12.5 points is
*exactly* the per-arm noise budget `CLAUDE.md` already tells you to assume. Four profiles moved
down and two moved up, which is not a clean signal either. So the honest statement is: the point
estimate is below the band, and 48 runs cannot tell whether the world is genuinely harder or
this is the documented flakiness. Resolving it means more runs, not more tuning.

What did not degrade: all four win routes are still live, the top route is 38% of wins (it was
45%), and every profile still wins at least one way, so nothing became unreachable. The spread
across profiles is wider than before, 12.5% to 75%, with whisper now the strongest.

---

## The band, settled at 288 runs

The 48-run figure could not tell a real shift from noise, so the sample was widened to 48
seeds per profile. Clean `~/.vaultcrawl`, `PYTHONHASHSEED=0`, run after the boss-placement
crash fix.

**77 of 288, 26.7%, Wilson 95% interval [22.0, 32.1].** The band is 40 to 60. The interval
lies **entirely below it**, so this is no longer a judgement call: the agents lose.

| profile | wins | rate | 95% interval | median floor | IQR |
|---|---|---|---|---|---|
| whisper | 24/48 | **50.0%** | [36.4, 63.6] | 26.0 | 15.0 to 27.0 |
| emergent | 14/48 | 29.2% | [18.2, 43.2] | 21.0 | 13.0 to 26.0 |
| cartographer | 11/48 | 22.9% | [13.3, 36.5] | 12.0 | 7.0 to 26.0 |
| exploiter | 11/48 | 22.9% | [13.3, 36.5] | 24.0 | 12.2 to 26.0 |
| artisan | 9/48 | 18.8% | [10.2, 31.9] | 20.0 | 12.5 to 26.0 |
| seeker | 8/48 | 16.7% | [8.7, 29.6] | 25.5 | 12.0 to 26.0 |

**whisper is the only profile whose interval touches the band at all.** Every other one is
entirely below 40.

### What the 8-seed arms were actually measuring

Nothing you could rely on. The same profiles, same world, same code, at 8 seeds and then 48:

| profile | 8 seeds | 48 seeds |
|---|---|---|
| artisan | 37.5% | 18.8% |
| cartographer | 50.0% | 22.9% |
| emergent | 12.5% | 29.2% |
| exploiter | 12.5% | 22.9% |
| seeker | 12.5% | 16.7% |
| whisper | 75.0% | 50.0% |

Every one moved, four of them by two or three wins' worth, against a documented budget of
one win per arm. `CLAUDE.md`'s "+/-1 win of noise per 8-seed arm" understates it by a factor
of about three. **Any conclusion in this document drawn from an 8-seed arm should be treated
as unmeasured** until it is redone at 48. The aggregate figures are safer, being six arms
pooled, but the per-profile claims are not.

One thing the wider sample did NOT change: the first 8 seeds of each profile reproduce their
earlier results exactly (artisan 3, cartographer 4, emergent 1, exploiter 1). So this is a
sampling effect, not run-to-run flakiness, and not the boss-placement fix either.

### The characterisation, and it holds

Raw kill counts confound with how long a profile survives, so normalise by turns:

| profile | kills | turns | kills per 1000 turns | median floor | win rate |
|---|---|---|---|---|---|
| emergent | 35.3 | 4566 | **7.73** | 21.0 | 29.2% |
| exploiter | 18.6 | 5128 | 3.63 | 24.0 | 22.9% |
| seeker | 11.6 | 5237 | 2.22 | 25.5 | 16.7% |
| artisan | 13.1 | 7036 | 1.86 | 20.0 | 18.8% |
| cartographer | 5.9 | 3430 | 1.72 | 12.0 | 22.9% |
| whisper | 6.6 | 6891 | **0.96** | 26.0 | 50.0% |

emergent kills at **eight times** whisper's rate. That is not a survival artifact, and it is
far too large to be sampling noise, though it cannot carry an interval because the eval
recorded only means. (Fixed going forward: the dump now carries per-run rows.)

So the berserker and the diplomat are real, and they were never authored. They fall out of
scoring weights. Two corrections to the earlier reading, both from the 8-seed arms:

- **"emergent dies shallow" is false.** Median floor 21 and the second-best win rate. It is
  violent and it is effective.
- **"whisper ends at nearly full health" is false.** 96.9 average HP at 8 seeds, 52.0 at 48.
- **whisper is not the least violent.** cartographer is, marginally, at 1.72 per 1000 turns.

The sharpest character is one nobody named: **seeker reaches a median floor of 25.5, deeper
than every profile except whisper, and wins least of all at 16.7%.** It arrives and it cannot
finish.

### Route concentration is back

Across all 77 wins: **standing 38 (49%)**, boss_killed 18 (23%), commune 16 (21%), truths 5
(6%). The earlier pass drove the top route down to 45% of wins at 48 runs; at 288 it is 49%
and `standing` is the clear monoculture. `truths` at 6% is close to vestigial.

Per profile, the routes each one actually uses:

| profile | routes |
|---|---|
| artisan | standing 7, commune 2 |
| cartographer | standing 5, boss_killed 3, commune 2, truths 1 |
| emergent | commune 5, standing 5, boss_killed 3, truths 1 |
| exploiter | boss_killed 5, standing 5, commune 1 |
| seeker | standing 4, commune 2, boss_killed 2 |
| whisper | standing 12, boss_killed 5, commune 4, truths 3 |

Every profile still wins at least two ways and three win all four, so nothing is unreachable.
But **artisan wins only two ways**, and exploiter is the only profile that does not lead with
`standing`.

### What this does not say

It does not say the world got harder when the bake was fixed. That comparison is now
untestable at the precision that matters: the old 22/48 was an 8-seed measurement, and the
table above shows 8-seed measurements move by up to three wins. Re-running the old world at
48 seeds would settle it and has not been done.

It also does not license a retune. 26.7% is a measurement, not a target, and deciding what to
do about it is a separate piece of work from finding out.

## Correcting the record: what the band is, and what it was ever measured at

The 288-run figure invites an obvious response, which is to tune the game back up until the
number returns to 40-60. Before doing that, two facts about the record above.

### The band is not justified anywhere

It appears in no spec. `guidance/AGENT_SPEC.md` says nothing about a target win rate; neither
does any other file in `guidance/`. Grep the repository and every occurrence is in this
document. Its first appearance is line 830, "just under the 40-60% band the balance pass
targeted", which cites the band as an existing standard while being the place it enters. From
there it is treated as given for the next 1,800 lines.

So nobody wrote down what an agent win rate is **for**. That matters more than whether 26.7%
is inside it: a target with no stated purpose cannot tell you which way to move a constant, or
whether to move one at all.

### And it was never reliably hit

Every claim of being inside the band was measured below the resolution the claim needed:

| claim | line | measured at |
|---|---|---|
| "3 of 6, 50%, the middle of the target band" | 903 | **two runs per agent** |
| "aggregate 46%, inside the band for the first time" | 1006 | 8 seeds |
| "23 of 48, 47.9%, inside the band" | 1114 | 8 seeds |
| "21 of 48, 43.75%, still inside the band" | 1315 | 8 seeds |
| "24 of 48, 50.0%, the centre of the target band" | 1460 | 8 seeds |
| "27 of 48, 56.25%, inside the band" | 1716 | 8 seeds |
| "45.8%, the lower half of the band" | 2189 | 8 seeds |

The table at line 2706 shows 8-seed arms moving by up to three wins per profile when the same
code, same world and same seeds are widened to 48, and the aggregate moving 45.8% to 26.7%
purely by sampling more. **26.7% is therefore not a regression from 46%. It is the first
aggregate this project has measured at a sample size that can support the sentence.** The
earlier numbers are not wrong so much as unresolved: they never distinguished the arms they
were used to distinguish.

### The five constants set that way

Each of these was chosen by comparing arms that differed by one to four wins at 8 seeds, which
is inside the noise now measured. None of them is known to be wrong. What is now known is that
the evidence offered for each could not have separated it from its neighbours:

| constant | value | set in | swept at | what the sweep could actually resolve |
|---|---|---|---|---|
| `EGRESS_STANDING` | 7 | `0df8c3f` R5, raised 3 to 7 later | 8 seeds | nothing at this margin |
| `EGRESS_TRUTHS_TENTHS` | 4 | `f0122b0` | 8 seeds | nothing at this margin |
| `DESCEND_MEND_DIV` | 4 | `622770b` | 8 seeds, one arm at 2 runs per agent | nothing at this margin |
| `BOSS_COMMUNE_TRUTHS` | 2 | `1c2006e` | 8 seeds, and the value came from a test file | nothing at this margin |
| `COMMUNE_PULL_BASE` | 12 | `0d5e744` | 8 seeds | nothing at this margin |

The point of writing this down is not to relitigate five decisions. It is that a sixth decision
made the same way would compound the problem rather than fix it, so the next constant this
project moves has to be moved on a sample that can decide.

## The first sweep run at a size that could decide: EGRESS_STANDING

Four arms, 144 runs each (24 seeds per profile, all six profiles), 576 runs total. Each arm
from a clean `~/.vaultcrawl` at `PYTHONHASHSEED=0`, sequential, never concurrent with the test
suite. The decision rule was fixed before the first arm ran: **adopt a value other than 7 only
if its interval does not overlap the interval for gate 7.**

| gate | wins | rate | 95% interval | died | stalled |
|---|---|---|---|---|---|
| 7 (current) | 34/144 | 23.6% | [17.4, 31.2] | 82 | 28 |
| 6 | 34/144 | 23.6% | [17.4, 31.2] | 82 | 28 |
| 5 | 38/144 | 26.4% | [19.9, 34.1] | 81 | 25 |
| 3 | 42/144 | 29.2% | [22.4, 37.1] | 82 | 20 |

**Every arm overlaps every other. Nothing is adopted. `EGRESS_STANDING` stays at 7.**

Gate 3 was measured but was never adoptable: `FRIEND_STANDING` is 4, and an escape gate that
asks for less than the standing at which a house merely stops fighting you is the inversion
`tests/test_pressure.py` already guards. It is in the table to show the shape of the curve.

Two things the sweep establishes beyond the rule.

**Gate 7 at 144 runs reproduces the 288-run baseline.** 23.6% [17.4, 31.2] against 26.7%
[22.0, 32.1]. The instrument agrees with itself at two sample sizes, which is the first time
that has been checked.

**The constant's total authority is bounded, and the bound is below the band.** Deaths are 82,
82, 81, 82 across the four arms: the gate cannot touch them, because a run that dies on floor
14 does not reach the last stair. Only the stall column moves, at about two wins per point of
gate. At gate 7 there are 28 stalls, so even deleting the gate outright and letting every
stalled run walk out gives at most 62/144 = **43.1%, [35.2, 51.3]**, the bottom edge of the
band, bought by making escape free again. That is exactly what `0df8c3f` R5 introduced the
constant to stop. **The gate is not the lever, and no setting of it reaches the band.**

### The stall standings predicted the sweep before it ran

The per-run egress capture landed the arm before, so arm 1 could be asked which standing each
stalled run actually held: 0 (x8), 1 (x3), 2 (x4), 3 (x8), 4 (x1), 5 (x3), and never 6. Counting
the stalls a lower gate would have released gave a prediction for each remaining arm:

| gate | predicted | actual |
|---|---|---|
| 6 | 34 | 34 |
| 5 | 37 | 38 |
| 3 | 46 | 42 |

Exact at one point of gate, within a win at two, and four wins optimistic at four. The
over-prediction is informative rather than a failure: a lower gate does not merely re-score the
ending, it opens the stair earlier and the run diverges from there, so 8 of the 12 counted
stalls converted and the rest went on to fail some other way. Route counts confirm the
mechanism, `standing` wins rising 15 to 26 while the other three routes fall by 3 between them.

The practical consequence: **a threshold change can now be priced from a single existing
evaluation, and only the promising ones need an arm.** Gate 6 cost an hour to confirm a
prediction of "no change" that the capture had already made for free.

### Where the losses actually are

- **All 28 stalls are at floor 26.** A stall is exactly what it was assumed to be: arrived at
  the bottom, could not open the stair.
- **69 of 82 deaths happen at standing 0.** For the majority of losing runs the standing
  economy is not merely priced wrong, it is never entered at all.
- Deaths are 74% of losses at every gate. Nothing in this sweep addressed them.

So the honest reading is that the question stopped being a tuning question. The remaining move
is the one in the plan's step 4: write down in `guidance/AGENT_SPEC.md` what an agent win rate
is **for**, and judge 26.7% against that rather than against a band nobody justified.

**Done, in `guidance/AGENT_SPEC.md` §What the win rate is for.** The answer is that the rate
carries no target: the agents are an instrument for showing the systems are reachable and the
decisions are real, not a difficulty proxy for a person, and they do not even run the same level
generator the default interactive mode uses. Health is seven structural conditions checkable
from one `eval_stats.json`. All seven currently hold; the closest to its limit is route
concentration at 44% of wins against a ceiling of 60%, or 49% on the 288-run batch. The
aggregate is reported with an interval and compared against the
history in this document, with degeneracy below 10% or above 80% the only absolute call. Every
in-band claim above stays exactly as written: it is the record of what was believed, not a
standard anyone should now measure against.

## What kills a run: attrition, with a healing sigil in hand it cannot see

The escape-gate sweep left deaths as 74% of losses and untouched by any threshold. This is the
first measurement that asked what they are. 288 runs on the corrected telemetry (see below),
clean `~/.vaultcrawl`, `PYTHONHASHSEED=0`.

**76 of 288, 26.4%, [21.6, 31.8]**, against the 77 of 288, 26.7%, [22.0, 32.1] baseline. One
win apart, so the telemetry work moved nothing, which is what a telemetry change should do.
157 died, 55 stalled.

### It is attrition, not burst

The obvious hypothesis from the old numbers was a burst: `hurt_share` said agents spent 2 to 17%
of turns below half health, so it looked like they were healthy and then suddenly dead. **Wrong.**

| reading | value |
|---|---|
| worst single-turn HP fall on a dying run | median **17%** of max, worst 44% |
| dying runs that ever took a hit of 50% or more | **0 of 157** |
| HP twelve decisions before the end | median **21%**, above 75% in only 7 of 157 |
| dying runs never below 25% HP before the end | **0 of 157** |
| share of a dying run spent below 25% HP | median 1.3%, which at 5,000 turns is about 65 turns |

Every run that dies is worn down, sits in the critical band for dozens of turns, and dies there.
`hurt_share` looked reassuring only because it averages over runs of five to ten thousand turns,
so hundreds of desperate turns disappear into thousands of healthy ones. The old number was not
wrong, it was the wrong denominator.

### And the heal never fires

With panic recorded and the label list untruncated, every survival branch is readable for the
first time. Shares of all decisions, 288 runs:

| profile | forced | panic_flee | panic_descend | panic_phase | recall | sigil_escape | flee | shield |
|---|---|---|---|---|---|---|---|---|
| artisan | 1.5% | 1.43% | 0.02% | 0.01% | **0.00%** | **0.00%** | 0.28% | 0.26% |
| cartographer | 13.7% | 9.63% | 4.06% | 0.01% | **0.00%** | **0.00%** | 0.40% | 0.28% |
| emergent | 2.1% | 2.08% | 0.05% | 0.00% | **0.00%** | **0.00%** | 0.16% | 0.37% |
| exploiter | 1.1% | 1.06% | 0.03% | 0.00% | **0.00%** | **0.00%** | 0.07% | 0.33% |
| seeker | 2.2% | 2.11% | 0.04% | 0.03% | **0.00%** | **0.00%** | 0.11% | 0.25% |
| whisper | 3.3% | 1.42% | 1.92% | 0.00% | **0.00%** | **0.00%** | 0.42% | 0.17% |

**`recall` and `sigil_escape` are zero for all six profiles across 288 runs**, and `panic_phase`
is within rounding of zero. Three survival branches that never once fired.

### The cause, and it is a bug rather than a balance number

**First hypothesis, and it was wrong.** `can_heal_meaningfully` gates the HEAL branch and reads
per-part HP, and `tests/known_failures.txt` says the body-part layer is broken, so the gate
looked dead. Sampled on real runs it is alive: True on 48 of 48 low-HP turns of a dying artisan
and 913 of 927 for a cartographer. The parts do take damage. (A hand-set `player.hp` leaves the
parts full, which is what made the gate look stuck; that was an artifact of the probe.)

The actual cause is one line up. The HEAL branch matches its sigil by exact string:

```python
if sig.get("ability") == "Recall" or sig.get("base") == "Recall":
```

A quality-graded sigil has `ability = "Legendary Recall"` and **`base = ""`**. Sampled over one
artisan run of 10,485 turns:

| what the agent held | turns | matches `== "Recall"` |
|---|---|---|
| `Legendary Recall` | 2,746 | no |
| `Uncommon Recall` | 1,084 | no |
| `Epic Phase` | 579 | no |
| `Epic Recall` | 52 | no |
| `Recall` | 65 | yes |

**The agent carried a Recall sigil on about 3,900 turns and could see it on 65.** It is holding
the heal and cannot read the label. The same exact-match appears at five sites in `agent.py`:
HEAL (`:245`), PANIC's Phase escape (`:252`), FORGE's "what do I already have" set (`:384`,
which is why an agent keeps forging a Recall it already owns), `sigil_escape` (`:547`) and
deploy (`:615`).

That is the whole diagnosis, and it fits the loss profile exactly: runs ground down over dozens
of turns in the critical band, holding an unreadable heal, falling through to `panic_flee` and
running for the stairs instead.

### Not fixed here, deliberately

This tranche pre-registered that no game behaviour changes in it, because a fix folded into a
diagnosis is a fix nobody measured. The next tranche is the fix and its measurement: match the
base ability inside a graded name at all five sites, then 288 runs against the 26.4% recorded
above. The expected direction is up, and it should be checked rather than assumed, since a heal
that fires also changes what the agent spends its turns doing.

### Health checklist, recomputed on the corrected telemetry

| condition | limit | current |
|---|---|---|
| every profile can win | above 0 for all six | 6 of 6 |
| every route is used | all 4 present | 4 of 4 |
| no route dominates | at most 60% | 50% (`standing` 38 of 76) |
| no verb is broken | empty | empty |
| decisions are contested | at most 0.05 | 0.000 |
| the decision space is used | at least 20 | 25.1 to 30.4 |
| profiles actually differ | every pair above 0.10 | **0.151 to 0.506** |

`policy_divergence` rose from 0.123-0.439 because it is now computed from whole policies rather
than each profile's top 8 labels. All seven conditions hold. Route concentration at 50% is the
closest to its limit, as it was before.

## The graded-name fix: correct, real, and it did not restore the heal

288 runs after the fix, same protocol. **The pre-registered mechanism check failed, so this is
reported as a failure before anything else.**

| | before | after |
|---|---|---|
| wins | 76/288, 26.4% [21.6, 31.8] | **63/288, 21.9% [17.5, 27.0]** |
| deaths | 157 | 184 |
| stalls | 55 | 41 |
| median death floor | 12 | 10 |
| `recall` share | 0.00% | **0.00 to 0.02%** |
| `sigil_escape` share | 0.00% | **0.00%** |

The intervals overlap, so the aggregate drop is not significant on its own. But five of six
profiles fell, and there is a mechanism, which is worth more than the interval.

### Why the heal still starves

The string match was real and is fixed. It was not the reason `recall` never fires. Counting the
three HEAL conditions separately over whole runs:

| | artisan | cartographer | seeker |
|---|---|---|---|
| turns | 6,984 | 1,202 | 6,203 |
| **holding no sigil at all** | **6,690 (96%)** | **684 (57%)** | **5,776 (93%)** |
| holding a Recall | 245 | 54 | 353 |
| below 60% HP with a Recall and a wound | 0 | 3 | 87 |

**The slots are empty almost all the time.** On the one profile that did get 87 chances, it took
the heal about once. So there are two faults behind the 0.00%, and the string match was only the
first.

### The second fault, which the fix exposed

`deploy` and `recover` both score on the **`explore`** profile key (`agent.py:635`, `:641`), a
key belonging to a different activity entirely, worth 15 to cartographer and 8 to seeker. HEAL
scores on `recall`, worth 3 to 6, with urgency `(100 - hp) // 4`. At 50% HP that is 12 against a
deploy candidate at 18 to 31. **Deploy outbids the heal, and deploying a Recall takes it out of
the slots**, after which the heal cannot fire at all.

Before the fix this was invisible because deploy was gated on the same broken string match, so
the branch was unreachable for graded sigils. Unblocking it did exactly what the label shares
show:

| label | artisan | cartographer | emergent | exploiter | seeker | whisper |
|---|---|---|---|---|---|---|
| deploy | 0.47 to **1.78** | 0.54 to **3.55** | 0.08 to **1.09** | 0.32 to **1.10** | 0.41 to **1.55** | 0.54 to **1.60** |
| recover | 3.26 to **7.31** | 0.77 to **5.01** | 0.27 to **2.63** | 0.85 to **3.30** | 3.55 to **6.40** | 1.17 to **3.71** |

Deploy triples to sevenfold, recover follows it, and average sigils forged falls on every profile
(whisper 3.25 to 1.62). The agent now spends its turns putting sigils on the floor and picking
them up again, and is unarmed in between.

**Correction to the previous entry.** "It is holding the heal and cannot read the label" was true
of the string match and wrong as a complete account: the agent usually holds nothing at all. The
label-blindness was real and worth fixing on its own terms, but it was not the cause of the
0.00%.

### Kept, and what comes next

The fix stays. Deploy was producing nameless entities with no effect, the Recall beacon tick
raised `AttributeError` the first time it ever reached execution, and the locus handed out
duplicates of what you already carried. Those are defects whatever the win rate does, and this
tranche pre-registered adoption on that basis.

The named next lever is **the deploy and recover scoring**, which is a mis-keyed candidate rather
than a balance number: an action that removes your survival tool should not be scored on the
weight for exploring, and should not outbid using it. That is one tranche, and it should be
measured against the 63 of 288 recorded here.

One small gain to record: `diplomacy` appeared as a **fifth win route** (whisper, seed 46), the
final warden laying down its arms at parley. Route concentration also fell, top route 50% to 44%.

### Health checklist

All seven still hold: 6 of 6 profiles win, all routes used, top route 44%, no broken verbs,
`uncontested_share` 0.000, `labels_used` 23.0 to 29.9, `policy_divergence` 0.114 to 0.562. The
divergence floor is now close to its 0.10 limit and is worth watching.

## Re-baseline at 123 of 288, and the third livelock it exposed

288 runs, clean `~/.vaultcrawl`, `PYTHONHASHSEED=0`, against `c33a4b8`.

| | wins | rate | 95% interval |
|---|---|---|---|
| this tranche | 123/288 | 42.7% | [37.0, 48.4] |
| prior baseline | 77/288 | 26.7% | [22.0, 32.1] |

Non-overlapping. Per profile: artisan 35.4%, cartographer 39.6%, emergent 31.2%,
exploiter 31.2%, seeker 56.2%, whisper 62.5%.

**Read the caveat before the number.** A livelocked run burns its turn allowance and is cut
off, so it was always a guaranteed loss rather than a badly played one. Two livelocks were
fixed in this tranche. Deaths rose from 74% to 90.3% of losses, which is the same fact from
the other side: the turn-capped non-deaths were mostly loops, and they stopped happening. Runs
that now finish and runs that now play better are different claims, and this measurement
evidences the first far more strongly than the second.

The prediction registered before the run was right on direction and wrong on attribution. It
named artisan and seeker as the carriers, on the grounds that those were the two profiles
caught livelocking, and predicted cartographer would be flat. Cartographer gained as much as
artisan, 22.9% to 39.6%. The gains are broad, so the causal story is incomplete.

### Two health conditions moved the wrong way

- **Top route concentration rose**, 44% to 48.8% (standing 60, boss_killed 37, commune 14,
  truths 9, diplomacy 3). All five routes still used.
- **The policy-divergence floor fell to 0.09**, crossing the 0.10 line the previous assessment
  flagged as worth watching, with artisan and seeker now the most alike pair. The median fell
  too, 0.28 to 0.24. The profiles are converging, which is what removing pathologies should do
  when the pathologies were themselves distinctive, and is worth watching precisely because
  the aggregate looks good.

`panic_phase` reads 0.00% across all six profiles. That is **not** by itself evidence of a
broken verb, for the reason established in `AGENT_SPEC` §A label share is the wrong instrument
for an emergency verb: it needs low HP, a hostile in range and a Phase sigil in hand at the
same moment. The conditional-uptake instrument is how to check it, and it has not been run.

### A third livelock, found in the per-run rows rather than the table

The aggregate table cannot show a stall: a locked run's `turns_survived` looks perfectly
ordinary. Scanning all 288 per-run label histograms for a single dominant label found **15
runs where one label took 60% or more of the decisions, of which 0 won**.

Thirteen of the fifteen are one failure. The agent reaches floor 26, the final stair is shut,
and it stands on it choosing `descend` or `panic_descend` for thousands of turns. Every one
carries the same `egress_why`:

> Fell the warden, commune with it, carry 4 truths (you have 0), or earn standing 7 (you have
> 5) with its house.

Four routes offered, none pursued. Seeker seed 6 spent 10,573 turns on it; cartographer seed
38 spent 94.2% of its decisions there. Several were one point of standing short.

Same shape as the other two: a candidate offered on turns its verb cannot succeed, failing
without spending a turn. Neither descend site checks the gate. `runtime/agent.py` appends
`("descend", 50, ...)` in the de-escalation branch and another in the stairs branch, and the
PANIC branch's `panic_descend` is a forced override that bypasses the candidate list entirely,
which is why three of the thirteen wear that label instead.

**The fix is not to gate on `egress_ready` alone.** The snapshot exposes that flag on every
floor while `Game.egress_ready()` describes the *last* stair only, so gating on it directly
would block ordinary descending everywhere. The condition is being at the boss floor with the
gate shut. All three sites need it, the forced one included.

This is the third instance of one root and the second found only after fixing the one in front
of it. Do not assume it is the last. `runtime/weight_audit.py` plus a scan of per-run label
histograms is the pair of instruments that finds them; the aggregate table never will.

## Warm versus cold: the world's memory is a one-way ratchet

The experiment this project had never run. `RunChronicle` carries a run's events forward and
`Upheaval` turns them into live modifiers on the next descent, but `agent_eval` deliberately
omits that return arrow, so **every balance number in this document describes a world with no
memory.** Two arms, 48 runs each, identical (agent, seed) pairs, identical order, isolated
`HOME`, `PYTHONHASHSEED=0`.

| | cold | warm |
|---|---|---|
| wins | 16/48 (33.3%) | **6/48 (12.5%)** |
| mean floor | 17.6 | **11.0** |
| mean labels used | 30.6 | 27.5 |
| max top-label share | 47.8% | 63.6% |
| win paths | standing 9, boss_killed 4, commune 2, truths 1 | commune 4, boss_killed 2 |

Paired: 3 cold-losses became warm-wins, **13 cold-wins became warm-losses**. Of 16 discordant
pairs, 13 fell one way, p about 0.021 two-sided. This is not seed noise.

### Why, and it is not a bug

`RunChronicle.to_upheaval_events` can emit `idea_ascends`, which empowers a note's enemy. It
has **no path that emits `power_wanes`**, which would diminish one. `Upheaval` supports waning
perfectly well; only `vaultcrawl/evolve.py` produces it, and that runs when you edit notes
between bakes, not when you play. So run-to-run memory can only ever escalate.

By the end of the warm arm, **5 of the 9 enemy-bearing notes were permanently empowered**, and
nothing in the game can ever unempower them. The chronicle also saturates: it reached 9 events
and stopped, because `save_chronicle` dedupes on `(kind, note, faction, region, pos)` and later
runs regenerate what is already stored. So the curriculum is short, monotonic and punitive: a
few lessons, all of them "the world got harder", and then silence.

The damage is not gradual. Warm mean floor is already 11.3 against cold's 21.2 at seed 0, with
only 5 events inherited. One prior run is enough to halve how deep the next one gets.

### What this means for the idea

A world that remembers is the design goal, and the machinery genuinely works now (see
`40b8ec2`; before that fix the two arms were byte-identical because the ascended set held
death-cause strings that could never match a note id). What it does not yet have is a
**counterweight**. Impressions accumulate in one direction only, so the syllabus teaches
exactly one lesson. The interesting version of this feature needs at least one of:

- a `power_wanes` path from play, so notes the player repeatedly defeats fade
- decay, so an ascendancy expires after N runs rather than persisting forever
- a cap on how much of the world can be empowered at once
- a compensating gift, so a harder world is also a richer one (the sanctum and monument
  events exist and are the obvious candidates, but `forge_grown` produced only 2 events
  against 5 ascendancies)

Until one of those exists, **do not wire the chronicle into `agent_eval`.** Not because
cross-run state ruins a benchmark, which is the reason recorded elsewhere in this document,
but because in its current shape it would make every arm progressively unwinnable and the
comparison meaningless.

## Post-egress-gate baseline: 130 of 288, and what the aggregate could not show

288 runs, clean `~/.vaultcrawl`, `PYTHONHASHSEED=0`, against `abed371`. The one behavioural
change since the previous 288 is the egress gate (`6086f50`); the chronicle key fix is
inert here because `agent_eval` leaves `chronicle_out` off.

| | wins | rate | 95% interval |
|---|---|---|---|
| post-gate | 130/288 | 45.1% | [39.4, 50.9] |
| pre-gate | 123/288 | 42.7% | [37.0, 48.4] |

**The aggregate does not show this fix and must not be used to claim it.** The intervals
overlap almost entirely. Paired on identical seeds: 12 losses became wins, 5 wins became
losses, 17 discordant, McNemar exact two-sided **p = 0.14**. Not significant. Predicted in
advance, for the right reason: 13 runs out of 288 is 4.5 points against a measurement whose
interval is about plus or minus six.

### What the per-run rows do show, categorically

Runs where a single label took 60% or more of decisions: **15 before, 2 after.** The two
survivors are `panic_flee` on cartographer seeds 5 and 28, byte-identical to their pre-fix
rows. They are pre-existing and unrelated; no new loop appeared.

All 13 egress stalls ended. Individually:

| outcome | count |
|---|---|
| won | 8 |
| lost without stalling | 5 |
| still stalled | 0 |

Seven of the eight wins came by `boss_killed` and one by `commune`, which is the point: the
agent was standing on a shut stair with four routes available and is now taking them. Seeker
seed 6, which had spent 10,573 turns choosing `descend`, ran 17,461 turns and won.

**The prediction registered before the run was wrong.** It said fewer than half of the 13
would convert, on the reasoning that several were genuinely short of every route rather than
merely looping. Eight of thirteen converted. The loop was costing more than the shortfall was.

### Health

- **Top route concentration fell 48.8% to 41%** (standing 53, boss_killed 52, commune 15,
  truths 7, diplomacy 3). The regression flagged in the previous baseline has reversed, and
  the top two routes are now nearly level.
- Deaths are 93.7% of losses, up from 90.3%. Same fact from the other side: fewer turn-capped
  non-deaths, because fewer runs stall.
- **The policy-divergence floor fell again, 0.09 to 0.073**, with artisan and exploiter the
  most alike pair; median 0.24 to 0.22. This is the third consecutive measurement in which the
  profiles converged, it is now well under the 0.10 line an earlier assessment set as worth
  watching, and nothing in this tranche addressed it. It is the open structural problem.

## The counterweight works, and the divergence hypothesis is dead

Re-run of warm versus cold after `6513be2` added the wane path. 48 runs per arm, identical
(agent, seed) pairs, isolated `HOME`, `PYTHONHASHSEED=0`.

| | cold | warm, before the wane path | warm, with it |
|---|---|---|---|
| wins | 16/48 (33.3%) | 6/48 (12.5%) | **18/48 (37.5%)** |
| mean floor | 17.6 | 11.0 | 16.0 |
| paired net vs cold | n/a | **-10** | **+2** |

The ratchet is gone. Warm is now statistically indistinguishable from cold: 16 discordant
pairs, 9 one way, two-sided p = 0.80. That is the intended outcome. A world that remembers
should not be a world that punishes; it should be a different world of roughly the same
weight. It is now.

One incidental gain: **route concentration is lower in the warm arm.** Cold's top route is
`standing` at 9 of 16 wins (56%); warm's is `boss_killed` at 8 of 18 (44%), and warm reaches
four routes including a `diplomacy`. A world whose creatures have been empowered and faded
differently pushes wins through different doors. Warm runs are also shorter and win more often
(5,062 turns against 6,128), which reads as more decisive rather than more lucky.

### The hypothesis this was really testing, and it failed

The standing worry is that the six profiles keep converging: divergence floor 0.09 then 0.073
across recent baselines, under the 0.10 line an earlier assessment set. The hypothesis was
that the convergence is caused by *static worlds*, that the differentiation which disappeared
had been coming from the pathologies since removed, and that a world changing between runs
would give the profiles different terrain to be different on.

| | cold | warm |
|---|---|---|
| divergence floor | 0.089 | **0.071** |
| median | 0.256 | 0.260 |

**Wrong, and wrong in direction.** The prediction registered before the run was that warm
would be higher by 0.02 to 0.04. Warm is *lower* by 0.018 at the floor and flat at the median,
with `seeker|whisper` the most alike pair in both arms. A remembering world does not keep the
profiles distinct, and may mildly homogenise them: everyone faces the same empowered notes and
converges on the same answers to them.

So **profile convergence remains unexplained and unaddressed**, and one plausible cause is now
eliminated. The next candidates are the ones already documented and not yet acted on: a third
of `_score` call sites never let a weight bind, and negative weights are arithmetically inert,
so the mechanism that is supposed to differentiate the profiles is partly missing rather than
partly starved.

A note on method. The 1-seed smoke of this same comparison put the divergence floor at 0.174
cold against 0.196 warm, which is the opposite of the 48-seed result and would have "confirmed"
the hypothesis. Six runs is not a measurement, including when it agrees with you.

## PROFILE_BIAS: the convergence lever, and what it cost

`_score` returned `max(weight, urgency)`, so a weight below the current urgency was not
outranked but **erased**: the candidate scored identically for all six profiles. Measured at
12 of 33 call sites where no weight had ever decided a score, and it made `fight: -5`
arithmetically identical to `fight: 0`. `PROFILE_BIAS = 0.15` (`12a68e1`) adds
`weight * BIAS` to every score, keeping the preference live without touching the identity
floor.

Measured with `runtime/chained_eval.py`, 48 runs per arm, identical (agent, seed) pairs
against the pre-change run, isolated `HOME`, `PYTHONHASHSEED=0`.

| | cold before | cold after | warm before | warm after |
|---|---|---|---|---|
| divergence floor | 0.089 | **0.117** | 0.071 | **0.089** |
| divergence median | 0.256 | 0.233 | 0.260 | 0.265 |
| wins | 16/48 | 14/48 | 18/48 | 10/48 |
| max top-label share | 47.8% | 38.2% | 52.0% | 71.9% |

**The target moved, and it was predicted in advance.** The divergence floor rose 0.028 in the
cold arm and is back above the 0.10 line an earlier assessment set as worth watching, for the
first time in several baselines. It rose 0.018 warm. The most-alike pair changed from
`seeker|whisper` to `artisan|exploiter` in both arms, which is what a real change in how
profiles differ looks like rather than a shuffle.

**Win rate is unaffected where it matters.** Cold 16 to 14, paired 7 gained and 9 lost across
16 discordant pairs, two-sided p = 0.80. That is the intended result: this was meant to make
the profiles *distinct*, not better, and a win-rate jump would have meant the constant was
buffing everyone instead.

**One signal to watch, not yet to act on.** The warm arm fell 18 to 10, paired 4 gained and 12
lost, p = 0.077. Marginal at this sample and not significant, but it is the only number that
moved against us. A plausible mechanism, untested: in a world whose notes have been empowered
and faded, leaning harder into a preference is worth less than responding to what changed, so
a stronger bias could cost adaptability exactly where the world varies. **Do not act on this
without a 288-run arm.** If it is real, the lever is the constant, and the bound documented in
`tests/test_profile_bias.py` allows anything under 0.25.

No stalls: zero dominated runs cold, one warm (`panic_flee` 71.9% on a 599-turn run that died,
`d/t` 1.03, which is a short run rather than a loop). Peak decisions per turn 1.08 cold and
1.17 warm, both with healthy label spreads.

## Phase A closed, Phase B opened, and two of my conclusions retracted

288 runs, 144 per arm, identical (agent, seed) pairs, isolated `HOME`, `PYTHONHASHSEED=0`,
at `a90f8f4`.

### The warm signal was real

| | cold | warm |
|---|---|---|
| wins | 58/144 (40.3%) | 42/144 (29.2%) |
| mean floor | 18.4 | 14.8 |

Paired: 19 cold-losses became warm-wins, 35 cold-wins became warm-losses, 54 discordant,
**two-sided p = 0.040**. The prediction registered before the run was that this would come
out null, at about 30% odds the effect was real. Wrong. Under current code the warm arm is
meaningfully handicapped.

What that does **not** establish is that `PROFILE_BIAS` caused it. The only pre-bias
warm-versus-cold comparison is n=48 and gave +2 at p=0.80, which the next section shows is
too small to trust for anything.

### Retraction: n=48 divergence numbers cannot carry a conclusion

The same code, measured twice at different sample sizes:

| | n=48 | n=144 |
|---|---|---|
| cold divergence floor | 0.117 | **0.059** |
| warm divergence floor | 0.089 | **0.082** |

Two claims in this document rest on the n=48 column and neither survives.

1. **"`PROFILE_BIAS` lifted the divergence floor above 0.10 and closed health condition 7."**
   Retracted. At n=144 the cold floor is 0.059. **Condition 7 still fails**, in both arms.
   The change may still be correct on its merits (a weight erased on a third of call sites is
   a defect regardless), but the measurement claimed for it does not hold.
2. **"The dynamic-world explanation for convergence is dead, and refuted in direction."**
   Retracted. At n=144 the warm floor (0.082) is *above* cold (0.059), which is the direction
   originally predicted. The n=48 result that reversed it was noise.

The lesson is one this document already recorded after a 1-seed smoke gave the opposite of a
48-seed answer, and which was then repeated at 48 against 144: **divergence floors are order
statistics over 15 pairs and are wildly unstable at small n.** Do not report a floor from
fewer than 144 runs per arm, and prefer the median, which moved far less (0.208 to 0.256
across the same comparisons).

### The first emergence measurement

`coupling_pairs`, ordered event pairs within a bounded window, replacing an `event_kinds`
metric pinned at 12.3 of 13:

| | cold | warm |
|---|---|---|
| coupling pairs per run | 82.2 | 70.6 |
| coupling density | 0.661 | 0.675 |
| ambient (`noise`) share | 88.8% | 89.5% |

**The instrument works.** It separates the arms by 14% where `event_kinds` read 12.3 against
12.3, and density sits at 0.66 with real headroom rather than at 0.95. It is the first number
this project has for systems *meeting* rather than merely running.

**The signal it reports is negative.** A world with memory produces *fewer* couplings per run,
not more. Consistent with the win data: warm runs are shorter (5,304 turns against 7,365) and
die earlier, so fewer systems get the chance to meet. Memory currently costs interaction.

### `haunted` is still 0, in both arms, and now we know why

The sharpest Phase B prediction was that `haunted` would fire in the warm arm, being
structurally impossible cold. It fired **0 times in 144 warm runs** despite 143 of them
inheriting upheaval. Refuted.

The chain: `haunted` needs ghosts, ghosts need `note_lost`, and `to_upheaval_events` emits
`note_lost` only for notes where `droll(note_id, 3) == 0`. **That is deterministic per note
id, not a per-run roll.** On the sample vault exactly two of ten notes qualify, `discipline`
and `second brain`, and the agent has never read either during a chained run. `record_lore`
is wired (`history.py:218`) and `lore_read` fires 625 times across the benchmark, so the
remaining unknown is whether those events and that recorder are even on the same path.

So the haunting mechanic is gated behind a fixed 2-of-10 subset *and* the agent choosing to
read those particular notes. On this world it has never once occurred.
