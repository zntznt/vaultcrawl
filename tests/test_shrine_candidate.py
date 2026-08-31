"""The shrine has its own brain candidate, and five things had to be true for it to fire.

Uptake was zero after the depth gate, the agent-side resolution, the sight bonus and the
points_of_interest were all fixed. Placement is not reachability, and it took five more steps
to close, each measured:

  1. perception has to report the shrine at all, and report what the offer is WORTH, so the
     agent does not cross a floor for a trade it would refuse on arrival;
  2. the candidate must not borrow another key's weight. `deploy` and `recover` borrowed
     `explore` and misbehaved for the life of the project (efd591b);
  3. arriving must emit `interact`. The navigation branch returns None when the step is
     (0, 0), so a candidate that reaches its target and has no special case stalls on top of
     it forever. `recover` has exactly this special case for exactly this reason;
  4. the pull has to steepen as it closes. On a flat ramp the shrine scored a median 17.9
     inside 3 to 5 tiles against a best rival of exactly 17.9, a dead tie on 134 decisions
     that `deesc_stairs` won 61 times: the agent walked to within three tiles of every shrine
     and oscillated away;
  5. `interact` is one overloaded verb with a fixed precedence, and the shrine sat behind
     weather. Both of the two times an agent ever stood on a shrine, weather was live and
     `interact` returned into `clear_weather`.

Attribution, 6 runs, shrines actually spent: full build 6, flat ramp 4, no weather exception 2.
"""
from __future__ import annotations

import pytest

from runtime.agent import PROFILES, SHRINE_PULL_STEP, SHRINE_RANGE, UniversalBrain
from runtime.agent_perception import agent_state
from runtime.game import Game, load_manifest
from runtime.stack import build_systems, register_brains


def _game():
    register_brains()
    return Game(load_manifest("examples/world.json"), systems=build_systems())


def _place_shrine(g, dx=3, dy=0):
    sac = g.system("sacrifice")
    from runtime.sacrifice import _OFFERINGS
    pos = (g.player.x + dx, g.player.y + dy)
    sac.shrines = {pos: list(_OFFERINGS[:3])}
    return sac, pos


# --- 1. perception ------------------------------------------------------------------------

def test_perception_reports_the_shrine_with_what_it_is_worth():
    g = _game()
    _sac, pos = _place_shrine(g)
    sh = agent_state(g, g.player)["nearest_shrine"]
    assert sh is not None, "the shrine is invisible to the brain"
    assert (sh[0], sh[1]) == pos
    assert sh[2] == 3, f"distance reported as {sh[2]}, expected chebyshev 3"
    assert isinstance(sh[3], (int, float)), (
        "no worth reported, so the agent must walk to the shrine to discover it would "
        "refuse every offer")


def test_no_shrine_reports_none_rather_than_a_default_position():
    g = _game()
    g.system("sacrifice").shrines = {}
    assert agent_state(g, g.player)["nearest_shrine"] is None


# --- 2. its own weight, present for everyone -----------------------------------------------

def test_every_profile_carries_the_shrine_weight():
    """Berlin: a key missing from one profile is an ability that profile cannot reach."""
    missing = [n for n, p in PROFILES.items() if "shrine" not in p]
    assert not missing, f"{missing} have no `shrine` weight, so the shrine is class-locked"


def test_the_weight_is_uniform_and_that_is_deliberate():
    """Differentiation comes from `_worth`, which prices the offer against what this run
    holds. Six invented numbers would be preference asserted; `_worth` is preference derived.
    If someone splits these, it should be because a measurement asked for it."""
    vals = {p["shrine"] for p in PROFILES.values()}
    assert len(vals) == 1, (
        f"`shrine` weights have been split into {vals}. That may be right, but it is a "
        f"balance claim and belongs with the measurement that motivated it")


def test_the_candidate_does_not_borrow_the_explore_key():
    import ast
    import inspect

    src = inspect.getsource(UniversalBrain.decide)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_score"
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "shrine"):
            break
    else:
        raise AssertionError(
            "no `_score(profile, 'shrine', ...)` call in decide, so the shrine candidate is "
            "scored on some other decision's key")


# --- 3. arriving must act -------------------------------------------------------------------

def test_standing_on_the_shrine_produces_an_interact_not_a_stall():
    """The navigation branch returns None on a zero step. Without the arrival case the agent
    reaches the tile and then does nothing, forever, which is a livelock that looks like
    patience."""
    import inspect

    from runtime.agent import UniversalBrain
    src = inspect.getsource(UniversalBrain._resolve)
    assert 'kind == "shrine"' in src and 'AgentAction("interact")' in src, (
        "no arrival case for the shrine, so reaching it yields no action")


def test_the_shrine_is_routed_through_the_navigation_kinds():
    import inspect

    src = inspect.getsource(UniversalBrain._resolve)
    i = src.index('elif kind in ("salvage", "cache"')
    assert '"shrine"' in src[i:i + 400], (
        "`shrine` is not in the navigation kind tuple, so its candidate falls through to "
        "`return None` and the agent never moves toward it")


# --- 4. the pull must steepen ----------------------------------------------------------------

def test_the_pull_grows_faster_than_one_per_tile():
    assert SHRINE_PULL_STEP > 1, (
        f"the pull step is {SHRINE_PULL_STEP}, a flat ramp. Measured, that tied the best "
        f"rival at 17.9 inside 3 to 5 tiles on 134 decisions and lost 61 of them")
    assert SHRINE_RANGE > 12, (
        f"range {SHRINE_RANGE} is no further than a locus's, and shrines are one or two per "
        f"descent where loci are eight per floor")


def test_closer_always_scores_higher():
    """A pull that is not monotone in distance can send the agent away from the shrine."""
    g = _game()
    sac, _ = _place_shrine(g)
    from runtime.sacrifice import _OFFERINGS
    scores = []
    for d in range(1, SHRINE_RANGE + 1):
        sac.shrines = {(g.player.x + d, g.player.y): list(_OFFERINGS[:3])}
        sh = agent_state(g, g.player)["nearest_shrine"]
        scores.append(max(0, SHRINE_RANGE - sh[2]) * SHRINE_PULL_STEP + max(0, sh[3]))
    assert scores == sorted(scores, reverse=True), f"not monotone in distance: {scores}"


# --- 5. the precedence exception ------------------------------------------------------------

def test_a_shrine_underfoot_outranks_the_weather():
    """`interact` is one verb with a fixed chain and the shrine sat behind weather.

    The agent is given matter first, and that is not incidental. This test used to pass on a
    fresh game where the shrine offered to take matter from an agent holding none: `apply`
    guarded the cost with `if salv` and granted +3 DEF anyway, so the assertion below was
    reading a free reward. With `_OFFERINGS` filtered to what the agent can actually pay,
    that offer is no longer made and the same setup correctly resolves to a refusal. Give it
    something real to trade.
    """
    g = _game()
    salv = g.system("salvage")
    if salv is not None:
        salv.inventory(g).add({"iron": 2})
    sac, pos = _place_shrine(g, 0, 0)
    weather = g.system("weather")
    if weather is not None:
        weather.weather = "acrid haze"      # the branch that used to swallow the interact
    # This has now been broken THREE times by a reprice, every time reporting a working
    # shrine as broken because the assertion enumerated stats: `sigil` moved off max HP,
    # `matter` moved off DEF onto sight, then `matter` moved onto a sigil SLOT, which is not
    # a stat at all. Enumerating is the mistake. The question this test asks is "did the
    # renunciation land", so it asks that directly, and the fingerprint is a backstop.
    def _stats():
        sigs = g.system("sigils")
        return (g.player.max_hp, g.player.atk, g.player.defense,
                getattr(sac, "sight_bonus", 0), len(getattr(sigs, "slots", []) or []))

    before = _stats()
    assert g.interact() is True
    assert pos not in sac.shrines, (
        "the shrine was not consumed, so `interact` went to the weather branch and the "
        "shrine is unreachable whenever weather is live")
    accepted = any("renunciation" in m for m in (getattr(g, "messages", []) or [])[-6:])
    assert accepted, "the shrine was consumed without a renunciation being applied"
    assert _stats() != before, "the shrine fired and granted nothing in any currency"


def test_the_exception_is_the_exact_tile_and_not_a_radius():
    """The cautionary case in `interact`'s own docstring: a broad preemption on adjacency
    hijacked everything else the verb does and cost every profile its run."""
    g = _game()
    sac, _ = _place_shrine(g, 1, 0)          # adjacent, not underfoot
    weather = g.system("weather")
    if weather is not None:
        weather.weather = "acrid haze"
    before = (g.player.max_hp, g.player.atk, g.player.defense)
    g.interact()
    assert (g.player.max_hp, g.player.atk, g.player.defense) == before, (
        "an adjacent shrine preempted the weather branch, which is the broad-guard mistake "
        "this exception was written narrowly to avoid")


# --- the trap that hid all of this ------------------------------------------------------------

def test_the_metrics_snapshot_survives_the_run():
    """`_get_metrics` used to reset the tracker on its way out, so anything reading
    `metrics()` after a run saw zeros. Shrine uptake was diagnosed as zero three separate
    times, and three fixes aimed at it, on a counter the harness had already wiped."""
    import inspect

    from runtime.agent_eval import _get_metrics
    assert "reset_metrics()" not in inspect.getsource(_get_metrics), (
        "_get_metrics resets the tracker again. `Game.__init__` already does it through "
        "reset_run_state, and doing it here makes post-run reads silently zero")
