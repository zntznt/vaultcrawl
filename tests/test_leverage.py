"""The instrument must not manufacture leverage, and must not hide it either.

`runtime/leverage.py` answers a criterion win rate cannot: is the game won by using the
systems that are implemented, and does using them introduce variance. A game can hold at 45%
with twenty-nine systems present and every one of them inert, and no aggregate would say so.

Because its output is a verdict per mechanic, its failure modes run both ways, and both have
already happened here on real rows:

  false positive   Raw counts accumulate with time, so on 48 classic runs `event:noise`
                   (footsteps) read +81.2% lift and `verb:move` (walking) read +75.0%. Thirty
                   signals came back load-bearing on that basis and none of them meant
                   anything. Dividing by turns inverted the artifact rather than removing it:
                   a run that dies at turn 60 having forged once outscores a winner's whole
                   career, and `count:sigils_forged` duly read -68.8%. Lift is measured within
                   duration bands now, which is the only version that holds.
  false negative   An earlier draft mapped a degenerate split to `inert`, burying twelve
                   signals with a coefficient of variation above 3. Sparse is not flat.

And the failure that is neither: testing seventy-six signals at p < 0.05 hands you about four
load-bearing verdicts for free. Hence the false-discovery control and the `suggestive` bucket.

The fixtures are synthetic on purpose. Real rows cannot tell you whether the instrument found
a true signal or invented one, because the truth is what you were trying to measure.
"""
from __future__ import annotations

import collections

import pytest

from runtime.leverage import (LIFT_FLOOR, SPREAD_FLOOR, analyse, duration_strata,
                              signals)

# Three duration bands need at least six runs each to split, so a fixture smaller than
# eighteen tests the sample size and not the instrument.
BAND = 12
N = BAND * 3


def _rows(values: dict, wins: list, turns=None) -> list:
    """One row per entry in `wins`. Turns ascend, so band membership is index // BAND."""
    turns = turns or [100 * (i + 1) for i in range(len(wins))]
    return [
        {"won": bool(w), "turns": turns[i], "decisions": turns[i],
         "label_share": {k: v[i] for k, v in values.items()}}
        for i, w in enumerate(wins)
    ]


def _banded(pattern: list) -> list:
    """Repeat a within-band pattern across all three bands."""
    return pattern * 3


# Half of every band wins, so no band carries the outcome on its own.
WINS = _banded([1] * (BAND // 2) + [0] * (BAND // 2))


def _by_name(rows):
    return {d["name"]: d for d in analyse(rows)}


def test_duration_bands_are_balanced_and_ordered():
    """Everything below rests on this: like is only ever compared against like."""
    rows = _rows({"a": [0.0] * N}, WINS)
    st = duration_strata(rows)
    assert st == [i // BAND for i in range(N)], "runs are not banded by ascending duration"
    assert sorted(collections.Counter(st).values()) == [BAND] * 3, "bands are uneven"


def test_a_signal_that_tracks_the_outcome_inside_every_band_is_load_bearing():
    """The thing we are looking for: use it more, win more, at every run length."""
    perfect = _banded([0.9] * (BAND // 2) + [0.1] * (BAND // 2))
    d = _by_name(_rows({"forge": perfect}, WINS))["label:forge"]
    assert d["verdict"] == "load-bearing", d
    assert d["lift"] > LIFT_FLOOR and d["survives_fdr"]


def test_a_constant_is_inert_however_central_it_looks():
    """A mechanic every run uses identically cannot differentiate anything."""
    d = _by_name(_rows({"move": [0.5] * N}, WINS))["label:move"]
    assert d["verdict"] == "inert", d
    assert d["reach"] == 1.0, "the point is that it is used everywhere, not that it is missing"
    assert d["cv"] < SPREAD_FLOOR


def test_variation_uncorrelated_with_the_outcome_is_decorative():
    """Spread without lift. It varies, and the game does not notice."""
    alternating = _banded([0.1, 0.9] * (BAND // 2))
    d = _by_name(_rows({"noise": alternating}, WINS))["label:noise"]
    assert d["verdict"] == "decorative", d
    assert d["cv"] >= SPREAD_FLOOR, "the premise is spread; without it this tests nothing"


def test_a_signal_no_run_ever_produced_is_unreachable():
    rows = _rows({"a": [0.5] * N}, WINS)
    for r in rows:
        r["label_share"]["ghost_verb"] = 0.0
    assert _by_name(rows)["label:ghost_verb"]["verdict"] == "unreachable"


def test_pure_duration_scores_nothing_once_the_bands_hold():
    """The control, and the whole reason for banding.

    Wins alternate with duration INSIDE each band, so being a longer run is worth nothing once
    like is compared against like. Before banding, duration was the top of the table on real
    rows at +87.5%, above every actual mechanic.
    """
    alt = _banded([1, 0] * (BAND // 2))
    d = _by_name(_rows({"a": _banded([0.1, 0.9] * (BAND // 2))}, alt))["control:turns"]
    assert abs(d["lift"]) < LIFT_FLOOR, (
        f"duration alone scores {d['lift']:+.1%}, so the bands are not holding and every "
        f"verdict in the report is really a verdict about run length")


def test_raw_counts_do_not_smuggle_duration_back_in():
    """A count that is a fixed *rate* must not look like leverage just because runs differ.

    Every run here fires the event once per ten turns, so nothing distinguishes them but
    length. If counts were read raw, the long runs would carry every win and this would top
    the table.
    """
    wins = _banded([1] * (BAND // 2) + [0] * (BAND // 2))
    rows = _rows({"a": [0.5] * N}, wins)
    for r in rows:
        r["events"] = {"tick": r["turns"] // 10}
    d = _by_name(rows)["event:tick"]
    assert abs(d["lift"] or 0) < LIFT_FLOOR, (
        f"a constant rate read as {d['lift']:+.1%} lift, so counts are still measuring how "
        f"long the run lasted")


def test_a_signal_the_median_cannot_split_falls_back_to_presence():
    """The false negative this file exists for. Sparse is not flat.

    Two thirds of each band use the mechanic at an identical rate, so the lower median is
    already that rate and a median split leaves the high group empty. Used-versus-not still
    separates them, and must.
    """
    pattern = [0.5] * 8 + [0.0] * 4
    users_win = [1] * 8 + [0] * 4
    d = _by_name(_rows({"commune": _banded(pattern)}, _banded(users_win)))["label:commune"]
    assert d["split"] == "presence", (
        f"split was {d['split']!r}; a median that equals the maximum cannot separate anyone, "
        f"and calling that inert is how twelve real signals got buried")
    assert d["verdict"] == "load-bearing", d


def test_too_few_runs_on_one_side_is_untestable_and_says_so():
    """A verdict about the sample must never be reported as a verdict about the mechanic."""
    almost_never = _banded([0.5] + [0.0] * (BAND - 1))
    d = _by_name(_rows({"rare": almost_never}, WINS))["label:rare"]
    assert d["verdict"] == "untestable", d
    assert d["lift"] is None, "an untestable signal must not carry a number to be misread"


def test_false_discovery_control_demotes_a_lone_marginal_signal():
    """Testing many signals at 0.05 buys load-bearing verdicts for free; FDR takes them back."""
    rows = _rows({"a": _banded([0.9] * (BAND // 2) + [0.1] * (BAND // 2))}, WINS)
    # Sixty pure-noise signals alongside one real one, which is the real batch's shape.
    for i, r in enumerate(rows):
        for j in range(60):
            r["label_share"][f"noise{j}"] = float((i * (j + 7)) % 11) / 10.0
    res = {d["name"]: d for d in analyse(rows)}
    assert res["label:a"]["verdict"] == "load-bearing", "the genuine signal was demoted too"
    demoted = [d for d in res.values() if d["verdict"] == "suggestive"]
    assert all(not d["survives_fdr"] for d in demoted)
    assert all(d["p"] <= 0.05 for d in demoted), (
        "a signal with raw p above 0.05 reached the suggestive bucket, which is meant to hold "
        "exactly the ones FDR took back")


def test_the_verdict_is_deterministic():
    """Same rows, same answer, on any machine. The RNG is seeded from the signal name."""
    rows = _rows({"a": _banded([0.9, 0.1] * (BAND // 2))}, WINS)
    first = _by_name(rows)["label:a"]
    second = _by_name(rows)["label:a"]
    assert (first["p"], first["lift"], first["verdict"]) == \
           (second["p"], second["lift"], second["verdict"])


def test_the_three_depths_stay_distinct():
    """A label and a verb of the same name are the comparison, so they must not merge."""
    rows = [{"won": True, "turns": 1000, "label_share": {"forge": 0.5},
             "verb_ok": {"forge": 3}, "events": {"forge_used": 3}}]
    names = set(signals(rows))
    assert {"label:forge", "verb:forge", "event:forge_used"} <= names, (
        "the depths have collapsed, so 'the agent wanted it' and 'the game granted it' can no "
        "longer disagree, and that disagreement is the diagnosis")
