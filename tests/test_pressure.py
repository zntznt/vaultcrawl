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
    assert gained <= g.player.max_hp // 3, (
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
    ok, why, route = g.egress_ready()
    assert not ok and why, "the last stair does not open for free"
    assert route == "", "and nothing claims to have opened it"


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


def test_win_path_names_the_route_that_opened_the_stair():
    """`escape` was not a route, it was the label every route got when the stair opened and
    the player walked out. Reading the vault and earning a house's trust are different
    achievements and were reported as one, which is why that one looked dominant at two
    thirds of all wins."""
    g = _game(systems=[MarginaliaSystem(), FactionSystem()])
    g.floor = g.max_floor
    g._boss_felled = True
    g.descend()
    assert g.won and g.win_path == "warden", (g.won, g.win_path)


def test_each_egress_route_names_itself():
    for setup, expected in (
        (lambda g: setattr(g, "_boss_communed", True), "warden"),
        (lambda g: setattr(g.system("marginalia"), "read", g.egress_truths_needed()),
         "truths"),
    ):
        g = _game(systems=[MarginaliaSystem(), FactionSystem()])
        setup(g)
        ok, _why, route = g.egress_ready()
        assert ok and route == expected, (expected, ok, route)


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


# ---- the descent has to be survivable ---------------------------------------------

def test_descent_mend_is_load_bearing():
    """The only resource in the game that scales with depth.

    entities.py is explicit that the player never gains stats during a run, so there is no
    power curve; the floor-enter mend is the whole of it. A previous pass cut this from
    max_hp//5 to //10 on the argument that it was a free heal handed to the winning action,
    and the win rate fell 3 to 2 to 1 of 6 over three passes while every other number
    improved. Swept against the harness: //10 and //6 win 1 of 6, //4 wins 3 of 6, //3 wins
    4 of 6.

    This test does not pin the exact value. It pins the reasoning: cutting it again without
    re-running the sweep is how the descent became unsurvivable the first time.
    """
    from runtime.game import DESCEND_MEND_DIV
    assert 3 <= DESCEND_MEND_DIV <= 5, (
        "outside the swept band; re-measure win rate before changing this",
        DESCEND_MEND_DIV)

    g = _game()
    g.player.hp = 10
    before = g.player.hp
    g.descend()
    gained = g.player.hp - before
    assert gained > 0, "reaching a new floor must mend something"
    assert gained <= g.player.max_hp // 3, "but it must not refill the bar"


# ---- the harness has to be able to measure a rate ---------------------------------

def test_run_seed_varies_the_run_without_changing_the_world():
    """Every run of one agent on one world used to be byte-identical.

    run_agent never varied anything, so `--runs 100` played the same game a hundred times
    and the reported win rate could only ever be 0% or 100%. The apparent bimodality
    across profiles (two that "never win") was that artifact: artisan wins on run seed 0
    and loses on 2 and 3.
    """
    from runtime.game import Game, load_manifest
    m = load_manifest("examples/world.json")
    a = Game(m, systems=[], run_seed=0)
    b = Game(m, systems=[], run_seed=1)
    c = Game(m, systems=[])
    assert a.seed != b.seed, "different run seeds must produce different runs"
    assert c.seed == m["seed"], "and no run seed leaves the baked world untouched"
    assert str(m["seed"]) in str(a.seed), "the world is still the same world"


def test_absorb_hazard_stops_when_it_can_no_longer_pay():
    """Hazard tiles and weather are roughly ninety percent of all HP the player loses;
    combat is a tenth. The agent parked in acid for an aspect it could no longer gain."""
    from runtime.agent import ABSORB_CAP, ABSORB_MIN_HP
    assert ABSORB_CAP >= 1 and ABSORB_MIN_HP > 0
    code = _code_only(__import__("runtime.agent", fromlist=["x"]).UniversalBrain.decide)
    assert "ABSORB_CAP" in code, "the candidate must respect the aspect budget"
    assert "ABSORB_MIN_HP" in code, "and must not trade HP it cannot spare"


def test_profile_weights_below_state_urgency_are_inert():
    """A documented consequence of the scoring formula, found while trying to fix one
    profile by raising a weight.

    score = max(profile_floor, state_urgency) + turn_bonus. So a profile weight beneath the
    typical state urgency for its candidate does nothing at all. Raising cartographer's
    flee weight from 3 to 6 to 8 produced byte-identical runs. Anyone tuning a profile
    should know the weight only bites where it exceeds the situation.
    """
    from runtime.agent import _score
    lo = {"flee": 3}
    hi = {"flee": 8}
    urgent = 20
    assert _score(lo, "flee", urgent, 0) == _score(hi, "flee", urgent, 0), (
        "below the state urgency, the weight is inert")
    calm = 1
    assert _score(hi, "flee", calm, 0) > _score(lo, "flee", calm, 0), (
        "above it, the weight is what decides")


def test_every_profile_starts_with_a_way_out():
    """The brain's panic branch has exactly one escape: cast a Phase sigil.

    Cartographer was the only profile that started with no sigil at all, and one of only
    two with a negative `fight` weight. The one profile that refuses to fight was the one
    with no way out of a fight, and it was the only profile that never won a run. Measured
    over four run seeds: 0 of 4 without a sigil, 3 of 4 with Phase.

    Berlin: the fix is starting state, which is the legal lever. Nothing here branches on
    the profile at decision time.
    """
    from runtime.stack import build_systems
    for name in ("artisan", "cartographer", "emergent", "exploiter", "seeker", "whisper"):
        g = Game(load_manifest("examples/world.json"), systems=build_systems())
        g.starting_kit(name)
        sigs = g.system("sigils")
        abilities = [s.get("ability") for s in sigs.slots]
        fight = __import__("runtime.agent", fromlist=["x"]).PROFILES[name].get("fight", 0)
        assert abilities, (name, "every profile starts with at least one sigil")
        if fight < 0:
            assert "Phase" in abilities, (
                name, "a profile that refuses combat needs the panic escape", abilities)


def test_the_profile_that_shields_has_something_to_shield_with():
    """`shield` is exploiter's highest weight by a wide margin, and its kit gave it two
    escape sigils and no defensive stat at all. It won 0 of 8 run seeds. Swept: +0 DEF
    wins 0, +1 wins 3, +2 wins 5.

    The general property, not the one profile: a profile whose top weight is a defensive
    verb must not start with zero of that stat, or the weight is decoration.
    """
    from runtime.stack import build_systems
    from runtime.agent import PROFILES
    for name, weights in PROFILES.items():
        top = max(weights, key=lambda k: weights[k])
        if top != "shield":
            continue
        g = Game(load_manifest("examples/world.json"), systems=build_systems())
        base = getattr(g.player, "defense", 0)
        g.starting_kit(name)
        assert getattr(g.player, "defense", 0) > base, (
            name, "shields hardest, starts with no defence")


def test_the_flooded_shape_stays_inside_its_region():
    """`_flood` expanded its frontier through any neighbour, so the water blob walked off
    the region and off the map onto the open integer plane. `seen` grew without bound and
    `body` counts only eligible cells, so the loop did not terminate in any useful time:
    `Game(sandbox=True)` on the shipped example world ran past ten minutes and ate enough
    memory to get the test suite OOM-killed.

    Asserted structurally rather than by wall clock, so the test does not depend on how
    fast the machine is.
    """
    import random
    from runtime.arch.areakinds import _flood, FLOOR

    w = h = 40
    tiles = [[FLOOR for _ in range(w)] for _ in range(h)]
    # one small region in the corner, with a lot of empty map around it to escape into
    cells = [(x, y) for x in range(2, 12) for y in range(2, 12)]
    outside = {(x, y) for x in range(w) for y in range(h)} - set(cells)
    _flood(tiles, cells, random.Random(1), w, h)
    escaped = [(x, y) for (x, y) in outside if tiles[y][x] != FLOOR]
    assert not escaped, ("the blob wrote outside its own region", escaped[:5])


def test_a_sandbox_world_can_actually_be_built():
    """The end of the same bug. Sandbox is the default interactive mode and it could not
    construct examples/world.json at all."""
    from runtime.stack import build_systems
    g = Game(load_manifest("examples/world.json"), systems=build_systems(), sandbox=True)
    assert g.level is not None and g.player is not None


# ---- C: the chemistry is combinatorial ---------------------------------------------

def _reactions_game():
    from runtime.reactions import ReactionSystem
    return Game(load_manifest("examples/world.json"), systems=[ReactionSystem()])


def test_element_pairs_actually_interact():
    """Two of fifteen possible pairs did anything. Water did not put out fire, and acid,
    despite the module docstring, corroded nothing."""
    from runtime.reactions import _PAIR_REACTIONS
    assert len(_PAIR_REACTIONS) + 1 >= 8, (  # +1 for the charged/wet chain component
        "at least eight of fifteen element pairs must interact", len(_PAIR_REACTIONS))
    for pair in _PAIR_REACTIONS:
        assert len(pair) == 2, "keys are unordered pairs, so the table cannot be asymmetric"


def test_water_puts_out_fire():
    g = _reactions_game()
    r = g.system("reactions")
    pos = (g.player.x + 6, g.player.y + 6)
    r.props[pos] = {"fire", "wet"}
    r._resolve_pairs(g)
    assert "fire" not in r.props.get(pos, set()), "water must put out fire"


def test_ice_smothers_fire_and_leaves_water():
    g = _reactions_game()
    r = g.system("reactions")
    pos = (g.player.x + 6, g.player.y + 6)
    r.props[pos] = {"fire", "ice"}
    r._resolve_pairs(g)
    assert r.props.get(pos) == {"wet"}, r.props.get(pos)


def test_pair_resolution_is_order_independent():
    """Keyed by frozenset, so there is no 'which one did we see first'."""
    from runtime.reactions import _PAIR_REACTIONS
    for pair in _PAIR_REACTIONS:
        a, b = tuple(pair)
        outs = []
        for order in ({a, b}, {b, a}):
            g = _reactions_game()
            r = g.system("reactions")
            pos = (g.player.x + 6, g.player.y + 6)
            r.props[pos] = set(order)
            r._resolve_pairs(g)
            outs.append(frozenset(r.props.get(pos, frozenset())))
        assert outs[0] == outs[1], (pair, outs)


def test_ice_and_sacred_can_actually_be_dealt():
    """Only fire, shock and acid dealt damage, so a flammable creature could never meet
    the 2x from its opposite and an acid one could never meet sacred: none of the three
    opposite pairs had both directions reachable."""
    from runtime.reactions import _CHILL_DAMAGE, _ELEMENT_OPPOSITE
    assert _CHILL_DAMAGE > 0, "ice has to bite for the frozen/flammable pair to mean anything"
    damaging = {"flammable", "charged", "corrosive", "frozen", "sacred"}
    pairs = {frozenset({a, b}) for a, b in _ELEMENT_OPPOSITE.items()}
    live = sum(1 for p in pairs if p <= damaging)
    assert live >= 2, ("at least two opposite pairs must be fully reachable", live)


# ---- C3: fire travels ---------------------------------------------------------------

def test_a_creature_standing_in_fire_catches():
    g = _reactions_game()
    r = g.system("reactions")
    foe = next(a for a in g.actors if a.allegiance == "monster")
    foe.hp = foe.max_hp = 99
    r.props.clear()
    r.ignite(foe.x, foe.y, life=8)
    for _ in range(6):
        r.on_player_act(g)
        if getattr(foe, "_burning", 0):
            return
    raise AssertionError("a creature standing in flame must eventually catch")


def test_a_burning_creature_sets_light_to_ground_nobody_touched():
    """The whole point of C3. Every ignite call site writes to a tile, never an actor, so
    the chemistry was one step deep: a thing could burn but could not carry the fire."""
    g = _reactions_game()
    r = g.system("reactions")
    foe = next(a for a in g.actors if a.allegiance == "monster")
    foe.hp = foe.max_hp = 99
    r.props.clear()
    foe._burning = 5
    lit = []
    for _ in range(3):
        foe.x += 1
        r.props.pop((foe.x, foe.y), None)
        r.on_player_act(g)
        lit.append("fire" in r.props.get((foe.x, foe.y), set()))
    assert all(lit), ("a burning creature leaves fire behind it", lit)


def test_water_puts_a_burning_creature_out():
    g = _reactions_game()
    r = g.system("reactions")
    foe = next(a for a in g.actors if a.allegiance == "monster")
    foe.hp = foe.max_hp = 99
    r.props.clear()
    foe._burning = 3
    r.props[(foe.x, foe.y)] = {"wet"}
    r.on_player_act(g)
    assert not getattr(foe, "_burning", 0), "standing in water puts you out"


def test_burning_the_player_out_actually_kills():
    """Hazard tile damage is capped and can never kill, so it can leave the player on 0 HP
    and still 'alive'. Burning is not capped, so it has to route through the death path
    or the same hole opens wider."""
    g = _reactions_game()
    r = g.system("reactions")
    r.props.clear()
    g.player.hp = 1
    g.player._burning = 3
    r.props.pop((g.player.x, g.player.y), None)
    r.on_player_act(g)
    assert not g.alive, "burning to zero has to end the run"
    assert g.player.hp <= 0


def test_burning_is_bounded():
    """Fire on actors must not be a new runaway. It burns out on its own."""
    from runtime.reactions import BURN_TURNS
    g = _reactions_game()
    r = g.system("reactions")
    foe = next(a for a in g.actors if a.allegiance == "monster")
    foe.hp = foe.max_hp = 999
    r.props.clear()
    foe._burning = BURN_TURNS
    for _ in range(BURN_TURNS + 2):
        # keep it off burning ground so only the status matters
        foe.x += 1
        r.props.pop((foe.x, foe.y), None)
        r.props.pop((foe.x + 1, foe.y), None)
        r.on_player_act(g)
    assert getattr(foe, "_burning", 0) == 0, "burning has to end by itself"


# ---- D: closing the runaway loop -----------------------------------------------------

def test_upheaval_survives_every_event_the_chronicle_can_produce():
    """`from_events` did `e["kind"], e["note"]` unconditionally, and six of the ten kinds
    `to_upheaval_events` produces carry no note key. Wiring the two halves together raised
    KeyError on the first faction or terraforming event, which is why the circuit was
    never closed."""
    from runtime.persistence import chronicle, reset_chronicle
    from runtime.upheaval import Upheaval

    reset_chronicle()
    c = chronicle()
    c.record_lore("note-a"); c.record_lore("note-b"); c.record_lore("note-c")
    for _ in range(3):
        c.record_forge("region_1")
    c.record_faction_end("faction_0", 6)
    c.record_faction_end("faction_1", -6)
    c.record_companion_death("Ally", "The Warden")
    c.record_death((3, 4), 0, {}, "struck down", False, False, 9)
    c.rest_count = 60
    c.sacred_ground_ticks = 45

    events = c.to_upheaval_events()
    kinds = {e["kind"] for e in events}
    assert len(kinds) >= 6, kinds
    u = Upheaval.from_events(events)          # used to raise KeyError: 'note'
    assert u.total > 0
    assert "region_1" in u.forge_sanctums
    assert "faction_0" in u.contested
    reset_chronicle()


def test_a_run_hands_its_events_to_the_next_run(tmp_path):
    """The missing return arrow. `to_upheaval_events` had zero callers, so nothing play
    produced could reach a later world: the only route was editing notes and re-baking."""
    from runtime.persistence import (chronicle, reset_chronicle,
                                     save_chronicle, load_chronicle_events)
    from runtime.upheaval import Upheaval

    store = str(tmp_path / "chronicle.json")
    reset_chronicle()
    for _ in range(3):
        chronicle().record_forge("region_7")
    assert save_chronicle("world-seed", store) > 0

    reset_chronicle()
    assert not chronicle().to_upheaval_events(), "the next run starts empty"
    past = load_chronicle_events("world-seed", store)
    assert Upheaval.from_events(past).forge_sanctums == {"region_7"}
    reset_chronicle()


def test_the_chronicle_is_bounded(tmp_path):
    """A return arrow is not licence for unbounded growth. Repeated runs on one world
    dedupe on event identity and the store is capped."""
    from runtime.persistence import (chronicle, reset_chronicle, save_chronicle,
                                     load_chronicle_events, CHRONICLE_MAX)
    store = str(tmp_path / "chronicle.json")
    for run in range(40):
        reset_chronicle()
        for _ in range(3):
            chronicle().record_forge(f"region_{run}")
        chronicle().record_forge("region_same")
        chronicle().record_forge("region_same")
        chronicle().record_forge("region_same")
        save_chronicle("w", store)
    stored = load_chronicle_events("w", store)
    assert len(stored) <= CHRONICLE_MAX, len(stored)
    keys = [(e.get("kind"), e.get("note")) for e in stored]
    assert len(keys) == len(set(keys)), "the same event must not stack"
    reset_chronicle()


def test_graves_escalate():
    """`_load_graves` assigned into a dict keyed by position, so N deaths on one tile
    loaded as one record and `_animate_graves` read `deaths` as the constant 2 forever.
    The ghost could never scale, however many times that tile had killed you."""
    import json, os
    from runtime.stack import build_systems
    g = Game(load_manifest("examples/world.json"), systems=build_systems())
    path = os.path.expanduser("~/.vaultcrawl/graves.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prior = None
    if os.path.exists(path):
        prior = open(path, encoding="utf-8").read()
    try:
        entries = [{"pos": [4, 4], "text": f"Here lies you, slain by a foe number {i}."}
                   for i in range(3)]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({g.seed: entries}, fh)
        g._graves = {}
        g._load_graves()
        text = g._graves[(4, 4)]
        assert text.count("slain by") == 3, ("three deaths, three records", text)
    finally:
        if prior is None:
            os.remove(path)
        else:
            open(path, "w", encoding="utf-8").write(prior)


def test_the_attractor_tracker_is_one_object_per_run():
    """`tracker()` returned a NEW AttractorTracker on every call, so anything recording
    from inside the game wrote into a throwaway. That is the structural reason three of
    the six scores were pinned at 0.0."""
    from runtime.attractors import tracker, reset_tracker
    reset_tracker()
    a = tracker()
    a.record_ghost_seen()
    assert tracker() is a, "one tracker per run, not one per call"
    assert tracker().ghosts_seen == 1
    reset_tracker()
    assert tracker().ghosts_seen == 0, "and reset between runs"


def test_no_attractor_score_is_structurally_unreachable():
    """Three of six were permanently 0.0 because their recorders had zero callers.
    Drive each recorder and assert the score it feeds can actually move."""
    from runtime.attractors import tracker, reset_tracker
    reset_tracker()
    t = tracker()
    t.record_note_learned(); t.record_note_learned()
    t.record_ghost_seen()
    t.record_companion_recruited(); t.record_companion_died()
    t.record_echo_fire(); t.record_echo_fire()
    t.record_matter_collected(10); t.record_matter_forged(10)
    t.record_floor(1, 0); t.record_floor(2, 0); t.record_floor(3, 0)
    t.record_standing({"a": 5, "b": -5})
    scores = t.scores()
    dead = [k for k, v in scores.items() if v == 0.0]
    assert not dead, ("every attractor must be reachable", dead, scores)
    reset_tracker()


def test_the_industrial_score_is_not_backwards():
    """It divided by an end-of-run inventory residual as if it were cumulative
    collection, so SPENDING matter shrank the denominator and pushed the score up."""
    from runtime.attractors import tracker, reset_tracker
    reset_tracker()
    t = tracker()
    t.record_matter_collected(100)
    t.record_matter_forged(60)
    low = t.scores()["industrial"]
    t.record_matter_forged(40)          # forge more of the same intake
    assert t.scores()["industrial"] > low, "forging more must raise the forge score"
    reset_tracker()


def test_collecting_matter_is_counted_where_it_happens():
    """Inventory.add is the only place matter enters an inventory, so it is the only
    honest place to count intake."""
    from runtime.attractors import tracker, reset_tracker
    from runtime.components import Inventory
    reset_tracker()
    inv = Inventory()
    inv.add({"iron": 3, "brass": 2}, quality=1)
    assert tracker().matter_collected == 5
    inv.pay({"iron": 3})
    assert tracker().matter_collected == 5, "spending is not un-collecting"
    reset_tracker()


# ---- D4: one loop with gain above 1 --------------------------------------------------

def _faction_game():
    from runtime.factions import FactionSystem
    g = Game(load_manifest("examples/world.json"), systems=[FactionSystem()])
    return g, g.system("factions")


def _provoke(fcs, fac, n):
    fcs.disturbance[fac] = fcs.disturbance.get(fac, 0) + n


def test_repeated_provocation_escalates_instead_of_settling():
    """Every loop in the codebase was capped or subcritical, which is why nothing ever
    ran away. Four alert dispatched 1 to 2 hunters and killing both loudly returned 2, so
    the loop gave back half of what it cost. Hunter tier read the floor and nothing else."""
    from runtime.factions import PURSUIT_MAX
    g, fcs = _faction_game()
    region = g.region_for(g.floor) or {}
    fac = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    if not fac:
        return  # this world's first floor has no owning house

    waves = []
    for _ in range(PURSUIT_MAX + 1):
        _provoke(fcs, fac, 4)
        before = len([a for a in g.actors if getattr(a, "is_hunter", False)])
        fcs.on_floor_enter(g)
        after = len([a for a in g.actors if getattr(a, "is_hunter", False)])
        waves.append(after - before)
    assert waves[-1] > waves[0], ("a house that keeps having to come after you sends "
                                  "more each time", waves)
    assert fcs.pursuit[fac] == PURSUIT_MAX, "and the grudge is remembered"


def test_the_alert_a_wave_costs_falls_as_the_grudge_deepens():
    """This is the term that carries the loop past gain 1. A wave of N hunters returns N
    disturbance when fought loudly; if the next wave costs less than N, it compounds."""
    from runtime.factions import PURSUIT_MAX, _PURSUIT_FLOOR_ALERT
    need = [max(_PURSUIT_FLOOR_ALERT, 4 - p) for p in range(PURSUIT_MAX + 1)]
    # hunters dispatched at grudge p: rng.randint(1, 2) + p, so at least 1 + p
    gain = [(1 + p) / need[p] for p in range(PURSUIT_MAX + 1)]
    assert gain[0] < 1.0, ("an unprovoked house is still subcritical", gain[0])
    assert max(gain) > 1.0, ("some depth of grudge has to be supercritical", gain)


def test_leaving_the_country_cools_the_pursuit():
    """Termination 1, and the one the plan named. A house can only hunt you where it can
    find you."""
    from runtime.factions import PURSUIT_DECAY
    g, fcs = _faction_game()
    region = g.region_for(g.floor) or {}
    here = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    other = next((f for f in fcs.standing if f != here), "faction_absent")
    fcs.pursuit[other] = 3
    fcs.on_floor_enter(g)
    assert fcs.pursuit[other] == 3 - PURSUIT_DECAY, "elsewhere, the grudge cools"


def test_going_quiet_cools_the_pursuit():
    """Termination 2. An environment kill is a thread the search loses, so the house
    never learns there was anything to pursue."""
    g, fcs = _faction_game()
    foe = next((a for a in g.actors if a.allegiance == "monster"
                and fcs.faction_of(getattr(a, "source", ""))), None)
    if foe is None:
        return
    fac = fcs.faction_of(foe.source)
    fcs.pursuit[fac] = 3
    fcs.disturbance[fac] = 3
    fcs._quiet_kill(g, foe)
    assert fcs.pursuit[fac] == 2, "a kill nobody saw walks the grudge back"


def test_peace_ends_the_grudge_not_just_the_wave():
    """Termination 3. A friend calling the hunters off already existed; it cleared the
    current wave and left the escalation running underneath."""
    g, fcs = _faction_game()
    region = g.region_for(g.floor) or {}
    fac = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    if not fac:
        return
    friend = next((f for f in fcs.standing if f != fac), None)
    if friend is None:
        return
    fcs.standing[friend] = 5
    fcs.pursuit[fac] = 3
    fcs.disturbance[fac] = 6
    fcs.on_floor_enter(g)
    assert fcs.pursuit[fac] == 0, "making peace ends it"


def test_the_escalation_is_bounded():
    """Termination 4. Gain above 1 with no ceiling is a crash, not a game."""
    from runtime.factions import PURSUIT_MAX
    g, fcs = _faction_game()
    region = g.region_for(g.floor) or {}
    fac = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    if not fac:
        return
    for _ in range(20):
        _provoke(fcs, fac, 6)
        fcs.on_floor_enter(g)
    assert fcs.pursuit[fac] <= PURSUIT_MAX, fcs.pursuit[fac]


def test_pursuit_reads_no_profile():
    """Berlin: the escalation answers what you did, never who you are."""
    from runtime.factions import FactionSystem
    code = _code_only(FactionSystem.on_floor_enter)
    for forbidden in ("brain", "profile", "artisan", "whisper", "_agent_name"):
        assert forbidden not in code, f"on_floor_enter must not branch on {forbidden}"


# ---- the rest weight is decoration on every profile ----------------------------------

def test_the_rest_weight_never_decides_whether_to_rest():
    """`rest` urgency is (100 - hp_pct) // 3, so inside the window where the branch is even
    reachable (hp below 70) it runs 10 to 30. Every profile's `rest` floor is at most 5, and
    the score is max(floor, urgency), so for the REST candidate the floor never once decides
    anything.

    It is not a dead weight though, and assuming so is a trap: `clear_weather` and
    `absorb_hazard` score off the same `rest` key with much lower urgencies, so the floor is
    live there. Tuning `rest` changes what the agent does about weather and hazard tiles,
    not how often it heals. A sweep of exploiter's rest floor from 3 to 5 changed its runs
    for exactly this reason and moved its healing not at all.
    """
    from runtime.agent import PROFILES
    lowest_rest_urgency = (100 - 69) // 3       # the least urgent reachable heal
    for name, weights in PROFILES.items():
        floor = weights.get("rest", 0)
        assert floor < lowest_rest_urgency, (
            name, "a rest floor above the minimum urgency would finally decide a heal; if "
                  "that is intended, change this test alongside the sweep that proves it",
            floor, lowest_rest_urgency)
    # and the other two users of the key, where the same floor genuinely competes
    weather_urgency_at_full_hp = 3
    assert any(w.get("rest", 0) > weather_urgency_at_full_hp for w in PROFILES.values()), (
        "the rest key is shared with clear_weather; if no profile's floor clears its "
        "urgency the key really is dead and the sharing should go")


def test_shield_outbids_healing_only_in_a_narrow_band():
    """Exploiter's defining weight is `shield` at 15, and shield's own urgency is 8 or 12,
    so unlike `rest` it IS live and it is the dominant term.

    The band where that matters is narrower than it looks. Rest scores (100 - hp) // 3, so
    a flat 15 beats it only while HP is above 55 percent, and the two tie exactly at 55.
    Below that, healing wins on urgency alone. So shield delays the first heal by a slice
    of the HP bar rather than replacing healing outright, which is why the profile's
    survivability does not move when the rest weight is tuned.

    Berlin: this is a preference, not a lock. The test pins where the crossover sits, so a
    change of character shows up as a failing test instead of a silent regression.
    """
    from runtime.agent import PROFILES
    ex = PROFILES["exploiter"]

    def rest_at(hp_pct):
        return max(ex.get("rest", 0), (100 - hp_pct) // 3)
    shield = max(ex.get("shield", 0), 12)

    assert shield > rest_at(60), ("shield leads while barely hurt", shield, rest_at(60))
    assert shield == rest_at(55), ("and ties at the crossover", shield, rest_at(55))
    assert shield < rest_at(45), ("healing takes over once it is urgent",
                                  shield, rest_at(45))


# ---- the player side of the escalation loop ------------------------------------------

def test_hostility_thaws_while_you_are_elsewhere():
    """Standing had no floor and no decay: it fell 1 per heard kill, forever. Measured at
    end of run, a loud profile finished at -10 to -22 while a quiet one sat near 0.

    That is load-bearing, because `rest_modifier` returns 0 below standing -3, so past
    that point resting in that house's country restores nothing at all. Kill loudly, lose
    standing, lose healing, have to kill to survive: gain above 1 and no exit. D4 gave the
    faction's pursuit a decay and left reputation ratcheting, which was the asymmetry.
    """
    from runtime.factions import FactionSystem, STANDING_THAW
    g = Game(load_manifest("examples/world.json"), systems=[FactionSystem()])
    fcs = g.system("factions")
    region = g.region_for(g.floor) or {}
    here = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    other = next((f for f in fcs.standing if f != here), None)
    if other is None:
        return
    fcs.standing[other] = -8
    fcs.on_floor_enter(g)
    assert fcs.standing[other] == -8 + STANDING_THAW, (
        "a house you are nowhere near stops actively hating you", fcs.standing[other])


def test_the_thaw_stops_at_neutral_and_does_not_touch_goodwill():
    """Hostility fading is the exit that makes the escalation survivable. Goodwill fading
    would be a different rule that quietly taxes the diplomatic route, so it is not made."""
    from runtime.factions import FactionSystem
    g = Game(load_manifest("examples/world.json"), systems=[FactionSystem()])
    fcs = g.system("factions")
    region = g.region_for(g.floor) or {}
    here = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    others = [f for f in fcs.standing if f != here][:2]
    if len(others) < 2:
        return
    fcs.standing[others[0]] = 0
    fcs.standing[others[1]] = 5
    for _ in range(4):
        fcs.on_floor_enter(g)
    assert fcs.standing[others[0]] == 0, "neutral is the ceiling of the thaw"
    assert fcs.standing[others[1]] == 5, "earned goodwill is not eroded by time"


def test_standing_does_not_thaw_where_you_are_standing():
    """The house whose country you are in is watching. Leaving is the exit, and it has to
    cost something or it is not one."""
    from runtime.factions import FactionSystem
    g = Game(load_manifest("examples/world.json"), systems=[FactionSystem()])
    fcs = g.system("factions")
    region = g.region_for(g.floor) or {}
    here = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    if not here:
        return
    fcs.standing[here] = -6
    fcs.on_floor_enter(g)
    assert fcs.standing[here] == -6, "standing in their country, they keep their grudge"


def test_being_hated_still_costs_the_heal():
    """The thaw must not quietly repeal the rule it is an exit from."""
    from runtime.factions import FactionSystem
    g = Game(load_manifest("examples/world.json"), systems=[FactionSystem()])
    fcs = g.system("factions")
    region = g.region_for(g.floor) or {}
    fid = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    if not fid:
        return
    fcs.standing[fid] = -4
    assert fcs.rest_modifier(g) == 0, "deep hostility still means no rest here"


def test_the_thaw_reads_no_profile():
    """Berlin: it is the same clock for everyone, and it lands hardest on whoever has
    spent the most reputation, which is a consequence of play and not of identity."""
    from runtime.factions import FactionSystem
    code = _code_only(FactionSystem.on_floor_enter)
    for forbidden in ("brain", "profile", "artisan", "whisper", "_agent_name"):
        assert forbidden not in code, f"on_floor_enter must not branch on {forbidden}"


def test_heard_kills_cannot_sink_you_past_the_heal():
    """The ratchet, and the constraint that actually bound the loud profile.

    Standing fell 1 per heard kill with nothing underneath it: measured at end of run, a
    loud profile finished at -10 to -22 off about 135 heard kills. `rest_modifier` returns
    0 below -3, so past that point resting restores nothing and the loop closes on itself.
    Probed by removing the gate outright, the profile living in that state went from 1 win
    in 8 to 5. The floor keeps the penalty and removes the lockout.
    """
    from runtime.factions import FactionSystem, STANDING_MIN
    g = Game(load_manifest("examples/world.json"), systems=[FactionSystem()])
    fcs = g.system("factions")
    foe = next((a for a in g.actors if a.allegiance == "monster"
                and fcs.faction_of(getattr(a, "source", ""))), None)
    if foe is None:
        return
    fac = fcs.faction_of(foe.source)
    for _ in range(40):
        fcs._loud_kill(g, foe)
    assert fcs.standing[fac] == STANDING_MIN, (
        "forty heard kills, and the house's opinion still has a bottom",
        fcs.standing[fac])


def test_the_floor_leaves_a_rest_worth_taking():
    """The point of the floor is that hostility costs most of the heal, not all of it.
    If STANDING_MIN ever moves to where rest_modifier is 0, the lockout is back and this
    test says so."""
    from runtime.factions import FactionSystem, STANDING_MIN
    g = Game(load_manifest("examples/world.json"), systems=[FactionSystem()])
    fcs = g.system("factions")
    region = g.region_for(g.floor) or {}
    fid = region.get("factionId") or g._region_faction.get(region.get("id", ""), "")
    if not fid:
        return
    fcs.standing[fid] = 0
    neutral = fcs.rest_modifier(g)
    fcs.standing[fid] = STANDING_MIN
    hated = fcs.rest_modifier(g)
    assert hated > 0, ("at the worst play can reach, a rest still returns something",
                       STANDING_MIN, hated)
    assert hated < neutral, "and it is still much worse than being on good terms"


def test_the_floor_binds_heard_kills_only():
    """Other things move standing (a companion dying, a friend calling off hunters). The
    floor is on the ratchet, not on the whole reputation system, so a test that asserts
    the deep-hostility rule can still set it directly."""
    from runtime.factions import FactionSystem, STANDING_MIN
    g = Game(load_manifest("examples/world.json"), systems=[FactionSystem()])
    fcs = g.system("factions")
    fcs.standing["faction_probe"] = STANDING_MIN - 5
    assert fcs.standing_of("faction_probe") == STANDING_MIN - 5, (
        "the floor is applied where standing is spent, not as a global clamp")


def test_a_profile_that_cannot_fight_can_still_take_a_hit():
    """Cartographer died early or won late and nothing in between: three wins all ending at
    standing 7 to 22 by escape, and three of five losses on floor 5 or 13 inside 1,600
    turns. With `fight` at -5 it flees below 90 percent HP and kills 2 to 6 things a run,
    so it cannot clear a threat and an early elite simply kills it.

    The general property: a profile whose `fight` weight is negative has no way to trade
    blows, so it must start with something that lets it absorb one. Raw HP does not count,
    because it has twice now been measured byte-identical for this profile.
    """
    from runtime.stack import build_systems
    from runtime.agent import PROFILES
    for name, weights in PROFILES.items():
        if weights.get("fight", 0) >= 0:
            continue
        g = Game(load_manifest("examples/world.json"), systems=build_systems())
        base_def = getattr(g.player, "defense", 0)
        g.starting_kit(name)
        sigs = g.system("sigils")
        abilities = [s.get("ability") for s in sigs.slots]
        has_mitigation = (getattr(g.player, "defense", 0) > base_def
                          or "Ward" in abilities)
        assert has_mitigation, (
            name, "a profile that refuses combat needs some way to survive one round of it",
            abilities, getattr(g.player, "defense", 0))


def test_every_profile_can_reach_the_panic_escape():
    """The brain's panic branch (low HP, hostiles near) can do exactly one thing: cast a
    Phase sigil. A profile without one cannot take that branch at all, whatever its HP.

    Cartographer was once the only profile with no sigil at all, and giving it one took it
    from 0 wins in 4 to 3. Seeker later gained Phase the same way, going from 4 of 8 to 5.

    Lacking Phase is NOT on its own an explanation for a weak profile, and the test says so
    by naming the exceptions rather than asserting a rule that does not hold: artisan has
    never carried Phase and sits mid-table, and emergent was fixed by a `stairs` weight
    instead, which matched a Phase-plus-defence arm at 5 of 8 on the same seeds. Both are
    measured choices. This test exists to make a THIRD profile silently losing its escape
    show up as a failure.
    """
    from runtime.stack import build_systems
    from runtime.agent import PROFILES
    without = []
    for name in sorted(PROFILES):
        g = Game(load_manifest("examples/world.json"), systems=build_systems())
        g.starting_kit(name)
        sigs = g.system("sigils")
        if "Phase" not in [s.get("ability") for s in sigs.slots]:
            without.append(name)
    assert without == ["artisan", "emergent"], (
        "the set of profiles without the panic escape is a deliberate, measured list",
        without)


def test_the_stairs_weight_is_live():
    """Unlike `rest`, whose urgency of 10 to 30 buries every profile's floor, the stairs
    candidate's base state urgency is 2. So a stairs weight is a real decision, and emergent
    sitting at 1 was the reason it ground floor 2 for 300 turns and died there.
    """
    from runtime.agent import PROFILES
    stairs_base_urgency = 2
    live = [n for n, w in PROFILES.items() if w.get("stairs", 0) > stairs_base_urgency]
    assert live, ("if no profile's stairs floor clears the base urgency, the weight is "
                  "decoration and the key should go", {n: w.get('stairs') for n, w in PROFILES.items()})
    assert PROFILES["emergent"]["stairs"] > stairs_base_urgency, (
        "the profile that would not descend has to actually want to")


# ---- the truths route: payout guard and threshold basis -------------------------------

def test_a_mark_that_says_nothing_is_not_spent():
    """`spent` was added to before `weave` was even called, so a note that wove nothing was
    gone from every later floor and paid nothing for it. The route needs 5 of the roughly 8
    notes a descent ever places, so each silent step cost it an eighth of its supply.

    It never fires on the sample corpus, where weave pays 100 of 100 on all ten notes, so
    the guard is free here. It matters for a vault too thin to weave from, which is exactly
    the vault that can least afford to lose the route.
    """
    g = _game(systems=[MarginaliaSystem()])
    ms = g.system("marginalia")
    if not ms.ground:
        return
    pos, nid = next(iter(ms.ground.items()))
    g.player.x, g.player.y = pos
    import runtime.marginalia as M
    real_weave = M.weave
    M.weave = lambda *a, **k: ""          # a note with nothing legible in it
    try:
        before = ms.read
        ms.on_player_act(g)
    finally:
        M.weave = real_weave
    assert ms.read == before, "a silent mark pays nothing, which was always true"
    assert nid not in ms.spent, "and now it is not burned for nothing either"
    assert pos not in ms.ground, (
        "it still leaves this floor, so standing on it does not re-roll every turn")


def test_a_mark_that_speaks_is_still_spent_once():
    """The guard must not make truths re-readable; that was the unbounded-truths bug."""
    g = _game(systems=[MarginaliaSystem()])
    ms = g.system("marginalia")
    if not ms.ground:
        return
    pos, nid = next(iter(ms.ground.items()))
    g.player.x, g.player.y = pos
    before = ms.read
    ms.on_player_act(g)
    assert ms.read == before + 1
    assert nid in ms.spent
    ms.on_floor_enter(g)
    assert nid not in ms.ground.values(), "a note that has spoken does not come back"


def test_the_truths_threshold_asks_for_a_share_of_what_is_reachable():
    """The docstring's intent is half the notes, but half the NOTES is not half the notes
    you can reach: of 10 in the sample vault only 8 are ever placed as a mark across a full
    26-floor descent, so a flat `notes // 2` asked for 63 percent of the obtainable supply.
    """
    from runtime.game import (EGRESS_TRUTHS_TENTHS, EGRESS_TRUTHS_MIN,
                              EGRESS_TRUTHS_MAX, Game)
    g = _game()
    notes = len(g.m.get("graph", {}).get("nodes", {}))
    need = g.egress_truths_needed()
    assert need == max(EGRESS_TRUTHS_MIN,
                       min(EGRESS_TRUTHS_MAX, notes * EGRESS_TRUTHS_TENTHS // 10))
    assert EGRESS_TRUTHS_TENTHS < 5, (
        "a flat half of the vault's notes is more than half of what a run can reach; "
        "if this goes back to 5 it should come with a sweep that justifies it")
    placeable = 8               # measured on this vault, see PROJECT_ASSESSMENT.md
    assert need <= placeable, ("never ask for more than a descent can offer", need)


def test_the_truths_threshold_stays_bounded():
    from runtime.game import EGRESS_TRUTHS_MIN, EGRESS_TRUTHS_MAX
    g = _game()
    need = g.egress_truths_needed()
    assert EGRESS_TRUTHS_MIN <= need <= EGRESS_TRUTHS_MAX


def test_the_commune_pull_does_not_drown_out_every_identity():
    """`commune_ready` adds COMMUNE_PULL_BASE plus 2 per floor of closeness to the stairs
    candidate. At 20 that is 20 to 38, against a table whose largest profile weight is 15,
    so once the warden was reachable nothing any profile wanted could outbid descending:
    seeker spent 22 percent of all its turns steering at the warden and won by commune in
    8 runs of 8.

    The property, not the number: at its weakest the pull must not already exceed every
    weight in the table, or profile identity stops meaning anything the moment commune
    comes online. It is still allowed to dominate when the warden is one floor away, which
    is the point of a pull.
    """
    from runtime.agent import COMMUNE_PULL_BASE, COMMUNE_PULL_STEP, PROFILES
    strongest = max(max(w.values()) for w in PROFILES.values())
    weakest_pull = COMMUNE_PULL_BASE                      # ten floors out
    strongest_pull = COMMUNE_PULL_BASE + 10 * COMMUNE_PULL_STEP
    assert weakest_pull <= strongest, (
        "far from the warden, the pull must not already outbid the strongest identity "
        "in the table", weakest_pull, strongest)
    assert strongest_pull > strongest, (
        "standing on the warden's floor it should still win", strongest_pull)


def test_the_warden_commune_is_priced_like_any_other():
    """It was the one commune in the game that was free, and it was the run-winning one.
    Two long-failing tests in test_commune.py were asserting this all along."""
    from runtime.game import BOSS_COMMUNE_TRUTHS, COMMUNE_TRUTHS
    assert BOSS_COMMUNE_TRUTHS == COMMUNE_TRUTHS, (
        "the warden is an elite like the others; a special case here is what made commune "
        "take 16 of 26 wins")


def test_the_standing_route_is_an_achievement_not_a_side_effect():
    """`EGRESS_STANDING` was 3, and an independent census found standing at 3 or better in
    33 of 48 runs. Once `escape` was split into the routes it had been hiding, that one
    condition turned out to carry 65 percent of all victories.

    Swept: gate 3 gives a 65 percent top route, gate 5 gives 56, gate 7 gives 45 and is the
    first setting at which all four routes appear in one batch. The property asserted here
    is that the gate sits above the standing a run picks up incidentally, which the perk
    table pins at 4, the point where a house is already a friend.
    """
    from runtime.game import EGRESS_STANDING, FRIEND_STANDING
    assert EGRESS_STANDING > FRIEND_STANDING, (
        "the last stair should ask for more than the reputation at which a house merely "
        "stops fighting you", EGRESS_STANDING, FRIEND_STANDING)


def test_no_single_egress_route_is_the_default():
    """The four routes are a disjunction, so the cheapest one is the only one that matters
    unless they are priced against each other. Asserted structurally: each route's gate has
    to be non-trivial on its own terms."""
    from runtime.game import (BOSS_COMMUNE_TRUTHS, EGRESS_STANDING,
                              EGRESS_TRUTHS_MIN, FRIEND_STANDING)
    g = _game()
    assert g.egress_truths_needed() >= EGRESS_TRUTHS_MIN >= 3, "truths asks for something"
    assert EGRESS_STANDING > FRIEND_STANDING, "standing asks for more than friendship"
    assert BOSS_COMMUNE_TRUTHS > 0, "communing with the warden is not free"
