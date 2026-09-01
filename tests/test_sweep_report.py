"""Tests for the sweep report's stall tripwire.

The report is how every balance decision in this project gets read, so a term that misses a
failure mode is worse than no term: it prints a clean bill of health over a broken arm.
"""
import runtime.sweep_report as SR


# --------------------------------------------------------------------------- #
# The third tripwire term. Two terms reported a clean bill of health on a mode where 80% of
# runs never resolved, because the dominant livelock paid a turn for every wasted decision
# (d/t exactly 1.000) and split its decisions across labels (44 to 47%, under the 60% share).
# --------------------------------------------------------------------------- #

def _row(**kw):
    base = dict(agent="seeker", seed=0, won=False, died=False, floor=1, turns=8016,
                decisions=8016, per_turn=1.0, top_label="workspace_camp", top_share=0.47,
                labels=30)
    base.update(kw)
    return base


def test_a_loop_that_pays_for_every_turn_is_caught():
    """The shape that got through: d/t at exactly 1.000 and a label share under the
    threshold, burning the whole budget on the first floor."""
    from runtime.sweep_report import _stalled

    assert _stalled(_row()), "8016 turns on floor 1 must trip"
    # and it must be the new term doing it, not one of the old two
    assert _row()["per_turn"] <= SR.STALL_DT
    assert _row()["top_share"] < SR.STALL_SHARE


def test_a_run_that_covers_ground_is_not_flagged():
    """No resolved run in 685 exceeded 1,344 turns per floor, so a normal descent must stay
    clear of the threshold with room to spare."""
    from runtime.sweep_report import _stalled, turns_per_floor

    healthy = _row(won=True, floor=26, turns=14268, top_share=0.28)
    assert turns_per_floor(healthy) < SR.STALL_TURNS_PER_FLOOR
    assert not _stalled(healthy)
    # the worst legitimate run observed, and it must still read as healthy
    assert not _stalled(_row(won=True, floor=1, turns=1344, top_share=0.3))


def test_the_threshold_keeps_its_margin_over_observed_healthy_runs():
    """Picked from data: 2000 against a worst observed resolved run of 1344. If someone
    lowers it under that, resolved runs start reading as stalls."""
    assert SR.STALL_TURNS_PER_FLOOR > 1344


def test_a_floorless_run_is_scored_on_its_whole_turn_count():
    """`floor` 0 must not divide by zero, and must not score as infinitely healthy."""
    from runtime.sweep_report import turns_per_floor

    assert turns_per_floor(_row(floor=0, turns=8016)) == 8016
