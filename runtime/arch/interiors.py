"""Room-scale interior patterns — themed substructures (ARCHITECTURE_SPEC §3, room scale).

Substructures are NOT random decoration. Each is an Alexander pattern: a `context`
predicate over the center's own dynamics decides WHERE and WHEN it appears, and a
structure-preserving `solution` carves it. The harness IS the context:

  colonnade       a great hub needs rhythm, or it reads as a warehouse      -> I pillars
  sanctum         an orphan is precious BECAUSE it is enclosed; one door    -> + altar
  alcoves         a bridge is a way-place; it needs stillness beside flow   -> = shelves
  meeting stones  a place belonging to two communities needs a marked mid   -> : stones
  overgrowth      a recently-tended thought is alive; growth carpets it     -> , growth
  ruin            a long-untouched thought crumbles                          -> ' dust + o well

THE POINT (design-panel finding): each pattern used to carve its distinct place-type
into the SAME anonymous '#' wall, so a gallery, a sanctum and rubble all read as '#'.
Now each stamps a SIGNATURE FIXTURE in its signature arrangement, as real walkable
tiles, so a place LOOKS like what it is from the doorway — and the game clusters the
room's cache/keeper/creature onto that fixture (game.py) and lets you examine it in
the note's own words (game.examine). A place is a thing that belongs here and answers.

Patterns register into a catalogue (Appendix A idiom). Deterministic: seeded per
center id. Connectivity is Someone Else's Problem — the carver's `_ensure_connected`
runs AFTER this pass, so a fixture can never strand a tile (fixtures are walkable
anyway). Fixture glyphs are plain ASCII to honour curses/8-color/1-glyph.
"""
from __future__ import annotations

import random

from runtime.dungeon import FLOOR, WALL

GROWTH, DUST = ",", "'"
# fixtures: walkable, non-blocking scenery. one glyph = one kind of made thing.
PILLAR, ALTAR, STONE, SHELF, WELL = "I", "+", ":", "=", "o"
FIXTURES = frozenset((PILLAR, ALTAR, STONE, SHELF, WELL))
# how examine names each fixture, diegetically (the note's own words follow)
FIXTURE_NOUN = {PILLAR: "a worn pillar", ALTAR: "the altar", STONE: "a meeting-stone",
                SHELF: "a laden shelf", WELL: "an old well"}

CATALOGUE: list = []


def pattern(name: str, phrase: str):
    """Register a room-scale pattern: fn(center, tiles, w, h, rng) -> list[(x,y)]
    of the fixture tiles it placed (its signature feature); [] if it did not apply."""
    def reg(fn):
        CATALOGUE.append((name, phrase, fn))
        return fn
    return reg


def _cells(c) -> set:
    return set(map(tuple, c.footprint))


def _interior(c) -> list:
    """Deep-interior cells: every 4-neighbor is also in the footprint."""
    cells = _cells(c)
    return [t for t in sorted(cells)
            if all((t[0] + dx, t[1] + dy) in cells
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]


def _centroid(c):
    if c.pos is not None:
        return int(c.pos[0]), int(c.pos[1])
    cells = sorted(_cells(c))
    return cells[len(cells) // 2]


def _put(tiles, x, y, w, h, glyph):
    """Stamp a fixture onto open ground only; return True if placed."""
    if 0 <= x < w and 0 <= y < h and tiles[y][x] == FLOOR:
        tiles[y][x] = glyph
        return True
    return False


@pattern("colonnade", "a colonnade marches through it")
def _colonnade(c, tiles, w, h, rng):
    # context: a great hub; a large void without rhythm reads as a warehouse.
    # a regular file of pillars gives the hall its measure (a gallery you can SEE).
    if c.role != "hub" or len(c.footprint) < 30:
        return None
    cx, cy = _centroid(c)
    cols = [t for t in _interior(c)
            if (t[0] - cx) % 3 == 0 and (t[1] - cy) % 3 == 0
            and max(abs(t[0] - cx), abs(t[1] - cy)) >= 2]
    placed = [t for t in cols if _put(tiles, t[0], t[1], w, h, PILLAR)]
    return placed if len(placed) >= 2 else []


@pattern("sanctum", "an inner sanctum hides behind a single threshold")
def _sanctum(c, tiles, w, h, rng):
    # context: an orphan (grow renames placed orphans "discovery"). the precious is
    # precious because it is enclosed: a wall-ring with one gate, an ALTAR at the heart.
    if c.role not in ("orphan", "discovery") or len(c.footprint) < 9:
        return None
    cells = _cells(c)
    cx, cy = _centroid(c)
    r = 2 if len(cells) >= 30 else 1
    ring = [t for t in sorted(cells)
            if max(abs(t[0] - cx), abs(t[1] - cy)) == r]
    if len(ring) < 4:
        return None
    gate = rng.choice(ring)
    walled = sum(1 for (x, y) in ring if (x, y) != gate
                 and 0 <= x < w and 0 <= y < h and tiles[y][x] == FLOOR
                 and _set_wall(tiles, x, y))
    if walled < 3:
        return None
    if not _put(tiles, cx, cy, w, h, ALTAR):
        tiles[cy][cx] = ALTAR   # the heart may be non-floor; the altar defines it
    return [(cx, cy)]


def _set_wall(tiles, x, y):
    tiles[y][x] = WALL
    return True


@pattern("alcoves", "quiet alcoves give rhythm to its length")
def _alcoves(c, tiles, w, h, rng):
    # context: a bridge, a way-place; stillness beside the flow — SHELVES in the niches.
    if c.role != "bridge" or len(c.footprint) < 18:
        return None
    cells = _cells(c)
    xs = sorted({x for x, _ in cells})
    ys = sorted({y for _, y in cells})
    placed = []
    if len(xs) >= len(ys):
        for i, x in enumerate(xs[2:-2:3]):
            col = [y for (xx, y) in cells if xx == x]
            y = min(col) if i % 2 == 0 else max(col)
            if _put(tiles, x, y, w, h, SHELF):
                placed.append((x, y))
    else:
        for i, y in enumerate(ys[2:-2:3]):
            row = [x for (x, yy) in cells if yy == y]
            x = min(row) if i % 2 == 0 else max(row)
            if _put(tiles, x, y, w, h, SHELF):
                placed.append((x, y))
    return placed if len(placed) >= 2 else []


@pattern("meeting stones", "meeting stones stand where two worlds touch")
def _meeting_stones(c, tiles, w, h, rng):
    # context: multi-membership (the semilattice overlap); a marked middle both
    # communities know — four STONES ringing the center.
    if len(getattr(c, "members", ()) or ()) < 2 or len(c.footprint) < 16:
        return None
    if c.role in ("orphan", "hub"):
        return None
    cells = _cells(c)
    cx, cy = _centroid(c)
    stones = [(cx + 2, cy), (cx - 2, cy), (cx, cy + 2), (cx, cy - 2)]
    placed = [t for t in stones if t in cells and _put(tiles, t[0], t[1], w, h, STONE)]
    return placed if len(placed) >= 2 else []


@pattern("overgrowth", "living growth carpets the ground")
def _overgrowth(c, tiles, w, h, rng):
    # context: a recently-tended note (high activity); a live thought grows.
    # texture, not a focal fixture: it returns a sentinel so the catalogue records
    # the motif phrase without an anchor tile.
    if c.age < 0.7 or len(c.footprint) < 10:
        return None
    floor = [t for t in sorted(_cells(c)) if tiles[t[1]][t[0]] == FLOOR]
    if not floor:
        return None
    for (x, y) in rng.sample(floor, min(len(floor), max(2, len(floor) // 7))):
        tiles[y][x] = GROWTH
    return []   # applied, but no focal fixture


@pattern("ruin", "rubble and dust of a long-untouched thought")
def _ruin(c, tiles, w, h, rng):
    # context: a note untouched for ages; neglect crumbles — dust, and a dry WELL.
    if c.age > 0.15 or len(c.footprint) < 12:
        return None
    inner = _interior(c)
    floor = [t for t in sorted(_cells(c)) if tiles[t[1]][t[0]] == FLOOR]
    if not floor:
        return None
    for (x, y) in rng.sample(inner, min(len(inner), max(1, len(inner) // 8))):
        if 0 <= x < w and 0 <= y < h and tiles[y][x] == FLOOR:
            tiles[y][x] = WALL                              # rubble
    for (x, y) in rng.sample(floor, min(len(floor), max(2, len(floor) // 7))):
        if tiles[y][x] == FLOOR:
            tiles[y][x] = DUST
    cx, cy = _centroid(c)
    well = (cx, cy) if (cx, cy) in _cells(c) else floor[len(floor) // 2]
    _put(tiles, well[0], well[1], w, h, WELL)
    return [well] if tiles[well[1]][well[0]] == WELL else []


def apply_interiors(plan, tiles, w, h, seed="interior"):
    """Match every placed center against the catalogue; stamp each match's signature
    fixture and record (name, phrase, fixture_tiles) as c.motifs — the fixture tiles
    are the room's focal features, which game.py clusters contents onto."""
    for c in sorted(plan.placed(), key=lambda c: c.id):
        rng = random.Random(f"{seed}:interior:{c.id}")
        motifs = []
        for name, phrase, fn in CATALOGUE:
            feats = fn(c, tiles, w, h, rng)
            if feats is None:            # did not apply
                continue
            motifs.append((name, phrase, [(int(x), int(y)) for x, y in feats]))
        c.motifs = motifs
