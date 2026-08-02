"""The world's memory has to be able to run downhill too.

Measured before this existed, 48 chained runs against 48 cold ones on identical seeds: the
warm arm won 6 of 48 against cold's 16, mean floor 11.0 against 17.6, and 13 of 16 discordant
pairs fell the same way (p about 0.021). The cause was structural rather than a defect.
`RunChronicle.to_upheaval_events` could emit `idea_ascends`, which empowers a note's enemy,
and had no path that emitted `power_wanes`, which diminishes one. `Upheaval` and `diminish()`
supported waning perfectly well; only `vaultcrawl/evolve.py` produced it, and that runs when
you edit your notes between bakes, not when you play. So run-to-run memory could only
escalate: 5 of 9 enemy-bearing notes ended permanently harder with nothing able to undo it.

What this pins:

  1. Felling creatures of a note `WANE_DEFEATS` times in one run emits `power_wanes`.
  2. Below the threshold it does not, so one lucky kill is not a verdict.
  3. Any death the player caused counts, not just melee. A counterweight that only noticed
     one damage type would make fading a fighter's privilege, which is the Berlin problem
     this project cares most about.
  4. **Ascend and wane are mutually exclusive, last verdict wins.** This is the one that
     makes the feature work at all: every consumer tests `ascended` before `waned`, and
     `_event_key` includes the kind, so without the mutual discard both verdicts persist
     forever and the ascendancy wins every time. A note could be empowered once and never
     fade again however many times you put it down.
"""
from __future__ import annotations

import pytest

from runtime.entities import Actor
from runtime.game import Game, load_manifest
from runtime.persistence import WANE_DEFEATS, RunChronicle
from runtime.stack import build_systems
from runtime.upheaval import Upheaval


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="wane-path", systems=build_systems())
    g.descend()
    return g


def _kinds(rc):
    return [e["kind"] for e in rc.to_upheaval_events()]


def test_repeated_defeats_make_a_note_fade():
    rc = RunChronicle()
    for _ in range(WANE_DEFEATS):
        rc.record_note_defeat("rust")
    events = [e for e in rc.to_upheaval_events() if e["kind"] == "power_wanes"]
    assert events, f"{WANE_DEFEATS} defeats did not produce a wane"
    assert events[0]["note"] == "rust"


def test_one_defeat_is_not_a_verdict():
    rc = RunChronicle()
    for _ in range(WANE_DEFEATS - 1):
        rc.record_note_defeat("rust")
    assert "power_wanes" not in _kinds(rc), (
        f"a note faded after {WANE_DEFEATS - 1} defeats, under the threshold of {WANE_DEFEATS}")


def test_the_wane_overturns_an_existing_ascendancy():
    """The check that makes the counterweight real rather than decorative."""
    rc = RunChronicle()
    rc.record_companion_death("Ally", "rust")          # rust ascends
    for _ in range(WANE_DEFEATS):
        rc.record_note_defeat("rust")                   # and is then put down repeatedly

    up = Upheaval.from_events(rc.to_upheaval_events())
    assert "rust" in up.waned, "the note did not fade despite being felled to threshold"
    assert "rust" not in up.ascended, (
        "the note is both ascended and waned. Every consumer tests `ascended` first, so "
        "the ascendancy wins forever and no amount of defeating it can ever bring it down")


def test_an_ascendancy_can_still_answer_a_wane():
    """Symmetry. The last word wins in both directions, not just the convenient one."""
    old = [{"kind": "power_wanes", "note": "rust", "defeats": 3},
           {"kind": "idea_ascends", "note": "rust", "cause": "slain_Ally"}]
    up = Upheaval.from_events(old)
    assert "rust" in up.ascended and "rust" not in up.waned, (
        "a later ascendancy did not overturn an earlier wane, so the ordering rule only "
        "works one way")


def test_any_player_kill_counts_not_only_melee(game):
    """Berlin: whatever fells it, standing on the far side of it counts."""
    from runtime.persistence import chronicle
    p = game.player
    victim = Actor(p.x + 1, p.y, "M", "Test Monster", 4, 4, 1)
    victim.allegiance = "monster"
    victim.source = "rust"
    game.actors.append(victim)
    before = chronicle().note_defeats.get("rust", 0)

    game.kill(victim, "sparkwire", killer=p)      # a crafted-consumable death, not melee

    assert chronicle().note_defeats.get("rust", 0) == before + 1, (
        "a non-melee player kill did not count toward the note fading")


def test_a_creature_that_is_not_a_note_is_not_recorded(game):
    """Ecology fauna carry sources like `fauna:grazer`, which no enemy spec can match.

    Seen for real in a chained smoke run, where `fauna:grazer` sat in `waned` doing nothing.
    Harmless in itself, but the chronicle is capped at CHRONICLE_MAX entries, so junk keys
    crowd out verdicts that mean something.
    """
    from runtime.persistence import chronicle
    p = game.player
    beast = Actor(p.x + 1, p.y, "r", "Grazer", 3, 3, 1)
    beast.allegiance = "monster"
    beast.source = "fauna:grazer"
    game.actors.append(beast)
    before = dict(chronicle().note_defeats)

    game.kill(beast, "melee", killer=p)

    assert chronicle().note_defeats == before, (
        "a non-note source was recorded as a note defeat, so the chronicle will carry keys "
        "no enemy spec can ever match")


def test_a_kill_the_player_did_not_cause_does_not_count(game):
    """A monster eaten by another monster is the world's business, not a verdict of yours."""
    from runtime.persistence import chronicle
    p = game.player
    victim = Actor(p.x + 1, p.y, "M", "Test Monster", 4, 4, 1)
    victim.allegiance = "monster"
    victim.source = "rust"
    other = Actor(p.x + 2, p.y, "N", "Other Monster", 6, 6, 2)
    other.allegiance = "monster"
    other.source = "ecs"
    game.actors.extend([victim, other])
    before = chronicle().note_defeats.get("rust", 0)

    game.kill(victim, "predation", killer=other)

    assert chronicle().note_defeats.get("rust", 0) == before, (
        "a monster-on-monster kill counted as the player defeating the note")
