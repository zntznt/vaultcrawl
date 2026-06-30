"""Phase 5 -- the *Seen* gate (ARCHITECTURE_SPEC §11).

Renders a baked world's grown + carved architecture to the terminal, beside the full
15-property wholeness breakdown (the *Measured* gate) and the carved grid's own
grid_wholeness. Per Alexander, "the quality without a name is recognized, not proven" --
so this tool exists to put maps in front of a human, across vaults of escalating size
(hamlet -> town -> megastructure), to feel whether the QWAN is there before the runtime
commits to it (§11 gate 2).

Run a single world:
    python -m runtime.arch.visualize examples/world.json
Run the escalating-scale gallery (all sample worlds, side-by-side report):
    python -m runtime.arch.visualize --gallery

Pure stdlib, deterministic. Reads only baked world.json files; touches no game state.
"""
from __future__ import annotations

import json
import sys

from runtime.arch import grow as G
from runtime.arch.carve import carve, grid_wholeness
from runtime.arch.wholeness import wholeness, WEIGHTS
from runtime.dungeon import WALL


# ascending the scale ladder the spec's §3 / §11 ask us to test
GALLERY = [
    ("hamlet",   "examples/world_hamlet.json"),   # P3 -- thin, intimate
    ("town",     "examples/world.json"),          # P2 -- a few districts + courts
    ("town_v2",  "examples/world_v2.json"),        # P2 -- town after evolution
    ("mega",     "examples/world_mega.json"),       # P1 -- a dense super-cluster
]


def _crop(level):
    """Trim the all-wall margin so the map is legible."""
    rows = [list(r) for r in level.tiles]
    sx, sy = level.player_start
    rows[sy][sx] = "@"
    nonwall_rows = [y for y in range(level.h) if any(c != WALL for c in rows[y])]
    if not nonwall_rows:
        return rows
    y0, y1 = min(nonwall_rows), max(nonwall_rows)
    xs = [x for y in nonwall_rows for x in range(level.w) if rows[y][x] != WALL]
    x0, x1 = min(xs), max(xs)
    return [rows[y][x0:x1 + 1] for y in range(y0, y1 + 1)]


def _bar(v, width=20):
    if v is None:
        return "   n/a"
    n = int(round(max(0.0, min(1.0, v)) * width))
    return "█" * n + "·" * (width - n)


def report(name, path, render=True):
    graph = json.load(open(path))["graph"]
    n_notes = len(graph.get("nodes", {}))
    plan = G.grow(graph, seed="vis")
    level = carve(plan, seed="vis")

    plan_w, terms = wholeness(plan, breakdown=True)
    grid_w, gterms = grid_wholeness(level, breakdown=True)
    placed = plan.placed()
    courts = sum(1 for s in plan.seams if s.kind == "shared_court")
    voids = sum(1 for y in range(1, level.h - 1) for x in range(1, level.w - 1)
                if level.tiles[y][x] == WALL
                and all(level.tiles[y + dy][x + dx] != WALL
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))))

    print("=" * 72)
    print(f"  {name.upper()}  ({n_notes} notes, {path})")
    print("=" * 72)
    if render:
        for row in _crop(level):
            print("  " + "".join(row))
        print()
    print(f"  centers placed : {len(placed)}    seams: {len(plan.seams)}    "
          f"shared courts: {courts}    focal voids: {voids}")
    print(f"  plan wholeness : {plan_w:.3f}   grid wholeness: {grid_w:.3f}")
    print("  --- §4 living-structure properties (plan) ---")
    for prop, val in terms.items():
        w = WEIGHTS.get(prop, 0.0)
        print(f"    {prop:24s} {_bar(val)} {('%.2f' % val) if val is not None else ' n/a':>5}  (w={w})")
    print("  --- carved-grid properties ---")
    for prop, val in gterms.items():
        print(f"    {prop:24s} {_bar(val)} {val:.2f}")
    print()
    return {"name": name, "notes": n_notes, "plan_w": plan_w, "grid_w": grid_w,
            "courts": courts, "voids": voids}


def gallery():
    rows = []
    for name, path in GALLERY:
        try:
            rows.append(report(name, path, render=True))
        except FileNotFoundError:
            print(f"(skip {name}: {path} not baked yet)\n")
    if rows:
        print("=" * 72)
        print("  ESCALATING-SCALE SUMMARY  (same pattern language, different worlds)")
        print("=" * 72)
        print(f"  {'world':10s} {'notes':>5s} {'plan_w':>7s} {'grid_w':>7s} {'courts':>7s} {'voids':>6s}")
        for r in rows:
            print(f"  {r['name']:10s} {r['notes']:5d} {r['plan_w']:7.3f} "
                  f"{r['grid_w']:7.3f} {r['courts']:7d} {r['voids']:6d}")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] == "--gallery":
        gallery()
    else:
        report(argv[0], argv[0], render=True)


if __name__ == "__main__":
    main()
