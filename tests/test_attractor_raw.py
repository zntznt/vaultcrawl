"""An attractor you cannot calibrate from its own output is not an instrument.

`_industrial_score` is `max(0, (ratio - 0.5) * 2)` where ratio is matter forged over matter
collected. Every ratio at or below 0.5 therefore reports exactly 0.000, and the clamp throws
away how far below. Measured over 288 runs, all six profiles read between 0.000 and 0.016,
which says only "at or under 0.5" and cannot distinguish a ratio of 0.49 from one of 0.05.
Those two would call for opposite changes: the first means nudge the threshold, the second
means the attractor is describing an economy the game does not have.

This is the third instance of one failure in this project. `event_kinds` sat at 12.3 of 13
and read the same for every change. `recall` sat at 0.00% because its denominator was every
decision in the run. Now `industrial` sits under a clamp. In each case a statistic parked
against a wall was reported as a constant and read as a fact about the game.

`raw()` exposes the unclamped quantities so the thresholds can be set from evidence. It is
deliberately separate from `scores()`, which keeps its shape: these are diagnostics, and
nothing should threshold on them without saying so.
"""
from __future__ import annotations

import pytest

from runtime.attractors import AttractorTracker


def _t():
    return AttractorTracker()


def test_raw_survives_the_clamp_that_scores_does_not():
    """The point of the file: two very different worlds that score identically."""
    near = _t()
    near.record_matter_collected(100)
    near.record_matter_forged(49)          # ratio 0.49, a nudge from the threshold

    far = _t()
    far.record_matter_collected(100)
    far.record_matter_forged(5)            # ratio 0.05, nowhere near it

    assert near.scores()["industrial"] == far.scores()["industrial"] == 0.0, (
        "the premise has changed: the clamp no longer hides these, so this file needs "
        "rewriting rather than trusting")
    assert near.raw()["forge_ratio"] != far.raw()["forge_ratio"], (
        "raw() cannot separate a ratio of 0.49 from 0.05 either, so the attractor still "
        "cannot be calibrated from its own output")


def test_raw_reports_both_terms_of_every_dead_attractor():
    """`haunted` and `echo_cascade` read zero too; their numerators and denominators differ.

    `haunted` was zero because ghosts_seen was pinned at 0 while notes_learned was 4 to 12.
    Knowing which term is empty is the whole diagnosis, and the score cannot say.
    """
    t = _t()
    for key in ("matter_collected", "matter_forged", "forge_ratio",
                "ghosts_seen", "notes_learned", "echo_fires"):
        assert key in t.raw(), f"raw() does not report {key}"


def test_a_zero_denominator_does_not_explode():
    t = _t()
    assert t.raw()["forge_ratio"] == 0.0
    assert t.scores()["industrial"] == 0.0


def test_scores_keeps_its_shape():
    """The attractor vector is consumed elsewhere; diagnostics must not leak into it."""
    t = _t()
    assert set(t.scores()) == {"industrial", "haunted", "companion_flux",
                               "pacifist", "echo_cascade", "standing_range"}
    assert not (set(t.raw()) & set(t.scores())), (
        "a diagnostic has leaked into scores(), so something will start thresholding on it")


def test_raw_tracks_what_actually_happened():
    t = _t()
    t.record_matter_collected(10)
    t.record_matter_collected(30)
    t.record_matter_forged(8)
    r = t.raw()
    assert r["matter_collected"] == 40 and r["matter_forged"] == 8
    assert r["forge_ratio"] == pytest.approx(0.2)
