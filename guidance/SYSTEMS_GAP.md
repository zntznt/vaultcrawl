<!-- Status: closed 2026-07-27 | supersedes the 2026-06-29 legacy audit -->
# Systems gap: closed

This document existed to answer one question, stated as its own thesis: *"the auto-demo AI
reaches more of the engine than a human can."* That is no longer true, and this is the record
of what it took, including the parts the old version of this file got wrong in the flattering
direction.

## The thesis, retired

`runtime/agent_action.py` `dispatch()` implements **19** verbs. Every one of them is now
reachable from the keyboard. The audit that closed it is `tests/test_keys.py`, which parses the
dispatch chain out of `runtime/play.py` and asserts it against `KEY_TABLE` in both directions,
so this claim cannot rot back into a lie the way the one below did.

## What the old version of this file got wrong

Worth being specific, because these were not drift. They were claims of completion for things
that had never worked:

- **"Break down a sigil, DONE"** (old `:95`). `b` was dead code, and doubly so: its branch sat
  inside the `f` handler at the wrong indent, and `b` is the `yubn` down-left diagonal, so
  `if k in moves` claimed it before the chain was ever reached. It is `B` now.
- **"SacrificeSystem, PLAYER-REACHABLE"** (old `:72`). It is reached only by `Game.interact()`,
  which is reached only by `a`, which was in the same dead block. The shrine had never opened.
- **"Forge, AUTO-AI-ONLY"** (old `:60`). Stale in the other direction: `ForgeSystem.auto` is
  False by default and `interactive()` disables it explicitly. `f` has been a real choice for
  some time.
- **"Dialogue, PLAYER-REACHABLE: `try_move` emits `interact` when you bump an NPC"**
  (old `:62`). `try_move` swaps places with a non-hostile and emits nothing. The only
  `emit("interact")` in the runtime is inside `Game.interact()`. So with `a` dead,
  `DialogueSystem.on_event` never fired for a human, and since `dialogue.py` holds the only call
  to `quests.offer()`, **a human could not acquire a quest at all**. Quests was not one verb
  short, as the old file said. It was severed.
- **The 28-system table listed `abilities.py`**, which is imported for a registration side
  effect and is not a stack member, and **omitted `MarginaliaSystem`**, which is. The
  authoritative list is `build_systems()` in `runtime/stack.py`.
- **"22 keybindings"**, with a ten-row table. It omitted `g o < m P M e V i Q D G` and the debug
  menu, while listing four keys that did nothing.

## The keys, generated from the one place they are written down

`runtime/play.py` `KEY_TABLE`. The status line and the `?` screen both render from it, and
`tests/test_keys.py` checks it against the dispatch chain, so this table cannot drift again.

Movement is `hjkl` plus `yubn` diagonals plus arrows, handled before the chain. Bump to attack;
bump a friendly to swap places.

| Key | Action | What it does |
|-----|--------|--------------|
| `?` | help | This screen |
| `o` | explore | Autoexplore one step toward the nearest unseen tile |
| `g` | travel | Glide one way until something worth stopping for |
| `>` | descend | Take the stair down, when you are on one |
| `<` | climb | Take the stair up |
| `.` / `5` | wait | Let a turn pass, and mend a little |
| `x` | examine | Read what lies around you |
| `i` | inspect | Study the creature beside you |
| `t` | speak | Talk to what is next to you, or to the place itself |
| `e` | effect | Wear one of the effects you carry |
| `z` | toss | Throw matter in a direction |
| `c` | cast | Fire a slotted sigil or a body action |
| `f` | forge | Make a sigil from matter |
| `B` | breakdown | Break a slotted sigil back down into matter |
| `w` | craft | Make a consumable from a recipe you know |
| `s` | set down | Deploy a slotted sigil onto the ground |
| `r` | recover | Take back a sigil you set down |
| `d` | shield | Brace, and take less from the next blow |
| `p` | shove | Push what is beside you, into whatever is behind it |
| `a` | act | Use what is underfoot, or entrust yourself to a Keeper |
| `m` / `P` | log | Scroll back through what has happened |
| `M` | combat log | The same, filtered to blows |
| `Q` | quests | What you have been charged with |
| `C` | companions | Who walks with you |
| `D` | discoveries | What this run has turned up |
| `G` | grave | Read the marker you are standing on |
| `V` | overworld | Look out over the land, from a high place |
| `q` | quit | Leave the run |
| `` ` `` | debug | Debug menu, with `--debug` only |

## What `a` bought back

It is the single most expensive key in the file. `Game.interact()` is the only site that emits
`interact`, so restoring one key restored, in one dedent: the sacrifice shrine, quest
acquisition through `DialogueSystem`, `Game.clear_weather`, `Game.repair_part`, and the
`on_interact` handler in `flora`, `decay`, `reactions`, `sacrifice`, `structures`, `fauna` and
`factions`. Seven systems' interaction handlers had never once run in interactive play.

## Two crashes found on the way

Neither was a verb gap, and both outranked one. They are recorded here because they are what
"nothing tests the input layer" actually costs.

- **`draw()` raised NameError on any graded creature in the viewport.** It coloured them using
  names that are locals of a sibling function, so Python resolved them as module globals and
  found nothing. With the real system stack that fires on the first frame, before any keypress,
  which means the default interactive mode did not start. Keyed on viewport position rather
  than fog, so a graded creature you could not see was enough.
- **`g` raised NameError because `travel` had no `def` line.** It was deleted at some point, so
  travel's docstring became a no-op expression and its body silently became the tail of
  `autoexplore`. Pressing `g` killed the process; pressing `o` took one explore step and then
  asked which way you wanted to travel.

A third, quieter one: assigning `menu = ...` inside the debug handler made `menu` local to the
whole dispatch loop, leaving the real `menu()` unbound for every other caller in it.

## The gap runs both ways

No document had said so. The human has four verbs the agent lacks: `confide`, `recruit`,
body-action `player_cast`, and `EffectSystem.wear`. The human's parley is also the better one:
`negotiate_window` runs every move in `runtime/negotiate.py` with a `resolve(recruit=)` branch,
while the agent gets one round with the last move hardcoded and can never recruit.

## Still open

- **Quest accept, decline and turn-in as direct verbs.** `Q` opens a read-only log. Acquisition
  works again, so this is now genuinely what the old file wrongly called it: small, and not
  blocking. It is feature work rather than repair.
- **Perception, which is where the real asymmetry now lives.** `agent_state()` computes five
  things with no human equivalent on screen: `predicted_traps`, `boss_weak_element`,
  `hazard_behind`, `encounter_options`, and `egress_ready`/`egress_route`. A human plays the
  endgame without being told which of the four win routes is open. No key fixes that; see the
  ambient narrator in `guidance/DESIGN_PLACE_PANEL.md`.
- **The same verb costs the two players differently.** `cast`, `toss`, `recover` and
  `craft_consumable` are free for the agent and cost a human a turn, and a human's `game.wait()`
  also heals. Every cell of that table is a balance number and half of them live in
  `agent_action.py`, so it wants measuring on purpose rather than fixing in passing.
- **The first press of `o` does nothing.** `KnowledgeSystem.seen` is only written in
  `on_player_act`, so at turn 0 the player's own tile reads as unexplored at distance 0 and
  autoexplore returns. Found while working here, not fixed here.

## Reachability gaps found by ablation, not by reading the keymap

This document was written from the input layer outward: which verbs exist, and who can press
them. Ablation and `runtime/system_activity.py` came at the same question from the other end,
by removing systems and by counting whether they ever act, and found three gaps that no key
table could have shown.

- **`sacrifice` cannot fire in classic descent at all.** Not a verb gap: a placement guard.
  `SacrificeSystem.on_floor_enter` opens `z = game.current_z; if z > -2: return`, and negative
  z is a sandbox depths concept. Classic calls `_set_level(lvl, z=0)` on every floor, so
  `current_z` is 0 for the whole run and the guard fires every time. Restoring the `a` key
  above brought the shrine's `on_interact` back for interactive play, and it was still true
  afterwards that classic descent has never placed a shrine to interact with. The two repairs
  are in different layers and neither implies the other.
- **No agent can complete a sacrifice even where a shrine exists.** `on_interact` sets
  `game._pending_sacrifice` and leaves the choice to a front-end popup. This is a fifth entry
  for the verb-gap list above, alongside `confide`, `recruit`, `player_cast` and
  `EffectSystem.wear`, and it is worth noting that the count keeps rising as instruments other
  than the keymap are pointed at it.
- **No agent could take a portal.** Fixed in `5c7f2f4`. `PortalSystem` registers a gate with
  no `<`/`>` glyph under it, `dispatch` gates the descend verb on `on_stairs`, and `on_stairs`
  tested the glyph. Sandbox perception meanwhile steers the agent at the nearest gate, portals
  included, so it walked to a threshold it was forbidden to enter.

`effects` belongs here for a different reason: it is reachable and starved. `EffectSystem`
defines six powers and the only way in is `acquire`, called from `Game.commune_landmark`, which
needs an adjacent wild landmark. Landmarks are placed under `if not self.sandbox and
self.floor % 3 == 0` from notes of degree 0, so sandbox never populates the pool and classic
`examples/world.json` offers exactly one orphan note. That is a content gap rather than a code
one, and it is invisible to every instrument that reads the keymap.

## A note on the bucket audit

The old three-bucket table (PLAYER-REACHABLE / AMBIENT-ONLY / AUTO-AI-ONLY, 14 / 11 / 3) is not
reproduced. Its counts were wrong in at least four rows and its line cites had drifted by up to
1,600 lines, and re-deriving all 28 rows was not part of the work that closed this document.
Treat it as deleted rather than as superseded by something checked. What is checked is the key
table above and the 19-verb claim, and both have tests.
