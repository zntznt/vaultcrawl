"""One default mode, and it is the sandbox.

`run_agent` hardcoded `sandbox=False` and `play.py` computed `not headless and not a.descent`,
so a person at a terminal played the grown Alexander world while every agent, demo, sweep and
evaluation played classic descent. No number this project produced described the game anyone
played, and the split was two expressions wide.

These tests exist because that is a silent failure: both modes run, both report, and nothing
about a classic result announces that it is classic.
"""
import ast
import inspect

import runtime.agent_eval as ev


def test_run_agent_defaults_to_sandbox():
    sig = inspect.signature(ev.run_agent)
    assert sig.parameters["sandbox"].default is True


def test_run_agent_hands_the_mode_to_the_game_rather_than_pinning_it():
    """The mode must reach `Game(...)` from the parameter. A literal here is the original
    bug, and a caller cannot override it."""
    src = inspect.getsource(ev.run_agent)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Game"]
    assert calls, "run_agent must construct a Game"
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "sandbox" in kw, "Game must be told the mode"
        assert isinstance(kw["sandbox"], ast.Name) and kw["sandbox"].id == "sandbox", (
            "the mode must come from the parameter, not a literal")


def test_the_floor_budget_follows_the_mode():
    """Sandbox never moves `floor`, so classic's 99 floors are phantom there and an
    unresolved run costs 49,599 decisions instead of 8,016."""
    assert ev.SANDBOX_MAX_FLOOR < ev.CLASSIC_MAX_FLOOR
    from runtime.agent_eval import run_agent
    sig = inspect.signature(run_agent)
    assert sig.parameters["max_floor"].default is None, (
        "max_floor must default to the mode's own budget, not to one mode's number")


def test_headless_play_is_not_quietly_classic():
    """`--auto` used to force classic through a `not headless` term, so the demo and every
    agent showed a different game from the one `play.py` opens interactively. Being headless
    must not change the world that gets grown."""
    from runtime.play import mode_is_sandbox

    for headless in (True, False):
        assert mode_is_sandbox(descent=False, headless=headless) is True
        assert mode_is_sandbox(descent=True, headless=headless) is False


def test_no_harness_smuggles_the_mode_in_through_a_patched_game():
    """Every harness used to monkeypatch `ev.Game` to force sandbox, because the runner
    hardcoded the other mode. A patch a caller forgets measures the wrong game silently, so
    the mode travels as an argument now."""
    for mod in ("ablate", "sandbox_eval", "system_activity"):
        src = open(f"runtime/{mod}.py").read()
        assert 'kw["sandbox"] = True' not in src, f"{mod} still patches the constructor"
