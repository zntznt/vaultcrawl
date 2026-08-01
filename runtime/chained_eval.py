"""Warm versus cold: does a world that remembers earlier runs play differently?

The question this project has never asked. `RunChronicle` carries a run's events forward and
`Upheaval` turns them into live modifiers on the next descent: notes whose bosses were slain
become monuments, forged rooms become sanctums, deleted notes haunt the floors, contested
regions change hands. `play.py` wires that return arrow. `agent_eval` deliberately does not,
because cross-run state ruins a benchmark, so every balance number this project has ever
quoted describes a world with no memory.

Two arms, identical (agent, seed) pairs, identical order:

  cold   the chronicle is deleted before every run. What the benchmark has always measured.
  warm   the chronicle persists, so each run inherits everything earlier runs left.

Run with an isolated HOME. The state directory is a real hazard: deleting or writing
`~/.vaultcrawl` while any other evaluation is running silently corrupts it, which is exactly
how the first attempt at this went wrong.
"""
import collections
import json
import os
import shutil
import sys

AGENTS = ("artisan", "cartographer", "emergent", "exploiter", "seeker", "whisper")
SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 8
WORLD = "examples/world.json"

home = os.environ.get("HOME", "")
if os.path.realpath(home) == os.path.realpath(os.path.expanduser("~")) and \
        os.environ.get("CHAINED_ALLOW_REAL_HOME") != "1":
    raise SystemExit(
        "refusing to run against the real HOME. This harness deletes and rewrites\n"
        "$HOME/.vaultcrawl between arms, and doing that while any evaluation is running\n"
        "silently corrupts it: that is exactly how the first attempt at this went wrong.\n"
        "Run with HOME set to a scratch directory.")

import runtime.agent_eval as ev  # noqa: E402
import runtime.agent as A  # noqa: E402
from runtime.game import Game as RealGame, load_manifest  # noqa: E402
from runtime.upheaval import Upheaval  # noqa: E402
from runtime.persistence import load_chronicle_events, chronicle_path  # noqa: E402

WSEED = str(load_manifest(WORLD).get("seed", ""))
state = {"warm": False, "inherited": 0, "total": 0}


def ChainedGame(manifest, *a, **kw):
    past = load_chronicle_events(WSEED) if state["warm"] else []
    up = Upheaval.from_events(past) if past else Upheaval()
    state["inherited"] = len(past)
    state["total"] = getattr(up, "total", 0)
    kw["upheaval"] = up
    kw["chronicle_out"] = True      # both arms write; only warm reads
    return RealGame(manifest, *a, **kw)


ev.Game = ChainedGame

# Decisions per turn, to catch a stall that the win rate would hide.
calls = collections.Counter()
_orig_decide = A.UniversalBrain.decide
picked = collections.Counter()


def _decide(self, game, actor):
    calls["n"] += 1
    r = _orig_decide(self, game, actor)
    try:
        if self._last_choice is not None:
            picked[self._last_candidates[self._last_choice][0]] += 1
    except Exception:
        pass
    return r


A.UniversalBrain.decide = _decide


def run_arm(warm: bool) -> list:
    state["warm"] = warm
    shutil.rmtree(os.path.join(home, ".vaultcrawl"), ignore_errors=True)
    rows = []
    for seed in range(SEEDS):
        for agent in AGENTS:
            if not warm:
                # Cold: no memory of anything, every run a first morning.
                try:
                    os.remove(chronicle_path())
                except OSError:
                    pass
            calls["n"] = 0
            picked.clear()
            r = ev.run_agent(WORLD, agent, run_seed=f"chain-{seed}")
            turns = r.turns_survived or 1
            tot = sum(picked.values()) or 1
            top, cnt = picked.most_common(1)[0] if picked else ("-", 0)
            rows.append(dict(
                arm="warm" if warm else "cold", agent=agent, seed=seed,
                won=bool(r.won), floor=r.floor_reached, turns=turns,
                win_path=r.win_path, died=bool(r.cause_of_death),
                inherited=state["inherited"], upheaval=state["total"],
                decisions=calls["n"], per_turn=round(calls["n"] / turns, 3),
                top_label=top, top_share=round(cnt / tot, 4), labels=len(picked),
            ))
            print(f"  [{'warm' if warm else 'cold'}] {agent:13} seed {seed} "
                  f"F{r.floor_reached:2} won={str(r.won):5} inherit={state['inherited']:2} "
                  f"up={state['total']:2} d/t={calls['n']/turns:.2f}", flush=True)
    return rows


print(f"=== cold arm: {SEEDS * len(AGENTS)} runs ===", flush=True)
cold = run_arm(False)
print(f"\n=== warm arm: {SEEDS * len(AGENTS)} runs ===", flush=True)
warm = run_arm(True)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chained_result.json")
with open(out, "w", encoding="utf-8") as fh:
    json.dump({"cold": cold, "warm": warm}, fh, indent=2)


def summarise(name, rows):
    n = len(rows)
    w = sum(1 for r in rows if r["won"])
    print(f"\n{name}: {w}/{n} wins ({w/n:.1%})")
    print(f"  mean floor {sum(r['floor'] for r in rows)/n:5.1f}   "
          f"mean turns {sum(r['turns'] for r in rows)/n:7.0f}   "
          f"mean decisions/turn {sum(r['per_turn'] for r in rows)/n:.3f}")
    print(f"  mean labels used {sum(r['labels'] for r in rows)/n:.1f}   "
          f"max top-label share {max(r['top_share'] for r in rows):.1%}")
    paths = collections.Counter(r["win_path"] for r in rows if r["won"])
    print(f"  win paths: {dict(paths)}")
    up = [r["upheaval"] for r in rows]
    print(f"  upheaval inherited: min {min(up)} max {max(up)} "
          f"nonzero on {sum(1 for u in up if u)}/{n} runs")


summarise("COLD", cold)
summarise("WARM", warm)

by = {(r["agent"], r["seed"]): r for r in cold}
cw = {(r["agent"], r["seed"]): r for r in warm}
to_win = [k for k in by if not by[k]["won"] and cw.get(k, {}).get("won")]
to_loss = [k for k in by if by[k]["won"] and not cw.get(k, {}).get("won")]
print(f"\nPAIRED on identical seeds: {len(to_win)} cold-losses became warm-wins, "
      f"{len(to_loss)} cold-wins became warm-losses, net {len(to_win)-len(to_loss):+d}")
print(f"\nSaved -> {out}")
