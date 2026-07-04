"""Canopy raycast: dense growth blocks SIGHT (not movement) — a forest to thread."""
from __future__ import annotations

import os

from runtime.game import Game, load_manifest
from runtime.knowledge import CANOPY, KnowledgeSystem


def _game():
    p = "examples/world.json"
    return Game(load_manifest(p), sandbox=True, sprawl=3.0,
                site_cache=p + ".site.json", systems=[KnowledgeSystem()])


def test_canopy_occludes_sight_but_never_movement():
    g = _game()
    kn = g.system("knowledge")
    canopy = {xy for xy, gl in g._overlay.items() if gl in CANOPY}
    assert canopy, "the world grows thickets to thread"
    # a canopy tile is still walkable — you push THROUGH growth, you don't bump it
    cx, cy = next(iter(canopy))
    assert g.level.walkable(cx, cy), "canopy blocks sight, not movement"
    # and it occludes: standing deep in a thicket sees far less than open ground
    def view(x, y):
        return len(kn._visible(g, x, y, kn._sight(g)))
    # find the densest thicket cell (most canopy neighbors)
    best = max(canopy, key=lambda c: sum((c[0] + dx, c[1] + dy) in canopy
                                         for dx in range(-3, 4) for dy in range(-3, 4)))
    # an open cell far from any canopy
    openc = None
    for y in range(15, g.level.h - 15):
        for x in range(15, g.level.w - 15):
            if (g.level.tiles[y][x] == "." and
                    not any((x + dx, y + dy) in canopy
                            for dx in range(-5, 6) for dy in range(-5, 6))):
                openc = (x, y)
                break
        if openc:
            break
    assert openc, "the world has open ground too"
    assert view(*best) < view(*openc), "a thicket closes the view; open ground opens it"


def test_raycast_reveals_the_player_tile_and_is_deterministic():
    g = _game()
    kn = g.system("knowledge")
    x, y = g.player.x, g.player.y
    v1 = kn._visible(g, x, y, kn._sight(g))
    v2 = kn._visible(g, x, y, kn._sight(g))
    assert (x, y) in v1, "you always see your own tile"
    assert v1 == v2, "visibility is a pure function of state"


if __name__ == "__main__":
    for fn in (test_canopy_occludes_sight_but_never_movement,
               test_raycast_reveals_the_player_tile_and_is_deterministic):
        fn()
        print(f"ok {fn.__name__}")
