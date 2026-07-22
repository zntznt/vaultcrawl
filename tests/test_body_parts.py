"""Body-part injury model tests.

Run: python3 -m tests.test_body_parts
"""
from runtime.game import Game, load_manifest
from runtime.entities import make_enemy, make_player
from runtime.body_parts import (init_body, hit_part, damage_part, heal_body,
                                 sync_hp, is_immobilized, BodySystem)
import random


def test_init_body():
    p = make_player(0, 0)
    init_body(p)
    assert p.body["head"]["hp"] == 8
    assert p.body["torso"]["hp"] == 16
    assert p.body["legs"]["hp"] == 8
    assert p.hp == 32
    assert p.max_hp == 32


def test_enemy_init():
    e = make_enemy({"tier": 1, "archetype": "warden", "name": "goblin",
                    "sourceNoteId": "x"}, 1, 1)
    init_body(e)
    total = sum(v["hp"] for v in e.body.values())
    assert total == e.hp == e.max_hp


def test_hit_distribution():
    p = make_player(0, 0)
    init_body(p)
    rng = random.Random(42)
    parts = [hit_part(p, rng) for _ in range(200)]
    heads = parts.count("head")
    torsos = parts.count("torso")
    legs = parts.count("legs")
    assert torsos >= heads, f"torso {torsos} should be most common, heads {heads}"
    assert torsos >= legs, f"torso {torsos} should be most common, legs {legs}"


def test_damage_part():
    p = make_player(0, 0)
    init_body(p)
    damage_part(p, "head", 4)
    assert p.body["head"]["hp"] == 4
    assert p.hp == 28


def test_leg_break_immobilizes():
    p = make_player(0, 0)
    init_body(p)
    assert not is_immobilized(p)
    damage_part(p, "legs", 8)
    assert is_immobilized(p)
    assert p.speed == 0


def test_heal_restores_legs():
    p = make_player(0, 0)
    init_body(p)
    damage_part(p, "legs", 8)
    assert is_immobilized(p)
    heal_body(p, 3)
    assert not is_immobilized(p)
    assert p.speed > 0


def test_heal_worst_first():
    p = make_player(0, 0)
    init_body(p)
    damage_part(p, "head", 4)
    damage_part(p, "legs", 6)
    # legs at 2/8 (25%), head at 4/8 (50%) — legs should heal first
    heal_body(p, 3)
    assert p.body["legs"]["hp"] == 5  # got 3 of the 3 healing


def test_body_system_registers():
    g = Game(load_manifest("examples/world.json"), systems=[BodySystem()])
    bs = g.system("body")
    assert bs is not None
    bs.on_floor_enter(g)
    assert getattr(g.player, "body", None) is not None


def main():
    test_init_body()
    test_enemy_init()
    test_hit_distribution()
    test_damage_part()
    test_leg_break_immobilizes()
    test_heal_restores_legs()
    test_heal_worst_first()
    test_body_system_registers()
    print("OK")


if __name__ == "__main__":
    main()
