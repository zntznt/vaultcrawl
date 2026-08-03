"""A chronicle's ascendancies must bite where the player can meet them.

Upheaval was applied uniformly to every floor. The player's power is not uniform: on floor 3
they have nothing, and by floor 20 they have sigils, standing and a forge. So an empowered
creature is lethal early and routine late, and a world that remembers lands almost all of its
added difficulty on the stretch that can least absorb it.

Measured, 144 chained runs against 144 cold ones on identical seeds:

  runs ending at floor <= 10   warm 44%   cold 24%
  median floor                 warm 12    cold 22
  deaths                       warm 67%   cold 55%

and the paired floor deficit scaled with how much memory was inherited: -2.0 floors at 8
events, -3.6 at 11, -5.5 at 12, -4.2 at 13. A dose-response like that is the upheaval doing
it, not a coincidence of seeds.

`UPHEAVAL_EMPOWER_DEPTH` gates empowerment to the deeper part of the descent. Waning is
deliberately NOT gated: it makes the world kinder, and rationing relief in the stretch that
is already lethal would be exactly backwards. That asymmetry is the design decision this
file exists to make explicit, so nobody later "fixes" it into symmetry without knowing.

The other half of the change is that all four spawn sites now call `apply_upheaval` instead
of repeating `if ascended: empower elif waned: diminish`. Three copies of a rule is how the
egress gate got missed at two sites out of three, and how commune got fixed for range and
not for price.
"""
from __future__ import annotations

import pytest

from runtime.entities import Actor
from runtime.game import UPHEAVAL_EMPOWER_DEPTH, Game, load_manifest
from runtime.stack import build_systems
from runtime.upheaval import Upheaval


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="upheaval-depth", systems=build_systems())
    g.descend()
    return g


def _creature(game, src="rust"):
    a = Actor(1, 1, "M", "Test Monster", 10, 10, 3)
    a.source = src
    a.allegiance = "monster"
    return a


def test_an_ascendancy_does_not_bite_in_the_shallows(game):
    game.up = Upheaval.from_events([{"kind": "idea_ascends", "note": "rust"}])
    game.floor = 1
    a = _creature(game)
    before = (a.max_hp, a.atk)
    assert game.apply_upheaval(a, "rust") == "too_shallow"
    assert (a.max_hp, a.atk) == before, (
        "an empowered creature appeared on floor 1, where the player has nothing to meet it "
        "with. This is where 44% of warm runs ended.")


def test_the_same_ascendancy_bites_in_the_depths(game):
    game.up = Upheaval.from_events([{"kind": "idea_ascends", "note": "rust"}])
    game.floor = game.max_floor
    a = _creature(game)
    before = (a.max_hp, a.atk)
    assert game.apply_upheaval(a, "rust") == "empowered"
    assert (a.max_hp, a.atk) != before, (
        "the gate has become a ban: ascendancies never take effect anywhere, so the world's "
        "memory can no longer make anything harder at all")


def test_waning_is_not_gated(game):
    """The asymmetry, stated as a decision rather than left as an accident."""
    game.up = Upheaval.from_events([{"kind": "power_wanes", "note": "rust"}])
    game.floor = 1
    a = _creature(game)
    before = a.max_hp
    assert game.apply_upheaval(a, "rust") == "diminished"
    assert a.max_hp < before, (
        "waning was gated along with empowerment, which rations relief in exactly the "
        "stretch of the descent that the measurement says is already lethal")


def test_the_gate_scales_with_the_descent(game):
    """Derived from `max_floor`, not a hardcoded floor number."""
    assert game.empower_floor() == max(1, int(game.max_floor * UPHEAVAL_EMPOWER_DEPTH))
    game.max_floor = 100
    assert game.empower_floor() > 10, (
        "the threshold does not scale, so on a long descent the whole early game is "
        "unprotected again")


def test_an_untouched_note_is_left_alone(game):
    game.up = Upheaval.from_events([{"kind": "idea_ascends", "note": "rust"}])
    game.floor = game.max_floor
    a = _creature(game, src="ecs")
    before = (a.max_hp, a.atk)
    assert game.apply_upheaval(a, "ecs") == "untouched"
    assert (a.max_hp, a.atk) == before


def test_every_spawn_site_uses_the_helper():
    """The rule lives in one place, because three copies is how two get missed."""
    src = open("runtime/game.py", encoding="utf-8").read()
    body = src.split("def apply_upheaval", 1)[1]
    body = body.split("\n    def ", 1)[1] if "\n    def " in body else body
    assert "empower(en)" not in body and "diminish(en)" not in body, (
        "a spawn site still calls empower/diminish directly, so it bypasses the depth gate")
