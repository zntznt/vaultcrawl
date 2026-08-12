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
  emitted   events it broadcast while it held the floor
  logged    lines it wrote to the player

**`acted` watches the system's own `__dict__`, so a system that acts on the game while
keeping no state of its own reads as zero.** `forge` proved it: `acted` 0 with 123 events
emitted in one classic run, which an earlier version of this file called dead by design. It
was wrong, and ablation independently shows `forge` opening a win route. Silence therefore
requires all three of acted, emitted and logged to be empty, never `acted` alone. The snapshot
is also shallow, so a mutation buried inside a nested object is missed. Both errors point the
same way: this undercounts activity, so anything it reports as acting definitely acted.

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


def instrument(systems: list, stats: dict, current: list) -> None:
    """Wrap every hook on every system so calls, state changes and output are counted."""
    for s in systems:
        name = getattr(s, "name", repr(s))
        stats.setdefault(name, collections.Counter())
        for hook in HOOKS:
            orig = getattr(s, hook, None)
            if orig is None:
                continue
            setattr(s, hook, _wrap(s, name, hook, orig, stats, current))


def _wrap(sysobj, name, hook, orig, stats, current):
    def wrapped(*a, **kw):
        stats[name]["hooks"] += 1
        stats[name][hook] += 1
        before = _snap(sysobj)
        current.append(name)
        try:
            return orig(*a, **kw)
        finally:
            current.pop()
            if _snap(sysobj) != before:
                stats[name]["acted"] += 1
    return wrapped


def verdict(c: collections.Counter) -> str:
    hooks, acted = c["hooks"], c["acted"]
    speaks = bool(c["emitted"] or c["logged"])
    if hooks == 0:
        return "never called"
    if acted == 0 and not speaks:
        return "silent"
    if acted == 0:
        return "stateless"
    if not speaks and acted / hooks > MUTE_BUSY:
        return "busy and mute"
    return "active"


def measure(world: str, sandbox: bool = False, agent: str = "seeker",
            run_seed: str = "activity", max_floor: int = 0) -> tuple:
    """Run one instrumented game. Returns (stats, RunResult)."""
    import runtime.agent_eval as ev
    from runtime.game import Game as RealGame
    from runtime.stack import build_systems

    systems = build_systems()
    stats: dict = {}
    current: list = []
    instrument(systems, stats, current)

    # The harness owns descent, so the harness has to drive. A hand-rolled stepping loop spent
    # 2,500 decisions on floor 1 and made every system that only wakes at depth look dead for
    # entirely the wrong reason.
    if sandbox:
        def SandboxGame(manifest, *a, **kw):
            kw["sandbox"] = True
            return RealGame(manifest, *a, **kw)
        ev.Game = SandboxGame
    ctor = ev.Game

    def CountingGame(manifest, *a, **kw):
        g = ctor(manifest, *a, **kw)
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
    if not max_floor:
        from runtime.ablate import SANDBOX_MAX_FLOOR
        max_floor = SANDBOX_MAX_FLOOR if sandbox else 99
    result = ev.run_agent(world, agent, run_seed=run_seed, max_floor=max_floor)
    return stats, result


def report(stats: dict, result=None, mode: str = "classic") -> None:
    if result is not None:
        print(f"\n{mode}: floor {result.floor_reached}, {result.turns_survived} turns, "
              f"won={result.won} died={bool(result.cause_of_death)}\n")
    print(f"{'system':14}{'hooks':>9}{'acted':>8}{'act%':>7}{'emitted':>9}{'logged':>8}"
          f"  verdict")
    for name, c in sorted(stats.items(), key=lambda kv: (kv[1]["acted"], kv[1]["hooks"])):
        h, a = c["hooks"], c["acted"]
        print(f"{name:14}{h:9}{a:8}{(a / h if h else 0):7.1%}{c['emitted']:9}"
              f"{c['logged']:8}  {verdict(c)}")
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
    ap.add_argument("--sandbox", action="store_true")
    ap.add_argument("--agent", default="seeker")
    ap.add_argument("--seed", default="activity")
    args = ap.parse_args(argv)
    stats, result = measure(args.world, args.sandbox, args.agent, args.seed)
    report(stats, result, "sandbox" if args.sandbox else "classic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
