"""`runtime/scent.py` computes a trail every turn of every run, and nothing read it.

The system diffuses the player's scent through walkable space, decays it, blocks it on walls
and exposes `scent_at` and `strongest_neighbour`. The only two things that touched any of
that were `runtime/behavior.py`, a utility-oracle module imported by nothing but two test
files, and the `scent_mask` consumable, which deletes the grid rather than reading it. So the
grid was built and thrown away.

`system_activity.py` already had the shape of it: busy and mute, acting on 11.1% of its
classic calls while emitting and logging nothing, which is exactly why dropping `scent` left
all 24 ablation arms unchanged. That reads as "this system does not matter" and it meant "this
system has no reader".

The signal was never thin. Measured over one classic seeker run before any change: 23,770
investigation steps, the observer standing on a live scent tile in 12,022 of them and with a
followable trail adjacent in 12,163. Half of every creature's investigating happened on top of
a path it could not smell.

Two things had to be true to consume it:

  1. `strongest_neighbour` scanned four orthogonals in an eight-directional game, so a tracker
     could only step orthogonally along a trail and was strictly slower than the prey that
     laid it. Measured after the fix, 907 of 2,716 followed steps are diagonal, which is a
     third of them that could not have happened before.
  2. `SenseField.scent` and `ScentSystem` are not duplicates and the split is the design.
     SenseField marks per actor and answers "something passed near", which is DETECTION and
     already fed `Perception.leads`. ScentSystem answers "and it went that way", which is a
     GRADIENT. Straight-lining at a detection walks into the wall between you and it.
"""
from __future__ import annotations

import pytest

from runtime.game import Game, load_manifest
from runtime.scent import SCENT_TRACK_MIN, ScentSystem
from runtime.senses import investigate_step, profile, scent_step
from runtime.stack import build_systems, register_brains


def _game():
    register_brains()
    return Game(load_manifest("examples/world.json"), systems=build_systems())


def _nose(g):
    """A creature whose profile actually has SMELL, per creatures.py."""
    from runtime.senses import SMELL
    for a in g.actors:
        if a is not g.player and getattr(a, "hp", 0) > 0 and profile(a).has(SMELL):
            return a
    a = next(x for x in g.actors if x is not g.player and getattr(x, "hp", 0) > 0)
    a.allegiance = "wild"          # wild resolves to scent_hound
    assert profile(a).has(SMELL)
    return a


def _blind(g):
    from runtime.senses import SMELL
    for a in g.actors:
        if a is not g.player and getattr(a, "hp", 0) > 0 and not profile(a).has(SMELL):
            return a
    pytest.skip("no smell-less creature on this floor")


# --- the gradient itself --------------------------------------------------------------------

def test_the_strongest_neighbour_is_found_on_a_diagonal():
    """Four-neighbour scanning cannot see a diagonal trail, and the game is eight-directional.
    A tracker that only steps orthogonally loses ground on every diagonal the prey takes."""
    g = _game()
    ss = ScentSystem()
    x, y = g.player.x, g.player.y
    ss.grid = {(x + 1, y + 1): 9}
    got = ss.strongest_neighbour(g, x, y)
    if not g.level.walkable(x + 1, y + 1):
        pytest.skip("no walkable diagonal at the player on this map")
    assert got == (x + 1, y + 1), (
        f"a trail one step diagonally was reported as {got}, so only the four orthogonals "
        f"are being scanned and a tracker can never close on a diagonal")


def test_a_flat_or_downhill_trail_yields_no_step():
    """Uphill is the whole signal. Following a level field is wandering, not tracking."""
    g = _game()
    ss = ScentSystem()
    x, y = g.player.x, g.player.y
    ss.grid = {(x, y): 9}                      # standing on the peak
    assert ss.gradient_step(g, x, y, SCENT_TRACK_MIN) is None


def test_an_uphill_neighbour_yields_a_step_toward_it():
    g = _game()
    ss = ScentSystem()
    x, y = g.player.x, g.player.y
    target = None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if g.level.walkable(x + dx, y + dy):
            target = (x + dx, y + dy, dx, dy)
            break
    assert target, "nowhere walkable beside the player"
    tx, ty, dx, dy = target
    ss.grid = {(x, y): 1, (tx, ty): 9}
    assert ss.gradient_step(g, x, y, SCENT_TRACK_MIN) == (dx, dy)


def test_the_floor_keeps_a_tracker_off_the_diffusion_haze():
    """Diffusion smears a thin value across a wide area. Chasing that is chasing nothing."""
    g = _game()
    ss = ScentSystem()
    x, y = g.player.x, g.player.y
    tgt = next(((x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if g.level.walkable(x + dx, y + dy)), None)
    assert tgt
    ss.grid = {tgt: SCENT_TRACK_MIN}           # exactly at the floor, not above it
    assert ss.gradient_step(g, x, y, SCENT_TRACK_MIN) is None
    ss.grid = {tgt: SCENT_TRACK_MIN + 1}
    assert ss.gradient_step(g, x, y, SCENT_TRACK_MIN) is not None


def test_the_gradient_never_steps_into_a_wall():
    g = _game()
    ss = ScentSystem()
    x, y = g.player.x, g.player.y
    ss.grid = {(nx, ny): 99 for nx in range(x - 1, x + 2) for ny in range(y - 1, y + 2)}
    step = ss.gradient_step(g, x, y, 0)
    if step is not None:
        assert g.level.walkable(x + step[0], y + step[1])


# --- the consumer ------------------------------------------------------------------------------

def test_only_a_nose_follows_the_trail():
    """The docstring's own contract: creatures with the SMELL sense track scent."""
    g = _game()
    ss = g.system("scent")
    blind = _blind(g)
    ss.grid = {(blind.x, blind.y): 9, (blind.x + 1, blind.y): 20}
    assert scent_step(g, blind) is None, (
        "a creature with no nose followed a scent trail, so every creature is a bloodhound")


def test_a_nose_standing_on_the_trail_follows_it():
    g = _game()
    ss = g.system("scent")
    nose = _nose(g)
    tgt = next(((nose.x + dx, nose.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if g.level.walkable(nose.x + dx, nose.y + dy)), None)
    assert tgt, "nowhere walkable beside the creature"
    ss.grid = {(nose.x, nose.y): 4, tgt: 20}
    assert scent_step(g, nose) == (tgt[0] - nose.x, tgt[1] - nose.y)


def test_a_whiff_is_not_a_trail():
    """Gated on standing ON it. A creature that merely caught a scent nearby keeps using the
    ordinary lead machinery, which is what `SenseField` is for."""
    g = _game()
    ss = g.system("scent")
    nose = _nose(g)
    ss.grid = {(nose.x + 1, nose.y): 20}       # adjacent trail, none underfoot
    assert scent_step(g, nose) is None


def test_investigate_prefers_the_trail_underfoot_over_a_remembered_position():
    """The reason the gradient is worth having: it rounds the corner the prey rounded, where
    pathing at a remembered position walks into whatever is between."""
    g = _game()
    ss = g.system("scent")
    nose = _nose(g)
    for a in list(g.actors):                   # no live target, so investigation runs
        if a is not nose and a is not g.player:
            a.hp = 0
    g.player.x, g.player.y = nose.x + 12, nose.y + 12
    nose._perc = None
    tgt = next(((nose.x + dx, nose.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if g.level.walkable(nose.x + dx, nose.y + dy)), None)
    assert tgt
    ss.grid = {(nose.x, nose.y): 4, tgt: 20}
    assert investigate_step(g, nose) == (tgt[0] - nose.x, tgt[1] - nose.y)


def test_investigate_still_uses_leads_when_there_is_no_trail():
    """The control. Adding the gradient must not replace the lead machinery, only precede it
    on the narrow case where a trail is underfoot."""
    g = _game()
    g.system("scent").grid = {}
    nose = _nose(g)
    nose._perc = None
    investigate_step(g, nose)                  # must not raise, and must not depend on scent


def test_the_gradient_is_deterministic():
    """Two equal neighbours must resolve the same way on every machine."""
    g = _game()
    ss = ScentSystem()
    x, y = g.player.x, g.player.y
    ss.grid = {(nx, ny): 9 for nx in range(x - 1, x + 2) for ny in range(y - 1, y + 2)
               if (nx, ny) != (x, y)}
    assert len({ss.gradient_step(g, x, y, 0) for _ in range(8)}) == 1
