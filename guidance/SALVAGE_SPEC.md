<!-- Status: Legacy (pre-Berlin) | Written: 2026-06-29 | Berlin compliance not yet applied to this domain -->
# Salvage / inventory contract — everything breaks into the world's materials

The matter of the world is its bible `aesthetic` vocabulary. `runtime/components.py` already
provides:
- `world_materials(game) -> [str]` — the material vocabulary (e.g. `["brass","ink","moss"]`).
- `components_of(game, kind=, source=, tier=, name=) -> {material: qty}` — what any thing
  breaks into (deterministic; richer/more for higher `tier`).
- `Inventory` (`.comp` dict, `.add`, `.total`, `.can_pay`, `.pay`, `.summary`) and
  `inv(actor) -> Inventory` (lazily attached; the player's persists across floors).

The bus already carries:
- `actor_died {actor, cause, pos}` — every death.
- `broke {kind, source, name, tier, pos}` — a sigil shattered (`kind="sigil"`) or a crystal
  detonated (`kind="crystal"`). (Already emitted by sigils.py / structures.py.)

Work in `/mnt/workspace/output/vaultcrawl` (cd every bash; cwd does NOT persist). Pure stdlib,
deterministic, every cross-system call None-guarded. Opt-in: these systems only run when
registered; without them, nothing here happens (existing tests unaffected).

Glyph budget: salvage on the ground draws `*` (the vanilla relic glyph, which is free because
vanilla stat-loot is suppressed when systems are on). Floor cells only.

## Agent A — `runtime/salvage.py` (+ `tests/test_salvage.py`)

`class SalvageSystem(System)` (`name="salvage"`) — drops + collects the world's matter:
- `on_event("actor_died")`: drop salvage at `data["pos"]` carrying `components_of(game,
  kind="creature", source=actor.source, tier=getattr(actor,"tier",1), name=actor.name)`.
  Store `self.ground: dict[(x,y) -> {material:qty}]` (merge if a tile already has salvage).
- `on_event("broke")`: drop salvage at `pos` from `components_of(game, kind=data["kind"],
  source=data["source"], tier=data["tier"], name=data["name"])`.
- `on_player_act`: if the player stands on a salvage tile, pour it into `inv(game.player)`
  and remove it; log `f"Salvaged {…}."`.
- `breakdown_sigil(game, ability=None) -> dict|None`: a player action — pull a slotted sigil
  from `game.system("sigils").slots` (the chosen ability, else the first), remove it, and
  `inv(game.player).add(components_of(game, kind="sigil", source=s.get("note",""),
  name=s["ability"]))`. Return the components (or None if no sigils / no sigil system).
- `render_overlay`: draw `*` on salvage tiles that are still floor (`.`).
- `points_of_interest(game)`: the salvage tiles (so the auto-agent walks over them).
- `status_line(game)`: `f"Matter: {inv(game.player).total()} ({inv(game.player).summary()})"`.
- Query API: `inventory(game) -> Inventory` (the player's), `matter(game) -> int`.
- `on_floor_enter`: clear `self.ground` (ground salvage is per-floor) but DO NOT touch the
  player's Inventory (carried matter persists across floors).

`tests/test_salvage.py`: on a real `Game(load_manifest("examples/world.json"), systems=[SalvageSystem()])`
(+ a SigilSystem for breakdown): emit `actor_died` with a real enemy → assert a salvage tile
exists carrying materials all drawn from `world_materials(game)`; move the player onto it and
`on_player_act` → assert `inventory(game).total()` grew and the tile is gone; emit `broke`
(kind="sigil") → assert salvage drops; give the player a slotted sigil and call
`breakdown_sigil` → assert the slot is freed and matter increased; assert `points_of_interest`
lists salvage tiles; assert inventory PERSISTS across an `on_floor_enter` while ground clears.
Print `OK`, deterministic.

## Agent B — `runtime/forge.py` (+ `tests/test_forge.py`)

`class ForgeSystem(System)` (`name="forge"`) — spend matter to re-craft sigils, closing the
shatter→salvage→forge loop. Read `runtime/sigils.py` for the slot shape
(`{note, role, ability, durability}`), `ROLE_ABILITY`, and `MAX_SLOTS`.
- `forge(game, ability=None) -> bool`: if the player has a free sigil slot
  (`len(sigils.slots) < MAX_SLOTS`) AND `inv(game.player)` can pay a cost (define a sensible
  cost, e.g. `_COST` total matter ≈ 4, spent from the most-abundant materials), then build a
  sigil dict (durability full; ability = the requested one, else a deterministic default /
  cycle), append it to `sigils.slots`, pay the cost, and log `f"You forge a {ability} sigil."`.
  Return True/False. None-guard: no sigil system / not enough matter / slots full → False.
- `on_player_act`: AUTOMATICALLY forge when there's a free slot and enough matter (so a run
  visibly recovers after a sigil shatters). Deterministic ability choice.
- `status_line(game)`: e.g. `"Forge: ready"` when a craft is affordable, else None.
- `cost(game) -> dict`: expose the current forge cost (for the test/HUD).

`tests/test_forge.py`: on a real `Game(load_manifest("examples/world.json"), systems=[SigilSystem(), SalvageSystem(), ForgeSystem()])`:
seed the player's `inv` with plenty of matter (`inv(game.player).add({...})`), ensure a free
sigil slot, call `forge(game, "Ward")` → assert a Ward sigil is now in `sigils.slots`, slot
count rose by 1, and matter dropped by the cost; with slots full OR no matter, `forge` returns
False and changes nothing; assert the auto-forge in `on_player_act` fires the loop when
affordable. Print `OK`, deterministic.

## Agent C — `runtime/salvage_scenario.py`

Narrated, deterministic showcase (model on `runtime/scenario.py`). `import runtime.sigils,
runtime.salvage, runtime.forge` as needed. Fresh `Game(..., systems=[SigilSystem(),
ReactionSystem(), SalvageSystem(), ForgeSystem()])` per piece; judge from live state with ✓/✗.
Demonstrate:
1. **Everything breaks** — print `components_of` for a creature, a sigil, a crystal, and an
   item; assert every yielded material is in `world_materials(game)` (the world's vocabulary).
2. **Death → salvage → inventory** — emit `actor_died`; salvage drops; walk the player onto it;
   inventory total grows; tile clears.
3. **Shatter → salvage** — emit `broke(kind="sigil")`; salvage drops carrying that sigil's matter.
4. **Breakdown** — give the player a slotted sigil; `breakdown_sigil` frees the slot and adds matter.
5. **Forge (closing the loop)** — with enough matter + a free slot, `forge` crafts a sigil:
   slot count rises, matter spent. Narrate shatter → salvage → forge as one cycle.
6. **Inventory persists, ground is per-floor** — after `on_floor_enter`, carried matter remains
   but ground salvage is cleared.

OVERALL PASS only if all ✓; exit 0. Report transcript + any mismatch. Mark task in_progress;
do NOT mark completed (the lead finalizes).

Report (all): glyph, query/command API exposed, events consumed, cost model, integrator notes.
