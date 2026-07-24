"""The rules that make the game press back, and the instrument that measures it.

game.py has no test file of its own, and these are the invariants the balance pass
depends on, so they are asserted here rather than left to the eval harness.
"""
from __future__ import annotations

from runtime.factions import FactionSystem
from runtime.game import TENSION_REST_CAP, Game, load_manifest
from runtime.marginalia import MarginaliaSystem
from runtime.pressure import DecisionLog, divergence, percentiles
from runtime.salvage import SalvageSystem
from runtime.sigils import SigilSystem


def _code_only(fn) -> str:
    """Executable source of a function: no docstring, no comments.

    Berlin checks below look for profile names in the logic, and prose about the rule
    would otherwise trip them.
    """
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)):
        node.body = node.body[1:]
    return ast.unparse(tree)


def _game(systems=None):
    return Game(load_manifest("examples/world.json"), systems=systems or [])


# ---- R1: waiting is not resting -------------------------------------------------

def test_wait_without_heal_does_not_restore():
    g = _game()
    g.player.hp = 50
    g.wait(allow_heal=False)
    assert g.player.hp == 50, "a bare turn pass must not heal"


def test_rest_restores():
    g = _game()
    g.player.hp = 50
    g.wait()
    assert g.player.hp > 50, "resting still heals"


def test_wait_still_costs_a_turn():
    g = _game()
    t = g.turn
    g.wait(allow_heal=False)
    assert g.turn == t + 1, "a bare wait consumes the turn like any other action"


# ---- R2: tension is an oscillator, not a ratchet ---------------------------------

def test_resting_raises_tension_and_acting_lowers_it():
    g = _game()
    g.player.hp = 10
    before = g._tension
    g.wait()
    risen = g._tension
    assert risen > before, "holding still raises complacency"
    g._tick_tension()          # any non-resting turn
    assert g._tension < risen, "acting works it back down"


def test_tension_never_goes_negative():
    g = _game()
    for _ in range(50):
        g._tick_tension()
    assert g._tension == 0, "complacency floors at zero"


def test_rest_is_refused_once_the_vault_is_watching():
    g = _game()
    g.player.hp = 10
    g._tension = TENSION_REST_CAP + 1
    hp = g.player.hp
    g.wait()
    assert g.player.hp == hp, "past the cap, holding still restores nothing"


# ---- R3: the descend refund is not a full heal ------------------------------------

def test_descending_does_not_refund_a_fifth_of_max_hp():
    g = _game()
    g.player.hp = 10
    before = g.player.hp
    g.descend()
    gained = g.player.hp - before
    assert gained <= g.player.max_hp // 10, (
        "descending mends a little; it must not pay for the whole descent", gained)


def test_auto_forge_is_off_by_default():
    from runtime.forge import ForgeSystem
    assert ForgeSystem.auto is False, (
        "auto-forge fired every turn the player held matter, so balance numbers were "
        "measured against a forge nobody chose to use")


# ---- R4: standing sets the rest rate, identically for every profile ---------------

def test_rest_modifier_tracks_standing():
    g = _game(systems=[FactionSystem()])
    fcs = g.system("factions")
    region = g.region_for(g.floor) or {}
    fid = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    if not fid:
        return  # this world's floor has no owning house; nothing to assert
    neutral = fcs.rest_modifier(g)
    fcs.standing[fid] = 2
    friendly = fcs.rest_modifier(g)
    fcs.standing[fid] = -3
    hated = fcs.rest_modifier(g)
    assert friendly > neutral > hated, ("standing moves the rate in both directions",
                                        friendly, neutral, hated)
    assert hated == 0 and neutral >= 2, "neutral ground still rests; being hated costs"


def test_rest_modifier_reads_no_profile():
    """Berlin: the modifier is a function of standing, never of who is playing."""
    code = _code_only(FactionSystem.rest_modifier)
    for forbidden in ("brain", "profile", "artisan", "whisper", "_name"):
        assert forbidden not in code, f"rest_modifier must not branch on {forbidden}"


# ---- R5: the last stair opens on any of four routes -------------------------------

def test_egress_is_shut_by_default():
    g = _game(systems=[MarginaliaSystem(), FactionSystem()])
    ok, why = g.egress_ready()
    assert not ok and why, "the last stair does not open for free"


def test_felling_the_warden_opens_egress():
    g = _game(systems=[MarginaliaSystem(), FactionSystem()])
    g._boss_felled = True
    assert g.egress_ready()[0]


def test_communing_opens_egress():
    g = _game(systems=[MarginaliaSystem(), FactionSystem()])
    g._boss_communed = True
    assert g.egress_ready()[0]


def test_truths_open_egress():
    g = _game(systems=[MarginaliaSystem(), FactionSystem()])
    g.system("marginalia").read = g.egress_truths_needed()
    assert g.egress_ready()[0], "reading the vault is a route of its own"


def test_egress_truth_cost_scales_with_the_vault():
    g = _game()
    need = g.egress_truths_needed()
    notes = len(g.m.get("graph", {}).get("nodes", {}))
    assert 3 <= need <= 8, ("bounded", need)
    assert need <= max(3, notes), "never asks for more truths than the vault can yield"


def test_egress_reads_no_profile():
    """Berlin: four routes, open to everyone, chosen by cost not by class."""
    code = _code_only(Game.egress_ready)
    for forbidden in ("brain", "profile", "artisan", "whisper"):
        assert forbidden not in code, f"egress_ready must not branch on {forbidden}"


def test_descend_is_blocked_at_the_last_floor_without_a_route():
    g = _game(systems=[MarginaliaSystem(), FactionSystem()])
    g.floor = g.max_floor
    g.descend()
    assert g.floor == g.max_floor, "the way down is shut"
    assert not g.won


def test_win_path_is_recorded():
    g = _game(systems=[MarginaliaSystem(), FactionSystem()])
    g.floor = g.max_floor
    g._boss_felled = True
    g.descend()
    assert g.won and g.win_path == "escape", (g.won, g.win_path)


# ---- truths are finite -----------------------------------------------------------

def test_a_note_yields_its_marginalia_once_per_run():
    g = _game(systems=[MarginaliaSystem()])
    ms = g.system("marginalia")
    if not ms.ground:
        return  # no marks on this floor
    pos, nid = next(iter(ms.ground.items()))
    g.player.x, g.player.y = pos
    ms.on_player_act(g)
    assert nid in ms.spent
    ms.on_floor_enter(g)
    assert nid not in ms.ground.values(), (
        "re-entering a floor used to re-scatter the same marks, making truths unbounded")


def test_breaking_down_a_sigil_mints_no_truth():
    g = _game(systems=[SalvageSystem(), SigilSystem(), MarginaliaSystem()])
    sigs, salv, ms = g.system("sigils"), g.system("salvage"), g.system("marginalia")
    sigs.slots = [{"ability": "Ward", "note": "x", "durability": 2, "quality": 0}]
    before = ms.read
    salv.breakdown_sigil(g, "Ward")
    assert ms.read == before, "melting your own equipment is not understanding"


# ---- the instrument itself --------------------------------------------------------

def test_decision_log_reads_margin_and_runner_up():
    class Brain:
        _last_candidates = [("deploy", 20.0, None), ("rest", 19.5, None), ("x", 2.0, None)]
        _last_choice = 0

    class Player:
        hp, max_hp, is_player = 40, 100, True

    class G:
        player = Player()

    log = DecisionLog()
    log.observe(G(), Brain())
    s = log.summary()
    assert s["label_share"] == {"deploy": 1.0}
    assert s["contested_share"] == 1.0, "a half-point gap is a real contest"
    assert s["min_hp_pct"] == 40 and s["hurt_share"] == 1.0


def test_decision_log_survives_a_brain_that_exposes_nothing():
    class Player:
        hp, max_hp, is_player = 100, 100, True

    class G:
        player = Player()

    log = DecisionLog()
    log.observe(G(), object())
    assert log.summary()["decisions"] == 0


def test_divergence_is_zero_for_identical_policies_and_one_for_disjoint():
    a = {"rest": 0.5, "move": 0.5}
    assert divergence(a, dict(a)) == 0.0
    assert divergence({"rest": 1.0}, {"fight": 1.0}) == 1.0


def test_percentiles_are_ordered():
    p = percentiles([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert p["p10"] <= p["p50"] <= p["p90"]
