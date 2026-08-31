"""Splitting the work must not silently drop runs or shred a history.

The chained evaluation runs two arms across processes. Getting the split wrong is the kind of
bug that produces a plausible-looking number from the wrong experiment, which is worse than a
crash, so the arithmetic is a pure function and this file exercises it without spending a run.

The two arms have opposite constraints:

  cold   every run starts from a deleted chronicle and shares nothing, so it can be split
         any way at all.
  warm   a chain is a history. All of a seed's agents must land in the same chunk, or a run
         inherits a chronicle written by a different history and the warm condition becomes
         a muddle rather than a memory.

Why this exists at all: with a single warm chain the cold arm finished in a quarter of the
time and three cores then idled for over an hour. Splitting into several independent chains
fixes that, and is arguably the better experiment anyway, since a chronicle saturates around
14 events so a chain of 48 reaches the same state as a chain of 144, and several short
histories sample "a world that remembers" better than one long one.
"""
from __future__ import annotations

import pytest

from runtime.chained_eval import partition

AGENTS = ("artisan", "cartographer", "emergent", "exploiter", "seeker", "whisper")


def _pairs(chunks):
    return [p for _warm, _idx, chunk in chunks for p in chunk]


@pytest.mark.parametrize("seeds,cold_workers,warm_chains", [
    (24, 4, 4), (24, 3, 3), (7, 3, 3), (2, 4, 4), (1, 4, 4), (24, 1, 1), (5, 8, 8),
])
def test_every_run_happens_exactly_once_in_each_arm(seeds, cold_workers, warm_chains):
    warm, cold = partition(seeds, AGENTS, cold_workers, warm_chains)
    expected = [(s, a) for s in range(seeds) for a in AGENTS]
    for name, chunks in (("warm", warm), ("cold", cold)):
        got = _pairs(chunks)
        assert sorted(got) == sorted(expected), f"{name} arm does not cover the work exactly"
        assert len(got) == len(set(got)), f"{name} arm runs something twice"


@pytest.mark.parametrize("seeds,warm_chains", [(24, 4), (7, 3), (5, 8), (24, 1)])
def test_a_seed_is_never_split_across_chains(seeds, warm_chains):
    """The one that matters. A history has to stay whole."""
    warm, _cold = partition(seeds, AGENTS, warm_chains, warm_chains)
    home = {}
    for _w, idx, chunk in warm:
        for seed, _agent in chunk:
            assert home.setdefault(seed, idx) == idx, (
                f"seed {seed} appears in chains {home[seed]} and {idx}: one of its runs would "
                f"inherit a chronicle written by a different history")


def test_no_empty_chunk_is_scheduled():
    """More workers than work should not spawn processes with nothing to do."""
    warm, cold = partition(1, AGENTS, 8, 8)
    assert all(chunk for _w, _i, chunk in warm + cold)
    assert len(warm) == 1, "one seed cannot fill more than one chain"


def test_each_chunk_is_tagged_with_its_arm():
    warm, cold = partition(4, AGENTS, 2, 2)
    assert all(w is True for w, _i, _c in warm)
    assert all(w is False for w, _i, _c in cold)
    idx = [i for _w, i, _c in warm]
    assert len(idx) == len(set(idx)), "two chains share an index, so they share a state dir"
