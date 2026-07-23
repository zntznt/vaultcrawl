# CLAUDE.md

## What this is

Two codebases under one roof:

- **`vaultcrawl/`** — the bake pipeline. Markdown vault → graph metrics → mechanical slots
  (deterministic) → LLM names/lore (the "skin", can never move a number) → `world.json`.
  Entry: `python3 -m vaultcrawl.bake <vault> -o world.json`. Zero deps, stock Python.
- **`runtime/`** — a terminal roguelike rendering a baked `world.json`, with a 28-system
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
python3 -m pytest tests/ -q                                       # 64 test modules
```

## Process — read this before touching anything

**Every domain has a spec. Find your task below, read the spec first, then work.**

| If your task is... | Read this first | What it covers |
|---|---|---|
| Understanding systems, the event bus, or System base class | `SYSTEMS_SPEC.md`, `INTERACTIONS_SPEC.md` | System hooks, canonical events, query API, contracts |
| Working on enemy/monster AI or NPC behavior | `BRAINS_SPEC.md`, `MIND_SPEC.md` | Brain interface, capability ladder, memory/planning tiers |
| Working on player-agent AI or agent profiles | `AGENT_SPEC.md` | UniversalBrain, 6 profiles, scoring formula, perception |
| Working on ecology (flora, fauna, weather, structures, decay) | `ECOLOGY_SPEC.md` | Autonomous world-layer, allegiance model, terrain write-API |
| Working on sigils, forge, salvage, or the matter economy | `SALVAGE_SPEC.md`, `QUALITY_SPEC.md` | Shatter→salvage→forge loop, quality grades, proficiency |
| Working on senses, perception, or creature detection | `SENSES_SPEC.md` | Two-layer perception (detection/identification), sense profiles |
| Working on quests, dialogue, Keepers, or machines | `DEEPEN_SPEC.md` | Quest lifecycle, NPC parley, Fabricator/Terminal placement |
| Working on loci, crafting, wear, recipes, or skills | `CRAFT_SPEC.md`, `LOCI_SPEC.md` | LocusSystem type-casting, 4 workspace rituals, 25 consumables, 5 skill trees |
| Working on level gen, architecture compiler, or sandbox mode | `ARCHITECTURE_SPEC.md` | Pattern-language compiler, semilattice world, wholeness scoring |
| Working on room fixtures, scenery, or sense-of-place | `DESIGN_PLACE_PANEL.md` | Fixture placement, examinable voice, ambient narrator |
| Working on cross-run persistence or Upheaval | `runtime/persistence.py` (docstring) | RunChronicle, terraforming events, death artifacts |
| Working on knowledge, fog-of-war, or map mechanics | `runtime/knowledge.py` (docstring) | Known/learned notes, region mapping, faction insight |
| Understanding what player verbs exist and what's missing | `SYSTEMS_GAP.md` | 28-system reachability audit, verb binding gaps |

**Rule:** Before touching any file in a domain, read the spec for that domain. Specs contain contracts, test recipes, and cross-system interaction rules. Skipping the spec produces work that breaks invariants.

## Agent architecture

Six agent profiles (artisan, cartographer, emergent, exploiter, seeker, whisper) share one
`UniversalBrain` class in `runtime/agent.py`. Profiles are scoring weight dicts. The identity
formula is: `score = max(profile_weight, state_urgency) + turn_bonus`. Berlin-compliant:
every agent CAN do everything. Starting state determines which branches are reachable.

The agent communicates with the game via a 14-verb `AgentAction` vocabulary
(`runtime/agent_action.py`) and reads the world through `agent_state()` in
`runtime/agent_perception.py`. See `AGENT_SPEC.md` for the full architecture.

## Core invariants

1. **Berlin Interpretation compliance — mandatory, project-wide.** Per the Berlin
   Interpretation of roguelikes: the game must have no class-locked features. Every
   agent must be able to do everything. Every system must be reachable by anyone.
   No ability gates. No personality-gated code paths. No hardcoded character differences.
   Differentiation comes exclusively from *starting state* (HP, DEF, matter, sigils,
   knowledge, standing, recipes) and *preference biases* (scoring weights, never locks).
   If you add a system, every profile must be able to interact with it. If you add an
   item, every profile must be able to craft or acquire it. If you add a locus activation
   type, it must be reachable through the universal tree. The six profiles are starting
   states + preference biases — never character classes. See `AGENT_SPEC.md`
   §Berlin Interpretation for the architectural contract. **Violating this is a design
   regression of the highest order.**
2. **Deterministic skeleton vs. LLM skin.** The LLM gets only `_`-prefixed flavor inputs
   and returns only `name`/`flavor`/`title`/`objective`. It cannot move a tier, depth, or
   power number. Do not break this seam.
3. **No em dashes** — ever, in anything (code, comments, docs, UI, commit messages). Rephrase.
4. **Determinism first.** No `random.seed()`, no `hash()`-seeded ordering, no wall-clock
   in the bake path. Seed RNG from SHA-256 of stable keys.
5. **Tests are pytest-style.** `pip install pytest && python3 -m pytest tests/ -q`
   (64 test modules). `unittest discover` finds nothing.
6. `ponytail:` comments mark deliberate shortcuts. Prefer deleting over adding.

## Known issues

- **Bake determinism, half-fixed.** Edge ordering is sorted, so re-baking on the same
  machine is byte-identical. Still open: `activity` derives from file mtimes and is baked in.
- **Privacy is enforced.** `#nogame`/`#private` tags exclude notes at ingest.
- **Real-LLM path is unproven.** No Anthropic-backed `complete_json` exists. The offline
  stub is the default. A `_named()` fallback prevents crashes when LLM output is missing keys.
- **`runtime/arch/` is LIVE.** The Alexander compiler powers the default interactive game.
  Still unwired: §10 word-level flow, the `siteplan` bake block, continuous-megastructure mode.
