"""The weight audit must count the right branch of the max(), and put `_score` back.

`runtime/weight_audit.py` replaces `runtime.agent._score` for the duration of a sample. If a
run raises and the wrapper stays installed, every later test in the same interpreter scores
through a stale tally, and the 20 script-style suites that share an interpreter would be
measuring each other. That restore is the check that protects everything downstream.

The counting rule is the other half. `_score` returns `max(weight, state) + bonus`, so the
weight decided the score only when it is strictly greater than the state. Counting `>=`
instead would credit the profile on every tie, and ties are common because several sites
pass a small constant that equals a weight exactly.
"""
from __future__ import annotations

import pytest

import runtime.agent as agent_mod
from runtime import weight_audit


def test_a_failed_audit_restores_score(monkeypatch):
    before = agent_mod._score

    def explode(*a, **kw):
        raise RuntimeError("run failed")

    import runtime.agent_eval as ev
    monkeypatch.setattr(ev, "run_agent", explode)

    with pytest.raises(RuntimeError):
        weight_audit.audit("examples/world.json", runs=1, agents=["seeker"])

    assert agent_mod._score is before, "the audit left its wrapper installed on _score"


def test_a_tie_is_not_a_bind(monkeypatch):
    """weight 5 against state 5 scores the same for every profile, so nobody's preference won."""
    seen = {}

    def fake_run(world, name, run_seed=None, **kw):
        agent_mod._score({"explore": 5}, "explore", 5, 0, True)   # tie, not a bind
        agent_mod._score({"explore": 9}, "explore", 5, 0, True)   # weight wins
        agent_mod._score({"explore": 1}, "explore", 5, 0, True)   # state wins
        seen["ran"] = True
        return None

    import runtime.agent_eval as ev
    monkeypatch.setattr(ev, "run_agent", fake_run)

    data = weight_audit.audit("examples/world.json", runs=1, agents=["seeker"])
    assert seen.get("ran"), "the fake run never fired"
    total_calls = sum(s["calls"] for s in data["sites"])
    total_binds = sum(s["weight_binds"] for s in data["sites"])
    assert total_calls == 3
    assert total_binds == 1, f"expected only the strict win to count, got {total_binds}"


def test_unreachable_candidates_are_not_counted(monkeypatch):
    """`reachable=False` short-circuits to 0, so it is not a decision the weight lost."""
    def fake_run(world, name, run_seed=None, **kw):
        agent_mod._score({"explore": 9}, "explore", 5, 0, False)
        return None

    import runtime.agent_eval as ev
    monkeypatch.setattr(ev, "run_agent", fake_run)

    data = weight_audit.audit("examples/world.json", runs=1, agents=["seeker"])
    assert sum(s["calls"] for s in data["sites"]) == 0


def test_report_survives_a_site_with_no_calls(capsys):
    weight_audit.report({"world": "w", "runs": 0,
                         "sites": [{"line": 1, "key": "explore", "calls": 0,
                                    "weight_binds": 0}]})
    out = capsys.readouterr().out
    assert "n/a" in out
