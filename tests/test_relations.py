"""Faction-aware hostility + embodiment: no entity is a special kind of thing."""
from __future__ import annotations

from runtime.entities import Actor
from runtime.game import FRIEND_STANDING, Game, load_manifest
from runtime.play import embody


def _game(**kw):
    return Game(load_manifest("examples/world.json"), sandbox=True, **kw)


def _actor(faction="", allegiance="monster", **kw):
    base = dict(x=1, y=1, glyph="s", name="t", hp=5, max_hp=5, atk=1)
    base.update(kw)
    a = Actor(**base)
    a.faction = faction
    a.allegiance = allegiance
    return a


def test_kin_never_fight():
    g = _game()
    assert not g.hostile(_actor("faction_0"), _actor("faction_0"))


def test_rival_houses_war():
    g = _game()
    g._rel[("faction_0", "faction_1")] = "rival"
    assert g.hostile(_actor("faction_0"), _actor("faction_1"))
    g._rel[("faction_0", "faction_1")] = "neutral"
    assert not g.hostile(_actor("faction_0"), _actor("faction_1"))


def test_spawned_creatures_carry_their_house():
    g = _game()
    factions = {a.faction for a in g.actors if a.allegiance == "monster"}
    assert factions and all(factions), "every spawned hostile belongs to a house"


def test_reputation_befriends_a_house():
    from runtime.factions import FactionSystem
    g = Game(load_manifest("examples/world.json"), sandbox=True,
             systems=[FactionSystem()])
    foe = next(a for a in g.actors if a.allegiance == "monster" and a.faction)
    assert g.hostile(g.player, foe), "a stranger house starts hostile"
    g.system("factions").standing[foe.faction] = FRIEND_STANDING
    assert not g.hostile(g.player, foe), "reputation makes the house a friend"


def test_wildlife_and_npc_rules_hold():
    g = _game()
    wild = _actor(allegiance="wild")
    npc = _actor(allegiance="npc")
    mon = _actor("faction_0")
    assert g.hostile(wild, mon) and g.hostile(mon, wild)
    assert not g.hostile(wild, g.player)
    assert not g.hostile(npc, mon) and not g.hostile(g.player, npc)


def test_embody_any_entity():
    g = _game()
    foe = next(a for a in g.actors if a.allegiance == "monster" and a.faction)
    name, faction = foe.name, foe.faction
    assert embody(g, name.lower())
    assert g.player is foe and g.player.is_player
    kin = _actor(faction)
    rival = _actor("someone_else")
    g._rel[(faction, "someone_else")] = "rival"
    assert not g.hostile(g.player, kin), "your new kin are friends"
    assert g.hostile(g.player, rival), "your new rivals are enemies"
    assert not g.hostile(g.player, _actor(allegiance="npc"))


if __name__ == "__main__":
    for fn in (test_kin_never_fight, test_rival_houses_war,
               test_spawned_creatures_carry_their_house,
               test_reputation_befriends_a_house,
               test_wildlife_and_npc_rules_hold, test_embody_any_entity):
        fn()
        print(f"ok {fn.__name__}")
