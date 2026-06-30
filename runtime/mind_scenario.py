"""Mind-layer SHOWCASE for vaultcrawl — per-entity memory + deliberate planning.

Reactive brains decide one step from the current instant. The MIND layer adds creatures
that *remember* (beliefs that persist, fade, and teach) and *plan* (a multi-step setup a
boss executes and monitors). This script stages six set-pieces a dumb auto-player could
never line up, runs the REAL code path (the `MemorySystem` hooks, `brain.decide`,
`game.enemies_act()`, the `ReactionSystem` tick), and prints a ✓/✗ verdict computed from
the resulting LIVE state — never from what a brain *claims* it will do.

Each set-piece builds a fresh
    Game(load_manifest("examples/world.json"),
         systems=[SenseField(), ReactionSystem(), MemorySystem()])
then stages the situation by carving floor (`game.level.tiles`), placing actors, poking
`reactions.props` (acid hazards — a flat 1 dmg/turn with no rng draw, so every outcome is
reproducible) and driving the real `MemorySystem.on_player_act` / `game.enemies_act()`.

Determinism: positions are fixed, hazards are acid (no rng), and the only stochastic source
(the reactions rng) is seeded once per floor by the engine; nothing here draws from it.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m runtime.mind_scenario
"""
from __future__ import annotations

import traceback

from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.senses import SenseField, has_los
from runtime.memory import MemorySystem, mem, recalled_spot, alert_of, fears
from runtime.entities import make_critter, make_enemy
from runtime.sense import (
    Brain, HunterBrain, BRAIN_REGISTRY, danger_tiles, step_toward,
)

# IMPORTANT: importing these two modules is what registers the MIND tiers
# (mastermind / tracker / wary) with the engine's brain registry. Without them the
# registry has no such tiers and the brain-driven set-pieces cannot run — so we import
# defensively and REPORT any module that is missing rather than crashing the showcase.
MISMATCHES: list = []          # (file/symbol, expected, actual) printed at the end
_MODULE_ERR: dict = {}         # module path -> import error repr
for _mod in ("runtime.planner", "runtime.instincts"):
    try:
        __import__(_mod)
    except Exception as _e:     # pragma: no cover - reported, not fatal
        _MODULE_ERR["runtime/" + _mod.split(".")[-1] + ".py"] = repr(_e)

MANIFEST = "examples/world.json"
OK, NO = "✓", "✗"


# ---------------------------------------------------------------- helpers ----
def build() -> Game:
    """A fresh world wired with the three MIND-relevant systems, in canonical order
    (senses perceive, reactions resolve matter, memory infers beliefs from both)."""
    return Game(load_manifest(MANIFEST),
                systems=[SenseField(), ReactionSystem(), MemorySystem()])


def reset(g) -> tuple:
    """Strip the procedurally-seeded spawns + hazards + sense field so each arena is
    fully controlled. Returns (senses, reactions, memory)."""
    sf, react, mem_sys = g.system("senses"), g.system("reactions"), g.system("memory")
    g.actors = []
    react.props, react.fire_life = {}, {}
    sf.sounds, sf.scent = [], {}
    mem_sys._hp = {}
    return sf, react, mem_sys


def carve(g, x0, x1, y0, y1):
    """Carve an open floor rectangle [x0..x1] x [y0..y1] (inclusive)."""
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            g.level.tiles[yy][xx] = "."


def wall(g, x, y):
    g.level.tiles[y][x] = "#"


def monster(x, y, name, hp, tier=1, source=""):
    """A faction monster (allegiance 'monster') with a plain 'warden' glyph -> the
    default 'sighted' sense profile, and a chosen affinity source ('' = neutral 1x)."""
    e = make_enemy({"tier": tier, "archetype": "warden", "name": name,
                    "sourceNoteId": source}, x, y)
    e.hp = e.max_hp = hp
    return e


def park_player_far(g, fx, fy):
    """Move the player to the farthest walkable tile from (fx,fy) so it is never the
    nearest perceived hostile, and make it un-hittable. Deterministic."""
    best, bd = None, -1
    for y in range(g.level.h):
        for x in range(g.level.w):
            if g.level.walkable(x, y):
                d = max(abs(x - fx), abs(y - fy))
                if d > bd:
                    best, bd = (x, y), d
    g.player.x, g.player.y = best
    g.player.hp = g.player.max_hp = 999


def tier_brain(name):
    """Resolve a MIND tier from the registry, or None if its module never registered it."""
    cls = BRAIN_REGISTRY.get(name)
    return cls() if cls is not None else None


def require(name, piece):
    """Fetch a brain tier; if missing, record a mismatch tied to `piece` and return None."""
    b = tier_brain(name)
    if b is None:
        src = "runtime/planner.py" if name == "mastermind" else "runtime/instincts.py"
        err = _MODULE_ERR.get(src, "module imported but tier not registered")
        MISMATCHES.append((f"{src}:{name!r} (set-piece {piece})",
                           f"register_brain({name!r}, ...)", f"not registered — {err}"))
    return b


def _cheb(ax, ay, bx, by):
    return max(abs(ax - bx), abs(ay - by))


def _fmt_goal(goal):
    """Render a planner goal for the transcript. An ('engage', foe_id) goal embeds a
    Python id() that varies per process; mask it so the printed output stays byte-stable
    run-to-run (the raw goal is still used for the change comparison)."""
    if isinstance(goal, tuple) and goal and goal[0] == "engage":
        return "('engage', <foe>)"
    return repr(goal)


def header(n, title):
    print("\n" + "=" * 74)
    print(f"SET-PIECE {n}: {title}")
    print("-" * 74)


def verdict(ok, text):
    print(f"   {OK if ok else NO} {text}")
    return bool(ok)


def advance(g, run_enemies=False):
    """One faithful sub-turn: bump the clock (drives perception caching + memory decay),
    optionally let every NPC act through its brain, then run each system's on_player_act
    in registration order (senses -> reactions -> memory), exactly as Game.try_move does."""
    g.turn += 1
    if run_enemies:
        g.enemies_act()
    for s in g.systems:
        s.on_player_act(g)


# ============================================================= set-piece 1 ====
def sp1_search_and_give_up():
    header(1, "Search & give up  (tracker: belief persists, then fades)")
    print("   A tracker sees the player, the player breaks line-of-sight and leaves. The")
    print("   tracker still heads to the last-known spot (a belief, not the live target);")
    print("   after ~18 turns of MemorySystem decay the belief is gone and it idles.")
    brain = require("tracker", 1)
    if brain is None:
        return verdict(False, "tracker tier unavailable (runtime/instincts.py missing).")

    g = build()
    sf, react, mem_sys = reset(g)
    ROW = 9
    carve(g, 3, 46, ROW - 1, ROW + 1)
    TX = 8
    trk = monster(TX, ROW, "Tracker-Hound", 30, tier=2)
    g.actors = [trk]
    g.player.x, g.player.y = TX + 4, ROW          # in clear LOS, within sight (dist 4)
    g.player.hp = g.player.max_hp = 999

    los0 = has_los(g, trk.x, trk.y, g.player.x, g.player.y)
    advance(g)                                    # real MemorySystem infers a belief
    spot = recalled_spot(g, trk)
    seen_ok = (spot == (TX + 4, ROW))
    alert_seen = alert_of(trk)
    print(f"   LOS to player = {los0}; after seeing it: recalled_spot = {spot}, "
          f"alert = {alert_seen:.2f}")

    # the player slips away, far out of sight
    park_player_far(g, TX, ROW)
    g.turn += 1
    trk._perc = None                              # force a fresh perception this turn
    dx, dy = brain.decide(g, trk)
    nx, ny = trk.x + dx, trk.y + dy
    toward = (dx, dy) != (0, 0) and _cheb(nx, ny, *spot) < _cheb(trk.x, trk.y, *spot) \
        if spot else False
    print(f"   player gone: recalled_spot = {recalled_spot(g, trk)}; decide -> {(dx, dy)} "
          f"(steps toward last-known {spot}: {toward})")

    # let the belief decay past the ~18-turn horizon
    for _ in range(22):
        advance(g)
    faded = recalled_spot(g, trk)
    trk._perc = None
    idle = brain.decide(g, trk)
    gave_up = faded is None and idle == (0, 0)
    print(f"   after {22} decay turns: recalled_spot = {faded}; decide -> {idle} "
          f"(idle/gave up: {gave_up})")

    return verdict(seen_ok and alert_seen > 0 and toward and gave_up,
                   "saw the player -> searched the last-known spot -> gave up (belief faded) and idled.")


# ============================================================= set-piece 2 ====
def sp2_learned_aversion():
    header(2, "Learned aversion  (wary: burned by acid twice -> won't path through it)")
    print("   A 1-wide corridor with a single acid tile is the ONLY route to the player.")
    print("   A naive wary creature, cornered, charges through the acid; one burned by")
    print("   acid twice (via the real MemorySystem) refuses to step onto it.")
    brain_kind = require("wary", 2)
    if brain_kind is None:
        return verdict(False, "wary tier unavailable (runtime/instincts.py missing).")

    ROW = 9
    X = 8                                          # corridor tiles: X .. X+3

    def run(learn_fear):
        g = build()
        sf, react, mem_sys = reset(g)
        # seal a 1-wide hall: floor on ROW from X..X+3, walls everywhere around it
        for x in range(X - 1, X + 5):
            wall(g, x, ROW - 1)
            wall(g, x, ROW + 1)
        wall(g, X - 1, ROW)
        wall(g, X + 4, ROW)
        carve(g, X, X + 3, ROW, ROW)
        react.props[(X + 1, ROW)] = {"acid"}       # the lone gap, blocked by acid
        wary = monster(X, ROW, "Wary-Stalker", 24, tier=3)
        g.actors = [wary]

        if learn_fear:
            # teach the fear the honest way: stand it on the acid and let the real
            # ReactionSystem bite it twice while the MemorySystem infers the aversion.
            park_player_far(g, X, ROW)
            wary.x, wary.y = X + 1, ROW             # on the acid tile
            advance(g)                              # baseline hp recorded by memory
            for _ in range(2):
                advance(g)                          # reactions bite -> memory.hurt(...)
            wary.x, wary.y = X, ROW                 # return to the corridor mouth

        g.player.x, g.player.y = X + 3, ROW         # clear LOS down the hall (dist 3)
        g.player.hp = g.player.max_hp = 999
        g.turn += 1
        wary._perc = None
        dx, dy = brain_kind.decide(g, wary) if not learn_fear else \
            BRAIN_REGISTRY["wary"]().decide(g, wary)
        nxt = (wary.x + dx, wary.y + dy)
        on_acid = "acid" in react.props.get(nxt, set())
        feared = dict(mem(wary).feared)
        return {"step": (dx, dy), "next": nxt, "on_acid": on_acid, "feared": feared}

    naive = run(learn_fear=False)
    burned = run(learn_fear=True)
    acid_tile = (X + 1, ROW)
    print(f"   acid tile at {acid_tile}; player at {(X + 3, ROW)} (only reachable through it)")
    print(f"   naive  wary: feared={naive['feared']}  decide={naive['step']} -> {naive['next']}  "
          f"(steps onto acid: {naive['on_acid']})")
    print(f"   burned wary: feared={burned['feared']}  decide={burned['step']} -> {burned['next']}  "
          f"(steps onto acid: {burned['on_acid']})")
    learned = any(v >= 2 for v in burned["feared"].values())
    ok = naive["on_acid"] and not burned["on_acid"] and learned
    return verdict(ok, "the naive creature charged into the acid; the burned one refused it "
                       "(learned aversion).")


# ============================================================= set-piece 3 ====
def sp3_grudge():
    header(3, "Grudge  (alert_of rises on damage, then decays each turn)")
    print("   Memory tracks arousal: taking damage raises a creature's alert/grudge; with")
    print("   no fresh provocation it cools a little every turn. Pure MemorySystem, no brain.")
    g = build()
    sf, react, mem_sys = reset(g)
    ROW = 9
    carve(g, 3, 46, ROW, ROW)
    beast = monster(10, ROW, "Sullen Warden", 40, tier=2)
    g.actors = [beast]
    park_player_far(g, 10, ROW)                    # never perceives the player (no sighting bump)

    advance(g)                                     # baseline hp; alert stays 0
    a0 = alert_of(beast)
    beast.hp -= 8                                   # it takes a hit (off any hazard -> pure grudge)
    advance(g)                                     # memory infers the damage -> grudge
    a_hit = alert_of(beast)
    curve = [a_hit]
    for _ in range(5):                             # then it cools with no new provocation
        advance(g)
        curve.append(alert_of(beast))
    print(f"   alert before any harm  : {a0:.3f}")
    print(f"   alert right after a hit: {a_hit:.3f}")
    print("   alert over next 5 turns: " + " -> ".join(f"{v:.3f}" for v in curve))
    rose = a_hit > a0 + 1e-9
    decays = all(curve[i + 1] < curve[i] - 1e-12 for i in range(len(curve) - 1))
    return verdict(rose and decays,
                   f"damage raised alert {a0:.3f}->{a_hit:.3f}, then it decayed monotonically.")


# ============================================================= set-piece 4 ====
def sp4_deliberate_combo():
    header(4, "Deliberate combo  (mastermind plans a multi-step lure onto a hazard)")
    print("   A mastermind sees a hazard near its quarry and forms a MULTI-STEP plan: route")
    print("   to a bait tile, then kite so the chaser's pursuit crosses the acid. Over a few")
    print("   turns the foe takes environmental damage / ends on the hazard. The plan is printed.")
    brain = require("mastermind", 4)
    if brain is None:
        return verdict(False, "mastermind tier unavailable (runtime/planner.py missing).")

    g = build()
    sf, react, mem_sys = reset(g)
    ROW = 9
    carve(g, 3, 46, ROW - 2, ROW + 2)              # open arena so kiting has room
    MX = 12
    mind = monster(MX, ROW, "Orrery Mastermind", 60, tier=5)
    mind.brain = brain
    g.actors = [mind]
    for x in (MX + 2, MX + 3, MX + 4):             # a 3-wide acid band beside the quarry
        react.props[(x, ROW)] = {"acid"}
    foe = make_critter("Greedy Chaser", "b", MX + 5, ROW, hp=6, atk=2, source="")
    foe.brain = HunterBrain()                       # hazard-blind greedy beeliner
    g.actors = [mind, foe]
    park_player_far(g, MX + 2, ROW)

    # build the plan deliberately, before anyone moves
    dx, dy = mind.brain.decide(g, mind)
    plan = list(getattr(mind.brain, "plan", []) or [])
    goal = getattr(mind.brain, "goal", None)
    multi = len(plan) > 1
    print(f"   goal = {_fmt_goal(goal)}")
    print(f"   plan ({len(plan)} steps) = {plan}")
    print(f"   first decide -> {(dx, dy)}")

    # drive the engine; isolate ENVIRONMENTAL damage to the foe (reactions tick only)
    start_hp = foe.hp
    env_dmg, on_hazard = 0, False
    kill_cause = {"c": None}
    orig_kill = g.kill

    def kill_wrap(actor, cause="other"):
        if actor is foe:
            kill_cause["c"] = cause
        return orig_kill(actor, cause)
    g.kill = kill_wrap

    for _ in range(12):
        g.turn += 1
        g.enemies_act()
        before = foe.hp if foe in g.actors else 0
        react.on_player_act(g)                      # the matter tick = the only env damage
        if foe in g.actors:
            after = foe.hp
            env_dmg += max(0, before - after)
            if "acid" in react.props_at(foe.x, foe.y):
                on_hazard = True
        else:
            on_hazard = on_hazard or kill_cause["c"] == "environment"
        mem_sys.on_player_act(g)
        if foe not in g.actors:
            break

    g.kill = orig_kill
    print(f"   foe: start {start_hp} HP; environmental damage taken = {env_dmg}; "
          f"ended on hazard / env-killed = {on_hazard} (kill cause = {kill_cause['c']!r})")
    return verdict(multi and env_dmg > 0 and on_hazard,
                   "mastermind built a multi-step plan and led the foe onto the hazard "
                   "(it took environmental damage).")


# ============================================================= set-piece 5 ====
def sp5_replanning():
    header(5, "Replanning  (invalidate the setup mid-plan; the plan changes)")
    print("   A mastermind commits to a lure plan. Then the opening vanishes — the hazard")
    print("   is cleared and the foe bolts far away. A deliberate agent does not execute a")
    print("   dead plan: it REPLANS. We snapshot brain.plan/goal before and after.")
    brain = require("mastermind", 5)
    if brain is None:
        return verdict(False, "mastermind tier unavailable (runtime/planner.py missing).")

    g = build()
    sf, react, mem_sys = reset(g)
    ROW = 9
    carve(g, 3, 46, ROW - 2, ROW + 2)
    MX = 12
    mind = monster(MX, ROW, "Orrery Mastermind", 60, tier=5)
    mind.brain = brain
    for x in (MX + 2, MX + 3, MX + 4):
        react.props[(x, ROW)] = {"acid"}
    foe = make_critter("Greedy Chaser", "b", MX + 5, ROW, hp=6, atk=2, source="")
    foe.brain = HunterBrain()
    g.actors = [mind, foe]
    park_player_far(g, MX + 2, ROW)

    mind.brain.decide(g, mind)
    plan_before = [str(s) for s in (getattr(mind.brain, "plan", []) or [])]
    goal_before = getattr(mind.brain, "goal", None)
    print(f"   BEFORE: goal = {_fmt_goal(goal_before)}, plan = {plan_before}")

    # invalidate the opening: clear every hazard (no lure possible) and move the foe to
    # the OTHER side, still perceived. A deliberate agent must drop the dead lure plan and
    # form a fresh one (approach/engage) toward the foe's new position.
    react.props, react.fire_life = {}, {}
    foe.x, foe.y = MX - 3, ROW
    g.turn += 1
    mind._perc = None
    mind.brain.decide(g, mind)
    plan_after = [str(s) for s in (getattr(mind.brain, "plan", []) or [])]
    goal_after = getattr(mind.brain, "goal", None)
    print(f"   AFTER : goal = {_fmt_goal(goal_after)}, plan = {plan_after}")

    changed = (plan_after != plan_before) or (goal_after != goal_before)
    return verdict(changed,
                   "the stale lure plan was abandoned and replaced (replanned), not continued blindly.")


# ============================================================= set-piece 6 ====
def sp6_memory_is_per_entity():
    header(6, "Memory is per-entity  (two creatures, two different minds)")
    print("   Memory is attached to each actor, not shared. One creature is burned by acid")
    print("   and watches the player; the other does neither. They end with different minds.")
    g = build()
    sf, react, mem_sys = reset(g)
    ROW = 9
    carve(g, 3, 46, ROW - 1, ROW + 1)
    # A: stands on acid (will be burned) and has the player in sight
    react.props[(12, ROW)] = {"acid"}
    a = monster(12, ROW, "Scarred Witness", 40, tier=3, source="")
    # B: off in a sealed alcove — never burned, never sees anyone
    carve(g, 40, 43, ROW, ROW)
    for x in range(39, 45):
        wall(g, x, ROW - 1)
        wall(g, x, ROW + 1)
    wall(g, 39, ROW)
    wall(g, 44, ROW)
    b = monster(41, ROW, "Cloistered Idler", 40, tier=3, source="")
    g.actors = [a, b]
    g.player.x, g.player.y = 15, ROW                # in A's LOS (dist 3), far from B
    g.player.hp = g.player.max_hp = 999

    advance(g)                                      # baseline; A sees the player
    for _ in range(2):
        advance(g)                                  # acid bites A twice -> learned aversion

    a_fear = dict(mem(a).feared)
    b_fear = dict(mem(b).feared)
    a_spot = recalled_spot(g, a)
    b_spot = recalled_spot(g, b)
    print(f"   A 'Scarred Witness' : feared={a_fear}  fears-acid={fears(a, 'acid')}  "
          f"recalled_spot={a_spot}  alert={alert_of(a):.2f}")
    print(f"   B 'Cloistered Idler': feared={b_fear}  fears-acid={fears(b, 'acid')}  "
          f"recalled_spot={b_spot}  alert={alert_of(b):.2f}")
    different = (fears(a, "acid") and not fears(b, "acid")) and (a_spot is not None) \
        and (b_spot is None)
    return verdict(different,
                   "A fears acid and remembers the player; B fears nothing and never saw it "
                   "— distinct, per-entity memories.")


# -------------------------------------------------------------------- main ----
def main():
    print("VAULTCRAWL — MIND-LAYER SHOWCASE")
    print("Per-entity memory (beliefs that persist, fade, and teach) and deliberate planning.")
    print("Each set-piece runs the real MemorySystem / brain / reactions code and judges live state.")
    if _MODULE_ERR:
        print("\n! MIND tier modules failed to import (brain-driven pieces will report this):")
        for path, err in _MODULE_ERR.items():
            print(f"    - {path}: {err}")

    pieces = [sp1_search_and_give_up, sp2_learned_aversion, sp3_grudge,
              sp4_deliberate_combo, sp5_replanning, sp6_memory_is_per_entity]
    results = []
    for fn in pieces:
        try:
            results.append(fn())
        except Exception:
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 74)
    line = "  ".join((OK if r else NO) + str(i + 1) for i, r in enumerate(results))
    print(f"VERDICTS: {line}    ({sum(results)}/{len(results)} passed)")
    if MISMATCHES:
        print("\nREPORTED MISMATCHES (could not stage against the real API):")
        for sym, exp, act in MISMATCHES:
            print(f"   - {sym}: expected {exp}, got {act}")
    if all(results):
        print("OVERALL: PASS — per-entity memory and deliberate planning verified on live state.")
        return 0
    print("OVERALL: FAIL — see the set-pieces marked above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
