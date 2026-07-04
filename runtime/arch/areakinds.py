"""Area kinds — a region is not just a texture, it is a KIND OF PLACE.

The design blocks (blocks.py) give a region its texture and voice. An AREA KIND
gives it its STRUCTURE and RULES: a labyrinth carves maze walls and closes sight, a
grove thickens the canopy, a necropolis stamps tombs and lets the dead stir, a
market crowds people you can talk to. Kinds are the pluggable seam — adding the
tenth kind of place is one entry in KINDS plus (optionally) one small shape function,
never a surgery.

A region picks its kind by a NATURE-BIASED ROLL: its anchor note's graph signals set
the weights (a dense hub leans market, a dead-end orphan leans labyrinth), then a
seeded roll picks — so meaning shapes the odds and the roll adds surprise, and the
same vault always yields the same kinds.

Each kind declares four things, all optional (a kind that sets none is a plain
region, exactly today's behaviour):
  favors  : extra design-block names folded into the region's environment (flavor)
  shape   : fn(tiles, cells, rng, w, h) -> None  — a LAYOUT transform on level.tiles
            (maze walls, flooding, tomb-stamps). Must keep the region connected;
            settle/carve run _ensure_connected afterwards as a backstop regardless.
  sight   : additive sight-radius modifier when the player stands in this kind
  voice   : extra ambient lines this kind murmurs

Determinism: every shape transform takes a seeded rng; no wall-clock, no globals.
"""
from __future__ import annotations

import random

from runtime.dungeon import FLOOR, WALL


# --------------------------------------------------------------------------- #
# shape transforms (layout on level.tiles) — each keeps the region connected
# --------------------------------------------------------------------------- #

def _maze(tiles, cells, rng, w, h):
    """LABYRINTH: stipple walls on a sparse lattice so the region reads as a maze to
    get lost in — but leave every OTHER lattice column/row open, so it stays a
    labyrinth you can thread, not a solid block. Only touches interior floor of the
    region (never its border), so the region can't be sealed off from the world."""
    cellset = set(cells)

    def interior(t):
        return all((t[0] + dx, t[1] + dy) in cellset
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    for (x, y) in cells:
        if not interior((x, y)) or tiles[y][x] != FLOOR:
            continue
        # walls on a 2-grid, with gaps: a hedge-maze lattice, never a solid fill
        if x % 2 == 0 and y % 2 == 0 and rng.random() < 0.72:
            tiles[y][x] = WALL


def _flood(tiles, cells, rng, w, h):
    """FLOODED: a few deep pools (impassable dark water) you route AROUND, with dry
    land between. Water is WALL on the tile map (so pathing routes around it) but the
    overlay/biome will paint it wet — it reads as water, behaves as an obstacle."""
    cellset = set(cells)

    def interior(t):
        return all((t[0] + dx, t[1] + dy) in cellset
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    interior_cells = [c for c in cells if interior(c)]
    if not interior_cells:
        return
    for _ in range(max(1, len(interior_cells) // 500)):
        cx, cy = interior_cells[rng.randrange(len(interior_cells))]
        # a soft blob of water
        body, frontier, seen = 0, [(cx, cy)], {(cx, cy)}
        size = rng.randint(20, 60)
        while frontier and body < size:
            x, y = frontier.pop(rng.randrange(len(frontier)))
            if (x, y) in cellset and interior((x, y)) and tiles[y][x] == FLOOR:
                tiles[y][x] = WALL
                body += 1
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, y + dy)
                if n not in seen and rng.random() < 0.75:
                    seen.add(n)
                    frontier.append(n)


# --------------------------------------------------------------------------- #
# the registry — add a kind here; that is the whole change
# --------------------------------------------------------------------------- #

KINDS = {
    # the default: a plain region (no shape, no rule change) — texture only
    "wilds": dict(favors=[], shape=None, sight=0, voice=[]),

    "labyrinth": dict(
        favors=["archive"], shape=_maze, sight=-4,
        voice=["The way forks, and forks again.",
               "You have passed this turning before. Or one like it.",
               "Walls lean close; the path remembers no one."]),

    "grove": dict(
        favors=["garden"], shape=None, sight=-2,     # thickets already occlude
        voice=["Green closes overhead.", "Something rustles and goes still.",
               "The canopy breathes without wind."]),

    "flooded": dict(
        favors=["wet"], shape=_flood, sight=0,
        voice=["Black water lies where the floor should be.",
               "Your reflection wavers and is gone.",
               "The drowned rooms keep their own counsel."]),

    "necropolis": dict(
        favors=["catacomb"], shape=None, sight=-1,
        voice=["The dead are filed here, and patient.",
               "Dust holds the shape of who knelt last.",
               "Something remembers being read."]),

    "market": dict(
        favors=["hub"], shape=None, sight=0,
        voice=["Voices cross, too many to follow.",
               "The square never quite empties.",
               "Trade and rumor, rumor and trade."]),
}


# --------------------------------------------------------------------------- #
# nature-biased roll — meaning sets the weights, a seeded roll picks
# --------------------------------------------------------------------------- #

def _weights(node: dict) -> dict:
    """A region's anchor-note graph signals set the ODDS of each kind. Every kind
    keeps a floor weight so any place can surprise you."""
    role = node.get("role", "cluster")
    degree = node.get("degree", 0)
    activity = node.get("activity", 0.5)     # 0=old .. 1=fresh (mtime-derived)
    bridge = node.get("bridge", False)
    w = {k: 1.0 for k in KINDS}              # everything is possible
    w["wilds"] = 3.0                         # ...but plain wilds is the common ground
    if role == "hub" or degree >= 6:
        w["market"] += 6.0                   # a crossroads of links -> a crowded place
    if role == "orphan" or degree <= 1:
        w["labyrinth"] += 5.0                # a note bound to nothing -> get lost
    if activity <= 0.25:
        w["necropolis"] += 5.0               # old, quiet -> the dead are filed here
    if bridge:
        w["flooded"] += 2.0                  # a span between -> water between
        w["market"] += 2.0
    # tag-ish leanings via role fallbacks
    if role == "leaf":
        w["grove"] += 4.0                    # a terminal green shoot -> a grove
    return w


def kind_for(region: dict, node: dict, seed) -> str:
    """Pick a region's area kind by a deterministic nature-biased roll."""
    weights = _weights(node or {})
    rng = random.Random(f"{seed}:areakind:{region.get('id', '')}")
    total = sum(weights.values())
    pick = rng.random() * total
    acc = 0.0
    for name in KINDS:            # KINDS insertion order is stable -> deterministic
        acc += weights.get(name, 0.0)
        if pick <= acc:
            return name
    return "wilds"


def favors(kind: str) -> list:
    return KINDS.get(kind, KINDS["wilds"]).get("favors", [])


def voice(kind: str) -> list:
    return KINDS.get(kind, KINDS["wilds"]).get("voice", [])


def sight_mod(kind: str) -> int:
    return KINDS.get(kind, KINDS["wilds"]).get("sight", 0)


def shape(kind: str):
    return KINDS.get(kind, KINDS["wilds"]).get("shape", None)
