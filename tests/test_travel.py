"""Motion & signal: log dedup, wide-open spawn, road/wild stride, travel interrupts."""
from __future__ import annotations

from runtime.game import Game, load_manifest


def _g():
    return Game(load_manifest("examples/world.json"), sandbox=True)


def test_log_dedup_collapses_repeats():
    g = _g()
    n = len(g.messages)
    for _ in range(4):
        g.log("Lightning splits the dark.", ambient=True)
    new = g.messages[n:]
    assert len(new) == 1 and new[0].endswith("(x4)"), new


def test_you_wake_on_open_ground_not_boxed_in():
    g = _g()
    px, py = g.player.x, g.player.y
    assert g.room_at(px, py) is None, "you wake on open ground, not a building interior"
    # at least a few directions are immediately walkable (you can explore FROM here)
    walk = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1))
               if g.level.walkable(px + dx, py + dy))
    assert walk >= 4, "the spawn is open enough to walk out of"


def test_stride_crosses_open_wild_but_not_rooms():
    g = _g()
    g.actors = []
    # find open wild floor with a clear run east, outside any room
    spot = None
    for y in range(g.level.h):
        for x in range(g.level.w - 3):
            if (g.room_at(x, y) is None
                    and all(g.level.walkable(x + i, y) and g.level.tiles[y][x + i] != "#"
                            and g.room_at(x + i, y) is None for i in range(3))
                    and not g._interest_near(x + 1, y)):
                spot = (x, y)
                break
        if spot:
            break
    if spot:
        g.player.x, g.player.y = spot
        g.try_move(1, 0)
        assert g.player.x - spot[0] == 2, "open-ground stride covers two tiles"


def test_wild_landmarks_are_beacons():
    g = _g()
    beacons = [pos for pos, kind in g._landmarks.items() if kind == "wild"]
    assert beacons, "wild landmarks register as fog-piercing beacons"
    assert all(pos in g._wild_structs for pos in beacons)


def test_interest_near_flags_discoveries():
    g = _g()
    if g._wild_structs:
        (lx, ly), _ = sorted(g._wild_structs.items())[0]
        assert g._interest_near(lx, ly), "a landmark is 'interest' the stride slows for"


if __name__ == "__main__":
    for fn in (test_log_dedup_collapses_repeats, test_you_wake_on_open_ground_not_boxed_in,
               test_stride_crosses_open_wild_but_not_rooms, test_wild_landmarks_are_beacons,
               test_interest_near_flags_discoveries):
        fn()
        print(f"ok {fn.__name__}")
