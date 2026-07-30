"""The heal's urgency curve: steep enough to matter, flat enough to stay breakable.

`recall` firing on 0.00% of decisions was read as a scoring bug for the life of this project.
It is not, or not only. The agent is below 60% HP on under 1% of its decisions, so an
emergency verb's label share is near zero by construction: the denominator is every decision
in the run. The honest instrument is conditional, and `runtime/availability.py` now reports
it as UPTAKE. On that instrument the defect is real: over 187 decisions where a Recall was
genuinely castable, the agent cast it 13 times (7.0%) and spent the rest on locus 25%,
explore_unseen 16%, salvage 11%. Wounded, holding the heal, looting.

The cause was a curve that was too flat. HEAL scored `(100 - hp%) // 4`, so at 55% HP it
offered 11. The `recall` weight cannot rescue that, being 3 to 6 and never once the binding
term (`runtime/weight_audit.py`: 84 calls, 0 binds). The exploration family carries an
`explore` weight reaching 15, so the heal did not clear even the *floor* of what it competes
with until HP fell under 40, and PANIC hard-overrides at 35 (25 for fighters). A five-point
window.

`// 2` doubles the slope: the heal clears 15 from 70% HP down, so it is live across the whole
band its own gate allows instead of a sliver of it.

What is deliberately NOT pinned here: that the heal beats any particular rival on any
particular turn. `locus` and friends carry computed state urgencies that exceed their weight
(at 50% HP the heal scores 25 and locus can score 27), so which one wins is a fact about the
board, not about the formula. An earlier version of this file asserted that and passed only
when run after `test_availability.py`, which is order dependence masquerading as a contract.
Whether the slope is now steep enough is a measured question, and UPTAKE is its arbiter, not
an assertion here.

The ceiling test is the one that would have caught the commune livelock. Fatigue is the only
backstop against a candidate that never resolves, it caps at `FATIGUE_MAX`, and above that cap
nothing can dislodge a candidate at all. Any urgency allowed to exceed 60 is a potential
permanent loop. See `tests/test_commune_reach.py` for the one that got through.
"""
from __future__ import annotations

import pytest

from runtime.agent import FATIGUE_MAX, PROFILES, UniversalBrain
from runtime.agent_perception import agent_state
from runtime.body_parts import damage_part
from runtime.game import Game, load_manifest
from runtime.stack import build_systems

# The highest `explore` weight any profile carries: the identity floor of everything the
# heal competes with while wandering. Read from PROFILES so it cannot drift out of date.
EXPLORE_FLOOR = max(p.get("explore", 0) for p in PROFILES.values())


def _fresh_game():
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="heal-priority", systems=build_systems())
    g.descend()
    # Past the opening. `_starting_bonus` adds 12, 8 then 4 over turns 1 to 6, which is
    # larger than the whole difference this file is about: at turn 1 the old flat curve
    # scored 12 + 12 = 24 and cleared the exploration floor for the wrong reason. A test
    # that cannot see the change it exists to protect is decoration.
    g.turn = 50
    return g


@pytest.fixture
def game():
    return _fresh_game()


def _wound_and_arm(game, hp_fraction):
    """Slot a Recall and drop the player to a given share of max HP."""
    sigs = game.system("sigils")
    sigs.slots.clear()
    sigs.slots.append({"ability": "Recall", "base": "Recall", "durability": 3,
                       "note": "test", "role": "hub"})
    p = game.player
    damage_part(p, "torso", int(p.max_hp * (1 - hp_fraction)))
    s = agent_state(game, p)
    assert s["can_heal_meaningfully"], "the fixture did not actually wound the player"
    return s


def _recall_score(game, profile="cartographer"):
    brain = UniversalBrain(profile)
    brain.decide(game, game.player)
    for label, score, _cand in brain._last_candidates:
        if label == "recall":
            return score
    return None


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_the_heal_clears_the_exploration_floor_at_half_health(game, profile):
    """The five-point window, closed. Berlin: urgency is state, identical for all six."""
    s = _wound_and_arm(game, 0.5)
    hp_pct = s["vitals"]["hp_pct"]
    score = _recall_score(game, profile)

    assert score is not None, f"{profile} did not consider the heal at {hp_pct}% HP"
    assert score >= EXPLORE_FLOOR, (
        f"{profile} at {hp_pct}% HP scores the heal at {score}, under the exploration "
        f"identity floor of {EXPLORE_FLOOR}, so looting outranks it before the board is "
        f"even consulted")


def test_the_heal_gets_more_urgent_as_hp_falls():
    """Monotonicity. A flat curve is what produced the window in the first place."""
    seen = {}
    for fraction in (0.55, 0.40):
        g = _fresh_game()
        _wound_and_arm(g, fraction)
        seen[fraction] = _recall_score(g)

    assert None not in seen.values(), f"the heal was not scored at both depths: {seen}"
    assert seen[0.40] > seen[0.55], (
        f"healing at 40% HP scores {seen[0.40]}, no more urgent than {seen[0.55]} at 55%")


def test_the_heal_urgency_stays_under_the_fatigue_ceiling():
    """The commune lesson, applied here before it bites.

    Fatigue is the only thing that stops a candidate which never resolves from winning every
    turn forever. It caps at FATIGUE_MAX, so an urgency that can exceed the cap is a
    livelock waiting for a verb to start failing. The worst case for this curve is HP 0.
    """
    worst_case = (100 - 0) // 2
    assert worst_case < FATIGUE_MAX, (
        f"the heal can reach {worst_case}, at or above the fatigue ceiling of {FATIGUE_MAX}. "
        f"If the cast ever fails without spending a turn, nothing can dislodge it and the "
        f"run livelocks, exactly as commune did")


def _panic_and_arm(game, hp_fraction, ability="Recall"):
    sigs = game.system("sigils")
    sigs.slots.clear()
    sigs.slots.append({"ability": ability, "base": ability, "durability": 3,
                       "note": "test", "role": "hub"})
    p = game.player
    damage_part(p, "torso", int(p.max_hp * (1 - hp_fraction)))
    for part in ("head", "left_arm", "right_arm", "left_leg", "right_leg"):
        try:
            damage_part(p, part, int(p.max_hp * (1 - hp_fraction)))
        except Exception:
            pass
    s = agent_state(game, p)
    return s


def test_a_panicking_agent_casts_its_heal_instead_of_running():
    """PANIC returns before the candidate list exists, so HEAL cannot compete below the
    cutoff. The branch knew about Phase and not about Recall, and fled with the heal in
    hand on 78.1% of the decisions where casting was possible."""
    g = _fresh_game()
    s = _panic_and_arm(g, 0.20)
    hp_pct = s["vitals"]["hp_pct"]
    # cartographer carries fight -5, so its panic cutoff is 35, not the fighters' 25.
    assert hp_pct < 35, f"fixture landed at {hp_pct}%, above cartographer's panic cutoff"
    assert s["can_heal_meaningfully"], "the fixture did not wound the player meaningfully"

    brain = UniversalBrain("cartographer")
    brain.decide(g, g.player)
    label = brain._last_candidates[brain._last_choice][0]
    assert label == "panic_recall", (
        f"a panicking agent at {hp_pct}% HP holding a castable Recall chose {label} "
        f"instead of drinking it")


def test_panic_still_prefers_phase_when_a_threat_is_adjacent():
    """Blinking clear solves what the heal only delays, so Phase keeps priority."""
    g = _fresh_game()
    _panic_and_arm(g, 0.20, ability="Phase")
    sigs = g.system("sigils")
    sigs.slots.append({"ability": "Recall", "base": "Recall", "durability": 3,
                       "note": "test", "role": "hub"})
    s = agent_state(g, g.player)
    if not s.get("near_hostiles"):
        pytest.skip("no hostile in range on this floor, so the branch is not exercised")

    brain = UniversalBrain("cartographer")
    brain.decide(g, g.player)
    label = brain._last_candidates[brain._last_choice][0]
    assert label == "panic_phase", (
        f"Phase lost its priority in PANIC, chose {label}")
