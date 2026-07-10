"""The GitHub-Page demo is captured from the REAL game, so it can't drift. This just
guards that the capture tool still produces a valid, animated, multi-frame SVG, so a
future game change that breaks the capture fails loudly in CI instead of silently
shipping a blank page."""
from __future__ import annotations

import xml.dom.minidom as minidom

from tools.capture_demo import capture, to_svg


def _world():
    return "examples/world.json"


def test_capture_produces_distinct_moving_frames():
    frames = capture(_world(), 20, 40, 14)
    assert len(frames) == 20
    # the player @ appears and moves across frames (a travelogue, not a still)
    def at(cells):
        return next(((x, y) for y, ln in enumerate(cells)
                     for x, c in enumerate(ln) if c[0] == "@"), None)
    spots = {at(f[0]) for f in frames}
    assert len(spots) >= 3, "the demo should travel, not sit still"
    # frames carry real colour (more than one hex on screen)
    hexes = {c[1] for cells, _h, _m in frames for ln in cells for c in ln}
    assert len(hexes) >= 3, "the capture should reflect the game's colours"


def test_svg_is_valid_and_animated():
    frames = capture(_world(), 12, 40, 12)
    svg = to_svg(frames, fps=6)
    # parses as XML (so it renders in a browser)
    doc = minidom.parseString(svg)
    assert doc.documentElement.tagName == "svg"
    # one <animate> per frame drives the loop
    assert svg.count("<animate") == len(frames)
    # SMIL keyTimes are well-formed: every list starts at 0 and ends at 1
    import re
    for kt in re.findall(r"keyTimes='([^']+)'", svg):
        parts = kt.split(";")
        assert parts[0] == "0" and parts[-1] == "1", f"bad keyTimes: {kt}"


if __name__ == "__main__":
    for fn in (test_capture_produces_distinct_moving_frames,
               test_svg_is_valid_and_animated):
        fn()
        print(f"ok {fn.__name__}")
