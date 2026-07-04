"""Rooms are places: note identity per room, contextual placement, entry announcements."""
from __future__ import annotations

from runtime.game import Game, load_manifest


def _game():
    return Game(load_manifest("examples/world.json"))


def test_rooms_get_notes_deterministically():
    a, b = _game(), _game()
    assert a.room_notes and a.room_notes == b.room_notes


def test_anchor_note_claims_deepest_room():
    g = _game()
    anchor = g.region_for(g.floor)["sourceNoteId"]
    assert g.room_notes[len(g.level.rooms) - 1] == anchor


def test_enemies_spawn_in_their_notes_room():
    g = _game()
    placed = [(a, g.room_of_note(a.source)) for a in g.actors
              if a.allegiance == "monster" and g.room_of_note(a.source) is not None]
    assert placed, "sample floor should place at least one enemy with a room"
    for actor, room in placed:
        assert room.contains(actor.x, actor.y), f"{actor.name} strayed from its room"


def test_entering_a_room_announces_it_once():
    g = _game()
    idx, room = next((i, r) for i, r in enumerate(g.level.rooms)
                     if i not in g._rooms_seen and g.room_label(i))
    label = g.room_label(idx)
    g.player.x, g.player.y = room.center[0] - 1, room.center[1]
    g.actors = []                        # a quiet stroll, nobody interferes
    g.try_move(1, 0)
    assert any(label in m for m in g.messages)
    n = sum(label in m for m in g.messages)
    g.try_move(-1, 0)
    g.try_move(1, 0)                     # re-enter: no repeat announcement
    assert sum(label in m for m in g.messages) == n


if __name__ == "__main__":
    for fn in (test_rooms_get_notes_deterministically,
               test_anchor_note_claims_deepest_room,
               test_enemies_spawn_in_their_notes_room,
               test_entering_a_room_announces_it_once):
        fn()
        print(f"ok {fn.__name__}")
