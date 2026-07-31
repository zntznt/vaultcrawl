"""The commune candidate must not be offered on turns the verb cannot fire.

`Game.commune()` requires an elite at Chebyshev distance <= 1. With none it returns `None`,
`dispatch` maps that to False, and no game turn is spent. The brain scored the verb off
`near_hostiles`, which is everything within 3, so on any turn with an elite at distance 2 or
3 it chose an action that could not succeed, the state did not change, and it chose the same
action again.

The fatigue backstop could not save it. Fatigue caps at `FATIGUE_MAX` 60, while commune
scores `25 + late_bonus` where `late_bonus` is `(floor - 19) * 8`: 65 on floor 24, 73 on
floor 26. Above the cap nothing dislodges the candidate, so on deep floors the loop is
permanent rather than merely wasteful. Measured on artisan, which gets deep: 11.38 `decide()`
calls per game turn against 1.01 to 1.03 for every other profile.

The fix narrows the verb to adjacency and adds `commune_approach`, a travel candidate at the
same urgency, so the intent survives the narrowing. Without that second half, nothing in the
cascade moves the agent toward an elite on purpose and the commune win path would have been
deleted rather than repaired, which is the more expensive bug of the two and the one a test
of the narrowing alone would have missed.
"""
from __future__ import annotations

import pytest

from runtime.agent import UniversalBrain
from runtime.entities import Actor
from runtime.game import Game, load_manifest
from runtime.stack import build_systems


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="commune-reach", systems=build_systems())
    g.descend()
    return g


def _only_elite_at(game, dist):
    """Clear the floor and put one tier-3 elite exactly `dist` tiles away."""
    game.actors = [a for a in game.actors if a is game.player]
    p = game.player
    x, y = p.x + dist, p.y
    while not game.level.walkable(x, y) and x < game.level.w - 1:
        x += 1
    elite = Actor(x, y, "E", "Test Elite", 20, 20, 3)
    elite.allegiance = "monster"
    elite.tier = 3
    elite.faction = ""
    elite.source = ""
    game.actors.append(elite)
    return elite


def _labels(game, profile="artisan"):
    brain = UniversalBrain(profile)
    brain.decide(game, game.player)
    return {label for label, _score, _cand in brain._last_candidates}


def _afford(game):
    """Commune wants 2 truths or 4 matter. Give it matter so `can_commune` is true."""
    salv = game.system("salvage")
    assert salv is not None, "no salvage system, so the fixture cannot fund a commune"
    salv.inventory(game).add({"scrap": 6})


def test_commune_is_not_offered_when_the_elite_is_out_of_range(game):
    """The livelock. An elite at distance 3 is inside near_hostiles and outside the verb."""
    _afford(game)
    _only_elite_at(game, 3)
    labels = _labels(game)
    assert "commune" not in labels, (
        "commune was offered with no adjacent elite, so the chosen action spends no turn "
        "and the agent will pick it again from an unchanged state")


def test_the_agent_walks_to_an_out_of_range_elite_instead(game):
    """The other half. Narrowing without this would delete the commune win path."""
    _afford(game)
    _only_elite_at(game, 3)
    assert "commune_approach" in _labels(game), (
        "nothing moves the agent toward an elite, so commune is now unreachable in play "
        "rather than merely unscored")


def test_commune_is_offered_once_the_elite_is_adjacent(game):
    """The narrowing is a range check, not a ban."""
    _afford(game)
    _only_elite_at(game, 1)
    labels = _labels(game)
    assert "commune" in labels, "an adjacent elite did not produce a commune candidate"
    assert "commune_approach" not in labels, (
        "the approach candidate is still offered while already in range, so the agent can "
        "walk away from an elite it could commune with this turn")


def _set_standing(game, faction, value):
    fcs = game.system("factions")
    assert fcs is not None, "no factions system, so the fixture cannot price a commune"
    fcs.standing[faction] = value


def _set_truths(game, n):
    for name in ("marginalia", "history"):
        sys_ = game.system(name)
        if sys_ is not None:
            sys_.read = n
            return
    pytest.skip("no truth-bearing system to set")


def test_commune_is_priced_off_the_elite_in_front_of_you(game):
    """The second livelock, and the same shape as the first.

    The brain used to read `max(standings.values())`, the best standing across every house.
    `Game._commune_discount` reads the standing of the creature actually being communed
    with. Stand next to a creature of a house that hates you while in good odour with some
    other house, and the brain believed it could afford what the verb then refused, without
    the refusal spending a turn.
    """
    elite = _only_elite_at(game, 1)
    elite.faction = "hostile_house"
    _set_standing(game, "hostile_house", -1)   # discount -1, so the commune costs 3 truths
    _set_standing(game, "friendly_house", 4)   # the old code would have read this one
    _set_truths(game, 1)                       # enough at the friendly price, not the real one

    assert "commune" not in _labels(game), (
        "commune was offered against a house that will refuse it, so the chosen action "
        "spends no turn and the agent picks it again from an unchanged state")


def test_an_affordable_neighbour_is_still_communed_with(game):
    """The pricing is a price check, not a ban.

    Standing 2 or 3 gives discount 0, so the commune costs the full 2 truths and the
    creature is still a hostile. Do not raise this to 4 looking for a bigger discount: at 4
    the creature stops being hostile at all, drops out of `near_hostiles`, and the test then
    passes or fails for a reason that has nothing to do with pricing.
    """
    elite = _only_elite_at(game, 1)
    elite.faction = "friendly_house"
    _set_standing(game, "friendly_house", 2)
    _set_truths(game, 2)

    assert "commune" in _labels(game), "an affordable commune was not offered"


def test_a_broke_agent_is_not_offered_the_boss_commune(game):
    """The boss-floor override that made the loop permanent.

    `can_commune` used to be forced true whenever a boss was near on floor 26+, so that the
    win condition was always attempted. The boss path has its own affordability check and
    also returns without spending a turn, so "always try" meant "try forever", and at
    25 + 48 late + 100 boss = 173 the fatigue ceiling of 60 could not touch it.
    """
    game.floor = 26
    boss = _only_elite_at(game, 1)
    boss.is_boss = True
    boss.faction = "hostile_house"
    _set_standing(game, "hostile_house", -1)
    _set_truths(game, 0)

    labels = _labels(game)
    assert "commune" not in labels, (
        "a broke agent is still offered a boss commune the game will refuse, which is an "
        "unbreakable loop at that score")


@pytest.mark.parametrize("profile", ["artisan", "cartographer", "emergent",
                                     "exploiter", "seeker", "whisper"])
def test_every_profile_gets_the_same_reach(game, profile):
    """Berlin: the range check is state, so it must read identically for all six."""
    _afford(game)
    _only_elite_at(game, 1)
    assert "commune" in _labels(game, profile), f"{profile} cannot reach commune in range"
