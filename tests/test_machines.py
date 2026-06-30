"""Hackable-machines system test: drive the real Game and assert the contract.

Machines are single-use map furniture grounding the two economies:
  - a **Fabricator** (`F`) spends salvaged matter to forge a sigil (via the
    `forge` system) into a free slot, then burns out;
  - a **Terminal** (`T`) hacks a region ahead onto the knowledge frontier (via
    `knowledge.reveal`), then burns out.

This runs the full partner stack the contract names — SigilSystem, ReactionSystem,
KnowledgeSystem, ForgeSystem, MachineSystem — and drives MachineSystem.on_player_act
directly (so we isolate the machine's effect from ForgeSystem's per-turn auto-forge).

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_machines
"""
from runtime.game import Game, load_manifest
from runtime.components import inv, world_materials
from runtime.sigils import SigilSystem
from runtime.reactions import ReactionSystem
from runtime.knowledge import KnowledgeSystem
from runtime.forge import ForgeSystem
from runtime.machines import MachineSystem


def _fresh():
    g = Game(load_manifest("examples/world.json"),
             systems=[SigilSystem(), ReactionSystem(), KnowledgeSystem(),
                      ForgeSystem(), MachineSystem()])
    return g


def _seed_matter(game, qty=20):
    """Give the player ample matter from the world's own material vocabulary."""
    mats = world_materials(game)
    assert mats, "world must define a material vocabulary"
    inv(game.player).comp = {}
    inv(game.player).add({mats[0]: qty})
    return mats


def test_placement():
    g = _fresh()
    m = g.system("machines")
    assert m.fabricators, "a Fabricator must be placed on floor enter"
    assert m.terminals, "a Terminal must be placed on floor enter"
    assert not (m.fabricators & m.terminals), "F and T occupy distinct tiles"

    # never on the player or the stairs, always on real floor
    forbidden = {(g.player.x, g.player.y), g.level.stairs}
    for (x, y) in m.fabricators | m.terminals:
        assert (x, y) not in forbidden, "machine on player/stairs"
        assert g.level.tiles[y][x] == ".", "machine must sit on a floor tile"

    # points_of_interest surfaces every machine tile
    poi = set(m.points_of_interest(g))
    assert poi == (m.fabricators | m.terminals), "POIs must list all machine tiles"


def test_fabricator_forges_and_consumes():
    g = _fresh()
    m = g.system("machines")
    sig = g.system("sigils")
    sig.slots = []                       # guarantee a free slot
    _seed_matter(g)

    slots_before = len(sig.slots)
    matter_before = inv(g.player).total()

    fab = sorted(m.fabricators)[0]
    g.player.x, g.player.y = fab
    m.on_player_act(g)                   # stand on F -> forge

    assert len(sig.slots) == slots_before + 1, "fabricator forged a sigil (slots +1)"
    assert inv(g.player).total() < matter_before, "matter was spent forging"
    assert fab not in m.fabricators, "the fabricator is single-use (consumed)"
    assert any("fabricator forges" in msg for msg in g.messages), "fabricator logged"


def test_fabricator_stays_when_no_free_slot():
    g = _fresh()
    m = g.system("machines")
    sig = g.system("sigils")
    _seed_matter(g)
    # fill every slot so forge() must fail
    from runtime.sigils import MAX_SLOTS
    sig.slots = [{"note": "x", "role": "leaf", "ability": "Ward", "durability": 2}
                 for _ in range(MAX_SLOTS)]

    fab = sorted(m.fabricators)[0]
    g.player.x, g.player.y = fab
    n_msgs = len(g.messages)
    m.on_player_act(g)

    assert fab in m.fabricators, "no free slot -> fabricator NOT consumed"
    assert not any("fabricator forges" in msg for msg in g.messages[n_msgs:]), \
        "nothing logged when the forge can't craft"


def test_terminal_reveals_region_and_consumes():
    g = _fresh()
    m = g.system("machines")
    knowledge = g.system("knowledge")

    rid = m.region_ahead(g)
    assert rid is not None, "a region ahead must be computable"
    region = next(r for r in g.m["regions"] if r["id"] == rid)
    anchor = region["sourceNoteId"]

    knowledge.known = set()              # ensure the region starts unknown
    assert not knowledge.is_known(anchor), "target region must start unknown"

    term = sorted(m.terminals)[0]
    g.player.x, g.player.y = term
    m.on_player_act(g)                   # stand on T -> hack

    assert knowledge.is_known(anchor), "terminal must reveal a region ahead"
    assert term not in m.terminals, "the terminal is single-use (consumed)"
    assert any("hack the terminal" in msg for msg in g.messages), "terminal logged"


def test_render_overlay_floor_only():
    g = _fresh()
    m = g.system("machines")
    grid = [row[:] for row in g.level.tiles]
    m.render_overlay(g, grid)
    for (x, y) in m.fabricators:
        assert grid[y][x] == "F", "Fabricator drawn as F on its floor cell"
    for (x, y) in m.terminals:
        assert grid[y][x] == "T", "Terminal drawn as T on its floor cell"
    # an actor/item glyph must never be overwritten
    grid2 = [row[:] for row in g.level.tiles]
    for (x, y) in m.fabricators:
        grid2[y][x] = "@"                # simulate the player standing there
    m.render_overlay(g, grid2)
    for (x, y) in m.fabricators:
        assert grid2[y][x] == "@", "overlay must not clobber a non-floor glyph"


def test_none_guarded_partners():
    # MachineSystem alone: placement still works; using machines is a safe no-op.
    g = Game(load_manifest("examples/world.json"), systems=[MachineSystem()])
    m = g.system("machines")
    assert m.fabricators and m.terminals, "machines place without any partners"
    fab = sorted(m.fabricators)[0]
    g.player.x, g.player.y = fab
    m.on_player_act(g)                   # no forge system -> bench stays, no crash
    assert fab in m.fabricators, "no forge -> fabricator stays"
    term = sorted(m.terminals)[0]
    g.player.x, g.player.y = term
    m.on_player_act(g)                   # no knowledge system -> no-op, no crash
    assert term in m.terminals, "no knowledge -> terminal stays"


def test_deterministic():
    runs = []
    for _ in range(2):
        g = _fresh()
        m = g.system("machines")
        runs.append((sorted(m.fabricators), sorted(m.terminals), m.region_ahead(g)))
    assert runs[0] == runs[1], ("placement + region choice are deterministic", runs)


def main():
    test_placement()
    test_fabricator_forges_and_consumes()
    test_fabricator_stays_when_no_free_slot()
    test_terminal_reveals_region_and_consumes()
    test_render_overlay_floor_only()
    test_none_guarded_partners()
    test_deterministic()
    print("OK")


if __name__ == "__main__":
    main()
