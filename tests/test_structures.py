"""Drive the real Game through the StructureSystem and assert the ecology contract.

Structures are allegiance-blind reactive objects: pressure plates fire under
*any* actor (player, faction monster, or wild critter) and crystal clusters burst
when fire or a live shock reaches them. We run a real descent with the reactions
substrate present, then exercise each behaviour deterministically:

  * traps & crystals are placed on floor tiles (not on the player/stairs) on enter;
  * a spike plate damages whatever stands on it and the plate spends (reverts);
  * a lethal spike on a monster routes the death through ``game.kill`` (-> the bus);
  * a gas plate writes ``acid`` onto the plate + neighbours via the reactions API;
  * a crystal whose tile is ignited detonates, is removed, and seeds props nearby;
  * ``hazard_tiles`` reports exactly the armed-trap positions;
  * ``render_overlay`` draws ``&`` / ``_`` onto floor cells only.

Deterministic across runs (seeded placement + fixed-position set-ups). Prints OK.
"""
from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.structures import StructureSystem, SPIKE_DMG, DET_DMG
from runtime.systems import System
from runtime.entities import make_enemy


class Spy(System):
    """Records every bus event so we can assert deaths route through game.kill."""
    name = "spy"

    def __init__(self):
        self.events = []

    def on_event(self, game, etype, data):
        self.events.append((etype, dict(data)))


def _new_game():
    return Game(load_manifest("examples/world.json"),
                systems=[ReactionSystem(), StructureSystem(), Spy()])


def _enemy(game, x, y, hp=None):
    """A faction monster placed at (x, y); optional explicit hp for lethality tests."""
    en = make_enemy(game.m["enemies"][0], x, y)
    if hp is not None:
        en.hp = hp
    return en


def _free_tile(game, used):
    """A floor tile that is not the player start, the stairs, or in `used`."""
    px, py = game.player.x, game.player.y
    for y in range(game.level.h):
        for x in range(game.level.w):
            if game.level.tiles[y][x] == "." and (x, y) not in used \
                    and (x, y) != (px, py) and (x, y) != game.level.stairs:
                return (x, y)
    raise AssertionError("no free floor tile available")


def _check_placement_and_overlay():
    g = _new_game()
    s = g.system("structures")

    # placed on floor enter (Game.__init__ -> descend -> on_floor_enter)
    assert s.traps, "no pressure plates placed on floor enter"
    assert s.crystals, "no crystal clusters placed on floor enter"

    forbidden = {(g.player.x, g.player.y), g.level.stairs}
    for pos in list(s.traps) + list(s.crystals):
        x, y = pos
        assert g.level.tiles[y][x] == ".", f"structure off the floor at {pos}"
        assert pos not in forbidden, f"structure on the player/stairs at {pos}"
    # traps and crystals never share a tile
    assert not (set(s.traps) & set(s.crystals)), "a trap and crystal overlap"

    # hazard_tiles == armed traps exactly
    assert set(s.hazard_tiles(g)) == set(s.traps), "hazard_tiles != armed traps"
    assert s.hazard_tiles(g), "hazard_tiles empty despite armed traps"

    # overlay draws & / _ onto floor cells only (render on a clean tile grid)
    grid = [row[:] for row in g.level.tiles]
    s.render_overlay(g, grid)
    cpos = next(iter(s.crystals))
    tpos = next(iter(s.traps))
    assert grid[cpos[1]][cpos[0]] == "&", "crystal glyph not drawn"
    assert grid[tpos[1]][tpos[0]] == "_", "armed-trap glyph not drawn"
    for y in range(len(grid)):
        for x in range(len(grid[y])):
            if grid[y][x] in ("&", "_"):
                assert g.level.tiles[y][x] == ".", "overlay drew on a non-floor cell"

    assert s.status_line(g).startswith("Traps:"), s.status_line(g)


def _check_spike_damage_and_spend():
    """A spike plate hurts whatever stands on it and then reverts to floor."""
    g = _new_game()
    s = g.system("structures")
    tile = _free_tile(g, set(s.traps) | set(s.crystals))
    s.traps[tile] = "spike"
    mon = _enemy(g, *tile)               # full-hp monster: survives, plate spends
    g.actors = [mon]
    hp0 = mon.hp
    s.on_player_act(g)
    assert mon.hp == hp0 - SPIKE_DMG, f"spike dealt {hp0 - mon.hp}, expected {SPIKE_DMG}"
    assert tile not in s.traps, "plate did not spend after firing"
    assert mon in g.actors, "non-lethal spike wrongly removed the monster"
    assert any("pressure plate clicks" in m for m in g.messages), "no plate-click log"


def _check_spike_lethal_routes_through_kill():
    """A lethal spike removes the monster via game.kill -> actor_died on the bus."""
    g = _new_game()
    s = g.system("structures")
    spy = g.system("spy")
    tile = _free_tile(g, set(s.traps) | set(s.crystals))
    s.traps[tile] = "spike"
    mon = _enemy(g, *tile, hp=2)         # < SPIKE_DMG -> dies
    g.actors = [mon]
    spy.events.clear()
    s.on_player_act(g)
    assert mon not in g.actors, "lethal spike did not remove the monster"
    deaths = [d for (et, d) in spy.events if et == "actor_died"]
    assert deaths, "no actor_died emitted for the trap kill"
    assert deaths[-1]["actor"] is mon and deaths[-1]["cause"] == "trap", \
        f"death not routed as a trap kill: {deaths[-1]}"


def _check_gas_writes_acid():
    """A gas plate writes acid onto the plate + its floor neighbours via reactions."""
    g = _new_game()
    s = g.system("structures")
    r = g.system("reactions")
    tile = _free_tile(g, set(s.traps) | set(s.crystals))
    s.traps[tile] = "gas"
    g.actors = [_enemy(g, *tile)]        # an actor must stand on the plate to fire it
    s.on_player_act(g)
    assert tile not in s.traps, "gas plate did not spend"
    assert "acid" in r.props_at(*tile), "gas burst left no acid on the plate"


def _check_crystal_detonation():
    """Igniting a crystal's tile detonates it; it is removed and seeds nearby props."""
    g = _new_game()
    s = g.system("structures")
    r = g.system("reactions")
    # a fresh crystal on a tile with at least one orthogonal floor neighbour
    tile = _free_tile(g, set(s.traps) | set(s.crystals))
    neighbours = [(tile[0] + dx, tile[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
    floor_nbrs = [n for n in neighbours if s._is_floor(g, n)]
    assert floor_nbrs, "test tile has no floor neighbour"
    s.crystals = {tile: 0}
    r.ignite(*tile)                      # fire on the crystal's tile
    s.on_player_act(g)
    assert tile not in s.crystals, "crystal on fire did not detonate"
    assert any("crystal detonates" in m.lower() for m in g.messages), "no detonation log"
    seeded = any(r.props_at(*n) for n in floor_nbrs)
    assert seeded, "detonation seeded no reactive props on a neighbour"


def main():
    _check_placement_and_overlay()
    _check_spike_damage_and_spend()
    _check_spike_lethal_routes_through_kill()
    _check_gas_writes_acid()
    _check_crystal_detonation()
    print("OK")


if __name__ == "__main__":
    main()
