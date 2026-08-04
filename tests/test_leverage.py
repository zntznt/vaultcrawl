"""The instrument must not manufacture leverage, and must not hide it either.

`runtime/leverage.py` answers a criterion win rate cannot: is the game won by using the
systems that are implemented, and does using them introduce variance. A game can hold at 45%
with twenty-nine systems present and every one of them inert, and no aggregate would say so.

Because its output is a verdict per mechanic, its failure modes are both directions:

  false positive   calling a coincidence load-bearing. With 48 runs and 10 wins a tercile
                   split will find a story in noise if nothing stops it, which is why lift is
                   permutation-tested rather than asserted.
  false negative   burying a real mechanic. An earlier draft mapped a degenerate tercile split
                   to `inert`, which put twelve signals in the wrong bucket, several with a
                   coefficient of variation above 3. Sparse is not the same as flat.

The fixtures are synthetic on purpose. Real rows cannot tell you whether the instrument found
a true signal or invented one, because the truth is what you were trying to measure.
"""
from __future__ import annotations

import pytest

from runtime.leverage import LIFT_FLOOR, SPREAD_FLOOR, analyse, signals


def _rows(values: dict, wins: list) -> list:
    """One row per entry in `wins`; `values` maps a label to its per-run share."""
    return [
        {"won": bool(w), "turns": 100, "label_share": {k: v[i] for k, v in values.items()}}
        for i, w in enumerate(wins)
    ]


def _by_name(rows):
    return {d["name"]: d for d in analyse(rows)}


WINS = [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0]


def test_a_signal_that_tracks_the_outcome_is_load_bearing():
    """The thing we are looking for: use it more, win more."""
    perfect = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.05, 0.04, 0.03, 0.02, 0.01, 0.005]
    d = _by_name(_rows({"forge": perfect}, WINS))["label:forge"]
    assert d["verdict"] == "load-bearing", d
    assert d["lift"] > LIFT_FLOOR and d["p"] <= 0.05


def test_a_constant_is_inert_however_central_it_looks():
    """A mechanic every run uses identically cannot differentiate anything."""
    d = _by_name(_rows({"move": [0.5] * 12}, WINS))["label:move"]
    assert d["verdict"] == "inert", d
    assert d["reach"] == 1.0, "the point is that it is used everywhere, not that it is missing"
    assert d["cv"] < SPREAD_FLOOR


def test_variation_uncorrelated_with_the_outcome_is_decorative():
    """Spread without lift. It varies, and the game does not notice."""
    alternating = [0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9]
    d = _by_name(_rows({"noise": alternating}, WINS))["label:noise"]
    assert d["verdict"] == "decorative", d
    assert d["cv"] >= SPREAD_FLOOR, "the premise is spread; without it this tests nothing"


def test_a_signal_no_run_ever_produced_is_unreachable():
    rows = _rows({"a": [0.5] * 12}, WINS)
    for r in rows:
        r["label_share"]["ghost_verb"] = 0.0
    assert _by_name(rows)["label:ghost_verb"]["verdict"] == "unreachable"


def test_a_sparse_signal_is_split_on_presence_not_terciles():
    """The false negative this file exists for. Sparse is not flat.

    Six users in twenty-four runs, all of them winners. A tercile boundary here sits at zero
    on both sides, so terciles cannot separate the users from anyone; presence can, and the
    mechanic is plainly part of how the game is won.
    """
    wins = [1] * 12 + [0] * 12
    sparse = [0.4, 0.3, 0.5, 0.6, 0.2, 0.45] + [0.0] * 18
    d = _by_name(_rows({"commune": sparse}, wins))["label:commune"]
    assert d["split"] == "presence", (
        "a tercile split on a signal three quarters of runs never touch is a tie, and calling "
        "that inert is how twelve real signals got buried")
    assert d["verdict"] == "load-bearing", d


def test_too_few_runs_on_one_side_is_untestable_and_says_so():
    """A verdict about the sample must never be reported as a verdict about the mechanic."""
    almost_never = [0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    d = _by_name(_rows({"rare": almost_never}, WINS))["label:rare"]
    assert d["verdict"] == "untestable", d
    assert d["lift"] is None, "an untestable signal must not carry a number to be misread"


def test_permutation_p_kills_a_coincidence():
    """Guards the false positive. A tiny sample shows a perfect split for free.

    Three users, three abstainers, and every user won. The lift is a flawless +100%, and it
    means nothing: one arrangement in twenty is this clean by chance alone.
    """
    tiny_wins = [1, 1, 1, 0, 0, 0]
    lucky = [0.6, 0.5, 0.4, 0.0, 0.0, 0.0]
    d = _by_name(_rows({"luck": lucky}, tiny_wins))["label:luck"]
    assert d["lift"] == pytest.approx(1.0), "the premise changed: this split is not perfect"
    assert d["p"] > 0.05, (
        f"a perfect split of 3 against 3 came back at p={d['p']:.4f}, so the permutation "
        f"test is not restraining anything and every small sample will read load-bearing")
    assert d["verdict"] == "decorative"


def test_the_verdict_is_deterministic():
    """Same rows, same answer, on any machine. The RNG is seeded from the signal name."""
    rows = _rows({"a": [0.9, 0.1, 0.8, 0.2, 0.7, 0.3, 0.6, 0.4, 0.5, 0.15, 0.85, 0.25]}, WINS)
    first = _by_name(rows)["label:a"]
    second = _by_name(rows)["label:a"]
    assert (first["p"], first["lift"], first["verdict"]) == \
           (second["p"], second["lift"], second["verdict"])


def test_the_three_depths_stay_distinct():
    """A label and a verb of the same name are the comparison, so they must not merge."""
    rows = [{"won": True, "turns": 1, "label_share": {"forge": 0.5},
             "verb_ok": {"forge": 3}, "events": {"forge_used": 3}}]
    names = set(signals(rows))
    assert {"label:forge", "verb:forge", "event:forge_used"} <= names, (
        "the depths have collapsed, so 'the agent wanted it' and 'the game granted it' can no "
        "longer disagree, and that disagreement is the diagnosis")
