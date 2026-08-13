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


def test_a_finished_arm_is_reused_rather_than_rerun(tmp_path):
    """A 28-arm sweep runs for hours and this container has restarted under two of them.

    The first restart discarded a 96-run classic confirmation partway through its second arm;
    the second killed a sandbox sweep after 2 arms of 27. An arm is a natural unit of work and
    costs nothing to persist, so losing more than the arm in flight was never necessary.
    """
    import json

    from runtime.ablate import _arm, _checkpoint_path

    home = str(tmp_path)
    rows = [{"agent": "seeker", "seed": i, "won": True, "floor": 26, "turns": 100,
             "win_path": "boss_killed", "kills": 0, "died": False, "resolved": True}
            for i in range(6)]
    with open(_checkpoint_path(home, "weather", False), "w", encoding="utf-8") as fh:
        json.dump(rows, fh)

    # runs=1 times six agents is six runs, which is what the checkpoint holds. If resume is
    # working this returns instantly without touching the world file, which does not exist
    # here: a cache miss would raise rather than quietly rerun.
    got = _arm("/nonexistent/world.json", 1, home, "weather", False, 99, 1, resume=True)
    assert got == rows


def test_a_half_written_checkpoint_is_rerun_not_trusted():
    """A run killed mid-arm must not leave a partial arm to be compared against."""
    import json
    import tempfile

    from runtime.ablate import _arm, _checkpoint_path

    with tempfile.TemporaryDirectory() as home:
        with open(_checkpoint_path(home, "weather", False), "w", encoding="utf-8") as fh:
            json.dump([{"agent": "seeker", "seed": 0, "won": True, "floor": 1,
                        "turns": 1, "win_path": "", "kills": 0, "died": False}], fh)
        # One row where six are expected. Trusting it would compare a full baseline against a
        # sixth of an arm and report the difference as the system's effect.
        with pytest.raises(Exception):
            _arm("/nonexistent/world.json", 1, home, "weather", False, 99, 1, resume=True)


def test_checkpoints_of_the_two_modes_do_not_collide():
    """Sandbox and classic arms of the same system are different measurements."""
    from runtime.ablate import _checkpoint_path
    assert _checkpoint_path("/h", "weather", True) != _checkpoint_path("/h", "weather", False)


def test_a_timed_out_run_is_recorded_as_unresolved_not_dropped():
    """A run that cannot finish is an outcome, not an absence.

    Dropping `loci` sent one sandbox worker into a CPU-bound spin: 2h12m at 99.9% on a single
    run where the whole 24-run arm normally takes ten minutes. The decision budget bounds the
    decision LOOP and cannot bound a loop inside one decision, so nothing stopped it, and it
    blocked every later stage of the pipeline behind it.

    Silently dropping such a run would shrink the arm and flatter it. Recording it keeps the
    arm the right size and marks it as floored by a harness limit.
    """
    from runtime.ablate import RUN_TIMEOUT, compare

    base = _rows([("a", i, True, 26, "boss_killed") for i in range(6)])
    arm = _rows([("a", i, False, 0, "") for i in range(6)])
    for r in arm:
        r["timed_out"] = True
        r["resolved"] = False
    for r in base:
        r["timed_out"] = False
        r["resolved"] = True

    d = compare(base, arm, "loci")
    assert d["n"] == 6, "timed-out runs were dropped, so the arm is the wrong size"
    assert d["arm_timeouts"] == 6 and d["base_timeouts"] == 0
    assert d["arm_resolved"] == 0, "a timed-out run must not count as resolved"
    assert RUN_TIMEOUT > 0
