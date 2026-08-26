"""The renunciation shrine, which had never once appeared in a measured run.

Three defects, and they compound, so fixing only the first would have shipped a regression.

  1. `on_floor_enter` began `z = getattr(game, "current_z", 0); if z > -2: return`.
     `current_z` is set from `level.z` and is only ever non-zero in SANDBOX. Classic descent
     leaves it 0 on every floor, so the guard rejected every floor and the system was
     unreachable in the mode every measurement this project has taken was run in: the 288-run
     baselines, three ablation sweeps, both quality sweeps. `ablate.py` called dropping
     `sacrifice` inert, which was true and meant nothing, because it was inert already.

  2. `on_interact` set `game._pending_sacrifice` and returned True. Only `runtime/play.py`
     ever reads that, inside its curses key handler. So an agent that reached a shrine had it
     popped from `shrines`, added to `_done`, and got nothing: the verb was strictly worse
     than not pressing it, and a choice a human walks through was closed to every agent. With
     defect 1 fixed and this one left, shrines would have started appearing and started
     costing agents outright.

  3. "Renounce an Effect" promises "+2 sight radius" in its own offering text. `apply` carried
     a comment saying the bonus was "handled in knowledge.py via _sight()". `_sight()` had no
     such term. The offering was pure loss.
"""
from __future__ import annotations

import pytest

from runtime.game import Game, load_manifest
from runtime.sacrifice import SIGHT_PER_RENUNCIATION, SacrificeSystem
from runtime.stack import build_systems, register_brains

KINDS = ["sigil", "note", "matter", "rest", "effect"]


def _game(has_ui: bool = False):
    register_brains()
    g = Game(load_manifest("examples/world.json"), systems=build_systems())
    g.has_ui = has_ui
    return g


def _first_shrine(g):
    sac = g.system("sacrifice")
    for f in range(1, (g.max_floor or 26) + 1):
        g.floor = f
        sac.on_floor_enter(g)
        if sac.shrines:
            return sac, f, next(iter(sac.shrines.items()))
    raise AssertionError("no shrine placed on any floor, so the system is still unreachable")


# --- 1. the gate -------------------------------------------------------------------------

def test_shrines_appear_in_classic_descent_at_all():
    """The headline. Classic never has a negative z, so the old guard was total."""
    g = _game()
    sac, floor, _ = _first_shrine(g)
    assert floor >= 2


def test_the_gate_does_not_depend_on_current_z_in_classic():
    """The exact regression: a guard reading only `current_z` cannot see classic depth."""
    g = _game()
    sac = g.system("sacrifice")
    assert getattr(g, "current_z", 0) == 0, "premise: classic leaves current_z at 0"
    shallow = [f for f in range(1, g.max_floor + 1) if not sac._is_deep(_at(g, f))]
    deep = [f for f in range(1, g.max_floor + 1) if sac._is_deep(_at(g, f))]
    assert shallow and deep, (
        "the depth gate is constant across every classic floor, so it is reading an axis "
        "classic does not move")


def _at(g, floor):
    g.floor = floor
    return g


def test_early_floors_stay_shrineless_and_deep_ones_qualify():
    g = _game()
    sac = g.system("sacrifice")
    assert not sac._is_deep(_at(g, 1))
    assert not sac._is_deep(_at(g, g.max_floor // 4))
    assert sac._is_deep(_at(g, g.max_floor))


def test_sandbox_still_gates_on_z():
    """The old behaviour was correct for the mode it could see, and must survive."""
    g = _game()
    sac = g.system("sacrifice")
    g.current_z, g.floor = -1, 0
    assert not sac._is_deep(g)
    g.current_z = -SacrificeSystem.SANDBOX_MIN_DEPTH
    assert sac._is_deep(g)


def test_shrines_stay_rare():
    """A permanent buff on every deep floor is a different game. Placement is a 30% roll on
    a qualifying floor; this pins that the result is a handful, not a fixture."""
    g = _game()
    sac = g.system("sacrifice")
    placed = 0
    for f in range(1, g.max_floor + 1):
        g.floor = f
        sac.on_floor_enter(g)
        placed += bool(sac.shrines)
    assert 1 <= placed <= 6, f"{placed} shrines across a full descent is not rare"


# --- 2. reachability, which is a Berlin question ------------------------------------------

def test_an_agent_resolves_the_shrine_rather_than_losing_it():
    g = _game(has_ui=False)
    sac, _, (pos, _offers) = _first_shrine(g)
    g.player.x, g.player.y = pos
    before = (g.player.max_hp, g.player.atk, g.player.defense,
              len(getattr(g.system("sigils"), "slots", []) or []))
    assert sac.on_interact(g) is True
    after = (g.player.max_hp, g.player.atk, g.player.defense,
             len(getattr(g.system("sigils"), "slots", []) or []))
    assert g._pending_sacrifice is None, (
        "the shrine was consumed and left a prompt nobody will answer, which is the state "
        "that made this verb strictly harmful for agents")
    assert before != after, "the shrine was spent and changed nothing"


def test_a_human_front_end_still_gets_its_prompt():
    """The other half. Resolving for the agent must not resolve for the player."""
    g = _game(has_ui=True)
    sac, _, (pos, _offers) = _first_shrine(g)
    g.player.x, g.player.y = pos
    before = (g.player.max_hp, g.player.atk, g.player.defense)
    assert sac.on_interact(g) is True
    assert g._pending_sacrifice, "the popup was resolved out from under the player"
    assert (g.player.max_hp, g.player.atk, g.player.defense) == before


def test_every_offering_is_reachable_by_the_same_code_path():
    """Berlin: the scorer reads game state and never the agent's identity.

    If `_worth` ever branched on a profile name this would still pass, so the source check
    below is the one that actually holds the line.
    """
    import ast
    import inspect

    # The docstring explains WHY this is identity-blind and naturally uses the words, so
    # scanning the raw source would match its own justification. Strip it and read the code.
    fn = ast.parse(inspect.getsource(SacrificeSystem._worth).lstrip()).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    src = ast.unparse(fn)
    for name in ("artisan", "cartographer", "emergent", "exploiter", "seeker", "whisper",
                 "profile", "brain"):
        assert name not in src, (
            f"`_worth` mentions {name!r}, so the shrine is choosing on identity rather than "
            f"on what the run has accumulated")


@pytest.mark.parametrize("kind", KINDS)
def test_each_offering_can_win_the_choice_from_some_state(kind):
    """Every one of the five must be takeable, or the pool is smaller than it reads."""
    g = _game()
    sac = g.system("sacrifice")
    # Give the state each offering is cheap in, and starve the others.
    sigs, know = g.system("sigils"), g.system("knowledge")
    salv, eff = g.system("salvage"), g.system("effects")
    if sigs is not None:
        sigs.slots = list(sigs.slots or [])[:1]
    if know is not None:
        know.known = set(list(sorted(know.known or []))[:1])
    if salv is not None:
        salv.inventory(g).comp.clear()
    if eff is not None:
        eff.collected = {}
    g.player.hp = g.player.max_hp
    if kind == "sigil" and sigs is not None:
        sigs.slots = [{"ability": "Ward", "base": "Ward", "durability": 3,
                       "note": "x", "role": "leaf"} for _ in range(6)]
    if kind == "note" and know is not None:
        know.known = {f"n{i}" for i in range(12)}
    if kind == "effect" and eff is not None:
        eff.collected = {f"e{i}": "n" for i in range(3)}
    if kind == "rest":
        g.player.hp = g.player.max_hp          # rest is only worth giving up while healthy
    assert sac._worth(g, kind) > 0, (
        f"{kind} scores {sac._worth(g, kind)} even in the state it is meant to be cheapest "
        f"in, so no agent will ever take it")


def test_rejecting_stays_possible():
    """A shrine offering nothing this agent wants must crumble unspent, not force a trade."""
    g = _game()
    sac = g.system("sacrifice")
    sigs, know = g.system("sigils"), g.system("knowledge")
    if sigs is not None:
        sigs.slots = []
    if know is not None:
        know.known = set()
    salv = g.system("salvage")
    if salv is not None:
        salv.inventory(g).add({"iron": 40})
    g.player.hp = 1
    offers = [("Renounce a Sigil Slot", "sigil", ""), ("Renounce Matter", "matter", ""),
              ("Renounce Rest", "rest", "")]
    before = (g.player.max_hp, g.player.defense)
    assert sac.resolve(g, offers) == ""
    assert (g.player.max_hp, g.player.defense) == before
    assert g._pending_sacrifice is None


def test_the_choice_is_deterministic():
    """Ties must break on the offering key, not on iteration order."""
    picks = set()
    for _ in range(4):
        g = _game()
        sac = g.system("sacrifice")
        offers = [(n, k, "") for k, n in (("sigil", "a"), ("note", "b"), ("matter", "c"))]
        picks.add(sac.resolve(g, offers))
    assert len(picks) == 1, f"the same state chose {picks} across runs"


# --- 3. the offering that promised a bonus and granted none -------------------------------

def test_renouncing_an_effect_actually_buys_sight():
    g = _game()
    sac, know = g.system("sacrifice"), g.system("knowledge")
    eff = g.system("effects")
    if eff is not None:
        eff.collected = {"lantern": "n1", "small": "n2"}
    before = know._sight(g)
    sac.apply(g, "effect")
    assert sac.sight_bonus == SIGHT_PER_RENUNCIATION
    assert know._sight(g) == before + SIGHT_PER_RENUNCIATION, (
        "the offering text promises +2 sight radius and `_sight` did not move, so the "
        "renunciation is still pure loss")


def test_the_offering_text_and_the_constant_agree():
    """They drifted apart once, silently, for the life of the project."""
    from runtime.sacrifice import _OFFERINGS
    text = next(t for _n, k, t in _OFFERINGS if k == "effect")
    assert f"+{SIGHT_PER_RENUNCIATION} sight" in text


# --- the gains, and the telemetry a sweep needs to read them ---------------------------------

def test_the_gains_are_a_named_table_not_five_literals():
    """They were five literals inside `_worth`, chosen to be state-driven rather than
    measured, which was said plainly at the time. A sweep needs them addressable."""
    from runtime.sacrifice import SHRINE_GAIN
    assert set(SHRINE_GAIN) == {"sigil", "note", "matter", "rest", "effect"}
    assert all(isinstance(v, int) and v > 0 for v in SHRINE_GAIN.values())


def test_the_gain_scalar_moves_every_offering_together():
    import runtime.sacrifice as S

    saved = S.GAIN_PCT
    try:
        S.GAIN_PCT = 200
        assert S._gain("matter") == S.SHRINE_GAIN["matter"] * 2
        S.GAIN_PCT = 50
        assert S._gain("matter") == S.SHRINE_GAIN["matter"] // 2
    finally:
        S.GAIN_PCT = saved


def test_lowering_the_scalar_makes_an_offering_refusable():
    """The point of the knob. At the default the agent took every shrine it ever reached:
    zero rejections in four runs, so `_worth` had no expressible "no"."""
    import runtime.sacrifice as S

    g = _game()
    sac = g.system("sacrifice")
    salv = g.system("salvage")
    if salv is not None:
        salv.inventory(g).comp.clear()
        salv.inventory(g).add({"iron": 4})
    offers = [("m", "matter", "")]
    saved = S.GAIN_PCT
    try:
        S.GAIN_PCT = 200
        assert sac._worth(g, "matter") > 0
        S.GAIN_PCT = 20
        assert sac._worth(g, "matter") <= 0, (
            "scaling the gains to a fifth still leaves every offer worth taking, so the knob "
            "cannot express reluctance and the sweep has nothing to move")
    finally:
        S.GAIN_PCT = saved


def test_resolutions_are_counted_with_their_denominator():
    """`shrine_used` alone counts takes. A build that refuses every shrine and one that never
    reaches a shrine then report the same number, and those are opposite problems."""
    from runtime.metrics import metrics, reset_metrics

    g = _game()
    sac = g.system("sacrifice")
    reset_metrics()
    sac.resolve(g, [("m", "matter", "")])
    sh = metrics().summary()["shrine"]
    assert sh["offered"] == 1, "a resolution was not counted, so uptake has no denominator"
    assert sh["used"] + sh["rejected"] == 1


def test_what_was_on_the_table_is_recorded_not_only_what_won():
    """An offering that never wins and one the pool rarely deals need opposite fixes: raise
    its gain, or change what `_OFFERINGS` samples. Measured over 4 runs, `sigil` was dealt 5
    times and chosen 0, so it is the first and not the second."""
    from runtime.metrics import metrics, reset_metrics

    g = _game()
    sac = g.system("sacrifice")
    reset_metrics()
    sac.resolve(g, [("s", "sigil", ""), ("m", "matter", ""), ("r", "rest", "")])
    pool = metrics().summary()["shrine"]["pool"]
    assert set(pool) == {"sigil", "matter", "rest"}, (
        f"the offered pool recorded {pool}, so a losing offering cannot be told apart from "
        f"one that was never dealt")


# --- offerings the agent can actually pay --------------------------------------------------

def _strip(g):
    """An agent holding nothing: no slots, no notes, no matter, no effects."""
    sigs, know = g.system("sigils"), g.system("knowledge")
    salv, eff = g.system("salvage"), g.system("effects")
    if sigs is not None:
        sigs.slots = []
    if know is not None:
        know.known = set()
    if salv is not None:
        salv.inventory(g).comp.clear()
    if eff is not None:
        eff.collected = {}
    return g


def _shrine_at_player(g, offers):
    """Put a shrine under the player's feet with an exact offer list."""
    sac = g.system("sacrifice")
    pos = (g.player.x, g.player.y)
    sac.shrines = {pos: list(offers)}
    return sac, pos


def test_an_agent_holding_nothing_can_renounce_nothing_but_rest():
    """`rest` is the odd one: it takes a capability rather than an object, so it stays
    payable as long as the capability is still there."""
    g = _strip(_game())
    sac = g.system("sacrifice")
    for kind in ("sigil", "note", "matter", "effect"):
        assert not sac.can_renounce(g, kind), (
            f"the shrine would offer to take {kind} from an agent that has none, and `apply` "
            f"then skips the cost and grants the reward anyway")
    assert sac.can_renounce(g, "rest")
    g._cant_camp = True
    assert not sac.can_renounce(g, "rest"), "camping cannot be renounced twice"


def test_unpayable_offers_are_dropped_from_the_draw():
    g = _strip(_game())
    sac = g.system("sacrifice")
    picks = [("s", "sigil", ""), ("r", "rest", ""), ("e", "effect", "")]
    live = sac.offers_for(g, picks)
    assert [o[1] for o in live] == ["rest"], (
        f"offers_for kept {[o[1] for o in live]}, so a trade the agent cannot make is still "
        f"on the table")


def test_a_draw_with_nothing_payable_falls_back_rather_than_crumbling():
    """A rare permanent opportunity lost to an unlucky draw is worse than one that offers a
    different trade. The fallback is sorted, so it is the same on any machine."""
    g = _strip(_game())
    salv = g.system("salvage")
    if salv is not None:
        salv.inventory(g).add({"iron": 3})     # matter is now payable, nothing else is
    sac = g.system("sacrifice")
    live = sac.offers_for(g, [("s", "sigil", ""), ("e", "effect", "")])
    assert [o[1] for o in live] == sorted(o[1] for o in live)
    assert "matter" in [o[1] for o in live]
    assert all(sac.can_renounce(g, o[1]) for o in live)


def test_the_shrine_never_presents_an_offer_the_agent_cannot_pay():
    """End to end, through the verb, on both the agent and the human path."""
    g = _strip(_game())
    sac, pos = _shrine_at_player(
        g, [("s", "sigil", ""), ("e", "effect", ""), ("n", "note", "")])
    g.has_ui = True                            # keep the offers on the table to inspect
    sac.on_interact(g)
    presented = g._pending_sacrifice or []
    assert all(sac.can_renounce(g, o[1]) for o in presented), (
        f"presented {[o[1] for o in presented]} to an agent that holds none of them")


def test_the_cost_is_always_paid_now_that_the_offer_is_filtered():
    """The latent half of the bug. `apply` grants its reward unconditionally and guards only
    the cost, so a `sigil` renunciation by an agent with no slots was +8 max HP for free. It
    never fired, because `sigil` never won a choice, but it was one balance change away from
    firing."""
    g = _game()
    sac, sigs = g.system("sacrifice"), g.system("sigils")
    sigs.slots = [{"ability": "Ward", "base": "Ward", "durability": 3,
                   "note": "x", "role": "leaf"} for _ in range(3)]
    before_slots, before_hp = len(sigs.slots), g.player.max_hp
    assert sac.can_renounce(g, "sigil")
    sac.apply(g, "sigil")
    assert len(sigs.slots) == before_slots - 1, "the reward was granted and the cost was not"
    assert g.player.max_hp == before_hp + 8


def test_perception_scores_the_filtered_offers():
    """Scoring the raw placement draw made the agent walk to shrines for trades it could not
    pay."""
    from runtime.agent_perception import agent_state

    g = _strip(_game())
    sac, pos = _shrine_at_player(g, [("s", "sigil", "")])   # unpayable, only pick
    g.player.x, g.player.y = pos[0] - 3, pos[1]            # stand off it, so it is a target
    sh = agent_state(g, g.player)["nearest_shrine"]
    assert sh is not None
    fallback = sac.offers_for(g, sac.shrines[pos])
    expected = max((sac._worth(g, o[1]) for o in fallback), default=0)
    assert sh[3] == expected, (
        f"perception reported worth {sh[3]} where the shrine will actually offer "
        f"{[o[1] for o in fallback]} worth {expected}")


def test_renouncing_an_effect_removes_it_rather_than_raising():
    """`EffectSystem.collected` is a dict and `apply` called `.discard(nid)` on it, a set
    method. AttributeError on every call.

    It never fired, because `effect` was chosen 0 times out of 233 dealings across a 432-run
    sweep, and `dispatch`'s `except Exception` would have swallowed it into a refused verb if
    it had. **Filtering the offer pool to what the agent holds is what would have made it
    reachable**, which is the rule this session keeps relearning: a reachability fix to a
    system with an unfinished consumer is a regression, not a partial improvement.
    """
    g = _game()
    eff, sac = g.system("effects"), g.system("sacrifice")
    eff.collected = {"lantern": "n1", "small": "n2"}
    eff.worn = "lantern"
    assert isinstance(eff.collected, dict), (
        "collected stopped being a dict, so the pop below needs re-deriving not trusting")
    sac.apply(g, "effect")
    assert len(eff.collected) == 1, "the renounced effect is still collected"
    assert eff.worn != "lantern", "the renounced effect is still worn"
