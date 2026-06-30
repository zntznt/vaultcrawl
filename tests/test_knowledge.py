"""Knowledge-fog system test: drives the real Game and asserts the contract.

Fog is REAL: standing on a floor does NOT auto-map its region — you reveal it by
exploring (line-of-sight radius) or by intel (lore / scavenged sensors / a shared map),
which also pre-lights regions you have yet to reach. Plus the cross-system interactions:
`enemy_killed` reveals the foe's source note, `lore_read` maps the named region, and the
`reveal`/`is_known` query API.

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_knowledge
"""
from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem, RADIUS


def main():
    s = KnowledgeSystem()
    g = Game(load_manifest("examples/world.json"), systems=[s])
    nodes = g.m["graph"]["nodes"]

    s.on_world_start(g)
    assert s.known == set(), "on_world_start must clear known"
    s.on_floor_enter(g)

    # --- fog is real: the floor you stand on starts UNKNOWN (no auto-reveal) ---
    region = g.region_for(g.floor)
    anchor = region["sourceNoteId"]
    assert anchor not in s.known, "floor enter must NOT auto-reveal the region (fog active)"
    assert not s.region_mapped(g), "the current region starts unmapped (fog of war)"
    assert g.floor in s.seen, "seen must have an entry for the current floor"

    # --- BUS: enemy_killed teaches you its source note ---
    if g.actors:
        enemy = g.actors[0]
        s.on_event(g, "enemy_killed", {"enemy": enemy})
        assert s.is_known(enemy.source), "on_event('enemy_killed') must reveal enemy.source"
    s.on_event(g, "enemy_killed", {})  # missing payload must not crash

    # --- explore a few turns so `seen` accumulates around the player ---
    s.on_player_act(g)
    for _ in range(6):
        g.try_move(1, 0)
        s.on_player_act(g)
    px, py = g.player.x, g.player.y

    # --- UNKNOWN region: fog blanks far, unexplored cells ---
    s.known = set()
    assert not s.region_mapped(g), "region reads as unknown after clearing known"
    grid = [row[:] for row in g.level.tiles]
    s.render_overlay(g, grid)
    far = None
    for y in range(len(grid)):
        for x in range(len(grid[y])):
            near = abs(x - px) <= RADIUS and abs(y - py) <= RADIUS
            if not near and (x, y) not in s.seen[g.floor]:
                far = (x, y)
                break
        if far:
            break
    assert far is not None, "expected a far, unexplored cell"
    fx, fy = far
    assert grid[fy][fx] == " ", f"far unknown cell {far} should be blanked, got {grid[fy][fx]!r}"
    assert grid[py][px] != " ", "the player's own cell must remain visible"

    # --- MAPPED region (via intel): full floor, no blanks ---
    s.reveal(region["id"])
    assert s.region_mapped(g), "revealing the region id should map it"
    grid = [row[:] for row in g.level.tiles]
    s.render_overlay(g, grid)
    assert grid == g.level.tiles, "a mapped region must be left fully visible"

    # --- status line ---
    line = s.status_line(g)
    mapped = len(s.known & set(nodes))
    assert line == f"Mapped: {mapped}/{len(nodes)} ideas", f"bad status line: {line!r}"

    # --- QUERY API: reveal accepts a note id OR a region id ---
    s.known = set()
    note_id = next(iter(nodes))
    s.reveal(note_id)
    assert s.is_known(note_id), "reveal(note_id) must mark the note known"

    s.known = set()
    reg = g.m["regions"][0]
    assert reg["id"] != reg["sourceNoteId"]
    s.reveal(reg["id"])
    assert s.is_known(reg["sourceNoteId"]), "reveal(region_id) must learn the region anchor"
    s.reveal(None)
    s.reveal("")

    # --- BUS: lore_read maps the named region AND reveals the named note ---
    s.known = set()
    far_reg = g.m["regions"][-1]
    R, R_anchor = far_reg["id"], far_reg["sourceNoteId"]
    N = next(k for k in nodes if k != R_anchor)
    s.on_event(g, "lore_read", {"region_id": R, "note": N})
    assert s.is_known(R_anchor), "lore_read region_id must map that region"
    assert s.is_known(N), "lore_read note must be revealed"
    s.on_event(g, "lore_read", {"region_id": None})
    s.on_event(g, "lore_read", {})

    # --- ghost ids (e.g. killing a lost-note echo) must NOT push Mapped over 100% ---
    s.known = set(nodes) | {"ghost-not-a-real-note"}
    line = s.status_line(g)
    assert line == f"Mapped: {len(nodes)}/{len(nodes)} ideas", f"Mapped must clamp: {line!r}"

    print("OK")


if __name__ == "__main__":
    main()
