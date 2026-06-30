"""Drive the real Game through the DecaySystem and assert the contract holds.

We register the system on a real descent alongside ReactionSystem. We then:
  - emit ``actor_died`` and assert a corpse appears at the death tile;
  - confirm a missing / out-of-bounds pos is guarded (no phantom corpse);
  - rot the corpse turn by turn and assert it eventually disappears (ttl elapsed)
    WITHOUT fouling its own tile with acid (which would hide the corpse glyph);
  - assert a corpse shaves hp off a living actor standing on it (the miasma);
  - assert ``consume`` removes a corpse (True), then returns False on the now-empty tile;
  - check the ``%`` overlay lands on the corpse's floor cell and the status line.

Deterministic: the manifest seed is fixed.
"""
from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.decay import DecaySystem, _GLYPH, _CORPSE_TTL
from runtime.systems import System
from runtime.entities import Actor, make_enemy
from runtime.dungeon import free_floor_tiles


class Spy(System):
    """Records bus events so we can assert decay emits corpse_spawned."""
    name = "spy"

    def __init__(self):
        self.events = []

    def on_event(self, game, etype, data):
        self.events.append((etype, dict(data)))


def _clean_tile(game):
    """A floor tile occupied by nobody (player, stairs, or an actor)."""
    exclude = {(game.player.x, game.player.y), game.level.stairs}
    for a in game.actors:
        exclude.add((a.x, a.y))
    free = free_floor_tiles(game.level, exclude)
    assert free, "no free floor tile to host a corpse"
    return free[0]


def _check_corpse_spawned_event():
    """A death emits corpse_spawned on the bus (a separate game with a Spy)."""
    g = Game(load_manifest("examples/world.json"),
             systems=[ReactionSystem(), DecaySystem(), Spy()])
    decay, spy = g.system("decay"), g.system("spy")
    cx, cy = _clean_tile(g)
    spy.events.clear()
    dead = Actor(x=cx, y=cy, glyph="e", name="slain", hp=0, max_hp=4, atk=1)
    g.emit("actor_died", actor=dead, cause="melee", pos=(cx, cy))
    spawned = [d for (et, d) in spy.events if et == "corpse_spawned"]
    assert spawned, "decay did not emit corpse_spawned"
    assert spawned[-1].get("pos") == (cx, cy), "corpse_spawned carried the wrong pos"


def main():
    g = Game(load_manifest("examples/world.json"),
             systems=[ReactionSystem(), DecaySystem()])
    decay = g.system("decay")
    react = g.system("reactions")

    cx, cy = _clean_tile(g)

    # --- a death drops a corpse at the death tile ---
    assert decay.corpse_at(cx, cy) is False, "tile should start corpse-free"
    # a "simple obj" dead actor (could equally be a make_enemy spec)
    dead = make_enemy({"name": "slain", "archetype": "beast", "tier": 1,
                       "sourceNoteId": "grocery list"}, cx, cy)
    g.emit("actor_died", actor=dead, cause="melee", pos=(cx, cy))
    assert decay.corpse_at(cx, cy) is True, "corpse not created on actor_died"
    assert decay.corpses[(cx, cy)] == _CORPSE_TTL, "corpse should start at full ttl"

    # --- a missing / out-of-bounds pos is guarded (no phantom corpse) ---
    before = len(decay.corpses)
    g.emit("actor_died", actor=dead, cause="melee", pos=None)
    g.emit("actor_died", actor=dead, cause="melee", pos=(-9, -9))
    g.emit("actor_died", actor=dead, cause="melee", pos=(10 ** 6, 10 ** 6))
    assert len(decay.corpses) == before, "guard failed: a bad pos created a corpse"

    # --- rot: with nobody underfoot the corpse just rots in plain view. It must NOT
    #     foul its OWN tile with acid (that used to hide the '%' beneath a ':'). ---
    g.player.x, g.player.y = -5, -5          # park the player off every tile
    g.actors = []
    react.props, react.fire_life = {}, {}    # clean substrate to isolate decay's effect
    ttl0 = decay.corpses[(cx, cy)]
    for _ in range(ttl0 + 2):
        decay.on_player_act(g)
        assert "acid" not in react.props_at(cx, cy), \
            "a rotting corpse must NOT seep acid onto its own tile (it would hide the corpse)"
    assert decay.corpse_at(cx, cy) is False, "corpse should be gone after its ttl elapsed"

    # --- consume: a scavenger eats a corpse (True), then nothing remains (False) ---
    g.emit("actor_died", actor=dead, cause="predation", pos=(cx, cy))
    assert decay.corpse_at(cx, cy) is True
    assert decay.consume(cx, cy) is True, "consume should remove an existing corpse"
    assert decay.consume(cx, cy) is False, "consume on an empty tile should be False"
    assert decay.corpse_at(cx, cy) is False

    # --- light miasma: harms a living actor on the corpse instead of seeping ---
    g.emit("actor_died", actor=dead, cause="melee", pos=(cx, cy))
    standing = make_enemy({"name": "standing", "archetype": "beast", "tier": 2,
                           "sourceNoteId": "grocery list"}, cx, cy)
    g.actors = [standing]
    hp0 = standing.hp
    decay.on_player_act(g)
    assert standing.hp == hp0 - 1, f"miasma should shave 1 hp (took {hp0 - standing.hp})"

    # --- overlay draws % on the corpse's floor cell; status line counts corpses ---
    g.actors = []
    grid = [row[:] for row in g.level.tiles]
    decay.render_overlay(g, grid)
    if g.level.tiles[cy][cx] == ".":
        assert grid[cy][cx] == _GLYPH, "overlay did not draw the corpse glyph on a floor cell"
    assert decay.status_line(g) == f"Corpses: {len(decay.corpses)}", decay.status_line(g)

    # --- a death emits corpse_spawned on the bus ---
    _check_corpse_spawned_event()

    print("OK")


if __name__ == "__main__":
    main()
