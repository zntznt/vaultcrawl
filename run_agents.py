"""Headless multi-agent runner — stress-tests all 6 player brains across
the same world.json, captures per-agent stats, and saves audit trails.

    python3 run_agents.py [world.json] [--floors N]

Outputs:
    ~/.vaultcrawl/audit/runs.json         — per-agent summary
    ~/.vaultcrawl/audit/{agent}_messages.json  — full message log
    ~/.vaultcrawl/forge/{seed}.json       — persistent forge state
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

DEFAULT_WORLD = str(ROOT / "examples" / "world.json")
AUDIT_DIR = Path(os.path.expanduser("~/.vaultcrawl/audit"))
FORGE_DIR = Path(os.path.expanduser("~/.vaultcrawl/forge"))
AGENT_NAMES = ["artisan", "cartographer", "emergent", "exploiter", "seeker", "whisper"]


@dataclass
class RunStats:
    agent: str
    alive: bool
    won: bool
    floor: int
    turns: int
    kills: int
    items_taken: int
    hp: int
    max_hp: int
    atk: int
    defense: int
    messages: list[str]


def ensure_world(path: str = DEFAULT_WORLD) -> str:
    if os.path.exists(path):
        return path
    print(f"world.json not found at {path}, baking from sample_vault...")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "vaultcrawl.bake", "sample_vault", "-o", path],
        check=True, cwd=str(ROOT),
    )
    return path


def build_systems():
    from runtime.senses import SenseField
    from runtime.memory import MemorySystem
    from runtime.sigils import SigilSystem
    from runtime.reactions import ReactionSystem
    from runtime.weather import WeatherSystem
    from runtime.flora import FloraSystem
    from runtime.structures import StructureSystem
    from runtime.decay import DecaySystem
    from runtime.fauna import FaunaSystem
    from runtime.salvage import SalvageSystem
    from runtime.forge import ForgeSystem
    from runtime.scent import ScentSystem
    from runtime.body_parts import BodySystem
    from runtime.terrain_mod import TerrainModSystem
    from runtime.portals import PortalSystem
    from runtime.sacrifice import SacrificeSystem
    from runtime.quests import QuestSystem
    from runtime.dialogue import DialogueSystem
    from runtime.machines import MachineSystem
    from runtime.caches import CacheSystem
    from runtime.factions import FactionSystem
    from runtime.history import HistorySystem
    from runtime.marginalia import MarginaliaSystem
    from runtime.knowledge import KnowledgeSystem
    from runtime.effects import EffectSystem
    from runtime.quality import QualitySystem
    import runtime.abilities  # noqa: F401

    return [
        SenseField(), MemorySystem(), SigilSystem(), ReactionSystem(), WeatherSystem(),
        FloraSystem(), StructureSystem(), DecaySystem(), FaunaSystem(),
        SalvageSystem(), ForgeSystem(),
        ScentSystem(),
        QuestSystem(), DialogueSystem(), MachineSystem(),
        CacheSystem(),
        TerrainModSystem(),
        PortalSystem(),
        SacrificeSystem(),
        FactionSystem(), BodySystem(), QualitySystem(),
        HistorySystem(), MarginaliaSystem(), KnowledgeSystem(),
        EffectSystem(),
    ]


def register_all_brains():
    from runtime import brains, tactics, planner, instincts  # noqa: F401
    # Agent brain modules — each registers at import time
    from runtime import agent  # noqa: F401  — universal brain


def auto_play(game, floors: int, max_turns: int = 500):
    """Drive the descent through the player's brain. Same logic as runtime.play.auto_play."""
    from collections import deque
    from runtime.agent_action import AgentAction, dispatch as _dispatch

    def bfs_step(level, start, goal, avoid=None):
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

    cleared = 0
    while game.alive and not game.won and cleared < floors:
        turns = 0
        while game.alive and not game.won:
            ppos = (game.player.x, game.player.y)
            adj_threat = any(max(abs(a.x - ppos[0]), abs(a.y - ppos[1])) == 1
                             and game.hostile(game.player, a) for a in game.actors)
            has_poi = bool(game.items) or any(s.points_of_interest(game) for s in game.systems)
            if game.on_stairs() and not adj_threat and not has_poi:
                break
            result = game.player.brain.decide(game, game.player)
            if isinstance(result, tuple) and len(result) == 2:
                result = AgentAction("move", dx=result[0], dy=result[1])
            ok = _dispatch(game, result)
            if not ok:
                if game.on_stairs():
                    break
                step = bfs_step(game.level, ppos, game.level.stairs)
                if not step or step == (0, 0):
                    break
                _dispatch(game, AgentAction("move", dx=step[0], dy=step[1]))
            turns += 1
            if turns > max_turns:
                game.log("(no progress — abandoning floor)")
                break
        if not game.alive or game.won:
            break
        cleared += 1
        if cleared < floors:
            game.descend()
    return cleared


def run_one(world_path: str, agent_name: str, floors: int = 99) -> RunStats:
    from runtime.game import Game, load_manifest
    from runtime.sense import make_brain

    manifest = load_manifest(world_path)
    systems = build_systems()
    register_all_brains()

    game = Game(manifest, systems=systems, sandbox=False)
    game.player.brain = make_brain(game, game.player, name=agent_name)

    auto_play(game, floors)

    return RunStats(
        agent=agent_name,
        alive=game.alive,
        won=game.won,
        floor=game.floor,
        turns=game.turn,
        kills=game.kills,
        items_taken=game.items_taken,
        hp=max(0, game.player.hp),
        max_hp=game.player.max_hp,
        atk=game.player.atk,
        defense=game.player.defense,
        messages=list(game.messages),
    )


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Run all 6 vaultcrawl agents headlessly.")
    ap.add_argument("world", nargs="?", default=DEFAULT_WORLD,
                    help="path to world.json (default: examples/world.json)")
    ap.add_argument("--floors", type=int, default=99,
                    help="max floors per agent (default 99)")
    ap.add_argument("--agent", choices=AGENT_NAMES,
                    help="run a single agent instead of all 6")
    args = ap.parse_args()

    world_path = ensure_world(args.world)
    agents = [args.agent] if args.agent else AGENT_NAMES

    os.makedirs(AUDIT_DIR, exist_ok=True)
    os.makedirs(FORGE_DIR, exist_ok=True)

    results: list[dict] = []
    seed = json.load(open(world_path))["seed"]

    print(f"{'AGENT':<16} {'ALIVE':<6} {'WON':<5} {'FLOOR':<7} {'TURNS':<7} {'KILLS':<6} {'ITEMS':<6} {'HP':<10}")
    print("-" * 72)

    for name in agents:
        t0 = time.monotonic()
        try:
            stats = run_one(world_path, name, args.floors)
        except Exception as exc:
            stats = RunStats(
                agent=name, alive=False, won=False, floor=0, turns=0,
                kills=0, items_taken=0, hp=0, max_hp=0, atk=0, defense=0,
                messages=[f"CRASH: {exc}"],
            )
        elapsed = time.monotonic() - t0

        stats_dict = asdict(stats)
        stats_dict["elapsed"] = round(elapsed, 2)
        results.append(stats_dict)

        # per-agent message log
        msg_path = AUDIT_DIR / f"{name}_messages.json"
        with open(msg_path, "w", encoding="utf-8") as fh:
            json.dump(stats.messages, fh, indent=2)

        # forge checkpoint
        forge_path = FORGE_DIR / f"{seed}.json"
        if not forge_path.exists():
            forge_data = {"seed": seed, "affinities": {}, "unlocks": []}
            with open(forge_path, "w", encoding="utf-8") as fh:
                json.dump(forge_data, fh)

        hp_str = f"{stats.hp}/{stats.max_hp}"
        print(f"{name:<16} {str(stats.alive):<6} {str(stats.won):<5} {stats.floor:<7} "
              f"{stats.turns:<7} {stats.kills:<6} {stats.items_taken:<6} {hp_str:<10}")

    # summary
    runs_path = AUDIT_DIR / "runs.json"
    with open(runs_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    print(f"\nSaved {len(results)} run(s) → {runs_path}")
    print(f"Message logs → {AUDIT_DIR}")
    print(f"Forge cache  → {FORGE_DIR}")


if __name__ == "__main__":
    main()
