"""The ambient narrator, held to the acceptance test its own spec wrote.

`DESIGN_PLACE_PANEL.md` step 5 states the pass condition in one sentence:

    every ambient line must point at a reachable thing or it's a lying screen.

and step 6b names itself the acceptance test for step 5:

    if wait-to-listen can name a direction and a real proper noun, the narrator is real;
    if it emits reworded telemetry ('Weather: mist. Wild: 3'), it dies with the last pass.

Both are executable, which is unusual for a design document and is the reason this file
exists. The flagship is `test_walking_toward_a_line_closes_the_distance`: the spec promises
that walking toward "a wet struggle to the east" reliably finds it, so the test walks.

The other load-bearing one is `test_the_narrator_moves_no_number`. This system arrived
after a long balance pass whose result (22 of 48) is only meaningful if nothing since has
moved the game. A narrator may produce text and nothing else, and that is asserted rather
than hoped for.
"""
from __future__ import annotations

import ast
import pathlib

from runtime import det, senses
from runtime.game import Game, load_manifest
from runtime.narrator import (_ELEMENT_VOICE, _ELEMENTS, _GAP_MOVING, _GAP_STILL,
                              NarratorSystem, bearing)
from runtime.stack import build_systems

# The eight compass words as unit offsets. Screen coordinates, so +y is south.
_HEADING = {
    "east": (1, 0), "south-east": (1, 1), "south": (0, 1), "south-west": (-1, 1),
    "west": (-1, 0), "north-west": (-1, -1), "north": (0, -1), "north-east": (1, -1),
}


def _game(seed="narrator", kit="seeker"):
    return _kitted(Game(load_manifest("examples/world.json"), sandbox=True,
                        run_seed=seed, systems=build_systems()), kit)


def _kitted(game, kit):
    if kit:
        game.starting_kit(kit)
    return game


def _listen(game, turns=400, move=False):
    """Wait (or wander) and collect every fresh narrator utterance.

    Returns a list of (last_tuple, player_position_at_the_time).
    """
    narrator = game.system("narrator")
    said = []
    for t in range(turns):
        before = narrator.last
        if move:
            step = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1)][det.droll(f"w{t}", 5)]
            game.try_move(*step)
        else:
            game.wait()
        if narrator.last is not None and narrator.last is not before:
            said.append((narrator.last, (game.player.x, game.player.y)))
    return said


def _present(game, kind, pos) -> bool:
    """Is the thing a line pointed at actually in the world right now?"""
    if kind in ("corpse", "struggle"):
        return pos in (getattr(game.system("decay"), "corpses", {}) or {})
    return kind in (getattr(game.system("reactions"), "props", {}) or {}).get(pos, set())


_CORPUS = None


def _corpus():
    """One long listening session, shared by the tests that only read what was said.

    Four separate 400-turn sessions cost 21 seconds each and produced the same corpus, so
    they run once. Whether the referent was really there is recorded AT EMIT TIME, since
    that is the only moment at which the question means anything: a corpse that rots two
    turns later did not make the line a lie.
    """
    global _CORPUS
    if _CORPUS is not None:
        return _CORPUS

    game = _game()
    narrator = game.system("narrator")
    said = []
    for _ in range(400):
        before = narrator.last
        game.wait()
        if narrator.last is None or narrator.last is before:
            continue
        turn, line, kind, pos, sense = narrator.last
        said.append({
            "turn": turn, "line": line, "kind": kind, "pos": pos, "sense": sense,
            "at": (game.player.x, game.player.y),
            "present": _present(game, kind, pos),
            "names": [getattr(a, "name", "") for a in game.actors
                      if getattr(a, "name", "")],
        })
    _CORPUS = (game, said)
    return _CORPUS


# ------------------------------------------------------------------ the cardinal rule

def test_no_line_names_a_thing_that_is_not_there():
    """The acceptance test, as an assertion.

    For every line the narrator spoke, the thing it pointed at had to be really there, in
    live game state, at the moment it spoke. A line that outlives its referent is the
    lying screen the spec calls the cardinal place-breaker, and the guard against it is
    structural: a percept carries a predicate over live state, not a remembered string.
    """
    _game_unused, said = _corpus()
    assert len(said) >= 5, f"the narrator barely spoke ({len(said)}), so this proved little"
    lies = [(s["line"], s["kind"], s["pos"]) for s in said if not s["present"]]
    assert not lies, f"lines pointing at nothing: {lies[:5]}"


def test_a_stale_percept_is_not_spoken():
    """The guard itself, exercised directly, because ordinary play never exercises it.

    Removing the `still_there()` check at emit time does NOT fail the corpus test above:
    the narrator diffs and speaks inside one turn, so in practice the referent has had no
    opportunity to vanish in between. That makes the corpus test a check on the invariant
    rather than on the guard, and leaves the guard itself unproven, so it is proven here.
    It matters for the case the spec actually names, a line that "says 'kill' but the
    corpse is already cleaned": that arrives the day something reaps mid-turn.
    """
    game = _game()
    narrator = game.system("narrator")
    px, py = game.player.x, game.player.y
    beside = (px + 1, py)

    class _Gone:
        kind, pos, actor = "corpse", beside, None

        @staticmethod
        def still_there():
            return False

    class _Real:
        kind, pos, actor = "corpse", beside, None

        @staticmethod
        def still_there():
            return True

    assert narrator._speak(game, [_Gone()]) is None, \
        "spoke about a thing whose own predicate said it was gone"
    spoken = narrator._speak(game, [_Real()])
    assert spoken is not None and spoken[0], "refused to speak about a thing that is there"


def test_walking_toward_a_line_closes_the_distance():
    """The spec's own promise: walking toward "a wet struggle to the east" finds it.

    Not a paraphrase of the promise. The test reads the bearing word out of the line the
    player was actually shown, steps that way, and requires the gap to actually shrink. A
    narrator whose bearings were decorative would pass every other test in this file and
    fail this one.
    """
    game = _game()
    narrator = game.system("narrator")

    walked = 0
    for _ in range(600):
        before = narrator.last
        game.wait()
        if narrator.last is None or narrator.last is before:
            continue
        _turn, line, kind, pos, _sense = narrator.last
        heading = next((h for h in _HEADING if f"to the {h}," in line), None)
        if heading is None:      # "underfoot": you are already standing on it
            continue

        dx, dy = _HEADING[heading]
        px, py = game.player.x, game.player.y
        start = max(abs(pos[0] - px), abs(pos[1] - py))
        if start <= 1:
            continue

        # Step the way the line pointed, as far as the walls allow.
        moved = 0
        for _step in range(start):
            nx, ny = game.player.x + dx, game.player.y + dy
            if not game.level.walkable(nx, ny) or game.actor_at(nx, ny) is not None:
                break
            game.player.x, game.player.y = nx, ny
            moved += 1
        if moved == 0:
            continue          # walled in on that side; the bearing is not on trial here

        now = max(abs(pos[0] - game.player.x), abs(pos[1] - game.player.y))
        assert now < start, (
            f"walked {moved} step(s) {heading} after {line!r} and got no closer "
            f"({start} then {now})")
        walked += 1
        if walked >= 8:
            return

    assert walked >= 3, f"only {walked} lines could be walked toward, too few to conclude"


def test_the_bearing_points_at_the_thing():
    """Every bearing agrees with the referent's real offset.

    The walking test proves it for the lines it could walk; this proves it for all of
    them, including the ones a wall blocked, by checking the compass word against the
    actual geometry.
    """
    _game_unused, said = _corpus()
    checked = 0
    for s in said:
        line, pos, (px, py) = s["line"], s["pos"], s["at"]
        heading = next((h for h in _HEADING if f"to the {h}," in line), None)
        if heading is None:
            assert "underfoot" in line, f"a line with no bearing at all: {line!r}"
            assert pos == (px, py), f"{line!r} claims underfoot but points at {pos}"
            continue
        assert heading == bearing(pos[0] - px, pos[1] - py), (
            f"{line!r} says {heading}, but it is at {pos} and you are at {(px, py)}")
        checked += 1
    assert checked >= 5, f"only {checked} bearings seen, too few to conclude"


def test_every_line_names_a_place():
    """Step 5 asks for "a bearing plus a note-derived proper noun", so both, every time."""
    _game_unused, said = _corpus()
    assert said, "the narrator never spoke"
    for s in said:
        line = s["line"]
        assert (" in " in line or " toward " in line or " out of " in line), \
            f"no place named: {line!r}"
        assert line.rstrip().endswith("."), f"not a sentence: {line!r}"


# --------------------------------------------------------------------- the budget

def test_at_most_one_ambient_line_per_turn():
    """The spec's cap, and it is enforced globally because several producers share the pipe.

    It matters more than it sounds: the message pane is five lines, so an unbudgeted
    ambient channel pushes the blow that is killing you off the screen.
    """
    for move in (False, True):
        game = _game()
        worst = 0
        for t in range(300):
            n0 = len(game.messages)
            if move:
                game.try_move(*[(1, 0), (0, 1), (-1, 0), (0, -1)][det.droll(f"b{t}", 4)])
            else:
                game.wait()
            fresh = sum(1 for tag in game.message_tags[n0:] if tag == "ambient")
            worst = max(worst, fresh)
        assert worst <= 1, f"{worst} ambient lines landed in one turn (move={move})"


def test_a_real_perception_outranks_the_place_murmur():
    """When both want the turn's one line, the one you can walk to wins.

    The place-voice timer fires from inside try_move, before the narrator has looked at
    the turn, so without ranking it would win every contested turn purely by going first.
    That is backwards: it has no referent, and the spec's whole thesis is that a line
    worth printing is a pointer.
    """
    game = _game()
    # Step off whatever turn the world was built on. Building a game can itself spend the
    # turn's one ambient line, and an earlier version of this test assumed a fresh budget
    # and started failing the moment the sample world changed. The budget is per turn, so
    # take a turn nobody has used.
    game.turn += 1
    game.log("a murmur with nowhere to go", ambient=True, ambient_rank=0)
    assert game.messages[-1].startswith("A murmur")
    game.log("a real thing to the east, in Somewhere", ambient=True, ambient_rank=2)
    assert game.messages[-1].startswith("A real thing"), "the ranked line did not take the slot"
    assert not any(m.startswith("A murmur") for m in game.messages), \
        "the murmur was left behind, so the turn now holds two ambient lines"
    assert len(game.messages) == len(game.message_tags), "replacing a line desynced the tags"

    # and not the other way round
    game.turn += 1
    game.log("another real thing", ambient=True, ambient_rank=2)
    game.log("a later murmur", ambient=True, ambient_rank=0)
    assert not any(m.startswith("A later murmur") for m in game.messages)


def test_standing_still_makes_the_world_speak():
    """Step 6b. Waiting is the verb that should let a place breathe, so it must pay off.

    Before this, `_ambient_tick` was reachable only from `try_move`: the world spoke when
    you walked and fell silent when you stopped, which is the exact inversion.

    The rate is tested at the DECISION, not by comparing two playthroughs. Two earlier
    drafts compared playthroughs, one wandering and one pacing in place, and both passed
    even when standing still was given no advantage whatsoever: `wait` also rests, heals
    and ticks tension, so no walking control holds the rest of the world equal, and the
    difference that showed up was geography. What can be held equal is the gate.
    """
    game = _game()
    narrator = game.system("narrator")

    # A silence long enough for a standing listener, too short for a walking one.
    opened, shut = 0, 0
    for turn in range(_GAP_STILL, _GAP_MOVING):
        narrator._last_line_turn = game.turn - turn
        if narrator._may_speak(game, stood_still=True):
            opened += 1
        if narrator._may_speak(game, stood_still=False):
            shut += 1
    assert opened > 0, "a standing listener never gets to speak inside the shorter gap"
    assert shut == 0, "a walking one should still be inside its own silence"

    # And when both are past their gap, the standing one is likelier to break it.
    narrator._last_line_turn = -999
    still = sum(narrator._may_speak(_at_turn(game, t), True) for t in range(400))
    moving = sum(narrator._may_speak(_at_turn(game, t), False) for t in range(400))
    assert still > moving, (
        f"past the silence, standing still broke it {still} times and moving {moving}; "
        "waiting is supposed to be when you hear things")

    # It should also actually produce lines in play, not merely be allowed to.
    assert len(_corpus()[1]) >= 5, "in a real session, standing still said almost nothing"


def _at_turn(game, turn):
    """The same game, asked about a different turn. The gate is a function of the turn."""
    game.turn = turn
    return game


# ------------------------------------------------------------------ the senses contract

def test_only_sight_may_name_what_it_found():
    """SENSES_SPEC makes sound and smell LOCATING senses: a position, and no identity.

    So the registers must differ, and the far one must stay ignorant. This is what the
    spec means by "routed through sight/sound/smell so smell-only reads differently".
    """
    for kind in _ELEMENTS:
        seen, smelt, heard = _ELEMENT_VOICE[kind]
        assert len({seen, smelt, heard}) == 3, f"{kind} reads the same through every sense"

    game = _game()
    narrator = game.system("narrator")
    px, py = game.player.x, game.player.y

    prof = senses.PROFILES["player"]
    assert narrator._sense_of(game, (px, py)) == senses.SIGHT, "your own tile is visible"
    far = (px + prof.rng(senses.SOUND) - 1, py)
    assert narrator._sense_of(game, far) == senses.SOUND, "past sight, you can only hear"
    beyond = (px + prof.rng(senses.SOUND) + 5, py)
    assert narrator._sense_of(game, beyond) is None, "out of every range, say nothing"

    # No line the player could not see may name a creature.
    _game_unused, said = _corpus()
    for s in said:
        if s["sense"] == senses.SIGHT:
            continue
        for name in s["names"]:
            assert name not in s["line"], \
                f"a {s['sense']} line named {name!r}: {s['line']!r}"


def test_bearings_cover_the_compass():
    """The compass words are the vocabulary the acceptance test parses, so they must map."""
    assert bearing(0, 0) == "underfoot"
    for word, (dx, dy) in _HEADING.items():
        assert bearing(dx * 5, dy * 5) == word, f"{(dx, dy)} should read as {word}"


# ------------------------------------------------------------------- the guarantees

def _fingerprint(game):
    """Everything the narrator could conceivably disturb, except the log."""
    salvage, decay = game.system("salvage"), game.system("decay")
    react, flora = game.system("reactions"), game.system("flora")
    return {
        "turn": game.turn, "floor": game.floor, "alive": game.alive, "won": game.won,
        "player": (game.player.x, game.player.y, game.player.hp, game.player.defense),
        "actors": sorted((a.x, a.y, getattr(a, "hp", 0), getattr(a, "name", ""))
                         for a in game.actors),
        "matter": salvage.inventory(game).total() if salvage else 0,
        "corpses": sorted(getattr(decay, "corpses", {}) or {}),
        "props": sorted((p, tuple(sorted(k))) for p, k in
                        (getattr(react, "props", {}) or {}).items()),
        "plants": sorted(getattr(flora, "plants", ()) or ()),
    }


def test_the_narrator_moves_no_number():
    """A narrator may produce text and nothing else.

    The measured balance baseline (22 of 48, commune 10 / standing 6 / boss_killed 4 /
    truths 2) is only worth anything if nothing since has moved the game.

    This asserts the property directly instead of comparing two whole playthroughs,
    because a playthrough is not a stable measuring stick. Four runs of the *identical*
    configuration, each with its own fresh HOME, in one process, gave matter totals of
    3, 4, 5 and 7. So an end-state comparison would have reported a difference the
    narrator did not cause, and in an earlier draft it did exactly that. Fingerprinting
    around the hook is immune to that noise and is a stronger claim besides: not "the
    outcome happened to match" but "this system wrote nothing".
    """
    game = _game()
    narrator = game.system("narrator")
    assert narrator is not None, "the narrator is not in the stack"

    # Run a while so there is real state, and real deltas, for it to chew on.
    _listen(game, 120)

    for _ in range(120):
        game.wait()
        before = _fingerprint(game)
        narrator.on_player_act(game)      # the hook, on its own, twice in a row
        after = _fingerprint(game)
        assert before == after, (
            "the narrator mutated game state: "
            + str([k for k in before if before[k] != after[k]]))


def test_the_ambient_tag_stays_aligned():
    """`message_tags` must track `messages` exactly, or every log filter silently dies.

    `show_log` only filters when the two lists are the same length, so one stray append
    turns `m:all / c:combat / d:discovery / a:ambient` into four buttons that all show
    everything. One site bypassed `log()` and did exactly that.
    """
    game = _game()
    _listen(game, 200)
    assert len(game.messages) == len(game.message_tags), "the log filters are dead"

    source = (pathlib.Path(__file__).resolve().parent.parent / "runtime" / "game.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    appends = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "log"):
            continue
        break
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "append"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "messages"):
            appends.append(node.lineno)
    assert len(appends) == 1, (
        f"self.messages.append at lines {appends}: every line must go through log(), "
        "which is what keeps message_tags aligned")
