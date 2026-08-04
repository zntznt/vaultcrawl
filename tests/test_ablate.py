"""Ablation has to report the second half of the criterion, not just the first.

The criterion is that the game be winnable by using the systems that are implemented, and
that using them introduce variance. Those are two measurements and a win rate is neither.
`runtime/ablate.py` takes a system out, re-runs the same seeds, and asks three questions:

  did the mean move       is this system part of how often the game is won
  did the spread move     is it part of what makes runs differ
  did the route mix move  is it part of HOW the game is won

The third is the one that justifies the file. Measured over 27 ablation arms at 24 runs
each: dropping `reactions` moved wins 12 to 11 at p = 1.000 and floor spread 9.2 to 6.5,
which reads as nothing happening twice over. The route table says otherwise. `boss_killed`
went 4 to 0 and every remaining win came by standing or commune. A whole way of winning
closed and both aggregates were blind to it.

The instrument also passes a mechanism check it was not built for: dropping `factions`
closes the `standing` route, and standing is the thing the faction system keeps.
"""
from __future__ import annotations

import pytest

from runtime.ablate import _mcnemar, _sd, compare


def _rows(spec: list) -> list:
    """spec is (agent, seed, won, floor, win_path)."""
    return [{"agent": a, "seed": s, "won": w, "floor": f, "turns": 1000 + f,
             "win_path": p, "kills": 0, "died": not w, "drop": ""}
            for a, s, w, f, p in spec]


def test_a_closed_route_is_reported_even_when_the_win_rate_holds():
    """The reason this module exists. `reactions` is the real case."""
    base = _rows([("a", i, True, 26, "boss_killed") for i in range(4)]
                 + [("a", i, True, 26, "standing") for i in range(4, 8)]
                 + [("a", i, False, 9, "") for i in range(8, 12)])
    arm = _rows([("a", i, True, 26, "standing") for i in range(8)]
                + [("a", i, False, 9, "") for i in range(8, 12)])
    d = compare(base, arm, "reactions")
    assert d["base_wins"] == d["arm_wins"] == 8, "the premise is an unchanged win count"
    assert d["p"] == 1.0, "the premise is that the aggregate sees nothing"
    assert d["closed"] == ["boss_killed"], (
        f"a whole way of winning vanished and `closed` reported {d['closed']}, so the only "
        f"column that could have seen it did not")


def test_a_route_the_system_was_suppressing_is_reported_too():
    """`quality` removed took `truths` from 0 wins to 9. A system can be a lid."""
    base = _rows([("a", i, True, 26, "boss_killed") for i in range(4)]
                 + [("a", i, False, 9, "") for i in range(4, 12)])
    arm = _rows([("a", i, True, 26, "boss_killed") for i in range(4)]
                + [("a", i, True, 26, "truths") for i in range(4, 10)]
                + [("a", i, False, 9, "") for i in range(10, 12)])
    d = compare(base, arm, "quality")
    assert d["opened"] == ["truths"]
    assert d["closed"] == []


def test_a_system_that_changes_nothing_reports_nothing():
    """The negative control. Dropping `narrator` really did land here on real runs."""
    spec = [("a", i, i % 2 == 0, 20 - i, "boss_killed" if i % 2 == 0 else "")
            for i in range(12)]
    d = compare(_rows(spec), _rows(spec), "narrator")
    assert (d["closed"], d["opened"]) == ([], [])
    assert d["p"] == 1.0
    assert d["base_floor"] == d["arm_floor"]
    assert d["base_floor_sd"] == d["arm_floor_sd"]


def test_the_comparison_is_paired_on_the_seed():
    """Each arm must face the identical worlds, or the difference is the seeds."""
    base = _rows([("a", i, True, 26, "boss_killed") for i in range(6)])
    arm = _rows([("a", i, False, 5, "") for i in range(3, 9)])
    d = compare(base, arm, "x")
    assert d["n"] == 3, (
        f"compared {d['n']} runs where only 3 seeds are shared, so unpaired seeds are being "
        f"counted and the arms are not facing the same worlds")


def test_mcnemar_counts_only_discordant_pairs():
    base = {k: {"won": w} for k, w in
            (("a", True), ("b", True), ("c", False), ("d", True), ("e", False))}
    arm = {k: {"won": w} for k, w in
           (("a", True), ("b", False), ("c", True), ("d", False), ("e", False))}
    lost, gained, p = _mcnemar(base, arm)
    assert (lost, gained) == (2, 1), "agreeing pairs are being counted as evidence"
    assert p == pytest.approx(2 * (1 + 3) / 8)


def test_no_shared_outcome_change_is_not_a_significant_result():
    same = {k: {"won": True} for k in "abcdef"}
    assert _mcnemar(same, same) == (0, 0, 1.0)


def test_spread_is_measured_on_floor_not_inferred_from_the_mean():
    """Two arms with the same mean floor and very different spreads must not read alike."""
    flat = _rows([("a", i, False, 18, "") for i in range(12)])
    wide = _rows([("a", i, False, 6 if i % 2 else 30, "") for i in range(12)])
    d = compare(flat, wide, "x")
    assert d["base_floor"] == d["arm_floor"] == 18, "the premise is an identical mean"
    assert d["arm_floor_sd"] > d["base_floor_sd"] == 0.0, (
        "identical means with opposite spreads reported the same spread, so the second half "
        "of the criterion is not being measured at all")
    assert _sd([18] * 12) == 0.0
