"""Behaviour tests for the deliberate planner brain (mastermind).

Everything runs against a *real* Game built from the example world with the live
SenseField + ReactionSystem + MemorySystem registered (so targeting is perception-limited
and beliefs are real). Hazards are staged by writing `reactions.props` directly — the same
lever the reaction/tactics tests use — and a small open arena is carved into the level so
the geometry is fully controlled. No rng, no clock: fixed positions only, so every
assertion is deterministic across runs.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_planner
"""
from runtime.game import Game, load_manifest
from runtime.senses import SenseField
from runtime.reactions import ReactionSystem
from runtime.memory import MemorySystem, mem, recalled_spot
from runtime.entities import Actor
from runtime.sense import HunterBrain, nearest_hostile, is_dangerous, danger_tiles
from runtime.planner import MastermindBrain, StrategistBrain


# --------------------------------------------------------------------------- #
# staging helpers
# --------------------------------------------------------------------------- #

def _new_game():
    return Game(load_manifest("examples/world.json"),
                systems=[SenseField(), ReactionSystem(), MemorySystem()])


def _carve(level, x0, y0, w, h):
    """Carve a w x h open floor block with its top-left at (x0, y0)."""
    for yy in range(y0, y0 + h):
        for xx in range(x0, x0 + w):
            level.tiles[yy][xx] = "."


def _monster(x, y):
    # tier-4 schemer: the capability tier the mastermind is meant for
    return Actor(x=x, y=y, glyph="g", name="mastermind", hp=40, max_hp=40, atk=6,
                 defense=0, tier=4, allegiance="monster")


def _foe(x, y):
    # a wild critter: hostile to the monster (so it chases), indifferent to the player
    return Actor(x=x, y=y, glyph="b", name="quarry", hp=20, max_hp=20, atk=3,
                 defense=0, allegiance="wild")


def _stage_arena(g):
    """Carve a 3-row open arena (rows 2-4, cols 2-11) and clear seeded hazards.
    Returns the middle row y and the left column x0."""
    _carve(g.level, 2, 2, 10, 3)
    rx = g.system("reactions")
    rx.props, rx.fire_life = {}, {}
    # keep the player well outside the arena and outside the mastermind's sight
    g.player.x, g.player.y = 19, 14
    g.player.hp = g.player.max_hp
    return 2, 3  # x0, y


def _drive(g, mm, foe):
    """Advance one full turn deterministically: the mastermind acts, then the foe chases,
    then the systems resolve (ReactionSystem bites anything on a hazard; MemorySystem ages
    beliefs). Mirrors Game.try_move's order (movers first, systems last)."""
    g.turn += 1
    dx, dy = mm.brain.decide(g, mm)
    g._npc_step(mm, dx, dy)
    fdx, fdy = foe.brain.decide(g, foe)
    g._npc_step(foe, fdx, fdy)
    for s in g.systems:
        s.on_player_act(g)


# --------------------------------------------------------------------------- #
# 1) lure-combo: a MULTI-STEP plan that leads the foe onto the hazard
# --------------------------------------------------------------------------- #

def _check_lure_combo():
    g = _new_game()
    x0, y = _stage_arena(g)
    rx = g.system("reactions")

    foe = _foe(x0 + 1, y)            # (3, 3)
    foe.brain = HunterBrain()        # greedy chaser, no self-preservation -> walks into acid
    mm = _monster(x0 + 4, y)         # (6, 3) — already on the far side, must reach the bait
    mm.brain = MastermindBrain()
    g.actors = [mm, foe]
    rx.props = {(x0 + 3, y): {"acid"}}   # hazard at (5, 3), between the foe and the bait

    # sanity: the mastermind perceives the foe, and the foe is its nearest hostile
    assert danger_tiles(g) == {(x0 + 3, y)}, danger_tiles(g)
    assert nearest_hostile(g, mm)[0] is foe, "mastermind should perceive the foe"
    assert not is_dangerous(g, mm.x, mm.y), "mastermind must not start on the hazard"

    # it forms a genuine MULTI-STEP plan (route waypoints + a kite manoeuvre)
    mm.brain.replan(g, mm)
    assert mm.brain.goal[0] == "lure", f"expected a lure plan, got {mm.brain.goal}"
    assert len(mm.brain.plan) > 1, f"plan must be multi-step, got {mm.brain.plan}"
    moves = [s for s in mm.brain.plan if MastermindBrain._is_move(s)]
    assert len(moves) >= 1 and ("kite", (x0 + 3, y)) in mm.brain.plan, mm.brain.plan
    plan_snapshot = list(mm.brain.plan)   # captured before driving mutates it

    # driving the turns leads the foe onto the hazard: it takes environmental damage
    foe_hp0 = foe.hp
    landed = False
    for _ in range(5):
        _drive(g, mm, foe)
        if is_dangerous(g, foe.x, foe.y):
            landed = True
        if foe.hp < foe_hp0:
            break
    assert landed, "the foe never stepped onto the hazard tile"
    assert foe.hp < foe_hp0, f"foe took no environmental damage (hp {foe.hp}/{foe_hp0})"

    # determinism: replanning from the same staged state yields the identical plan
    g2 = _new_game()
    x0b, yb = _stage_arena(g2)
    rxb = g2.system("reactions")
    foe2 = _foe(x0b + 1, yb); foe2.brain = HunterBrain()
    mm2 = _monster(x0b + 4, yb); mm2.brain = MastermindBrain()
    g2.actors = [mm2, foe2]
    rxb.props = {(x0b + 3, yb): {"acid"}}
    mm2.brain.replan(g2, mm2)
    assert mm2.brain.plan == plan_snapshot, "replan is not deterministic"


# --------------------------------------------------------------------------- #
# 2) replanning: invalidate the setup mid-plan and the plan must CHANGE
# --------------------------------------------------------------------------- #

def _check_replans_when_hazard_cleared():
    g = _new_game()
    x0, y = _stage_arena(g)
    rx = g.system("reactions")

    foe = _foe(x0 + 1, y)
    foe.brain = HunterBrain()
    mm = _monster(x0 + 4, y)
    mm.brain = MastermindBrain()
    g.actors = [mm, foe]
    rx.props = {(x0 + 3, y): {"acid"}}

    mm.brain.replan(g, mm)
    goal_before = mm.brain.goal
    plan_before = list(mm.brain.plan)
    assert goal_before[0] == "lure" and len(plan_before) > 1, (goal_before, plan_before)

    # INVALIDATE: clear the hazard. The lure assumption is dead; deciding must replan.
    rx.props = {}
    assert not is_dangerous(g, x0 + 3, y), "hazard should be gone"
    mm.brain.decide(g, mm)

    assert mm.brain.plan != plan_before, "plan did not change after invalidation"
    assert mm.brain.goal != goal_before, f"goal did not change: still {mm.brain.goal}"
    assert mm.brain.goal[0] == "engage", f"expected fallback to engage, got {mm.brain.goal}"


def _check_replans_when_foe_flees():
    """A different invalidation lever: the foe leaves perception range entirely."""
    g = _new_game()
    x0, y = _stage_arena(g)
    rx = g.system("reactions")

    foe = _foe(x0 + 1, y)
    foe.brain = HunterBrain()
    mm = _monster(x0 + 4, y)
    mm.brain = MastermindBrain()
    g.actors = [mm, foe]
    rx.props = {(x0 + 3, y): {"acid"}}

    mm.brain.replan(g, mm)
    plan_before = list(mm.brain.plan)
    assert mm.brain.goal[0] == "lure"

    # move the foe far away (out of sight); with no belief seeded, the plan empties out
    foe.x, foe.y = 50, 17
    g.level.tiles[17][50] = "."
    g.turn += 1   # advance so per-turn perception caches recompute with the new position
    assert nearest_hostile(g, mm)[0] is None, "foe should be out of perception"
    mm.brain.decide(g, mm)
    assert mm.brain.plan != plan_before, "plan should change once the foe is gone"
    assert mm.brain.goal is None or mm.brain.goal[0] != "lure", mm.brain.goal


# --------------------------------------------------------------------------- #
# 3) search: head to a remembered spot, then give up when the belief fades
# --------------------------------------------------------------------------- #

def _check_search_and_give_up():
    g = _new_game()
    x0, y = _stage_arena(g)
    rx = g.system("reactions")
    rx.props = {}

    mm = _monster(x0 + 1, y)         # (3, 3)
    mm.brain = MastermindBrain()
    g.actors = [mm]                  # no foe present -> nothing to perceive
    assert nearest_hostile(g, mm)[0] is None

    # seed a belief: the mastermind "remembers" seeing a foe at the far end of the arena
    spot = (x0 + 8, y)               # (10, 3)
    mem(mm).saw("ghost", spot, g.turn)
    assert recalled_spot(g, mm) == spot

    mm.brain.replan(g, mm)
    assert mm.brain.goal == ("search", spot), mm.brain.goal
    assert len(mm.brain.plan) >= 1, mm.brain.plan
    step = mm.brain.decide(g, mm)
    assert step == (1, 0), f"should step toward the remembered spot, got {step}"

    # the belief fades -> the mastermind gives up (no longer searching)
    mem(mm).beliefs.clear()
    assert recalled_spot(g, mm) is None
    mm.brain.decide(g, mm)
    assert mm.brain.goal is None, f"should give up once the belief fades, got {mm.brain.goal}"


# --------------------------------------------------------------------------- #
# 4) graceful degradation: no senses + no memory -> still a sane reaction
# --------------------------------------------------------------------------- #

def _check_degrades_without_systems():
    # only a ReactionSystem: no SenseField (omniscient targeting), no MemorySystem
    g = Game(load_manifest("examples/world.json"), systems=[ReactionSystem()])
    _carve(g.level, 2, 2, 10, 3)
    rx = g.system("reactions")
    rx.props, rx.fire_life = {}, {}
    g.player.x, g.player.y = 19, 14

    x0, y = 2, 3
    foe = _foe(x0 + 1, y)
    mm = _monster(x0 + 4, y)
    mm.brain = MastermindBrain()
    g.actors = [mm, foe]
    rx.props = {(x0 + 3, y): {"acid"}}

    # memory/senses helpers stay None-safe; the brain still produces a real, safe step
    step = mm.brain.decide(g, mm)
    assert step != (0, 0), "degraded mastermind should still act"
    nx, ny = mm.x + step[0], mm.y + step[1]
    assert g.level.walkable(nx, ny) and not is_dangerous(g, nx, ny), \
        f"degraded step {step} must stay off the hazard and on the floor"


# --------------------------------------------------------------------------- #
# 5) strategist (bonus player brain) registers and plans without crashing
# --------------------------------------------------------------------------- #

def _check_strategist_registers():
    from runtime.sense import BRAIN_REGISTRY
    assert BRAIN_REGISTRY.get("mastermind") is MastermindBrain
    assert BRAIN_REGISTRY.get("strategist") is StrategistBrain

    g = _new_game()
    x0, y = _stage_arena(g)
    rx = g.system("reactions")
    # player-as-strategist herds a monster onto a hazard
    mon = _monster(x0 + 1, y)        # monster = the player's hostile
    mon.brain = HunterBrain()
    g.actors = [mon]
    g.player.x, g.player.y = x0 + 4, y
    g.player.hp = g.player.max_hp
    rx.props = {(x0 + 3, y): {"acid"}}

    brain = StrategistBrain()
    step = brain.decide(g, g.player)
    assert isinstance(step, tuple) and len(step) == 2, step


def main():
    _check_lure_combo()
    _check_replans_when_hazard_cleared()
    _check_replans_when_foe_flees()
    _check_search_and_give_up()
    _check_degrades_without_systems()
    _check_strategist_registers()
    print("OK")


if __name__ == "__main__":
    main()
