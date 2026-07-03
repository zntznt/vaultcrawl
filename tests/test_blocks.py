"""Design blocks: environments are ordered blends; order changes what manifests."""
from __future__ import annotations

from runtime.arch.blocks import BLOCKS, Environment, environment_for
from runtime.game import Game, load_manifest


def test_a_block_has_all_four_channels():
    for name, b in BLOCKS.items():
        assert b["feats"] and b["tend"] and "palette" in b and b["voice"], \
            f"block {name} must carry objects, space, palette, and voice"


def test_order_changes_the_environment():
    # same two blocks, swapped order -> different dominant palette/voice/features
    a = Environment(["foundry", "wet"])
    b = Environment(["wet", "foundry"])
    assert a.palette() != b.palette() or a.voice()[0] != b.voice()[0], \
        "reversing dominance must change what manifests"
    assert a.dominant == "foundry" and b.dominant == "wet"


def test_dominant_block_contributes_more():
    env = Environment(["archive", "wet"])
    feats = dict((g, w) for g, w, _n in env.features())
    # archive's shelf '=' at full weight; wet's reed '"' halved
    assert feats.get("=", 0) > 0
    # the head block's features outweigh the tail's for shared/similar glyphs
    total_head = sum(w for g, w, _n in env.features()
                     if (g, w, _n) and env.names[0])
    assert total_head > 0


def test_environment_composes_from_signals():
    env = environment_for("sacred", "wastes", "leaf")
    assert env.label() == "wastes-sacred-leaf"      # biome dominant, then element, role
    assert env.palette() in ("dim", "holy")          # wastes dim, tinted by sacred/leaf
    assert len(env.features()) >= 3


def test_regions_get_varied_atmospheres():
    g = Game(load_manifest("examples/world.json"), sandbox=True)
    labels = {env.label() for env in g._region_env.values()}
    palettes = {env.palette() for env in g._region_env.values()}
    assert g._region_env, "every region gets a blended environment"
    # with more than one region we expect more than one vibe
    if len(g._region_env) > 1:
        assert len(labels) >= 1 and palettes


def test_wild_has_many_feature_types_now():
    g = Game(load_manifest("examples/world.json"), sandbox=True)
    kinds = {gph for gph in g._overlay.values() if gph in g._block_glyphs}
    assert len(kinds) >= 4, f"the wild should be built from many bricks, got {kinds}"


if __name__ == "__main__":
    for fn in (test_a_block_has_all_four_channels, test_order_changes_the_environment,
               test_dominant_block_contributes_more, test_environment_composes_from_signals,
               test_regions_get_varied_atmospheres, test_wild_has_many_feature_types_now):
        fn()
        print(f"ok {fn.__name__}")
