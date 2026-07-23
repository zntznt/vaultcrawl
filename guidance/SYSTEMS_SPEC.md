<!-- Status: Valid (pre-Berlin, creature domain) | Written: 2026-06-29 | Berlin-audited 2026-07-23: describes NPC/enemy systems, no player-class locks -->
# Systems contract (read this before writing a system)

You are adding one **system** to the vaultcrawl runtime — a Qud/Cogmind-inspired layer
that adds a *verb* or *knowledge*, **never** just bigger numbers. Power comes from
interaction and configuration, and should be **lossy**. Keep effects small.

Project root: `/mnt/workspace/output/vaultcrawl` (run everything from here; `cd` first).
Pure stdlib only. No new dependencies. Deterministic: seed all randomness from
`game.seed` (a hex string) + the floor, e.g. `random.Random(f"{game.seed}:{game.floor}:{self.name}")`.

## Hard rules

- **Create ONLY your two files:** `runtime/<system>.py` and `tests/test_<system>.py`.
- **Do NOT edit** `game.py`, `entities.py`, `dungeon.py`, `systems.py`, `mapping.py`,
  `analyze.py`, the schema, or any other system's file. Expose everything through your
  `System` subclass. (Integration into game.py is done by the lead afterward.)
- Subclass `runtime.systems.System` and set a unique `name`.
- Your test must import the **real** `Game`, drive it, call your hooks manually, assert
  behavior, and print `OK`. It must pass.

## The System base class (hooks; override what you need)

```python
from runtime.systems import System
class MySystem(System):
    name = "mysystem"
    def on_world_start(self, game): ...      # once, after the world loads
    def on_floor_enter(self, game): ...      # each descend, floor built + spawns placed
    def on_player_act(self, game): ...       # after each player action (+ enemy turn)
    def on_enemy_killed(self, game, enemy): ...
    def render_overlay(self, game, grid): ...# grid[y][x] single chars; mutate in place
    def status_line(self, game): return None # short str appended to the HUD, or None
```

## Game API you may use (read-only unless noted)

- `game.m` — manifest dict. Keys: `bible`, `graph`, `regions`, `enemies`, `bosses`,
  `items`, `secrets`, `quests`, `seed`, `generatedFrom`.
- `game.seed:str`, `game.floor:int` (1-based), `game.max_floor:int`
- `game.player` — Actor. `game.actors:list[Actor]` (living enemies). `game.items:list[Item]`.
- `game.level` — Level: `.w`, `.h`, `.tiles[y][x]` (chars `#` wall, `.` floor, `>` stairs),
  `.walkable(x,y)->bool`, `.stairs:(x,y)`, `.player_start:(x,y)`, `.rooms`.
- `game.region_name:str` (current). `game.region_for(floor)->region dict`.
- `game.actor_at(x,y)->Actor|None`. `game.on_stairs()->bool`.
- `game.log(msg:str)` — **write** a line to the message log (shown to the player).
- `game.up` — Upheaval (may be empty). Sets: `.ascended`, `.waned`, `.lost`,
  `.risen_regions`, `.contested` (all sets of note ids), `.throne` (note id or None).
- `game.kills:int`, `game.items_taken:int`.
- Helpers: `from runtime.dungeon import free_floor_tiles` → `free_floor_tiles(level, exclude_set)->[(x,y),...]`.

You MAY mutate: `game.player.hp` (clamp to `<= game.player.max_hp`), `game.actors`
(append/remove enemies — build via `runtime.entities.make_enemy(spec, x, y)` or
construct `Actor(...)`), `game.log(...)`, and `game.alive` (only to revive, carefully).

## Entities (`runtime/entities.py`)

- `Actor`: `x,y,glyph,name,hp,max_hp,atk,defense,tier,is_player,is_boss,source` (source =
  note id), property `.alive`.
- `Item`: `x,y,glyph,name,slot,power,flavor,source`.

## Manifest fields you’ll want

- `game.m["graph"]["nodes"][note_id]` → `{title, pagerank, degree, community, bridge,
  role, activity, tags, neighbors}`. `role ∈ {hub,bridge,orphan,leaf,cluster}`.
  `activity ∈ [0,1]` (higher = edited more recently; lower = older → use for "age").
  `neighbors` = linked note ids.
- region dict → `{id, name, biome, element, depthBand:[lo,hi], factionId, sourceNoteId,
  themeTags, activity, flavor}`. `element ∈ {charged,wet,flammable,frozen,sacred,corrosive,inert}`.
- enemy → `{id,name,archetype,tier,damageType,regionId,sourceNoteId,flavor}`.
- boss → `{id,name,title,tier,depth,regionId,sourceNoteId,flavor}`.
- `game.m["bible"]["factions"]` → `[{id,name,ethos,clusterId,relations:[{factionId,stance}]}]`,
  `stance ∈ {ally,rival,vassal,neutral,war}`. Faction id is `faction_{community}`.

## Glyph budget (so overlays don't collide)

Reserved by core: `@ > # . M`, lowercase `a–z` (enemies), `) [ = * !` (items).
Your system's allotted on-map glyphs (use only these):
- reactions: `~` wet · `^` fire · `/` charged · `:` acid · `,` ice · `+` sacred
- sigils: `$` (sigil on the ground)
- history: `?` (lore fragment)
- factions: `H` (hunter)
- knowledge: ` ` (space, to hide unrevealed tiles)

Only overwrite floor cells (`.`) in `render_overlay`, except knowledge-fog, which may
blank any cell to hide it.

## Test recipe (`tests/test_<system>.py`, run `python -m tests.test_<system>`)

```python
from runtime.game import Game, load_manifest
from runtime.<system> import <System>

g = Game(load_manifest("examples/world.json"))
s = <System>()
s.on_world_start(g)
s.on_floor_enter(g)
for _ in range(40):
    g.try_move(1, 0)       # nudge the player around
    s.on_player_act(g)
grid = [row[:] for row in g.level.tiles]
s.render_overlay(g, grid)
assert <something specific to your system>, "…"
print("OK")
```

Report back: your class name, the `name` attr, glyphs used, any `game.*` attributes you
set, and the `status_line` format — so the lead can wire and order the systems.
