"""Two games in one process must not be able to tell that the other happened.

CLAUDE.md invariant 4 is "determinism first", and the project already knew about state
carried between runs through `~/.vaultcrawl`. This is the other half, and it is worse
because a fresh HOME does not help: module globals live in RAM.

Measured before the fix, on the identical configuration with a fresh HOME per run, eight
runs in one process gave matter totals of

    3, 4, 5, 7, 7, 7, 9, 9

while one run per fresh interpreter gave 3 every time. The cause was not exotic. The
foraging skill tier is added to every scrap heap you pick, `exercise_skill` accumulates it
in a module-level singleton, and `reset_run_state()` (which clears exactly this, and whose
own docstring says "call this at the start of every run") was called only by `agent_eval`
and `run_agents.py`. Anything else that built two Games in one process, the whole test
suite included, inherited the previous run's skills.

The fix is one call, moved to where a run actually begins: `Game.__init__`.

Two things this protects that are not obvious:

  * Every balance number this project quotes. A batch harness that forgot the reset was
    reporting position-in-batch as though it were agent skill.
  * Any test that builds more than one Game, which is most of them. Before the fix, test
    order could change test results.
"""
from __future__ import annotations

from runtime import det
from runtime.game import Game, load_manifest
from runtime.stack import build_systems


def _run(turns=120, seed="isolation"):
    game = Game(load_manifest("examples/world.json"), sandbox=True,
                run_seed=seed, systems=build_systems())
    game.starting_kit("seeker")
    for t in range(turns):
        if det.droll(f"iso{t}", 3):
            game.try_move(*[(1, 0), (0, 1), (-1, 0), (0, -1)][det.droll(f"isod{t}", 4)])
        else:
            game.wait()
    salvage = game.system("salvage")
    return {
        "turn": game.turn, "hp": game.player.hp,
        "pos": (game.player.x, game.player.y),
        "actors": len(game.actors),
        "matter": salvage.inventory(game).total() if salvage else 0,
    }


def test_a_second_game_starts_where_the_first_one_did():
    """The regression itself. Same config, three times, one process, same answer."""
    runs = [_run() for _ in range(3)]
    assert runs[0] == runs[1] == runs[2], (
        f"three identical runs in one process disagreed: {runs}")


def test_skills_do_not_survive_a_new_game():
    """The specific leak, named, so a future reset that drops proficiency still fails here.

    Foraging is the one that was caught, because its tier is added to every scrap heap and
    a heap is picked in almost any run. Diplomacy and the rest leaked identically.
    """
    from runtime.proficiency import exercise_skill, skills

    for _ in range(40):
        exercise_skill("foraging")
    assert skills().tier("foraging") > 0, "the test could not raise a tier to begin with"

    Game(load_manifest("examples/world.json"), sandbox=True,
         run_seed="isolation", systems=build_systems())
    assert skills().tier("foraging") == 0, \
        "a new Game inherited the previous run's foraging tier"


def test_the_heap_reports_what_it_actually_gave():
    """The log said one thing and the inventory did another.

    `_collect_heaps` adds the foraging tier to the take but logged the base amount, so a
    skilled forager was told a smaller number than they received. It also meant two runs
    that granted different amounts produced byte-identical logs, which is precisely why
    the leak above went unnoticed: the message trace matched perfectly while the totals
    did not.
    """
    from runtime.proficiency import exercise_skill, skills

    game = Game(load_manifest("examples/world.json"), sandbox=True,
                run_seed="isolation", systems=build_systems())
    salvage = game.system("salvage")
    assert salvage is not None and salvage.heaps, "no heaps on this floor to pick"

    for _ in range(40):
        exercise_skill("foraging")
    tier = skills().tier("foraging")
    assert tier > 0, "could not raise foraging, so the claim is untested"

    pos = next(p for p, h in salvage.heaps.items() if not h["depleted"])
    base = salvage.heaps[pos]["matter"]
    before = salvage.inventory(game).total()
    n = len(game.messages)
    game.player.x, game.player.y = pos
    salvage._collect_heaps(game)

    gained = salvage.inventory(game).total() - before
    said = [m for m in game.messages[n:] if "pick through the trash" in m]
    assert gained == base + tier, f"expected {base} + {tier}, got {gained}"
    assert said, "picking a heap said nothing"
    assert f"({gained} scrap)" in said[0], \
        f"gave {gained} but reported {said[0]!r}"
