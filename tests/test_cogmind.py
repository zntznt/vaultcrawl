"""The Cogmind circle: creatures embody parts; their fall makes those parts yours."""
from __future__ import annotations

from runtime.entities import Actor
from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem
from runtime.sigils import MAX_SLOTS, SigilSystem


def _game(*systems):
    return Game(load_manifest("examples/world.json"), sandbox=True,
                systems=list(systems))


def test_a_capable_creatures_fall_drops_its_part():
    g = _game(SigilSystem())
    sigs = g.system("sigils")
    elite = Actor(x=2, y=2, glyph="s", name="Rare shade", hp=1, max_hp=1, atk=1)
    elite._special_actions = ["blink"]
    g.actors.append(elite)
    g.kill(elite, "melee")
    node = sigs.ground.get((2, 2))
    assert node and node["base"] == "Blink" and node.get("part")


def test_the_part_becomes_your_verb():
    g = _game(SigilSystem())
    sigs = g.system("sigils")
    sigs.slots = [{"note": "t", "role": "part", "ability": "Enrage",
                   "base": "Enrage", "durability": 2, "part": True}]
    atk = g.player.atk
    assert sigs.cast(g, 0)
    assert g.player.atk == atk + 1, "the salvaged verb fires as yours"
    assert sigs.slots[0]["durability"] == 1, "and it is lossy, like everything"


def test_understanding_widens_capacity():
    g = _game(SigilSystem(), KnowledgeSystem())
    sigs, know = g.system("sigils"), g.system("knowledge")
    assert sigs.max_slots(g) == MAX_SLOTS
    for r in g.m["regions"]:
        know._reveal(g, r["sourceNoteId"], direct=True)
    assert sigs.max_slots(g) == min(6, MAX_SLOTS + len(g.m["regions"]))
    assert f"/{sigs.max_slots(g)}]" in sigs.status_line(g)


if __name__ == "__main__":
    for fn in (test_a_capable_creatures_fall_drops_its_part,
               test_the_part_becomes_your_verb,
               test_understanding_widens_capacity):
        fn()
        print(f"ok {fn.__name__}")
