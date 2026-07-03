"""Corpus layer: chains built from the vault's own words, woven back at play time."""
from __future__ import annotations

import json
import random

from runtime.game import Game, load_manifest
from runtime.marginalia import MarginaliaSystem, weave


def _manifest():
    return load_manifest("examples/world.json")


def test_corpus_baked_and_deterministic():
    from vaultcrawl.analyze import analyze
    from vaultcrawl.corpus import build_corpus
    from vaultcrawl.ingest import load_vault
    v = load_vault("sample_vault")
    an = analyze(v)
    a, b = build_corpus(v, an), build_corpus(v, an)
    assert a == b and a
    assert json.dumps(a) == json.dumps(b)


def test_weave_uses_only_the_vaults_words():
    comm = next(iter(_manifest()["corpus"].values()))
    vocab = set()
    for prefix, nexts in comm["chain"].items():
        vocab.update(prefix.split(" "))
        vocab.update(nexts)
    nid = next(iter(comm["starters"]))
    line = weave(comm, nid, random.Random(1))
    assert line
    assert all(w in vocab for w in line.rstrip(".").split(" ") if w), line


def test_weave_is_seeded():
    comm = next(iter(_manifest()["corpus"].values()))
    nid = next(iter(comm["starters"]))
    assert weave(comm, nid, random.Random(7)) == weave(comm, nid, random.Random(7))


def test_marginalia_lands_in_its_notes_room_and_reads():
    g = Game(_manifest(), systems=[MarginaliaSystem()])
    ms = g.system("marginalia")
    assert ms.ground, "sample floor should surface at least one marginalia mark"
    for pos, nid in ms.ground.items():
        room = g.room_of_note(nid)
        assert room is not None and room.contains(*pos)
    (x, y), _ = next(iter(ms.ground.items()))
    g.player.x, g.player.y = x, y
    ms.on_player_act(g)
    assert any(m.startswith("Marginalia, in your own hand:") for m in g.messages)


def test_lines_keep_prose_and_drop_structure():
    from vaultcrawl.corpus import _lines
    body = ("# How this folder is organized\n"
            "Reference (root): Hardware Inventory\n"
            "- [ ] a task item\n"
            "I think the retention curve matters more than the deck size.\n"
            "This gave the cluster near-infinite failover capacity.\n")
    got = _lines(body)
    assert "I think the retention curve matters more than the deck size." in got
    assert "This gave the cluster near-infinite failover capacity." in got
    assert not any("folder is organized" in ln for ln in got), "headings are not voice"


def test_weave_prefers_intact_sentences():
    # recognition is the payload: with lines present, most weaves are VERBATIM
    comm = {"chain": {"a b": ["c."]}, "starters": {"n1": ["a b"]},
            "lines": {"n1": ["My own sentence, written whole."]}}
    outs = {weave(comm, "n1", random.Random(i)) for i in range(20)}
    assert "My own sentence, written whole." in outs, "intact lines must dominate"
    assert any(o != "My own sentence, written whole." for o in outs), \
        "the dream-garbled chain walk stays as the uncanny minority"


def test_weave_walk_leans_home():
    # at a fork, the walk favours the successor from the SPEAKER'S own sentences,
    # so two notes sharing a community chain still garble distinctly
    comm = {"chain": {"the door": ["opens.", "rots."], "door opens.": [], "door rots.": []},
            "starters": {"n1": ["the door"]},
            "lines": {"n1": ["My door opens quietly, always."]}}
    verbatim = "My door opens quietly, always."
    woven = [w for w in (weave(comm, "n1", random.Random(i)) for i in range(300))
             if w != verbatim]
    assert woven, "some walks must take the chain path"
    opens = sum(1 for w in woven if "opens" in w)
    rots = sum(1 for w in woven if "rots" in w)
    assert opens > rots * 1.5, f"the walk should lean home ({opens} vs {rots})"


def test_chain_is_prose_not_structure():
    from vaultcrawl.corpus import build_corpus

    class _N:
        def __init__(self, body):
            self.body = body

    class _V:
        notes = {"a": _N("# How this folder is organized\n"
                         "Reference (root): Hardware Inventory\n"
                         "The lantern still burns in the far room.\n"
                         "It burns because nobody wrote an ending.\n")}

    class _A:
        community = {"a": 0}

    comm = build_corpus(_V(), _A())["0"]
    joined = " ".join(comm["chain"])
    assert "folder is" not in joined and "Reference" not in joined, \
        "heading/structure text must not enter the chain when prose exists"
    assert "lantern still" in joined


def test_marginalia_inert_without_corpus():
    m = _manifest()
    del m["corpus"]
    g = Game(m, systems=[MarginaliaSystem()])
    assert not g.system("marginalia").ground


if __name__ == "__main__":
    for fn in (test_corpus_baked_and_deterministic, test_weave_uses_only_the_vaults_words,
               test_weave_is_seeded, test_marginalia_lands_in_its_notes_room_and_reads,
               test_lines_keep_prose_and_drop_structure, test_weave_prefers_intact_sentences,
               test_weave_walk_leans_home, test_chain_is_prose_not_structure,
               test_marginalia_inert_without_corpus):
        fn()
        print(f"ok {fn.__name__}")
