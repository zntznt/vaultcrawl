"""Sandbox world v1: the whole vault grown + carved as ONE persistent open-world map,
roamed (no floors), with the district-under-the-player driving the systems.

Contract checked here:
  * a Game(architecture=True) builds ONE carved world (not a 56x20 floor), with a
    walkable player_start, and spawns enemies/bosses into it -- once, no descent;
  * region_at(x, y) resolves the district from the carved tile->note map, so a system
    asking "where am I" gets the right region by POSITION, not by floor number;
  * spawned enemies land inside a real district (region_at returns a named region);
  * the camera viewport clamps inside the map and follows the player;
  * classic mode (architecture=False) is byte-for-byte unchanged: a 56x20 floor that
    renders whole (no camera), so the floor game and every existing test are untouched.

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_sandbox
"""
from runtime.game import Game, load_manifest


def main():
    m = load_manifest("examples/world.json")

    # --- classic mode unchanged ---
    g0 = Game(m, systems=[])
    assert (g0.level.w, g0.level.h) == (56, 20), "classic floor must stay 56x20"
    assert g0._camera() == (0, 0, 56, 20), "small level renders whole (no camera)"
    classic_view = g0.render().split("\n")[0]
    assert len(classic_view) == 56, "classic render is the full-width map"

    # --- sandbox builds one world ---
    g = Game(m, architecture=True, systems=[])
    assert g.level.w > 56 or g.level.h > 20, "sandbox world should be bigger than a floor"
    sx, sy = g.player.x, g.player.y
    assert g.level.walkable(sx, sy), "player starts on a walkable tile"
    assert g.actors, "sandbox must spawn content into the world"

    # --- region_at resolves by position from the tile->note map ---
    assert g._region_map, "sandbox must carry a tile->note region map"
    here = g.region_at(sx, sy)
    assert here and "name" in here, "region_at must resolve the district under the player"
    # every spawned enemy stands somewhere that maps to a named region
    for a in g.actors:
        r = g.region_at(a.x, a.y)
        assert r and r.get("name"), f"enemy at ({a.x},{a.y}) not in a named district"

    # --- the camera clamps inside the map and follows the player ---
    g.player.x, g.player.y = 0, 0
    cx, cy, vw, vh = g._camera()
    assert cx == 0 and cy == 0, "camera clamps at the top-left corner"
    g.player.x, g.player.y = g.level.w - 1, g.level.h - 1
    cx, cy, vw, vh = g._camera()
    assert cx + vw <= g.level.w and cy + vh <= g.level.h, "camera never scrolls past the edge"
    # a move in the middle of the map scrolls the camera
    g.player.x, g.player.y = g.level.w // 2, g.level.h // 2
    mid = g._camera()[:2]
    g.player.x += min(15, g.level.w - 1 - g.player.x)
    assert g._camera()[:2] != mid or g.level.w <= Game.VIEW_W, "camera follows the player"

    # --- no descent in the sandbox: floor stays put ---
    assert g.floor == 1, "sandbox has one world, not numbered floors"

    print(f"OK  sandbox: {g.level.w}x{g.level.h} world  actors={len(g.actors)}  "
          f"start-region={here['name']!r}  classic={g0.level.w}x{g0.level.h} unchanged")


if __name__ == "__main__":
    main()
