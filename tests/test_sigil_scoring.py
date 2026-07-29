"""Deploying a sigil is its own preference, and it must not eat the heal.

`deploy` and `recover` were scored on the `explore` profile key. Nobody chose that; it is
the nearest usable weight someone reached for, and it then decided the agent's behaviour
for the rest of the project. A cartographer valued putting a sigil on the floor at 15, the
same as mapping the level, while casting that same sigil to heal scored on `recall` at 6.
Worse, deploying a Recall gained +10 at exactly the HP where the HEAL branch wakes up, so
the two candidates spiked together and deploy won: at 40% HP, HEAL scored max(6, 15) = 15
against deploy's max(15, 18) = 18.

The measured consequence, over 288 runs: `recall` and `sigil_escape` fired on 0.00% of
decisions, and the agent held no sigil at all on 93 to 96% of turns. It was not refusing to
heal. It had already thrown the heal on the floor.

What this pins:

  1. Every profile carries a positive `sigil` weight. Berlin: a preference, never a lock,
     and a profile that omitted the key would silently score 0 and stop deploying at all.
  2. `deploy` and `recover` do not read `explore` any more. Moving the exploration weight
     must not move them, or the borrowing is simply back under a new name.
  3. A wounded agent holding a Recall casts it instead of deploying it.

A Recall Beacon does heal 2 HP a turn in radius 3, so deploying one is not nonsense in
general. Nothing in the brain scores standing inside that aura, though, so the agent walked
away from the beacon it had just spent a sigil on. If that ever gets valued, case 3 is the
test to revisit.

  4. The `sigil` weight actually decides deploy's score when nothing is happening. It could
     not while deploy opened at an unconditional state of 8, which sat above every weight.
     Case 4 was written, reverted with the base-0 change in `b71e49e` for putting artisan
     into an 11-decisions-per-turn stall, and restored once that stall turned out to be the
     commune livelock (`tests/test_commune_reach.py`) rather than anything to do with sigils.
"""
from __future__ import annotations

import pytest

from runtime.agent import PROFILES, UniversalBrain
from runtime.agent_perception import agent_state
from runtime.body_parts import damage_part
from runtime.game import Game, load_manifest
from runtime.stack import build_systems


@pytest.fixture
def game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="sigil-scoring", systems=build_systems())
    g.descend()
    return g


def _slot(game, ability):
    sigs = game.system("sigils")
    sigs.slots.clear()
    sigs.slots.append({"ability": ability, "base": "", "durability": 3,
                       "note": "test", "role": "hub"})


def _wound_to_heal_range(game):
    """Land between the PANIC floor (35%) and the HEAL ceiling (60%)."""
    p = game.player
    damage_part(p, "torso", int(p.max_hp * 0.5))
    s = agent_state(game, p)
    assert 35 <= s["vitals"]["hp_pct"] < 60, f"fixture landed at {s['vitals']['hp_pct']}% HP"
    assert s["can_heal_meaningfully"], "the fixture did not actually wound the player"
    return s


def _scores(brain):
    return {label: score for label, score, _ in brain._last_candidates}


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_every_profile_can_deploy(name):
    """Berlin: six starting states and six preference biases, not six character classes."""
    weight = PROFILES[name].get("sigil")
    assert weight is not None, f"{name} has no `sigil` weight, so deploy scores 0 for it"
    assert weight > 0, f"{name} is locked out of deploying with weight {weight}"


def test_deploy_no_longer_reads_the_exploration_weight(game, monkeypatch):
    """The regression that matters. Move `explore`, and deploy must not move with it."""
    _slot(game, "Ward")  # not Recall, so the heal guard is not what is being measured
    p = game.player
    brain = UniversalBrain("cartographer")

    brain.decide(game, p)
    before = _scores(brain).get("deploy")
    assert before is not None, "the fixture did not produce a deploy candidate at all"

    monkeypatch.setitem(PROFILES["cartographer"], "explore", 99)
    brain = UniversalBrain("cartographer")
    brain.decide(game, p)
    after = _scores(brain).get("deploy")

    assert after == before, (
        f"deploy still tracks the exploration weight: {before} became {after} when "
        f"`explore` went to 99")


def test_a_wounded_agent_casts_its_recall_instead_of_deploying_it(game):
    """The behaviour the 0.00% recall share was actually reporting."""
    _slot(game, "Legendary Recall")
    p = game.player
    _wound_to_heal_range(game)

    brain = UniversalBrain("cartographer")
    brain.decide(game, p)
    scores = _scores(brain)

    assert "recall" in scores, f"the heal was not even considered. Candidates: {sorted(scores)}"
    assert "deploy" not in scores, (
        "a wounded agent is still offered the option of throwing its only heal on the "
        "floor, which is the candidate that beat casting on every measured run")


def _quiet(game):
    """Strip the situational bumps: no hostiles near, no hazards underfoot."""
    game.actors = [a for a in game.actors
                   if a is game.player or getattr(a, "allegiance", "") == "companion"]
    react = game.system("reactions")
    if react is not None and hasattr(react, "props"):
        react.props.clear()
    s = agent_state(game, game.player)
    assert not s.get("near_hostiles"), "the fixture still has hostiles in range"
    assert not s.get("hazard_tiles"), "the fixture still has hazards in range"
    return s


def test_the_sigil_weight_decides_deploy_when_nothing_is_happening(game):
    """The point of base 0.

    `_score` returns max(weight, state). Deploy's base used to be an unconditional 8, at or
    above every `sigil` weight, so the profile was never consulted: 418 calls, 0 binds. With
    no hostiles and no hazards the state is 0, so two different weights must give two
    different scores. If they do not, the weight is inert again and deploy is back to being
    a standing offer worth 8 for nothing having happened.
    """
    _slot(game, "Ward")
    _quiet(game)

    seen = {}
    for weight in (4, 7):
        PROFILES["cartographer"]["sigil"] = weight
        try:
            brain = UniversalBrain("cartographer")
            brain.decide(game, game.player)
            seen[weight] = _scores(brain).get("deploy")
        finally:
            PROFILES["cartographer"]["sigil"] = 5

    assert None not in seen.values(), f"no deploy candidate was produced: {seen}"
    assert seen[4] != seen[7], (
        f"deploy scored {seen[4]} at weight 4 and {seen[7]} at weight 7, so the profile "
        f"weight is still being discarded by the state floor")
    assert seen[7] - seen[4] == pytest.approx(3, abs=0.01), (
        f"deploy should track the weight one for one when quiet, got {seen}")


def test_deploying_recall_is_still_available_when_healing_would_not_help(game):
    """The guard is a state gate, not a ban. At full HP the beacon is a fine idea."""
    _slot(game, "Recall")
    brain = UniversalBrain("cartographer")
    brain.decide(game, game.player)
    assert "deploy" in _scores(brain), (
        "an unwounded agent can no longer deploy a Recall Beacon, so the heal guard has "
        "become a lock rather than a preference")
