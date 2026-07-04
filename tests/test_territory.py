"""Territoriality: sandbox creatures belong to their note's ground."""
from __future__ import annotations

from runtime.game import LEASH, Game, load_manifest


def _game():
    return Game(load_manifest("examples/world.json"), sandbox=True)


def _far_foe(g):
    """A monster whose home is well away from the player."""
    return next(a for a in g.actors if a.allegiance == "monster"
                and max(abs(a._home[0] - g.player.x),
                        abs(a._home[1] - g.player.y)) > LEASH + 4)


def test_a_creature_keeps_to_its_own_ground():
    g = _game()
    foe = _far_foe(g)
    pos = (foe.x, foe.y)
    for _ in range(5):
        g.enemies_act()
    assert (foe.x, foe.y) == pos, "unprovoked and unvisited, it does not stir"


def test_provocation_overrides_territory():
    g = _game()
    foe = _far_foe(g)
    # outside its territory (> LEASH from home) but within its brain's sight
    g.player.x, g.player.y = foe._home[0] + LEASH + 2, foe._home[1]
    pos = (foe.x, foe.y)
    for _ in range(3):
        g.enemies_act()
    assert (foe.x, foe.y) == pos, "unprovoked, it ignores you beyond its ground"
    foe._provoked = True
    moved = False
    for _ in range(5):
        g.enemies_act()
        moved = moved or (foe.x, foe.y) != pos
    assert moved, "a struck creature forgets its territory"


def test_entering_its_ground_wakes_it():
    g = _game()
    foe = _far_foe(g)
    g.player.x, g.player.y = foe._home   # stand on its ground
    foe.x, foe.y = foe._home[0] + 2, foe._home[1]
    pos = (foe.x, foe.y)
    moved = False
    for _ in range(5):
        g.enemies_act()
        moved = moved or (foe.x, foe.y) != pos
    assert moved, "intrusion on its ground stirs it"


def test_waiting_at_the_entrance_is_safe():
    g = _game()
    for _ in range(100):
        g.wait()
    assert g.alive and g.player.hp == g.player.max_hp


if __name__ == "__main__":
    for fn in (test_a_creature_keeps_to_its_own_ground,
               test_provocation_overrides_territory,
               test_entering_its_ground_wakes_it,
               test_waiting_at_the_entrance_is_safe):
        fn()
        print(f"ok {fn.__name__}")
