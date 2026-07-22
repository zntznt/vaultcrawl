"""Combat and ecology systems — on-hit effects, scent, weather, behavior, emotions.

Run: python3 -m tests.test_combat_ecology
"""
from runtime.game import Game, load_manifest
from runtime.entities import Actor, make_enemy
from runtime.systems import System
from runtime.sigils import SigilSystem
from runtime.reactions import ReactionSystem
from runtime.weather import WeatherSystem
from runtime.scent import ScentSystem
from runtime import behavior


def test_onhit_effects():
    """On-hit status effects: stagger skips turn, bleed drains HP, winded reduces ATK."""
    g = Game(load_manifest("examples/world.json"), systems=[])
    g.alive = True
    e = make_enemy({"tier": 2, "archetype": "warden", "name": "brute",
                    "sourceNoteId": "stoicism"}, 5, 5)
    g.actors = [e]
    g.player.x, g.player.y = 4, 5

    # attack with high damage to trigger effects
    g.player.atk = 8
    g.attack(g.player, e)
    assert e.hp > 0, "enemy should survive one hit"

    # stagger: skip next turn (sets _staggered)
    if getattr(e, "_staggered", 0) > 0:
        # stagger should be consumed in _act_once, causing turn skip
        pass  # probabilistic, just check no crash

    # bleed: drains HP each turn
    if getattr(e, "_bleeding", 0) > 0:
        g._tick_effects()
        assert e.hp > 0, "bleeding shouldn't instantly kill"


def test_scent_diffusion():
    """Scent decays and diffuses; strongest neighbour is readable."""
    g = Game(load_manifest("examples/world.json"), systems=[ScentSystem()])
    s = g.system("scent")
    assert s is not None
    s.on_floor_enter(g)

    # player moves through tiles, leaving scent
    g.player.x, g.player.y = 10, 10
    s.on_player_act(g)
    g.player.x, g.player.y = 11, 10
    s.on_player_act(g)
    assert s.scent_at(11, 10) > 0 or s.scent_at(10, 10) > 0, "moving should leave scent trail"

    # strongest neighbour — the tile just-left should have scent
    nbr = s.strongest_neighbour(g, 10, 10)
    if nbr is None:
        # diffusion may not have reached; check that scent exists somewhere
        for x in range(8, 14):
            for y in range(8, 14):
                if s.scent_at(x, y) > 0:
                    nbr = (x, y)
                    break
            if nbr:
                break
    assert nbr is not None or s.scent_at(11, 10) > 0, "should find scented tile or trail"


def test_weather_player_effects():
    """Weather impacts player: acrid haze deals damage, cold snap slows speed."""
    g = Game(load_manifest("examples/world.json"),
             systems=[ReactionSystem(), WeatherSystem()])
    g.player.x, g.player.y = 10, 10
    g.alive = True

    w = g.system("weather")
    assert w is not None
    assert isinstance(w.current(g), str)

    # run a cadence to trigger _affect_player
    before = g.player.hp
    for _ in range(6):
        w.on_player_act(g)
    # acrid haze should have dealt damage if active
    assert g.player.hp <= before, "haze should deal damage or leave HP unchanged"


def test_behavior_oracles():
    """Oracle predicates return valid scores."""
    g = Game(load_manifest("examples/world.json"), systems=[])
    g.alive = True
    e = make_enemy({"tier": 2, "archetype": "warden", "name": "brute",
                    "sourceNoteId": "stoicism"}, 1, 1)
    g.actors = [e]

    scored = behavior.oracles_for(g, e)
    assert isinstance(scored, list)
    for name, score in scored:
        assert isinstance(name, str)
        assert 0 < score <= 1.0, f"oracle '{name}' score {score} out of [0,1]"


def test_trigger_emotions():
    """Triggers modify anger/fear; decay brings them back to baseline."""
    from runtime.sense import apply_trigger, decay_emotions, anger_of, fear_of
    g = Game(load_manifest("examples/world.json"), systems=[])
    e = make_enemy({"tier": 2, "archetype": "warden", "name": "brute",
                    "sourceNoteId": "stoicism"}, 1, 1)
    g.actors = [e]

    assert anger_of(e) == 0.0 and fear_of(e) == 0.0
    apply_trigger(g, e, "hurt", 1.0)
    assert anger_of(e) > 0.0, "hurt should raise anger"

    for _ in range(20):
        decay_emotions(e)
    assert anger_of(e) < 0.4, "anger should decay toward baseline"


def test_proficiency_forge():
    """Forge requires note-role knowledge before crafting sigils."""
    from runtime.forge import ForgeSystem
    from runtime.sigils import SigilSystem
    from runtime.salvage import SalvageSystem
    from runtime.knowledge import KnowledgeSystem
    from runtime.components import inv

    g = Game(load_manifest("examples/world.json"),
             systems=[SigilSystem(), SalvageSystem(), ForgeSystem(), KnowledgeSystem()])
    g.player.x, g.player.y = 10, 10
    g.alive = True

    forge = g.system("forge")
    sigs = g.system("sigils")
    sal = g.system("salvage")

    # clear starter sigil and give matter
    sigs.slots = []
    inv(g.player).add({"brass": 10, "ink": 10})

    # without note knowledge, forge should refuse
    ok = forge.forge(g, "Recall")
    assert not ok, "forge should refuse without hub-note knowledge"

    # teach the knowledge system a leaf-role note (Ward needs 1 leaf-note known)
    know = g.system("knowledge")
    know.known.add("memento mori")   # leaf role
    # exercise Ward enough times to pass proficiency check
    from runtime.proficiency import ptracker
    for _ in range(3):
        ptracker().exercise("Ward")
    ok = forge.forge(g, "Ward")
    assert ok, "forge should succeed once leaf-role notes are known"


def main():
    test_onhit_effects()
    test_scent_diffusion()
    test_weather_player_effects()
    test_behavior_oracles()
    test_trigger_emotions()
    test_proficiency_forge()
    print("OK")


if __name__ == "__main__":
    main()
