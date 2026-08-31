"""Every locus activation must finish, and finishing means the heal and the consume.

There was no test file for `runtime/loci.py` at all, which is how five of the seven
activation handlers came to call `heal_body` with no import in scope. `heal_body` was
imported inside `_activate_becalm` and nowhere else, so `forge`, `parley`, `explore`,
`shield` and `commune` each raised NameError partway through, after their effect but before
their heal and before `_consume`.

Nothing reported it. `LocusSystem.on_player_act` runs inside `game.try_move`, which the
agent reaches through `dispatch`, and `dispatch` wraps its body in `except Exception:
return False`. So a locus that crashed looked exactly like a move the game declined. One
seed of six runs swallowed 157 of them.

The cost is the heal: 5, 5, 3, 3 and 10 HP that never arrived. This project's own death
analysis says losses are attrition rather than burst, that no run in 288 ever took a 50%
hit, and that every dying run spent dozens of turns below 25% HP. A silently dead heal is
the worst possible bug to have in that game.
"""
from __future__ import annotations

import pytest

from runtime.game import Game, load_manifest
from runtime.loci import LocusSystem

# (handler, expected heal). `fight` heals nothing by design: it spawns a Sentinel.
HEALERS = [("_activate_forge", 5), ("_activate_parley", 5), ("_activate_explore", 3),
           ("_activate_shield", 3), ("_activate_commune", 10), ("_activate_becalm", 5)]


def _game():
    g = Game(load_manifest("examples/world.json"))
    g.player.hp = max(1, g.player.max_hp // 2)   # room to heal into
    return g


def _locus(g):
    lx, ly = g.player.x + 3, g.player.y
    return lx, ly, {"type": None}


@pytest.mark.parametrize("handler,heal", HEALERS)
def test_every_activation_heals_and_consumes(handler, heal):
    """The heal is the point, and `_consume` is the proof the handler reached its end."""
    g = _game()
    sys = LocusSystem()
    lx, ly, locus = _locus(g)
    sys.loci = {(lx, ly): locus}
    before = g.player.hp
    getattr(sys, handler)(g, lx, ly, locus)
    assert g.player.hp > before, (
        f"{handler} healed nothing. It is supposed to give {heal} HP, and if it raised on "
        f"the way there `dispatch` would report the move as declined rather than crashed")
    assert locus.get("depleted"), (
        f"{handler} never reached `_consume`, so it exited early: everything after its "
        f"heal was skipped")


def test_the_fight_locus_spawns_rather_than_heals():
    """The negative control. If every handler passed the test above by healing, the test
    would also pass on a build where `_activate_fight` had been quietly given a heal."""
    g = _game()
    sys = LocusSystem()
    lx, ly, locus = _locus(g)
    before_hp, before_actors = g.player.hp, len(g.actors)
    sys._activate_fight(g, lx, ly, locus)
    assert g.player.hp == before_hp, "the fight locus is not a heal"
    assert len(g.actors) == before_actors + 1, "the fight locus must spawn its Sentinel"
    assert locus.get("depleted")


def test_heal_body_is_in_module_scope_not_one_function():
    """The exact shape of the bug: an import that only one of six handlers could see."""
    import runtime.loci as L
    assert callable(getattr(L, "heal_body", None)), (
        "`heal_body` is not a module-level name in runtime.loci, so any handler without a "
        "local import raises NameError, and dispatch will report that as a refused move")


def test_activation_is_reached_through_a_move_and_a_crash_would_be_swallowed():
    """The premise that made this invisible, asserted rather than assumed.

    If `dispatch` ever stops swallowing, this test should be revisited, not deleted: the
    swallow is what turned a crash into a silent no-op.
    """
    import inspect

    from runtime.agent_action import dispatch
    assert "except Exception" in inspect.getsource(dispatch)
