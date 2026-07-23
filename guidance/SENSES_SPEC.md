<!-- Status: Legacy (pre-Berlin) | Written: 2026-06-29 | Berlin compliance not yet applied to this domain -->
# Senses contract — perception by capacity 

The perception core lives in `runtime/senses.py`. Read it first. Two layers:
- **detection/exploration** — locating senses (SOUND, SMELL) give a *position*, no identity →
  the engine walks the creature toward the lead to get a look;
- **identification** — identifying senses (SIGHT+line-of-sight, TOUCH when adjacent, or the
  supernatural LIFE/MIND/MAGIC) confirm *what* it is → only an identified **hostile actor**
  is a target. Fire is perceived as a hazard, never a target.

Perception is **opt-in**: active only when a `SenseField` system is registered. Build/verify
with `Game(load_manifest("examples/world.json"), systems=[SenseField(), ...])`. Work in
`/mnt/workspace/output/vaultcrawl` (cd every bash; cwd does NOT persist). Pure stdlib,
deterministic.

## Core API (in `runtime/senses.py`)

- Modalities: `SIGHT, SOUND, SMELL, TOUCH, LIFE, MIND, MAGIC`. Identifying = SIGHT(LOS)/TOUCH(adj)/LIFE/MIND/MAGIC; locating = SOUND/SMELL.
- `SenseProfile(ranges: dict)` — `{modality: range}`. `register_profile(name, profile)`.
- `profile_name_for(actor)` (policy, already written): player→`"player"`; wild→`"scent_hound"`;
  by monster glyph `h→"life_wraith"`, `e→"echolocator"`, `b→"scent_hound"`, `s→"mind_seer"`,
  else `"sighted"`. **You implement & register the named profiles it points at** (unregistered
  names fall back to `"sighted"`, which exists).
- `perceive(game, observer) -> Perception` (cached per `game.turn`). `Perception` has
  `.identified` (actors recognized), `.leads` ([(x,y,salience)]), `.hazards` ([(x,y)]), and
  `.hostiles(game, observer)`, `.nearest_hostile(game, observer)`, `.best_lead(observer)`.
- `has_los(game, x0,y0,x1,y1)`, `is_alive(a)`, `is_minded(a)`, `is_magical(a, game)`.
- Engine already: `sense.nearest_hostile` is perception-limited when SenseField is present;
  `enemies_act` runs `investigate_step` when a brain has no identified target. So a creature
  that only *hears* you walks toward the noise; gets LOS/touch; *then* engages.

`emits` rules (what the supernatural senses bite on): **LIFE** = `is_alive` (everything
except glyph `g`/`c` machines and `h`/`e` spectral); **MIND** = `is_minded` (player, bosses,
tier≥4, wild predators); **MAGIC** = `is_magical` (spectral `h`/`e`, or the player while
holding sigils). So a life-wraith is blind to golems; a mind-seer is blind to mindless swarm.

## Agent A — `runtime/creatures.py` (+ `tests/test_creatures.py`)

Define and `register_profile(...)` these `SenseProfile`s (tune ranges sensibly):
- **`echolocator`** (the `e` echo — blind): hears far, no sight; identifies only by touch.
  e.g. `{SOUND: 16, TOUCH: 1}`.
- **`scent_hound`** (the `b` beast, and all wildlife): strong smell, weak eyes.
  e.g. `{SMELL: 10, SOUND: 8, SIGHT: 4, TOUCH: 1}`.
- **`life_wraith`** (the `h` shade): senses the living through walls, no ordinary sight.
  e.g. `{LIFE: 10, SOUND: 6, TOUCH: 1}`.
- **`mind_seer`** (the `s` scribe): feels thought at range; modest eyes.
  e.g. `{MIND: 10, SIGHT: 5, TOUCH: 1}`.

`tests/test_creatures.py` (run `python3 -m tests.test_creatures`): on a real
`Game(..., systems=[SenseField()])`, assign profiles by giving actors the right glyph (so
`profile_name_for` selects them) or by `senses.PROFILES`-lookup, and assert capacity matters:
- a `life_wraith` identifies a *living* player even with NO line-of-sight (place a wall between,
  or put it out of SIGHT range but within LIFE range) — while a plain `sighted` creature at the
  same spot does NOT identify; and the wraith does NOT identify a golem (glyph `g`, not alive).
- an `echolocator` does NOT identify the player by sight at range (no SIGHT), but a nearby
  `noise` (`game.emit("noise", pos=..., volume=...)`) gives it a lead.
- a `mind_seer` identifies the player (minded) but not a mindless grazer at the same range.
Print `OK`, deterministic. Edit ONLY your two files.

## Agent B — `runtime/sense_scenario.py`

A narrated, deterministic showcase (model it on `runtime/scenario.py`). `import runtime.creatures`
at top so profiles register. Each set-piece builds a fresh `Game(..., systems=[SenseField(), ReactionSystem()])`,
stages walls/positions/`reactions.props`/noises, runs the REAL `perceive`/`enemies_act`, and
judges from live state with ✓/✗. Demonstrate:
1. **Lose & investigate**: a sighted monster identifies the player (LOS), the player breaks
   LOS behind a wall → it no longer identifies but heads to the last-seen/noise lead (it does
   NOT bee-line through the wall).
2. **Blind by sound**: an `echolocator` can't identify by sight; a `noise` gives a lead, it
   closes in, and identifies by TOUCH when adjacent → then engages.
3. **Don't attack the fire**: with fire between it and the player, a sighted creature targets
   the *player* (identified hostile), lists the fire only in `perception.hazards`, and never
   issues an attack toward the fire tile (no actor there).
4. **Through walls (supernatural)**: a `life_wraith` identifies the player across a wall (LIFE)
   and homes in, while a `sighted` monster at the same spot only has a stale lead.
5. **Selective mind-sense**: a `mind_seer` identifies the player but not a mindless construct
   at equal range.
6. **Capacity comparison**: same staged situation (player hidden, a noise made) → sighted vs
   echolocator vs life_wraith produce different reactions.

End with OVERALL PASS only if all ✓; exit 0. If something can't be staged, pass the rest and
REPORT it. Edit ONLY `runtime/sense_scenario.py`. Mark task in_progress; do NOT mark completed.

Report: profiles registered / ranges, the sense helpers used, and integrator notes.
