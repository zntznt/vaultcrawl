"""The eval must dump per-run rows, not only averages.

Every balance number this project has quoted came out of `agent_stats`, which is means and
counts. A mean carries no interval, so claims like "emergent is the berserker, 31.6 average
kills" were point estimates presented as measurements, with no way to ask whether two
profiles actually differ or whether the sample was simply too small.

The cost of that showed up directly. Extending three profiles from 8 seeds to 48 moved
artisan 37.5% to 18.8%, cartographer 50% to 22.9% and emergent 12.5% to 29.2%. That is up
to three wins' worth of movement against a noise budget `CLAUDE.md` documents as one win per
arm. With only aggregates there was nothing to inspect after the fact.

So `per_run` is now part of the dump, and this pins two things: that it exists at all, and
that it agrees with the aggregates computed beside it. Two views of one run that can drift
apart are worse than one view.
"""
from __future__ import annotations

import runtime.agent_eval as ev


def _fake(agent, seed, **kw):
    base = dict(agent=agent, seed="world", run_seed=seed, floor_reached=5, max_floor=26, won=False,
                kills=2, items_collected=1, sigils_forged=1, caches_opened=1,
                turns_survived=100, hp_ended=10, cause_of_death="", floors_cleared=1,
                average_hp=20.0, attractor_scores=None, narrative="", metrics=None,
                win_path="")
    base.update(kw)
    return ev.RunResult(**base)


def test_the_dump_carries_one_row_per_run(tmp_path, monkeypatch):
    """A row per run, with the fields a later analysis needs to compute spread."""
    monkeypatch.setenv("HOME", str(tmp_path))
    runs = [_fake("artisan", 0), _fake("artisan", 1, won=True, win_path="commune", kills=9),
            _fake("whisper", 0, floor_reached=26)]

    monkeypatch.setattr(ev, "AGENT_NAMES", ["artisan", "whisper"])
    monkeypatch.setattr(ev, "run_agent",
                        lambda *a, **kw: runs.pop(0) if runs else _fake("x", 0))
    out = ev.evaluate_agents("examples/world.json", 2, 26, agents=["artisan"])

    rows = out.get("per_run")
    assert rows is not None, "the dump has no per_run block, so nothing can be re-analysed"
    assert len(rows) == 2, f"expected one row per run, got {len(rows)}"
    for field in ("agent", "world_seed", "run_seed", "floor_reached", "won", "win_path",
                  "kills", "turns_survived", "hp_ended", "cause_of_death"):
        assert field in rows[0], f"per_run rows are missing {field!r}"

    # A row you cannot trace back to a run is half useless. `seed` on RunResult is the
    # WORLD seed and is identical across a batch, so the row also carries the per-run
    # varier; re-running with it replays that exact game.
    assert len({r["run_seed"] for r in rows}) == len(rows), \
        "rows do not carry a distinct run_seed, so no row identifies its run"


def test_rows_and_aggregates_describe_the_same_runs(tmp_path, monkeypatch):
    """Recomputing the aggregates from the rows must reproduce them exactly.

    Two summaries of one experiment that disagree are worse than one, because the reader
    cannot tell which is wrong. This makes them one summary in two shapes.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    made = [_fake("artisan", 0, kills=1, floor_reached=3),
            _fake("artisan", 1, kills=7, floor_reached=11, won=True, win_path="truths"),
            _fake("artisan", 2, kills=4, floor_reached=6)]
    supply = list(made)

    monkeypatch.setattr(ev, "AGENT_NAMES", ["artisan"])
    monkeypatch.setattr(ev, "run_agent", lambda *a, **kw: supply.pop(0))
    out = ev.evaluate_agents("examples/world.json", 3, 26, agents=["artisan"])

    rows = [r for r in out["per_run"] if r["agent"] == "artisan"]
    agg = out["agent_stats"]["artisan"]

    assert len(rows) == agg["runs"]
    assert round(sum(r["kills"] for r in rows) / len(rows), 2) == agg["avg_kills"]
    assert round(sum(r["floor_reached"] for r in rows) / len(rows), 2) == agg["avg_floor"]
    assert max(r["floor_reached"] for r in rows) == agg["deepest_floor"]
    assert round(sum(1 for r in rows if r["won"]) / len(rows), 4) == agg["win_rate"]

    won_paths = {}
    for r in rows:
        if r["won"]:
            won_paths[r["win_path"]] = won_paths.get(r["win_path"], 0) + 1
    assert won_paths == agg["win_paths"]
