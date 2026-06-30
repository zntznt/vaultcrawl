"""Senses showcase — perception by capacity, and detection vs. identification.

Deterministic set-pieces, each judged from live state. Run:
    python -m runtime.sense_scenario

Proves: a creature that loses line-of-sight investigates instead of bee-lining through
walls; a blind creature hunts by sound and identifies by touch; a creature perceives fire
as a hazard and never targets it; supernatural senses reach through walls; mind-sense is
selective; and the SAME situation yields different reactions for different sense profiles.
"""
from __future__ import annotations

# importing these registers the brain tiers and the creature sense-profiles
import runtime.brains   # noqa: F401
import runtime.tactics  # noqa: F401
import runtime.creatures  # noqa: F401

from runtime.entities import make_critter, make_enemy
from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.senses import (SenseField, has_los, investigate_step, perceive,
                            profile_name_for)

ROW = 9


def fresh():
    g = Game(load_manifest("examples/world.json"), systems=[SenseField(), ReactionSystem()])
    g.actors = []
    r = g.system("reactions")
    r.props, r.fire_life = {}, {}
    for yy in (ROW - 1, ROW, ROW + 1):
        for x in range(3, 46):
            g.level.tiles[yy][x] = "."
    return g


def mob(g, glyph, x, y, tier=2, hp=60):
    e = make_enemy({"tier": tier, "archetype": "warden", "name": f"{glyph}-mob",
                    "sourceNoteId": "stoicism"}, x, y)
    e.glyph, e.hp, e.max_hp = glyph, hp, hp
    return e


def wall(g, x, y):
    g.level.tiles[y][x] = "#"


def peek(g, obs):
    g.turn += 1
    obs._perc = None
    return perceive(g, obs)


def _ident_has_player(p, g):
    return any(getattr(t, "is_player", False) for t in p.identified)


# --------------------------------------------------------------------------- #

def sp1_lose_and_investigate():
    g = fresh()
    g.player.x, g.player.y = 20, ROW
    m = mob(g, "r", 16, ROW)            # 'r' -> sighted
    g.actors = [m]
    before = _ident_has_player(peek(g, m), g)
    wall(g, 18, ROW)                    # break line of sight
    p = peek(g, m)
    after = _ident_has_player(p, g)
    lead = p.best_lead(m)
    step = investigate_step(g, m)
    ok = before and not after and lead is not None and step != (0, 0)
    return ("Lose & investigate (sighted)", ok, [
        f"in LOS: identifies player = {before}",
        f"player ducks behind a wall: identifies = {after}, lead = {lead}, investigate step = {step}",
        "-> it heads for the last-seen spot instead of bee-lining through the wall",
    ])


def sp2_blind_by_sound():
    g = fresh()
    g.player.x, g.player.y = 20, ROW
    e = mob(g, "e", 14, ROW)            # 'e' -> echolocator (no sight)
    g.actors = [e]
    seen_far = _ident_has_player(peek(g, e), g)
    g.emit("noise", pos=(20, ROW), volume=8)
    p = peek(g, e)
    has_lead = p.best_lead(e) is not None
    step = investigate_step(g, e)
    # now it has closed to touch range
    e.x, e.y = 19, ROW
    touched = _ident_has_player(peek(g, e), g)
    hp0 = g.player.hp
    g.enemies_act()
    bit = g.player.hp < hp0
    ok = (not seen_far) and has_lead and step != (0, 0) and touched and bit
    return ("Blind by sound (echolocator)", ok, [
        f"player in the open, no eyes: identifies by sight = {seen_far}",
        f"a noise rings out: gains a lead = {has_lead}, investigate step = {step}",
        f"closed to touch range: identifies = {touched}, then struck the player = {bit}",
    ])


def sp3_dont_attack_fire():
    g = fresh()
    g.player.x, g.player.y = 20, ROW
    m = mob(g, "r", 16, ROW, tier=2)   # sighted survivor
    g.actors = [m]
    g.system("reactions").ignite(18, ROW)   # fire on the line between them
    p = peek(g, m)
    fire_is_hazard = (18, ROW) in p.hazards
    fire_not_target = (18, ROW) not in {(t.x, t.y) for t in p.identified}
    targets_player = (p.nearest_hostile(g, m)[0] is g.player)
    stepped_on_fire = False
    for _ in range(8):
        g.enemies_act()
        if (m.x, m.y) == (18, ROW):
            stepped_on_fire = True
        if not g.alive:
            break
    ok = fire_is_hazard and fire_not_target and targets_player and not stepped_on_fire
    return ("Don't attack the fire (sighted)", ok, [
        f"fire (18,{ROW}) is in perception.hazards = {fire_is_hazard}; is a target = {not fire_not_target}",
        f"its target is the player = {targets_player}",
        f"over 8 turns it stepped onto the fire = {stepped_on_fire} (it routed around)",
    ])


def sp4_through_walls():
    g = fresh()
    g.player.x, g.player.y = 20, ROW
    w = mob(g, "h", 16, ROW)           # 'h' -> life_wraith
    s = mob(g, "r", 16, ROW + 1)       # 'r' -> sighted, same distance
    g.actors = [w, s]
    wall(g, 18, ROW)
    wall(g, 18, ROW + 1)
    wraith_sees = _ident_has_player(peek(g, w), g)
    sighted_sees = _ident_has_player(peek(g, s), g)
    # and the wraith is blind to an unliving golem
    g.actors.append(mob(g, "g", 12, ROW))   # 'g' -> golem, is_alive False
    golem = g.actors[-1]
    wraith_p = peek(g, w)
    senses_golem = any(t is golem for t in wraith_p.identified)
    ok = wraith_sees and not sighted_sees and not senses_golem
    return ("Through walls (life-wraith)", ok, [
        f"wall between them: wraith senses the living player = {wraith_sees}; sighted creature = {sighted_sees}",
        f"wraith senses the unliving golem = {senses_golem} (it is blind to non-life)",
    ])


def sp5_selective_mind():
    g = fresh()
    g.player.x, g.player.y = 23, ROW    # dist 7 from the seer: beyond its eyes, within its mind
    s = mob(g, "s", 16, ROW)           # 's' -> mind_seer (SIGHT 5, MIND 10)
    grazer = make_critter("doe", "n", 16, ROW + 3, hp=6, atk=1, source="fauna:grazer")
    g.actors = [s, grazer]
    p = peek(g, s)
    knows_player = any(getattr(t, "is_player", False) for t in p.identified)
    knows_grazer = any(t is grazer for t in p.identified)
    ok = knows_player and not knows_grazer
    return ("Selective mind-sense (mind-seer)", ok, [
        f"feels the thinking player at range = {knows_player}",
        f"feels the mindless grazer = {knows_grazer} (no thought to sense)",
    ])


def sp6_capacity_comparison():
    rows = []
    results = {}
    for glyph, label in (("r", "sighted"), ("e", "echolocator"), ("h", "life_wraith")):
        g = fresh()
        g.player.x, g.player.y = 20, ROW
        o = mob(g, glyph, 16, ROW)
        g.actors = [o]
        wall(g, 18, ROW)                # player hidden behind a wall
        g.emit("noise", pos=(20, ROW), volume=7)
        p = peek(g, o)
        ident = _ident_has_player(p, g)
        lead = p.best_lead(o) is not None
        results[label] = (ident, lead)
        rows.append(f"  {label:12} identifies={ident!s:5} has-lead={lead}")
    # only the wraith pierces the wall; the others merely have a lead to chase
    ok = (results["life_wraith"][0] and not results["sighted"][0]
          and not results["echolocator"][0]
          and results["sighted"][1] and results["echolocator"][1])
    return ("Capacity comparison (same scene, 3 senses)", ok, rows)


SET_PIECES = [sp1_lose_and_investigate, sp2_blind_by_sound, sp3_dont_attack_fire,
              sp4_through_walls, sp5_selective_mind, sp6_capacity_comparison]


def main():
    print("VAULTCRAWL — SENSES SHOWCASE")
    print("Perception, not omniscience: detection (sound/smell) leads to investigation;")
    print("identification (sight/touch/life/mind) decides the reaction. Capacity rules.\n")
    verdicts = []
    for i, fn in enumerate(SET_PIECES, 1):
        title, ok, lines = fn()
        verdicts.append(ok)
        print("=" * 74)
        print(f"SET-PIECE {i}: {title}")
        print("-" * 74)
        for ln in lines:
            print(f"   {ln}")
        print(f"   {'✓' if ok else '✗'} {title}")
    print("=" * 74)
    tags = "  ".join(f"{'✓' if v else '✗'}{i}" for i, v in enumerate(verdicts, 1))
    n = sum(verdicts)
    print(f"VERDICTS: {tags}    ({n}/{len(verdicts)} passed)")
    print("OVERALL: " + ("PASS — perception works by capacity, in two layers."
                         if n == len(verdicts) else "FAIL"))
    return 0 if n == len(verdicts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
