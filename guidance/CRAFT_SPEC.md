<!-- Status: Current (post-Berlin) | Written: 2026-07-23 -->
# Crafting / wear / recipes / skills contract

The agent sacrifices something permanent at a workspace to gain a system wire.
Crafts persist on the player, wear scales with quality, 25 consumables are
discovered from 6 sources, and 5 skill trees gate mastery bonuses.

**What this covers:** `runtime/craft.py`, `runtime/wear.py`, `runtime/recipes.py`,
`runtime/proficiency.py`

## CraftSystem (`runtime/craft.py`)

`class CraftSystem(System)` (`name="craft"`). Fires BEFORE `MachineSystem` in the
systems list (`play.py:1278`). Four site-based workspace rituals, standing on the
workspace tile:

- **Fabricator** (`_craft_fabricator`) -- sacrifice a sigil slot permanently;
  the sigil auto-casts when HP < 50%. Stored as `game.player._crafts["auto_{ability}"]`
  (type `"auto_cast"`).

- **Terminal** (`_craft_terminal`) -- sacrifice 2 known notes from
  `KnowledgeSystem.known`. Gain passive enemy HP reveal: `_crafts["passive_enemy_hp"]`
  (type `"passive_reveal"`).

- **Depleted Locus** (`_craft_locus`) -- sacrifice 1 collected effect from
  `EffectSystem.collected`. Kill→heal trigger: `_crafts["kill_heal"]` (type
  `"condition_trigger"`, trigger `"enemy_killed"`, effect `"heal_2"`).

- **Camp** (`_craft_camp`) -- sacrifice 10 max HP (floor 5). Hazard walk immunity:
  `_crafts["hazard_walk"]` (type `"environmental"`, effect `"hazard_immunity"`).

`CraftSystem.apply_wires(game, event_type, **data)` -- static dispatcher called
from `game.py` on `"player_hp_check"` and `"enemy_killed"`. Fires any active wire
whose condition matches. `status_line(game)` returns `"Crafts: auto-Recall, ..."`.

## Wear system (`runtime/wear.py`)

5 tiers: `fine → scuffed → worn → damaged → broken`. Effectiveness:
`WEAR_EFFECTS = {fine:1.0, scuffed:0.75, worn:0.5, damaged:0.25, broken:0.0}`.
`WEAR_CHANCE` per quality: Normal 15%, Uncommon 10%, Rare 7%, Epic 4%, Legendary 1%.

- `apply_wear(game, item, quality, uses)` -- deterministic degradation via
  `hash(f"{item_id}:{game.turn}")`.
- `maintain(game, item)` -- spends 1 matter, restores 1-2 tiers. Tinkering
  tier 2 gives chance for +2; tier 3+ guarantees +2 restore.
- `wear_multiplier(item)`, `is_broken(item)` -- effectiveness/state check.
- `craft_consumable(game, recipe_name)` -- pays `RECIPE_COSTS[name]` matter
  from `SalvageSystem.inventory()`; requires recipe in `player._known_recipes`.

## 25 Consumable recipes (`runtime/recipes.py`)

`register_recipe(name, cost, effect_fn)`. Matter costs 1-5.

| Cost | Recipes |
|------|---------|
| 1    | growth_spore, corpse_compost, lantern_oil |
| 2    | noise_lure, scent_mask, hush_chime, blight_salve, root_tendril, memory_dust, brewers_yeast |
| 3    | faction_token, weather_vane, trap_kit, cache_decoy, echo_shard, frost_ampoule, sparkwire, wardstone, graft_patch |
| 4    | portal_anchor, crystal_seed, scarab_charm, prophecy_ink |
| 5    | beacon_fragment, kinship_bond |

Each effect touches at least one subsystem: sense/noise, factions, flora, scent,
weather, portals, structures/traps, decay, body-parts/heal, knowledge/reveal,
reactions/hazards, companions, crafting/wear, salvaging, quests/scrying, becalm.

**6 discovery sources** (each calls `_pick_undiscovered(game, source_tag)`):

1. `discover_from_lore(game)` -- 10%
2. `discover_from_parley(game)` -- 15% + `_scholar_bonus(game)`
3. `discover_from_boss(game)` -- 30%
4. `discover_from_cache(game)` -- 12% + scholar bonus
5. `discover_from_terminal(game)` -- 20% + scholar bonus
6. `discover_from_confide(game)` -- 18% + scholar bonus

Scholar bonus: `skills().tier("scholarship") * 0.02` (adds up to +10%).

**Starter recipes** in `Game.starting_kit(agent_name)`: artisan→blight_salve,
cartographer→prophecy_ink, emergent→trap_kit, exploiter→noise_lure,
seeker→brewers_yeast, whisper→faction_token.

## 5 Skill trees (`runtime/proficiency.py`)

`class Skills` holds five `SkillTracker` instances (ring buffer size 20 + lifetime
counter). Tiers: 0→0, 1→5 exercises, 2→15, 3→30, 4→60, 5→100.

| Skill | Trigger | Bonus |
|-------|---------|-------|
| tinkering | maintain actions | better wear restoration |
| foraging | harvest flora | yield bonus, plant regrowth |
| husbandry | tame grazers | unlock scavengers/predators, companion auto-maintain |
| scholarship | read lore | +2% recipe discovery per tier, truth bonus |
| diplomacy | parley/negotiate | cheaper becalm, standing decay reduction |

Accessed via `skills().tier(name)`, `skills().exercise(name)`, `skills().recent(name)`.
Separate from forge `ProficiencyTracker` (`ptracker()`, `can_craft()`).
