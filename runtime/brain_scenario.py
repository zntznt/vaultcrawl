"""Brain-spectrum SHOWCASE for vaultcrawl — the capability ladder, proven on live state.

Entities act through a `Brain.decide(game, actor) -> (dx, dy)`. The ladder runs from the
legacy `HunterBrain` (a hazard-blind beeliner) up through self-preserving and
terrain-exploiting tiers. This script stages five set-pieces a dumb auto-player could
never line up, runs the REAL engine code path (`game.enemies_act()`, `brain.decide`,
`game.try_move`, the `ReactionSystem` tick), and prints a ✓/✗ verdict computed from the
resulting live state — never from what a brain *claims* it will do.

Each set-piece builds a fresh `Game(load_manifest("examples/world.json"),
systems=[ReactionSystem()])`, then stages the situation by poking `reactions.props`
(acid hazards — deterministic, no rng) and placing actors. Acid is used throughout
because it bites for a flat 1 dmg/turn with no rng draw, so every outcome is reproducible.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m runtime.brain_scenario
"""
from __future__ import annotations

import traceback

from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.entities import make_enemy, make_boss, make_critter, make_player
from runtime.sense import Brain, HunterBrain, make_brain, brain_for, BRAIN_REGISTRY

# IMPORTANT: importing these modules is what registers their tiers with the engine's
# brain registry / `brain_for` policy. Without them the ladder falls back to HunterBrain.
import runtime.brains   # noqa: F401  registers survivor / opportunist / forager / scavenger
import runtime.tactics  # noqa: F401  registers tactician / exploiter
import runtime.planner   # noqa: F401  registers mastermind (+ strategist)
import runtime.instincts  # noqa: F401  registers tracker / wary

MANIFEST = "examples/world.json"
OK, NO = "✓", "✗"
MISMATCHES: list = []   # (file/symbol, expected, actual) reported at the end


# ---------------------------------------------------------------- helpers ----
def build() -> Game:
    """A fresh world wired with only the reactive-matter system (acid hazards)."""
    return Game(load_manifest(MANIFEST), systems=[ReactionSystem()])


def reset(g) -> "ReactionSystem":
    """Strip the procedurally-seeded spawns + hazards so each arena is fully controlled."""
    react = g.system("reactions")
    g.actors = []
    react.props = {}
    react.fire_life = {}
    return react


def arena_room(g, min_w=6, min_h=3):
    """A clean, open interior room (not the entrance/stairs room) for a 2-D arena.

    Deterministic: widest-then-tallest, tie-broken by position."""
    rooms = g.level.rooms
    cands = [r for i, r in enumerate(rooms)
             if r.w >= min_w and r.h >= min_h and i not in (0, len(rooms) - 1)]
    cands.sort(key=lambda r: (-r.w, -r.h, r.y, r.x))
    return cands[0] if cands else max(rooms, key=lambda r: (r.w, r.h))


def h_lane(level, n):
    """Top-left of the first run of `n` contiguous horizontal floor tiles (house style)."""
    for y in range(level.h):
        for x in range(level.w - n):
            if all(level.tiles[y][x + i] == "." for i in range(n)):
                return x, y
    raise RuntimeError("no horizontal floor run found")


def park_player_far(g, fx, fy):
    """Move the player to the farthest walkable tile from (fx,fy) so it never becomes
    a nearer hostile than the staged target. Deterministic."""
    best, bd = None, -1
    for y in range(g.level.h):
        for x in range(g.level.w):
            if g.level.walkable(x, y):
                d = max(abs(x - fx), abs(y - fy))
                if d > bd:
                    best, bd = (x, y), d
    g.player.x, g.player.y = best
    g.player.hp = g.player.max_hp = 999


def grunt(x, y, name, hp, tier=1, source=""):
    """A faction monster with a neutral (sourceless) affinity, so any hazard bites it
    for the plain 1x — no manifest-dependent immunity/double surprises."""
    e = make_enemy({"tier": tier, "archetype": "beast", "name": name, "sourceNoteId": source}, x, y)
    e.hp = e.max_hp = hp
    return e


def tier_brain(name):
    cls = BRAIN_REGISTRY.get(name)
    if cls is None:
        raise LookupError(f"brain tier {name!r} not registered (is runtime.brains/tactics imported?)")
    return cls()


def header(n, title):
    print("\n" + "=" * 74)
    print(f"SET-PIECE {n}: {title}")
    print("-" * 74)


def show_logs(g, start, indent="   | "):
    for m in g.messages[start:]:
        print(indent + str(m))


def verdict(ok, text):
    print(f"   {OK if ok else NO} {text}")
    return bool(ok)


def step(g, react, stop=None):
    """One real engine sub-turn: every NPC acts through its brain, then the reactive
    matter ticks (the same order `Game.try_move` uses). Returns True to stop early."""
    g.enemies_act()
    react.on_player_act(g)
    return bool(stop and stop())


# ----------------------------------------------------------- set-piece 1 ----
def sp1_dumb_dies_survivor_lives():
    header(1, "Dumb dies, survivor lives  (hunter vs survivor)")
    print("   A lane of acid sits between the monster and its quarry. The hazard-blind")
    print("   HunterBrain beelines straight through it; the SurvivorBrain routes around.")
    SUBJ_HP, TURNS = 6, 8

    def run(brain_name):
        g = build()
        react = reset(g)
        r = arena_room(g)
        Y = r.y + r.h // 2
        x0, qx = r.x, r.x + r.w - 1
        subj = grunt(x0, Y, f"{brain_name.title()} grunt", SUBJ_HP)
        subj.brain = tier_brain(brain_name)
        for x in range(x0 + 1, qx):                 # acid fills the straight-line path
            react.props[(x, Y)] = {"acid"}
        quarry = make_critter("Quarry", "q", qx, Y, 999, 0)
        quarry.brain = Brain()                       # inert dummy: never moves or strikes
        g.actors = [subj, quarry]
        park_player_far(g, x0, Y)                    # keep the player out of the picture
        lane = sorted((x, Y) for x in range(x0 + 1, qx))
        for _ in range(TURNS):
            if step(g, react, lambda: subj not in g.actors):
                break
        alive = subj in g.actors
        return {"alive": alive, "hp": (subj.hp if alive else 0), "lane": lane}

    hun = run("hunter")
    sur = run("survivor")
    print(f"   Acid lane: {hun['lane']}   (subjects start with {SUBJ_HP} HP, {TURNS} turns)")
    print(f"   HunterBrain  : {'ALIVE' if hun['alive'] else 'DEAD '}  HP {hun['hp']}/{SUBJ_HP}"
          f"   (lost {SUBJ_HP - hun['hp']})")
    print(f"   SurvivorBrain: {'ALIVE' if sur['alive'] else 'DEAD '}  HP {sur['hp']}/{SUBJ_HP}"
          f"   (lost {SUBJ_HP - sur['hp']})")
    ok = (SUBJ_HP - hun["hp"]) > (SUBJ_HP - sur["hp"]) and sur["alive"] and not hun["alive"]
    return verdict(ok, "hunter walked into the acid and died; survivor routed around, unscathed & alive.")


# ----------------------------------------------------------- set-piece 2 ----
def sp2_opportunist_lets_terrain_finish():
    header(2, "Opportunist lets terrain finish the job")
    print("   Pinned between two adjacent hostiles — one safe, one already standing in")
    print("   acid — the opportunist strikes the DOOMED one and ignores the safe foe.")
    g = build()
    react = reset(g)
    r = arena_room(g)
    Y = r.y + r.h // 2
    ox = r.x + 2
    opp = grunt(ox, Y, "Opportunist", 13, tier=3)
    opp.brain = tier_brain("opportunist")
    g.player.x, g.player.y = ox - 1, Y               # SAFE hostile (the player)
    g.player.hp = g.player.max_hp = 999
    victim = make_critter("Acid-bather", "v", ox + 1, Y, 5, 0)
    victim.brain = Brain()
    react.props[(ox + 1, Y)] = {"acid"}              # the DOOMED hostile stands here
    g.actors = [opp, victim]

    print(f"   Opportunist @ {(ox, Y)};  safe player @ {(ox - 1, Y)};  acid-bather @ {(ox + 1, Y)} on acid.")
    dx, dy = opp.brain.decide(g, opp)                # the pure choice, before anyone moves
    toward_doomed = (dx, dy) == (1, 0)
    p_before = g.player.hp
    s = len(g.messages)
    step(g, react)                                   # opportunist strikes, then acid ticks
    show_logs(g, s)
    victim_gone = victim not in g.actors
    player_untouched = g.player.hp == p_before
    print(f"   decide() -> {(dx, dy)} (toward the acid-bather: {toward_doomed})")
    print(f"   acid-bather dead: {victim_gone}   safe player untouched: {player_untouched}")
    return verdict(toward_doomed and victim_gone and player_untouched,
                   "opportunist hit the acid-stander (terrain finished it) and never touched the safe foe.")


# ----------------------------------------------------------- set-piece 3 ----
def sp3_tactician_no_touch_kill():
    header(3, "Tactician's no-touch kill  (kite a greedy chaser onto acid)")
    print("   A TacticianBrain monster baits a hazard-blind HunterBrain chaser: every")
    print("   turn it side-steps so the chaser's greedy pursuit lands it on acid. The")
    print("   terrain does ALL the killing — the tactician never lands a melee blow.")
    g = build()
    react = reset(g)
    X, Y = h_lane(g.level, 8)
    tact = grunt(X + 1, Y, "Tactician", 30, tier=5)
    tact.brain = tier_brain("tactician")
    for x in (X + 2, X + 3, X + 4):                  # 3-wide acid band
        react.props[(x, Y)] = {"acid"}
    chaser = make_critter("Greedy chaser", "c", X + 5, Y, 2, 0)
    chaser.brain = HunterBrain()                     # the dumb beeliner being played
    g.actors = [tact, chaser]
    park_player_far(g, X + 3, Y)

    melee = {"n": 0}
    death = {"cause": None}
    orig_attack, orig_kill = g.attack, g.kill

    def attack_wrap(att, dfn):
        if att is tact:
            melee["n"] += 1
        return orig_attack(att, dfn)

    def kill_wrap(actor, cause="other"):
        if actor is chaser:
            death["cause"] = cause
        return orig_kill(actor, cause)

    g.attack, g.kill = attack_wrap, kill_wrap

    print(f"   Tactician @ {(X + 1, Y)};  acid {[(X + 2, Y), (X + 3, Y), (X + 4, Y)]};  chaser @ {(X + 5, Y)} (2 HP).")
    s = len(g.messages)
    turns = 0
    for turns in range(1, 9):
        if step(g, react, lambda: chaser not in g.actors):
            break
    show_logs(g, s)
    dead = chaser not in g.actors
    print(f"   After {turns} turns:  chaser dead = {dead}  (cause = {death['cause']!r})   "
          f"tactician melee blows = {melee['n']}")
    return verdict(dead and death["cause"] == "environment" and melee["n"] == 0,
                   "chaser dissolved on acid (cause=environment); tactician landed 0 melee blows.")


# ----------------------------------------------------------- set-piece 4 ----
def sp4_exploiter_clears_room():
    header(4, "Exploiter player clears a pocket via terrain  (exploiter vs hunter)")
    print("   Same seed, same layout, same monsters — only the PLAYER's brain differs.")
    print("   The ExploiterBrain leads monsters onto acid and finishes the dissolving;")
    print("   the dumb HunterBrain charges across the acid itself, trading raw blows.")
    CAP = 25

    def run(player_brain, label):
        g = build()
        react = reset(g)
        r = arena_room(g)
        Y = r.y + r.h // 2
        px = r.x + 2
        g.player.x, g.player.y = px, Y
        g.player.hp = g.player.max_hp = 32
        g.player.brain = player_brain
        react.props[(px - 1, Y)] = {"acid"}
        react.props[(px + 1, Y)] = {"acid"}
        mons = [grunt(px + 2, Y, "Drudge-A", 2), grunt(px - 2, Y, "Drudge-B", 2),
                grunt(px + 3, Y, "Drudge-C", 2)]
        for m in mons:
            m.brain = HunterBrain()
        g.actors = list(mons)

        causes: dict = {}
        orig_kill = g.kill

        def kill_wrap(actor, cause="other"):
            causes[cause] = causes.get(cause, 0) + 1
            return orig_kill(actor, cause)

        g.kill = kill_wrap

        start = g.player.hp
        turns, prev = 0, None
        while g.alive and any(a in g.actors for a in mons) and turns < CAP:
            dx, dy = g.player.brain.decide(g, g.player)
            g.try_move(dx, dy)
            turns += 1
            sig = (g.player.x, g.player.y, g.player.hp,
                   tuple(sorted((a.x, a.y, a.hp) for a in g.actors)))
            if sig == prev:                          # fully static turn -> stalled
                break
            prev = sig
        return {"label": label, "turns": turns, "alive": g.alive,
                "hp": g.player.hp, "dmg": start - g.player.hp,
                "env": causes.get("environment", 0), "melee": causes.get("melee", 0),
                "left": sum(1 for a in mons if a in g.actors)}

    exp = run(tier_brain("exploiter"), "exploiter")
    hun = run(HunterBrain(), "hunter")
    hdr = f"   {'brain':10} {'turns':>5} {'alive':>5} {'HP':>4} {'dmg taken':>9} {'env-kills':>9} {'melee-kills':>11} {'left':>4}"
    print(hdr)
    for d in (exp, hun):
        print(f"   {d['label']:10} {d['turns']:>5} {str(d['alive']):>5} {d['hp']:>4} "
              f"{d['dmg']:>9} {d['env']:>9} {d['melee']:>11} {d['left']:>4}")
    ok = (exp["alive"] and exp["dmg"] < hun["dmg"] and exp["hp"] >= hun["hp"]
          and exp["env"] >= hun["env"])
    return verdict(ok, "exploiter took less damage, ended healthier, and scored the environmental kill(s).")


# ----------------------------------------------------------- set-piece 5 ----
def sp5_right_brain_per_entity():
    header(5, "Right brain per entity  (the brain_for / make_brain policy)")
    print("   The engine hands each entity the capability tier it deserves. Build one of")
    print("   each and check both the policy (brain_for) and the resolved brain agree.")
    g = build()
    hunter = grunt(4, 1, "Hunter", 10, tier=2)
    hunter.is_hunter = True
    cases = [
        ("tier-1 monster", grunt(1, 1, "Grunt", 7, tier=1), "hunter"),
        ("tier-3 monster", grunt(2, 1, "Veteran", 13, tier=3), "wary"),
        ("tier-5 monster", grunt(3, 1, "Adept", 19, tier=5), "mastermind"),
        ("faction hunter", hunter, "tracker"),
        ("boss", make_boss({"tier": 3, "name": "Warden", "sourceNoteId": ""}, 6, 1), "mastermind"),
        ("wild grazer", make_critter("Moss-grazer", "b", 7, 1, 6, 0, source="grazer:moss"), "forager"),
        ("player", make_player(8, 1), "exploiter"),
    ]
    print(f"   {'entity':16} {'expected':12} {'brain_for':12} {'make_brain':12} ok")
    all_ok = True
    for label, actor, expected in cases:
        policy = brain_for(actor)
        resolved = make_brain(g, actor).name
        row_ok = (policy == expected and resolved == expected)
        all_ok = all_ok and row_ok
        if not row_ok:
            MISMATCHES.append((f"sense.brain_for/make_brain [{label}]", expected,
                               f"brain_for={policy}, make_brain={resolved}"))
        print(f"   {label:16} {expected:12} {policy:12} {resolved:12} {OK if row_ok else NO}")
    return verdict(all_ok, "every entity resolved to its ladder tier "
                           "(hunter/wary/mastermind/tracker/mastermind/forager/exploiter).")


# -------------------------------------------------------------------- main ----
def main():
    print("VAULTCRAWL — AGENT CAPABILITY-LADDER SHOWCASE")
    print("Dumb pathfinders vs interaction-aware exploiters. Each set-piece runs the real")
    print("engine (enemies_act / brain.decide / try_move + reactions) and judges live state.")
    pieces = [sp1_dumb_dies_survivor_lives, sp2_opportunist_lets_terrain_finish,
              sp3_tactician_no_touch_kill, sp4_exploiter_clears_room,
              sp5_right_brain_per_entity]
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
        print("\nREPORTED MISMATCHES (brain behavior did not match the ladder spec):")
        for sym, exp, act in MISMATCHES:
            print(f"   - {sym}: expected {exp!r}, got {act}")
    if all(results):
        print("OVERALL: PASS — the full capability ladder is demonstrated on live state.")
        return 0
    print("OVERALL: FAIL — see the set-pieces marked above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
