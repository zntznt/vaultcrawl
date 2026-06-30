"""Behaviour tests for the memory-driven reactive brains (tracker + wary).

Everything runs against a *real* `Game` built from the example world with the live
`SenseField` + `ReactionSystem` + `MemorySystem` registered. Scenes are staged by carving
a small walled area into `game.level.tiles`, placing actors at fixed coordinates, and
writing `reactions.props` directly (the same lever the reaction/tactics tests use). No
rng, no clock beyond the turn counter we set explicitly -- so every assertion is
deterministic across runs.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_instincts
"""
from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.senses import SenseField
from runtime.memory import MemorySystem, mem, recalled_spot, alert_of, fears
from runtime.entities import Actor
from runtime.sense import nearest_hostile, step_toward
from runtime.instincts import TrackerBrain, WaryBrain


# --------------------------------------------------------------------------- #
# staging helpers
# --------------------------------------------------------------------------- #

def _new_game():
    return Game(load_manifest("examples/world.json"),
                systems=[SenseField(), ReactionSystem(), MemorySystem()])


def _carve_corridor(game, x0, y, length):
    """An isolated 1-wide horizontal corridor of `length` floor cells, walled all round."""
    lvl = game.level
    for i in range(length):
        lvl.tiles[y][x0 + i] = "."
        lvl.tiles[y - 1][x0 + i] = "#"
        lvl.tiles[y + 1][x0 + i] = "#"
    lvl.tiles[y][x0 - 1] = "#"
    lvl.tiles[y][x0 + length] = "#"


def _carve_block(game, x0, y0, w, h):
    """A w x h floor block walled all round (multiple internal routes possible)."""
    lvl = game.level
    for yy in range(y0 - 1, y0 + h + 1):
        for xx in range(x0 - 1, x0 + w + 1):
            lvl.tiles[yy][xx] = "#"
    for yy in range(y0, y0 + h):
        for xx in range(x0, x0 + w):
            lvl.tiles[yy][xx] = "."


def _far_from(level, x, y):
    """A tile well outside any sense range of (x, y) (used to break perception)."""
    fx = 1 if x > level.w // 2 else level.w - 2
    fy = 1 if y > level.h // 2 else level.h - 2
    return fx, fy


def _monster(x, y, glyph="g", tier=3):
    # glyph "g" resolves to the default "sighted" sense profile (sight 8) with no
    # creatures.py registered, so perception is plain line-of-sight.
    return Actor(x=x, y=y, glyph=glyph, name="stalker", hp=24, max_hp=24, atk=4,
                 tier=tier, allegiance="monster")


def _clear_reactions(game):
    rx = game.system("reactions")
    rx.props, rx.fire_life = {}, {}
    return rx


# --------------------------------------------------------------------------- #
# tracker: engage -> hunt last-known -> give up
# --------------------------------------------------------------------------- #

def _check_tracker_engages_perceived():
    """A perceived, adjacent foe is bumped (no memory needed)."""
    g = _new_game()
    _clear_reactions(g)
    x0, y = 3, g.level.h // 2
    _carve_corridor(g, x0, y, 3)
    trk = _monster(x0, y)
    g.actors, g.items = [trk], []
    g.player.x, g.player.y = x0 + 1, y          # adjacent, in line of sight

    t, d = nearest_hostile(g, trk)
    assert t is g.player and d == 1, f"foe should be perceived adjacent, got {t},{d}"
    assert TrackerBrain().decide(g, trk) == (1, 0), "should bump the adjacent foe"


def _check_tracker_hunts_then_gives_up():
    """Seed a sighting via the MemorySystem, break line-of-sight, then verify the tracker
    heads for the last-known spot -- and idles once the belief has decayed away."""
    g = _new_game()
    _clear_reactions(g)
    x0, y = 3, g.level.h // 2
    _carve_corridor(g, x0, y, 6)
    trk = _monster(x0, y)
    g.actors, g.items = [trk], []

    # 1) seed a belief: place the player in view and run the memory hook (turn 0)
    g.turn = 0
    spot = (x0 + 5, y)
    g.player.x, g.player.y = spot
    g.system("memory").on_player_act(g)
    assert recalled_spot(g, trk) == spot, f"belief not seeded at {spot}: {recalled_spot(g, trk)}"

    # 2) break line-of-sight: the player leaves; the tracker should still hunt the spot
    g.turn = 1
    g.player.x, g.player.y = _far_from(g.level, *spot)
    assert nearest_hostile(g, trk)[0] is None, "foe must be out of perception now"
    assert recalled_spot(g, trk) == spot, "belief should persist after losing sight"
    step = TrackerBrain().decide(g, trk)
    assert step == step_toward(g, trk, spot[0], spot[1], safe=True), "should path to the spot"
    assert step == (1, 0), f"should step toward the last-known spot, got {step}"

    # 3) let the belief decay (~horizon turns) -> it gives up and idles
    g.turn = 20
    mem(trk).decay(g.turn)
    assert recalled_spot(g, trk) is None, "belief should have faded"
    assert TrackerBrain().decide(g, trk) == (0, 0), "faded belief -> give up (0,0)"


def _check_tracker_searches_without_looping():
    """Standing on the last-known spot with nothing in view, the tracker probes a fresh
    adjacent tile each turn (recorded in mem.searched) instead of repeating itself."""
    g = _new_game()
    _clear_reactions(g)
    cx, cy = 4, g.level.h // 2
    _carve_block(g, cx - 1, cy - 1, 3, 3)        # 3x3 open block centred on (cx, cy)
    trk = _monster(cx, cy)
    g.actors, g.items = [trk], []
    g.turn = 0
    g.player.x, g.player.y = _far_from(g.level, cx, cy)   # unseen

    # belief points at the tracker's own tile -> it is "on the spot" and must search
    mem(trk).saw(id(g.player), (cx, cy), g.turn)
    assert recalled_spot(g, trk) == (cx, cy)
    assert nearest_hostile(g, trk)[0] is None, "no foe should be perceived"

    s1 = TrackerBrain().decide(g, trk)
    s2 = TrackerBrain().decide(g, trk)
    assert s1 != (0, 0) and s2 != (0, 0), f"should probe neighbours, got {s1},{s2}"
    assert s1 != s2, f"must not re-probe the same tile: {s1} then {s2}"
    assert (cx + s1[0], cy + s1[1]) in mem(trk).searched, "probed tile must be remembered"


# --------------------------------------------------------------------------- #
# wary: learned aversion to a feared element
# --------------------------------------------------------------------------- #

def _check_wary_avoids_feared_acid():
    """A foe sits across an acid tile in a 1-wide corridor (acid is the only route). A
    FRESH wary brain charges through; once it has been corroded twice it `fears`
    'corrosive' and refuses -- its step no longer targets the acid tile."""
    g = _new_game()
    rx = _clear_reactions(g)
    x0, y = 3, g.level.h // 2
    _carve_corridor(g, x0, y, 3)
    acid = (x0 + 1, y)
    mon = _monster(x0, y)
    g.actors, g.items = [mon], []
    g.player.x, g.player.y = x0 + 2, y           # the foe, two tiles away
    rx.props = {acid: {"acid"}}                  # the only path runs over acid

    t, d = nearest_hostile(g, mon)
    assert t is g.player and d == 2, f"foe should be perceived at d=2, got {t},{d}"

    # FRESH: no aversion yet -> it would head straight onto the acid tile
    fresh = WaryBrain().decide(g, mon)
    assert fresh == (1, 0), f"fresh wary should step toward the foe, got {fresh}"
    assert (mon.x + fresh[0], mon.y + fresh[1]) == acid, "fresh step should target the acid"

    # learn the aversion: corroded twice (region-element word, as the spec/MemorySystem use)
    mem(mon).hurt("corrosive")
    mem(mon).hurt("corrosive")
    assert fears(mon, "corrosive"), "two corrosions should breed fear of corrosive"

    guarded = WaryBrain().decide(g, mon)
    target = (mon.x + guarded[0], mon.y + guarded[1])
    assert target != acid, f"wary must NOT step onto the feared acid tile, got {target}"
    assert guarded == (0, 0), f"cornered by the feared tile -> wait, got {guarded}"
    assert WaryBrain().decide(g, mon) == guarded, "decision must be deterministic"


def _check_wary_high_alert_braves_nonfeared_hazard():
    """With a safe detour available, a calm wary creature routes around an acid tile; an
    aroused one (high alert, but NOT fearing acid) commits and charges straight through."""
    g = _new_game()
    rx = _clear_reactions(g)
    x0, y0 = 3, g.level.h // 2
    _carve_block(g, x0, y0, 3, 2)                # rows y0 (acid path) and y0+1 (safe detour)
    acid = (x0 + 1, y0)
    mon = _monster(x0, y0)
    g.actors, g.items = [mon], []
    g.player.x, g.player.y = x0 + 2, y0
    rx.props = {acid: {"acid"}}

    assert nearest_hostile(g, mon)[0] is g.player, "foe must be perceived"
    assert not fears(mon, "corrosive"), "this creature has NOT learned to fear acid"

    # calm: a safe detour exists (down a row), so it does not enter the acid
    mem(mon).alert = 0.0
    calm = WaryBrain().decide(g, mon)
    assert calm == (0, 1), f"calm wary should route around via the safe row, got {calm}"
    assert (mon.x + calm[0], mon.y + calm[1]) != acid

    # aroused: braves the non-feared hazard to close directly on the foe
    mem(mon).alert = 0.9
    hot = WaryBrain().decide(g, mon)
    assert hot == (1, 0), f"aroused wary should charge through the non-feared acid, got {hot}"
    assert (mon.x + hot[0], mon.y + hot[1]) == acid


def _check_wary_flees_when_low():
    """Wounded, a wary creature breaks off and opens distance from the foe."""
    g = _new_game()
    _clear_reactions(g)
    x0, y = 3, g.level.h // 2
    _carve_corridor(g, x0, y, 3)
    mon = _monster(x0 + 1, y)
    mon.hp = 1                                   # << 35% of max -> flee
    g.actors, g.items = [mon], []
    g.player.x, g.player.y = x0, y               # foe adjacent on the left

    got = WaryBrain().decide(g, mon)
    assert got == (1, 0), f"low-hp wary should retreat away from the foe, got {got}"


# --------------------------------------------------------------------------- #
# degradation: no MemorySystem -> purely reactive (recall None, alert 0, no fear)
# --------------------------------------------------------------------------- #

def _check_degrades_without_memory():
    g = Game(load_manifest("examples/world.json"),
             systems=[SenseField(), ReactionSystem()])     # no MemorySystem
    _clear_reactions(g)
    x0, y = 3, g.level.h // 2
    _carve_corridor(g, x0, y, 5)
    trk = _monster(x0, y)
    g.actors, g.items = [trk], []
    g.player.x, g.player.y = _far_from(g.level, x0, y)
    # no belief can exist without the MemorySystem -> tracker simply idles
    assert recalled_spot(g, trk) is None and alert_of(trk) == 0.0
    assert TrackerBrain().decide(g, trk) == (0, 0), "no memory -> reactive idle"


def main():
    _check_tracker_engages_perceived()
    _check_tracker_hunts_then_gives_up()
    _check_tracker_searches_without_looping()
    _check_wary_avoids_feared_acid()
    _check_wary_high_alert_braves_nonfeared_hazard()
    _check_wary_flees_when_low()
    _check_degrades_without_memory()
    print("OK")


if __name__ == "__main__":
    main()
