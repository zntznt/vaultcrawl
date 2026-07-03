"""Yume-Nikki effects: ways of being from your notes — exploration, never power."""
from __future__ import annotations

from runtime.effects import EFFECTS, EffectSystem, effect_for
from runtime.entities import Actor
from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem
from runtime.reactions import ReactionSystem


def _game(*systems):
    return Game(load_manifest("examples/world.json"), sandbox=True,
                systems=[EffectSystem(), *systems])


def test_effect_is_a_note_taken_by_exploring():
    g = _game()
    eff = g.system("effects")
    assert g._wild_structs, "the world has wild landmarks to commune with"
    (lx, ly), nid = sorted(g._wild_structs.items())[0]
    g.player.x, g.player.y = lx, ly
    assert g.commune_landmark() is True
    assert eff.collected.get(effect_for(nid)) == nid
    assert eff.worn == effect_for(nid), "the first effect is worn automatically"


def test_effects_never_touch_combat_stats():
    # the roster is pure perception/traversal/mood — no atk/def/hp verbs anywhere
    src = open("runtime/effects.py").read()
    for banned in (".atk", ".defense", "max_hp +", "hp +="):
        assert banned not in src, f"an effect must not touch {banned}"


def test_lantern_widens_sight():
    g = _game(KnowledgeSystem())
    eff, kn = g.system("effects"), g.system("knowledge")
    base = kn._sight(g)   # surface radius (generous for wandering)
    eff.collected = {"lantern": "n"}
    eff.wear("lantern")
    assert kn._sight(g) > base, "the lantern effect widens sight further"


def test_small_and_hush_make_you_unbothered():
    g = _game()
    eff = g.system("effects")
    foe = Actor(x=1, y=1, glyph="s", name="t", hp=5, max_hp=5, atk=1)
    foe.faction = "f1"
    assert g.hostile(g.player, foe), "normally a rival is hostile"
    eff.collected = {"small": "n"}
    eff.wear("small")
    assert not g.hostile(g.player, foe), "'small' (unseen) stops all menace"
    eff.collected["hush"] = "n"
    eff.wear("hush")
    assert not g.hostile(g.player, foe), "'hush' calms too"


def test_drift_negates_hazard_harm():
    g = _game(ReactionSystem())
    eff = g.system("effects")
    eff.collected = {"drift": "n"}
    eff.wear("drift")
    assert eff.can_drift(g)


def test_effects_vary_across_notes():
    kinds = {effect_for(f"note{i}") for i in range(30)}
    assert len(kinds) >= 4, "notes should grant a spread of effects, not all one"
    assert kinds <= set(EFFECTS)


if __name__ == "__main__":
    for fn in (test_effect_is_a_note_taken_by_exploring,
               test_effects_never_touch_combat_stats, test_lantern_widens_sight,
               test_small_and_hush_make_you_unbothered, test_drift_negates_hazard_harm,
               test_effects_vary_across_notes):
        fn()
        print(f"ok {fn.__name__}")
