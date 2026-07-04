"""Procedural creature portraits — Spore-style faces assembled from parts, one per
note, deterministic. The curses render is elsewhere; the ASSEMBLY is tested here."""
from __future__ import annotations

from runtime.game import Game, load_manifest
from runtime.portrait import _SILHOUETTE, portrait


def test_every_archetype_builds_a_rectangular_face():
    for arch in _SILHOUETTE:
        face = portrait(arch, "note", tier=1, quality=0)
        assert face, f"{arch} produced no portrait"
        widths = {len(r) for r in face}
        assert len(widths) == 1, f"{arch} portrait is ragged: {widths}"


def test_same_note_same_face_different_notes_differ():
    a = portrait("scribe", "Memento Mori")
    b = portrait("scribe", "Memento Mori")
    c = portrait("scribe", "Zettelkasten")
    assert a == b, "a creature's face is deterministic"
    assert a != c, "different notes grow different faces"


def test_traits_add_parts():
    plain = portrait("warden", "n", tier=1, quality=0, damage="")
    crowned = portrait("warden", "n", tier=1, quality=4, damage="")
    aura = portrait("warden", "n", tier=4, quality=0, damage="flame")
    assert len(crowned) > len(plain), "high quality adds a crown row"
    assert max(len(r) for r in aura) > max(len(r) for r in plain), \
        "a high-tier elemental creature is framed by its aura"


def test_unknown_archetype_falls_back():
    face = portrait("no-such-thing", "n")
    assert face and len({len(r) for r in face}) == 1


def test_creature_look_resolves_from_the_manifest():
    g = Game(load_manifest("examples/world.json"))
    foe = next((a for a in g.actors if getattr(a, "source", "")), None)
    if foe is None:
        return
    arch, dmg = g.creature_look(foe)
    assert isinstance(arch, str) and arch, "every creature resolves to an archetype"
    assert isinstance(dmg, str)
    # and that archetype builds a face
    assert portrait(arch, foe.source, foe.tier, foe.quality, dmg)


if __name__ == "__main__":
    for fn in (test_every_archetype_builds_a_rectangular_face,
               test_same_note_same_face_different_notes_differ,
               test_traits_add_parts, test_unknown_archetype_falls_back,
               test_creature_look_resolves_from_the_manifest):
        fn()
        print(f"ok {fn.__name__}")
