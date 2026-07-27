"""The bake must be a pure function of the vault, and nothing else.

`CLAUDE.md` invariant 4 is "determinism first", and `ingest.py` has always promised that
"copying the vault to another machine yields the identical world". That promise was false.
`activity` was min-max normalised from file modification times, and `git clone` rewrites
every mtime to checkout time, so what survived was the order git happened to write the
files in. Measured on this repo: a 5.3 millisecond spread, amplified by min-max to the full
0..1 range.

It was not cosmetic. `activity` is read back out of the manifest by six mechanical
consumers, among them `runtime/game.py`'s `n = 2 + floor//4 + round(activity * 2)`, the
number of enemies on every floor. It also reached `_archetype_for`, and archetype picks
the creature's glyph, and glyph picks its sense profile: a `scribe` is a mind_seer that
senses thought through walls, a `gloom` is plain sighted. A file timestamp decided what a
creature could perceive.

The tests below are ordered by how much they would have caught:

  * `test_the_committed_world_is_reproducible` is the one that was impossible before. It
    collapses three worlds into one: the committed artifact, the world 149 test call sites
    validate against, and the world the demo page publishes.
  * `test_the_same_vault_bakes_the_same_world_anywhere` is the direct F6 regression.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_vault"
COMMITTED = ROOT / "examples" / "world.json"


def _bake(vault, out, *extra):
    """Run the real CLI, so the flags and defaults under test are the shipped ones."""
    proc = subprocess.run(
        [sys.executable, "-m", "vaultcrawl.bake", str(vault), "-o", str(out), "-q", *extra],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"bake failed: {proc.stderr[-2000:]}"
    return json.loads(pathlib.Path(out).read_text(encoding="utf-8"))


def _stamp(vault, when, spread=1.0, reverse=False):
    """Set mtimes to a SPREAD around `when`, not a single value.

    Stamping every file identically looks like the harsher test and is actually the
    weakest one: min-max normalisation divides by the span, so a span of zero sends every
    note to the same activity in both arms and the comparison passes no matter what the
    code does. A clone produces a small spread in filesystem write order, which is exactly
    what discriminates, so that is what these reproduce. `reverse` flips the order between
    two arms, which is the strongest available stand-in for "a different machine wrote
    these files in a different order".
    """
    paths = sorted(pathlib.Path(vault).rglob("*.md"), reverse=reverse)
    for i, path in enumerate(paths):
        t = when + i * spread
        os.utime(path, (t, t))


# --------------------------------------------------------------- the whole point

def test_the_committed_world_is_reproducible(tmp_path):
    """Baking the sample vault reproduces the committed manifest, byte for byte.

    This check could not be written before: the committed file carried the author's
    machine in it, both as `activity` derived from their mtimes and literally as
    `"vaultPath": "/Users/.../vaultcrawl/sample_vault"`. CI now runs this, which is what
    keeps the demo page, the tests, and the artifact describing the same game.
    """
    fresh = tmp_path / "fresh.json"
    _bake(SAMPLE, fresh)
    assert fresh.read_bytes() == COMMITTED.read_bytes(), (
        "a fresh bake no longer matches examples/world.json; if that is intended, "
        "regenerate it in the same commit and re-measure the balance baseline")


def test_the_same_vault_bakes_the_same_world_anywhere(tmp_path):
    """Same content, wildly different mtimes, different parent directories: same world.

    The F6 regression, and it fails on the code this replaced. Note the copies share a
    directory NAME: `vaultPath` records the basename, which is part of how you invoked the
    bake, so two differently-named folders are legitimately two different manifests.
    """
    one, two = tmp_path / "one" / "sample_vault", tmp_path / "two" / "sample_vault"
    for dest in (one, two):
        dest.parent.mkdir(parents=True)
        shutil.copytree(SAMPLE, dest)
    # Different eras, different spreads, and opposite write orders.
    _stamp(one, 946_684_800.0, spread=0.001)                 # 2000, clone-like jitter
    _stamp(two, 1_893_456_000.0, spread=86_400, reverse=True)  # 2030, days apart, reversed

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _bake(one, a)
    _bake(two, b)
    assert a.read_bytes() == b.read_bytes(), "the clock still reaches the world"


def test_no_build_machine_path_in_the_manifest(tmp_path):
    """The manifest is published. It must not carry the path of whoever baked it.

    The committed world used to contain an absolute path into the author's home directory.
    That is both an environment leak into a shared artifact and, on its own, enough to stop
    any re-bake elsewhere from matching.
    """
    out = tmp_path / "w.json"
    _bake(SAMPLE, out)
    text = out.read_text(encoding="utf-8")

    assert str(ROOT) not in text, "the repository path is in the manifest"
    assert str(tmp_path) not in text, "the output path is in the manifest"
    manifest = json.loads(text)
    where = manifest["generatedFrom"]["vaultPath"]
    assert where == "sample_vault", f"expected a bare basename, got {where!r}"
    assert not os.path.isabs(where)

    # and the committed artifact itself, which is the one that actually ships
    committed = COMMITTED.read_text(encoding="utf-8")
    for leak in ("/Users/", "/home/", "C:\\\\"):
        assert leak not in committed, f"{leak!r} appears in the committed world"


# ------------------------------------------------------------------- the mechanism

def test_activity_does_not_come_from_the_clock(tmp_path):
    """Touching a note changes no activity value, and therefore no archetype."""
    vault = tmp_path / "sample_vault"
    shutil.copytree(SAMPLE, vault)
    _stamp(vault, 1_500_000_000.0, spread=3600)

    before = _bake(vault, tmp_path / "before.json")
    # Move one note far enough to reorder it AND, under min-max, to rescale everyone else.
    one = sorted(vault.rglob("*.md"))[0]
    os.utime(one, (1_600_000_000.0, 1_600_000_000.0))
    after = _bake(vault, tmp_path / "after.json")

    assert [n["activity"] for n in before["graph"]["nodes"].values()] == \
           [n["activity"] for n in after["graph"]["nodes"].values()]
    assert [e["archetype"] for e in before["enemies"]] == \
           [e["archetype"] for e in after["enemies"]]
    assert [r["activity"] for r in before["regions"]] == \
           [r["activity"] for r in after["regions"]]


def test_one_note_does_not_rescale_the_others():
    """Rank, not min-max.

    Min-max is the wrong estimator even where mtimes are real: it divides by the span, so
    one note edited today rescales every other note in the vault. Rank moves only the notes
    the changed one actually overtakes. Exercised through the mtime path, because that is
    where a single value can move by an arbitrary amount.
    """
    from vaultcrawl.mapping import activity_map

    class _N:
        def __init__(self, t):
            self.mtime = t

    notes = {f"n{i}": _N(1_000_000.0 + i) for i in range(10)}
    base = activity_map(notes, "seed", use_mtime=True)

    notes["n9"] = _N(9_999_999_999.0)          # one note dragged far into the future
    moved = activity_map(notes, "seed", use_mtime=True)

    unchanged = [k for k in base if base[k] == moved[k]]
    assert len(unchanged) == len(base), (
        "moving the newest note further into the future rescaled its neighbours; "
        f"changed: {[k for k in base if base[k] != moved[k]]}")

    notes["n0"] = _N(5_000_000.0)              # the oldest note leapfrogs to the middle
    leapt = activity_map(notes, "seed", use_mtime=True)
    assert leapt["n9"] == moved["n9"], "the far end moved when the near end was reordered"
    assert sum(1 for k in base if leapt[k] != moved[k]) < len(base), \
        "a single reorder disturbed every value, which is the min-max behaviour"


def test_the_mtime_opt_in_still_works(tmp_path):
    """The recency feature is opt-in, not deleted, and it says so in the manifest."""
    vault = tmp_path / "sample_vault"
    shutil.copytree(SAMPLE, vault)
    for i, path in enumerate(sorted(vault.rglob("*.md"))):
        os.utime(path, (1_000_000_000.0 + i * 86_400, 1_000_000_000.0 + i * 86_400))

    default = _bake(vault, tmp_path / "d.json")
    recency = _bake(vault, tmp_path / "r.json", "--mtime-activity")

    # Compare the ACTIVITY VALUES, not the manifests. An earlier version compared whole
    # manifests and passed even with the flag disabled, because the `activitySource` marker
    # alone made them unequal. The marker is not the feature.
    assert [n["activity"] for n in default["graph"]["nodes"].values()] != \
           [n["activity"] for n in recency["graph"]["nodes"].values()], \
        "the opt-in flag changed no activity value, so it is dead"
    assert recency["generatedFrom"].get("activitySource") == "mtime", \
        "a world that cannot be reproduced from the vault must say so"
    assert "activitySource" not in default["generatedFrom"], \
        "the reproducible default should not claim a source it did not use"

    ordered = [n["activity"] for n in recency["graph"]["nodes"].values()]
    assert min(ordered) == 0.0 and max(ordered) == 1.0, "ranks should span the range"
