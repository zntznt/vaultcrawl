"""The dump must keep carrying the fields the health checklist reads.

`guidance/AGENT_SPEC.md` now states what the agent win rate is for, and the answer is that the
rate itself carries no target: health is a checklist of seven structural conditions, each read
out of one `eval_stats.json`. Every profile can win, every route is used, no route dominates, no
verb is broken, decisions are contested, the decision space is used, and the profiles actually
differ from each other.

A checklist is only a contract while the fields behind it exist. Rename `broken_verbs`, drop
`policy_divergence` from the output, or stop aggregating `uncontested_share`, and the spec
silently becomes a document nobody can execute. That is precisely the failure this whole tranche
was about: a standard that was quoted for a year and could not be checked against anything.

So this pins the shape of the dump, not the values in it. The thresholds live in the spec and
move as the game changes; the fields must not move quietly.
"""
from __future__ import annotations

import runtime.agent_eval as ev

# One profile's telemetry, in the shape `evaluate_agents` aggregates from. The numbers are
# arbitrary: nothing here asserts a healthy game, only that a reader could tell.
_PRESSURE = {"label_share": {"explore_unseen": 0.6, "fight": 0.4}, "top_label_share": 0.6,
             "contested_share": 0.3, "uncontested_share": 0.0, "median_margin": 2.0,
             "avg_candidates": 8.0, "min_hp_pct": 40, "hurt_share": 0.02,
             "top3_label_share": 0.9, "labels_used": 24.0}
_EMERGENCE = {"event_kinds": 12, "event_counts": {"attack": 3},
              "verb_ok": {"move": 30}, "verb_fail": {}}


def _fake(agent, seed, **kw):
    base = dict(agent=agent, seed="world", run_seed=seed, floor_reached=26, max_floor=26,
                won=True, kills=2, items_collected=1, sigils_forged=1, caches_opened=1,
                turns_survived=100, hp_ended=10, cause_of_death="", floors_cleared=1,
                average_hp=20.0, attractor_scores=None, narrative="", metrics=None,
                win_path="standing", pressure=dict(_PRESSURE), emergence=dict(_EMERGENCE))
    base.update(kw)
    return ev.RunResult(**base)


def _run(monkeypatch, tmp_path, runs):
    monkeypatch.setenv("HOME", str(tmp_path))
    supply = list(runs)
    monkeypatch.setattr(ev, "AGENT_NAMES", ["artisan", "whisper"])
    monkeypatch.setattr(ev, "run_agent", lambda *a, **kw: supply.pop(0))
    return ev.evaluate_agents("examples/world.json", 2, 26, agents=["artisan", "whisper"])


def test_every_health_condition_has_a_field_to_read(tmp_path, monkeypatch):
    """All seven conditions in the spec, each traced to the field that answers it."""
    out = _run(monkeypatch, tmp_path,
               [_fake("artisan", 0), _fake("artisan", 1, won=False, win_path="",
                                           cause_of_death="slain"),
                _fake("whisper", 0, win_path="commune"), _fake("whisper", 1, win_path="truths")])
    stats = out["agent_stats"]

    for name in ("artisan", "whisper"):
        agg = stats[name]
        assert "win_rate" in agg, f"{name}: no win_rate, so 'every profile can win' is unreadable"
        assert "win_paths" in agg, f"{name}: no win_paths, so route use is unreadable"
        assert "broken_verbs" in agg.get("emergence", {}), \
            f"{name}: no emergence.broken_verbs, so 'no verb is broken' is unreadable"
        press = agg.get("pressure", {})
        for field in ("uncontested_share", "labels_used"):
            assert field in press, \
                f"{name}: no pressure.{field}, so the decision-space condition is unreadable"

    assert "policy_divergence" in out, \
        "no policy_divergence, so 'the profiles actually differ' is unreadable"
    assert out["policy_divergence"], "policy_divergence is empty with two profiles present"


def test_the_route_mix_pools_across_profiles(tmp_path, monkeypatch):
    """Route concentration is a property of the population, not of one profile.

    The condition is that no single route takes more than 60% of ALL wins. A profile that wins
    only one way is fine and expected; six profiles that all win the same way is the monoculture
    the escape gate was introduced to break. So the counts have to add up across profiles.
    """
    out = _run(monkeypatch, tmp_path,
               [_fake("artisan", 0), _fake("artisan", 1),
                _fake("whisper", 0, win_path="commune"), _fake("whisper", 1, win_path="truths")])

    pooled: dict[str, int] = {}
    for agg in out["agent_stats"].values():
        for route, n in agg["win_paths"].items():
            pooled[route] = pooled.get(route, 0) + n

    assert sum(pooled.values()) == 4, f"wins did not pool: {pooled}"
    assert pooled["standing"] == 2 and pooled["commune"] == 1 and pooled["truths"] == 1

    rows = [r for r in out["per_run"] if r["won"]]
    from_rows: dict[str, int] = {}
    for r in rows:
        from_rows[r["win_path"]] = from_rows.get(r["win_path"], 0) + 1
    assert from_rows == pooled, \
        f"the rows and the aggregates disagree about the route mix: {from_rows} vs {pooled}"
