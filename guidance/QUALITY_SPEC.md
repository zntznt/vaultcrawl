<!-- Status: Valid (pre-Berlin, creature domain) | Written: 2026-06-29 | Berlin-audited 2026-07-23: describes NPC/enemy systems, no player-class locks -->
# Quality contract — Factorio-style grades on everything

`runtime/quality.py` is the hub. Tiers: `NORMAL(0) UNCOMMON(1) RARE(2) EPIC(3) LEGENDARY(4)`,
`NAMES[t]`, `mark(t)`. Quality is **rare** and **opt-in**: only the `QualitySystem` assigns
it (registered in the live game + your tests); without it everything is Normal. Work in
`/mnt/workspace/output/vaultcrawl` (cd every bash; cwd does NOT persist). Pure stdlib,
deterministic, None-guard every cross-system call.

## quality.py API
- `roll(rng, floor=0, bias=0.0) -> int` — tier ≥ floor, rare, cascading; `bias`≥0 raises odds.
- `scale_creature(actor, tier)` — +stats per tier (already applied by the QualitySystem).
- `quality_of(thing) -> int` (actor/item/sigil-dict).
- Registries (call at import): `register_action(name, fn)`, `register_perk(name, kind, apply)`,
  `register_additive(material, perk_name)`; dicts `SPECIAL_ACTIONS`, `PERKS`, `ADDITIVE_AFFINITY`.
- `QualitySystem` (`name="quality"`): `on_floor_enter` qualifies each monster/critter (rolls
  tier; if >0 scales stats + assigns `actor._special_actions` = tier names from SPECIAL_ACTIONS,
  prefixes the name, sets `actor.quality`); `on_player_act` makes quality creatures perform a
  special action on a cadence; **`qualify_sigil(game, sigil, floor=0, bias=0.0, additives=None)
  -> tier`** rolls a sigil's quality, grants one perk per tier (from PERKS, biased toward
  `ADDITIVE_AFFINITY[material]` for each material in `additives`), applies `kind=="stat"` perks
  immediately and records all in `sigil["perks"]`, sets `sigil["quality"]`.
- Entity fields: `actor.quality`, `item.quality`, sigil dict `["quality"]`/`["perks"]` (default 0/[]).
- Inventory (`runtime/components.py`): `add(comps, quality=0)` now also banks per-material
  quality; `quality_of(material)`, `min_quality(materials)` → for the crafting floor.

A perk def: `register_perk(name, kind, apply)` where `kind ∈ {"stat","passive"}`; `apply(sigil)`
mutates the sigil for stat perks (e.g. `+durability`) or is `None` for passives (a flag in
`sigil["perks"]` that the sigil logic reads). A special action: `fn(game, actor) -> bool`
(True if it did something); it MUST keep engine invariants (no two actors on a tile, only
`level.walkable` tiles — use `runtime.dungeon.free_floor_tiles`).

## Agent A — sigil quality + perks (`runtime/sigils.py` edits + `tests/test_sigils.py`)
- When a sigil is CREATED (in `_place`, and any pickup-time creation), call
  `q = game.system("quality"); q.qualify_sigil(game, sigil, ...)` if `q` (else leave Normal).
- `register_perk(...)` a real pool (≈6): stat perks (e.g. `reinforced` +durability,
  `keen` +1 effect magnitude/radius applied as data) and passive perks the sigil logic reads
  from `sigil["perks"]` (e.g. `ward_reach` → Ward shoves 2 tiles, `phase_decoy` → Phase leaves
  a brief decoy, `recall_cleanse` → Recall also clears the player's feared elements,
  `thrifty` → 1-in-2 chance a use costs no durability, `echo_twin` → Echo revives at 2 hp).
  Interpret those passives where each ability fires. Keep effects bounded (utility, not flat damage spam).
- Test: with a `QualitySystem` registered, force a high roll (seed / `qualify_sigil(..., floor=3)`)
  and assert the sigil gained `tier` perks and a known stat perk took effect; without a
  QualitySystem, sigils stay Normal (no perks) — existing slot mechanics unchanged. Print `OK`.

## Agent B — forge/fabricator quality + additives (`runtime/forge.py` (+ machines) edits + `tests/test_forge.py`)
- In `forge(game, ability=None, additives=None)`: after picking the `cost`, set
  `floor = inv(game.player).min_quality(cost)` (never below the lowest ingredient), and a
  `bias` that rises with the input quality (e.g. `0.15*floor`) plus a small bump per additive.
  **Additives** = extra materials the player spends beyond the recipe (auto-pick a couple of
  the player's abundant materials, or accept a param); pay them too. Call
  `game.system("quality").qualify_sigil(game, sigil, floor=floor, bias=bias, additives=additive_mats)`
  before slotting, so the forged sigil's quality (and perks) reflect inputs + additives.
- `register_additive(material, perk_name)` for a few materials so a chosen additive favours a
  specific perk (vs a random one).
- Test: seed `inv` with high-quality matter (`inv.add({...}, quality=2)`) → assert the forged
  sigil's `quality >= 2` (floor honored); forging with an additive whose affinity is perk P →
  assert P is among the sigil's perks. Without a QualitySystem, forging still works (Normal).
  Print `OK`.

## Agent C — creature special-action library (`runtime/abilities.py` + `tests/test_abilities.py`)
- `register_action(name, fn)` a rich, INVARIANT-SAFE set (≈6–8): e.g. `enrage` (small temp
  atk up), `summon` (spawn ONE weak ally on a `free_floor_tiles` tile — same allegiance),
  `blink` (teleport to a free tile nearer the player), `spit` (ranged: if the player is in a
  straight line within N and unobstructed, deal small damage), `shield` (raise own defense /
  small heal), `rally` (buff an adjacent ally's atk), `split` (spawn a half-HP copy on a free
  tile). Each `fn(game, actor) -> bool`; NEVER place an actor on an occupied/unwalkable tile;
  keep numbers modest; deterministic (derive any rng from `game.seed`+pos+turn).
- Test: build a Game with a `QualitySystem`; construct a quality creature
  (`actor.quality=3; actor._special_actions=[...]` or force via the system), call each action
  fn directly, assert it either did something legal or returned False, and assert NO invariant
  break (no two actors share a tile, every actor on a walkable tile). Print `OK`.

## Agent D — `runtime/quality_scenario.py`
Narrated, deterministic showcase (model on `runtime/scenario.py`). `import runtime.abilities`
(+ sigils/forge already register their perks/additives on import). Fresh Game per piece with
`[SigilSystem, ReactionSystem, SalvageSystem, ForgeSystem, QualitySystem]` (+ MachineSystem
where useful). Demonstrate, judged from live state with ✓/✗:
1. **Rarity is rare** — roll a few thousand and print the tier histogram (mostly Normal, a
   sliver Legendary); show the cascade.
2. **Quality creature** — force a Rare/Epic creature (seed or set fields via the system) and
   show it has scaled stats AND ≥1 special action, and that calling its action does something legal.
3. **Quality equippable** — a high-tier sigil carries `tier` perks (name + effects), including
   a stat perk that changed a value.
4. **Crafting floor + cascade** — seed Rare matter; forge → output `quality >= Rare`; show a
   cascade reaching Epic/Legendary with bias.
5. **Additive steering** — forge with an additive whose affinity favours perk P → P appears
   (vs a random perk without it).
6. **Salvage carries quality** — a quality creature's salvage banks higher-quality matter
   (`inv.quality_of(material) > 0`), feeding the next forge's floor.
OVERALL PASS only if all ✓; exit 0. Report transcript + mismatches. Mark your task
in_progress; do NOT mark completed (the lead finalizes).

Report (all): what you registered, how you read quality, integrator notes (esp. invariant safety).
