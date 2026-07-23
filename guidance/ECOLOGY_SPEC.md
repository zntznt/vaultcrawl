<!-- Status: Legacy (pre-Berlin) | Written: 2026-06-29 | Berlin compliance not yet applied to this domain -->
# Ecology contract — an autonomous world (player/faction-independent)

This layer adds world entities that live, react, and die on their OWN logic — flora,
fauna, weather, structures, decay. They respond to the elemental substrate (reactions),
to time, and to each other. The player and factions can exploit or get caught in them,
but these systems pursue no one's interest.

Read with `SYSTEMS_SPEC.md` + `INTERACTIONS_SPEC.md` (same Game/System API and bus).
Work in `/mnt/workspace/output/vaultcrawl` (cd every bash; cwd does NOT persist). Pure
stdlib. Deterministic: seed from `game.seed`+floor+your name. None-guard EVERY
cross-system call (a partner may be absent — the world must still run).

## You OWN exactly one NEW file

Create `runtime/<your-system>.py` (a `System` subclass) and `tests/test_<your-system>.py`.
Do NOT edit any other file. Cross-talk happens only through the bus + the command/query
API below.

## New engine facilities (already in place)

- **Allegiances.** `Actor.allegiance ∈ {"player","monster","wild"}`. The turn loop makes
  any non-player actor target the nearest *hostile*: monster↔player, monster↔wild, and
  wild↔monster are hostile; **wild↔player are NOT** (wildlife ignores you). So a `wild`
  creature automatically fights `monster`s through normal combat — you get that for free.
  Build wildlife with `runtime.entities.make_critter(name, glyph, x, y, hp, atk, defense=0, source="")`
  and append to `game.actors`.
- **Universal death.** `game.kill(actor, cause)` removes an actor and emits
  `actor_died {actor, cause, pos}` on the bus. ANY death (monster, critter) flows through
  here, so decay/scavengers can react. (`enemy_killed` is still emitted separately, only
  for player/environment kills the factions notice.)
- **Terrain write-API on reactions** (call via `r = game.system("reactions")`, guarded):
  - `r.ignite(x, y, life=6)` — set a tile on fire
  - `r.add_prop(x, y, prop)` — add `"wet"|"charged"|"acid"|"ice"|"sacred"|"fire"`
  - `r.clear_prop(x, y, prop)`
  - reads: `r.element_at(x,y)`, `r.is_hazard(x,y)`, `r.props_at(x,y)`

## Canonical events (bus)

| event | payload | who |
|---|---|---|
| `actor_died` | `{actor, cause, pos}` | game.kill (every death) |
| `enemy_killed` | `{enemy, cause}` | game (melee) / reactions (environment) |

You may define your own additional events; document them.

## The command/query API each owner EXPOSES (exact signatures)

Other ecology systems call these on `game.system("<you>")`, all None-guarded by callers:
- **flora**: `flora_at(x,y) -> bool`, `consume(x,y) -> bool` (grazer eats the plant; True if there was one)
- **decay**: `corpse_at(x,y) -> bool`, `consume(x,y) -> bool` (scavenger eats the corpse)
- **fauna**: (no required query API)
- **weather**: `current(game) -> str` (the active weather word, for HUD)
- **structures**: `hazard_tiles(game) -> list` (armed traps — so the auto-agent avoids them)

## Glyph budget (overlay on floor cells only; don't collide)

Reserved already: `@ > # . M H ; n Y z & _ % ^ ~ / : , + $ ? ) [ = * !` and lowercase
enemy letters `s g w r e b c h`. Your allotment:
- flora: `;` (plants) — overlay
- fauna: critter glyphs via `make_critter` — grazer `n`, scavenger `z`, predator `Y` (these are real Actors, drawn by core; no overlay)
- structures: crystal `&`, armed trap `_` (sprung trap reverts to floor) — overlay
- decay: corpse `%` — overlay
- weather: no glyph (it shapes the substrate); surface state via `status_line`

## What each owner builds

**flora** (`runtime/flora.py`, `FloraSystem`, name `"flora"`) — the world's vegetation.
- Seed from the vault's most-common tag (scan `m["graph"]["nodes"][*]["tags"]`) — that tag
  is the dominant "weed". On `on_floor_enter`, sprout a handful of plants on floor tiles.
- Each `on_player_act`: spread to adjacent floor tiles (slowly). React to the substrate
  (query/guard reactions): a plant on a `fire` tile **burns** — remove it and `r.ignite`
  one adjacent floor tile (fire runs through vegetation); on `wet` it spreads faster; on
  `acid` it dies; on `sacred` it blooms (heal +1 to any actor standing on it).
- Expose `flora_at`, `consume`. Render `;` on plant cells. Indifferent to everyone.

**fauna** (`runtime/fauna.py`, `FaunaSystem`, name `"fauna"`) — wildlife with drives.
- On `on_floor_enter`, spawn a few `wild` critters (`make_critter`, allegiance wild):
  **grazers** (`n`) eat flora, **scavengers** (`z`) eat corpses, **predators** (`Y`) hunt.
  Predators vs `monster`s is handled by the core turn loop automatically (both hostile).
- Each `on_player_act`, move/act critters by drive (guard partners): grazer → nearest
  flora, `flora.consume` when adjacent (breed when fed); scavenger → nearest corpse,
  `decay.consume`; predator → also hunt grazers (resolve intra-wild predation yourself via
  `game.attack` or hp). Critters that die go through `game.kill` (→ corpse). Keep counts
  small & bounded. They never target the player.
- Determinism via seeded rng. No overlay (critters are actors).

**weather** (`runtime/weather.py`, `WeatherSystem`, name `"weather"`) — ambient process.
- On `on_floor_enter`, choose a weather from the region `element` (`game.region_for`):
  charged→"static storm", wet→"rising damp", flammable→"ember drift", frozen→"cold snap",
  sacred→"hallowed calm", corrosive→"acrid haze", inert→"still air".
- Each `on_player_act` with a cadence (e.g. every few turns), nudge the substrate via the
  reactions write-API (guarded): static storm `r.add_prop(x,y,"charged")`/occasional
  `r.ignite` (a lightning strike); rising damp spreads `wet`; ember drift `r.ignite` a
  random floor tile; cold snap `clear_prop fire` + add `ice`. Indifferent; affects all.
- `current(game)` + `status_line` show the weather.

**structures** (`runtime/structures.py`, `StructureSystem`, name `"structures"`) — reactive objects.
- On `on_floor_enter`, place a few **pressure-plate traps** (armed, glyph `_`) and
  **crystal clusters** (glyph `&`) preferentially on `charged` tiles.
- Traps trigger on **any** actor standing on them (player, monster, or wild) — spikes
  (hp damage to that actor; use `game.kill` if it dies) or a gas burst (`r.add_prop` acid
  around). After firing, the plate is spent (revert to floor).
- Crystals **grow** over time on charged tiles and **detonate** when they catch fire or sit
  on a live charged/shock tile (query reactions): a detonation `r.ignite`/`add_prop charged`
  in a small radius and damages nearby actors. Indifferent to allegiance.
- Expose `hazard_tiles(game)` = armed-trap positions (so the auto-agent dodges them).

**decay** (`runtime/decay.py`, `DecaySystem`, name `"decay"`) — corpses & rot.
- `on_event("actor_died")`: drop a corpse at `data["pos"]` (glyph `%`) with a rot timer.
- Each `on_player_act`: corpses rot down; while rotting they seep `decay` — `r.add_prop`
  the tile (or a tiny miasma aura that lightly harms living actors standing on it). When the
  timer hits 0 the corpse is gone.
- Expose `corpse_at`, `consume` (scavengers). May emit `corpse_spawned`. Render `%`.

## Testing (`tests/test_<system>.py`, run `python3 -m tests.test_<system>`)

Register your system on a real `Game(load_manifest("examples/world.json"), systems=[...])`
(include partners or a stub for any you query) and assert autonomous behavior. Examples:
- flora: after several `on_player_act`s, plants spread; a plant on a `fire` tile (set via
  `reactions.ignite`) burns and ignites a neighbour; `consume` removes a plant.
- fauna: critters spawn as `wild`; a predator placed next to a `monster` damages it through
  the core loop (call `game.enemies_act()`); a grazer next to flora consumes it.
- weather: a region element yields a named weather and, after its cadence, a substrate
  change appears in `reactions.props`.
- structures: an actor stepped onto an armed trap takes damage / the plate spends; a crystal
  on a fire tile detonates and adds props nearby.
- decay: emitting `actor_died` drops a corpse (`corpse_at` True); after N turns it's gone;
  `consume` removes it.

Must print `OK` and exit 0. Deterministic across runs.

Report back: glyphs used, the command/query API you expose, events you emit/consume,
which reactions write-calls you make, and integrator notes (ordering, partner deps).
