"""The survival branch has to appear in the record of what the agent decided.

`UniversalBrain.decide()` opens with a panic override: below 25% HP for fighters and 35% for
everyone else it casts Phase, descends, or runs for the stairs. All three paths return before
the candidate list is built, and they used to return before recording anything at all.

`DecisionLog.observe()` reads exactly two attributes, `_last_candidates` and `_last_choice`
(`pressure.py`). Neither was assigned on those paths, so they still held the PREVIOUS turn's
values, and observe dutifully recorded that turn a second time. Two consequences, both bad:

  * Panic never appeared in a label distribution. Every "no combat label in the top 8" reading
    this project has taken was partly an artifact of the branch being unrecordable.
  * The turns just before a near-death were counted twice, with their margins and candidate
    counts, so `contested_share`, `median_margin` and `avg_candidates` were inflated by
    duplicates drawn from exactly the moments that matter most.

A single smoke run afterwards put `panic_flee` at 30% of all decisions and `forced_share` at
31%, so this was not a rounding error in the telemetry. It was a third of it.

The fix must be telemetry only: the action a panic turn returns has to be the action it
returned before, or the measurement it exists to support is measuring a different game. The
identity property of `_forced` is pinned here; the whole-run version is a fixed-seed action
trace diffed across the change, which lives in the tranche's verification rather than in
pytest because it takes minutes.
"""
from __future__ import annotations

import pytest

from runtime.agent import UniversalBrain
from runtime.agent_action import AgentAction
from runtime.game import Game, load_manifest
from runtime.pressure import HP_TAIL, DecisionLog
from runtime.stack import build_systems


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="panic", systems=build_systems())
    g.descend()
    return g


def _decide(g, brain, log):
    action = brain.decide(g, g.player)
    log.observe(g, brain)
    return action


def test_a_panic_turn_records_itself_and_not_the_turn_before_it(game):
    """The bug, stated directly: panic used to be logged as a repeat of the last decision."""
    brain = UniversalBrain("cartographer")
    log = DecisionLog()

    _decide(game, brain, log)
    before = dict(log.labels)
    assert before, "the healthy turn recorded nothing, so the test proves nothing"
    assert not any(k.startswith("panic") for k in before), \
        "the agent was at full health and still panicked; the fixture is wrong"

    game.player.hp = max(1, int(game.player.max_hp * 0.05))
    action = _decide(game, brain, log)

    panicked = [k for k in log.labels if k.startswith("panic")]
    assert panicked, (
        f"a turn at 5% HP recorded no panic label, only {sorted(log.labels)}. The survival "
        f"branch is invisible again.")
    assert action is not None and getattr(action, "kind", "") in ("cast", "descend", "move"), \
        f"panic returned something that is not a panic action: {action!r}"

    # And it must not have re-recorded the healthy turn's choice.
    repeated = [k for k, v in log.labels.items()
                if not k.startswith("panic") and v > before.get(k, 0)]
    assert not repeated, (
        f"the panic turn incremented {repeated}, which is the previous turn's label. "
        f"`_last_candidates` is stale again.")


def test_forced_returns_the_action_it_was_given(game):
    """Telemetry only. Whatever goes in comes out, by identity, not by equality."""
    brain = UniversalBrain("seeker")
    action = AgentAction("descend")
    assert brain._forced("panic_descend", action) is action
    assert brain._last_forced is True
    assert brain._last_candidates[0][0] == "panic_descend"
    assert brain._last_choice == 0


def test_a_forced_turn_counts_as_a_decision_but_not_as_a_contest():
    """An override did not weigh alternatives, so it must not enter the margin statistics.

    `uncontested_share` means "the cascade offered nothing to weigh against". A panic turn
    means "the cascade never ran". Folding the second into the first would have quietly moved
    a number the AGENT_SPEC health checklist reads.
    """
    log = DecisionLog()

    class FakeBrain:
        _last_candidates = [("explore_unseen", 12.0, None), ("salvage", 4.0, None)]
        _last_choice = 0
        _last_forced = False

    class FakeGame:
        player = None

    scored = FakeBrain()
    log.observe(FakeGame(), scored)
    assert log.labels == {"explore_unseen": 1}
    assert len(log.margins) == 1 and log.forced == 0

    forced = FakeBrain()
    forced._last_candidates = [("panic_flee", 0.0, None)]
    forced._last_forced = True
    log.observe(FakeGame(), forced)

    assert log.labels["panic_flee"] == 1, "the forced turn did not record its label"
    assert log.forced == 1, "the forced turn was not counted as an override"
    assert len(log.margins) == 1, (
        "the forced turn added a margin sample; it never weighed an alternative, so "
        "uncontested_share and median_margin now describe a turn that did not happen")
    assert log.summary()["forced_share"] == 0.5


def test_the_run_summary_carries_the_shape_of_the_ending():
    """hp_tail and max_drop_pct, so a death can be read as burst or attrition."""
    log = DecisionLog()

    class G:
        class player:
            hp = 100
            max_hp = 100

    # More samples than HP_TAIL keeps, so that taking the head instead of the tail is a
    # visible mistake rather than the same list twice.
    trace = [100] * 14 + [96, 90, 88, 40, 12, 0]
    for hp in trace:
        G.player.hp = hp
        log.observe(G(), object())

    out = log.summary()
    assert len(out["hp_tail"]) == HP_TAIL
    assert out["hp_tail"][-3:] == [40, 12, 0], f"hp_tail does not end at the end: {out['hp_tail']}"
    assert 100 not in out["hp_tail"][-6:], "hp_tail is reporting the start of the run"
    assert out["max_drop_pct"] == 48, (
        f"the worst single-turn fall was 88 to 40, so 48, got {out['max_drop_pct']}")
    assert out["critical_share"] == pytest.approx(2 / len(trace)), \
        "turns below 25% HP are not being counted"
