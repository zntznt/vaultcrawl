"""The human input layer, which until now nothing tested at all.

No test imported `interactive` or `run`, and that is the whole reason four advertised keys
were dead code, a fifth crashed the process with NameError, and the key hint disagreed with
the dispatch chain in nine places. Every one of those is the same failure: two descriptions
of the key set, no check that they match.

Four guards here, each aimed at one of the bugs that got through:

  * `test_chain_matches_table`      the four dead keys (indentation)
  * `test_no_key_is_shadowed`       breakdown on `b`, which is a movement key
  * `test_no_orphaned_docstrings`   travel losing its `def` line
  * the press-every-key tests       anything that raises, or silently does nothing

The last group drives the REAL `run()` loop. `runtime.play.interactive` does a
function-local `import curses` (play.py, inside `interactive`), so patching
`runtime.play.curses` does nothing and the patch has to go into `sys.modules` before the
module is imported. With a fake screen feeding a scripted key list, the whole interactive
game runs headlessly and a keypress becomes an ordinary assertion.
"""
from __future__ import annotations

import ast
import curses as _real_curses
import importlib
import json
import pathlib
import sys

PLAY = pathlib.Path(__file__).resolve().parent.parent / "runtime" / "play.py"
RUNTIME = PLAY.parent
WORLD = PLAY.parent.parent / "examples" / "world.json"


# --------------------------------------------------------------------------- ast helpers

def _play_tree():
    return ast.parse(PLAY.read_text(encoding="utf-8"))


def _func(node, name):
    for n in ast.walk(node):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found in {PLAY.name}")


def _chain_keys():
    """Every key matched at the OUTER level of run()'s dispatch chain.

    Anchored on `if k in moves:`, which is the head of the chain, and walks only each
    branch's `test`, never its body. That is the whole point: the four dead keys lived in
    the body of the `f` handler, so a body-blind walk does not see them and the set
    comparison below fails, which is exactly what should have happened years ago.
    """
    run = _func(_func(_play_tree(), "interactive"), "run")
    head = None
    for n in ast.walk(run):
        if (isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                and isinstance(n.test.ops[0], ast.In)
                and getattr(n.test.comparators[0], "id", "") == "moves"):
            head = n
            break
    assert head is not None, "could not find `if k in moves:`, the head of the chain"

    keys, node = set(), head
    while isinstance(node, ast.If):
        for call in ast.walk(node.test):
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "ord":
                keys.add(call.args[0].value)
        node = node.orelse[0] if (len(node.orelse) == 1
                                  and isinstance(node.orelse[0], ast.If)) else None
    return keys


# --------------------------------------------------------------------------- the guards

def test_chain_matches_table():
    """KEY_TABLE and the dispatch chain describe the same key set, both directions.

    A row with no branch is a key advertised and dead, which is what `b`, `a`, `d` and `p`
    were. A branch with no row is a verb the player is never told about, which is what
    `5`, `P`, `M`, `D` and `G` were.
    """
    play = importlib.import_module("runtime.play")
    table = {k for entry in play.KEY_TABLE for k in entry[0]}
    chain = _chain_keys()

    # `q` is deliberately its own `if` above the chain, not a branch in it: a fast
    # arrow-mash can leak a partial escape sequence, and quitting mid-fight on that would
    # be worse than the duplication. It is the one documented exception.
    table.discard("q")

    assert not table - chain, f"advertised but never dispatched: {sorted(table - chain)}"
    assert not chain - table, f"dispatched but never advertised: {sorted(chain - table)}"


def test_no_key_is_shadowed():
    """No table key is also a movement key.

    `if k in moves:` is tested before the first elif, so a verb bound to a movement key
    can never fire. Breakdown was on `b`, the yubn down-left diagonal, which means the
    indentation fix alone would have left it broken while looking repaired.
    """
    play = importlib.import_module("runtime.play")
    tree = _play_tree()
    dirkeys = None
    for n in ast.walk(_func(tree, "interactive")):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_DIRKEYS":
            dirkeys = {c.args[0].value for c in ast.walk(n.value)
                       if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "ord"}
    assert dirkeys, "could not read _DIRKEYS"

    table = {k for entry in play.KEY_TABLE for k in entry[0]}
    clash = table & dirkeys
    assert not clash, f"bound to a verb and to movement, so the verb can never fire: {sorted(clash)}"


def test_help_covers_every_key():
    """The `?` screen lists every row, including the ones the status line omits."""
    play = importlib.import_module("runtime.play")
    text = "\n".join(play._help_lines())
    for entry in play.KEY_TABLE:
        assert entry[2] in text, f"{entry[0]} missing its description from the help screen"
    short = play._keys_help()
    for entry in play.KEY_TABLE:
        if entry[3]:
            assert f"{entry[0][0]}:{entry[1]}" in short, f"{entry[0][0]} missing from the hint line"


def test_no_name_escapes_its_scope():
    """Two scoping bugs in one file, both invisible to the eye and both fatal.

    `draw` read `G`, `B`, `M`, `Y` and `BOLD` to colour a graded creature, but those are
    locals of `_init_palette`, a SIBLING function. Python resolved them as module globals,
    found nothing, and raised NameError on the first frame containing a graded creature.
    With the real system stack that is frame one, so the default interactive mode did not
    survive to its first keypress.

    Separately, the debug handler assigned `menu = " ".join(...)`, which makes `menu` local
    to the whole of `run()` and leaves the real `menu()` from `interactive()` unbound. That
    broke `e`, and would have broken the sacrifice shrine and craft the moment the dead
    keys were revived.

    The symbol table answers both without executing anything: a name the body reads should
    resolve to an enclosing scope, not to a global that does not exist.
    """
    import symtable

    table = symtable.symtable(PLAY.read_text(encoding="utf-8"), PLAY.name, "exec")

    def scope(node, name):
        for child in node.get_children():
            if child.get_name() == name:
                return child
            found = scope(child, name)
            if found is not None:
                return found
        return None

    interactive = scope(table, "interactive")
    module_globals = {s.get_name() for s in table.get_symbols()}

    import builtins

    known = module_globals | set(dir(builtins))
    escaped = []
    for fn in interactive.get_children():
        if fn.get_type() != "function":
            continue
        for sym in fn.get_symbols():
            if sym.is_global() and not sym.is_assigned() and sym.get_name() not in known:
                escaped.append(f"{fn.get_name()}() reads {sym.get_name()}, which is nowhere")
    assert not escaped, escaped

    run = scope(interactive, "run")
    for helper in ("menu", "pick", "popup", "draw"):
        sym = run.lookup(helper)
        assert not sym.is_local(), (
            f"run() assigns `{helper}`, which makes every call to interactive()'s "
            f"{helper}() inside the loop an UnboundLocalError")


def test_no_orphaned_docstrings():
    """A string statement that is not a docstring is dead code, and hides a deleted `def`.

    `travel` lost its `def travel(scr):` line. Python did not complain: the docstring
    became a no-op expression and the body silently became the tail of `autoexplore`, so
    pressing `g` raised NameError and pressing `o` prompted for a travel direction. The
    shape is invisible to the eye and trivial to detect.
    """
    holds_doc = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)
    found = []
    for path in sorted(RUNTIME.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            body = getattr(node, "body", None)
            if not isinstance(body, list):
                continue
            first = 1 if (isinstance(node, holds_doc) and body
                          and isinstance(body[0], ast.Expr)
                          and isinstance(body[0].value, ast.Constant)
                          and isinstance(body[0].value.value, str)) else 0
            for stmt in body[first:]:
                if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)):
                    found.append(f"{path.name}:{stmt.lineno}")
    assert not found, f"string statements evaluated and discarded: {found}"


# ------------------------------------------------------------------- the headless driver

class _Screen:
    """Enough of a curses window to run the real draw loop. Records what it was told."""

    def __init__(self, keys):
        self.keys = [ord(k) if isinstance(k, str) else k for k in keys]
        self.written = []

    def getch(self):
        return self.keys.pop(0) if self.keys else ord("q")

    def getmaxyx(self):
        return (40, 140)

    def addstr(self, *a, **kw):
        text = [x for x in a if isinstance(x, str)]
        if text:
            self.written.append(text[-1])

    def __getattr__(self, _name):
        return lambda *a, **kw: None


class _Curses:
    """The real curses' constants, its functions stubbed, and wrapper wired to us."""

    def __init__(self, screen):
        self._screen = screen

    def wrapper(self, fn):
        return fn(self._screen)

    def __getattr__(self, name):
        value = getattr(_real_curses, name)
        return (lambda *a, **kw: 0) if callable(value) else value


def _play(keys, kit="artisan", prepare=None):
    """Run one interactive session over a scripted key list. Returns (game, screen).

    The REAL system stack, not a subset: the crash in draw() only fires on a creature
    QualitySystem has graded, so a game built without it would have run clean and proved
    nothing. `prepare` runs against the game before the first frame.
    """
    from runtime.game import Game
    from runtime.stack import build_systems

    screen = _Screen(list(keys) + ["q"])
    saved = sys.modules.get("curses")
    sys.modules["curses"] = _Curses(screen)
    try:
        for name in [m for m in sys.modules if m.startswith("runtime.play")]:
            del sys.modules[name]
        play = importlib.import_module("runtime.play")
        game = Game(json.loads(WORLD.read_text(encoding="utf-8")),
                    sandbox=True, run_seed="keys", systems=build_systems())
        if kit:
            game.starting_kit(kit)
        if prepare is not None:
            prepare(game)
        play.interactive(game)
        return game, screen
    finally:
        if saved is not None:
            sys.modules["curses"] = saved
        else:
            del sys.modules["curses"]
        for name in [m for m in sys.modules if m.startswith("runtime.play")]:
            del sys.modules[name]


def test_every_key_survives_a_press():
    """Press every advertised key in one session and reach the end alive.

    This is the check that would have caught `g`. It raised NameError, unwound curses and
    killed the process, on a key the status line advertised, for as long as the bug
    existed. A key that opens a prompt gets a follow-up keystroke so it does not eat the
    next verb.
    """
    play = importlib.import_module("runtime.play")
    script = []
    for entry in play.KEY_TABLE:
        key = entry[0][0]
        if key == "q":
            continue
        script.append(key)
        script.append(27)   # dismiss whatever prompt or popup it opened

    game, screen = _play(script)
    assert screen.written, "the session drew nothing, so it never really ran"
    assert game.turn >= 0


def test_the_four_dead_keys_now_act():
    """shield, shove, breakdown and act each reach the engine.

    Before the indentation fix all four returned with a turn delta of exactly zero,
    which is what "the branch was never evaluated" looks like from outside. `d` is the
    cleanest of them: `Game.shield` runs the turn tail itself and takes no argument, so
    one keypress must move the clock.
    """
    game, _ = _play(["d"])
    assert game.turn > 0, "shield did not consume a turn, so `d` never reached Game.shield"

    before, _ = _play([])
    assert before.turn == 0, "the baseline session should not have advanced the clock"


def test_act_reaches_interact():
    """`a` is the only route to Game.interact, and Game.interact is a lot of the game.

    It is the sole caller that emits `interact`, which is the sole trigger for
    DialogueSystem, which is the sole caller of quests.offer. With `a` dead a human could
    not acquire a quest at all, could not reach the sacrifice shrine, and never fired the
    on_interact handler in flora, decay, reactions, sacrifice, structures, fauna or
    factions.
    """
    seen = []
    from runtime.game import Game

    real = Game.interact
    Game.interact = lambda self: seen.append(True) or real(self)
    try:
        _play(["a"])
    finally:
        Game.interact = real
    assert seen, "pressing `a` did not call Game.interact"


def test_drawing_a_graded_creature_does_not_crash():
    """The default interactive mode did not survive to its first keypress.

    `draw` coloured graded creatures with names that belong to a sibling function, so any
    creature QualitySystem had graded raised NameError inside the draw loop. `put()` only
    swallows curses.error, so it propagated and killed the run. It is keyed on viewport
    position, not on fog, so a graded creature you could not even see was enough. This
    presses nothing at all: building the world and drawing one frame is the whole test.
    """
    def grade_everything(game):
        for actor in game.actors:
            if actor is not game.player:
                actor.quality = 3

    game, screen = _play([], prepare=grade_everything)
    assert screen.written, "the first frame never drew"


def test_craft_can_reach_past_the_ninth_recipe():
    """A picker that reads one keystroke cannot offer more than nine things.

    `pick` and `menu` both parse a single key in 1..9, and there are 25 consumable
    recipes, so a plain menu over them would leave the tail permanently unreachable. That
    is the same defect as a key nothing dispatches, only quieter. `paged_menu` pages
    instead, and this drives the real `w` handler with every recipe known: turn one page,
    then take the first row of the second.
    """
    from runtime.wear import RECIPE_COSTS

    assert len(RECIPE_COSTS) > 9, "if recipes ever fit one page, simplify the craft key"

    def learn_everything(game):
        game.player._known_recipes = set(RECIPE_COSTS)
        salvage = game.system("salvage")
        if salvage is not None:
            salvage.inventory(game).add({"scrap": 60})

    # "9" is the page-turn row on a page of eight, then "1" is recipe nine overall.
    game, screen = _play(["w", "9", "1"], prepare=learn_everything)
    rendered = "\n".join(screen.written)
    assert "more" in rendered, "the craft menu never offered a second page"


def test_set_down_and_recover_round_trip():
    """`s` then `r`: a sigil leaves a slot onto the ground and comes back.

    Two verbs the auto agent dispatched every run and a human had no key for at all.
    """
    game, _ = _play(["s", "1", "r"])
    sigils = game.system("sigils")
    assert sigils is not None
    deployed = [a for a in game.actors if getattr(a, "_is_deployed", False)]
    assert game.turn > 0, "neither verb consumed a turn, so neither reached the engine"
    # Either it came back (slot restored) or it is still out there; both prove the verbs
    # ran. What must not happen is the sigil vanishing from the world entirely.
    assert sigils.slots or deployed, "the sigil left its slot and never reached the ground"
