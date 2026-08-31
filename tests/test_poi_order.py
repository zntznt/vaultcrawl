"""The agent walks to the nearest point of interest, not to whichever system listed first.

`sense.points_of_interest` concatenates each system's list in STACK ORDER and the brain takes
`pois[0]`, so which point an agent crossed a floor for was decided by where its provider
happened to sit in the system list.

Measured on a real seeker run, over 400 sampled decisions that had more than one candidate:
the chosen point was the nearest **zero** times, median distance 9 against a nearest of 2,
with a median of 23 on offer.

Two things follow. The agent walked past closer things to reach further ones, and any system
whose list is appended late was unreachable in practice however correctly it placed. The second
is what kept the renunciation shrine dead even after its depth gate was fixed: it sits at stack
index 19 behind loci, caches and salvage, so its tiles never once reached the front of the list.

The cache list ten lines above this in `agent_perception` already sorts by exactly this
distance, which is the best evidence available for what the intent was.
"""
from __future__ import annotations

from runtime.agent_perception import agent_state
from runtime.game import Game, load_manifest
from runtime.stack import build_systems, register_brains


class _FarFirst:
    """A system that offers a far tile, standing in for one early in the stack."""
    name = "farfirst"

    def points_of_interest(self, game):
        return [(game.player.x + 20, game.player.y + 12)]

    def __getattr__(self, _n):
        return lambda *a, **k: None


class _NearLast:
    """A system that offers a near tile, standing in for one late in the stack."""
    name = "nearlast"

    def points_of_interest(self, game):
        return [(game.player.x + 2, game.player.y)]

    def __getattr__(self, _n):
        return lambda *a, **k: None


def _game():
    register_brains()
    return Game(load_manifest("examples/world.json"), systems=build_systems())


def _dist(game, pt):
    return max(abs(pt[0] - game.player.x), abs(pt[1] - game.player.y))


def test_the_first_poi_is_the_nearest_one():
    g = _game()
    g.systems = [_FarFirst(), _NearLast()] + list(g.systems)
    pois = agent_state(g, g.player)["pois"]
    assert pois, "no points of interest at all, so this test proves nothing"
    assert _dist(g, pois[0]) == min(_dist(g, p) for p in pois), (
        f"pois[0] is {_dist(g, pois[0])} tiles away and the nearest is "
        f"{min(_dist(g, p) for p in pois)}, so the brain is picking by stack order")


def test_a_late_system_can_win_the_slot_when_it_is_closer():
    """The reachability half. Without this, placing a thing correctly is not enough."""
    g = _game()
    g.systems = [_FarFirst()] + list(g.systems) + [_NearLast()]
    near = (g.player.x + 2, g.player.y)
    pois = agent_state(g, g.player)["pois"]
    assert pois[0] == near or _dist(g, pois[0]) <= _dist(g, near), (
        "a tile two steps away, contributed by the last system in the stack, lost to "
        "something further off, so late systems remain unreachable")


def test_the_whole_list_is_ordered_not_just_its_head():
    """The brain takes pois[0] today. If it ever takes pois[:3], that must mean something."""
    g = _game()
    g.systems = [_FarFirst(), _NearLast()] + list(g.systems)
    d = [_dist(g, p) for p in agent_state(g, g.player)["pois"]]
    assert d == sorted(d), f"points of interest are not distance-ordered: {d[:12]}"


def test_ordering_does_not_drop_or_invent_points():
    """A sort must be a permutation. Losing a tile here silently unreaches a system."""
    from runtime.sense import points_of_interest

    g = _game()
    g.systems = [_FarFirst(), _NearLast()] + list(g.systems)
    assert sorted(agent_state(g, g.player)["pois"]) == sorted(points_of_interest(g))
