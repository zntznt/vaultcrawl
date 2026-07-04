"""Bumping friendlies swaps places: no friendly body ever blocks a way."""
from __future__ import annotations

from runtime.entities import make_critter, make_npc
from runtime.game import Game, load_manifest


def _game():
    g = Game(load_manifest("examples/world.json"), sandbox=True)
    g.actors = []
    return g


def _clear_spot(g):
    """A walkable tile with a walkable east neighbor."""
    for y in range(g.level.h):
        for x in range(g.level.w - 1):
            if g.level.walkable(x, y) and g.level.walkable(x + 1, y):
                return x, y
    raise AssertionError("no open pair")


def test_bumping_a_keeper_swaps_places():
    g = _game()
    x, y = _clear_spot(g)
    g.player.x, g.player.y = x, y
    npc = make_npc("Keeper", "P", x + 1, y)
    g.actors = [npc]
    g.try_move(1, 0)
    assert (g.player.x, g.player.y) == (x + 1, y)
    assert (npc.x, npc.y) == (x, y)
    assert npc.hp == npc.max_hp, "a bump never harms a friendly"


def test_bumping_wildlife_swaps_not_attacks():
    g = _game()
    x, y = _clear_spot(g)
    g.player.x, g.player.y = x, y
    critter = make_critter("grazer", "n", x + 1, y, hp=3, atk=0)
    g.actors = [critter]
    g.try_move(1, 0)
    assert critter.hp == 3, "wildlife is not a punching bag"
    assert (g.player.x, g.player.y) == (x + 1, y)


def test_a_becalmed_creature_is_safe_to_pass():
    g = _game()
    x, y = _clear_spot(g)
    g.player.x, g.player.y = x, y
    foe = next(a for a in g.actors) if g.actors else None
    from runtime.entities import Actor
    foe = Actor(x=x + 1, y=y, glyph="s", name="stilled shade", hp=5, max_hp=5, atk=1)
    g.actors = [foe]
    g._join_wild(foe)
    g.try_move(1, 0)
    assert foe.hp == 5, "bumping a becalmed creature must not undo the becalming"
    assert (g.player.x, g.player.y) == (x + 1, y)


def test_hostiles_still_get_bumped_attacked():
    g = _game()
    x, y = _clear_spot(g)
    g.player.x, g.player.y = x, y
    from runtime.entities import Actor
    foe = Actor(x=x + 1, y=y, glyph="s", name="shade", hp=99, max_hp=99, atk=1)
    g.actors = [foe]
    g.try_move(1, 0)
    assert foe.hp < 99, "a hostile bump is still an attack"
    assert (g.player.x, g.player.y) == (x, y)


if __name__ == "__main__":
    for fn in (test_bumping_a_keeper_swaps_places, test_bumping_wildlife_swaps_not_attacks,
               test_a_becalmed_creature_is_safe_to_pass, test_hostiles_still_get_bumped_attacked):
        fn()
        print(f"ok {fn.__name__}")
