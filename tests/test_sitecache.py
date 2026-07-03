"""The grown-world cache: instant relaunch, identical world, stale-safe."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from runtime.game import Game, load_manifest


def test_cache_reproduces_the_world_exactly():
    m = load_manifest("examples/world.json")
    with tempfile.TemporaryDirectory() as d:
        cache = str(Path(d) / "site.json")
        a = Game(m, sandbox=True, site_cache=cache)
        assert Path(cache).exists()
        b = Game(m, sandbox=True, site_cache=cache)
        assert a.level.tiles == b.level.tiles
        assert a.room_notes == b.room_notes and a._motifs == b._motifs
        assert [(x.name, x.x, x.y) for x in a.actors] == \
               [(x.name, x.x, x.y) for x in b.actors]


def test_stale_cache_is_ignored():
    m = load_manifest("examples/world.json")
    with tempfile.TemporaryDirectory() as d:
        cache = Path(d) / "site.json"
        cache.write_text(json.dumps({"seed": "not-this-world"}))
        g = Game(m, sandbox=True, site_cache=str(cache))
        assert g.room_notes, "a stale cache regrows instead of loading"
        assert json.loads(cache.read_text())["seed"] == m["seed"], \
            "and the fresh growth replaces it"


if __name__ == "__main__":
    for fn in (test_cache_reproduces_the_world_exactly, test_stale_cache_is_ignored):
        fn()
        print(f"ok {fn.__name__}")
