"""Autonomous behaviour test for the flora ecology system.

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_flora

Drives a REAL Game with the reactions + flora systems registered and asserts the
vegetation lives on its own logic: it sprouts on floor enter, creeps over several
turns, burns (igniting a neighbour) when it sits on fire, and can be grazed away.
Deterministic: two identical runs reach the same plant set.
"""
from __future__ import annotations

import collections

from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.flora import FloraSystem

_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _build():
    # Game.__init__ runs on_world_start + (via descend) on_floor_enter for floor 1.
    return Game(load_manifest("examples/world.json"),
                systems=[ReactionSystem(), FloraSystem()])


def _expected_weed(game):
    counts = collections.Counter()
    for node in game.m["graph"]["nodes"].values():
        for tag in (node.get("tags") or []):
            counts[tag] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _is_floor(lvl, x, y):
    return 0 <= x < lvl.w and 0 <= y < lvl.h and lvl.tiles[y][x] == "."


def main():
    g = _build()
    flora = g.system("flora")

    # weed is seeded from the vault's most-common tag
    assert flora.weed == _expected_weed(g), f"weed should be the dominant tag, got {flora.weed!r}"

    # 1) plants sprout on floor enter
    assert flora.plants, "flora should sprout on floor enter"
    n0 = len(flora.plants)

    # 2) they spread over several turns (slow, but monotic growth with room)
    for _ in range(12):
        flora.on_player_act(g)
    assert len(flora.plants) > n0, f"flora should spread (was {n0}, now {len(flora.plants)})"
    assert len(flora.plants) <= flora.cap, "flora must stay under its cap (never fill the map)"

    # determinism: an identical game driven identically lands on the same plant set
    g_b = _build()
    f_b = g_b.system("flora")
    for _ in range(12):
        f_b.on_player_act(g_b)
    assert flora.plants == f_b.plants, "flora spread must be deterministic across runs"

    # 3) a plant on a fire tile burns and the flame leaps to an adjacent tile
    g2 = _build()
    f2 = g2.system("flora")
    r2 = g2.system("reactions")
    lvl = g2.level
    # pick a floor tile that has at least one orthogonal floor neighbour
    target = None
    for (x, y) in sorted(flora_free(lvl)):
        if any(_is_floor(lvl, x + dx, y + dy) for dx, dy in _ORTH):
            target = (x, y)
            break
    assert target is not None, "need a floor tile with a floor neighbour"
    f2.plants = {target}
    r2.ignite(*target)                       # set the plant's tile alight
    f2.on_player_act(g2)
    assert not f2.flora_at(*target), "a plant on fire should burn away"
    tx, ty = target
    spread = any("fire" in r2.props_at(tx + dx, ty + dy)
                 for dx, dy in _ORTH if _is_floor(lvl, tx + dx, ty + dy))
    assert spread, "burning flora should ignite an adjacent floor tile"

    # 4) consume removes a plant and reports it (then reports False)
    spot = target
    f2.plants = {spot}
    assert f2.consume(*spot) is True, "consume should eat the plant and return True"
    assert f2.flora_at(*spot) is False, "consumed plant should be gone"
    assert f2.consume(*spot) is False, "consuming an empty tile returns False"

    print("OK")


def flora_free(lvl):
    return [(x, y) for y in range(lvl.h) for x in range(lvl.w) if lvl.tiles[y][x] == "."]


if __name__ == "__main__":
    main()
