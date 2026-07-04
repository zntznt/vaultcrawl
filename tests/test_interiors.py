"""Interior patterns: themed substructures matched by each center's own dynamics."""
from __future__ import annotations

import json
from collections import deque

from runtime.arch.carve import carve
from runtime.arch.grow import grow
from runtime.dungeon import WALL
from runtime.game import Game, load_manifest


def _world():
    m = json.load(open("examples/world.json"))
    plan = grow(m["graph"], seed=m["seed"])
    return m, plan, carve(plan, seed=m["seed"])


def test_motifs_follow_the_notes_dynamics():
    _m, plan, _level = _world()
    # motifs are (name, phrase, fixture_tiles) triples now
    by_note = {c.id: {m[0] for m in getattr(c, "motifs", [])} for c in plan.placed()}
    applied = {name for names in by_note.values() for name in names}
    assert len(applied) >= 3, f"expected a varied language, got {applied}"
    for c in plan.placed():
        names = {m[0] for m in getattr(c, "motifs", [])}
        if "colonnade" in names:
            assert c.role == "hub"
        if "ruin" in names:
            assert c.age <= 0.15
        if "overgrowth" in names:
            assert c.age >= 0.7
        if "meeting stones" in names:
            assert len(c.members) >= 2


def test_fixtures_are_walkable_and_examinable():
    from runtime.arch.interiors import FIXTURES
    from runtime.game import Game, load_manifest
    g = Game(load_manifest("examples/world.json"), sandbox=True)
    placed_fix = [(i, f) for i, fs in g._fixtures.items() for f in fs]
    assert placed_fix, "the world should stamp some focal fixtures"
    ridx, (fx, fy) = placed_fix[0][0], placed_fix[0][1]
    assert g.level.tiles[fy][fx] in FIXTURES
    assert g.level.walkable(fx, fy), "fixtures are walkable scenery"
    g.player.x, g.player.y = fx, fy
    before = len(g.messages)
    g.examine()
    said = " ".join(g.messages[before:])
    assert any(n.split()[-1] in said for n in
               ("altar", "pillar", "meeting-stone", "shelf", "well")), \
        "standing at a fixture names it in the log"


def test_interiors_are_deterministic():
    _m, _p, a = _world()
    _m2, _p2, b = _world()
    assert a.tiles == b.tiles


def test_connectivity_survives_the_interiors():
    _m, _plan, level = _world()
    start = level.player_start
    seen, q = {start}, deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt not in seen and level.walkable(*nxt):
                seen.add(nxt)
                q.append(nxt)
    stranded = [(x, y) for y in range(level.h) for x in range(level.w)
                if level.tiles[y][x] != WALL and (x, y) not in seen]
    assert not stranded, f"interior walls stranded tiles: {stranded[:5]}"


def test_the_game_names_the_place():
    # arrival folds the place's truest feature into one quiet line (no log dump)
    g = Game(load_manifest("examples/world.json"), sandbox=True)
    assert any(g._motifs.values()), "some rooms should carry motifs"
    idx = next(i for i, ms in g._motifs.items() if ms)
    tiles = [t for t in g.room_tiles(idx) if g.room_at(t[0] - 1, t[1]) != idx]
    if not tiles:
        return
    tile = tiles[0]
    g.player.x, g.player.y = tile[0] - 1, tile[1]
    g.actors = []
    g._rooms_seen.discard(idx)
    before = len(g.messages)
    g.try_move(1, 0)
    if g.room_at(*tile) == idx:
        assert any("where" in m and "You enter" in m for m in g.messages[before:]), \
            "entering names the place and its feature in one line"


if __name__ == "__main__":
    for fn in (test_motifs_follow_the_notes_dynamics, test_interiors_are_deterministic,
               test_connectivity_survives_the_interiors, test_the_game_names_the_place):
        fn()
        print(f"ok {fn.__name__}")
