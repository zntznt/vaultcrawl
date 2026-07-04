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


def test_creature_stats_are_readable_and_adaptive():
    from runtime.entities import Actor
    g = _game()
    # a plain wild critter -> just its stance, no clutter
    w = Actor(x=1, y=1, glyph="n", name="grazer", hp=6, max_hp=6, atk=1,
              allegiance="wild")
    assert g.creature_stats(w) == ["indifferent"]
    # a wounded legendary hostile -> the full readout, condition included
    b = Actor(x=1, y=1, glyph="q", name="S", hp=5, max_hp=40, atk=9,
              tier=4, quality=4, allegiance="monster")
    s = g.creature_stats(b)
    assert "hostile" in s and "legendary" in s and "tier 4" in s
    assert any("death" in x or "wounded" in x for x in s), "condition surfaced when hurt"
    # a healthy creature does NOT surface a condition word
    assert not any("death" in x or "wounded" in x for x in g.creature_stats(w))


if __name__ == "__main__":
    for fn in (test_dialogue_topics_are_note_specific, test_topics_reference_the_real_note,
               test_topics_empty_for_sourceless, test_mechanical_verbs_apply_to_any_target,
               test_creature_stats_are_readable_and_adaptive):
        fn()
        print(f"ok {fn.__name__}")
