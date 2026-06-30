"""Behaviour tests for the two top-tier brains (tactician + exploiter).

Everything runs against a *real* Game built from the example world with a real
ReactionSystem; hazards are staged by writing `reactions.props` directly (the same
lever the reaction tests use). No rng, no clock — fixed positions only — so every
assertion is deterministic across runs.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_tactics
"""
from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.systems import System
from runtime.entities import Actor, Item
from runtime.sense import (
    danger_tiles, is_dangerous, greedy_dir, lure_step, points_of_interest,
    step_toward, nearest_hostile,
)
from runtime.tactics import TacticianBrain, ExploiterBrain


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

class PoiStub(System):
    """A tiny system that advertises points-of-interest via the base `ground` hook."""
    name = "poi"

    def __init__(self):
        self.ground = {}


def _new_game(systems):
    return Game(load_manifest("examples/world.json"), systems=systems)


def _floor(level, x, y):
    return 0 <= y < level.h and 0 <= x < level.w and level.tiles[y][x] == "."


def _find_run(game, length, exclude):
    """Find (x0, y) such that (x0..x0+length-1, y) are all floor and none excluded."""
    lvl = game.level
    for y in range(lvl.h):
        for x in range(lvl.w - length + 1):
            cells = [(x + i, y) for i in range(length)]
            if all(_floor(lvl, cx, cy) for cx, cy in cells) and \
                    not any(c in exclude for c in cells):
                return x, y
    raise AssertionError(f"no open horizontal run of length {length} found")


def _monster(x, y):
    return Actor(x=x, y=y, glyph="g", name="schemer", hp=24, max_hp=24, atk=4,
                 tier=4, allegiance="monster")


# --------------------------------------------------------------------------- #
# tactician: kites the player onto a hazard
# --------------------------------------------------------------------------- #

def _check_tactician_lures():
    g = _new_game([ReactionSystem()])
    rx = g.system("reactions")

    # Layout (a clear 3-cell row):  player @ x0 | monster @ x0+1 (ACID) | clear @ x0+2
    x0, y = _find_run(g, 3, {g.level.stairs})
    g.player.x, g.player.y = x0, y
    g.player.hp = g.player.max_hp                 # not wounded
    mon = _monster(x0 + 1, y)
    g.actors = [mon]
    rx.props = {(x0 + 1, y): {"acid"}}            # hazard on the monster's own tile
    rx.fire_life = {}

    assert danger_tiles(g) == {(x0 + 1, y)}, danger_tiles(g)
    assert not is_dangerous(g, g.player.x, g.player.y), "player must NOT start on danger"

    # the kite primitive and the brain must agree, and it must be a real step
    expected = lure_step(g, mon, g.player)
    assert expected is not None, "lure_step found no kite for this layout"
    got = TacticianBrain().decide(g, mon)
    assert got == expected != (0, 0), f"tactician should kite ({expected}), got {got}"

    # ...and the kite actually works: after the monster takes that step, the player's
    # greedy chase lands it ON the hazard tile.
    nmx, nmy = mon.x + got[0], mon.y + got[1]
    pdx, pdy = greedy_dir(g.player.x, g.player.y, nmx, nmy)
    landing = (g.player.x + pdx, g.player.y + pdy)
    assert is_dangerous(g, *landing), f"player's greedy chase {landing} is not danger"

    # determinism: same call, same answer
    assert TacticianBrain().decide(g, mon) == got


def _check_tactician_finishes_on_hazard():
    """A hostile already standing on a danger tile adjacent to the tactician -> attack
    it (dir toward that tile), instead of bothering to kite."""
    g = _new_game([ReactionSystem()])
    rx = g.system("reactions")

    x0, y = _find_run(g, 3, {g.level.stairs})
    # player ON the hazard at x0, monster adjacent at x0+1
    g.player.x, g.player.y = x0, y
    g.player.hp = g.player.max_hp
    mon = _monster(x0 + 1, y)
    g.actors = [mon]
    rx.props = {(x0, y): {"acid"}}
    rx.fire_life = {}

    assert is_dangerous(g, g.player.x, g.player.y), "player should be on a danger tile"
    got = TacticianBrain().decide(g, mon)
    assert got == (-1, 0), f"should attack toward the doomed player (-1,0), got {got}"


# --------------------------------------------------------------------------- #
# exploiter: loot when safe, flee to the stairs when wounded
# --------------------------------------------------------------------------- #

def _check_exploiter_loots_item():
    g = _new_game([ReactionSystem()])
    rx = g.system("reactions")
    rx.props, rx.fire_life = {}, {}

    x0, y = _find_run(g, 4, {g.level.stairs})
    g.player.x, g.player.y = x0, y
    g.player.hp = g.player.max_hp
    g.actors = []                                  # no threat anywhere
    g.items = [Item(x=x0 + 3, y=y, glyph="*", name="sigil", slot="relic", power=1)]

    assert nearest_hostile(g, g.player)[0] is None, "no hostiles expected"
    got = ExploiterBrain().decide(g, g.player)
    assert got == (1, 0), f"exploiter should step toward the item (1,0), got {got}"


def _check_exploiter_loots_poi():
    stub = PoiStub()
    g = _new_game([ReactionSystem(), stub])
    rx = g.system("reactions")
    rx.props, rx.fire_life = {}, {}

    x0, y = _find_run(g, 4, {g.level.stairs})
    g.player.x, g.player.y = x0, y
    g.player.hp = g.player.max_hp
    g.actors, g.items = [], []
    stub.ground = {(x0 + 3, y): "lore"}

    assert (x0 + 3, y) in points_of_interest(g), "POI not exposed via points_of_interest"
    got = ExploiterBrain().decide(g, g.player)
    assert got == (1, 0), f"exploiter should step toward the POI (1,0), got {got}"


def _check_exploiter_flees_when_low():
    g = _new_game([ReactionSystem()])
    rx = g.system("reactions")
    rx.props, rx.fire_life = {}, {}

    x0, y = _find_run(g, 4, {g.level.stairs})
    g.player.x, g.player.y = x0, y
    g.actors = []
    g.items = [Item(x=x0 + 3, y=y, glyph="*", name="sigil", slot="relic", power=1)]
    g.player.hp = 1                                # << 40% of max -> retreat overrides loot

    expected = step_toward(g, g.player, *g.level.stairs, safe=True)
    got = ExploiterBrain().decide(g, g.player)
    assert got == expected, f"low-HP exploiter should head to stairs {expected}, got {got}"
    assert got != (0, 0), "expected a real retreat step toward the stairs"


def _check_exploiter_finishes_on_hazard():
    """Priority 2: an adjacent monster already standing on a danger tile gets finished
    (attack dir toward it), ahead of looting/fleeing."""
    g = _new_game([ReactionSystem()])
    rx = g.system("reactions")

    x0, y = _find_run(g, 3, {g.level.stairs})
    # monster @ x0 (ON acid), player adjacent @ x0+1
    mon = _monster(x0, y)
    g.actors = [mon]
    g.player.x, g.player.y = x0 + 1, y
    g.player.hp = g.player.max_hp
    rx.props = {(x0, y): {"acid"}}
    rx.fire_life = {}

    assert is_dangerous(g, mon.x, mon.y), "monster should be on a danger tile"
    assert not is_dangerous(g, g.player.x, g.player.y), "player must NOT be on danger"
    got = ExploiterBrain().decide(g, g.player)
    assert got == (-1, 0), f"exploiter should finish the monster on acid (-1,0), got {got}"


def _check_exploiter_lures():
    """Priority 3: a monster within d<=2 (not yet on a hazard) is kited — the exploiter
    takes a safe step so the monster's greedy chase next lands it on the hazard."""
    g = _new_game([ReactionSystem()])
    rx = g.system("reactions")

    # row: monster @ x0 | ACID @ x0+1 | player @ x0+2 | clear @ x0+3
    x0, y = _find_run(g, 4, {g.level.stairs})
    mon = _monster(x0, y)
    g.actors = [mon]
    g.player.x, g.player.y = x0 + 2, y            # d=2, not adjacent, not on danger
    g.player.hp = g.player.max_hp
    rx.props = {(x0 + 1, y): {"acid"}}
    rx.fire_life = {}

    assert not is_dangerous(g, mon.x, mon.y), "monster must NOT start on danger (else it'd attack)"
    expected = lure_step(g, g.player, mon)
    assert expected is not None, "lure_step found no kite for this layout"
    got = ExploiterBrain().decide(g, g.player)
    assert got == expected == (1, 0), f"exploiter should kite away (1,0), got {got}"

    # the kite pays off: the monster's greedy chase lands ON the hazard.
    nx, ny = g.player.x + got[0], g.player.y + got[1]
    mdx, mdy = greedy_dir(mon.x, mon.y, nx, ny)
    landing = (mon.x + mdx, mon.y + mdy)
    assert is_dangerous(g, *landing), f"monster's greedy chase {landing} is not danger"


def main():
    _check_tactician_lures()
    _check_tactician_finishes_on_hazard()
    _check_exploiter_loots_item()
    _check_exploiter_loots_poi()
    _check_exploiter_flees_when_low()
    _check_exploiter_finishes_on_hazard()
    _check_exploiter_lures()
    print("OK")


if __name__ == "__main__":
    main()
