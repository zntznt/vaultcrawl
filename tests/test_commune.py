"""Communion: the deepest thought can be integrated, not just slain."""
from __future__ import annotations

from runtime.entities import make_boss
from runtime.game import COMMUNE_COST, Game, load_manifest
from runtime.history import HistorySystem
from runtime.marginalia import MarginaliaSystem
from runtime.salvage import SalvageSystem, inv


def _game():
    g = Game(load_manifest("examples/world.json"),
             systems=[SalvageSystem(), HistorySystem(), MarginaliaSystem()])
    spec = max(g.m["bosses"], key=lambda b: b["depth"])
    boss = make_boss(spec, g.player.x + 1, g.player.y)   # the finale, beside you
    g.actors.append(boss)
    return g, boss


def test_not_adjacent_returns_none():
    g, boss = _game()
    boss.x, boss.y = g.player.x + 5, g.player.y
    assert g.commune() is None and not g.won


def test_unknown_refuses():
    g, boss = _game()
    assert g.commune() is False
    assert not g.won and boss in g.actors


def test_truths_path_wins_without_a_kill():
    g, boss = _game()
    g.system("marginalia").read = 2
    g.system("history").read = 1
    kills = g.kills
    assert g.commune() is True
    assert g.won and boss not in g.actors and g.kills == kills


def test_offering_path_spends_matter():
    g, boss = _game()
    bag = inv(g.player)
    bag.add({"brass": 6, "vellum": 6})
    assert g.commune() is True
    assert g.won and bag.total() == 12 - COMMUNE_COST


def test_the_old_way_still_works():
    g, boss = _game()
    boss.hp = 1
    g.attack(g.player, boss)
    assert g.won, "felling the deepest boss still wins"


if __name__ == "__main__":
    for fn in (test_not_adjacent_returns_none, test_unknown_refuses,
               test_truths_path_wins_without_a_kill, test_offering_path_spends_matter,
               test_the_old_way_still_works):
        fn()
        print(f"ok {fn.__name__}")
