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


def test_flee_works_at_the_matter_it_is_offered_at():
    """The gate and the body used to disagree, and the gap was a silent no-op.

    `flee` was offered at `matter >= 1` and its branch charged 2, so an agent holding exactly
    one matter picked flee, paid nothing, watched the elite not move, and the encounter
    resolved into nothing at all. It was pinned rather than fixed while it was still one of
    several open questions.

    It is closed toward the GATE rather than the body, and the mercy clause is why. Ten lines
    above the branch sits `# Mercy: desperate agents always get a way out`, offering flee at
    `matter >= 1`. Raising the gate to 2 would have broken that guarantee for precisely the
    agent it exists for: the one who is nearly out of everything. So the cost is now
    `min(FLEE_COST, held)`, the full toss when affordable and everything you have when not.
    """
    g = _game()
    foe, _ = _flee_encounter(g, 1)
    assert g.system("salvage").inventory(g).total() == 0, (
        "one matter was offered as a flee and not spent, so the option and its body still "
        "disagree")
    assert (foe.x, foe.y) != (g.player.x + 1, g.player.y), (
        "the elite did not move, so a flee the game offered did nothing")


def test_the_full_cost_is_charged_when_it_can_be_afforded():
    """The other side: the cheap path must not become the only path."""
    from runtime.game import FLEE_COST

    g = _game()
    before = g.system("salvage").inventory(g).total()
    _foe, _ = _flee_encounter(g, 4)
    spent = before + 4 - g.system("salvage").inventory(g).total()
    assert spent == FLEE_COST, f"charged {spent} where the full cost is {FLEE_COST}"


def test_the_gate_and_the_body_read_the_same_constant():
    """The literals drifted apart once and nothing noticed for the life of the project.

    Checked by moving the constant rather than by reading the source. A source scan for the
    name passes on a file where the constant is defined and the gates are still bare
    literals, which is exactly the state this test exists to catch, and it did pass on it.
    """
    import runtime.game as G

    assert G.FLEE_MIN <= G.FLEE_COST, (
        "flee is offered below the minimum it can ever spend, which is the original bug")

    # Raise the floor above what the agent holds. If the option gates read the constant, flee
    # stops being offered and the encounter resolves some other way. If they are literals,
    # flee is still offered and still spends.
    # Asserted on the CHOICE, not on the matter spent. Both worlds leave the bag untouched
    # here, because a body that reads the constant refuses the throw anyway; only which
    # option the encounter picked tells them apart.
    g = _game()
    saved = G.FLEE_MIN
    G.FLEE_MIN = 3
    try:
        _foe, chose = _flee_encounter(g, 1)
    finally:
        G.FLEE_MIN = saved
    assert chose != "flee", (
        "with FLEE_MIN raised above what the agent holds, the encounter still offered flee, "
        "so an option gate is a bare literal and can drift from the body again in silence")


def test_the_matter_is_only_spent_once_the_throw_has_somewhere_to_land():
    """An elite with no walkable tile 5 steps away used to take the payment and stay put.

    The old order spent first and searched afterwards, which is the same silent half-failure
    as the gate mismatch, one line further out.
    """
    g = _game()
    foe = _foe(g)
    foe.tier, foe.is_boss = 3, False
    foe.x, foe.y = g.player.x + 1, g.player.y
    for a in list(g.actors):
        if a is not foe and a is not g.player:
            a.hp = 0
    g.system("salvage").inventory(g).add({"iron": 4})
    before = g.system("salvage").inventory(g).total()

    walkable = g.level.walkable
    g.level.walkable = lambda x, y: False        # nowhere for the clatter to land
    try:
        g.encounter_resolve(foe)
    finally:
        g.level.walkable = walkable

    assert g.system("salvage").inventory(g).total() == before, (
        "matter was spent on a throw that had nowhere to land")
    assert (foe.x, foe.y) == (g.player.x + 1, g.player.y)


def test_a_flee_that_does_nothing_still_says_so():
    """Silent failure is the class this project keeps rediscovering: an action the brain
    cannot tell has failed is one it will choose again from an unchanged state."""
    g = _game()
    foe = _foe(g)
    foe.tier, foe.is_boss = 3, False
    foe.x, foe.y = g.player.x + 1, g.player.y
    for a in list(g.actors):
        if a is not foe and a is not g.player:
            a.hp = 0
    g.system("salvage").inventory(g).add({"iron": 4})
    n = len(getattr(g, "messages", []) or [])
    walkable = g.level.walkable
    g.level.walkable = lambda x, y: False
    try:
        g.encounter_resolve(foe)
    finally:
        g.level.walkable = walkable
    assert len(getattr(g, "messages", []) or []) > n, (
        "the flee failed and logged nothing at all")


if __name__ == "__main__":
    for fn in (test_temperament_follows_the_notes_role,
               test_it_speaks_in_its_own_notes_words, test_loved_moves_sway_it,
               test_spurned_moves_enrage_it, test_a_bored_creature_disengages,
               test_requirements_cost_no_round, test_fickleness_exists_and_is_seeded,
               test_the_flee_branch_spends_matter_instead_of_raising,
               test_flee_works_at_the_matter_it_is_offered_at,
               test_the_full_cost_is_charged_when_it_can_be_afforded,
               test_the_gate_and_the_body_read_the_same_constant,
               test_the_matter_is_only_spent_once_the_throw_has_somewhere_to_land,
               test_a_flee_that_does_nothing_still_says_so):
        fn()
        print(f"ok {fn.__name__}")
