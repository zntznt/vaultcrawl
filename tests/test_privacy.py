"""The #nogame / #private opt-out: a marked note never reaches the world."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from vaultcrawl.bake import bake


def _vault(tmp):
    (tmp / "Open Thought.md").write_text(
        "A public note. Links [[Secret Journal]] and [[Also Hidden]] and [[Friend]].\n"
        "#philosophy\n- [ ] a public todo\n")
    (tmp / "Friend.md").write_text("Also public. [[Open Thought]] #philosophy\n")
    (tmp / "Secret Journal.md").write_text(
        "#private/journal\nReal names live here. Alice Bob Carol.\n")
    (tmp / "Also Hidden.md").write_text(
        "---\ntags: [nogame]\n---\nAn embarrassing draft.\n")


def test_marked_notes_never_reach_the_manifest():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _vault(tmp)
        out = tmp / "world.json"
        bake(str(tmp), str(out))
        raw = out.read_text()
        m = json.loads(raw)
        assert "secret journal" not in m["graph"]["nodes"]
        assert "also hidden" not in m["graph"]["nodes"]
        assert "open thought" in m["graph"]["nodes"]
        # not the ids only: the marked notes' CONTENT must be absent everywhere
        for leak in ("Alice", "Bob", "Carol", "embarrassing", "Secret Journal"):
            assert leak not in raw, f"{leak!r} leaked into world.json"


if __name__ == "__main__":
    test_marked_notes_never_reach_the_manifest()
    print("ok test_marked_notes_never_reach_the_manifest")
