"""Debug toolkit: engine-side operators used by the backtick menu."""
from __future__ import annotations

from runtime import debug as dbg
from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem
from runtime.salvage import SalvageSystem, inv
from runtime.sigils import SigilSystem


def _game():
    return Game(load_manifest("examples/world.json"), sandbox=True,
                systems=[KnowledgeSystem(), SalvageSystem(), SigilSystem()])


def test_reveal_all_lifts_every_fog():
    g = _game()
    dbg.reveal_all(g)
    assert g.system("knowledge").region_mapped(g)
    assert len(g.system("knowledge").seen[g.floor]) == g.level.w * g.level.h


def test_warp_heart_lands_beside_the_boss():
    g = _game()
    # the warden waits in its depths now: enter them, then warp
    door = next(p for p, d in sorted(g._gates.items())
                if d == next(b["regionId"] for b in g.m["bosses"]
                             if b["sourceNoteId"] == g.final_boss_source))
    g.player.x, g.player.y = door
    g.descend()
    dbg.warp_heart(g)
    boss = next(a for a in g.actors if a.is_boss
                and a.source == g.final_boss_source)
    assert max(abs(g.player.x - boss.x), abs(g.player.y - boss.y)) == 1


def test_grants_and_smite():
    g = _game()
    dbg.grant_matter(g)
    assert inv(g.player).total() >= 25
    dbg.grant_sigils(g)
    assert g.system("sigils").slots, "slots filled"
    dbg.warp_heart(g)
    assert "smote" in dbg.smite(g, radius=3)


def test_inspect_reads_the_ground():
    g = _game()
    lines = dbg.inspect(g)
    assert any("seed" in ln for ln in lines)
    # you now wake on open settled ground (not boxed in a room), so inspect reports
    # the world state; step into a room and it names it
    idx = next(iter(g.room_notes))
    g.player.x, g.player.y = g.room_tiles(idx)[0]
    assert any("room" in ln for ln in dbg.inspect(g))


if __name__ == "__main__":
    for fn in (test_reveal_all_lifts_every_fog, test_warp_heart_lands_beside_the_boss,
               test_grants_and_smite, test_inspect_reads_the_ground):
        fn()
        print(f"ok {fn.__name__}")
