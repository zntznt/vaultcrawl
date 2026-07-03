"""Non-violent approaches to hostiles: understanding, offering, distraction."""
from __future__ import annotations

from runtime.entities import Actor, make_boss
from runtime.game import BECALM_COST, Game, load_manifest
from runtime.knowledge import KnowledgeSystem
from runtime.salvage import SalvageSystem, inv


def _game():
    return Game(load_manifest("examples/world.json"),
                systems=[SalvageSystem(), KnowledgeSystem()])


def _foe(g, tier=1):
    foe = next(a for a in g.actors if a.allegiance == "monster" and not a.is_boss)
    foe.tier = tier
    return foe


def test_understanding_disarms_for_free():
    g = _game()
    foe = _foe(g)
    g.system("knowledge")._reveal(g, foe.source, direct=True)
    assert g.becalm(foe)
    assert foe.allegiance == "wild"
    assert not g._hostile("player", foe.allegiance)
    assert inv(g.player).total() == 0, "understanding costs nothing"


def test_offering_placates():
    g = _game()
    foe = _foe(g, tier=2)
    inv(g.player).add({"brass": 5})
    assert g.becalm(foe)
    assert foe.allegiance == "wild"
    assert inv(g.player).total() == 5 - BECALM_COST * 2


def test_empty_handed_and_unknowing_is_refused():
    g = _game()
    foe = _foe(g)
    assert not g.becalm(foe)
    assert foe.allegiance == "monster"


def test_bosses_are_communions_business():
    g = _game()
    spec = max(g.m["bosses"], key=lambda b: b["depth"])
    boss = make_boss(spec, g.player.x + 1, g.player.y)
    g.actors.append(boss)
    inv(g.player).add({"brass": 99})
    assert not g.becalm(boss)


def test_toss_makes_noise_where_it_lands():
    g = _game()
    inv(g.player).add({"vellum": 2})
    g.actors = [a for a in g.actors
                if abs(a.x - g.player.x) + abs(a.y - g.player.y) > 6]
    noises = []
    orig = g.emit
    g.emit = lambda etype, **d: (noises.append(d) if etype == "noise" else None,
                                 orig(etype, **d))
    assert g.toss(1, 0)
    assert inv(g.player).total() == 1, "a toss spends 1 matter"
    (noise,) = noises
    assert noise["pos"] != (g.player.x, g.player.y), "the clatter is away from you"
    assert noise["volume"] >= 8


def test_toss_needs_matter():
    g = _game()
    assert not g.toss(1, 0)


if __name__ == "__main__":
    for fn in (test_understanding_disarms_for_free, test_offering_placates,
               test_empty_handed_and_unknowing_is_refused,
               test_bosses_are_communions_business,
               test_toss_makes_noise_where_it_lands, test_toss_needs_matter):
        fn()
        print(f"ok {fn.__name__}")
