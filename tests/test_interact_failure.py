"""A failed interact must cost nothing and still be visible.

Those pull in opposite directions and both matter. Pressing `interact` on empty ground should
not cost a player their turn. But an action the brain cannot tell has failed is one it will
choose again from an unchanged state, which is a livelock.

Measured: one agent spent **74.2% of its decisions on `interact` at 3.75 decisions per game
turn**, standing in weather it could not afford to clear. `dispatch` returned `True`
unconditionally, so `note_result` was never told, and the 15-point `FATIGUE_FAILED` penalty
that exists for exactly this case never applied. `Game.interact`, `clear_weather` and
`repair_part` all returned `None` on every path, success and failure alike, so there was
nothing to report even if dispatch had asked.

This is the fourth instance in this codebase of one shape: a candidate's reachability test
drifting from the precondition of the verb it chooses. The brain offers `interact` when
`commune_landmark()` is truthy; `interact()` checks keepers, then weather, then corpses, then
handlers, returning early at each. The two can disagree in both directions, and here they did.

What this pins:

  1. A failed interact spends no turn. This is the half a player feels.
  2. A failed interact returns False, and `dispatch` passes that on. This is the half the
     brain needs.
  3. A successful interact still returns True and still spends its turn.
  4. `note_result(False)` actually penalises the objective, so reporting failure has teeth.
"""
from __future__ import annotations

import pytest

from runtime.agent import FATIGUE_FAILED, UniversalBrain
from runtime.agent_action import AgentAction, dispatch
from runtime.game import Game, load_manifest
from runtime.stack import build_systems


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="interact-failure", systems=build_systems())
    g.descend()
    g.turn = 50
    return g


def _nothing_to_do(game):
    """Strip every branch `interact` checks, so it must fall through to 'nothing here'."""
    game.actors = [a for a in game.actors if a is game.player]
    w = game.system("weather")
    if w is not None:
        w.weather = ""
        if hasattr(w, "props"):
            w.props.clear()
    d = game.system("decay")
    if d is not None and hasattr(d, "corpses"):
        d.corpses.clear()
    game._wild_structs = {}


def test_a_failed_interact_spends_no_turn(game):
    """The half a player feels. Pressing it on empty ground is free."""
    _nothing_to_do(game)
    before = game.turn
    game.interact()
    assert game.turn == before, (
        "a failed interact cost a turn, so pressing it on empty ground punishes the player")


def test_a_failed_interact_reports_failure(game):
    """The half the brain needs. Without this it re-chooses from an unchanged state."""
    _nothing_to_do(game)
    assert game.interact() is False, "interact claims success when nothing handled it"
    assert dispatch(game, AgentAction("interact")) is False, (
        "dispatch still hardcodes True, so note_result is never told and FATIGUE_FAILED "
        "never applies")


def test_an_unaffordable_weather_clear_is_a_failure(game):
    """The exact situation that stalled: weather present, no matter to clear it with."""
    salv = game.system("salvage")
    if salv is None:
        pytest.skip("no salvage system to empty")
    salv.inventory(game).comp.clear()
    structures = game.system("structures")
    if structures is not None and hasattr(structures, "crystals"):
        structures.crystals.clear()
    assert game.clear_weather() is False, (
        "clear_weather reports success with nothing to pay with, so interact inherits a "
        "false positive")
    assert dispatch(game, AgentAction("interact")) is False


def test_note_result_penalises_the_objective():
    """Reporting failure has to have teeth, or reporting it changes nothing."""
    brain = UniversalBrain("artisan")
    brain._last_key = ("interact",)
    before = brain._fatigue.get(("interact",), 0.0)
    brain.note_result(False)
    after = brain._fatigue.get(("interact",), 0.0)
    assert after == pytest.approx(before + FATIGUE_FAILED), (
        f"a reported failure moved fatigue from {before} to {after}, so the brain will keep "
        f"choosing the objective that just failed")
    brain.note_result(True)
    assert brain._fatigue.get(("interact",), 0.0) == pytest.approx(after), (
        "success is charging a penalty too")


def test_a_working_interact_still_costs_its_turn(game):
    """The gate must not become a ban: real interactions still resolve and still cost."""
    salv = game.system("salvage")
    if salv is None:
        pytest.skip("no salvage system")
    salv.inventory(game).add({"scrap": 5})
    w = game.system("weather")
    if w is None:
        pytest.skip("no weather system")
    w.weather = "acrid haze"
    before = game.turn
    assert game.clear_weather() is True, "an affordable weather clear reported failure"
    assert game.turn > before, "a successful interaction did not spend its turn"


def test_the_crystal_route_works_for_an_agent_with_no_matter():
    """`clear_weather`'s no-matter fallback called a set method on a dict.

    The path exists so a broke agent can still clear weather: stand on a crystal and channel
    it. `StructureSystem.crystals` is a dict of (x, y) -> growth, and this said
    `crystals.discard(pos)`, which dicts do not have. AttributeError, every time, propagating
    out of `interact` into `dispatch`'s `except Exception` and arriving at the brain as an
    ordinary refusal.

    So the route reserved for the poorest agent was the one route that never worked, and
    nothing in the verb accounting could say so: `clear_weather` fails legitimately all the
    time when there is no weather, so `interact` never showed as broken.
    """
    from runtime.game import Game, load_manifest
    from runtime.structures import StructureSystem

    st = StructureSystem()
    g = Game(load_manifest("examples/world.json"), systems=[st])
    assert isinstance(st.crystals, dict), (
        "crystals stopped being a dict, so the fix below needs re-deriving rather than "
        "trusting")

    salv = g.system("salvage")
    if salv is not None:
        salv.inventory(g).comp.clear()          # the whole premise: no matter
    pos = (g.player.x, g.player.y)
    st.crystals[pos] = 0

    g.clear_weather()                            # must not raise
    assert pos not in st.crystals, (
        "the crystal was not consumed, so the no-matter route did not run")


def test_clearing_without_matter_or_a_crystal_still_just_refuses():
    """The control for the test above: removing the crash must not make the route free."""
    from runtime.game import Game, load_manifest
    from runtime.structures import StructureSystem

    st = StructureSystem()
    g = Game(load_manifest("examples/world.json"), systems=[st])
    salv = g.system("salvage")
    if salv is not None:
        salv.inventory(g).comp.clear()
    st.crystals.clear()
    assert g.clear_weather() is False
