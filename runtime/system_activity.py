"""Does a system that changes no outcome fire at all? Three answers, three different fixes.

Ablation (`runtime/ablate.py`) says roughly twenty of twenty-seven systems change no outcome.
That single result has causes that pull apart completely, and an ablation table cannot tell
them apart because the column it reports is the same in every case:

  never called    the stack does not invoke it. A wiring bug; the system may be fine.
  silent          called constantly, never acts, says nothing. Dead by design.
  busy and mute   heavy internal state and no output ON THE EVENT BUS. Read the caveat below
                  before concluding nobody listens.
  active          it acts and speaks, and the outcome still does not move. That is a balance
                  question, and only here is "the design is wrong" the right conclusion.

Four columns, measured over one instrumented run:

  hooks     how many times the game called into it
  acted     hook calls after which the system's own state changed
  touched   hook calls after which the PLAYER's state changed
  emitted   events it broadcast while it held the floor
  logged    lines it wrote to the player

**`acted` watches the system's own `__dict__`, so a system that acts elsewhere and keeps no
state of its own reads as zero.** This has produced two false "dead by design" verdicts
already. `forge`: `acted` 0 with 123 events emitted, while ablation shows it opening a win
route. `body`: `acted` 0 with nothing emitted or logged either, yet `on_floor_enter` calls
`init_body` on the player and every actor, which is most of what a body system is for. The
first was caught by the emitted column; the second slipped through it entirely, which is why
`touched` exists.

Silence therefore requires acted, touched, emitted and logged ALL empty, and even then it is a
screen rather than a verdict.

`body` is the worked example of why, and it still reads silent after `touched` was added. Two
things defeat the measurement at once. The stack fires `on_world_start` and `on_floor_enter`
inside `Game.__init__`, before a player exists to watch, so the initial `init_body` is invisible
by construction. And on later floors `init_body` rewrites `player.body` to a dict of the same
shape, which a snapshot keyed on length cannot see. Deepening the snapshot enough to catch that
would cost more than the answer is worth on an 18,000-hook run.

So: every error here points at undercounting, anything reported as active definitely is, and
**a silent verdict is a question for ablation, never an answer on its own.**

**`busy and mute` sees only `emit` and `log`, so a system read directly off its attributes
looks mute when it is anything but.** `senses` lands there and is consumed by every perception
call the agent makes. The verdict is a question, not an answer, and ablation settles it: mute
plus an ablation that changes nothing means genuinely unconsumed, which is `scent`, whose
removal left all 24 runs byte-identical. Mute plus an ablation that moves the game means
consumed by direct read, which is `senses`. Never quote this column without the other.

Measured on one winning run per mode (classic floor 27 in 6,235 turns; sandbox floor 3 in
1,900): **no system is ever unreached.** Every one is called about 18,000 times in classic and
5,100 in sandbox, so "the agent never engages it" is not the explanation for any of them.
Three are silent in both modes (`effects`, `sacrifice`, `body`), `portals` is silent in
sandbox only, and `scent` is the busy-and-mute case, acting on 11.1% of its classic calls
while emitting and logging nothing at all. That is exactly why dropping `scent` left all 24
ablation runs byte-identical: two instruments agreeing from opposite directions.

    PYTHONHASHSEED=0 python3 -m runtime.system_activity [--sandbox] [--agent seeker]
"""
from __future__ import annotations

import argparse
import collections

# The hooks a System exposes. `render_overlay` and `status_line` are deliberately absent:
# they are display, and a headless run never calls them, so counting them would report every
# system as partly unreachable for a reason that has nothing to do with the game.
HOOKS = ("on_world_start", "on_floor_enter", "on_player_act", "on_enemy_killed",
         "on_event", "on_interact", "points_of_interest", "hazard_tiles")

# Above this share of calls, a system with no output at all is doing enough work that its
# silence is the finding rather than a rounding error.
MUTE_BUSY = 0.05


def _snap(sysobj) -> dict:
    """Shallow, cheap, and stable enough to compare twice in a row."""
    out = {}
    for k, v in vars(sysobj).items():
        try:
            if isinstance(v, (int, float, str, bool, type(None))):
                out[k] = v
            elif isinstance(v, (list, tuple, set, dict)):
                out[k] = len(v)
            else:
                out[k] = repr(v)[:80]
        except Exception:
            out[k] = "?"
    return out


def instrument(systems: list, stats: dict, current: list, player=None) -> None:
    """Wrap every hook on every system so calls, state changes and output are counted.

    `player` is optional and may be supplied later via `set_player`; the game does not exist
    yet when the systems are built.
    """
    for s in systems:
        name = getattr(s, "name", repr(s))
        stats.setdefault(name, collections.Counter())
        for hook in HOOKS:
            orig = getattr(s, hook, None)
            if orig is None:
                continue
            setattr(s, hook, _wrap(s, name, hook, orig, stats, current))


# The player, once a game exists. A system that acts only on the player reads as silent
# without this, which is exactly how `body` was misclassified.
_PLAYER: list = []


def set_player(p) -> None:
    _PLAYER[:] = [p]


def _wrap(sysobj, name, hook, orig, stats, current):
    def wrapped(*a, **kw):
        stats[name]["hooks"] += 1
        stats[name][hook] += 1
        before = _snap(sysobj)
        pbefore = _snap(_PLAYER[0]) if _PLAYER else None
        current.append(name)
        try:
            return orig(*a, **kw)
        finally:
            current.pop()
            if _snap(sysobj) != before:
                stats[name]["acted"] += 1
            if pbefore is not None and _snap(_PLAYER[0]) != pbefore:
                stats[name]["touched"] += 1
    return wrapped


def verdict(c: collections.Counter) -> str:
    hooks, acted = c["hooks"], c["acted"]
    speaks = bool(c["emitted"] or c["logged"])
    if hooks == 0:
        return "never called"
    if acted == 0 and not speaks and not c["touched"]:
        return "silent"
    if acted == 0:
        return "stateless"
    if not speaks and acted / hooks > MUTE_BUSY:
        return "busy and mute"
    return "active"


def measure(world: str, sandbox: bool = True, agent: str = "seeker",
            run_seed: str = "activity", max_floor: int = 0) -> tuple:
    """Run one instrumented game. Returns (stats, RunResult)."""
    import runtime.agent_eval as ev
    from runtime.stack import build_systems

    systems = build_systems()
    stats: dict = {}
    current: list = []
    instrument(systems, stats, current)

    # The harness owns descent, so the harness has to drive. A hand-rolled stepping loop spent
    # 2,500 decisions on floor 1 and made every system that only wakes at depth look dead for
    # entirely the wrong reason.
    ctor = ev.Game

    def CountingGame(manifest, *a, **kw):
        g = ctor(manifest, *a, **kw)
        set_player(g.player)
        _emit, _log = g.emit, g.log

        def emit(etype, **data):
            if current:
                stats[current[-1]]["emitted"] += 1
            return _emit(etype, **data)

        def log(msg):
            if current:
                stats[current[-1]]["logged"] += 1
            return _log(msg)

        g.emit, g.log = emit, log
        return g

    ev.Game = CountingGame
    ev._build_systems = lambda: systems
    result = ev.run_agent(world, agent, run_seed=run_seed, max_floor=max_floor or None,
                          sandbox=sandbox)
    return stats, result


def report(stats: dict, result=None, mode: str = "classic") -> None:
    if result is not None:
        print(f"\n{mode}: floor {result.floor_reached}, {result.turns_survived} turns, "
              f"won={result.won} died={bool(result.cause_of_death)}\n")
    print(f"{'system':14}{'hooks':>9}{'acted':>8}{'act%':>7}{'touched':>9}{'emitted':>9}"
          f"{'logged':>8}  verdict")
    for name, c in sorted(stats.items(), key=lambda kv: (kv[1]["acted"], kv[1]["hooks"])):
        h, a = c["hooks"], c["acted"]
        print(f"{name:14}{h:9}{a:8}{(a / h if h else 0):7.1%}{c['touched']:9}"
              f"{c['emitted']:9}{c['logged']:8}  {verdict(c)}")
    tally = collections.Counter(verdict(c) for c in stats.values())
    print("\n  " + "   ".join(f"{k} {v}" for k, v in tally.most_common()))
    dead = sorted(n for n, c in stats.items() if verdict(c) in ("silent", "never called"))
    mute = sorted(n for n, c in stats.items() if verdict(c) == "busy and mute")
    if dead:
        print(f"  silent or unreached: {dead}")
    if mute:
        print(f"  busy and mute on the event bus: {mute}")
        print(f"     Cross-check each against ablation. Unmoved by its own removal means "
              f"genuinely\n     unconsumed; moved means read directly off its attributes, "
              f"as `senses` is.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("world", nargs="?", default="examples/world.json")
    ap.add_argument("--classic", action="store_true",
                    help="measure the retired classic descent instead of the sandbox")
    ap.add_argument("--agent", default="seeker")
    ap.add_argument("--seed", default="activity")
    args = ap.parse_args(argv)
    stats, result = measure(args.world, not args.classic, args.agent, args.seed)
    report(stats, result, "classic" if args.classic else "sandbox")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
