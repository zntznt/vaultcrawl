<!-- Status: Current (post-Berlin) | Written: 2026-07-23 -->
# Loci contract -- polymorphic encounter nodes

Neutral until an agent approaches. The agent's profile type-casts the locus: a
fighter spawns combat, a crafter finds a forge. One world object, many outcomes.

**What this covers:** `runtime/loci.py`

## LocusSystem (`runtime/loci.py`)

`class LocusSystem(System)` (`name="loci"`) -- places neutral `?` nodes per floor,
type-casts on agent proximity (Chebyshev distance <= 2).

### Placement (`on_floor_enter`)

5-8 baseline (`5 + hash % 4`), adjusted by depth:

| Floors | Loci | Theme |
|--------|------|-------|
| 1-8    | 8-11 | early sustain |
| 9-15   | 4-7  | mid taper |
| 16+    | 2-5  | deep scarcity |

Walkable tiles, >=6 from player, >=4 from stairs. Stored in
`self.loci: dict[(x,y) -> {type:, glyph:, ...}]`.

### Type-casting (`on_player_act`, `_activate`)

Highest-scored profile action (`game.player.brain.profile`) activates:

| Profile | Type     | Glyph | Effect |
|---------|----------|-------|--------|
| forge   | forge    | `F`   | free sigil (Recall/Ward/Phase/Echo/Rally) + 2 essence |
| parley  | parley   | `p`   | +1 faction standing, reveal one note |
| explore | explore  | `e`   | reveal radius 10 tiles into `KnowledgeSystem.seen` |
| fight   | fight    | `!`   | Locus Sentinel: tier-2 warden, 5 HP |
| shield  | shield   | `D`   | +1 DEF (cap 5) |
| commune | commune  | `c`   | +1 truth (`MarginaliaSystem.read`) |
| becalm/recall | becalm | `b` | +5 HP heal |

Fallthrough (balanced profiles): random from `[forge, parley, explore, shield]`.

### Beacon variant

Entry floor of the deepest boss region gets a beacon within 6 tiles of stairs
(`"beacon": True`). Prioritizes `commune` if agent has >= 2 truths or >= 4 matter,
else falls through to profile type-casting.

### Depleted loci

`_consume()` marks `locus["depleted"] = True`. Renders as `·`. `CraftSystem` uses
depleted loci as crafting sites: sacrifice 1 collected effect → kill→heal 2 HP.

### Healing

Every activation provides sustain via `heal_body()`: forge +5, parley +5,
explore +3, shield +3, commune +10, becalm +5. No agent cost.

### Rendering (`render_overlay`)

| State | Glyph |
|-------|-------|
| untyped | `?` |
| typed | `F`/`p`/`e`/`!`/`D`/`c`/`b` |
| depleted | `·` |

### Perception (`agent_state()` in `agent_perception.py`)

`loci_count`, `nearest_locus` `(x, y, dist)`, `beacon_on_floor`,
`nearest_beacon` `(x, y, dist)`.

### Integration points

- `points_of_interest(game)` returns non-depleted untyped loci positions
- `status_line(game)` returns `"Loci: N remaining"`
- `self.depleted` cleared per floor; `CraftSystem` queries `loc.get("depleted")`
