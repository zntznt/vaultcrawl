# Systems gap: 18 systems, 9 player verbs (mostly closed)

The engine runs an 18-system stack (`runtime/play.py` wires them into `Game`). The
**interactive human UI** (`runtime/play.py` `interactive()`) binds nine inputs:

| Key | Action | Calls |
|-----|--------|-------|
| arrows / `h` `j` `k` `l` | move | `game.try_move(dx, dy)` |
| `>` (or `.` on stairs) | descend | `game.descend()` |
| `.` / `5` (off stairs) | wait in place (quiet: no footstep noise) | `game.wait()` |
| `x` | examine: region + nearby actors/items + system POIs (sigils, lore, salvage, machines, marginalia), with baked flavor | `game.examine()` |
| `c` | cast a slotted sigil NOW (pick a slot; costs the turn) | `SigilSystem.cast` |
| `f` | forge a chosen ability from matter (costs the turn) | `ForgeSystem.forge` |
| `b` | break down a slotted sigil into matter (costs the turn) | `SalvageSystem.breakdown_sigil` |
| `t` | speak: commune with the final boss, parley with a Keeper, or NEGOTIATE with an adjacent hostile (SMT-style rounds; it speaks its note's own words, temperament by graph role) | `game.commune` / `interact` / `negotiate.Parley` |
| `z` | toss a scrap of matter: it clatters up to 4 tiles away and hearing creatures investigate (active stealth) | `game.toss` |
| (walk into hostile) | bump-attack | `try_move` → `attack` |
| (walk into friendly) | swap places — a Keeper or wild body never blocks a way; talk is `t` | `try_move` |
| `q` / `Esc` | quit | — |

Flavor is no longer dead data: region flavor logs on first entry, boss flavor on spawn,
enemy flavor on first blood (once per source note), item flavor on pickup and examine.

Manual timing beats the passive triggers: a cast Ward shoves even a single foe, a cast
Phase blinks without being boxed in, a cast Recall mends mid-fight. Echo stays a
death-trigger. In interactive mode the forge autopilot is off (`ForgeSystem.auto`), so
`f` is a real choice; the headless demo keeps auto-forge.

`try_move()` (`game.py:176-193`) is the **only** action a human drives. A human reaches a
system only by: **stepping onto a tile**, **bumping a hostile** (combat), **bumping an NPC**
(`interact` → parley), or **the per-turn tick** (`on_player_act` / `on_floor_enter`).

The depth is real but **ambient**: systems react to where you *step*, not to anything you
*choose*. The auto-demo AI (`play.py --auto`) reaches more of the engine than a human can,
because its brain selects actions that have no keybinding.

---

## The buckets

Each system is one of:

- **PLAYER-REACHABLE** — a human meaningfully drives it with the 4 verbs (reacts to where you step / who you bump).
- **AMBIENT-ONLY** — runs every turn regardless of intent; the player witnesses, cannot direct.
- **AUTO-AI-ONLY** — only does something interesting when an AI brain picks an action a human has no key for, *or* exposes a public action verb that `interactive()` never binds.

| # | System | Bucket | Evidence |
|---|--------|--------|----------|
| 1 | SenseField (`senses.py`) | AMBIENT | Decays sound/scent each turn; `noise` is auto-emitted by `try_move`, never chosen. `senses.py:300` |
| 2 | Memory (`memory.py`) | AMBIENT | Infers beliefs/grudges for non-player actors each turn; "player has no memory-brain by default." `memory.py:122,141` |
| 3 | **Sigils** (`sigils.py`) | PLAYER-REACHABLE* | Step onto `$` slots a sigil (`_pickup`); Ward/Phase/Echo/corrode **auto-fire** by where you stand. *No manual cast.* `sigils.py:77,146,256` |
| 4 | Reactions (`reactions.py`) | AMBIENT | Resolves fire/acid/shock on each actor's tile, spreads fire; you influence only by where you step. `reactions.py:189` |
| 5 | Weather (`weather.py`) | AMBIENT | Stirs the substrate on a fixed cadence. "It pursues no one's interest." `weather.py:77` |
| 6 | Flora (`flora.py`) | AMBIENT | Burns/spreads plants from the substrate; "indifferent — it targets no one." `flora.py:106` |
| 7 | Structures (`structures.py`) | PLAYER-REACHABLE | Walking onto a `_` plate springs a trap (player is in `_occupants`); crystal blast catches you. `structures.py:107,171` |
| 8 | Decay (`decay.py`) | AMBIENT | Drops corpses on `actor_died`, rots/seeps them; seep gnaws whoever stands on `%`. `decay.py:43,75` |
| 9 | Fauna (`fauna.py`) | AUTO-AI-ONLY | Critters "never path to or attack the player"; player↔wild non-hostile so even bumping does nothing. Pure spectacle. `fauna.py:16,108`, `game.py:216` |
| 10 | Salvage (`salvage.py`) | PLAYER-REACHABLE† | Standing on `*` banks salvage (`_collect`). †But `breakdown_sigil()` (the voluntary melt) is never bound. `salvage.py:53,111` |
| 11 | Forge (`forge.py`) | AUTO-AI-ONLY | `forge()` auto-fires in `on_player_act` whenever slot+matter exist; human never *chooses* what to craft. `forge.py:128,188` |
| 12 | Quests (`quests.py`) | AUTO-AI-ONLY | Objectives auto-check; the only way to *acquire* a quest is `offer()`, reachable only via the (bump-driven) parley. No accept/turn-in verb. `quests.py:64,286` |
| 13 | Dialogue (`dialogue.py`) | PLAYER-REACHABLE | Parley fires on `interact`; `try_move` emits `interact` when you bump an NPC. Bump-into-Keeper works. `dialogue.py:75`, `game.py:183` |
| 14 | Machines (`machines.py`) | PLAYER-REACHABLE | Standing on an `F`/`T` tile runs the Fabricator/Terminal (forge/hack). `machines.py:210` |
| 15 | Factions (`factions.py`) | AMBIENT | Reacts to `enemy_killed` you cause via combat, dispatches hunters / grants passage on descent. No direct faction verb. `factions.py:127,170` |
| 16 | Quality (`quality.py`) | AMBIENT | Rolls quality on spawns; drives elite special actions on a cadence. Grades the world, not the player. `quality.py:136` |
| 17 | History (`history.py`) | PLAYER-REACHABLE | Stepping onto a `?` reveals a lore fragment / boss / secret. `history.py:192` |
| 18 | Knowledge (`knowledge.py`) | AMBIENT | Paints the fog radius each turn; `reveal()` called only by other systems. `knowledge.py:108` |
| + | `abilities.py` | PLAYER-REACHABLE | Registers enrage/shield/rally/spit/blink/summon/split for elite creatures via Quality — AND for the player: `player_cast` exposes the controlled body's actions in the `c` menu (targeted symmetrically; spawners ally offspring to you). The body is the build. |

**Counts:** PLAYER-REACHABLE 6 · AMBIENT-ONLY 9 · AUTO-AI-ONLY 3 (+ enemy-only abilities). = 18.

\* Sigils are listed reachable because you pick them up and position into their effects — but
the *firing* is automatic. See gap #3, the biggest design hole.

---

## Missing player verbs (the keybinding gap)

Public action methods (or deliberate designed actions) that exist but `interactive()` never
binds, so a human literally cannot trigger them:

1. ~~**Cast a sigil on demand**~~ — DONE: `SigilSystem.cast(game, index)` + the `c` key.
   The passive triggers remain; casting is the same effect at the player's chosen moment.
2. ~~**Forge / craft**~~ — DONE: `f` prompts which ability to forge; the interactive UI
   disengages the auto-forge so the choice is real. (Additive selection still automatic.)
3. ~~**Break down a sigil**~~ — DONE: `b` prompts which slotted sigil to melt.
4. ~~**Wait / skip turn**~~ — DONE: `.`/`5` off the stairs passes the turn (`game.wait()`),
   silently, so ambient systems can be watched (or hidden from) in place.
5. **Quest accept / decline / turn-in** — `QuestSystem.offer()` is reachable only transitively
   through the Keeper parley; no direct quest-management verb. `quests.py:286`
6. ~~**Explicit talk**~~ — DONE: `t` speaks — communion at the final boss, parley at a Keeper.

**Still open:** #5 (quest accept/decline/turn-in as a direct verb). Small; does not block
playing the build.

---

## Status

The original complaint ("a 4-verb roguelike wearing an 18-system coat") is addressed: a
human now waits, examines, casts, forges, and breaks down — the difference between
*witnessing* a build and *playing* it. What remains ambient (weather, flora, decay,
factions, quality) is ambient by design.
