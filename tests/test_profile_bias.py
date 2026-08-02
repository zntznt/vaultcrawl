"""A profile's preference has to survive being outranked.

`_score` returned `max(weight, urgency)`. When urgency exceeded the weight the weight was
not merely outranked, it was erased: the candidate scored identically for all six profiles,
so on those turns the six agents were one agent. Measured by `runtime/weight_audit.py` over
real runs, **12 of 33 call sites had never once had a weight decide a score**, and the
`fight: -5` that cartographer and whisper carry did precisely nothing, because `max()` can
raise a ceiling and never lower one.

The consequence shows up in the health checklist. The policy-divergence floor has fallen on
every recent baseline, 0.09 then 0.073, under the 0.10 line an earlier assessment set as
worth watching. The dynamic-world hypothesis for that convergence was tested and refuted
(warm arm floor 0.071 against cold's 0.089, the wrong direction), which leaves the
differentiation mechanism itself as the remaining explanation: it is partly missing rather
than partly starved.

`PROFILE_BIAS` keeps the weight in the arithmetic always, including when negative, while
staying too small to reorder a real urgency gap. What this file pins:

  1. Two profiles with different weights score the same candidate differently, even when
     urgency is far above both. This is the whole point.
  2. A negative weight scores BELOW a zero weight. Aversion is expressible now.
  3. Urgency still dominates: a large urgency gap is never overturned by a weight gap. The
     identity floor and the crisis override both still work, and this file fails if the
     bias is ever raised to where a preference can outrank an emergency.
"""
from __future__ import annotations

import pytest

from runtime.agent import PROFILE_BIAS, PROFILES, _score


def test_the_weight_still_counts_when_it_is_outranked():
    """The defect. Urgency 40 towers over both weights; the profiles must still differ."""
    hot = _score({"fight": 15}, "fight", 40, 0, True)
    cold = _score({"fight": 1}, "fight", 40, 0, True)
    assert hot != cold, (
        "two profiles 14 points apart score an identical candidate identically once urgency "
        "passes them both, so on this turn the six agents are one agent")
    assert hot > cold, "the profile that wants this more scored it lower"


def test_an_aversion_scores_below_indifference():
    """`fight: -5` meant exactly `fight: 0` before. Both profiles that carry it are affected."""
    averse = _score({"fight": -5}, "fight", 20, 0, True)
    neutral = _score({"fight": 0}, "fight", 20, 0, True)
    assert averse < neutral, (
        "a negative weight does not lower the score, so 'this profile avoids X' cannot be "
        "said at all and cartographer and whisper fight exactly as much as anyone")


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_every_profile_is_distinguishable_somewhere(name):
    """Berlin: profiles differ by preference, so a preference that never shows is a broken
    contract rather than a tuning question."""
    others = [n for n in PROFILES if n != name]
    mine = PROFILES[name]
    distinct = False
    for other in others:
        theirs = PROFILES[other]
        for key in set(mine) | set(theirs):
            a = _score(mine, key, 30, 0, True)      # urgency well above every weight
            b = _score(theirs, key, 30, 0, True)
            if a != b:
                distinct = True
                break
        if distinct:
            break
    assert distinct, f"{name} is indistinguishable from every other profile under high urgency"


# How big an urgency lead must be to count as the situation speaking clearly rather than
# arithmetic noise. Below this, a strong preference is allowed to win, which is what
# "preference biases, never locks" means; above it, the situation decides for everyone.
CLEAR_URGENCY_LEAD = 5


def test_a_clear_urgency_lead_still_beats_any_preference():
    """The guard on the guard, and the bound on PROFILE_BIAS.

    The first version of this asserted that a ONE-point urgency lead survives the widest
    preference gap. That failed, and the honest response was to pick the invariant rather
    than shrink the constant until the test went quiet. A one-point difference between two
    hand-tuned integer urgencies is inside their own noise, and a profile 20 points apart
    from another SHOULD be able to break that tie: it is the difference between a bias and
    no opinion. Genuine emergencies do not rely on this at all, because PANIC returns before
    the candidate list is built.

    So the line is a CLEAR lead, and it bounds the constant at
    PROFILE_BIAS < CLEAR_URGENCY_LEAD / spread. Raise the constant past that and this fails
    first, which is the intent.
    """
    weights = [v for p in PROFILES.values() for v in p.values()]
    spread = max(weights) - min(weights)
    urgent_disliked = _score({"k": min(weights)}, "k", 30 + CLEAR_URGENCY_LEAD, 0, True)
    calm_loved = _score({"k": max(weights)}, "k", 30, 0, True)
    assert urgent_disliked > calm_loved, (
        f"a {CLEAR_URGENCY_LEAD}-point urgency lead lost to a {spread}-point preference "
        f"gap. PROFILE_BIAS ({PROFILE_BIAS}) is too large: preferences are overruling the "
        f"situation. The bound is {CLEAR_URGENCY_LEAD / spread:.3f}")


def test_a_marginal_urgency_lead_can_be_overturned_by_a_strong_preference():
    """The deliberate other half, stated so it is a decision and not an accident.

    If this ever fails it means the bias has been shrunk to decoration: profiles would
    differ only where the `max()` already let them, which is the state that produced 12
    dead call sites and a divergence floor under 0.10.
    """
    weights = [v for p in PROFILES.values() for v in p.values()]
    urgent_disliked = _score({"k": min(weights)}, "k", 31, 0, True)
    calm_loved = _score({"k": max(weights)}, "k", 30, 0, True)
    assert calm_loved > urgent_disliked, (
        "a one-point urgency lead beats the widest preference gap in the table, so the "
        "bias is too small to express a preference at all")


def test_the_bias_is_actually_wired():
    """Guards against the constant being set to zero and this file passing vacuously."""
    assert PROFILE_BIAS > 0, "PROFILE_BIAS is zero, so every check here is decoration"
    lo = _score({"k": 0}, "k", 10, 0, True)
    hi = _score({"k": 10}, "k", 10, 0, True)
    assert hi - lo == pytest.approx(10 * PROFILE_BIAS, abs=1e-9)
