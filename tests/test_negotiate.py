"""Negotiation: creatures converse as their notes and are swayed in character."""
from __future__ import annotations

from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem
from runtime.marginalia import MarginaliaSystem
from runtime.negotiate import MOVES, Parley
from runtime.salvage import SalvageSystem, inv


def _game():
    return Game(load_manifest("examples/world.json"),
                systems=[SalvageSystem(), KnowledgeSystem(), MarginaliaSystem()])


def _foe(g):
    return next(a for a in g.actors if a.allegiance == "monster" and not a.is_boss)


def test_temperament_follows_the_notes_role():
    g = _game()
    foe = _foe(g)
    role = g.m["graph"]["nodes"][foe.source]["role"]
    p = Parley(g, foe, fickle=False)
    expected = {"hub": "proud", "bridge": "curious", "leaf": "timid",
                "orphan": "lonely", "discovery": "lonely", "cluster": "communal"}
    assert p.temperament == expected.get(role, "communal")


def test_it_speaks_in_its_own_notes_words():
    g = _game()
    foe = _foe(g)
    p = Parley(g, foe, fickle=False)
    line = p.speak(g, foe)
    node = g.m["graph"]["nodes"][foe.source]
    comm = g.m["corpus"][str(node["community"])]
    vocab = set()
    for prefix, nxt in comm["chain"].items():
        vocab.update(w.strip('.!?,;:') for w in prefix.split(" "))
        vocab.update(w.strip('.!?,;:') for w in nxt)
    words = [w.strip('.!?,;:"') for w in line.split(" ")]
    assert all(w in vocab for w in words if w), line


def test_loved_moves_sway_it():
    g = _game()
    foe = _foe(g)
    p = Parley(g, foe, fickle=False)
    loved = max(MOVES, key=lambda m: p.taste.get(m, 0))
    inv(g.player).add({"brass": 9})   # in case its love is gifts
    for _ in range(6):
        if p.outcome:
            break
        p.hear(g, foe, loved)
    assert p.outcome == "swayed"
    assert p.resolve(g, foe)
    assert foe.allegiance == "wild"
    assert foe.source in g.system("knowledge").learned, \
        "being swayed, it teaches you its note"


def test_spurned_moves_enrage_it():
    g = _game()
    foe = _foe(g)
    p = Parley(g, foe, fickle=False)
    p.disposition = -2
    p.taste = {**p.taste, "ask": -2}   # force a spurned move with no requirement
    p.hear(g, foe, "ask")
    assert p.outcome == "enraged"
    p.resolve(g, foe)
    assert getattr(foe, "_enraged", False)
    assert foe.allegiance == "monster"


def test_a_bored_creature_disengages():
    g = _game()
    foe = _foe(g)
    p = Parley(g, foe, fickle=False)
    p.taste = {m: 0 for m in MOVES}
    for _ in range(4):
        p.hear(g, foe, "ask")
    assert p.outcome == "bored"
    p.resolve(g, foe)
    assert foe.allegiance == "monster" and not getattr(foe, "_enraged", False)


def test_requirements_cost_no_round():
    g = _game()
    foe = _foe(g)
    p = Parley(g, foe, fickle=False)
    line = p.hear(g, foe, "truth")   # nothing read yet
    assert "no unspoken truth" in line and p.rounds == 0
    line = p.hear(g, foe, "gift")    # empty bag
    assert "nothing to give" in line and p.rounds == 0


def test_fickleness_exists_and_is_seeded():
    g = _game()
    foe = _foe(g)
    swings = 0
    for turn in range(40):
        g.turn = turn
        p = Parley(g, foe, fickle=True)
        p.taste = {**p.taste, "praise": 2}   # a felt reaction, so a swing shows
        if "strange humor" in p.hear(g, foe, "praise"):
            swings += 1
    assert 0 < swings < 40, "fickle sometimes, not always"


if __name__ == "__main__":
    for fn in (test_temperament_follows_the_notes_role,
               test_it_speaks_in_its_own_notes_words, test_loved_moves_sway_it,
               test_spurned_moves_enrage_it, test_a_bored_creature_disengages,
               test_requirements_cost_no_round, test_fickleness_exists_and_is_seeded):
        fn()
        print(f"ok {fn.__name__}")
