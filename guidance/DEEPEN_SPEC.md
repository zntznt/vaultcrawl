<!-- Status: Current (post-Berlin) | Written: 2026-07-23 -->
# Deepen contract — social, objective, and machine layer

Turns vault `- [ ]` TODOs into quests, note-anchored Keepers into NPCs, and
floors into hackable machine sites. Opt-in: registered explicitly; bare game
untouched. Pure stdlib, deterministic, every cross-system call None-guarded.

**What this covers:** `runtime/quests.py`, `runtime/dialogue.py`,
`runtime/machines.py`, `runtime/negotiate.py`, `runtime/deepen_scenario.py`

## QuestSystem (`runtime/quests.py`)

`QuestSystem(System)` (`name="quests"`) — lifecycle **offer→active→complete**:

- **Kinds:** `slay` (graph-nearest boss via `_nearest_boss`), `fetch`/`escort` (reach
  region `depthBand` via `_nearest_region`), `cleanse` (`_floor_clear`: no `monster`
  allegiance actors with hp>0), `recover` (accrue `inv(player).total()` matter).
  Bound deterministically in `_bind` using BFS `_graph_dist`.
- **Bus events:** `on_event("enemy_killed")` → `_record_kill` (boss `sourceNoteId` in
  `_slain_bosses`). `on_floor_enter`/`on_player_act` → `_check(game)`.
- **Rewards** (`_grant_reward`): slay → `_raise_standing(game, fid, +2)` via
  `FactionSystem.standing`. Cleanse/reach → `_reveal(region_id)` via
  `KnowledgeSystem.reveal`. Recover/fallback → `_grant_matter` (2–3 units of a
  `world_materials` material into `inv(game.player)`).
- **Query:** `offer(game)` (NPCs call this), `quest_progress(game, q)` → e.g.
  `"matter 3/5"`, `status_line(game)` → `"Quests: 0/3"`.

## DialogueSystem / Keeper NPCs (`runtime/dialogue.py`)

`DialogueSystem(System)` (`name="dialogue"`) — one neutral Keeper per region on the
surface (`game._dungeon` blocks it below). Spawned via `free_floor_tiles` near the
region's anchor room; glyph `NPC_GLYPH = "P"`, allegiance `"npc"`. Bumping swaps
positions (never attacks); `t` verb emits `interact` on the bus.

**Parley priority chain** in `on_event("interact")`:
1. **Quest** (`_try_quest`): `QuestSystem.offer(game)` — Keeper entrusts next charge.
2. **Offering** (`_try_offering`): spends 1 unit of held matter, raises
   `FactionSystem.standing[fid]` by 1, reveals `_region_ahead`. Ties reputation to
   the matter economy, not Qud's water.
3. **Gossip** (`_gossip`): rotates boss/secret reveals per `npc._parleys`; speaks a
   line from `game._weave_note(npc.source, salt="gossip")`.

**Hooks:** `points_of_interest(game)` → Keeper tiles (auto-agent walks over).
`status_line(game)` → `"Keepers: 1"`.

## Talk verbs & Parley (`runtime/play.py`, `runtime/negotiate.py`)

`TALK_VERBS` at `play.py:619` — five player verbs always available in any talk frame:
`("Speak with it", "Ask its history", "Offer matter", "Confide a truth", "Seek a truce")`.
`Seek a truce` hands off to `Parley` (hostile only).

`class Parley` (`negotiate.py`) — SMT-style deterministic negotiation:
- **Temperament by graph role** (`TEMPERAMENT`): hub→`proud` (loves `praise`, spurns
  `gift`), bridge→`curious` (loves `truth`), leaf→`timid` (loves `gift`, spurns `truth`),
  orphan→`lonely` (loves `ask`), cluster→`communal` (loves `gift`).
- **Disposition** starts with knowledge bonus (+2 if `learned`) and bloodied penalty (-1).
  `taste` weights per move; 25% `fickle` chance flips delta ("strange humor").
- **Resolution:** `goal` (3–5, scaled by note `activity`); `"swayed"` → reveals note +
  goes wild/recruited; `"enraged"` at `ENRAGE_AT = -3` → permanent `_enraged` flag;
  `"bored"` after `MAX_ROUNDS = 4`. `MOVES = ("praise", "ask", "truth", "gift")`.

## MachineSystem (`runtime/machines.py`)

`MachineSystem(System)` (`name="machines"`) — two single-use props per floor, placed
`on_floor_enter`:

- **Fabricator** (`FAB_GLYPH = "F"`, glyph `F`): seeded near hub-note room via
  `_anchor_for_role("hub")`. On step (`on_player_act`), calls
  `forge.forge(game, _pick_ability(game))` — crafts the first unslotted ability,
  burns out (`discard(pos)`). Inert if no slot or no matter.
- **Terminal** (`TERM_GLYPH = "T"`, glyph `T`): seeded near bridge-note room. On step,
  `knowledge.reveal(region_ahead(game))` (deeper region via `depthBand` sort) +
  `_disarm_nearby` (one 3x3 trap). If weather active: `_scramble_weather` instead
  (30-turn suppress via `game._weather_suppressed`).
- **Glyphs drawn** via `render_overlay` on `.` cells only. **Agent hooks:**
  `points_of_interest(game)` → sorted positions; `status_line` → `"Machines: 1F 1T"`.

## Testing: `runtime/deepen_scenario.py`

Narrated showcase, fresh `Game(load_manifest(MANIFEST), systems=[SigilSystem,
ReactionSystem, KnowledgeSystem, FactionSystem, SalvageSystem, ForgeSystem,
QuestSystem, DialogueSystem, MachineSystem])` per piece. Five set-pieces:
1. **Quest from a note** — slay charge bound, `emit("enemy_killed")` → complete + reward.
2. **NPC parley** — drain offers, triggering offering boon (matter spent → standing + map).
3. **Fabricator** — player on `F` tile → forge fires, slot +1, bench burns out.
4. **Terminal** — player on `T` tile → `is_known(anchor)` flips False→True, node dies.
5. **NPCs are neutral** — monster adjacent to Keeper 5 turns, 0 damage; bump swaps; `t`
   verb parleys.
