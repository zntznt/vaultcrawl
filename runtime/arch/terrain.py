"""Biome terrain + wild structures — the sprawl BETWEEN buildings is world, not void.

The surface was 96% empty floor. The first fix (per-tile sprinkle) just made TV snow:
density without composition is still noise. Real wilderness has SHAPE — groves and
thickets and debris-fields in clumps, with clearings between, and LANDMARKS that break
the horizon and give the eye somewhere to go. So this layer:

  1. Biome PATCHES: each region's element grows a handful of organic blobs (a reed-bed,
     a slag-field, a fern-grove) with open ground between them — clusters, not static.
  2. Wild STRUCTURES: your unlinked orphan-notes become solitary landmarks strewn across
     the wild (a standing stone, a cairn, a wreck, a shrine), each a real place you find
     while travelling and can examine in its own words. 85 homeless notes become 85
     things to discover instead of scattered specks.

Deterministic, pure stdlib. Terrain glyphs are walkable textured ground; structure
glyphs are landmarks (recorded so the game can voice/anchor them, like interior fixtures).
"""
from __future__ import annotations

import random
from collections import deque

from runtime.dungeon import FLOOR, WALL

# biome terrain (walkable textured ground)
SCRUB, DEBRIS = '"', '`'
# wild structures (landmarks in the between) — plain ASCII, distinct from interior fixtures
CAIRN, WRECK, SHRINE, MONOLITH = "A", "X", "H", "V"
WILD_STRUCT = {CAIRN: "a lonely cairn", WRECK: "a rusted wreck",
               SHRINE: "a wayside shrine", MONOLITH: "a leaning monolith"}

# element -> patch feature glyph, and how thick/large its patches are
BIOME_PATCH = {
    "charged":   (DEBRIS, 0.55),   # slag-fields
    "wet":       (SCRUB, 0.70),    # dense reed-beds
    "corrosive": (DEBRIS, 0.45),   # salt-crust
    "sacred":    (SCRUB, 0.60),    # fern-groves
    "flammable": (SCRUB, 0.65),    # tinder-scrub
    "frozen":    (DEBRIS, 0.40),   # rime
    "inert":     (DEBRIS, 0.30),
}


def _region_of_all(level, cell_region):
    """Flood region ids to every open floor tile (nearest-anchor Voronoi)."""
    w, h, tiles = level.w, level.h, level.tiles
    region_of = dict(cell_region)
    q = deque(region_of)
    while q:
        x, y = q.popleft()
        rid = region_of[(x, y)]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if (0 <= n[0] < w and 0 <= n[1] < h and n not in region_of
                    and tiles[n[1]][n[0]] == FLOOR):
                region_of[n] = rid
                q.append(n)
    return region_of


def _grow_patch(tiles, biome, cx, cy, size, glyph, rng, region_of, rid, w, h):
    """Flood a soft organic blob of `glyph` into the biome OVERLAY (not level.tiles,
    so spawning stays biome-independent and cache-deterministic)."""
    if not (0 <= cx < w and 0 <= cy < h) or tiles[cy][cx] != FLOOR:
        return 0
    filled, frontier = 0, [(cx, cy)]
    seen = {(cx, cy)}
    while frontier and filled < size:
        x, y = frontier.pop(rng.randrange(len(frontier)))
        if (tiles[y][x] == FLOOR and region_of.get((x, y)) == rid
                and (x, y) not in biome):
            biome[(x, y)] = glyph
            filled += 1
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if (n not in seen and 0 <= n[0] < w and 0 <= n[1] < h
                    and rng.random() < 0.7):
                seen.add(n)
                frontier.append(n)
    return filled


def _weighted(feats, r):
    """Pick a feature glyph from [(glyph, weight, noun)] by weight, or None."""
    total = sum(w for _g, w, _n in feats)
    if total <= 0:
        return None
    pick = r.random() * total
    acc = 0.0
    for g, w, _n in feats:
        acc += w
        if pick <= acc:
            return g
    return feats[-1][0]


def _near_field(level, seeds, reach):
    """Chebyshev distance (capped at `reach`) from every open tile to the nearest
    seed (a building cell) — a cheap BFS. Used to fill the SETTLED ground densely
    and let it taper into the sparse deep wild."""
    from collections import deque
    w, h, tiles = level.w, level.h, level.tiles
    dist = {}
    q = deque()
    for s in seeds:
        dist[s] = 0
        q.append(s)
    while q:
        x, y = q.popleft()
        d = dist[(x, y)]
        if d >= reach:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (0 <= n[0] < w and 0 <= n[1] < h and n not in dist
                        and tiles[n[1]][n[0]] != WALL):
                    dist[n] = d + 1
                    q.append(n)
    return dist


def paint_biomes(level, cell_region, region_env, building_cells=(), seed="biome"):
    """Strew each region's ENVIRONMENT across its ground as clumped feature-patches.
    Density is HIGH on settled ground (near buildings) and TAPERS into the deep wild,
    so where you actually are reads as a full place while true travel-distance stays
    open. `building_cells` are the perimeter/interior tiles of the settlements.
    Returns (overlay {(x,y):glyph}, region_of); level.tiles untouched."""
    from .blocks import Environment
    w, h, tiles = level.w, level.h, level.tiles
    region_of = _region_of_all(level, cell_region)
    biome: dict = {}
    rng = random.Random(f"{seed}:patches")

    # ---- layer A: SIGNATURE FIELDS (the meso scale sameyness lacked) ----
    # A region is recognized by its one big thing: THE reed-marsh, THE slag-field,
    # a large contiguous body of the region's head feature with open country around
    # it. Small mixed patches alone read as confetti no matter which glyphs they use.
    cells_of: dict = {}
    for c, rid in region_of.items():
        cells_of.setdefault(rid, []).append(c)
    for rid in sorted(cells_of, key=str):
        cells = sorted(cells_of[rid])
        env = region_env.get(rid) or Environment(["inert"])
        feats = sorted(env.features(), key=lambda f: -f[1])
        if not feats:
            continue
        primary = feats[0][0]
        n_sig = max(2, len(cells) // 900)
        for i in range(n_sig):
            x, y = cells[rng.randrange(len(cells))]
            # the odd field is the SECOND voice, so big shapes vary too
            g = primary if (i % 3) or len(feats) < 2 else feats[1][0]
            _grow_patch(tiles, biome, x, y, rng.randint(40, 120), g,
                        rng, region_of, rid, w, h)

    # ---- layer B: fine texture, with real CONTRAST between regions ----
    # density spans austere to thick (a bare gravel plain is an identity too);
    # near buildings the ground is thick with the district's stuff; the deep wild
    # tapers to open travel-country.
    _DENSITY = {"dense": 0.95, "broken": 0.75, "linear": 0.6,
                "open": 0.4, "scattered": 0.22}
    REACH = 16
    near = _near_field(level, set(building_cells), REACH) if building_cells else {}
    step = 3          # fine grid -> dense feature coverage where it matters
    for gy in range(1, h, step):
        for gx in range(1, w, step):
            x = gx + rng.randint(-1, 1)
            y = gy + rng.randint(-1, 1)
            if not (0 <= x < w and 0 <= y < h) or tiles[y][x] != FLOOR:
                continue
            rid = region_of.get((x, y))
            env = region_env.get(rid) or Environment(["inert"])
            base = _DENSITY.get(env.tendency(), 0.6)
            # settled ground fills nearly full; tapers hard in the deep wild
            d = near.get((x, y), REACH)
            fill = max(base, 0.9) if d <= 2 else base * (1.0 - 0.7 * d / REACH)
            if rng.random() > fill:
                continue                      # a clearing — leave it open
            glyph = _weighted(env.features(), rng)
            if not glyph:
                continue
            size = rng.randint(3, 8)   # smaller, more numerous clumps read denser
            _grow_patch(tiles, biome, x, y, size, glyph, rng, region_of, rid, w, h)

    # ---- layer C: GRAIN — bare ground is never a void ----
    # clearings stay open (that is their job) but the floor itself gets a faint,
    # sparse grain so open country reads as ground, not as blank paper. Rendered
    # dim; it is texture, not a feature.
    grain = random.Random(f"{seed}:grain")
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if tiles[y][x] == FLOOR and (x, y) not in biome and grain.random() < 0.10:
                biome[(x, y)] = "'"
    return biome, region_of


def region_map_only(level, cell_region):
    """Just the Voronoi region map (for cache-loaded worlds whose tiles are already
    biomed): flood region ids to every open/textured tile."""
    w, h, tiles = level.w, level.h, level.tiles
    from runtime.dungeon import WALL
    region_of = dict(cell_region)
    q = deque(region_of)
    while q:
        x, y = q.popleft()
        rid = region_of[(x, y)]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if (0 <= n[0] < w and 0 <= n[1] < h and n not in region_of
                    and tiles[n[1]][n[0]] != WALL):
                region_of[n] = rid
                q.append(n)
    return region_of


def place_wild_structures(level, region_of, orphan_notes, reserved, seed="wild"):
    """Strew orphan-notes across the wild as solitary landmarks. Returns
    (struct_glyph {(x,y):glyph}, struct_note {(x,y):note_id}) overlays so the game
    draws/voices each without mutating level.tiles (keeps spawns cache-deterministic).
    `reserved` are tiles already taken (player, gates, actors)."""
    w, h, tiles = level.w, level.h, level.tiles
    rng = random.Random(f"{seed}:structs")
    open_tiles = [(x, y) for y in range(h) for x in range(w)
                  if tiles[y][x] == FLOOR and (x, y) not in reserved]
    rng.shuffle(open_tiles)
    glyphs, notes, used = {}, {}, []
    for nid, node in orphan_notes:
        age = node.get("activity", 0.5)
        glyph = (WRECK if age <= 0.2 else SHRINE if age >= 0.8
                 else CAIRN if rng.random() < 0.5 else MONOLITH)
        spot = None
        for t in open_tiles:
            if all(abs(t[0] - ux) + abs(t[1] - uy) > 6 for ux, uy in used):
                spot = t
                break
        if spot is None:
            break
        used.append(spot)
        open_tiles.remove(spot)
        glyphs[spot] = glyph
        notes[spot] = nid
    return glyphs, notes
