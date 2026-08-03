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
# Compare against the passwd entry, not `expanduser("~")`. That reads $HOME, so it equals
# `home` by construction and the guard fired on every run including the correct ones.
try:
    import pwd
    _real_home = pwd.getpwuid(os.getuid()).pw_dir
except Exception:
    _real_home = os.path.expanduser("~")
if os.path.realpath(home) == os.path.realpath(_real_home) and \
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


def _progress(msg: str) -> None:
    """Append to a file as well as stdout.

    Two runs died today with no way to tell how far they had got, both because the launch
    piped through `tail`, which buffers until the process exits. `python3 -u` does not help
    when something downstream is holding the pipe. A file always tells the truth, and
    `wc -l` on it is the progress bar.
    """
    print(msg, flush=True)
    try:
        with open(os.path.join(home, "progress.log"), "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


def run_arm(warm: bool, pairs=None, state_dir: str = None) -> list:
    """One arm. `pairs` lets a worker take a slice; `state_dir` isolates its ~/.vaultcrawl.

    The cold arm is embarrassingly parallel, since every run starts from a deleted chronicle
    and shares nothing. The warm arm cannot be: it is a chain, and each run must see what the
    previous one left. So cold fans out across processes while warm runs in the parent, and
    the wall clock becomes max(cold / workers, warm) instead of cold + warm.
    """
    state["warm"] = warm
    if state_dir:
        os.environ["HOME"] = state_dir      # chronicle_path() expands ~ at call time
        os.makedirs(state_dir, exist_ok=True)
    root = os.path.join(os.environ["HOME"], ".vaultcrawl")
    shutil.rmtree(root, ignore_errors=True)
    rows = []
    if pairs is None:
        pairs = [(seed, agent) for seed in range(SEEDS) for agent in AGENTS]
    for seed, agent in pairs:
        if True:
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
                label_share={k: v / tot for k, v in picked.items()},
                attractors=dict(r.attractor_scores or {}),
                coupling=(r.emergence or {}).get("coupling_pairs", 0),
                coupling_density=(r.emergence or {}).get("coupling_density", 0.0),
                ambient_share=(r.emergence or {}).get("ambient_share", 0.0),
            ))
            _progress(f"  [{'warm' if warm else 'cold'}] {agent:13} seed {seed} "
                      f"F{r.floor_reached:2} won={str(r.won):5} "
                      f"inherit={state['inherited']:2} up={state['total']:2} "
                      f"d/t={calls['n']/turns:.2f}")
    return rows


def _cold_slice(args):
    """A worker's share of the cold arm, in its own process and its own state directory."""
    idx, pairs = args
    return run_arm(False, pairs=pairs,
                   state_dir=os.path.join(home, f"cold_w{idx}"))


ALL_PAIRS = [(seed, agent) for seed in range(SEEDS) for agent in AGENTS]
# One core is left for the warm arm, which runs here in the parent at the same time.
WORKERS = max(1, min(len(ALL_PAIRS), (os.cpu_count() or 2) - 1))

_progress(f"=== {len(ALL_PAIRS)} runs per arm: cold across {WORKERS} workers, "
          f"warm sequential in parallel with them ===")

import multiprocessing as mp  # noqa: E402

chunks = [(i, ALL_PAIRS[i::WORKERS]) for i in range(WORKERS)]
ctx = mp.get_context("fork")   # children inherit the monkeypatched modules
pool = ctx.Pool(WORKERS)
cold_async = pool.map_async(_cold_slice, chunks)

# The chain has to be sequential, so it runs here while the pool works.
warm = run_arm(True, state_dir=os.path.join(home, "warm"))

cold = [row for part in cold_async.get() for row in part]
pool.close()
pool.join()
cold.sort(key=lambda r: (r["seed"], r["agent"]))
warm.sort(key=lambda r: (r["seed"], r["agent"]))

# Next to the scratch HOME, never in the repo: `__file__` lives in runtime/ now, so the
# obvious choice would commit a result blob on every run.
out = os.path.join(home, "chained_result.json")
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
    print(f"  coupling: {sum(r['coupling'] for r in rows)/n:5.1f} pairs/run   "
          f"density {sum(r['coupling_density'] for r in rows)/n:.3f}   "
          f"ambient {sum(r['ambient_share'] for r in rows)/n:.1%}")
    keys = sorted({k for r in rows for k in r["attractors"]})
    if keys:
        line = "  attractors: " + "  ".join(
            f"{k} {sum(r['attractors'].get(k, 0) for r in rows)/n:.3f}" for k in keys)
        print(line)
        # `haunted` needs ghosts, ghosts need note_lost events, note_lost comes from a
        # chronicle. It is structurally impossible in a cold arm and is the sharpest single
        # test of whether memory produces a KIND of run the memoryless world cannot.
        hn = sum(1 for r in rows if r["attractors"].get("haunted", 0) > 0)
        print(f"  runs with any haunting: {hn}/{n}")


def divergence(name, rows):
    """Are the six profiles more distinguishable in this arm, or less?

    The reason this experiment is worth more than its win rate. The profiles have converged
    on every recent baseline (floor 0.09 then 0.073, under the 0.10 line an earlier
    assessment set as worth watching), and the differentiation that disappeared may have
    been coming from the pathologies that were removed. A world that changes between runs
    gives the profiles different terrain to be different on, so if memory helps anywhere it
    should show here before it shows in wins.
    """
    from runtime.pressure import divergence_matrix
    shares = {}
    for a in AGENTS:
        agg = collections.Counter()
        for r in rows:
            if r["agent"] == a:
                agg.update(r["label_share"])
        tot = sum(agg.values()) or 1.0
        shares[a] = {k: v / tot for k, v in agg.items()}
    m = divergence_matrix(shares)
    vals = sorted(m.values())
    lo = min(m, key=m.get)
    print(f"  {name} divergence: min {vals[0]:.3f}  median {vals[len(vals)//2]:.3f}  "
          f"max {vals[-1]:.3f}   most alike: {lo} at {m[lo]:.3f}")
    return vals


summarise("COLD", cold)
summarise("WARM", warm)

print("\nPOLICY DIVERGENCE (the hypothesis: a world with memory keeps profiles distinct)")
cv = divergence("COLD", cold)
wv = divergence("WARM", warm)
print(f"  floor  {cv[0]:.3f} -> {wv[0]:.3f}   median {cv[len(cv)//2]:.3f} -> {wv[len(wv)//2]:.3f}")

by = {(r["agent"], r["seed"]): r for r in cold}
cw = {(r["agent"], r["seed"]): r for r in warm}
to_win = [k for k in by if not by[k]["won"] and cw.get(k, {}).get("won")]
to_loss = [k for k in by if by[k]["won"] and not cw.get(k, {}).get("won")]
print(f"\nPAIRED on identical seeds: {len(to_win)} cold-losses became warm-wins, "
      f"{len(to_loss)} cold-wins became warm-losses, net {len(to_win)-len(to_loss):+d}")
print(f"\nSaved -> {out}")
