"""Drive the real Game through the FaunaSystem and assert the autonomous contract.

Checks:
  1. spawn      — entering a floor spawns `wild` critters tagged `fauna:<kind>`.
  2. core loop  — a wild predator placed next to a `monster` damages it through the
                  allegiance-aware turn loop (`game.enemies_act()`), while the player
                  (kept far away) is never touched: wildlife ignores the hero.
  3. drive      — with a flora STUB exposing `flora_at`/`consume`, a grazer adjacent
                  to a plant eats it.
  4. determinism— two fresh worlds spawn critters at identical positions.

Run: python3 -m tests.test_fauna
"""
from runtime.game import Game, load_manifest
from runtime.systems import System
from runtime.entities import make_critter, make_enemy
from runtime.fauna import FaunaSystem
from runtime.dungeon import free_floor_tiles

MANIFEST = "examples/world.json"


class FloraStub(System):
    """Minimal flora partner: a fixed set of plant tiles + the query/command API."""
    name = "flora"

    def __init__(self, tiles):
        self.tiles = set(tiles)

    def flora_at(self, x, y):
        return (x, y) in self.tiles

    def consume(self, x, y):
        if (x, y) in self.tiles:
            self.tiles.remove((x, y))
            return True
        return False


def _critters(game):
    return [a for a in game.actors
            if isinstance(a.source, str) and a.source.startswith("fauna:")]


def _check_spawn():
    g = Game(load_manifest(MANIFEST), systems=[FaunaSystem()])
    crit = _critters(g)
    assert crit, "fauna spawned no critters on floor enter"
    assert all(a.allegiance == "wild" for a in crit), \
        "every fauna critter must be allegiance 'wild'"
    kinds = {a.source.split(":", 1)[1] for a in crit}
    assert kinds <= {"grazer", "scavenger", "predator"}, kinds
    assert all(a.glyph in ("n", "z", "Y") for a in crit), "unexpected critter glyph"
    # bounded population
    assert len(crit) <= 10, "fauna population is not bounded"
    # status line reports the count
    assert g.system("fauna").status_line(g) == "Wild: %d" % len(crit)


def _check_core_loop():
    """Predator (wild) next to a monster: the core loop makes the predator fight it,
    and the player — parked far off the map — is left completely alone."""
    g = Game(load_manifest(MANIFEST), systems=[FaunaSystem()])
    g.actors = []
    g.player.x, g.player.y = -50, -50          # wildlife ignores the player anyway
    php = g.player.hp

    mon = make_enemy({"tier": 1, "archetype": "beast",
                      "name": "big monster", "sourceNoteId": "x"}, 6, 5)
    mon.hp = mon.max_hp = 200                   # big hp so it survives to be measured
    assert mon.allegiance == "monster"
    pred = make_critter("predator", "Y", 5, 5, 9, 3, source="fauna:predator")
    assert pred.allegiance == "wild"
    g.actors = [pred, mon]

    g.enemies_act()
    assert mon.hp < 200, "wild predator did not fight the adjacent monster"
    assert g.player.hp == php, "the player was touched — wildlife must ignore the hero"
    assert g.alive, "player should be unharmed"


def _check_grazer_eats():
    """A grazer adjacent to a flora tile consumes it via the flora partner API."""
    g = Game(load_manifest(MANIFEST), systems=[FaunaSystem(), FloraStub(set())])
    fauna = g.system("fauna")
    flora = g.system("flora")

    exclude = {(g.player.x, g.player.y), g.level.stairs}
    spots = free_floor_tiles(g.level, exclude)
    plant = grazer_at = None
    for (fx, fy) in spots:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            gx, gy = fx + dx, fy + dy
            if (g.level.walkable(gx, gy)
                    and (gx, gy) != (g.player.x, g.player.y)
                    and (gx, gy) != (fx, fy)):
                plant, grazer_at = (fx, fy), (gx, gy)
                break
        if plant:
            break
    assert plant is not None, "could not find a walkable plant+neighbour pair"

    flora.tiles = {plant}
    g.actors = [make_critter("grazer", "n", grazer_at[0], grazer_at[1],
                             6, 1, source="fauna:grazer")]
    assert flora.flora_at(*plant)
    fauna.on_player_act(g)
    assert not flora.flora_at(*plant), "grazer did not consume the adjacent flora"


def _check_determinism():
    a = [(c.glyph, c.x, c.y) for c in _critters(
        Game(load_manifest(MANIFEST), systems=[FaunaSystem()]))]
    b = [(c.glyph, c.x, c.y) for c in _critters(
        Game(load_manifest(MANIFEST), systems=[FaunaSystem()]))]
    assert a == b, "fauna spawning is not deterministic"


def main():
    _check_spawn()
    _check_core_loop()
    _check_grazer_eats()
    _check_determinism()
    print("OK")


if __name__ == "__main__":
    main()
