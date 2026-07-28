"""A floor must have its note map before anything asks which room a note owns.

`descend()` rebuilds the level, then `_assign_rooms()` rebuilds `room_notes` from the new
`self.level.rooms`. The boss-placement block calls `spot_for` -> `room_of_note`, which
indexes `self.level.rooms[i]` with `room_notes` keys. That block used to run BEFORE
`_assign_rooms`, so it read the PREVIOUS floor's map against the CURRENT floor's level.

While the two floors happened to have the same room count, this was invisible and merely
wrong: the boss was positioned from a stale map. The moment a floor had fewer rooms than
the one above it, it was an `IndexError` out of `room_of_note`, and since the block is
gated on `self.floor == self.max_floor` it could only ever fire on the final floor, which
is the win-condition floor. A run died at the exact point it was about to be decided.

It survived because nothing reached it. A 48-run evaluation uses seeds 0 to 7 per profile
and none of those hit the combination; the 288-run evaluation crashed on artisan seed 17.
The bug predates the assessment work: the boss block entered in `937beea`.

Two guards, because they fail for different reasons. The invariant test catches a stale map
however it arises. The ordering test catches the specific mistake being reintroduced, and
keeps working even if the sample world stops producing floors that differ in room count.
"""
from __future__ import annotations

import ast
import pathlib

from runtime.game import Game, load_manifest
from runtime.stack import build_systems

GAME_PY = pathlib.Path(__file__).resolve().parent.parent / "runtime" / "game.py"


def test_room_notes_only_ever_index_real_rooms():
    """Descend the whole dungeon and check the map matches the level at every floor.

    This is the invariant the crash violated, stated directly: every key of `room_notes`
    must be a valid index into `level.rooms`, and `room_of_note` must resolve for every
    note in it without raising.
    """
    game = Game(load_manifest("examples/world.json"), sandbox=False,
                run_seed="descend", systems=build_systems())

    for _ in range(game.max_floor):
        game.descend()
        rooms = game.level.rooms
        bad = [i for i in game.room_notes if not (0 <= i < len(rooms))]
        assert not bad, (
            f"floor {game.floor}: room_notes holds {bad} but the level has "
            f"{len(rooms)} rooms, so room_of_note would raise")
        for note_id in game.room_notes.values():
            game.room_of_note(note_id)      # must not raise


def test_the_note_map_is_built_before_the_boss_is_placed():
    """Ordering, read out of the source, so the mistake cannot come back quietly.

    The invariant test above only fires when the sample world happens to produce a floor
    with fewer rooms than the one above it. That is a property of the world, not of the
    code, so it could stop being true without the bug being fixed. This checks the thing
    that is actually required.
    """
    tree = ast.parse(GAME_PY.read_text(encoding="utf-8"))
    descend = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "descend"), None)
    assert descend is not None, "descend() not found"

    assign_at = [n.lineno for n in ast.walk(descend)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", "") == "_assign_rooms"]
    spot_at = [n.lineno for n in ast.walk(descend)
               if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "spot_for"]

    assert assign_at, "descend() no longer calls _assign_rooms"
    if not spot_at:
        return      # nothing consults the note map here any more, so nothing to order
    assert min(assign_at) < min(spot_at), (
        f"_assign_rooms runs at line {min(assign_at)} but spot_for is called at "
        f"{min(spot_at)}: the boss is placed from the previous floor's room map")
