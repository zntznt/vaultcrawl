"""A verb that raises must not be indistinguishable from a verb the game refused.

`agent_action.dispatch` wraps its body in `except Exception: return False`. The runner reads
False as "nothing happened" and records it through `observe_verb(kind, ok=False)`, which lands
in `verb_fail` next to every legitimate refusal. `broken_verbs()` then only names a verb that
NEVER succeeds, so a verb that works most of the time and crashes on one branch leaves no
trace anywhere.

That is not a hypothetical failure mode, it is how three separate bugs survived:

  * `self._spend_matter` in the elite-encounter flee branch, AttributeError for the life of
    the project, found by a test that happened to reach it
  * `heal_body` unimported in five of seven locus handlers, NameError, 157 occurrences in a
    single seed of six runs
  * `structures.crystals.discard(...)` on a dict, AttributeError, the no-matter route for
    clearing weather

None appeared in 288 classic runs, three ablation sweeps or 432 runs of a quality sweep.
Counting the swallow is what turned that class from found-by-luck into listed.

The counter deliberately does NOT change behaviour. dispatch still returns False.
"""
from __future__ import annotations

import pytest

from runtime.agent_action import AgentAction, dispatch
from runtime.metrics import metrics, reset_metrics


class _Boom:
    """The narrowest possible game: `try_move` raises, everything else is absent."""

    def try_move(self, dx, dy):
        raise ValueError("boom")


def test_a_raising_verb_is_counted_not_merely_refused():
    reset_metrics()
    assert dispatch(_Boom(), AgentAction("move", dx=1)) is False, (
        "behaviour must be unchanged: dispatch still reports a crash as a refusal")
    crashes = metrics().verb_crashes
    assert crashes.get("move:ValueError") == 1, (
        f"the crash was swallowed without a trace and {crashes} was recorded, which is "
        f"exactly the state that hid three bugs")


def test_the_crash_site_is_recorded_so_it_can_be_found_without_reproducing_it():
    reset_metrics()
    dispatch(_Boom(), AgentAction("move", dx=1))
    site = metrics().crash_sites.get("move:ValueError", "")
    assert "test_dispatch_crashes.py:" in site, (
        f"crash site {site!r} does not name the raising line, so a report of the count "
        f"would leave someone grepping for it")


def test_repeats_accumulate_rather_than_overwrite():
    reset_metrics()
    for _ in range(4):
        dispatch(_Boom(), AgentAction("move", dx=1))
    assert metrics().verb_crashes["move:ValueError"] == 4


def test_an_ordinary_refusal_is_not_recorded_as_a_crash():
    """The control. If every False were counted, the signal would be worthless: dispatch
    legitimately returns False constantly."""
    reset_metrics()
    assert dispatch(_Boom(), AgentAction("move", dx=0, dy=0)) is False
    assert metrics().verb_crashes == {}, (
        "a zero-length move is a refusal, not a crash, and counting it would bury the "
        "real ones")


def test_the_inner_handlers_are_instrumented_too():
    """`breakdown` and `craft_consumable` have their own `except Exception`, and an
    uninstrumented one is a blind spot in the shape of a verb."""
    import inspect

    src = inspect.getsource(dispatch)
    assert src.count("_swallowed(") >= 3, (
        "dispatch has an `except Exception` that does not record, so crashes in that verb "
        "remain invisible")
    assert "except Exception:\n        return False" not in src, (
        "a bare swallowing handler is back in dispatch")


def test_the_run_timeout_still_escapes_the_counter():
    """`_RunTimeout` inherits BaseException precisely so `except Exception` cannot hold it.
    Recording crashes must not have widened the net to catch it."""
    from runtime.ablate import _RunTimeout

    class _Slow:
        def try_move(self, dx, dy):
            raise _RunTimeout()

    reset_metrics()
    with pytest.raises(_RunTimeout):
        dispatch(_Slow(), AgentAction("move", dx=1))
    assert metrics().verb_crashes == {}
