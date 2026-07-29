"""The supply instrument must read the world it is given and put the game back as it found it.

`runtime/availability.py` measures by wrapping `UniversalBrain.decide`, `Game.emit` and the
two sigil verbs. That is the right call, since nothing in the run path then knows it is being
watched, but it means a raised exception mid-sample could leave four monkeypatched methods
installed process-wide. Every later test in the same interpreter would then be measuring
through a sampler pointed at a stale tally. This pins the restore.

It also pins the world reader. `world_supply` walked `world["nodes"]` in its first draft,
which does not exist; the real path is `world["graph"]["nodes"]`. It silently counted zero
notes and printed an empty supply table, which reads exactly like a world with no sigils in
it rather than like a broken query.
"""
from __future__ import annotations

import json

import pytest

from runtime import availability
from runtime.agent import UniversalBrain
from runtime.game import Game
from runtime.sigils import ROLE_ABILITY


def test_supply_reads_the_real_node_path():
    supply = availability.world_supply("examples/world.json")
    assert supply, "no roles found, so the query missed the graph entirely"
    assert set(supply) <= set(ROLE_ABILITY), (
        f"roles with no verb mapping: {set(supply) - set(ROLE_ABILITY)}")


def test_supply_of_a_world_with_a_list_of_nodes(tmp_path):
    """Both node shapes in the wild: a dict keyed by title, and a bare list."""
    as_list = {"graph": {"nodes": [{"role": "hub"}, {"role": "leaf"}, {"role": "hub"}]}}
    as_dict = {"graph": {"nodes": {"a": {"role": "hub"}, "b": {"role": "leaf"},
                                   "c": {"role": "hub"}}}}
    for name, world in (("list.json", as_list), ("dict.json", as_dict)):
        p = tmp_path / name
        p.write_text(json.dumps(world), encoding="utf-8")
        assert availability.world_supply(str(p)) == {"hub": 2, "leaf": 1}


def test_a_failed_sample_does_not_leak_its_monkeypatches(monkeypatch):
    """The one that protects every other test in the process."""
    before = (UniversalBrain.decide, Game.emit, Game.deploy, Game.recover)

    def explode(*a, **kw):
        raise RuntimeError("run failed")

    monkeypatch.setattr(availability, "world_supply", lambda *a, **kw: {})
    import runtime.agent_eval as ev
    monkeypatch.setattr(ev, "run_agent", explode)

    with pytest.raises(RuntimeError):
        availability.sample("examples/world.json", runs=1, agents=["seeker"])

    assert (UniversalBrain.decide, Game.emit, Game.deploy, Game.recover) == before, (
        "the sampler left its wrappers installed after a failed run")


def test_report_survives_an_empty_sample(capsys):
    """A zero-decision tally must print `n/a`, never divide by zero."""
    availability.report({"world": "w", "runs": 0, "supply": {"hub": 1},
                         "per_agent": {"seeker": {}}})
    out = capsys.readouterr().out
    assert "n/a" in out
    assert "Recall" in out, "the supply table lost its verb column"
