"""Do not offer a stair that will not open.

`Game.egress_ready()` gates the final descent on four routes: the warden dead, the warden
communed with, `EGRESS_TRUTHS` truths carried, or `EGRESS_STANDING` with its house. Descending
onto that stair with none of them satisfied refuses, and the refusal spends no turn.

Measured over 288 runs before this gate existed: **13 runs reached floor 26, stood on the shut
stair, and chose `descend` for 83.5% to 94.2% of every decision they had left. None won.** One
spent 10,573 turns there. Several were a single point of standing short of a route they never
went and took. The aggregate table cannot see this: a stalled run's `turns_survived` looks
completely ordinary, and the runs were found by scanning per-run label histograms.

Three sites needed the gate, and the third is the expensive one:

  - the stairs branch, scored on `stairs`
  - the faction de-escalation branch, a flat 50 on the stair and 40 walking to it
  - PANIC's `panic_descend`, a **forced override** that returns before the candidate list
    exists. A hard override cannot be outscored, so three of the thirteen wore that label and
    no amount of scoring elsewhere would have saved them.

The trap this file mostly exists to prevent: **`egress_ready` alone is the wrong condition.**
The snapshot reports it on every floor while it describes the last stair only, so it already
reads False on floor 2. Gating descent on the flag by itself walls the agent in on the second
floor and every run ends at once. The condition is the boss floor specifically.
"""
from __future__ import annotations

import pytest

from runtime.agent import UniversalBrain
from runtime.agent_perception import agent_state
from runtime.game import Game, load_manifest
from runtime.stack import build_systems

DESCEND_LABELS = {"descend", "panic_descend", "deesc_stairs", "stairs"}


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="egress-gate", systems=build_systems())
    g.descend()
    return g


def _labels(game, profile="seeker"):
    brain = UniversalBrain(profile)
    brain.decide(game, game.player)
    return {label for label, _score, _cand in brain._last_candidates}


def _stand_on_stairs(game):
    """Put the player on this floor's down staircase."""
    from runtime.tactics import _stairs
    st = _stairs(game)
    if st is None:
        pytest.skip("no staircase on this floor to stand on")
    game.player.x, game.player.y = st[0], st[1]
    assert agent_state(game, game.player)["position"]["on_stairs"], "fixture is not on stairs"


def test_the_shut_final_stair_is_not_offered(game):
    """The livelock. At the boss floor with the gate shut, no stair candidate at all."""
    game.floor = game.max_floor
    _stand_on_stairs(game)
    s = agent_state(game, game.player)
    assert not s["position"]["egress_ready"], "fixture has the gate open, so it tests nothing"

    offered = _labels(game) & DESCEND_LABELS
    assert not offered, (
        f"the agent is still offered {sorted(offered)} on a stair that will refuse it, which "
        f"spends no turn and repeats from an unchanged state")


def test_de_escalation_does_not_walk_to_the_shut_stair(game):
    """The third site, which needs `kills >= 4` to exist at all.

    Without that precondition in the fixture this branch is simply never built, and a revert
    of its gate passes every other test in this file. It scores a flat 50 on the stair and 40
    walking toward it, both above most of what would otherwise pursue the four routes.
    """
    game.floor = game.max_floor
    game.kills = 5
    _stand_on_stairs(game)
    game.actors = [a for a in game.actors if a is game.player]   # de-escalation wants no melee
    s = agent_state(game, game.player)
    assert not s["adjacent_hostiles"], "fixture still has an adjacent hostile"
    assert not s["position"]["egress_ready"], "fixture has the gate open, so it tests nothing"

    offered = _labels(game) & DESCEND_LABELS
    assert not offered, (
        f"faction de-escalation still offers {sorted(offered)} at a stair that will refuse it")


def test_panic_does_not_force_a_descent_onto_the_shut_stair(game):
    """The forced override, which no scoring change could have rescued."""
    game.floor = game.max_floor
    _stand_on_stairs(game)
    p = game.player
    p.hp = max(1, int(p.max_hp * 0.10))   # deep into PANIC for every profile

    brain = UniversalBrain("cartographer")
    action = brain.decide(game, p)
    label = brain._last_candidates[brain._last_choice][0] if brain._last_choice is not None else "-"
    assert label != "panic_descend", (
        "PANIC still hard-overrides onto a stair that will not open, and a forced branch "
        "cannot be outscored by anything")
    assert getattr(action, "kind", "") != "descend", f"panic still returned a descend: {action}"


def test_ordinary_floors_still_descend(game):
    """The trap. `egress_ready` is False on floor 2 as well, and must not gate anything there."""
    s = agent_state(game, game.player)
    assert s["position"]["floor"] < s["position"]["boss_floor"], "fixture is on the boss floor"
    assert not s["position"]["egress_ready"], (
        "this test is only meaningful while the flag reads False off the boss floor, which is "
        "exactly the condition that makes gating on it alone a mistake")

    _stand_on_stairs(game)
    offered = _labels(game) & DESCEND_LABELS
    assert offered, (
        "no stair candidate on an ordinary floor: the gate is reading `egress_ready` without "
        "checking the boss floor, and the agent is now walled in from floor 2")


@pytest.mark.parametrize("route", ["warden", "truths"])
def test_the_open_final_stair_is_still_offered(game, route):
    """The gate is a gate, not a wall.

    This is the test that matters most, because the failure it guards is worse than the bug
    being fixed: a gate that never opens makes the descent victory unreachable and every run
    a loss. It must not be allowed to skip its way to green, so it drives two of the four
    routes rather than the one that happened to be convenient.
    """
    game.floor = game.max_floor
    _stand_on_stairs(game)
    assert not _labels(game) & DESCEND_LABELS, "fixture did not start shut"

    if route == "warden":
        game._boss_felled = True
    else:
        need = game.egress_truths_needed()
        sys_ = game.system("marginalia") or game.system("history")
        assert sys_ is not None, "no truth-bearing system to satisfy the truths route"
        sys_.read = need

    s = agent_state(game, game.player)
    assert s["position"]["egress_ready"], (
        f"the {route} route did not open the gate, so this asserts nothing")
    assert _labels(game) & DESCEND_LABELS, (
        f"the final stair stayed shut after satisfying the {route} route, so the gate has "
        f"become a wall and the descent victory is unreachable")
