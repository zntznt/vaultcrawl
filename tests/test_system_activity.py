"""Four ways to change no outcome, and they must not be reported as one.

`runtime/ablate.py` says roughly twenty of twenty-seven systems move nothing. That result has
causes with opposite fixes, and the ablation table cannot separate them:

  never called    a wiring bug. The system may be perfectly good.
  silent          called constantly, never acts, says nothing. Dead by design.
  busy and mute   heavy internal state, no output. Needs a consumer, not a rewrite.
  active          it acts, it speaks, and the outcome still does not move. Only here is
                  "the design is wrong" the right conclusion.

The classifier is the whole value of the module, so it is what this file exercises. The
fixtures are fakes on purpose: a real system cannot tell you whether the verdict it received
was correct, because the verdict is what you were trying to establish.

The failure that actually happened is `test_a_stateless_system_is_not_called_silent`. An
earlier version required only `acted == 0` and duly called `forge` dead by design, on a run
where it emitted 123 events. Ablation showed the same `forge` opening a win route. A system
can act entirely on the game and keep nothing of its own, and the metric watches only its own
`__dict__`.
"""
from __future__ import annotations

import collections

import pytest

from runtime.system_activity import HOOKS, MUTE_BUSY, instrument, verdict


def _c(**kw):
    return collections.Counter(kw)


def test_a_system_the_stack_never_invokes_is_a_wiring_bug():
    assert verdict(_c()) == "never called"
    assert verdict(_c(hooks=0, acted=0)) == "never called"


def test_called_constantly_and_doing_nothing_is_dead_by_design():
    assert verdict(_c(hooks=18285, acted=0)) == "silent"


def test_a_stateless_system_is_not_called_silent():
    """The real bug. `forge`: 18,285 calls, 0 own-state changes, 123 events emitted."""
    assert verdict(_c(hooks=18285, acted=0, emitted=123)) == "stateless", (
        "a system that acts on the game while keeping no state of its own is being reported "
        "as dead by design, which is how `forge` was misclassified while ablation showed it "
        "opening a win route")
    assert verdict(_c(hooks=100, acted=0, logged=5)) == "stateless"


def test_busy_with_no_output_is_its_own_diagnosis():
    """`scent`: acts on 11.1% of calls, emits nothing, logs nothing, changes no outcome."""
    assert verdict(_c(hooks=18285, acted=2021)) == "busy and mute", (
        "a system doing heavy internal work that nothing downstream reads needs a consumer, "
        "and lumping it with the silent ones prescribes the wrong fix")


def test_a_trickle_of_state_with_no_output_is_not_promoted_to_busy():
    """One state change in eighteen thousand calls is a rounding error, not a finding."""
    c = _c(hooks=18285, acted=1)
    assert c["acted"] / c["hooks"] < MUTE_BUSY
    assert verdict(c) == "active"


def test_a_system_that_acts_and_speaks_is_active():
    assert verdict(_c(hooks=18285, acted=6266, logged=1951)) == "active"


def test_instrument_counts_calls_and_state_changes_separately():
    """The two columns must not be the same measurement wearing two names."""

    class Fake:
        name = "fake"

        def __init__(self):
            self.n = 0

        def on_player_act(self, game):
            pass

        def on_floor_enter(self, game):
            self.n += 1

    stats, current = {}, []
    f = Fake()
    instrument([f], stats, current)
    for _ in range(5):
        f.on_player_act(None)
    for _ in range(3):
        f.on_floor_enter(None)
    c = stats["fake"]
    assert c["hooks"] == 8, "not every hook call is being counted"
    assert c["acted"] == 3, (
        f"acted={c['acted']}; only the three calls that moved `n` changed state, so counting "
        f"anything else makes `acted` a second copy of `hooks`")
    # 3 of 8 calls with no output at all is the busy-and-mute shape, and the classifier
    # agreeing with the counter here is the cross-check worth having.
    assert verdict(c) == "busy and mute"


def test_instrument_attributes_output_to_the_system_that_was_running():
    """Emissions are credited by who held the floor, so nesting must not misattribute."""

    seen = []

    class Fake:
        name = "outer"

        def on_player_act(self, game):
            # Read the stack from INSIDE the hook, which is where a real system emits. An
            # earlier version read it from a wrapper placed outside and of course saw nothing.
            seen.append(list(current))

    class Raiser:
        name = "raiser"

        def on_player_act(self, game):
            raise RuntimeError("boom")

    stats, current = {}, []
    f, bad = Fake(), Raiser()
    instrument([f, bad], stats, current)
    f.on_player_act(None)
    assert seen == [["outer"]], (
        f"the running-system stack read {seen}, so an event emitted inside a hook would be "
        f"credited to the wrong system or to none")
    assert current == [], "the stack was not unwound, so later output is misattributed"

    with pytest.raises(RuntimeError):
        bad.on_player_act(None)
    assert current == [], (
        "a hook that raised left its name on the stack, so every later emission in the run "
        "would be credited to a system that already failed")


def test_display_hooks_are_excluded_on_purpose():
    """A headless run never renders, and counting render calls would fake unreachability."""
    assert "render_overlay" not in HOOKS and "status_line" not in HOOKS


def test_every_hook_name_exists_on_the_base_system():
    """A typo here silently stops counting a hook and inflates the silent bucket."""
    from runtime.systems import System
    missing = [h for h in HOOKS if not hasattr(System, h)]
    assert missing == [], f"HOOKS names hooks the System base class does not have: {missing}"


def test_busy_and_mute_is_a_question_not_a_conclusion():
    """`senses` is mute on the bus and consumed by every perception call the agent makes.

    The column sees `emit` and `log` only, so a system read directly off its attributes looks
    identical to one nobody reads. Both `scent` and `senses` land here on a real run and they
    are opposite cases: dropping `scent` left all 24 ablation runs byte-identical, while
    `senses` is excluded from ablation entirely because removing it blinds the agent. Anything
    that prints this verdict must say so, or a reader will go and delete `senses`.
    """
    from runtime.ablate import UNDROPPABLE
    import runtime.system_activity as sa

    assert verdict(_c(hooks=24158, acted=11273)) == "busy and mute", (
        "the premise is gone: `senses` no longer lands in this bucket and the caveat below "
        "may no longer be needed")
    assert "senses" in UNDROPPABLE, (
        "`senses` became droppable, so the worked example in the caveat is stale")
    doc = sa.__doc__ or ""
    assert "senses" in doc and "ablation" in doc, (
        "the module no longer warns that busy-and-mute needs cross-checking against "
        "ablation, so `senses` reads as an unused system that should be cut")


def test_touched_separates_a_player_only_system_from_a_silent_one():
    """`body` acts on the player and nothing else. Without this column it reads as dead."""
    assert verdict(_c(hooks=18285, acted=0, touched=42)) == "stateless", (
        "a system whose only effect is on the player is being called dead by design, which "
        "is the same error that misclassified `forge` and then `body`")
    assert verdict(_c(hooks=18285, acted=0, touched=0)) == "silent"


def test_silence_is_documented_as_a_screen_not_a_verdict():
    """`body` still reads silent, for reasons the module must state rather than hide.

    `on_floor_enter` fires inside `Game.__init__`, before there is a player to watch, and
    later calls rewrite `player.body` to a dict of the same shape that a length-keyed
    snapshot cannot see. Anyone reading the table needs to know that before deleting a
    system on its say-so.
    """
    import runtime.system_activity as sa
    doc = sa.__doc__ or ""
    assert "body" in doc, "the known false positive is no longer named"
    assert "ablation" in doc and "screen" in doc, (
        "the module no longer says a silent verdict is a question for ablation, so the "
        "table reads as authority it does not have")
