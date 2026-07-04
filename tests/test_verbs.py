"""The interactive verbs that surface baked flavor: wait, examine, first-blood reveal."""
from __future__ import annotations

from runtime.game import Game, load_manifest


def _game():
    return Game(load_manifest("examples/world.json"))


def test_region_flavor_logged_on_first_entry():
    g = _game()
    region = g.region_for(1)
    assert region.get("flavor"), "sample world regions should carry flavor"
    assert region["flavor"] in g.messages
    # once per region, not per floor
    before = g.messages.count(region["flavor"])
    g.descend()
    assert g.messages.count(region["flavor"]) == before


def test_wait_advances_turn_without_moving_or_noise():
    g = _game()
    noises = []
    orig = g.emit
    g.emit = lambda etype, **d: (noises.append(etype) if etype == "noise" else None,
                                 orig(etype, **d))
    pos, turn = (g.player.x, g.player.y), g.turn
    g.wait()
    assert (g.player.x, g.player.y) == pos
    assert g.turn == turn + 1
    assert not noises, "waiting is quiet"


def test_examine_reveals_region_and_nearby_foes():
    g = _game()
    foe = next(a for a in g.actors if a.flavor)
    foe.x, foe.y = g.player.x + 1, g.player.y   # place it in view
    turn = g.turn
    g.examine()
    assert g.turn == turn, "examine is a free action"
    assert any(g.region_name in m for m in g.messages)
    assert any(foe.flavor in m for m in g.messages)


def test_first_blood_reveals_flavor_once():
    g = _game()
    foe = next(a for a in g.actors if a.flavor)
    foe.hp = foe.max_hp = 99   # survive two hits
    g.attack(g.player, foe)
    g.attack(g.player, foe)
    assert g.messages.count(foe.flavor) == 1


if __name__ == "__main__":
    for fn in (test_region_flavor_logged_on_first_entry,
               test_wait_advances_turn_without_moving_or_noise,
               test_examine_reveals_region_and_nearby_foes,
               test_first_blood_reveals_flavor_once):
        fn()
        print(f"ok {fn.__name__}")
