"""Balance test: verify no craft makes an agent quantitatively worse off.
Runs baseline (no CraftSystem) vs craft-enabled across N runs per agent.
Reports: avg floor, avg turns, avg kills. Flags any metric that drops >5%."""
import sys, json, os
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from runtime.game import Game, load_manifest
from runtime.sense import make_brain
from runtime.play import auto_play
from runtime.senses import SenseField;from runtime.memory import MemorySystem
from runtime.sigils import SigilSystem;from runtime.reactions import ReactionSystem
from runtime.weather import WeatherSystem;from runtime.flora import FloraSystem
from runtime.structures import StructureSystem;from runtime.decay import DecaySystem
from runtime.fauna import FaunaSystem;from runtime.salvage import SalvageSystem
from runtime.forge import ForgeSystem;from runtime.scent import ScentSystem
from runtime.body_parts import BodySystem;from runtime.terrain_mod import TerrainModSystem
from runtime.portals import PortalSystem;from runtime.sacrifice import SacrificeSystem
from runtime.quests import QuestSystem;from runtime.dialogue import DialogueSystem
from runtime.machines import MachineSystem;from runtime.caches import CacheSystem
from runtime.factions import FactionSystem;from runtime.history import HistorySystem
from runtime.marginalia import MarginaliaSystem;from runtime.loci import LocusSystem
from runtime.craft import CraftSystem
from runtime.knowledge import KnowledgeSystem
from runtime.effects import EffectSystem;from runtime.quality import QualitySystem
import runtime.abilities
import runtime.brains; import runtime.tactics; import runtime.planner; import runtime.instincts
from runtime import agent

AGENTS = ["artisan", "cartographer", "emergent", "exploiter", "seeker", "whisper"]
RUNS = 30

BASE_SYSTEMS = [
    SenseField(), MemorySystem(), SigilSystem(), ReactionSystem(), WeatherSystem(),
    FloraSystem(), StructureSystem(), DecaySystem(), FaunaSystem(),
    SalvageSystem(), ForgeSystem(), ScentSystem(),
    QuestSystem(), DialogueSystem(), MachineSystem(), CacheSystem(),
    TerrainModSystem(), PortalSystem(), SacrificeSystem(),
    FactionSystem(), BodySystem(), QualitySystem(),
    HistorySystem(), MarginaliaSystem(), LocusSystem(), KnowledgeSystem(),
    EffectSystem(),
]

CRAFT_SYSTEMS = BASE_SYSTEMS + [CraftSystem()]


def run_batch(manifest, agent_name, systems, n):
    results = []
    for _ in range(n):
        game = Game(manifest, systems=list(systems), sandbox=False)
        game.player.brain = make_brain(game, game.player, name=agent_name)
        game.player._agent_name = agent_name
        game.player.brain.name = agent_name
        auto_play(game, 99)
        results.append({
            "floor": game.floor,
            "turns": game.turn,
            "kills": game.kills,
            "won": game.won,
            "crafts": len(getattr(game.player, "_crafts", {})),
            "messages": list(game.messages),
        })
    return results


def main():
    world = os.path.join(os.path.dirname(__file__), "examples", "world.json")
    if not os.path.exists(world):
        print("baking world...")
        import subprocess
        subprocess.run([sys.executable, "-m", "vaultcrawl.bake", "sample_vault", "-o", world],
                       cwd=os.path.dirname(__file__), check=True)
    manifest = load_manifest(world)
    seed = manifest.get("seed", "?")

    print(f"{'='*70}")
    print(f"CRAFT BALANCE TEST — {seed} — {RUNS} runs per agent per condition")
    print(f"{'='*70}")

    all_ok = True
    total_baseruns = 0
    total_craftruns = 0

    for agent_name in AGENTS:
        print(f"\n--- {agent_name} ---")
        print(f"  Running baseline ({RUNS} runs without CraftSystem)...", end=" ", flush=True)
        base = run_batch(manifest, agent_name, BASE_SYSTEMS, RUNS)
        print("done")

        print(f"  Running craft   ({RUNS} runs with CraftSystem)...", end=" ", flush=True)
        craft = run_batch(manifest, agent_name, CRAFT_SYSTEMS, RUNS)
        print("done")

        b_floor = sum(r["floor"] for r in base) / len(base)
        b_turns = sum(r["turns"] for r in base) / len(base)
        b_kills = sum(r["kills"] for r in base) / len(base)
        b_won  = sum(1 for r in base if r["won"]) / len(base)

        c_floor = sum(r["floor"] for r in craft) / len(craft)
        c_turns = sum(r["turns"] for r in craft) / len(craft)
        c_kills = sum(r["kills"] for r in craft) / len(craft)
        c_won  = sum(1 for r in craft if r["won"]) / len(craft)
        crafts_used = sum(1 for r in craft if r["crafts"] > 0)

        d_floor = c_floor - b_floor
        d_turns = c_turns - b_turns
        d_kills = c_kills - b_kills

        v_floor = "WORSE" if d_floor < b_floor * -0.05 else "OK"
        v_turns = "WORSE" if d_turns < b_turns * -0.05 else "OK"
        v_kills = "WORSE" if d_kills < b_kills * -0.05 else "OK"

        if any(v == "WORSE" for v in (v_floor, v_turns, v_kills)):
            all_ok = False

        print(f"  {'Metric':<8} {'Baseline':>10} {'Craft':>10} {'Delta':>10} {'Verdict':>10}")
        print(f"  {'floor':<8} {b_floor:>10.1f} {c_floor:>10.1f} {d_floor:>+10.1f} {v_floor:>10}")
        print(f"  {'turns':<8} {b_turns:>10.0f} {c_turns:>10.0f} {d_turns:>+10.0f} {v_turns:>10}")
        print(f"  {'kills':<8} {b_kills:>10.1f} {c_kills:>10.1f} {d_kills:>+10.1f} {v_kills:>10}")
        print(f"  {'won%':<8} {b_won:>10.1%} {c_won:>10.1%} {'':>10} {'':>10}")
        print(f"  {'crafted':<8} {'':>10} {crafts_used:>10}/{RUNS} {'':>10} {'':>10}")

        # Show sample craft messages from the first craft run that used crafts
        for r in craft:
            if r["crafts"] > 0:
                craft_msgs = [m for m in r["messages"] if any(
                    kw in m.lower() for kw in ("fabricator weaves", "terminal rewires",
                                                "depleted locus drinks", "camp ritual"))]
                if craft_msgs:
                    print(f"  Sample craft: {craft_msgs[0][:100]}")
                break

        total_baseruns += RUNS
        total_craftruns += RUNS

    print(f"\n{'='*70}")
    print(f"OVERALL: {'PASS — no agent worse off by >5%' if all_ok else 'FAIL — some agents worse off'}")
    print(f"Runs: {total_baseruns} baseline + {total_craftruns} craft = {total_baseruns + total_craftruns} total")
    print(f"{'='*70}")

    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
