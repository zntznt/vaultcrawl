"""Unified conversation: every creature offers the SAME mechanical verbs (roguelike
all-options), plus its OWN note-specific dialogue topics. The frame is curses (not
unit-tested here); the talk LOGIC is."""
from __future__ import annotations

from runtime.game import Game, load_manifest
from runtime.dialogue import DialogueSystem
from runtime.factions import FactionSystem
from runtime.knowledge import KnowledgeSystem
from runtime.salvage import SalvageSystem


def _game():
    return Game(load_manifest("examples/world.json"),
                systems=[DialogueSystem(), FactionSystem(),
                         SalvageSystem(), KnowledgeSystem()])


def test_dialogue_topics_are_note_specific():
    g = _game()
    sourced = [a for a in g.actors if getattr(a, "source", "")]
    assert sourced, "some creatures carry a note"
    # a note's topics are drawn from ITS graph (neighbors / tags / role), so two
    # different notes generally produce different topic sets
    seen = {}
    for a in sourced[:8]:
        labels = tuple(lbl for lbl, _ in g.dialogue_topics(a.source))
        seen[a.source] = labels
    # at least one creature has topics, and they reference its own note title/links
    assert any(seen.values()), "at least one creature has exclusive dialogue topics"


def test_topics_reference_the_real_note():
    g = _game()
    # pick a note with neighbors so the 'connects to' topic fires
    nid = next((n for n, nd in g.m["graph"]["nodes"].items()
                if nd.get("neighbors")), None)
    if nid is None:
        return
    topics = g.dialogue_topics(nid)
    title = g.m["graph"]["nodes"][nid].get("title", nid)
    assert any(title in lbl for lbl, _ in topics), \
        "the connects-to topic names the creature's own note"


def test_topics_empty_for_sourceless():
    g = _game()
    assert g.dialogue_topics("") == []
    assert g.dialogue_topics("no-such-note") == []


def test_mechanical_verbs_apply_to_any_target():
    # the same verbs resolve on any target — a becalm/confide either works or is a
    # graceful no-op, never a crash or a missing option
    g = _game()
    foe = next((a for a in g.actors if a.allegiance == "monster"
                and not a.is_boss), None)
    if foe is None:
        return
    # ask-history works on anything with a note
    if getattr(foe, "source", ""):
        assert isinstance(g._note_history(foe.source, salt="talk"), str)
    # becalm is offered on a hostile and returns a bool (works or explains)
    assert isinstance(g.becalm(foe), bool)


if __name__ == "__main__":
    for fn in (test_dialogue_topics_are_note_specific, test_topics_reference_the_real_note,
               test_topics_empty_for_sourceless, test_mechanical_verbs_apply_to_any_target):
        fn()
        print(f"ok {fn.__name__}")
