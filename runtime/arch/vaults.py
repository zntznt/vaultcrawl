"""Declarative room templates — hand-authored ASCII rooms with glyph substitution.

Each vault is an ASCII map with glyph substitution rules. The carver places
matching templates into rooms during dungeon generation. Templates are selected
by tag matching (room role + region element) and weighted randomly.

File format (vaults.json): list of vaults, each with:
  - name: unique ID
  - tags: ["hub", "charged", etc.] — must match room/region properties
  - weight: selection weight among candidates
  - min_area: minimum room area required for this template
  - map: ASCII art grid (list of strings, one per row)
  - subst: dict of glyph -> [[replacement, weight], ...] (weighted substitution)
"""
from __future__ import annotations

import json
import os
import random

# glyph mapping: vault glyph -> level tile
_GLYPH_MAP = {
    "#": "#",  # wall
    ".": ".",  # floor
    "~": "W",  # water (rendered as overlay glyph)
    "+": "+",  # door
    "{": "I",  # pillar (fixture)
    "}": "=",  # shelf (fixture)
    "@": ".",  # vault exit / connection point
    "*": ".",  # special / loot spot
    "X": "#",  # template wall (always wall unless overridden)
}


def _load_vaults() -> list[dict]:
    """Load vault templates from the JSON data file."""
    path = os.path.join(os.path.dirname(__file__), "arch", "vaults.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return _BUILTIN_VAULTS


def try_place_vaults(level, placed_centers, region_data, seed: str):
    """Attempt to place matching vaults into rooms of a generated level.
    Returns number of vaults placed (for logging)."""
    vaults = _load_vaults()
    if not vaults:
        return 0
    rng = random.Random(f"{seed}:vaults")
    placed = 0

    for i, room in enumerate(level.rooms):
        role = region_data.get(i, {}).get("role", "")
        element = region_data.get(i, {}).get("element", "")
        tags = [role, element]
        # find matching vaults for this room
        candidates = [v for v in vaults
                      if v.get("min_area", 0) <= room.w * room.h
                      and any(t in v.get("tags", []) for t in tags)]
        if not candidates:
            continue
        v = rng.choices(candidates, weights=[v.get("weight", 10) for v in candidates], k=1)[0]

        # place the vault into the room, centered
        vmap = v.get("map", [])
        if not vmap:
            continue
        vh, vw = len(vmap), max(len(row) for row in vmap)
        if vh > room.h or vw > room.w:
            continue

        ox = room.x + (room.w - vw) // 2
        oy = room.y + (room.h - vh) // 2
        subst = v.get("subst", {})

        for vy, row in enumerate(vmap):
            for vx, ch in enumerate(row[:vw]):
                tx, ty = ox + vx, oy + vy
                if not (0 <= tx < level.w and 0 <= ty < level.h):
                    continue
                if ch in subst:
                    # weighted substitution
                    opts = subst[ch]
                    weights = [w for _, w in opts]
                    pick = rng.choices([r for r, _ in opts], weights=weights, k=1)[0]
                    if pick:
                        level.tiles[ty][tx] = _GLYPH_MAP.get(pick, pick)
                else:
                    level.tiles[ty][tx] = _GLYPH_MAP.get(ch, ".")

        placed += 1

    return placed


# built-in templates (always available even without the JSON file)
_BUILTIN_VAULTS = [
    {
        "name": "temple_alcove",
        "tags": ["hub", "charged", "sacred", "flammable", "frozen", "wet", "corrosive", "inert", "cluster", "leaf", "bridge", "orphan"],
        "weight": 15,
        "min_area": 24,
        "map": [
            "XXXXX",
            "X...X",
            "X.{.X",
            "X...X",
            "XXXXX"
        ],
        "subst": {
            "X": [["#", 5], [".", 1]],
            "}": [["=", 3], [".", 1]]
        }
    },
    {
        "name": "chamber_with_pillars",
        "tags": ["hub", "charged", "sacred", "flammable", "frozen", "wet", "corrosive", "inert", "cluster"],
        "weight": 10,
        "min_area": 30,
        "map": [
            "XXXXXXX",
            "X.....X",
            "X.{.}.X",
            "X.....X",
            "X.{.}.X",
            "X.....X",
            "XXXXXXX"
        ],
        "subst": {
            "X": [["#", 8], [".", 1]],
            "{": [["I", 3], [".", 1]]
        }
    },
    {
        "name": "sewer_passage",
        "tags": ["wet", "bridge"],
        "weight": 12,
        "min_area": 12,
        "map": [
            "XXXXXX",
            "..~..~",
            "XXXXXX"
        ],
        "subst": {
            "X": [["#", 6], [".", 1]],
            "~": [["W", 1], [".", 2]]
        }
    }
]
