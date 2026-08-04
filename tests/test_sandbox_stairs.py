"""A stair that does nothing must say so, and one that works must cost a turn.

Sandbox mode is the default interactive mode and had never been run with an agent. The
first batch that did found the worst livelock this project has recorded: **533 decisions
per game turn**, against 11.38 for the commune loop and 3.75 for interact. Three separate
defects stacked into it, and each one alone is enough to hang a run.

  1. **A door drawn on nothing.** `generate_level` writes a `>` at `level.stairs` for
     classic descent. The sandbox surface builds its own district doors and never cleared
     that one, so the map carried a `>` with no gate behind it. `on_stairs` reads the
     glyph; `descend` reads `_gates`. They disagreed, and the agent's forced
     `panic_descend` override rode the disagreement for 49,437 consecutive decisions.

  2. **A verb with no verdict.** `Game.descend` returned None on every path, success and
     refusal alike, and `dispatch` answered True regardless. `note_result` was therefore
     never told, and `FATIGUE_FAILED` never applied. This is the same shape as commune
     range, commune price, the egress stair and interact: the fifth instance.

  3. **A free action.** Sandbox traversal moved the player between z-levels without
     touching the clock. The arrival tile is the matching stair, so descend-ascend was a
     no-cost cycle: 98 of 194 decisions and zero game turns. A loop the clock never
     advances through is invisible to every backstop that measures per turn.

Fixing 1 took cartographer/sbx-1 from 533.32 decisions per turn to 2.02. Fixing 3 took it
to 0.79, and the run went from a loss to a win. 2 is the one that keeps the class from
recurring silently: it makes any future disagreement report itself.
"""
from __future__ import annotations

import pytest

from runtime.agent_action import AgentAction, dispatch
from runtime.game import Game, load_manifest
from runtime.stack import build_systems


@pytest.fixture
def sbx():
    return Game(load_manifest("examples/world.json"), sandbox=True,
                run_seed="sbx-stairs", systems=build_systems())


def _stair_tiles(game):
    return [(x, y) for y, row in enumerate(game.level.tiles)
            for x, c in enumerate(row) if c in "<>"]


@pytest.mark.parametrize("run_seed", ["sbx-0", "sbx-1", "sbx-2", "sbx-3", "sbx-stairs"])
def test_every_surface_stair_leads_somewhere(run_seed):
    """Defect 1. A glyph is a promise; the surface was breaking it.

    Swept over seeds deliberately. `level.stairs` sometimes lands on a district door or on
    unwalkable ground, and on those layouts the bug is simply absent: a single-seed check
    passed with the fix reverted and would have shipped as decoration.
    """
    g = Game(load_manifest("examples/world.json"), sandbox=True,
             run_seed=run_seed, systems=build_systems())
    orphans = [p for p in _stair_tiles(g) if p not in g._gates]
    assert orphans == [], (
        f"{len(orphans)} stair glyphs on the surface of {run_seed} have no gate behind "
        f"them: {orphans}. `on_stairs` will say yes and `descend` will do nothing, which "
        f"is the exact livelock this file exists for")


def test_descending_where_there_is_no_stair_reports_failure(sbx):
    """Defect 2, the plain case."""
    floor = next((x, y) for y, row in enumerate(sbx.level.tiles)
                 for x, c in enumerate(row)
                 if c not in "<>" and sbx.level.walkable(x, y))
    sbx.player.x, sbx.player.y = floor
    assert sbx.descend() is False, "descend claims success standing on open ground"
    assert sbx.ascend() is False, "ascend claims success standing on open ground"


def test_a_descend_that_does_nothing_spends_no_turn_and_admits_it(sbx):
    """Defect 2, the case that actually happened: the glyph is right, the gate is not.

    Planted rather than found, because defect 1 is fixed and the surface no longer has
    such a tile. The verb must still be honest if one ever comes back.
    """
    x, y = next((x, y) for y, row in enumerate(sbx.level.tiles)
                for x, c in enumerate(row)
                if c not in "<>" and sbx.level.walkable(x, y))
    sbx.level.tiles[y][x] = ">"          # a door with no gate, exactly as the bug had it
    sbx.player.x, sbx.player.y = x, y
    assert sbx.on_stairs() is True, "the premise is gone: this tile no longer reads as a stair"
    before = sbx.turn
    assert sbx.descend() is False, (
        "descend returned success having moved nobody, so the brain re-reads an unchanged "
        "state and forces the same nothing again")
    assert sbx.turn == before, "a descend that did nothing still charged a turn"
    assert dispatch(sbx, AgentAction("descend")) is False, (
        "dispatch hardcodes True again, so note_result is never told and FATIGUE_FAILED "
        "never applies")


def test_a_working_traversal_costs_a_turn(sbx):
    """Defect 3. Free travel is a loop no per-turn backstop can see.

    Picks a gate that a stair glyph marks. Not every gate has one: `PortalSystem` writes a
    temporary gate rendered as `◉` with no `<`/`>` under it, which is why the glyph-to-gate
    check above is one-directional.
    """
    gate = next(p for p in sorted(sbx._gates)
                if sbx.level.tiles[p[1]][p[0]] in "<>")
    sbx.player.x, sbx.player.y = gate
    before_turn, before_realm = sbx.turn, sbx._realm
    assert sbx.descend() is True, "crossing a real district door reported failure"
    assert sbx._realm != before_realm, "the traversal did not actually move the player"
    assert sbx.turn > before_turn, (
        "crossing a threshold cost no game time, so descend and ascend form a zero-cost "
        "cycle the agent can ride forever")


def test_classic_descent_still_reports_its_verdict():
    """The return value must not have been bolted on to sandbox alone."""
    g = Game(load_manifest("examples/world.json"), sandbox=False,
             run_seed="sbx-stairs-classic", systems=build_systems())
    assert g.descend() is True, "an ordinary classic descent reported failure"
    g.floor = g.max_floor
    assert g.egress_ready()[0] is False, (
        "the premise is gone: the last stair opens with nothing done, so this case cannot "
        "test a refusal")
    before = g.floor
    assert g.descend() is False, (
        "a shut egress stair reported success, which is how 13 runs in 288 stood on it for "
        "the rest of their lives")
    assert g.floor == before


def test_a_null_move_really_is_free(sbx):
    """The premise the next test rests on: dispatch refuses (0, 0) and charges nothing."""
    before = sbx.turn
    assert dispatch(sbx, AgentAction("move", dx=0, dy=0)) is False
    assert sbx.turn == before, (
        "a null move now spends a turn, so a forced null step is merely wasteful rather "
        "than an unbreakable loop, and the guard below is no longer load-bearing")


def test_a_forced_flee_with_nowhere_to_go_is_not_forced(sbx, monkeypatch):
    """The panic override has no fatigue backstop, so it must never force a no-op.

    `_forced` returns before the candidate list exists, so a forced null step meets nothing
    that could break it: the agent re-reads the state it just read and forces the same
    nothing again. Measured in sandbox at 51.0% of one run's decisions, 98 of them moving
    nobody.
    """
    import runtime.agent as A

    monkeypatch.setattr(A, "step_toward_avoiding_elites",
                        lambda *a, **k: (0, 0))
    brain = A.UniversalBrain("artisan")
    p = sbx.player
    p.hp = max(1, p.max_hp // 10)          # deep in the panic band
    foe = next((a for a in sbx.actors if sbx.hostile(p, a)), None)
    if foe is None:
        pytest.skip("no hostile on the surface to panic about")
    foe.x, foe.y = p.x + 1, p.y            # adjacent, so PANIC engages

    act = brain.decide(sbx, p)
    assert not (getattr(act, "kind", "") == "move"
                and act.dx == 0 and act.dy == 0), (
        "the brain forced a null move, which dispatch refuses without spending a turn and "
        "no backstop can see")
