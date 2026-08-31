"""Whether a note can haunt you must depend on the run, not on its name.

`to_upheaval_events` rolled `droll(note_id, 3) == 0` to turn a read note into a ghost. `droll`
is deterministic, so that is a pure function of the note's NAME: whether a note could *ever*
become a ghost was fixed for all time when someone typed its title.

On the sample vault it leaves exactly two eligible notes, `discipline` and `second brain`.
Measured over four runs, the agent reads `stoicism`, `roguelike project` and `grocery list`,
and only those. **The two sets are disjoint.** So `haunted` scored 0.000 across 288 runs in
both arms of a chained evaluation, and the entire ghost mechanic, plus the attractor named
after it, was unreachable rather than rare. `notes_learned` was 4 to 12, so the denominator
was never the problem.

Salting the roll with the run seed makes each read note a genuine one-in-three per run, which
is what the original comment already claimed it was.

What this pins:

  1. The same note can ghost in one run and not another. That is the fix.
  2. Every note is eligible in some run. No note is born unhauntable.
  3. It stays deterministic: same note, same run seed, same answer. The bake and the runtime
     both depend on that (`CLAUDE.md` invariant 4), so the fix must not reach for `random`.
  4. The rate stays near one in three rather than becoming "always", which would make ghosts
     ordinary instead of a thing that happens to a run.
"""
from __future__ import annotations

from runtime.persistence import RunChronicle

# The three the agent was measured actually reading, and the two the old gate allowed.
READ_IN_PRACTICE = ("stoicism", "roguelike project", "grocery list")
OLD_GATE_ALLOWED = ("discipline", "second brain")


def _lost(note_id: str, run_seed: str) -> bool:
    rc = RunChronicle()
    rc.run_seed = run_seed
    rc.record_lore(note_id)
    return any(e["kind"] == "note_lost" for e in rc.to_upheaval_events())


def test_a_notes_fate_varies_by_run():
    """The defect: under the old gate this was False for every note, forever."""
    for note in READ_IN_PRACTICE:
        outcomes = {_lost(note, f"run-{i}") for i in range(30)}
        assert outcomes == {True, False}, (
            f"{note!r} has the same fate in all 30 runs, so ghosting is still a property of "
            f"the note's name rather than of what happened")


def test_no_note_is_born_unhauntable():
    """Every note the agent might read has to be able to ghost in some run."""
    import json
    world = json.load(open("examples/world.json", encoding="utf-8"))
    for note in world["graph"]["nodes"]:
        assert any(_lost(note, f"run-{i}") for i in range(40)), (
            f"{note!r} can never become a ghost in any of 40 runs. That is the old bug in a "
            f"new place: some notes are permanently exempt from the mechanic.")


def test_the_roll_is_still_deterministic():
    """`CLAUDE.md` invariant 4. Same inputs, same answer, every time and every machine."""
    for note in READ_IN_PRACTICE:
        for seed in ("a", "b", "c"):
            assert _lost(note, seed) == _lost(note, seed)


def test_ghosts_stay_occasional():
    """A one-in-three that became an always would make hauntings wallpaper."""
    hits = sum(_lost(n, f"run-{i}") for n in READ_IN_PRACTICE for i in range(60))
    rate = hits / (len(READ_IN_PRACTICE) * 60)
    assert 0.15 < rate < 0.55, (
        f"ghost rate {rate:.0%} is outside the intended neighbourhood of one in three")


def test_the_old_gate_really_was_disjoint_from_what_the_agent_reads():
    """The evidence for the change, kept executable so it cannot rot into an anecdote."""
    from runtime.det import droll
    old_eligible = {n for n in
                    ("discipline", "ecs", "grocery list", "journaling", "memento mori",
                     "procedural generation", "roguelike project", "rust", "second brain",
                     "stoicism")
                    if droll(n, 3) == 0}
    assert old_eligible == set(OLD_GATE_ALLOWED), old_eligible
    assert not (old_eligible & set(READ_IN_PRACTICE)), (
        "the old gate and the notes the agent reads now overlap, which would mean the "
        "premise recorded here no longer holds and this history needs rewriting")
