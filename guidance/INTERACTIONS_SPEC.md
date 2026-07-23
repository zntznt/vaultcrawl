<!-- Status: Valid (pre-Berlin, creature domain) | Written: 2026-06-29 | Berlin-audited 2026-07-23: describes NPC/enemy systems, no player-class locks -->
# Interactions contract (deep cross-system play)

The five systems already run side by side. This phase makes them **interact** — the
output of one becomes the input of another, producing Qud/Cogmind emergence:

- lure an enemy onto a hazard → it dies to the **environment**, which is a **quiet** kill
  the faction never notices (vs a **loud** melee kill that raises its alert);
- **Ward** (sigil) shoves an enemy into **acid/fire** (reactions) — shove-to-kill;
- standing in **charged** tiles **corrupts** your sigils (they shatter faster);
- killing a **hunter** scavenges its sensors → reveals the map (knowledge);
- high **standing** with a faction → it **shares its map** with you;
- reading a **lore fragment** (history) **reveals** the boss/secret region it names;
- enemies are **immune** to their own region's element and **weak** to its opposite.

Read this with `SYSTEMS_SPEC.md` (the base Game/System API still applies). Work in
`/mnt/workspace/output/vaultcrawl` (cd for every bash). Pure stdlib. Deterministic.

## You OWN exactly one existing system file

Edit **only** `runtime/<your-system>.py` and its test(s) under `tests/`. Do NOT edit any
other system, `game.py`, `systems.py`, `entities.py`, or `dungeon.py`. Systems interact
ONLY through the bus and the query API below — never by importing each other.

## The bus

- `game.emit(etype, **data)` — broadcast; calls every system's `on_event(game, etype, data)`.
- `System.on_event(self, game, etype, data)` — override to react. `data` is a dict.
- `game.system(name)` — fetch another registered system by `.name`, or `None`.

### Canonical events

| event | payload | emitted by | 
|---|---|---|
| `"enemy_killed"` | `{"enemy": Actor, "cause": "melee"\|"environment"\|"sigil"}` | game (melee), reactions (environment) |
| `"lore_read"` | `{"note": str, "region_id": str\|None}` | history |

`game.py` already emits `enemy_killed`/`cause="melee"` on a bump kill. **Migration:** if
your system currently overrides `on_enemy_killed`, DELETE that override and move the logic
into `on_event` under `etype == "enemy_killed"`, branching on `data["cause"]`. (game.py
calls both during this transition, so deleting your override avoids double-counting.)

## Query API — the methods each system MUST expose

Other systems will call these on `game.system("<you>")`. Implement exactly these
signatures. **Every cross-system call you MAKE must be None-guarded** (degrade gracefully
if the partner isn't registered): `r = game.system("reactions"); haz = r.is_hazard(x, y) if r else False`.

- **reactions** exposes:
  - `element_at(x, y) -> str | None`   (dominant reactive property at the tile)
  - `is_hazard(x, y) -> bool`          (would standing here damage an actor?)
  - `props_at(x, y) -> set[str]`
- **factions** exposes:
  - `faction_of(note_id) -> str | None`   (`"faction_{community}"`)
  - `standing_of(faction_id) -> int`
- **knowledge** exposes:
  - `reveal(target) -> None`           (target = a note id OR a region id; reveal it as known/mapped)
  - `is_known(note_id) -> bool`
- **sigils** exposes:
  - `has_ability(name) -> bool`        (optional; used for flavor)

## What each owner implements

**reactions** (`runtime/reactions.py`)
- **Elemental affinity:** when a hazard damages an *enemy*, scale by affinity. An enemy is
  *immune* (0×) to its own region's element and takes *2×* from the opposing one. Opposites:
  `charged↔wet`, `fire↔frozen/ice`, `acid↔sacred`. Derive the enemy's home element from
  `enemy.source` → `game.m["graph"]["nodes"][source]["community"]` → the region whose
  `factionId == f"faction_{community}"` → its `element`.
- When a hazard kill happens, `game.emit("enemy_killed", enemy=e, cause="environment")` and
  log it as a quiet/"unnoticed" kill. (Do NOT also call `on_enemy_killed`.)
- Expose `element_at`, `is_hazard`, `props_at`.

**factions** (`runtime/factions.py`)
- Handle kills via `on_event("enemy_killed")`: `cause in ("melee","sigil")` → **loud**
  (disturbance +1, standing −1, rivals +1, as today). `cause == "environment"` → **quiet**
  (no disturbance; you may gently decay alert). Log the distinction.
- **Hunter intel:** if a killed enemy is one of your hunters (you spawn them) and the kill is
  loud, call `knowledge.reveal(current_region_id)` (guarded) — you scavenge its sensors.
- **Shared map:** in `on_floor_enter`, if `standing_of(current_faction) >= 3`, call
  `knowledge.reveal(current_region_id)` (guarded) in addition to the existing safe-passage.
- Expose `faction_of`, `standing_of`.

**knowledge** (`runtime/knowledge.py`)
- Migrate reveal-on-kill to `on_event("enemy_killed")` (reveal `enemy.source` + neighbors).
- `on_event("lore_read")`: `reveal(data["region_id"])` (and the note).
- Expose `reveal(target)` (accept a note id or a region id; mark known/mapped) and
  `is_known(note_id)`. Keep the fog behavior.

**sigils** (`runtime/sigils.py`)
- **Ward → shove-to-kill:** when Ward fires, prefer shoving each adjacent enemy onto a
  hazard tile (`reactions.is_hazard`, guarded) instead of just away; log "Ward shoves <name>
  toward the <element>." The reaction system damages it on the next tick.
- **EM corruption:** in `on_player_act`, if the player stands on/next to a `charged` tile
  (`reactions.props_at`, guarded), drain 1 durability from a random slotted sigil and log
  "EM corruption frays your <ability>." (deterministic via your seeded rng).
- Keep all existing sigil behavior. None-guard every reactions call.

**history** (`runtime/history.py`)
- When a fragment is read, in addition to the log, `game.emit("lore_read", note=<target note>,
  region_id=<that boss/secret's region id>)` so knowledge reveals it. Bosses carry
  `regionId`; for a secret, map its `sourceNoteId`'s community → region id.
- Keep history generation as-is.

## Testing — prove the interaction, but don't depend on a mid-migration partner

Each owner writes/updates `tests/test_<system>.py` to assert BOTH its core behavior AND its
interaction, using **spies/stubs** for partners (don't rely on the real partner's new code,
which may be landing in parallel):

```python
from runtime.systems import System
class Spy(System):
    name = "spy"
    def __init__(self): self.events = []
    def on_event(self, game, etype, data): self.events.append((etype, data))
    # stub any query a partner needs, e.g.:
    def is_hazard(self, x, y): return (x, y) in self._haz
```

Register your system + a spy/stub on a real `Game(load_manifest("examples/world.json"),
systems=[...])` (pass `systems=` so hooks fire), drive it, and assert. Examples:
- reactions: kill an enemy via a hazard → the spy received `("enemy_killed", {"cause":"environment", ...})`; affinity: an enemy of a `charged` region takes 0 from a charged tile and 2× from a wet tile.
- factions: `on_event("enemy_killed", {"cause":"melee", "enemy":e})` raises disturbance; `"environment"` does not; a hunter kill calls `reveal` on a knowledge-stub.
- sigils: with a stub reactions exposing `is_hazard`, Ward shoves an adjacent enemy onto a hazard tile; a charged `props_at` drains durability.
- knowledge: `on_event("lore_read", {"region_id": R})` makes `is_known`/mapped true for R.
- history: reading a fragment emits `lore_read` with a real `region_id` (caught by a spy).

Run `cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_<system>` → must print `OK`.

Report back: what you exposed (query methods), what events you emit/consume, and any
ordering needs for the integrator.
