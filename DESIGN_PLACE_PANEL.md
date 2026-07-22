# Sense-of-Place Design Panel — Build Plan

_Convened 2026-07-02 after the verdict: "the feeling of place is garbage and absent."_
_Panel: CoQ level designer, Cogmind UX, terrain modder, ASCII env-artist, atmosphere designer.
 35 fixes proposed, 9 survived adversarial review._

## Thesis
A place is felt when the grid shows you a THING that belongs here, that you can approach, that
answers you in this note's own voice, and whose neighbors (cache, keeper, marginalia, the
creature that guards it) cluster around it so the room reads as one center with a purpose. Every
panel converges on the same gap from a different side: the generative layer already KNOWS what
each place is (interiors.py records c.motifs, room_notes binds the note, the corpus can speak,
caches/creatures/marginalia already spawn there) but spends that knowing on invisible attributes
(a bold/dim glow the fog overwrites) and ephemeral log-prose (a manual recited on entry), so
nothing durable reaches the retina or anchors the eye. The fix is a rendering and content RE-
BUDGET, not more generation and not more color: convert each interior pattern's anonymous carved
walls into a small vocabulary of pure-ASCII SCENERY glyphs placed in the pattern's signature
arrangement (colonnade -> a row of pillars, sanctum -> one altar at the enclosed heart, meeting-
stones -> markers at the four stones), make that scenery EXAMINABLE with a line woven from the
note's own corpus, cluster the room's existing cache/keeper/creature onto its scenery so the
feature is inhabited not decorative, and give the standing world a voice over TIME by narrating
real, reachable sim-events near you (a predator's kill you can walk to, weather at the map edge)
through the already-principled senses radius. Same robust world; now it has things in it, those
things mean something, they speak in the note's words, and the world acts on you while you stand
still. That is what turns data into somewhere you are standing.

## Core problem
The robust world lives entirely in the data model and the scrolling log; almost none of it
reaches the persistent grid the eye actually parses. Interior patterns carve six semantically
distinct place-types into the SAME anonymous '#' wall and record what they are only as motif-
phrases the log recites once on entry. So the map is an ocean of identical '.' inside identical
'#', place-identity is a log line that scrolls away, and the one felt-architecture attempt (a
brightness glow) is a channel too weak to perceive and is then overwritten by the fog dim-pass.
There is nothing durable IN a place to see, approach, or be answered by, so no frame reads as a
location.

## Status (2026-07-02)

- **DONE — Step 1** (scenery layer): interiors stamp signature ASCII fixtures (`I` pillar,
  `+` altar, `:` stone, `=` shelf, `o` well) as walkable tiles; motifs carry fixture coords;
  site-cache fmt bumped to 3.
- **DONE — Step 2** (examinable voice): standing at a fixture speaks a line woven from the
  room note's own corpus (`game._examine_fixture`).
- **DONE — Step 3** (anchor contents): `spot_for` biases guardians beside the fixture;
  `caches.py` anchors caches beside it (90/104 on the Notebook world).
- **DONE — Step 4** (figure-ground bug): walls render normal white (figure), floor dim, road
  dim-blue; middot dither and heart-glow removed.
- **DONE — Step 6a** (cut the manual): arrival is name + one woven voice line; room entry is
  one quiet line folding the truest motif.
- **TODO — Step 5** (ambient narrator from real reachable state) & **Step 6b** (wait-to-
  listen). Acceptance test: every ambient line must point at a reachable thing or it's a
  lying screen.

## Build plan

### Step 1 — medium (dep: none)
**What:** Add a tile-level SCENERY layer. Give interiors.py a small pure-ASCII fixture
vocabulary (I pillar, + altar, : marker-stone, = shelf/case, o well/font) and have each pattern
stamp its signature fixture in its signature arrangement INTO self.level.tiles instead of (or
alongside) carving anonymous WALL: colonnade -> row of I; sanctum -> one + at the enclosed
center; meeting-stones -> : at the four cardinal stones; alcoves -> = in each niche;
overgrowth/ruin keep , and '. Register these glyphs as walkable non-blocking terrain in the
walkable/spawn-skip check. Because they are real tiles they flow through play.py's existing
'.#\'' tint/glow path and wear their region.
**Why place:** This is the one un-tried, non-cosmetic lever every panel converged on: the grown
places are empty of THINGS. Reusing the pattern's own arrangement (already computed) means a
gallery LOOKS like a gallery from the doorway, using the SAME generative signal, not a new one.
Tile-level (not a play.py-only glyph) keeps it inside the proven render path and off the
collision list.

### Step 2 — small (dep: step 1)
**What:** Make scenery EXAMINABLE in the note's own voice. In game.examine(), when the player is
on or adjacent to a scenery tile, emit ONE line woven from that room's note corpus via the
existing marginalia.weave() machinery, prefixed diegetically to the fixture ('The altar holds:
<woven line>'). Dedupe against any marginalia " already spawned in the same room so the note is
never quoted twice.
**Why place:** A pillar you can only look past is decoration; a pillar that answers 'x' with the
note's own words is a place. This is the survival condition the CoQ/atmosphere panels set and
the fix that separates this from the rejected cosmetic pass. Reuses weave() (proven), adds no
new corpus machinery.

### Step 3 — medium (dep: step 1)
**What:** ANCHOR the room's existing contents onto its scenery. Bias cache placement (caches.py
on_floor_enter) toward the room's fixture tile when one exists; place the district Keeper and
the room's guardian/territorial creature adjacent to the signature fixture rather than at a
random room tile. No new entities, just placement bias toward the center.
**Why place:** Turns a lone glyph into an inhabited center (Alexander's strong center): the
altar has a keeper standing by it, the shelf holds the cache, the stones ring a creature.
Clustering is what makes the eye read one room as one purposeful place instead of scattered
noise, and it makes the fixture matter to play, not just to the eye.

### Step 4 — small (dep: none)
**What:** Fix figure-ground as a correctness bug (NOT sold as the place-fix). In play.py
palette: wall '#' -> NORMAL white (currently DIM, same as floor); floor '.' stays dim; give road
'░' a real palette entry at a dim, unified low value (currently none, so it renders brightest).
Kill the global 1-in-9 middot dither (play.py:232) so negative space returns. Preserve region
HUE on all capped ground so districts stay distinct.
**Why place:** The palette provably paints wall and floor identically while the heavy road out-
contrasts both, so the eye is drawn to roads first: inverted figure-ground that erases the
buildings the generator worked to make figures. This is a defect fix and a precondition for any
focal point to land; it must ship as one small correctness change, not be oversold.

### Step 5 — medium (dep: none)
**What:** Add an ambient-event NARRATOR backed only by durable, reachable world-state. Give
Weather/Fauna/Decay a budget of ONE sensory log line per N turns, fired only when a perceivable
event happens within the senses radius, gated to at most one ambient line/turn, routed through
sight/sound/smell so smell-only reads differently. Every line MUST point at a real persistent
thing (an actual corpse, an actual charged tile) so walking toward 'a wet struggle to the east'
reliably finds it. Include a bearing plus a note-derived proper noun.
**Why place:** This targets the missing axis: located-in-TIME, the world acting near you while
you stand still. It uses an un-fatigued channel (the log) fed by real state through the
principled senses radius. Survives ONLY if every line is a pointer to a reachable consequence; a
line with no reachable thing is worse than silence (a lying screen).

### Step 6 — small (dep: step 5)
**What:** Cut the manual-voice exposition and make waiting LISTEN. Move the static rules ('7
settled hearts...', 'Settled ground: nothing hostile...') out of the entry log into the
sidebar/help. On entry, keep at most the place name plus ONE woven voice line (deduped vs
marginalia). In wait(), raise the narrator's fire chance and prefer distant/faint perceptions
drawn from real offscreen state (nearest offscreen fauna action + bearing, weather at map edge,
nearest friction wall's region name).
**Why place:** The threshold is the one high-attention moment and it is currently spent on
rules-text; waiting is the verb that should let a place breathe and currently says nothing. This
is the acceptance test for step 5's narrator: if wait-to-listen can name a direction and a real
proper noun, the narrator is real; if it emits reworded telemetry ('Weather: mist. Wild: 3'), it
dies with the last pass.

## Stop doing
- Stop routing place-identity through ANSI color and brightness attributes. The bold/dim heart-
  glow is a channel the eye cannot resolve on an 8-color monospace grid and the fog dim-pass
  overwrites it anyway. No more gradient/tier/friction-border passes as the 'place fix' - the
  user already called that family garbage.
- Stop delivering place-identity as log prose the player must read. A woven line scrolls away;
  the 'not anywhere' deficit lives in the persistent viewport it never touches. Voice is a
  complement to on-grid substance, never the substitute.
- Stop opening with a manual. The entry log spending its one high-attention moment on mechanics
  recitation ('waiting is rest, and the door leads below') is the exact inversion of arrival.
  Rules go to the sidebar/help.
- Abandon the non-ASCII fixture glyphs from the raw proposal (the sign-of-intersection / omega /
  almost-equal / pi / capital-psi / white-circle set) and any glyph that collides with taken
  symbols (heart-landmark, cache-square, and the message-log dagger prefix). They fight curses,
  8-color, and terminal width the codebase otherwise honors. Use plain ASCII: I + : = o.
- Stop treating subtractions as fixes. Killing the middot dither or flattening the palette CALMS
  the screen but manufactures no presence; quiet ground with nothing to look AT is still
  nowhere. Every cleanup must ship alongside something the eye lands ON.
- Stop firing ambient/flavor lines for events with no reachable consequence. A narrator on a
  timer with decorative lines is wallpaper the user will smell as fake, and a line that drifts
  from world-state (says 'kill' but the corpse is already cleaned) is a lying screen, the
  cardinal place-breaker.
- Do NOT re-glyph the carved walls without giving them behavior. A pillar-shaped '#' that you
  cannot examine and that no creature/cache belongs to is just the rejected cosmetic layer
  wearing a new letter.
