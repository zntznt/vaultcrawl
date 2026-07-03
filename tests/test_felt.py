"""The felt architecture: gradients, landmarks, frictions, stride."""
from __future__ import annotations

from runtime.game import Game, load_manifest


def _game():
    return Game(load_manifest("examples/world.json"), sandbox=True)


def test_light_rises_toward_the_heart():
    g = _game()
    assert g._glow_cells, "places carry a glow"
    assert max(g._glow_cells.values()) > 0.9 and min(g._glow_cells.values()) < 0.3, \
        "the gradient spans periphery to heart"


def test_hearts_and_towns_are_landmarks():
    g = _game()
    kinds = set(g._landmarks.values())
    assert "town" in kinds, "settlements are visible from afar"
    for door in g._gates:
        assert door in g._landmarks


def test_stride_on_the_road():
    g = _game()
    g.actors = []
    found = None
    for y in range(g.level.h):
        for x in range(g.level.w - 2):
            if all(g.level.tiles[y][x + i] == "░" for i in range(1, 3)) \
                    and g.level.walkable(x, y):
                found = (x, y)
                break
        if found:
            break
    assert found, "the world has roads"
    g.player.x, g.player.y = found
    g.try_move(1, 0)
    assert g.player.x - found[0] == 2, "two paces a turn on the road"


def test_single_steps_within_places():
    g = _game()
    g.actors = []
    idx = next(iter(g.room_notes))
    tiles = [t for t in g.room_tiles(idx)
             if g.level.walkable(t[0] + 1, t[1]) and g.room_at(t[0] + 1, t[1]) == idx]
    if not tiles:
        return
    g.player.x, g.player.y = tiles[0]
    g.try_move(1, 0)
    assert g.player.x - tiles[0][0] == 1, "inside a place, steps are careful"


if __name__ == "__main__":
    for fn in (test_light_rises_toward_the_heart, test_hearts_and_towns_are_landmarks,
               test_stride_on_the_road, test_single_steps_within_places):
        fn()
        print(f"ok {fn.__name__}")
