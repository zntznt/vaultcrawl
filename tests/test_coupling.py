"""The emergence metric has to be able to tell a rich run from a poor one.

`event_kinds` cannot. Thirteen kinds exist in the whole game and a single 288-run pass sees
**12.3 of them per run**, so the number sits at 95% of its ceiling and reads the same for
every profile and every change. Across the egress-gate fix it moved from 12.3 to 12.3. A
metric pinned at its ceiling is not a measurement, it is a constant with error bars.

Worse, the bus it is computed over is **86.8% `noise`**, so any statistic taken across raw
events is mostly a statistic about one ambient event.

Emergence is systems combining: one system's output arriving as another's input. That is a
fact about which kinds appear *together*, which `event_kinds` discards by construction.
`couplings` records ordered pairs within `COUPLING_WINDOW`, giving a ceiling of kinds squared
(169 rather than 13) and leaving the metric room to move.

What this pins:

  1. Ambient events are excluded from coupling and reported separately, so the signal is not
     drowned by the 87%.
  2. Two runs with identical `event_kinds` but different *structure* score differently. This
     is the whole reason the metric exists, and it is the case the old one fails.
  3. Order matters: A then B is not B then A.
  4. The window is bounded, so unrelated events far apart are not called a coupling.
"""
from __future__ import annotations

from runtime.pressure import AMBIENT_EVENTS, COUPLING_WINDOW, EmergenceLog


def _log(seq):
    log = EmergenceLog()
    for e in seq:
        log.observe_event(e)
    return log


def test_ambient_events_do_not_drown_the_signal():
    ambient = sorted(AMBIENT_EVENTS)[0]
    log = _log([ambient] * 50 + ["a", "b"])
    s = log.summary()
    assert s["coupling_pairs"] == 1, "an ambient event was counted as a coupling"
    assert s["ambient_share"] > 0.9, "the ambient share is not being reported"
    assert not any(ambient in k for k in s["coupling_top"]), (
        f"{ambient!r} appears in the couplings, so the metric is measuring the 87%")


def test_it_separates_runs_that_event_kinds_calls_identical():
    """The case the old metric cannot see, and the reason for this file.

    Both runs contain exactly the same four kinds in the same quantities. One has them
    arriving in a repeating chain, the other in two isolated clumps that never meet. A
    player would call those different runs; `event_kinds` calls them the same number.
    """
    interleaved = ["a", "b", "c", "d"] * 4
    clumped = ["a"] * 8 + ["c"] * 8   # only two kinds meet, and only their own
    lo = _log(clumped)
    hi = _log(interleaved)

    assert len(hi.event_kinds) >= 2 and len(lo.event_kinds) >= 2
    assert hi.summary()["coupling_pairs"] > lo.summary()["coupling_pairs"], (
        "a run where four systems interleave scores no higher than one where two never "
        "meet, so the metric is blind to structure exactly like the one it replaces")


def test_order_matters():
    ab = _log(["a", "b"]).summary()["coupling_top"]
    ba = _log(["b", "a"]).summary()["coupling_top"]
    assert "a>b" in ab and "a>b" not in ba, (
        "coupling is unordered, so it cannot distinguish a cause from its effect")


def test_the_window_is_bounded():
    """Events far apart are not a coupling, or every run scores the maximum."""
    far = ["a"] + ["z"] * (COUPLING_WINDOW + 3) + ["b"]
    assert "a>b" not in _log(far).summary()["coupling_top"], (
        f"events {COUPLING_WINDOW + 3} apart were counted as coupled, so proximity means "
        f"nothing and the metric saturates like the old one")
    near = ["a", "z", "b"]
    assert "a>b" in _log(near).summary()["coupling_top"], "a real near pair was missed"


def test_density_has_headroom():
    """The failure mode being replaced: a number that sits at its ceiling.

    Thirteen kinds is 169 ordered pairs. A run that touches every kind but couples them
    sparsely must score well under 1.0, or the new metric saturates the same way.
    """
    kinds = [chr(ord("a") + i) for i in range(13)]
    chained = []
    for k in kinds:
        chained += [k, k]          # each kind mostly meets only itself
    s = _log(chained).summary()
    assert s["coupling_possible"] == 169, s["coupling_possible"]
    assert s["coupling_density"] < 0.5, (
        f"density {s['coupling_density']} on a deliberately sparse trace: the metric is "
        f"already near its ceiling and will not discriminate")
