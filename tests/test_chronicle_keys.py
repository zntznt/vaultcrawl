"""The chronicle must speak in note ids, because that is the only key the next run reads.

`Upheaval.ascended` is tested against `spec["sourceNoteId"]` when enemies spawn
(`game.py`, `empower`/`diminish`). So every `idea_ascends` event has to carry a note id.
It carried a death-cause string instead: `Game.kill` passed `cause` into a parameter named
`killer_name`, which `to_upheaval_events` emitted as `note`.

The measured consequence: on the sample vault, `ascended` held `{"predation",
"environment"}` while the notes are `discipline`, `ecs`, `rust`, `second brain`. Nothing
could ever match, so `empower()` never once fired from a chronicle. A paired warm-versus-cold
experiment, six profiles on the same seed, came back **6 of 6 runs byte-identical** with the
warm arm inheriting up to 6 upheaval events. The whole cross-run memory feature was inert.

What this pins:

  1. A companion killed by a creature records that creature's SOURCE, not its name and not
     the cause.
  2. An authorless death (fire, trap, bleeding) records nothing, and produces no event. An
     empty note in `ascended` is not harmless: it matches any spec with no source.
  3. The note ids the chronicle emits actually exist in the world's enemy source ids. This is
     the check that would have caught the original bug, and it is the one worth keeping: it
     compares the two sides of the seam rather than testing either side alone.
"""
from __future__ import annotations

import json

import pytest

from runtime.entities import Actor
from runtime.game import Game, load_manifest
from runtime.persistence import RunChronicle
from runtime.stack import build_systems
from runtime.upheaval import Upheaval


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="chronicle-keys", systems=build_systems())
    g.descend()
    return g


def _companion_and_killer(game):
    p = game.player
    comp = Actor(p.x + 1, p.y, "c", "Test Companion", 5, 5, 1)
    comp.allegiance = "companion"
    comp.faction = ""
    comp.source = "journaling"
    killer = Actor(p.x + 2, p.y, "M", "Test Monster", 9, 9, 3)
    killer.allegiance = "monster"
    killer.source = "rust"          # a real note in the sample vault
    game.actors.extend([comp, killer])
    return comp, killer


def test_a_companion_death_records_the_killers_note(game):
    from runtime.persistence import chronicle
    comp, killer = _companion_and_killer(game)
    before = len(chronicle().companion_deaths)

    game.kill(comp, "melee", killer=killer)

    deaths = chronicle().companion_deaths
    assert len(deaths) == before + 1, "the companion death was not recorded at all"
    _name, note = deaths[-1]
    assert note == "rust", (
        f"recorded {note!r}; the chronicle needs the killer's source note, since "
        f"`Upheaval.ascended` is matched against `sourceNoteId`")


def test_the_real_combat_path_threads_the_killer(game):
    """Through `Game.attack`, not `Game.kill` directly.

    Calling `kill(..., killer=...)` by hand tests the recorder and nothing else: dropping
    `killer=att` at the combat site leaves that test green. This drives the path the game
    actually takes when a monster fells your companion.
    """
    from runtime.persistence import chronicle
    comp, killer = _companion_and_killer(game)
    comp.hp = 1
    comp.defense = 0
    before = len(chronicle().companion_deaths)

    for _ in range(40):
        if comp not in game.actors:
            break
        game.attack(killer, comp)
    assert comp not in game.actors, "the fixture never actually killed the companion"

    deaths = chronicle().companion_deaths
    assert len(deaths) > before, "combat killed the companion without recording it"
    assert deaths[-1][1] == "rust", (
        f"combat recorded {deaths[-1][1]!r}: `Game.attack` is not passing the attacker to "
        f"`kill`, so the killer's note is lost on the one path that always has it")


def test_an_authorless_death_produces_no_ascendant(game):
    """Fire has no idea to promote, and "" in `ascended` matches any sourceless spec."""
    rc = RunChronicle()
    rc.record_companion_death("Test Companion", "")
    kinds = [e["kind"] for e in rc.to_upheaval_events()]
    assert "idea_ascends" not in kinds, (
        "an authorless companion death still emitted an ascendant, so an empty note id "
        "reaches Upheaval.ascended")


def test_the_ascended_notes_exist_in_the_world():
    """The seam check. Compare what the chronicle emits against what the spawner reads."""
    world = json.load(open("examples/world.json", encoding="utf-8"))
    sources = {s["sourceNoteId"] for grp in ("enemies", "bosses")
               for s in world.get(grp, []) if s.get("sourceNoteId")}
    assert sources, "no enemy source ids in the world, so this asserts nothing"

    rc = RunChronicle()
    rc.record_companion_death("Test Companion", "rust")
    up = Upheaval.from_events(rc.to_upheaval_events())

    assert up.ascended, "no ascended note recorded"
    assert up.ascended <= sources, (
        f"ascended holds {sorted(up.ascended - sources)}, which no enemy spec can match. "
        f"That is exactly the defect this file exists for: the chronicle and the spawner "
        f"were reading different key spaces and nothing ever empowered.")
