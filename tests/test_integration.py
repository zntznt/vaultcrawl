"""Full-stack integration + determinism audit for vaultcrawl.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_integration

This is the audit that drives the WHOLE live system stack -- the exact eleven systems
runtime.play wires up, in the exact order, with the player's "exploiter" brain and the
tier/glyph-driven monster brains + sense profiles -- across a real auto-descent on both
baked example worlds (with and without `--evolve-from`-style upheaval), and asserts the
cross-cutting invariants that no single-system unit test can see.

It is intentionally NON-fatal on the first failure: every invariant is checked, every
failure is collected with evidence, and the process exits non-zero iff anything broke.
The point is to surface inconsistencies for the lead to fix at the source -- so a FAIL
here is a finding, not a bug in the test.

Invariants checked (mapping to the audit brief):
  1. No crashes descending ~10 floors on world.json AND world_v2.json, plain and under
     evolve-style upheaval.
  2. Per-turn / per-floor state sanity: HP never *displayed* negative; game.kills is
     monotonic and only credited to player melee; no actor (incl. player) on a wall tile;
     no two living actors share a tile; game.turn advances every action.
  3. Bus / ecology: every corpse tile corresponds to a real death; every system.status_line
     returns str|None without raising; every system.render_overlay runs without raising and
     the finished frame shows exactly one '@', on the player's tile.
  4. Determinism: the same world built twice and auto-played the same way yields byte-identical
     transcripts (worlds are seed-deterministic; systems use seeded rng).
  5. Perception opt-in: with a SenseField present, a monster with no line-of-sight and no
     sensory leads does NOT target the player (controlled arena).
"""
from __future__ import annotations

import re
import sys
import traceback

# --- registration side-effects (mirror runtime.play): brains + tactics + sense profiles ---
from runtime import brains, tactics, creatures, planner, instincts, abilities  # noqa: F401
from runtime import senses
from runtime.game import Game, load_manifest
from runtime.sense import make_brain
from runtime.play import auto_play, bfs_step

from runtime.senses import SenseField, perceive, has_los, nearest_perceived_hostile, investigate_step
from runtime.sigils import SigilSystem
from runtime.reactions import ReactionSystem
from runtime.weather import WeatherSystem
from runtime.flora import FloraSystem
from runtime.structures import StructureSystem
from runtime.decay import DecaySystem
from runtime.fauna import FaunaSystem
from runtime.factions import FactionSystem
from runtime.history import HistorySystem
from runtime.knowledge import KnowledgeSystem
from runtime.memory import MemorySystem
from runtime.salvage import SalvageSystem
from runtime.forge import ForgeSystem
from runtime.quests import QuestSystem
from runtime.dialogue import DialogueSystem
from runtime.machines import MachineSystem
from runtime.quality import QualitySystem

from runtime.upheaval import Upheaval
from runtime.entities import make_enemy

try:
    from vaultcrawl.evolve import evolve
except Exception:   # pragma: no cover - defensive: package import path issues
    evolve = None

V1 = "examples/world.json"
V2 = "examples/world_v2.json"
FLOORS = 10
HP_BOOST = 100_000   # for the "deep sweep" that exercises all 10 floors of the stack


# --------------------------------------------------------------------------- #
# Stack construction -- the canonical live stack, mirrored from runtime.play
# --------------------------------------------------------------------------- #

def _systems():
    """The exact ordered system list runtime.play builds for the live game."""
    return [SenseField(), MemorySystem(), SigilSystem(), ReactionSystem(), WeatherSystem(),
            FloraSystem(), StructureSystem(), DecaySystem(), FaunaSystem(),
            SalvageSystem(), ForgeSystem(), QuestSystem(), DialogueSystem(), MachineSystem(),
            FactionSystem(), QualitySystem(), HistorySystem(), KnowledgeSystem()]


def full_game(seed_world, upheaval=None, hp=None) -> Game:
    """Build the FULL live stack exactly like runtime.play.main():
    Game(load_manifest(path), systems=[...all 11...]) + the player 'exploiter' brain.
    Monster brains/sense profiles resolve lazily via the registries imported above."""
    game = Game(load_manifest(seed_world), systems=_systems(), upheaval=upheaval)
    game.player.brain = make_brain(game, game.player, name="exploiter")
    if hp is not None:   # deep-sweep only: keep the descent alive long enough to see 10 floors
        game.player.hp = game.player.max_hp = hp
    return game


def evolve_upheaval(old_path, new_path):
    """Reproduce `--evolve-from old new`: chronicle(old->new) overlaid as live upheaval."""
    if evolve is None:
        return None
    events = evolve(load_manifest(old_path), load_manifest(new_path))
    return Upheaval.from_events(events)


# --------------------------------------------------------------------------- #
# Instrumentation (attached to a Game instance; does NOT mutate any source file
# and is only used on invariant runs, never on the determinism-comparison runs)
# --------------------------------------------------------------------------- #

def instrument(game):
    """Wrap game.attack / game.emit on the instance to observe kill crediting and deaths.

    Instance attributes shadow the bound methods, and the engine calls these through
    `self.attack(...)` / `self.emit(...)`, so the wrappers see every internal call without
    changing behaviour (they call straight through)."""
    state = {"deaths": set(), "bad_kill": [], "kills_seen": 0}

    orig_attack = game.attack
    orig_emit = game.emit

    def attack(att, dfn):
        before = game.kills
        orig_attack(att, dfn)
        if game.kills > before:
            ok = bool(getattr(att, "is_player", False)) and getattr(dfn, "allegiance", "") == "monster"
            if not ok:
                state["bad_kill"].append(
                    f"kills credited to non-player-melee: attacker={getattr(att, 'name', '?')} "
                    f"is_player={getattr(att, 'is_player', False)} victim_allegiance={getattr(dfn, 'allegiance', '?')}")

    def emit(etype, **data):
        if etype == "actor_died":
            pos = data.get("pos")
            if pos is not None:
                state["deaths"].add(tuple(pos))
        orig_emit(etype, **data)

    game.attack = attack
    game.emit = emit
    return state


# --------------------------------------------------------------------------- #
# Invariant checks
# --------------------------------------------------------------------------- #

_HP_RE = re.compile(r"HP (-?\d+)/(\d+)")


def _render_grid(game, fails, label):
    """Rebuild the display grid exactly like Game.render does, running each overlay in
    isolation so a raise can be attributed to a named system. Returns the finished grid."""
    grid = [row[:] for row in game.level.tiles]
    for it in game.items:
        if 0 <= it.y < len(grid) and 0 <= it.x < len(grid[it.y]):
            grid[it.y][it.x] = it.glyph
    for a in game.actors:
        if 0 <= a.y < len(grid) and 0 <= a.x < len(grid[a.y]):
            grid[a.y][a.x] = a.glyph
    grid[game.player.y][game.player.x] = "@"
    for s in game.systems:
        try:
            s.render_overlay(game, grid)
        except Exception as e:
            fails.append(f"[{label}] render_overlay raised in system "
                         f"'{getattr(s, 'name', '?')}': {e!r}")
    return grid


def check_floor(game, fails, label):
    """Per-floor (render-path) checks: HP display, status lines, overlay isolation, '@' count."""
    # status_line: every system returns str|None, never raises
    for s in game.systems:
        nm = getattr(s, "name", "?")
        try:
            sl = s.status_line(game)
        except Exception as e:
            fails.append(f"[{label}] status_line raised in system '{nm}': {e!r}")
            continue
        if sl is not None and not isinstance(sl, str):
            fails.append(f"[{label}] status_line in '{nm}' returned {type(sl).__name__}, not str|None")

    # HP never displayed negative (and the HUD reflects the true clamped hp)
    try:
        text = game.render()
    except Exception as e:
        fails.append(f"[{label}] game.render() raised: {e!r}")
        text = ""
    m = _HP_RE.search(text)
    if m is None:
        fails.append(f"[{label}] could not find 'HP n/m' in rendered HUD")
    else:
        shown = int(m.group(1))
        if shown < 0:
            fails.append(f"[{label}] HUD displayed negative HP: {shown}")
        expected = max(0, game.player.hp)
        if shown != expected:
            fails.append(f"[{label}] HUD HP {shown} != clamped player.hp {expected}")

    # render_overlay isolation + exactly one '@', on the player's tile
    grid = _render_grid(game, fails, label)
    ats = [(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if c == "@"]
    if len(ats) != 1:
        fails.append(f"[{label}] floor {game.floor}: expected exactly one '@' after overlays, "
                     f"found {len(ats)} at {ats[:8]}")
    elif ats[0] != (game.player.x, game.player.y):
        fails.append(f"[{label}] floor {game.floor}: '@' at {ats[0]} but player at "
                     f"{(game.player.x, game.player.y)}")


def check_turn(game, fails, label, turn_before, last_kills):
    """Cheap per-action structural checks. Returns the current kills count."""
    # turn advanced
    if game.turn <= turn_before:
        fails.append(f"[{label}] floor {game.floor}: game.turn did not advance "
                     f"({turn_before} -> {game.turn})")

    # kills monotonic
    if game.kills < last_kills:
        fails.append(f"[{label}] floor {game.floor}: game.kills decreased "
                     f"({last_kills} -> {game.kills})")

    # nobody on a wall tile (player + every living actor)
    on_wall = []
    living = [a for a in game.actors if getattr(a, "hp", 1) > 0]
    for a in living + [game.player]:
        if not game.level.walkable(a.x, a.y):
            on_wall.append((getattr(a, "name", "?"), (a.x, a.y)))
    if on_wall:
        fails.append(f"[{label}] floor {game.floor}: actor(s) on a non-walkable tile: {on_wall[:8]}")

    # no two living actors share a tile (player included while alive)
    occ = [(a.x, a.y) for a in living]
    if game.alive:
        occ.append((game.player.x, game.player.y))
    dupes = {p for p in occ if occ.count(p) > 1}
    if dupes:
        fails.append(f"[{label}] floor {game.floor}: overlapping living actors at {sorted(dupes)[:8]}")

    return game.kills


# --------------------------------------------------------------------------- #
# Driver: mirrors runtime.play.auto_play, weaving invariant checks in
# --------------------------------------------------------------------------- #

def drive_and_check(game, floors, fails, label, max_turns=500):
    """A copy of runtime.play.auto_play's control flow with per-turn / per-floor invariant
    checks interleaved. Returns the number of floors cleared."""
    state = instrument(game)
    last_kills = game.kills
    check_floor(game, fails, label)

    cleared = 0
    while game.alive and not game.won and cleared < floors:
        turns = 0
        while game.alive and not game.won:
            ppos = (game.player.x, game.player.y)
            adj_threat = any(max(abs(a.x - ppos[0]), abs(a.y - ppos[1])) == 1
                             and game._hostile("player", a.allegiance) for a in game.actors)
            has_poi = bool(game.items) or any(s.points_of_interest(game) for s in game.systems)
            if game.on_stairs() and not adj_threat and not has_poi:
                break
            dx, dy = game.player.brain.decide(game, game.player)
            if dx == 0 and dy == 0:
                if game.on_stairs():
                    break
                step = bfs_step(game.level, ppos, game.level.stairs)
                if not step or step == (0, 0):
                    break
                dx, dy = step
            t0 = game.turn
            game.try_move(dx, dy)
            last_kills = check_turn(game, fails, label, t0, last_kills)
            turns += 1
            if turns > max_turns:
                break
        if not game.alive or game.won:
            break
        cleared += 1
        if cleared < floors:
            game.descend()
            check_floor(game, fails, label)

    # final-frame render must still hold (even on death)
    check_floor(game, fails, label + ":final")

    # ecology / bus end-of-run invariants
    if state["bad_kill"]:
        fails.extend(f"[{label}] {m}" for m in state["bad_kill"])
    if game.kills > len(state["deaths"]):
        fails.append(f"[{label}] game.kills ({game.kills}) exceeds total deaths "
                     f"({len(state['deaths'])}) -- a credited kill with no death event")
    decay = game.system("decay")
    if decay is not None:
        for pos in list(getattr(decay, "corpses", {})):
            if tuple(pos) not in state["deaths"]:
                fails.append(f"[{label}] corpse at {pos} with no recorded death there")

    return cleared, state


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def section_descent_invariants(fails):
    """Invariants 1, 2, 3 across all worlds/upheaval modes, plus a deep sweep that
    exercises a full 10-floor descent (HP-boosted so the run actually reaches the depth)."""
    up = evolve_upheaval(V1, V2)
    if up is None:
        fails.append("[setup] vaultcrawl.evolve unavailable -- could not build upheaval run")

    scenarios = [
        ("v1-plain", V1, None, None),
        ("v2-plain", V2, None, None),
        ("v2-upheaval", V2, up, None),
        ("v1-deepsweep", V1, None, HP_BOOST),
        ("v2-deepsweep", V2, None, HP_BOOST),
    ]
    if up is not None:
        scenarios.insert(3, ("v1-upheaval", V1, evolve_upheaval(V2, V1), None))

    results = []
    for label, path, upheaval, hp in scenarios:
        n_before = len(fails)
        try:
            game = full_game(path, upheaval=upheaval, hp=hp)
            cleared, _state = drive_and_check(game, FLOORS, fails, label)
            outcome = "WON" if game.won else ("DIED" if not game.alive else "stopped")
            results.append((label, f"reached floor {game.floor}, cleared {cleared}, "
                                   f"{game.kills} kills, {game.turn} turns, {outcome}",
                            len(fails) == n_before))
        except Exception:
            tb = traceback.format_exc().strip().splitlines()[-3:]
            fails.append(f"[{label}] CRASHED during descent (invariant #1): " + " | ".join(tb))
            results.append((label, "CRASHED", False))
    return results


def section_determinism(fails):
    """Invariant 4: identical builds + identical play => identical transcripts."""
    up = evolve_upheaval(V1, V2)
    cases = [("v1", V1, None), ("v2", V2, None)]
    if up is not None:
        cases.append(("v2-upheaval", V2, "u"))

    results = []
    for label, path, mode in cases:
        upa = evolve_upheaval(V1, V2) if mode == "u" else None
        upb = evolve_upheaval(V1, V2) if mode == "u" else None
        g1 = full_game(path, upheaval=upa)
        g2 = full_game(path, upheaval=upb)
        t1, c1 = auto_play(g1, FLOORS)
        t2, c2 = auto_play(g2, FLOORS)
        if t1 == t2 and c1 == c2:
            results.append((label, f"identical transcripts ({len(t1)} frames, cleared {c1})", True))
        else:
            ev = _first_transcript_diff(t1, t2)
            fails.append(f"[determinism:{label}] non-deterministic transcript: {ev}")
            results.append((label, "DIVERGED", False))
    return results


def _first_transcript_diff(t1, t2):
    if len(t1) != len(t2):
        return f"frame count differs ({len(t1)} vs {len(t2)})"
    for i, (a, b) in enumerate(zip(t1, t2)):
        if a != b:
            la, lb = a.split("\n"), b.split("\n")
            for j in range(max(len(la), len(lb))):
                x = la[j] if j < len(la) else "<none>"
                y = lb[j] if j < len(lb) else "<none>"
                if x != y:
                    return f"frame {i}, line {j}:\n      A={x!r}\n      B={y!r}"
    return "transcripts equal length but compared unequal (whitespace?)"


def section_perception_optin(fails):
    """Invariant 5: with a SenseField present, a monster with no LOS and no leads does not
    target the player. Controlled arena (a carved lane + one wall), SenseField-only stack."""
    label = "perception"
    g = Game(load_manifest(V1), systems=[SenseField()])
    sf = g.system("senses")
    Y = g.level.h // 2
    for x in range(1, g.level.w - 1):           # carve a clean horizontal lane
        g.level.tiles[Y][x] = "."
    OX = 10
    g.player.x, g.player.y = OX + 6, Y          # distance 6: out of TOUCH
    g.player.hp = g.player.max_hp
    g.actors = []
    sf.sounds, sf.scent = [], {}                # NO sensory leads

    # NEGATIVE: a sighted monster walled off from the player perceives nothing.
    g.level.tiles[Y][OX + 3] = "#"              # block the sight-line
    mon = make_enemy({"tier": 1, "archetype": "warden", "name": "Sentry", "sourceNoteId": ""}, OX, Y)
    mon.glyph = "r"                              # -> 'sighted' profile {SIGHT:8,...}
    g.actors = [mon]
    g.turn += 1

    if senses.profile_name_for(mon) != "sighted":
        fails.append(f"[{label}] staging error: monster profile is "
                     f"{senses.profile_name_for(mon)}, expected 'sighted'")
    if has_los(g, mon.x, mon.y, g.player.x, g.player.y):
        fails.append(f"[{label}] staging error: expected NO line-of-sight to the player")

    perc = perceive(g, mon)
    if g.player in perc.identified:
        fails.append(f"[{label}] monster identified the player with no LOS and no leads")
    if perc.leads:
        fails.append(f"[{label}] monster has leads despite empty sound/scent fields: {perc.leads}")
    tgt, _d = nearest_perceived_hostile(g, mon)
    if tgt is not None:
        fails.append(f"[{label}] nearest_perceived_hostile targeted {getattr(tgt, 'name', '?')} "
                     f"with no perception")
    mon.brain = make_brain(g, mon)
    if mon.brain.decide(g, mon) != (0, 0):
        fails.append(f"[{label}] monster brain produced a move toward an unperceived player")
    if investigate_step(g, mon) != (0, 0):
        fails.append(f"[{label}] investigate_step produced a move with no leads")

    # POSITIVE control: give it line-of-sight and it MUST identify + target the player
    g.level.tiles[Y][OX + 3] = "."              # clear the wall -> LOS within SIGHT range
    g.player.x, g.player.y = OX + 5, Y          # distance 5 <= SIGHT 8
    mon2 = make_enemy({"tier": 1, "archetype": "warden", "name": "Sentry2", "sourceNoteId": ""}, OX, Y)
    mon2.glyph = "r"
    g.actors = [mon2]
    g.turn += 1
    if not has_los(g, mon2.x, mon2.y, g.player.x, g.player.y):
        fails.append(f"[{label}] staging error: expected clear LOS in the positive control")
    perc2 = perceive(g, mon2)
    if g.player not in perc2.identified:
        fails.append(f"[{label}] positive control FAILED: monster with LOS did not identify the "
                     f"player (perception may be broken, weakening the negative result)")
    tgt2, _d2 = nearest_perceived_hostile(g, mon2)
    if tgt2 is not g.player:
        fails.append(f"[{label}] positive control FAILED: monster with LOS did not target the player")

    return [("opt-in negative (no LOS, no leads -> no target)", "", True),
            ("opt-in positive control (LOS -> identifies + targets)", "", True)]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def _print_section(title, results):
    print(f"\n=== {title} ===")
    for name, detail, ok in results:
        tag = "PASS" if ok else "FAIL"
        line = f"  [{tag}] {name}"
        if detail:
            line += f"  ({detail})"
        print(line)


def main():
    fails = []
    print("vaultcrawl full-stack integration + determinism audit")
    print(f"worlds: {V1}, {V2}   floors/run: {FLOORS}")

    # NOTE: results lists carry a coarse per-scenario PASS/FAIL; `fails` carries the
    # authoritative, evidence-bearing list of every invariant violation.
    n0 = len(fails)
    r1 = section_descent_invariants(fails)
    _print_section("Invariants 1-3: no-crash descent + state/ecology sanity", r1)

    n1 = len(fails)
    r4 = section_determinism(fails)
    _print_section("Invariant 4: determinism (same world x2 -> identical transcript)", r4)

    n2 = len(fails)
    r5 = section_perception_optin(fails)
    # reflect any failures discovered in section 5 into its result rows
    if len(fails) > n2:
        r5 = [(nm, dt, False) for (nm, dt, _ok) in r5]
    _print_section("Invariant 5: perception opt-in (senses gate targeting)", r5)

    print("\n" + "=" * 70)
    if not fails:
        print("RESULT: PASS -- all invariants held across every world / mode.")
        print("=" * 70)
        return 0

    print(f"RESULT: FAIL -- {len(fails)} invariant violation(s) found. Evidence:")
    for i, f in enumerate(fails, 1):
        print(f"  {i:2d}. {f}")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
