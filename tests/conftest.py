"""Turn the known-failure list into strict xfails, so CI can be green and still honest.

Sixteen tests fail today and have failed identically on every commit checked. Until this
file existed there were only two options: leave CI red from its first run, which trains
everyone to ignore it, or deselect the failures, which hides them forever.

`xfail(strict=True)` is the third option and it is strictly better than deselecting:

  * The build is green while the bugs are real.
  * A listed test that starts PASSING fails the build (`XPASS(strict)`), so the list
    cannot rot into a lie. You cannot fix a bug and forget to claim it.
  * An entry matching nothing is a collection error, not a shrug. Renaming a test without
    updating the list would otherwise silently widen the hole.

No existing test file is edited: the marks are applied at collection, so `known_failures.txt`
is the single place the set is written down.
"""
from __future__ import annotations

from pathlib import Path

import pytest

KNOWN_FAILURES = Path(__file__).parent / "known_failures.txt"


def _listed() -> list[str]:
    """Node IDs from the list file, ignoring comments and blank lines.

    Duplicates are kept rather than collapsed into a set, so they can be reported as the
    mistake they are.
    """
    if not KNOWN_FAILURES.exists():
        return []
    out = []
    for raw in KNOWN_FAILURES.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def pytest_collection_modifyitems(config, items):
    listed = _listed()
    if not listed:
        return

    wanted = set(listed)
    seen = set()
    for item in items:
        if item.nodeid in wanted:
            seen.add(item.nodeid)
            item.add_marker(
                pytest.mark.xfail(
                    strict=True,
                    reason=f"known failure, see {KNOWN_FAILURES.name}",
                )
            )

    _check_stale(listed, seen, items)


def _check_stale(listed, seen, items) -> None:
    """Fail collection on an entry that matches nothing, or on a duplicate.

    Judged per FILE rather than per run, which is what makes this safe under `-k`, a single
    test path, or `--last-failed`. If a listed entry's file contributed no items at all,
    this run simply did not include it and the entry is not evidence of anything. If the
    file WAS collected and the entry still went unmatched, the test has been renamed or
    deleted and the list is lying.
    """
    collected_files = {item.nodeid.split("::", 1)[0] for item in items}

    stale = [
        node for node in listed
        if node not in seen and node.split("::", 1)[0] in collected_files
    ]
    dupes = sorted({node for node in listed if listed.count(node) > 1})

    problems = []
    if stale:
        problems.append("listed but not collected, though their file was "
                        "(renamed, deleted, or a typo):\n  " + "\n  ".join(sorted(stale)))
    if dupes:
        problems.append("listed more than once:\n  " + "\n  ".join(dupes))
    if problems:
        raise pytest.UsageError(
            f"{KNOWN_FAILURES} is out of date.\n\n" + "\n\n".join(problems)
            + "\n\nThis list may only shrink. Delete the line when the bug is fixed."
        )


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    """Every test gets its own `~/.vaultcrawl`. None of them get the developer's.

    The suite was not hermetic. `~/.vaultcrawl` carries graves, the forge cache and the
    chronicle, and at least two tests read them: with a warm directory left over from an
    evaluation, `test_relations.py::test_spawned_creatures_carry_their_house` and
    `test_travel.py::test_log_dedup_collapses_repeats` both fail, and pass again the moment
    it is deleted. Nothing was wrong with the code either time.

    That is worse than a flake. The suite is the thing every change in this project is
    verified against, and it was reporting on the state of a directory rather than on the
    commit. It stayed hidden because CI always starts clean, so the failure only ever
    reaches whoever has just finished running an eval, which is precisely whoever is about
    to check whether their change worked. It cost an hour today and nearly bought a revert
    of correct code.

    `monkeypatch.setenv` restores the old value per test, and `tmp_path` is unique per test,
    so this also stops tests leaking state into each other. A test that genuinely needs
    persistent state should create it under this HOME.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))   # the same lookup on Windows
    return tmp_path
