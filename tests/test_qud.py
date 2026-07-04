"""The Qud layer: body verbs, companions, legendary personalities, secret trading."""
from __future__ import annotations

import random

from runtime.abilities import player_cast
from runtime.entities import Actor
from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem
from runtime.marginalia import MarginaliaSystem
from runtime.negotiate import Parley
from runtime.quality import QualitySystem
from runtime.salvage import SalvageSystem
from runtime.factions import FactionSystem


def _game(*systems):
    return Game(load_manifest("examples/world.json"), sandbox=True,
                systems=list(systems))


def _foe(g, **kw):
    a = Actor(x=g.player.x + 1, y=g.player.y, glyph="s", name="test shade",
              hp=9, max_hp=9, atk=1, **kw)
    g.actors.append(a)
    return a


def test_body_verbs_are_castable():
    g = _game()
    g.player._special_actions = ["enrage", "shield"]
    atk, dfn = g.player.atk, g.player.defense
    assert player_cast(g, "enrage") and g.player.atk == atk + 1
    assert player_cast(g, "shield") and g.player.defense == dfn + 1


def test_player_spit_kills_and_credits():
    g = _game()
    g.actors = []
    foe = _foe(g)
    foe.hp = 1
    kills = g.kills
    assert player_cast(g, "spit")
    assert foe not in g.actors and g.kills == kills + 1


def test_player_summon_makes_a_companion():
    g = _game()
    before = set(map(id, g.actors))
    assert player_cast(g, "summon")
    child = next(a for a in g.actors if id(a) not in before)
    assert child.allegiance == "companion"
    assert not g.hostile(g.player, child)


def test_recruit_walks_with_you():
    from runtime import brains  # noqa: F401  (registers the companion brain)
    g = _game()
    g.actors = []
    foe = _foe(g, source="stoicism")
    foe.faction = "faction_0"
    g.recruit(foe)
    assert foe.allegiance == "companion"
    assert not g.hostile(g.player, foe)
    enemy = _foe(g)
    enemy.faction = "faction_other"
    assert g.hostile(foe, enemy), "a companion fights what you fight"
    # far from you with no enemy in reach, it closes the distance
    g.actors = [foe]
    foe.x, foe.y = g.player.x, g.player.y
    for dx in range(1, 8):
        if g.level.walkable(g.player.x + dx, g.player.y):
            foe.x = g.player.x + dx
    if max(abs(foe.x - g.player.x), abs(foe.y - g.player.y)) > 2:
        d = foe.brain.decide(g, foe)
        assert d != (0, 0), "an idle companion keeps to your side"


def test_legend_is_a_person():
    g = _game(QualitySystem(), SalvageSystem())
    foe = _foe(g, source="stoicism")
    q = g.system("quality")
    q._enlegend(g, foe, random.Random(7))
    assert getattr(foe, "_legend", False)
    assert '"' in foe.name, f"a legend takes a personal name: {foe.name}"
    p = Parley(g, foe, fickle=False)
    plain = Parley(g, _foe(g, source="stoicism"), fickle=False)
    assert p.goal == plain.goal - 1, "legends like to talk"
    p.disposition = -5
    p.outcome = "enraged"
    p.resolve(g, foe)
    assert not getattr(foe, "_enraged", False), "a legend holds no grudge"
    # its fall leaves a relic: the broke event reaches salvage
    salv = g.system("salvage")
    ground = len(salv.ground)
    g.kill(foe, "melee")
    assert len(salv.ground) > ground, "the fallen legend left its relic to salvage"


def test_confide_trades_secrets():
    g = _game(KnowledgeSystem(), MarginaliaSystem(), FactionSystem())
    g.actors = []
    friend = _foe(g, source="stoicism")
    friend.faction = "faction_0"
    g._join_wild(friend)
    assert not g.confide(friend), "nothing read, nothing to trade"
    g.system("marginalia").read = 2
    assert g.confide(friend)
    assert g.system("knowledge").is_known("stoicism")
    assert g.system("factions").standing.get("faction_0") == 1
    assert not g.confide(friend), "each creature shares its note once"


if __name__ == "__main__":
    for fn in (test_body_verbs_are_castable, test_player_spit_kills_and_credits,
               test_player_summon_makes_a_companion, test_recruit_walks_with_you,
               test_legend_is_a_person, test_confide_trades_secrets):
        fn()
        print(f"ok {fn.__name__}")
