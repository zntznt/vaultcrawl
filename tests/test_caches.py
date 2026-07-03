"""Caches: place-typed contents, telegraphed peril, crafting geography."""
from __future__ import annotations

from runtime.caches import CacheSystem, ROLE_PERK
from runtime.game import Game, load_manifest
from runtime.salvage import SalvageSystem, inv
from runtime import quality


def _game():
    return Game(load_manifest("examples/world.json"), sandbox=True,
                systems=[SalvageSystem(), CacheSystem()])


def test_caches_hold_the_places_own_matter():
    g = _game()
    cs = g.system("caches")
    assert cs.caches, "the sample world should surface caches"
    for pos, c in cs.caches.items():
        idx = g.room_at(*pos)
        assert idx is not None and g.room_notes[idx] == c["note"], \
            "a cache sits in its own note's room"
        assert c["material"] == cs.material_of(g, c["note"])
    mats = {c["material"] for c in cs.caches.values()}
    assert len(mats) > 1, f"places offer DISTINCT matter, got {mats}"


def test_searching_yields_and_ages_season():
    g = _game()
    cs = g.system("caches")
    pos, c = sorted(cs.caches.items())[0]
    g.player.x, g.player.y = pos
    hp = g.player.hp
    cs.on_player_act(g)
    bag = inv(g.player)
    assert bag.comp.get(c["material"], 0) >= 2
    if c["aged"]:
        assert bag.quality_of(c["material"]) == 2, "old thoughts season their matter"
    if c["peril"]:
        assert g.player.hp == hp - 2, "a warded cache bites"
    assert pos not in cs.caches, "one search each"


def test_peril_is_telegraphed_before_touching():
    g = _game()
    cs = g.system("caches")
    warded = next(((p, c) for p, c in cs.caches.items() if c["peril"]), None)
    if warded is None:   # this seed warded nothing: the describe path still works
        pos, c = sorted(cs.caches.items())[0]
        g.player.x, g.player.y = pos
        assert any(c["material"] in line for line in cs.describe_near(g))
        return
    pos, c = warded
    g.player.x, g.player.y = pos
    assert any("humming" in line for line in cs.describe_near(g)), \
        "the ward is legible before you commit"


def test_crafting_has_geography():
    g = _game()
    cs = g.system("caches")
    nodes = g.m["graph"]["nodes"]
    by_material: dict = {}
    for nid, node in nodes.items():
        perk = ROLE_PERK.get(node.get("role", ""))
        if perk:
            by_material.setdefault(cs.material_of(g, nid), set()).add(perk)
    assert by_material, "some place matter should carry affinities"
    for mat, perks in by_material.items():
        assert quality.ADDITIVE_AFFINITY.get(mat) in perks, \
            f"{mat} should steer one of {perks}"


if __name__ == "__main__":
    for fn in (test_caches_hold_the_places_own_matter,
               test_searching_yields_and_ages_season,
               test_peril_is_telegraphed_before_touching,
               test_crafting_has_geography):
        fn()
        print(f"ok {fn.__name__}")
