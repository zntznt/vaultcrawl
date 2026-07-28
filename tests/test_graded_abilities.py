"""A sigil that got good must not become invisible.

`quality.qualify_sigil` renames a graded sigil in place, `ability` becoming "Legendary Recall",
and it does not fill in `base`. Anything that asked `ability == "Recall"` therefore stopped
seeing the sigil at exactly the moment it became worth having.

The sigil system itself was immune, because it routed everything through a private `_ab()` that
stripped the prefix. The brain, `Game.deploy` and the locus forge each had their own version of
that logic, written as an equality test, and were blind. Measured over one 10,485-turn artisan
run: a Recall sigil was in the slots on about 3,900 turns and the brain could see it on 65. In a
288-run evaluation the `recall` and `sigil_escape` branches fired on 0.00% of decisions for all
six profiles while 157 runs died of attrition, dozens of turns each below 25% HP, holding a heal
they could not read.

So the rule now lives in one place, `sigils.base_ability`, and the agent's perception snapshot
carries the answer as `verb` so no future consumer has to know the rule at all. These tests pin
the helper, the seam, and the two consumers that were wrong.
"""
from __future__ import annotations

import pytest

from runtime.agent import UniversalBrain
from runtime.agent_perception import agent_state
from runtime.body_parts import damage_part
from runtime.game import Game, load_manifest
from runtime.sigils import base_ability, strip_grade
from runtime.stack import build_systems


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="graded", systems=build_systems())
    g.descend()
    return g


def _slot(game, ability, base=""):
    """Put exactly one sigil in the slots, as the grader would leave it."""
    sigs = game.system("sigils")
    sigs.slots.clear()
    sigs.slots.append({"ability": ability, "base": base, "durability": 3,
                       "note": "test", "role": "hub"})
    return sigs.slots[0]


@pytest.mark.parametrize("sigil,expected", [
    ({"ability": "Legendary Recall", "base": ""}, "Recall"),   # what the grader produces
    ({"ability": "Uncommon Phase", "base": ""}, "Phase"),
    ({"ability": "Recall", "base": "Recall"}, "Recall"),       # a fresh forge
    ({"ability": "Ward"}, "Ward"),                             # no base key at all
    ({"ability": "Epic Ward", "base": "Ward"}, "Ward"),        # base wins when present
    ({"ability": ""}, ""),
    ("Legendary Recall", "Recall"),                            # a bare _deploy_ability string
])
def test_the_verb_survives_the_grade(sigil, expected):
    assert base_ability(sigil) == expected


def test_only_a_real_grade_word_is_stripped():
    """"Recall" is one word and must stay whole; an unknown first word is not a grade."""
    assert strip_grade("Recall") == "Recall"
    assert strip_grade("Cursed Recall") == "Cursed Recall"
    assert strip_grade("") == ""


def test_perception_hands_the_brain_the_verb(game):
    """The seam. Every consumer of the snapshot gets the answer without knowing the rule."""
    _slot(game, "Legendary Recall")
    s = agent_state(game, game.player)
    sig = s["sigils"][0]
    assert sig["ability"] == "Legendary Recall", "the display name should be preserved"
    assert sig["verb"] == "Recall", "the snapshot does not carry the verb"


def test_the_agent_can_reach_its_heal_while_holding_a_graded_sigil(game):
    """The whole point: a wounded agent with a Legendary Recall must score the heal.

    HEAL wants HP under 60% and a damaged body part, and PANIC takes over under 35% for a
    non-fighter, so the fixture damages the torso to land in between.
    """
    _slot(game, "Legendary Recall")
    p = game.player
    damage_part(p, "torso", int(p.max_hp * 0.5))
    s = agent_state(game, p)
    assert 35 <= s["vitals"]["hp_pct"] < 60, f"fixture landed at {s['vitals']['hp_pct']}% HP"
    assert s["can_heal_meaningfully"], "the fixture did not actually wound the player"

    brain = UniversalBrain("cartographer")
    brain.decide(game, p)
    labels = [c[0] for c in brain._last_candidates]
    assert "recall" in labels, (
        f"a wounded agent holding a Legendary Recall did not even consider healing. "
        f"Candidates were {labels}")


def test_a_graded_sigil_deploys_as_itself(game):
    """`Game.deploy` read the display name, so a graded Recall became a nameless dud.

    The tick that heals from the beacon reads `_deploy_ability` back off the entity, so
    storing the verb there fixes both halves at once.
    """
    _slot(game, "Legendary Recall")
    assert game.deploy(0) is True

    beacon = next((a for a in game.actors if getattr(a, "_deploy_ability", "")), None)
    assert beacon is not None, "nothing was deployed"
    assert beacon._deploy_ability == "Recall", \
        f"the entity remembers a display name, not a verb: {beacon._deploy_ability!r}"
    assert getattr(beacon, "_heal_aura", 0) > 0, \
        "a deployed Recall has no heal aura, so the beacon does nothing"
    assert beacon.name == "Recall Beacon"


def test_the_forge_knows_what_it_is_already_carrying(game):
    """The FORGE branch picks the first ability it does not already hold.

    Reading display names meant a graded Recall never matched "Recall", so the agent kept
    forging a second one of what it was holding. Same bug in the locus free forge.
    """
    _slot(game, "Legendary Recall")
    s = agent_state(game, game.player)
    slotted = {sig.get("verb") for sig in s["sigils"]}
    assert slotted == {"Recall"}, f"the brain thinks it is carrying {slotted}"
