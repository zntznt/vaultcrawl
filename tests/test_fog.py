"""Fog regression: an ordinary kill's neighbor-splash must never unmask a region."""
from __future__ import annotations

from runtime.entities import Actor
from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem


def _game():
    return Game(load_manifest("examples/world.json"), systems=[KnowledgeSystem()])


def test_neighbor_kill_extends_frontier_but_keeps_fog():
    g = _game()
    ks = g.system("knowledge")
    anchor = g.region_for(g.floor)["sourceNoteId"]
    neighbor = next(n for n in g.m["graph"]["nodes"][anchor]["neighbors"] if n != anchor)
    foe = Actor(x=1, y=1, glyph="s", name="splash test", hp=1, max_hp=1, atk=1,
                source=neighbor)
    ks.on_event(g, "enemy_killed", {"enemy": foe})
    assert ks.is_known(anchor), "the anchor joins the navigable frontier"
    assert not ks.region_mapped(g), "but splash alone must not lift the region's fog"


def test_intel_maps_ahead_never_here():
    g = _game()
    ks = g.system("knowledge")
    here = g.region_for(g.floor)
    ks.reveal(here["id"])
    assert not ks.region_mapped(g), "intel naming the CURRENT region must not map it"
    assert ks.is_known(here["sourceNoteId"]), "but it still extends the frontier"
    ahead = next(r for r in g.m["regions"] if r["id"] != here["id"])
    ks.reveal(ahead["id"])
    assert ahead["sourceNoteId"] in ks.learned, "a region ahead is pre-mapped"


def test_ordinary_anchor_kill_does_not_map_but_boss_kill_does():
    g = _game()
    ks = g.system("knowledge")
    anchor = g.region_for(g.floor)["sourceNoteId"]
    grunt = Actor(x=1, y=1, glyph="s", name="anchor grunt", hp=1, max_hp=1, atk=1,
                  source=anchor)
    ks.on_event(g, "enemy_killed", {"enemy": grunt})
    assert not ks.region_mapped(g), "an ordinary kill is not region intel"
    boss = Actor(x=1, y=1, glyph="M", name="warden", hp=1, max_hp=1, atk=1,
                 source=anchor, is_boss=True)
    ks.on_event(g, "enemy_killed", {"enemy": boss})
    assert ks.region_mapped(g), "felling the boss maps its region"


def test_mapped_region_shows_terrain_but_hides_far_actors():
    g = _game()
    ks = g.system("knowledge")
    # simulate having taken this region's map earlier (e.g. its boss fell)
    ks._reveal(g, g.region_for(g.floor)["sourceNoteId"], direct=True)
    assert ks.region_mapped(g)
    px, py = g.player.x, g.player.y
    far = next(a for a in g.actors
               if max(abs(a.x - px), abs(a.y - py)) > 4)   # beyond sight radius
    grid = [row[:] for row in g.level.tiles]
    grid[far.y][far.x] = far.glyph                          # composited actor glyph
    ks.render_overlay(g, grid)
    assert grid[far.y][far.x] == g.level.tiles[far.y][far.x], \
        "a far actor must be fogged back to terrain even in a mapped region"


if __name__ == "__main__":
    for fn in (test_neighbor_kill_extends_frontier_but_keeps_fog,
               test_intel_maps_ahead_never_here,
               test_ordinary_anchor_kill_does_not_map_but_boss_kill_does,
               test_mapped_region_shows_terrain_but_hides_far_actors):
        fn()
        print(f"ok {fn.__name__}")
