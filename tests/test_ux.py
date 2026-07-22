"""UX polish tests.

Run: python3 -m tests.test_ux
"""
from runtime.game import Game, load_manifest
from runtime.entities import make_enemy, Actor
from runtime.quests import QuestSystem
from runtime.body_parts import init_body


def test_quest_progress():
    g = Game(load_manifest("examples/world.json"))
    qs = QuestSystem()
    qs.on_world_start(g)
    assert isinstance(qs.status_line(g), str)
    # quest_progress should work on any quest dict
    for q in qs.quests:
        prog = qs.quest_progress(g, q)
        assert isinstance(prog, str)
        assert len(prog) > 0


def test_inspect_actor():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    e = make_enemy({"tier": 2, "archetype": "warden", "name": "Guardian",
                    "sourceNoteId": "stoicism"}, 5, 5)
    g.actors = [e]
    init_body(e)
    lines = g.inspect_actor(e)
    assert len(lines) >= 2
    assert "Guardian" not in "".join(lines)  # name is from the popup title, not body
    assert "HP" in lines[0]


def test_message_tags():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    g.message_tags = []
    g.messages = []

    g.log("You hit the goblin for 5 (7 HP left)")
    assert "combat" in g.message_tags

    g.log("You enter the Hall of 'Stoicism'.")
    assert "discovery" in g.message_tags

    g.log("The sky is clear.", ambient=True)
    assert "ambient" in g.message_tags


def test_rest_camp():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    g.player.x, g.player.y = 5, 5
    g._town_tiles = {(5, 5)}
    g._resting = False
    g._consecutive_rest = 0

    # three consecutive waits should enter camp mode
    for i in range(3):
        g.wait()
    assert g._consecutive_rest == 3
    assert g._resting

    # movement breaks camp
    g.try_move(1, 0)
    assert not g._resting
    assert g._consecutive_rest == 0


def test_rest_safety():
    g = Game(load_manifest("examples/world.json"))
    g.alive = True
    g.player.x, g.player.y = 5, 5
    g._town_tiles = {(5, 5)}
    g._resting = False
    g._consecutive_rest = 0
    e = make_enemy({"tier": 1, "archetype": "warden", "name": "goblin",
                    "sourceNoteId": "x"}, 6, 5)
    g.actors = [e]
    g.wait()
    # hostiles within 4 tiles should prevent rest
    assert not g._resting


print("OK")
