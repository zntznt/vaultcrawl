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


def _flee_encounter(g, matter: int):
    """Drive `encounter_resolve` into its `flee` branch with `matter` in the bag.

    flee is reached by giving the agent matter and nothing else: `coerce` needs standing,
    `parley` needs a known source or two truths, `appease` needs one truth, and `fight` is
    only ever the fallback when no preferred option exists.
    """
    foe = _foe(g)
    foe.tier, foe.is_boss = 3, False
    foe.x, foe.y = g.player.x + 1, g.player.y
    for a in list(g.actors):
        if a is not foe and a is not g.player:
            a.hp = 0
    g.system("salvage").inventory(g).add({"iron": matter})
    return foe, g.encounter_resolve(foe)


def test_the_flee_branch_spends_matter_instead_of_raising():
    """`self._spend_matter` was an AttributeError waiting for a full bag.

    `_spend_matter` is a module-level function and every other call site says so; this one
    line said `self.`, so the flee branch of an elite encounter crashed the moment the agent
    carried two matter. It sat unnoticed because flee is the fourth-choice option and the
    suite only ever reached it with an empty bag. Lowering the creature quality base surfaced
    it: fewer graded foes means longer runs, longer runs mean fuller bags.
    """
    g = _game()
    before = g.system("salvage").inventory(g).total()
    foe, _ = _flee_encounter(g, 4)
    after = g.system("salvage").inventory(g).total()
    assert after == before + 4 - 2, (
        f"flee took {before + 4 - after} matter where the branch charges 2, so it did not "
        f"run")


def test_flee_is_offered_at_one_matter_and_charges_two():
    """A recorded mismatch, not a fix. The option gate is `matter >= 1`; the branch body is
    `>= 2`. With exactly one matter the agent picks flee, pays nothing, and the elite does
    not move: the encounter resolves into a no-op. Closing it either way is a balance change
    and belongs in a measured sweep, so this pins the current behaviour rather than blessing
    it."""
    g = _game()
    foe, _ = _flee_encounter(g, 1)
    assert g.system("salvage").inventory(g).total() == 1, "one matter must not be charged"
    assert (foe.x, foe.y) == (g.player.x + 1, g.player.y), (
        "the elite moved on a flee the agent could not afford")


if __name__ == "__main__":
    for fn in (test_temperament_follows_the_notes_role,
               test_it_speaks_in_its_own_notes_words, test_loved_moves_sway_it,
               test_spurned_moves_enrage_it, test_a_bored_creature_disengages,
               test_requirements_cost_no_round, test_fickleness_exists_and_is_seeded,
               test_the_flee_branch_spends_matter_instead_of_raising,
               test_flee_is_offered_at_one_matter_and_charges_two):
        fn()
        print(f"ok {fn.__name__}")
