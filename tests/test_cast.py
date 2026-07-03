"""Player-driven sigil casting: manual timing beats the passive triggers."""
from __future__ import annotations

from runtime.entities import Actor
from runtime.game import Game, load_manifest
from runtime.sigils import SigilSystem


def _game():
    return Game(load_manifest("examples/world.json"), systems=[SigilSystem()])


def _sigil(ability, durability=2):
    return {"note": "t", "role": "", "ability": ability, "base": ability,
            "durability": durability}


def _foe(x, y):
    return Actor(x=x, y=y, glyph="s", name="test foe", hp=5, max_hp=5, atk=1)


def _open_run(g, n=4):
    """Leftmost horizontal run of n walkable tiles (for staged positions)."""
    for y in range(g.level.h):
        for x in range(g.level.w - n):
            if all(g.level.walkable(x + i, y) for i in range(n)):
                return x, y
    raise AssertionError("no open run on the sample floor")


def test_cast_recall_heals_when_hurt_refuses_when_whole():
    g = _game()
    sigs = g.system("sigils")
    sigs.slots = [_sigil("Recall")]
    assert not sigs.cast(g, 0), "full HP: Recall should stay quiet"
    assert sigs.slots[0]["durability"] == 2
    g.player.hp = 10
    assert sigs.cast(g, 0)
    assert g.player.hp == 16 and sigs.slots[0]["durability"] == 1


def test_cast_ward_shoves_a_single_foe():
    g = _game()
    sigs = g.system("sigils")
    sigs.slots = [_sigil("Ward")]
    x, y = _open_run(g)
    g.player.x, g.player.y = x, y
    foe = _foe(x + 1, y)
    g.actors = [foe]                     # one adjacent foe: passive would need two
    assert sigs.cast(g, 0)
    assert (foe.x, foe.y) != (x + 1, y), "the foe should be shoved"


def test_cast_phase_blinks_without_being_boxed():
    g = _game()
    sigs = g.system("sigils")
    sigs.slots = [_sigil("Phase")]
    g.actors = []
    before = (g.player.x, g.player.y)
    assert sigs.cast(g, 0)
    assert (g.player.x, g.player.y) != before


def test_cast_echo_refuses():
    g = _game()
    sigs = g.system("sigils")
    sigs.slots = [_sigil("Echo", durability=1)]
    assert not sigs.cast(g, 0)
    assert sigs.slots[0]["durability"] == 1


def test_cast_rally_needs_a_foe():
    g = _game()
    sigs = g.system("sigils")
    sigs.slots = [_sigil("Rally")]
    g.actors = []
    assert not sigs.cast(g, 0)
    assert sigs.slots[0]["durability"] == 2
    g.actors = [_foe(1, 1)]
    assert sigs.cast(g, 0)
    assert not g.actors, "the rallied foe stands aside"


def test_forge_autopilot_can_be_disengaged():
    from runtime.forge import ForgeSystem
    from runtime.salvage import SalvageSystem, inv
    g = Game(load_manifest("examples/world.json"),
             systems=[SigilSystem(), SalvageSystem(), ForgeSystem()])
    forge = g.system("forge")
    inv(g.player).add({m: 9 for m in forge.cost(g)})   # plenty of matter
    forge.auto = False
    slots_before = len(g.system("sigils").slots)
    forge.on_player_act(g)
    assert len(g.system("sigils").slots) == slots_before, "no craft while auto is off"
    assert forge.forge(g), "manual forge still works"


if __name__ == "__main__":
    for fn in (test_cast_recall_heals_when_hurt_refuses_when_whole,
               test_cast_ward_shoves_a_single_foe,
               test_cast_phase_blinks_without_being_boxed,
               test_cast_echo_refuses, test_cast_rally_needs_a_foe,
               test_forge_autopilot_can_be_disengaged):
        fn()
        print(f"ok {fn.__name__}")
