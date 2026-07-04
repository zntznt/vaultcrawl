# CLAUDE.md

## What this is

Two codebases under one roof:

- **`vaultcrawl/`** — the bake pipeline. Markdown vault → graph metrics → mechanical slots
  (deterministic) → LLM names/lore (the "skin", can never move a number) → `world.json`.
  Entry: `python3 -m vaultcrawl.bake <vault> -o world.json`. Zero deps, runs on stock Python.
- **`runtime/`** — a terminal roguelike that renders a baked `world.json`, with an 18-system
  stack (sigils, reactions, senses, brains, factions, ecology).
  Entry: `python3 -m runtime.play world.json` (interactive) or `--auto` (headless AI demo).

Run both from the repo root so the packages import.

## The core invariant

Deterministic mechanical skeleton vs. LLM semantic skin. The LLM gets only `_`-prefixed flavor
inputs and returns only `name`/`flavor`/`title`/`objective` — it is structurally unable to move a
tier, depth, or power number (`generate.py:69-81`, schemas in `prompts.py:115-152`). **Do not
break this seam.** If you add a generated field, keep mechanics out of the LLM's output schema.

## Known issues (verified)

- **Bake determinism, half-fixed.** Edge ordering is now sorted (`mapping.py`), so re-baking
  on the same machine is byte-identical. Still open: `activity` derives from file **mtimes**
  (`ingest.py:115`) and is baked in, so "identical world on any machine" is false after a vault copy.
- **Privacy is enforced.** `#nogame`/`#private` tags exclude a note entirely at ingest, and
  excluded titles are scrubbed from kept bodies (tested in `tests/test_privacy.py`). Sandbox
  growth on large vaults (~20s at 120 notes) is cached per seed in `<world>.site.json`
  (`Game(site_cache=...)`); stale caches regrow automatically.
- **Real-LLM path is unproven.** No Anthropic-backed `complete_json` exists; `generate_world`
  indexes `out["name"]`/`out["flavor"]` with no fallback, so a missing key crashes the bake.
- **`runtime/arch/` is LIVE.** The Christopher-Alexander compiler (grow/carve/wholeness +
  interiors.py room-scale patterns: colonnade/sanctum/alcoves/stones/overgrowth/ruin) now
  powers the default interactive game: `Game(sandbox=True)` builds one grown semilattice world
  (no floors; walk inward, periphery to greatest center). The classic descent remains for
  `--descent`, `--auto`, and the floor-based tests. Still unwired from the spec: §10 word-level
  flow, the `siteplan` bake block, and the "continuous megastructure sliced into floors" mode.

## The systems gap (read `SYSTEMS_GAP.md`)

Mostly closed. The interactive UI now binds 9 verbs: move, descend, wait (`.`), examine (`x`),
cast (`c`, `SigilSystem.cast`), forge (`f`, autopilot off in interactive), breakdown (`b`),
bump-attack, quit. Baked flavor surfaces in play (floor entry, first blood, examine); rooms
carry note identities with contextual placement; marginalia weave the corpus. Still open per
`SYSTEMS_GAP.md`: a direct quest accept/turn-in verb, and explicit talk (optional).

## Relations & embodiment

Hostility is faction-aware, not player-special: `Game.hostile(a, b)` (actors) layers kin /
rival-house / reputation (`FRIEND_STANDING`) rules over the legacy `_hostile` string table,
and every spawn carries `actor.faction` (its region's factionId). All engine paths
(try_move, _npc_step, sense.hostiles, senses.Perception) route through it. `--embody WHO`
(runtime/play.py `embody()`) transfers control to any actor; nothing else changes, so its
faction relations simply become yours.

## Conventions

- **No em dashes** in anything user-facing (prose, comments, copy). Rephrase.
- Determinism first: no `random.seed()`/global state, no `hash()`-seeded ordering, no wall-clock in
  the bake path. Seed RNG from SHA-256 of stable keys (see `_shash`/`_rng`). Sort before iterating
  sets/dicts whose order reaches output.
- Tests are pytest-style but **pytest is not a declared dep** — `pip install pytest` then
  `python3 -m pytest tests/ -q` (30 tests, ~0.3s). `unittest discover` finds nothing.
- `ponytail:` comments mark deliberate shortcuts; there's a history of over-engineering audits.
  Prefer deleting over adding.
