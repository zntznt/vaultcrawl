"""More creature types (read from note nature) + more things telling note histories."""
from __future__ import annotations

from vaultcrawl.mapping import _archetype_for, _FAMILY
from runtime.notehistory import facts, one_fact
from runtime.game import Game, load_manifest


def test_archetype_reads_from_role():
    # each role maps to a distinct family; a hub note is never a feral orphan-beast
    hub = _archetype_for("hub", 0.9, 15, "n1")
    orphan = _archetype_for("orphan", 0.9, 0, "n2")
    assert hub in _FAMILY["hub"]
    assert orphan in _FAMILY["orphan"]
    assert hub != orphan


def test_archetype_varies_within_a_family():
    # a flat vault (all fresh) must still spread across a family via degree + hash
    kinds = {_archetype_for("cluster", 1.0, d, f"note{d}") for d in range(6)}
    assert len(kinds) >= 2, "same-role notes should not all become one creature"


def test_note_history_is_read_from_graph_facts():
    hub = {"degree": 20, "activity": 0.9, "role": "hub", "bridge": True,
           "tags": ["a", "b"], "neighbors": ["x", "y", "z", "w"]}
    fs = facts(hub, "Big Note")
    joined = " ".join(fs)
    assert "keystone" in joined and "20 roads" in joined
    assert "bridge" in joined
    lonely = {"degree": 0, "activity": 0.05}
    assert "orphan" in " ".join(facts(lonely, "Lost"))
    assert "first age" in " ".join(facts(lonely, "Lost"))


def test_examine_tells_a_creatures_note_history():
    g = Game(load_manifest("examples/world.json"), sandbox=True)
    foe = next((a for a in g.actors if a.allegiance == "monster"
                and getattr(a, "source", "")), None)
    if foe is None:
        return
    g.player.x, g.player.y = foe.x - 1, foe.y
    before = len(g.messages)
    g.examine()
    said = " ".join(g.messages[before:])
    assert "Of its origin:" in said, "the nearest creature recounts its note's history"


if __name__ == "__main__":
    for fn in (test_archetype_reads_from_role, test_archetype_varies_within_a_family,
               test_note_history_is_read_from_graph_facts,
               test_examine_tells_a_creatures_note_history):
        fn()
        print(f"ok {fn.__name__}")
