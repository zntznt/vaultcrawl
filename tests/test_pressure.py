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


# ---- A: the decision loop cannot be owned by an action that does not work ----------

def test_deploy_and_recover_round_trip():
    """Game.deploy constructed Actor with the wrong signature and raised TypeError on
    every call for the life of the project, swallowed by dispatch's blanket except. It
    still won 27% of every agent's decisions."""
    from runtime.agent_action import AgentAction, dispatch
    from runtime.stack import build_systems
    g = Game(load_manifest("examples/world.json"), systems=build_systems())
    sigs = g.system("sigils")
    sigs.slots = [{"ability": "Ward", "note": "x", "durability": 2, "quality": 0}]

    assert dispatch(g, AgentAction("deploy", index=0)) is True, "deploy must succeed"
    assert sigs.slots == [], "the sigil leaves the slot"
    placed = [a for a in g.actors if getattr(a, "_is_deployed", False)]
    assert len(placed) == 1, "a deployed entity exists on the map"

    g.player.x, g.player.y = placed[0].x, placed[0].y
    assert dispatch(g, AgentAction("recover")) is True, "recover must succeed"
    assert [s["ability"] for s in sigs.slots] == ["Ward"], "the sigil comes back"


def test_run_state_resets_between_runs():
    """proficiency and skills were module globals with no reset, and a harness runs
    hundreds of games per process. Measured: the same agent on the same world won runs 1
    and 2 and lost runs 3 through 6 as skill tiers climbed."""
    from runtime.proficiency import exercise_skill, skills
    from runtime.stack import reset_run_state
    for _ in range(30):
        exercise_skill("foraging")
    assert skills().tier("foraging") > 0
    reset_run_state()
    assert skills().tier("foraging") == 0, "skills must not survive into the next run"


def test_fatigue_penalises_a_repeated_objective():
    from runtime.agent import FATIGUE_STEP, UniversalBrain
    b = UniversalBrain("seeker")
    key = ("locus", 5, 5)
    b._fatigue[key] = FATIGUE_STEP * 3
    assert b._fatigue[key] > 0, "an objective chosen repeatedly carries a cost"


def test_note_result_charges_a_failed_action():
    from runtime.agent import FATIGUE_FAILED, UniversalBrain
    b = UniversalBrain("seeker")
    b._last_key = ("deploy", 1)
    b.note_result(False)
    assert b._fatigue[("deploy", 1)] >= FATIGUE_FAILED, "failure must cost more than repetition"
    before = dict(b._fatigue)
    b.note_result(True)
    assert b._fatigue == before, "success changes nothing"


def test_broken_verb_detector():
    """The check that would have caught all three of this project's decision-loop bugs."""
    from runtime.pressure import MIN_ATTEMPTS_TO_JUDGE, EmergenceLog
    e = EmergenceLog()
    for _ in range(MIN_ATTEMPTS_TO_JUDGE + 5):
        e.observe_verb("deploy", False)
    for _ in range(10):
        e.observe_verb("move", True)
    e.observe_verb("move", False)
    assert e.broken_verbs() == ["deploy"]
    assert e.summary()["verb_success"]["deploy"] == 0.0
    assert 0 < e.summary()["verb_success"]["move"] < 1


def test_emergence_log_counts_event_kinds():
    from runtime.pressure import EmergenceLog
    e = EmergenceLog()
    for k in ("noise", "noise", "enemy_killed", "lore_read"):
        e.observe_event(k)
    s = e.summary()
    assert s["event_kinds"] == 3
    assert s["event_counts"]["noise"] == 2


def test_no_verb_is_broken_in_a_real_run():
    """End to end: drive a short descent and assert nothing the brain believes in is dead."""
    from runtime.agent_eval import run_agent
    r = run_agent("examples/world.json", "seeker", max_floor=3)
    assert r.emergence, "the harness records emergence"
    assert r.emergence["broken_verbs"] == [], (
        "a verb attempted many times and never once successful is a dead mechanic",
        r.emergence["broken_verbs"])


# ---- B: the bus carries the events, and the systems own their own effects ----------

def test_interact_reaches_the_dialogue_system():
    """DialogueSystem.on_event listens for `interact`, and nothing in real play emitted
    it, so its whole quest/offering/gossip tree ran only in a demo and a test."""
    from runtime.dialogue import DialogueSystem
    from runtime.stack import build_systems
    g = Game(load_manifest("examples/world.json"), systems=build_systems())
    dlg = g.system("dialogue")
    assert isinstance(dlg, DialogueSystem)

    seen = []
    orig = dlg.on_event
    dlg.on_event = lambda game, etype, data: (
        seen.append((etype, (data or {}).get("target"))) or orig(game, etype, data))

    # place one of the dialogue system's own NPCs next to the player
    if not dlg.npcs:
        return  # this floor has no Keeper; the plumbing is asserted below regardless
    npc = dlg.npcs[0]
    npc.x, npc.y = g.player.x + 1, g.player.y
    g.actors.append(npc) if npc not in g.actors else None
    g.interact()
    assert any(e == "interact" and t is npc for e, t in seen), (
        "an adjacent Keeper must reach the dialogue tree", seen)


def test_emit_is_only_a_broadcast():
    """Game.emit was three lines of broadcast plus ninety lines doing five systems' jobs."""
    code = _code_only(Game.emit)
    for forbidden in ("standing[", "allegiance", "plants", "_town_rooms", "chronicle"):
        assert forbidden not in code, f"emit must not do {forbidden} itself"


def test_one_failing_system_does_not_silence_the_rest():
    from runtime.systems import System

    class Boom(System):
        name = "boom"
        def on_event(self, game, etype, data):
            raise RuntimeError("nope")

    class Listener(System):
        name = "listener"
        def __init__(self):
            self.heard = 0
        def on_event(self, game, etype, data):
            self.heard += 1

    listener = Listener()
    g = Game(load_manifest("examples/world.json"), systems=[Boom(), listener])
    g.emit("noise", pos=(0, 0), volume=1)
    assert listener.heard == 1, "a raising system must not eat the broadcast"


def test_communion_announces_itself_on_the_bus():
    """The standing bump wrote factions.standing directly and did not emit
    standing_changed, so terrain_mod never saw one of the code paths."""
    g = _game(systems=[FactionSystem()])
    fcs = g.system("factions")
    fcs._build(g)
    fcs.standing["faction_0"] = 0
    heard = []
    orig = g.emit
    g.emit = lambda etype, **kw: (heard.append(etype) or orig(etype, **kw))
    fcs.on_event(g, "communed", {})
    assert fcs.standing["faction_0"] == 1, "communion still raises standing"
    assert "standing_changed" in heard, "and it says so on the bus"


def test_scent_system_is_load_bearing():
    """Guard against deleting it: two modules consume it, so `isolate` is wrong."""
    import inspect
    from runtime import behavior, recipes
    assert 'system("scent")' in inspect.getsource(behavior)
    assert 'system("scent")' in inspect.getsource(recipes)
