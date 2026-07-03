# vaultcrawl

Generate a traditional roguelike world from a folder of markdown notes (an Obsidian
vault, or any `.md` directory). A personal knowledge graph *is* a world model — notes
are rooms, links are corridors, your most-linked obsession is the final boss.

The whole design rests on one separation:

- **Mechanical skeleton** — tiers, depths, power budgets, connectivity, what region a
  thing lives in. Authored by deterministic code. This is the "definite structure."
- **Semantic skin** — names, lore, flavor, faction identities. Authored by an LLM,
  grounded in your notes. **It can never move a number.**

Everything except the LLM step is deterministic: the same vault content always bakes
the same world. The LLM runs once, offline, at bake time, and its output is frozen into
the manifest — so the game runtime never needs a model.

---

## Quickstart (no dependencies, no API key)

```bash
cd vaultcrawl
python -m vaultcrawl.bake sample_vault -o examples/world.json
```

The default generator is a deterministic offline stub, so this runs on a stock Python
3.10+ with nothing installed. Output:

```
  The Philosophy Archives  (seed ccee0b8af9afe4f7)
  tone: luminous and overgrown
  from: 10 notes, 19 links, 2 clusters
  built: 2 regions, 2 bosses, 7 enemies, 5 items, 1 secrets, 5 quests
  final boss (floor 26): Roguelike Project, the Overgrown — Warden of the Forge

  factions:
    - House Philosophy  [neutral->faction_1]
    - House Project     [neutral->faction_0]

  regions:
    - The Patient Meridian  (observatory, floors 4-18)
    - The Fevered Engine-Yard  (foundry, floors 12-26)
```

Point it at your own vault: `python -m vaultcrawl.bake /path/to/vault -o world.json`.

---

## Architecture

```
ingest  -> analyze -> mapping -> generate -> validate -> bake
(parse)    (graph)    (slots)    (2-pass)    (invariants) (world.json)
\________________ deterministic ________________/  \LLM/  \__ deterministic __/
```

| File | Role |
|------|------|
| `vaultcrawl/ingest.py` | Parse markdown → `Note`s + a directed link graph. Hash the vault into a content seed. |
| `vaultcrawl/analyze.py` | Pure-Python graph metrics: PageRank, Louvain communities, bridges, orphans. |
| `vaultcrawl/mapping.py` | **Deterministic** metrics → mechanical slots (tiers, depths, biomes, power). |
| `vaultcrawl/prompts.py` | The two-pass prompt contract + output schemas. |
| `vaultcrawl/llm.py` | The LLM seam: offline deterministic stub + real-model drop-in (sketched). |
| `vaultcrawl/generate.py` | Runs pass 1 (bible) then pass 2 (per-slot content); assembles the manifest. |
| `vaultcrawl/validate.py` | Game-invariant checks + sparse-vault fallback. |
| `vaultcrawl/corpus.py` | Per-community word chains from the notes' own bodies (the Qud move). |
| `runtime/marginalia.py` | Weaves those chains into `"` marks read in each note's own room. |
| `vaultcrawl/bake.py` | CLI entrypoint wiring it all together. |
| `schema/world.schema.json` | Formal JSON Schema for the world manifest. |
| `sample_vault/` | 10 interlinked notes (2 clusters + a bridge + an orphan) to run out of the box. |
| `examples/world.json` | A baked world from `sample_vault`. |
| `runtime/` | Playable terminal roguelike that renders `world.json` (procedural floors, combat, permadeath). |
| `runtime/upheaval.py` | Overlays a chronicle onto a run so note edits become live in-game events. |
| `runtime/systems.py` | Hook interface for the pluggable systems layer. |
| `runtime/{sigils,reactions,knowledge,factions,history}.py` | The five Qud/Cogmind player-facing systems. |
| `runtime/{flora,fauna,weather,structures,decay}.py` | The autonomous ecology (player/faction-independent). |
| `SYSTEMS_SPEC.md`, `INTERACTIONS_SPEC.md`, `ECOLOGY_SPEC.md`, `tests/` | The authoring contracts + per-system unit tests. |
| `runtime/scenario.py` | Narrated showcase of the six cross-system interactions. |
| `runtime/ecology_scenario.py` | Narrated showcase of the seven autonomous-ecology set-pieces. |
| `runtime/sense.py` | Perception toolkit + `Brain` interface + the `brain_for` capability policy. |
| `runtime/{brains,tactics}.py` | The brain ladder (hunter → survivor → opportunist → tactician → exploiter). |
| `BRAINS_SPEC.md`, `runtime/brain_scenario.py` | The brain contract + the capability-ladder showcase. |
| `runtime/senses.py` | Perception layer: stimuli, sense profiles, two-layer detect/identify. |
| `runtime/creatures.py` | Sense-profile archetypes (echolocator, scent-hound, life-wraith, mind-seer). |
| `SENSES_SPEC.md`, `runtime/sense_scenario.py` | The senses contract + the perception showcase. |
| `runtime/memory.py` | Per-entity memory: beliefs (confidence decay), learned aversion, grudge. |
| `runtime/{planner,instincts}.py` | Deliberate planner (mastermind) + memory-reactive brains (tracker/wary). |
| `MIND_SPEC.md`, `runtime/mind_scenario.py` | The mind contract + the memory/planning showcase. |
| `runtime/components.py` | Materials (the bible's aesthetic) + `components_of` breakdown + `Inventory`. |
| `runtime/{salvage,forge}.py` | Salvage/inventory (drop · pickup · breakdown) + the forge (re-craft sigils). |
| `SALVAGE_SPEC.md`, `runtime/salvage_scenario.py` | The salvage contract + the matter/forge showcase. |
| `runtime/quests.py` | Your `- [ ]` TODOs become tracked dungeon objectives with rewards. |
| `runtime/dialogue.py` | Note-derived neutral NPCs you parley with (quest / offering / gossip). |
| `runtime/machines.py` | Hub-note Fabricators + bridge-note Terminals (forge · hack-to-reveal). |
| `DEEPEN_SPEC.md`, `runtime/deepen_scenario.py` | The social/objective/machine contract + showcase. |
| `runtime/quality.py` | Factorio-style quality grades: the rare cascading roll, creature scaling, the QualitySystem hub. |
| `runtime/abilities.py` | Invariant-safe creature special actions granted by quality (lunge/summon/blink/spit/…). |
| `QUALITY_SPEC.md`, `runtime/quality_scenario.py` | The quality contract + the grade showcase. |
| `vaultcrawl/evolve.py` | Diff two baked worlds into a chronicle of events. |
| `sample_vault_v2/`, `examples/world_v2.json`, `examples/evolution.md` | A later snapshot + its baked chronicle. |

---

## The vault is a graph, and a graph is a map

An Obsidian vault is already a knowledge graph: notes are nodes, `[[wikilinks]]` are
edges, tags are categories, folders are hierarchy, backlinks are centrality. Most of
the *structure* falls out of plain graph algorithms; the LLM is reserved for turning
structure into personal flavor.

| Vault feature | Game element | Where |
|---|---|---|
| Note | Room / enemy / item / lore | `mapping.py` |
| `[[wikilink]]` | Corridor / relationship / border | `analyze.py` |
| Backlink centrality (PageRank) | Importance → boss tier, **depth** | `mapping.py` |
| Tag (`#philosophy`) | Biome / enemy theme | `mapping.py` (`_TAG_BIOME_HINTS`) |
| Community (Louvain cluster) | A **faction** + a **region** | `analyze.py` → `mapping.py` |
| Cross-cluster link (bridge) | A faction **border** + its stance | `generate.py` (`_bible_inputs`) |
| Orphan note (degree 0) | A **secret** (hidden room / lost artifact) | `mapping.py` |
| Open checkbox `- [ ]` | A **quest** | `mapping.py` |
| Attachment `![[img]]` | **Loot** | `mapping.py` |
| Edit recency (mtime) | Region **activity** (spawn density) | `mapping.py` |

The poetic anchor for a *traditional* descent: **depth = centrality**. You start at the
periphery of your knowledge and descend toward your most-linked notes. The deepest boss
is your single most-connected note — in the sample, that's `Roguelike Project`.

---

## The two-pass contract (consistency)

The trick that keeps a generated world reading as *one place* rather than theme soup:

**Pass 1 — world bible (one call).** Sees only a graph *summary* (clusters, their tags,
borders) and authors the global identity: world name, tone, a shared aesthetic
vocabulary, and the factions + their relations. Small, global, cached.

**Pass 2 — local content (one call per slot).** Each enemy/region/item is generated
*conditioned on the bible* + its source note. It inherits the world's voice and can only
fill `name`/`flavor` into a slot whose mechanical fields are already fixed.

Both passes use **schema-bound output** (`prompts.py`) — the model fills slots, it can't
invent structure or set a tier. See `prompts.BIBLE_SCHEMA` and `prompts.CONTENT_SCHEMAS`.

---

## Determinism & the LLM seam

- The seed is a hash of note ids + bodies + resolved links (not mtimes, not paths), so
  copying your vault to another machine bakes the **identical** world.
- The offline stub (`llm.OfflineStubLLM`) is seeded per-slot, so even the "creative"
  layer is reproducible. Regenerating `sample_vault` is byte-identical across runs.
- To get real prose, implement the one-method `LLM` interface. `llm.py` includes a
  ready-to-uncomment `AnthropicLLM` that forces structured output via a single tool
  call. Nothing else in the pipeline changes — the world is still baked, the runtime
  still pure.

```python
from vaultcrawl.bake import bake
from vaultcrawl.llm import AnthropicLLM        # after uncommenting + pip install anthropic
bake("my_vault", "world.json", llm=AnthropicLLM(model="claude-opus-4-8"))
```

---

## Invariants the validator enforces (`validate.py`)

So a generated world is always *playable*:

- Every cross-reference resolves (enemy→region, region→faction, relations→faction).
- Enums valid; `tier ∈ 1..5`; `depth ≥ 1`; `powerBudget` within its rarity band.
- **Boss depth is monotonic with tier** — a deeper boss is never weaker.
- At least one boss exists (the world has an objective).
- Sparse/empty vaults are padded with a default playable world (`padded: true`).

Region-graph connectivity is a *warning*, not a failure: hard reachability is the
runtime layout generator's job (BSP / Delaunay+MST), which always guarantees a path.

---

## Play it: the included reference runtime

`world.json` is engine-agnostic — a **content palette**, not a map. The bundled runtime
(`runtime/`, pure stdlib) proves it: it generates a fresh, guaranteed-connected dungeon
each floor (rooms + an MST of corridors), then draws *which* enemies/items/boss appear,
and at what depth, from the manifest.

```bash
python -m runtime.play examples/world.json --auto --floors 5   # headless demo (classic descent)
python -m runtime.play examples/world.json                     # interactive (needs a TTY)
python -m runtime.play examples/world.json --descent           # interactive classic floors
python -m runtime.play examples/world.json --debug             # + backtick debug menu
```

**The interactive UI** is colored and composed: the map sits in a framed viewport whose
title names the exact place you stand in ("The Hall of 'Rust' · The Fevered
Engine-Yard"), colored by the region's element. Text-heavy interactions open **Qud-style
popup windows** instead of the narrow message strip: `x` (examine) opens a bordered,
word-wrapped, scrollable "You look around" window; parley opens a running conversation
modal where the creature's lines and your moves accumulate in one scrollable transcript;
and `m` opens the full **message log** scrollback, so nothing is ever lost off the bottom.

**Atmospheres — environments as blended design blocks** (`runtime/arch/blocks.py`): a
place's vibe is not a fixed theme but an ORDERED BLEND of small design blocks (element +
biome + note-role), and the order sets dominance — `foundry-charged` reads as dead
machinery, `archive-charged` as a shelf-lined hall, from the same `charged` block. Each
block carries four agreeing channels: its own feature-objects (17 kinds now, up from 3 —
pipes, shelves, fallen tomes, reeds, standing stones, spark-nodes, niches…), a spatial
tendency (dense/open/broken/linear/scattered), a palette-lean (rust, holy, cold, verdant,
pale, harsh), and an ambient voice. So crossing into a different region shifts the
objects, the layout density, the screen's hue, AND what the place murmurs. 20 blocks
permute into thousands of distinct environments; `x` reads the vibe, and a place speaks
its atmosphere on its own as you move (roughly 1 line per 11 steps — silence is kept).

**Effects — Yume Nikki, ported to a vault** (`runtime/effects.py`): not weapons but WAYS
OF BEING. Out in the wild you find solitary landmarks (your unlinked notes); commune with
one (`t`) and take its *effect* into yourself — **lantern** (see far in the dark),
**drift** (cross hazard unharmed), **hush** (wild things lose their fear), **eyeless**
(dream the whole place, no fog), **small** (unseen, nothing menaces you), **echo** (notes
murmur themselves as you pass). Wear one at a time (`e`), switch freely, lose nothing.
Effects change how you *explore and perceive*, never how hard you hit — exploration as the
verb, a lucid dream of your own notes. Glyphs are colored by meaning (hazards
by element, hostiles red, the boss magenta, lore and marginalia gold, growth green,
machinery blue), and **each place wears its own region's palette**: a district's floors
and interior structure are washed in its element's color (corrosive green, charged
yellow, wet blue, frozen cyan, sacred magenta, flammable red) while the ways between
places stay neutral gray — the map literally reads as a field of colored centers.
Tiles beyond your sight radius render dimmed — remembered, not seen.
And the architecture is FELT, not just generated (four of Alexander's properties made
perceptual): **Gradients** — floor light rises toward each district's heart, so walking
inward is visible; **Strong Centers** — hearts (`◆`) and town doors (`>`) render
through the fog as landmarks you navigate by; **Boundaries** — walls parting two
regions are colored by their houses' stance (war burns red, accord glows green);
**ways vs places** — on the open ways between districts you stride two paces a turn,
dropping to careful single steps inside a place, so the journey/arrival rhythm lives
in your fingers. Roughness accents (`·`) keep no floor dead-flat. A sidebar carries the world's name, an HP bar, and one line per live system in
place of the old single mega-line; the message log is colored by what happened (combat
red, victories green, places bold, texts gold). Degrades cleanly to monochrome on
colorless terminals; the viewport sizes itself to yours.

**The world is a SEMILATTICE of realms** (ARCHITECTURE_SPEC §13): the grown overworld
plus one depths-realm per region, joined by gates. Each district's heart is a **town**
— settled ground where nothing hostile may enter, its Keeper lives, waiting is rest —
holding the door (`>`) down into the region's **depths**, where its warden dwells (no
boss stands in the open anymore). Below, **passages** (`>`) join the depths of
bordering regions (bridge notes made spatial) and stairs (`<`) climb home, so the
map-graph has loops no tree contains: down one door, across beneath the border, up
another. **Realms persist**: what you kill stays dead, what you search stays searched.

**The interactive game is a sandbox.** Instead of floors, the whole vault is grown into ONE
structure by the pattern-architecture compiler (`runtime/arch/`, per `ARCHITECTURE_SPEC.md`):
organic districts, semilattice ways (loops and shared courts, never an MST), each center
literally being one of your notes. The surface is rasterized **figure-ground**
(`runtime/arch/settle.py`), not cave-carved: buildings stand in OPEN LAND — each note's
footprint a walled enclosure whose doors face its linked neighbours (the graph decides
the doors) — and the seams are visible roads (`░`) crossing the fields, where you
stride two paces a turn. Region color-fields spread over the ground so districts read
as lands. The depths keep the classic dark cave carve on purpose: settled landscape
above, dungeon below — the intimacy gradient as a paradigm contrast you feel. The world **sprawls**: after growth, districts are
pushed radially apart by the `--sprawl` factor (default 2.0; 1.0 = compact, 3.0 = a
~900x900 continent for a 120-note vault) — places stay coherent inside while the land
between them stretches, so crossing between communities is a journey and bridges are
real roads. The site cache keys on sprawl, so changing it regrows once. Creatures are **territorial**: each dwells at its
note's center and stirs only if you stand on its ground, press in close, or provoke it;
drawn too far from home it gives up and drifts back. Each place is an encounter you
choose. Power is gentle at the periphery and rises quadratically toward the heart.
Inside each center, room-scale interior patterns
(`runtime/arch/interiors.py`) theme the place from the note's own dynamics — never at
random: a hub raises a colonnade, an orphan hides a sanctum behind one threshold, a
bridge grows quiet alcoves, a shared note sets meeting stones, a recently-tended thought
is carpeted in growth (`,`), a long-untouched one crumbles to rubble and dust (`'`).
Entering a place names its motif, so the theming is felt, not just drawn. You start at the periphery; your most-linked thought holds
the greatest center. Depth = centrality becomes *spatial*: there is no down, you walk inward,
power rising toward the heart, and resolve the run there (communion or blade). A scrolling
viewport follows you. The classic depth-descent survives as `--descent` and as the `--auto`
demo's mode.

Glyphs: `@` you · `>` stairs down · `M` boss · lowercase = enemies (by archetype) ·
`) [ = * !` = loot. The per-floor loop:

1. Pick the region whose `depthBand` contains floor *N* (nearest region if there's a gap).
2. Generate a layout seeded by `(vault seed, N)` — always solvable (MST connectivity).
3. Spawn that region's enemies (count scales with `activity`; **power is capped by depth**
   so early floors stay gentle), drop loot, and place any boss whose `depth == N`.
4. Bump-to-attack combat, permadeath. The run resolves at your single most-linked
   note, the deepest thought in the vault — and violence is the fallback, not the
   point. Standing before it, `t` attempts **communion**: speak enough of the vault's
   read truths (marginalia + lore), or lay down an offering of salvaged matter, and
   you integrate it and surface changed. Or draw your blade; the old way still works.
   Lesser hostiles can be approached without violence too: `t` opens a **negotiation**
   (SMT-style, but note-embodied): the creature converses in lines woven from its OWN
   note's corpus, and its temperament follows its graph role — a hub is proud, a bridge
   curious, a leaf timid, an orphan lonely. Respond with praise / ask / truth / gift;
   reactions are fickle (a seeded "strange humor" can invert one). Sway it and it stands
   down into the wild AND teaches you its note (conversation as intel, no faction alarm);
   enrage it and it never talks again. `game.becalm` remains the direct engine path
   (understanding disarms free; else matter). `z` **tosses** a scrap of matter whose clatter draws
   hearing creatures away (the senses layer, played actively). And quiet movement plus
   broken line-of-sight has always been sneaking.
   **Relations are factional, not special-cased** (Qud-style): every creature belongs
   to a house (its region's faction), kin never fight, rival houses war on sight (the
   evolve layer can ignite rivalries between snapshots), wildlife is hostile to every
   house and neutral to you, and **reputation is real**: raise a house's standing to
   +4 (offerings, becalmed kin, quests) and its creatures stop fighting you entirely.
   And because the controlled actor is not a special kind of thing, you can play AS
   any entity: `--embody <name-or-note>` hands you its body, stats, house, and
   relations — wake as a shade of House Philosophy and its kin part around you while
   its rivals and the wild hunt you.
   **The CDDA layer — places are distinct opportunities**: a note-room may hold a
   **cache** (`□`) of that place's OWN matter, named from the note's tags ('rust'
   ground yields lang-matter, Stoicism's chamber mind-matter). Old thoughts yield
   seasoned quality-2 matter (ruins are worth the trip); caches in charged, flammable,
   or corrosive ground may be **warded** — telegraphed as [humming] on examine, and a
   sprung ward bites and RINGS, calling the place's dwellers. Place matter carries
   **crafting geography**: each material steers a perk by its note's role (hub matter
   steers keen, orphan matter echo_twin...), so wanting a specific perk gives you a
   destination. Contents, uses, perils — legible before you commit.
   **The Cogmind circle**: creatures embody parts, and their fall makes those parts
   yours — a capable creature (any elite with special actions) drops a **part node**
   (`$`) carrying its own verb when it dies, by any hand: slot a fallen shade's Blink
   and blink; it is lossy like every sigil. And capacity **evolves**: each region you
   truly map widens your grasp by one sigil slot (3 base, cap 6) — understanding is
   carrying capacity.
   **The Qud layer** deepens all of it: your **body is your build** — the controlled
   body's special actions (blink, spit, enrage, shield, rally, summon, split) are
   castable from the `c` menu alongside sigils, so an embodied elite plays like one;
   a swayed creature may **walk with you** as a companion (it mirrors your enemies,
   its kin stay its kin, your summons and splits side with you); a **Legendary** spawn
   is a person — named in words woven from its own note, easier to sway, immune to
   grudges, and its fall leaves a named relic of legendary matter; and friendly
   creatures **trade secrets** — `t` spends a read truth and they open their source
   note to you (+1 standing with their house, once each).
   **No path is ever truly blocked**: the carver guarantees static connectivity
   (flood-fill repair after every pattern operator), and bumping any friendly —
   Keeper, wildlife, a becalmed creature — swaps places with it, so a body in a
   one-wide way is never a wall. All interaction is by explicit command (`t`).
   The `--auto` agent loots, fights, and descends on its own.

**Rooms are places.** Each room on a floor carries the identity of a note from the
region's community (the anchor note always claims the deepest room), named by its graph
role: a hub is a Hall, a bridge a Gallery, an orphan a Sealed Alcove. Contents are
contextual to place, CDDA-style: an enemy, sigil, machine, or Keeper spawns inside the
room of its own source note when that room exists on the floor. Entering a room
announces it; `x` (examine) names where you stand and what is nearby.

## Evolve it: your world grows as your notes do

Because the world derives from the vault, re-baking after you edit your notes *changes*
the world — and `vaultcrawl/evolve.py` turns that change into a chronicle of events,
matched by **note anchor** (stable across rebakes).

```bash
python -m vaultcrawl.evolve examples/world.json examples/world_v2.json --md chronicle.md
```

From the bundled snapshots (a music cluster added, the orphan deleted, two notes
backlinked):

```
👑 A new realm forms around 'Music Theory' — The Order of Music claims it.
✦ 'Guitar' enters the world.
† 'Grocery List' is gone; what it seeded crumbles to ruin.
▲ 'Memento Mori' gains influence (tier 2→3).
↧ The warden 'Stoicism' sinks deeper (floor 18→21).
⚔ 'Roguelike Project' and 'Stoicism' shift from neutral to rival.
```

## Close the loop: the chronicle becomes live upheaval

Editing your notes doesn't just rebuild the world — it changes what you *encounter*.
`--evolve-from OLD` plays the new world with the OLD→new chronicle overlaid as in-game
events (`runtime/upheaval.py`):

```bash
python -m runtime.play examples/world_v2.json --evolve-from examples/world.json --auto --floors 22
```

```
~ The world has shifted since you last descended: 10 upheaval(s). ~
✦ New territory — The Annotated Lens-Hall has risen into the world.
† The ruins of 'Grocery List' stir here.
You destroy Ascendant Veiled Echo.
⚔ The Recursive Assembly is contested ground; its borders bleed.
```

| Chronicle event | What you meet mid-descent |
|---|---|
| `kingdom_rises` | the region is **new territory** — announced, with a frontier loot drop |
| `idea_ascends` | that note's enemy spawns **Ascendant** — an empowered mini-boss spike |
| `power_wanes` | that note's enemy spawns **Fading** — diminished |
| `note_lost` | the deleted note **haunts the floors** as a roaming ruin-echo |
| `throne_taken` | the new deepest boss is marked **Ascendant** |
| `border_shifts` | the region becomes **contested ground** |

> Surfacing every region required a runtime fix: a region's depth band (min..max member
> depth) can span the *whole* descent, so "first band containing the floor" let one
> region monopolize every floor. The runtime instead carves **contiguous zones** — each
> region owns the floors up to its boss's depth — guaranteeing every region (risen ones
> included) is reachable and each boss sits inside its own zone.

---

## Systems layer — power is configuration, not numbers

Inspired by Caves of Qud and Cogmind: instead of bigger numbers, five composable systems
change your *relationship to the world*. The player **never gains stats during a run** —
progression is which sigils you've slotted, how you use the terrain, and what you know.
Every system is generated from the vault graph. Built in parallel as self-contained
modules against `SYSTEMS_SPEC.md`, wired through one ordered hook list.

| System (`runtime/…`) | Inspiration | What it does | Vault source |
|---|---|---|---|
| **Sigils** `sigils.py` | Cogmind parts | 3 slots; abilities (Recall / Phase / Rally / Ward / Echo), never flat damage; **lossy** — they shatter | a note's graph **role** (hub/bridge/cluster/leaf/orphan) |
| **Reactions** `reactions.py` | Qud chemistry | tiles react — chain-shock, fire spread, acid, sacred heal; fight the *environment* | a region's **element** from its tags |
| **Knowledge** `knowledge.py` | Cogmind intel | fog of war *is* the link graph; knowing a note reveals its neighbors | graph **neighbors** |
| **Factions** `factions.py` | Cogmind alert / Qud rep | kills raise a faction's *disturbance* (→ hunters) and shift *standing* (its rivals favor you) | **community** + the relation graph |
| **History** `history.py` | Qud sultan-history | a mythic history from note age / bridges / orphans; readable lore fragments grant map knowledge | node **activity** (age), bridges, orphans |

```bash
python -m runtime.play examples/world.json --auto --floors 8     # systems on (default)
python -m runtime.play examples/world.json --no-systems --auto    # bare descent
```

One live floor's HUD shows all five at once:

```
Sigils: Phase(2) Ward(2) Rally(1) [3/3]  ·  Ground: corrosive  ·  House Philosophy: -4 favor  ·  Lore: 2 read  ·  Mapped: 6/10 ideas
```

Design rules that keep it honest:

- **No power creep.** With systems on, the vanilla stat-loot economy is *off* — sigils
  (utility verbs, lossy) replace it. The player holds a fixed baseline (ATK 4 / 32 HP) all
  run; the only sustain is a flat rest-on-descend, never a stat gain.
- **Every addition is a verb or knowledge, never a coefficient** — and it's lossy (sigils
  shatter, the world reacts, knowledge can be stale).
- **Self-contained + hook-based.** Each system subclasses `System` and touches game state
  only through documented hooks (`on_floor_enter`, `on_player_act`, `on_enemy_killed`,
  `render_overlay`, …). Order matters: sigils first (an Echo can revive a just-killed
  player), knowledge last (its fog paints over every other overlay).
- Systems compose with the **evolution** layer: play the new world with `--evolve-from`
  and a risen kingdom both announces itself *and* fields its own faction's hunters.
- The `--auto` agent is a dumb smoke test (it grabs sigils, reads lore, flees when hurt,
  dodges hazards) — it dies shallow on purpose; a human plays the systems to go deep.

---

## Interactions — where the systems compose

The five systems share a tiny event bus (`game.emit` / `System.on_event`) and a query
API (`game.system("reactions").is_hazard(x, y)`, …), so the *output* of one becomes the
*input* of another. The emergence (Qud/Cogmind):

| Interaction | Systems | What happens |
|---|---|---|
| **Quiet vs loud kills** | reactions × factions | a melee kill is *heard* (faction alert +1); luring a foe onto a hazard kills it *unseen* — alert doesn't rise, it even cools. Stealth is real. |
| **Ward shove-to-kill** | sigils × reactions | Ward doesn't just push foes away — it shoves one onto acid/fire so the terrain makes the kill |
| **EM corruption** | sigils × reactions | standing in a charged field frays a slotted sigil (it shatters sooner) |
| **Lore reveals the map** | history × knowledge | reading a fragment that names a boss/secret reveals that region on your map |
| **Hunter intel** | factions × knowledge | killing a dispatched hunter scavenges its sensors → a region *ahead* is pre-mapped |
| **Elemental affinity** | reactions | an enemy is immune to its own region's element and takes **2×** from the opposite |

See them all in one deterministic run — six staged set-pieces, each verified from live state:

```bash
python -m runtime.scenario
```

```
SET-PIECE 1: Loud vs quiet kill    ✓ melee raised alert 0->1; environment did not (decayed)
SET-PIECE 2: Ward shove-to-kill    ✓ Ward shoved the foe onto acid; reactions owns the kill
SET-PIECE 3: EM corruption         ✓ charged tile drained 1 durability
SET-PIECE 4: Lore reveals the map  ✓ reading lore flipped is_known False->True
SET-PIECE 5: Hunter intel          ✓ loud hunter kill scavenged sensors; a region revealed
SET-PIECE 6: Elemental affinity    ✓ own element 0x, opposite 2x
OVERALL: PASS — all six cross-system interactions verified.
```

How it stays clean: **systems never import each other.** They talk only through
`game.emit(event)` (canonical events: `enemy_killed{cause}`, `lore_read{region_id}`) and
`game.system(name)` queries — every cross-call is None-guarded, so any system degrades
gracefully when a partner is absent (`--no-systems`, or any subset). The contract lives in
`INTERACTIONS_SPEC.md`; the five were deepened **in parallel**, each owning exactly one file,
composing only through the bus.

Honest limit: the sample vault has just two regions and their elements aren't opposites, so
the affinity 0×/2× split is shown across two tiles rather than one; a richer vault makes it
a single-tile play.

---

## A living world — autonomous ecology

The systems above serve the player. These five run the world *regardless of you or the
factions* — they react to the elements, to time, and to each other. You exploit them or
get caught in them.

| System (`runtime/…`) | What it is | Reacts to |
|---|---|---|
| **Flora** `flora.py` | vegetation seeded by your most-used tag; spreads, blooms, burns | fire (runs through it), wet (spreads), acid (dies), sacred (heals) |
| **Fauna** `fauna.py` | `wild` critters — grazers, scavengers, predators — that ignore you | flora (graze), corpses (scavenge), monsters (predators hunt them) |
| **Weather** `weather.py` | a region-element ambient process: static storm, rising damp, ember drift, cold snap, acrid haze | reshapes the substrate each turn |
| **Structures** `structures.py` | pressure-plate traps + charged crystals | any actor (traps), fire/shock (crystals detonate) |
| **Decay** `decay.py` | every death drops a corpse that rots and seeps miasma | `actor_died` (any death), scavengers (eaten) |

The keystone is **allegiance.** Every actor is `player`, `monster`, or `wild`; the turn
loop makes wild and monster mutual enemies but leaves the player alone — so wildlife
fights your enemies on its own, and a trap kills whatever steps on it. Death is universal
(`game.kill` → `actor_died`), so anything that dies feeds the decay/scavenger loop.

See the autonomous web in one deterministic run:

```bash
python -m runtime.ecology_scenario
```

```
SET-PIECE 1: Predation thins the faction   ✓ the wild felled the monster; the factions heard nothing
SET-PIECE 2: Fire runs through vegetation   ✓ flame walked the whole row of plants
SET-PIECE 3: Crystal detonation             ✓ fire reached the crystal; it burst (fire+charge) and hit a bystander
SET-PIECE 4: The dungeon is impartial       ✓ the trap killed a monster, not caring whose foot it was
SET-PIECE 5: Death feeds the ecology        ✓ the kill became a corpse; a scavenger ate it
SET-PIECE 6: Grazer eats the weed           ✓ a grazer consumed a plant
SET-PIECE 7: Weather reshapes the world     ✓ a static storm sowed charge + a lightning fire
OVERALL: PASS — all seven autonomous-ecology set-pieces verified.
```

Now the cross-layer emergence multiplies, none of it about you: weather sows charge → a
crystal detonates → the blast ignites flora → fire walks into a monster (a quiet,
unattributed kill) → its corpse draws a scavenger → a predator hunting that scavenger
strays into your faction enemies. A live floor's HUD reflects it all at once:

```
Sigils: Phase(2) [1/3] · Ground: corrosive · Weather: acrid haze · Flora: 5 · Traps: 2 · Crystals: 3 · Corpses: 1 · Wild: 4 · House Philosophy: -2 favor · Lore: 1 read · Mapped: 6/10 ideas
```

---

## Agents — a capability ladder (not just pathfinders)

Every actor decides through a **brain** (`Brain.decide(game, actor) -> step`), assigned by
capability tier — so the same world holds blind grunts and cunning schemers, and the player
auto-agent is just another brain. Intelligence is how well a brain reads the world
(`sense.py`'s affordances: hazards, lures, loot, safe paths) and turns it into a step.

| Tier | Who gets it | Behaviour |
|---|---|---|
| **hunter** | tier-1 monsters | the legacy chaser — beelines and bumps, walks straight into acid |
| **survivor** | tier-2 monsters | chases but routes *around* hazards; flees when hurt |
| **opportunist** | tier-3 monsters, predators | survivor + attacks the foe the terrain is already killing |
| **tactician** | tier-4+/bosses/hunters | **kites you onto hazards** — lands the kill without a blow |
| **forager / scavenger** | grazers / scavengers | skittish prey — flee threats, leave foraging to the fauna system |
| **exploiter** | the player | lure foes onto terrain, grab loot, fight on hazards, flee to the stairs |

`brain_for(actor)` maps entity → tier; the engine assigns lazily. The ladder, proven on
live state:

```bash
python -m runtime.brain_scenario
```

```
SET-PIECE 1: Dumb dies, survivor lives       ✓ the hunter walked into acid and died; the survivor routed around, unscathed
SET-PIECE 2: Opportunist lets terrain finish  ✓ it hit the acid-stander and never touched the safe foe
SET-PIECE 3: Tactician's no-touch kill        ✓ the chaser dissolved on acid (cause=environment); the tactician landed 0 blows
SET-PIECE 4: Exploiter clears via terrain      ✓ the exploiter took less damage and scored the environmental kill
SET-PIECE 5: Right brain per entity            ✓ tier1→hunter, tier5/boss→tactician, grazer→forager, player→exploiter
```

Pick the player's brain live to watch the difference:

```bash
python -m runtime.play examples/world.json --auto --brain dumb        # legacy pathfinder
python -m runtime.play examples/world.json --auto --brain exploiter   # interaction-aware (default)
```

The world got smarter too: tier-4+ monsters and faction hunters now lure *you* onto the
acid, the traps, and the crystals you meant to use on them — so a dumb descent dies faster
than an exploiter that turns the same terrain against them.

---

## Senses — perception, not omniscience (CDDA-style)

Brains used to be omniscient: every creature always knew where you were. The senses layer
(`senses.py`, the perception model — distinct from `sense.py`, the brains' movement toolkit)
fixes that. Each creature perceives only what its **sense profile** allows, in two layers:

- **Detection / exploration.** Locating senses — **sound**, **smell** — give a *position*,
  not an identity. A creature that merely hears you walks toward the noise to investigate.
- **Identification / reaction.** Identifying senses — **sight** (line-of-sight), **touch**
  (adjacent), or the supernatural **life / mind / magic** — confirm *what* a thing is. Only
  an identified *hostile actor* becomes a target; fire is perceived as a hazard and avoided,
  never attacked, because it is never an actor.

Creatures sense by capacity (`creatures.py`):

| Profile | Creature | Senses |
|---|---|---|
| sighted | most monsters | sight + hearing + a little smell |
| echolocator | echoes (`e`) | blind — hears far, identifies only by touch |
| scent-hound | beasts (`b`), wildlife | follows smell, weak eyes |
| life-wraith | shades (`h`) | senses the living through walls; blind to machines |
| mind-seer | scribes (`s`) | feels thought at range; blind to the mindless |

So a monster that loses line-of-sight investigates your last position and the noise you make
instead of bee-lining through walls; a blind echo hunts you by sound and only "sees" you when
adjacent; a wraith feels you through stone but can't sense a golem; and *everyone* treats fire
as terrain, not a foe.

```bash
python -m runtime.sense_scenario
```

```
SET-PIECE 1: Lose & investigate     ✓ lost line-of-sight → heads to the last-seen spot, not through the wall
SET-PIECE 2: Blind by sound          ✓ the echo hears the noise, closes in, identifies by touch, strikes
SET-PIECE 3: Don't attack the fire   ✓ fire is a hazard, never a target — it routes around
SET-PIECE 4: Through walls            ✓ the life-wraith senses the living player through stone; blind to the golem
SET-PIECE 5: Selective mind-sense     ✓ the mind-seer feels the player, not the mindless grazer
SET-PIECE 6: Capacity comparison      ✓ same scene, three senses, three different reactions
```

Perception is **opt-in** via the `senses` system: every test/showcase without it stays
omniscient (and unchanged); the live game switches it on — so monsters can be snuck past,
distracted with noise, or shaken by breaking line-of-sight.

---

## Mind — memory & deliberate planning

The capability ladder now tops out in creatures that **remember** and **scheme**.

**Per-entity memory** (`memory.py` + the `MemorySystem`) — each creature acts on beliefs,
not just the current instant:
- it remembers where it last saw you (confidence fades over ~18 turns), so a foe that loses
  sight heads to your last-known spot and *searches*, then gives up;
- it **learns aversion** — an element that has burned it enough becomes *feared*, and it
  routes around that hazard even when desperate;
- it holds a **grudge** — taking damage raises alertness (which decays), making it hunt
  harder and longer.
Memory is *inferred*, not bolted on: the `MemorySystem` derives beliefs from perception and
harm from HP-deltas-near-hazards each turn — no edits to combat or reactions, and it's
opt-in (off ⇒ memory-aware brains degrade to reactive).

**Deliberate agents** (`planner.py`) — the top tier (`mastermind`, bosses/elites) doesn't
react one step at a time; it forms a multi-step **plan** toward a goal, executes it over
several turns, and **replans** when it breaks. Its signature play is a *lure-combo*: walk to
a bait tile, then kite you across a hazard so the terrain lands the kill. Faction hunters get
`tracker` (memory search); tier-3 foes get `wary` (learned aversion).

```bash
python -m runtime.mind_scenario
```

```
SET-PIECE 1: Search & give up     ✓ heads to last-known, searches, gives up once the belief fades
SET-PIECE 2: Learned aversion      ✓ burned by acid twice → refuses to path through acid
SET-PIECE 3: Grudge                ✓ alert rises on a hit, then decays over the next turns
SET-PIECE 4: Deliberate combo      ✓ builds a 2-step plan and lures a foe onto a hazard
SET-PIECE 5: Replanning            ✓ clear the hazard mid-plan → the plan changes (lure → engage)
SET-PIECE 6: Memory is per-entity  ✓ one creature fears acid & remembers you; another neither
```

`brain_for` now routes the whole ladder: tier-1 **hunter** · tier-2 **survivor** · tier-3
**wary** · faction hunter **tracker** · tier-4+/boss **mastermind** · wildlife
**forager/scavenger/opportunist** · player **exploiter** (perception-limited throughout).

---

## Inventory — salvage the world's matter, then re-forge

There's now a real inventory, and **everything breaks into components** — but the components
are the world's *own* materials: the words in your bible's `aesthetic` vocabulary ("brass",
"ink", "moss", "vellum"). `components_of(thing)` (`components.py`) turns any fallen creature,
shattered sigil, detonated crystal, or item into a handful of that matter, scaled by potency.

- **Salvage** (`salvage.py`): when something dies or breaks it drops `*` salvage; walk over it
  to pour the matter into your `Inventory` (carried across floors; ground salvage is per-floor).
  You can also **break down** a slotted sigil for parts.
- **Forge** (`forge.py`): spend matter to **re-craft** a sigil into a free slot.

This turns the lossy sigils into a real economy: a sigil **shatters** (Cogmind part-loss) →
its shards are **salvaged** → the **forge** spends the matter to rebuild — all in the world's
own materials.

```bash
python -m runtime.salvage_scenario
```

```
SET-PIECE 1: Everything breaks      ✓ creature/sigil/crystal/item → only the world's materials (brass, moss, vellum)
SET-PIECE 2: Death → salvage → bag   ✓ a kill drops salvage; collecting grows the inventory
SET-PIECE 3: Shatter → salvage       ✓ a shattered sigil leaves its matter on the floor
SET-PIECE 4: Breakdown               ✓ melt a slotted sigil back into matter, freeing the slot
SET-PIECE 5: Forge closes the loop   ✓ shatter → salvage → forge re-crafts a sigil (slots +1, matter −cost)
SET-PIECE 6: Inventory persists       ✓ carried matter survives the descent; ground salvage is per-floor
```

The HUD gains a `Matter: N (brassx3 …)` readout, and the exploiter auto-agent detours to grab
`*` salvage (it's exposed as a point-of-interest). Power stays *configuration, not creep*: the
forge only ever re-crafts the five utility verbs, never bigger numbers.

---

## Inhabited & purposeful — quests, NPCs, machines

The dungeon now has objectives, residents, and usable machinery — all from the vault.

- **Quests** (`quests.py`): your unfinished `- [ ]` TODOs (baked into the manifest as
  `quests`) become real objectives — slay the idea at a region's heart, recover matter, reach
  a region, cleanse a floor — each completing on the right event and paying out matter,
  reputation, or map intel. Your actual backlog becomes the dungeon's quest log.
- **NPCs & parley** (`dialogue.py`): note-derived neutral Keepers (`P`) you *talk* to, not
  fight (bumping a neutral emits `interact`). They entrust you with quests, accept an
  **offering** of salvaged matter (→ faction standing + a glimpse of the road ahead — a
  vault-native trade, *not* Qud's water-ritual), or gossip a boss's location.
- **Machines** (`machines.py`): hub-notes manifest as **Fabricators** (`F`) — step on one to
  forge a sigil from your matter — and bridge-notes as **Terminals** (`T`) — hack one to
  reveal a region ahead. The map's own graph structure becomes interactive Cogmind machinery.

```bash
python -m runtime.deepen_scenario
```

```
SET-PIECE 1: Quest from a note   ✓ a transformed TODO completes on its trigger and pays a reward
SET-PIECE 2: NPC parley           ✓ bump a Keeper → it entrusts a quest, or accepts a matter offering (standing + intel)
SET-PIECE 3: Fabricator           ✓ step on F with matter → forge a sigil (slot +1, matter −cost)
SET-PIECE 4: Terminal             ✓ step on T → a region ahead becomes known
SET-PIECE 5: NPCs are neutral     ✓ monsters ignore the Keeper; bumping it parleys, never attacks
```

---

## Quality grades — every creature and every sigil, rolled

A Factorio-Space-Age axis runs through everything: **Normal · Uncommon · Rare · Epic ·
Legendary**. Every creature and equippable *rolls* a tier on creation — upgrades are rare and
**cascade** (a success can bump again at decaying odds), so most things are Normal and a
Legendary is a genuine event. It is not unique items at fixed rarities; any instance can be any tier.

- **Creatures** (`quality.py` + `abilities.py`): each tier adds stats *and* one **special
  action** — an elite Rare foe hits harder and can `lunge`, `summon`, `blink`, `spit`,
  `shield`, `rally`, or `split` (all invariant-safe). A "Legendary Warden" is a boss-grade
  threat wherever it happens to roll.
- **Equippables (sigils)**: each tier grants one random **perk** — a stat (more durability,
  bigger effect via `mag`) or a passive (Ward shoves 2 tiles, Phase leaves a decoy, Recall
  also cures fear, thrifty uses, Echo revives at 2 hp).
- **Crafting** (forge / fabricator): output quality is rolled with the floor pinned to the
  **lowest-quality ingredient** (never worse than your inputs) and the odds raised by better
  matter + **additives** — extra materials you toss in that *steer* which perk you get (some
  materials favour a specific effect over a random one). Salvage from an elite banks
  higher-quality matter, so killing tough foes feeds better crafts.

```bash
python -m runtime.quality_scenario
```

```
SET-PIECE 1: Rarity is rare          ✓ ~91% Normal, a sliver Legendary; bias cascades the mass upward
SET-PIECE 2: Quality creature        ✓ a Rare elite out-stats its Normal twin and wields a special action
SET-PIECE 3: Quality equippable      ✓ an Epic sigil carries 3 perks; a stat perk changed a value
SET-PIECE 4: Crafting floor + cascade ✓ Rare matter → output ≥ Rare, cascading to Epic
SET-PIECE 5: Additive steering       ✓ an additive's affinity forces its perk (vs a random one)
SET-PIECE 6: Salvage carries quality  ✓ an elite's matter raises the next forge's floor
```

The HUD gains an `Elites: N` readout; graded foes wear their tier in their name ("Rare
Warden"). Quality is the one sanctioned power-*variance* axis — rare, tiered, earned — as
opposed to the flat "no creep" baseline everywhere else.

---

## Privacy & honest limits

- **Transformation, not transcription.** The prompts instruct the model to metaphorize —
  your tax note becomes ledger-golems, never a room labeled "Taxes." Tune `CONTENT_SYSTEM`.
- **PII.** Real vaults hold real names and private journals. The `#nogame` / `#private`
  opt-out tag (inline or frontmatter, nesting like `#private/journal` counts) is
  ENFORCED in `ingest.py`: a marked note contributes nothing — no graph node, no corpus
  words, no seed — and even its title is scrubbed from every kept note's body, so
  nothing of it reaches world.json or an LLM prompt. For real use with a real model,
  still prefer a *local* one.
- **The corpus layer is transcription by design.** `manifest["corpus"]` carries word
  chains built from your notes' actual bodies, so world.json contains fragments of your
  own wording (that is the point of marginalia). Treat a baked world as private as the
  vault it came from.
- Community detection is single-level Louvain (good for small/medium vaults). For very
  large vaults, add aggregation levels.
- The offline stub is a *contract demonstrator*, not a writer — its prose is templated.
  Swap in a real model for quality; the structure is already correct.

## Next steps worth building

- **Chronicle as boss mechanic:** an Ascendant note that ascended *again* gets a second
  phase; a lost note's echo drops a relic that buffs you in its old region.
- **Folder hierarchy → acts**, sub-headings → tower floors within a region.
- **Multi-level Louvain** + betweenness bridges for very large vaults.
- Port the runtime to rot.js or bracket-lib for tiles + field-of-view.

> The full pipeline is live: `bake` (vault → world) · `runtime.play` (world → game) ·
> `evolve` (two worlds → chronicle) · `play --evolve-from` (chronicle → live upheaval).
