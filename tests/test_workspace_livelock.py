"""The workspace livelock, which was the dominant failure of the default mode.

`workspace_camp` and `workspace_depleted` scored on proximity alone, `max(0, 12 - dist)`, so a
tile at distance 0 scored a permanent 12 whether or not the agent had any reason to be there.
The `workspace` nav kind had no arrival case, so on reaching the tile `step_toward` returned
(0, 0) and the branch returned None. Every turn, forever.

It hid from all of it. Each wasted decision still spent a turn, so decisions-per-turn sat at
exactly 1.000 and the rate tripwire could not fire by construction. The label share was 44 to
47%, under the 60% share term. The runs were recorded as ordinary losses: 122 of 138 made no
progress, mean floor 1.3, and the median run never left the first floor.

Two of these tests would have failed before the fix. The third pins the Berlin consequence.
"""
import runtime.agent as A
from runtime.agent_action import AgentAction


class _Actor:
    def __init__(self, x=5, y=5):
        self.x, self.y = x, y


class _Game:
    """Enough game for the nav branch: it only reaches `step_toward` when off-tile, and the
    arrival case returns before that."""
    def system(self, name):
        return None


def _brain():
    return A.UniversalBrain("seeker")


def test_arriving_at_a_workspace_produces_an_action_rather_than_none():
    """The bug itself, driven through the real resolver: standing on the target tile must
    not yield None. Before the fix `step_toward` returned (0, 0) here and the branch fell
    through to `return None`, which is a decision that changes nothing and still costs a
    turn."""
    brain = _brain()
    actor = _Actor(5, 5)
    # the payload the workspace candidate carries, with the agent already on the tile
    act = brain._resolve(_Game(), actor, {}, ("workspace", 5, 5))
    assert act is not None, "arriving at a workspace must not return None"
    assert isinstance(act, AgentAction) and act.kind == "rest", (
        f"the turn has to be SPENT on the tile for the positional ritual to fire, got {act}")


def test_walking_to_a_workspace_still_steps_toward_it():
    """The arrival case must not swallow the approach. Real game, because pathing needs a
    real level: off the tile the resolver must still produce a step."""
    from runtime.game import Game, load_manifest

    g = Game(load_manifest("examples/world.json"), systems=[])
    brain = _brain()
    px, py = g.player.x, g.player.y
    act = brain._resolve(g, g.player, {}, ("workspace", px + 3, py))
    assert act is not None and act.kind == "move", f"approach must still path, got {act}"


def test_a_camp_is_not_worth_walking_to_at_full_health():
    """The one thing the gate is for: at exactly full HP there is nothing to collect."""
    assert _ws_reasons(hp_pct=100, collected=[])["workspace_camp"] is False
    assert _ws_reasons(hp_pct=99, collected=[])["workspace_camp"] is True
    assert _ws_reasons(hp_pct=40, collected=[])["workspace_camp"] is True


def test_the_camp_gate_stays_where_it_was_measured():
    """Tightening this to 70 on a plausible argument cost nine wins, 24 to 15 paired on the
    same 23 seeds, and closed the commune route. The camp trips are load-bearing even when
    the agent looks healthy. Lowering it needs an arm, not a rationale."""
    assert A.CAMP_HP_PCT == 100, (
        "lowering the camp gate was measured at nine wins worse; re-measure before changing")


def test_a_depleted_locus_is_not_worth_walking_to_with_nothing_to_sacrifice():
    """It trades one collected effect for the kill-heal wire. With an empty collection it
    logs a refusal once per turn and never marks itself done, so the trip never ends."""
    assert _ws_reasons(hp_pct=100, collected=[])["workspace_depleted"] is False
    assert _ws_reasons(hp_pct=100, collected=["ember"])["workspace_depleted"] is True


def _ws_reasons(hp_pct: int, collected: list) -> dict:
    """The REAL gate, called with the state shape it reads. Reimplementing it here would
    make every assertion below pass against a copy rather than against the game."""
    return A.workspace_reasons({"vitals": {"hp_pct": hp_pct},
                                "effects": {"collected": collected}})


def test_the_single_use_workspaces_keep_no_precondition():
    """Fabricators and terminals remove themselves from the set on use, so they cannot loop
    and must not be gated. Gating a reachable system is the other half of this bug class."""
    reasons = _ws_reasons(hp_pct=100, collected=[])
    assert "workspace_fabricator" not in reasons
    assert "workspace_terminal" not in reasons
