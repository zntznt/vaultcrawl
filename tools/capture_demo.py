"""Capture the REAL game as an animated SVG for the GitHub Page.

This drives the actual sandbox Game (same growth, same colours, same everything)
and records a run of frames, then writes a single self-contained animated SVG.
Because it calls the live game code, the demo is ALWAYS loyal to the current build
— CI re-runs this on every push, so the page can never drift from reality.

No curses (headless-safe for CI): we read game.compose_frame() and colour each
glyph with the same rules the terminal front-end uses, translating to ANSI-style
colours baked straight into the SVG.

Usage: python -m tools.capture_demo --world examples/world.json --out docs/demo.svg
"""
from __future__ import annotations

import argparse
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime import brains  # noqa: F401  (registers brains)
from runtime.game import Game, load_manifest

# ---- colour table: mirrors runtime/play.py's palette, as (hex, bold, dim) ---- #
# 8 ANSI colours, resolved to hexes that read well on black.
_C = {"R": "#e05561", "G": "#8cc265", "Y": "#e5c07b", "B": "#61afef",
      "M": "#c678dd", "C": "#56b6c2", "W": "#d7dae0", "K": "#5c6370"}
# glyph -> (colour key, bold, dim), a faithful subset of the game's palette
_GLYPH = {
    "@": ("W", 1, 0),
    "#": ("W", 0, 0), ".": ("W", 0, 1), "░": ("B", 0, 1), "·": ("W", 0, 1),
    '"': ("G", 0, 1), "`": ("Y", 0, 1), "-": ("B", 0, 1), "|": ("W", 0, 0),
    "[": ("Y", 0, 1), "(": ("W", 0, 1), "]": ("W", 0, 1), "!": ("Y", 1, 0),
    ">": ("Y", 1, 0), "<": ("Y", 1, 0), ",": ("G", 0, 0), ";": ("G", 0, 0),
    "'": ("Y", 0, 1), "^": ("R", 1, 0), "~": ("B", 0, 0), "/": ("Y", 1, 0),
    "I": ("W", 1, 0), "+": ("Y", 1, 0), ":": ("C", 1, 0), "=": ("Y", 0, 0),
    "o": ("B", 1, 0), "&": ("M", 0, 0), "_": ("R", 0, 1), "%": ("M", 0, 1),
    "*": ("Y", 1, 0), "$": ("C", 1, 0), "?": ("Y", 1, 0), "F": ("B", 1, 0),
    "T": ("B", 1, 0), "P": ("C", 1, 0), "M": ("M", 1, 0),
    "n": ("C", 0, 1), "z": ("C", 0, 1), "Y": ("C", 0, 1),
    "A": ("W", 0, 0), "X": ("R", 0, 1), "H": ("M", 0, 0), "V": ("W", 1, 0),
}
for ch in "sgwrebch" + "qucmjkydfv":     # hostile bestiary reads red
    _GLYPH[ch] = ("R", 0, 0)
for ch in "hejuk":                       # spectral kinds read magenta
    _GLYPH[ch] = ("M", 0, 0)
# region palette-leans -> colour key (mirrors play.py pal:* + the vivid/muted axis)
_LEAN = {"verdant": ("G", 1), "holy": ("M", 1), "rust": ("R", 1), "harsh": ("Y", 1),
         "cold": ("C", 1), "bloom": ("M", 1), "gold": ("Y", 1),
         "pale": ("W", 0), "dim": ("W", -1), "ash": ("W", -1)}
_GROUND = set(".,'`\"")


def _cell_style(game, ch, wx, wy, block_glyphs):
    """(hex, bold, dim) for one glyph, applying the region's colour to ground —
    the same decision the live renderer makes."""
    key, bold, dim = _GLYPH.get(ch, ("W", 0, 0))
    if ch in block_glyphs or ch in _GROUND:
        rid = game._region_of.get((wx, wy)) if hasattr(game, "_region_of") else None
        lean = game.region_palette(rid) if rid is not None else ""
        if lean in _LEAN:
            key, b = _LEAN[lean]
            bold = 1 if b == 1 else 0
            dim = 1 if (b == -1 or ch == ".") else 0
    return _C[key], bold, dim


def _explorer_step(game, heading):
    """A traveller that COMMITS to a heading and holds it while it can, only turning
    when blocked — so the demo crosses real ground instead of jittering in place.
    Returns (dx, dy, new_heading). Deterministic (seeded by turn)."""
    import random
    px, py = game.player.x, game.player.y

    def ok(d):
        nx, ny = px + d[0], py + d[1]
        return game.level.walkable(nx, ny) and game.actor_at(nx, ny) is None

    if heading and ok(heading):
        return heading[0], heading[1], heading   # keep going straight
    # blocked: pick a fresh heading that clears, prefer turning not reversing
    r = random.Random(f"{game.seed}:demo:{game.turn}")
    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]
    r.shuffle(dirs)
    rev = (-heading[0], -heading[1]) if heading else None
    for d in dirs:
        if d != rev and ok(d):
            return d[0], d[1], d
    for d in dirs:                               # last resort: even reversing
        if ok(d):
            return d[0], d[1], d
    return 0, 0, heading


def capture(world, frames, width, height):
    """Run the real game; return a list of frames, each a grid of (char, hex, bold,
    dim) cells, plus the per-frame HUD line."""
    g = Game(load_manifest(world), sandbox=True, sprawl=2.5,
             site_cache=world + ".site.json")
    g.width, g.height = width, height
    block_glyphs = getattr(g, "_block_glyphs", frozenset())
    out = []
    heading = (1, 0)
    for _ in range(frames):
        grid, (ox, oy) = g.compose_frame()
        cells = []
        for y, row in enumerate(grid):
            line = []
            for x, ch in enumerate(row):
                hexc, bold, dim = _cell_style(g, ch, ox + x, oy + y, block_glyphs)
                line.append((ch, hexc, bold, dim))
            cells.append(line)
        hud = g.region_name or "the vault"
        msg = g.messages[-1] if g.messages else ""
        out.append((cells, hud, msg))
        dx, dy, heading = _explorer_step(g, heading)
        if dx or dy:
            g.try_move(dx, dy)
        else:
            g.wait()
    return out


def _frame_svg(cells, hud, msg, cols, rows, cell_w, cell_h):
    """One frame's <text> runs (glyphs of identical style merged for size)."""
    parts = []
    for y, line in enumerate(cells):
        py = 14 + y * cell_h
        x = 0
        while x < len(line):
            ch, hexc, bold, dim = line[x]
            run = ch
            j = x + 1
            while j < len(line) and line[j][1:] == (hexc, bold, dim):
                run += line[j][0]
                j += 1
            op = " opacity='.5'" if dim else ""
            wt = " font-weight='bold'" if bold else ""
            parts.append(f"<text x='{8 + x * cell_w}' y='{py}' fill='{hexc}'{op}{wt}"
                         f" xml:space='preserve'>{html.escape(run)}</text>")
            x = j
    parts.append(f"<text x='8' y='{14 + rows * cell_h + 12}' fill='#8cc265'"
                 f" font-weight='bold'>{html.escape((hud + '   ' + msg)[:cols])}</text>")
    return "".join(parts)


def to_svg(frames, cell_w=8, cell_h=16, fps=6):
    """One self-contained animated SVG that plays in an <img> tag. Each frame is a <g>
    stacked in the same spot; SMIL (<animate> on `display`) shows each frame only during
    its 1/n slice of the loop. SMIL runs inside <img> (unlike CSS animation), so this
    plays like a video anywhere with no external player and no JS."""
    if not frames:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    n = len(frames)
    rows = len(frames[0][0])
    cols = len(frames[0][0][0])
    W = cols * cell_w + 16
    H = rows * cell_h + 40
    dur = n / fps
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' "
        f"viewBox='0 0 {W} {H}' font-family='monospace' font-size='{cell_h - 3}'>",
        f"<rect width='{W}' height='{H}' fill='#12141a' rx='8'/>",
    ]
    for i, (cells, hud, msg) in enumerate(frames):
        t0 = i / n
        t1 = (i + 1) / n
        # discrete OPACITY switch (well supported inside <img> SVG). Each frame is
        # opaque only during [t0, t1). keyTimes must start at 0 and end at 1.
        # keyTimes: first must be 0, last must be 1, one value per keyTime. A value
        # holds until the next keyTime; discrete = hard switch.
        if i == 0:
            values, keys = "1;0;0", f"0;{t1:.5f};1"
        else:
            values, keys = "0;1;0;0", f"0;{t0:.5f};{t1:.5f};1"
        parts.append(
            f"<g opacity='0'><animate attributeName='opacity' values='{values}' "
            f"keyTimes='{keys}' dur='{dur:.3f}s' begin='0s' repeatCount='indefinite' "
            f"calcMode='discrete'/>")
        parts.append(_frame_svg(cells, hud, msg, cols, rows, cell_w, cell_h))
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--world", default="examples/world.json")
    ap.add_argument("--out", default="docs/demo.svg")
    ap.add_argument("--frames", type=int, default=48)
    ap.add_argument("--width", type=int, default=54)
    ap.add_argument("--height", type=int, default=22)
    ap.add_argument("--fps", type=int, default=6)
    a = ap.parse_args(argv)
    frames = capture(a.world, a.frames, a.width, a.height)
    svg = to_svg(frames, fps=a.fps)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {a.out}  ({len(frames)} frames, {len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
