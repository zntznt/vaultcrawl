"""Entry point.

    python -m runtime.play world.json --auto --floors 3   # headless, deterministic demo
    python -m runtime.play world.json                      # interactive curses (needs a TTY)

The auto-demo drives a BFS agent that descends toward the stairs and fights what blocks
it -- enough to show layout, depth-banded spawns, combat, and loot without a keyboard.
"""
from __future__ import annotations

import argparse
import sys
from collections import deque

from .game import Game, load_manifest


def bfs_step(level, start, goal, avoid=None):
    """First (dx, dy) along the shortest floor path from start to goal, or None.
    Tiles in `avoid` are treated as blocked (except the goal itself)."""
    avoid = avoid or set()
    if start == goal:
        return (0, 0)
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        x, y = cur
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt not in prev and level.walkable(*nxt) and (nxt not in avoid or nxt == goal):
                prev[nxt] = cur
                q.append(nxt)
    if goal not in prev:
        return None
    cur = goal
    while prev[cur] != start:
        cur = prev[cur]
    return (cur[0] - start[0], cur[1] - start[1])


def auto_play(game: Game, floors: int, max_turns: int = 500):
    """Drive the descent through the PLAYER'S BRAIN. The brain handles fight/flee/lure/loot;
    this loop only descends when the brain has nothing left to do on the floor, and nudges
    toward the stairs to avoid a stall."""
    transcript = [game.render()]
    cleared = 0
    while game.alive and not game.won and cleared < floors:
        turns = 0
        while game.alive and not game.won:
            ppos = (game.player.x, game.player.y)
            adj_threat = any(max(abs(a.x - ppos[0]), abs(a.y - ppos[1])) == 1
                             and game._hostile("player", a.allegiance) for a in game.actors)
            has_poi = bool(game.items) or any(s.points_of_interest(game) for s in game.systems)
            if game.on_stairs() and not adj_threat and not has_poi:
                break
            dx, dy = game.player.brain.decide(game, game.player)
            if dx == 0 and dy == 0:
                if game.on_stairs():
                    break
                step = bfs_step(game.level, ppos, game.level.stairs)   # anti-stall
                if not step or step == (0, 0):
                    break
                dx, dy = step
            game.try_move(dx, dy)
            turns += 1
            if turns > max_turns:
                game.log("(no progress — abandoning floor)")
                break
        if not game.alive or game.won:
            break
        cleared += 1
        if cleared < floors:
            game.descend()
            transcript.append(game.render())
    return transcript, cleared


def interactive(game: Game) -> int:
    import curses

    def run(scr):
        curses.curs_set(0)
        moves = {curses.KEY_UP: (0, -1), curses.KEY_DOWN: (0, 1),
                 curses.KEY_LEFT: (-1, 0), curses.KEY_RIGHT: (1, 0),
                 ord("k"): (0, -1), ord("j"): (0, 1), ord("h"): (-1, 0), ord("l"): (1, 0)}
        while True:
            scr.erase()
            for i, line in enumerate(game.render().split("\n")):
                try:
                    scr.addstr(i, 0, line)
                except curses.error:
                    pass
            scr.refresh()
            if game.won or not game.alive:
                scr.getch()
                return
            k = scr.getch()
            if k in (ord("q"), 27):
                return
            if k in moves:
                game.try_move(*moves[k])
            elif k in (ord(">"), ord(".")) and game.on_stairs():
                game.descend()

    curses.wrapper(run)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Play a baked vaultcrawl world.")
    ap.add_argument("world", help="path to world.json")
    ap.add_argument("--auto", action="store_true", help="run the headless auto-demo")
    ap.add_argument("--floors", type=int, default=3, help="auto-demo: floors to descend")
    ap.add_argument("--evolve-from", metavar="OLD",
                    help="play `world` with the chronicle from OLD->world overlaid as live upheaval")
    ap.add_argument("--width", type=int, default=56)
    ap.add_argument("--height", type=int, default=20)
    ap.add_argument("--no-systems", action="store_true",
                    help="disable the Qud/Cogmind-inspired systems layer (sigils, reactions, ...)")
    ap.add_argument("--brain", default="exploiter",
                    help="player brain: exploiter (default), survivor, hunter/dumb")
    ap.add_argument("--sandbox", action="store_true",
                    help="grow the WHOLE vault as one persistent open-world map (no floors)")
    a = ap.parse_args(argv)

    manifest = load_manifest(a.world)
    upheaval = None
    if a.evolve_from:
        try:
            from vaultcrawl.evolve import evolve
        except ImportError:
            print("error: run from the project root so the `vaultcrawl` package is importable.",
                  file=sys.stderr)
            return 2
        from .upheaval import Upheaval
        events = evolve(load_manifest(a.evolve_from), manifest)
        upheaval = Upheaval.from_events(events)

    systems = []
    if not a.no_systems:
        from .senses import SenseField
        from .memory import MemorySystem
        from .sigils import SigilSystem
        from .reactions import ReactionSystem
        from .weather import WeatherSystem
        from .flora import FloraSystem
        from .structures import StructureSystem
        from .decay import DecaySystem
        from .fauna import FaunaSystem
        from .salvage import SalvageSystem
        from .forge import ForgeSystem
        from .quests import QuestSystem
        from .dialogue import DialogueSystem
        from .machines import MachineSystem
        from .factions import FactionSystem
        from .history import HistorySystem
        from .knowledge import KnowledgeSystem
        from .quality import QualitySystem
        from . import abilities  # noqa: F401  (registers creature special actions)
        # Order matters: sigils first (Echo can revive a just-killed player); reactions
        # before the substrate-writers (weather/flora/structures) so they see seeded
        # tiles; decay before fauna (scavengers query corpses); knowledge LAST so its fog
        # paints over every other overlay.
        systems = [SenseField(), MemorySystem(), SigilSystem(), ReactionSystem(), WeatherSystem(),
                   FloraSystem(), StructureSystem(), DecaySystem(), FaunaSystem(),
                   SalvageSystem(), ForgeSystem(),   # salvage pools matter, then forge spends it
                   QuestSystem(), DialogueSystem(), MachineSystem(),   # objectives · NPCs · machines
                   FactionSystem(), QualitySystem(),   # quality grades all spawned foes (incl. hunters)
                   HistorySystem(), KnowledgeSystem()]

    game = Game(manifest, a.width, a.height, upheaval=upheaval, systems=systems,
                architecture=a.sandbox)

    # Register the brain tiers (import = registration), then give the player its chosen
    # brain. Monsters get theirs lazily by tier via brain_for: tier-1 grunts charge (hunter),
    # tough foes/hunters/bosses scheme (tactician), wildlife forages.
    from . import (brains, tactics, creatures, planner, instincts)  # noqa: F401
    # ^ registers brain tiers (hunter…tactician/exploiter, mastermind/tracker/wary) + profiles
    from .sense import make_brain
    game.player.brain = make_brain(game, game.player,
                                   name="hunter" if a.brain == "dumb" else a.brain)
    headless = a.auto or not sys.stdin.isatty() or not sys.stdout.isatty()
    if headless:
        transcript, cleared = auto_play(game, a.floors)
        print("\n\n".join(transcript))
        outcome = "WON" if game.won else ("DIED" if not game.alive else f"descended {cleared} floor(s)")
        print(f"\n=== {outcome} | reached floor {game.floor} | "
              f"{game.kills} kills | {game.items_taken} items ===")
        return 0
    return interactive(game)


if __name__ == "__main__":
    raise SystemExit(main())
