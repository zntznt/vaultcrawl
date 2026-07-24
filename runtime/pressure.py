"""Balance instrumentation: does the game present hard choices, or one obvious one?

Win rate cannot answer that. A 90% win rate looked healthy while every win was the same
win, taken by four profiles that behaved identically and never dropped below full HP.

What this measures instead:

**Decision margin.** UniversalBrain scores every candidate action and takes the top one.
The gap between first and second place is how forced the decision was. A game with real
tradeoffs produces narrow margins often; a dominant strategy produces one wide margin
every turn. `contested` is the share of decisions where the runner-up was within one
point, and it is the single number to watch.

**Label share.** Which candidate actually won, by name rather than by dispatched verb.
`move` covers explore, flee, stairs, salvage, cache and more, so verb counts hide the
decision. If one label owns most turns, that is the game.

**Resource floor.** The lowest HP reached and the share of turns spent hurt. If agents
never dip, nothing in the game is spending the resource it is built around.

**Policy divergence.** How differently two profiles play, as the total variation distance
between their label distributions. Six profiles that produce one distribution are one
profile.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Two candidates within this many points are treated as a real contest rather than a
# foregone conclusion. Scores run roughly 0-50, so one point is a genuinely close call.
CONTESTED_MARGIN = 1.0
# Below this fraction of max HP the agent counts as under pressure.
HURT_PCT = 50


@dataclass
class DecisionLog:
    """Per-turn record of what the brain chose and how close the alternative was."""

    labels: dict[str, int] = field(default_factory=dict)
    margins: list[float] = field(default_factory=list)
    runner_ups: dict[str, int] = field(default_factory=dict)
    hp_pcts: list[int] = field(default_factory=list)
    turns_hurt: int = 0
    min_hp_pct: int = 100
    candidate_counts: list[int] = field(default_factory=list)

    def observe(self, game, brain) -> None:
        """Read the decision the brain just made. Safe on brains that do not expose one."""
        cands = getattr(brain, "_last_candidates", None)
        choice = getattr(brain, "_last_choice", None)
        if cands and choice is not None and choice < len(cands):
            label = cands[choice][0]
            self.labels[label] = self.labels.get(label, 0) + 1
            self.candidate_counts.append(len(cands))
            if len(cands) > 1:
                self.margins.append(float(cands[0][1] - cands[1][1]))
                self.runner_ups[cands[1][0]] = self.runner_ups.get(cands[1][0], 0) + 1
            else:
                # Nothing to weigh against: an uncontested turn.
                self.margins.append(float("inf"))

        player = getattr(game, "player", None)
        if player is not None:
            mx = max(1, getattr(player, "max_hp", 1))
            pct = max(0, int(player.hp * 100 / mx))
            self.hp_pcts.append(pct)
            self.min_hp_pct = min(self.min_hp_pct, pct)
            if pct < HURT_PCT:
                self.turns_hurt += 1

    def summary(self) -> dict:
        n = sum(self.labels.values())
        finite = [m for m in self.margins if m != float("inf")]
        turns = len(self.hp_pcts) or 1
        return {
            "decisions": n,
            "label_share": {k: v / n for k, v in
                            sorted(self.labels.items(), key=lambda kv: -kv[1])} if n else {},
            "top_label_share": (max(self.labels.values()) / n) if n else 0.0,
            "median_margin": _median(finite),
            "contested_share": (sum(1 for m in self.margins if m <= CONTESTED_MARGIN)
                                / len(self.margins)) if self.margins else 0.0,
            "uncontested_share": (sum(1 for m in self.margins if m == float("inf"))
                                  / len(self.margins)) if self.margins else 0.0,
            "avg_candidates": (sum(self.candidate_counts) / len(self.candidate_counts))
                              if self.candidate_counts else 0.0,
            "min_hp_pct": self.min_hp_pct,
            "hurt_share": self.turns_hurt / turns,
        }


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def percentiles(xs, ps=(10, 50, 90)) -> dict[str, float]:
    """Cheap nearest-rank percentiles. Every aggregate in the harness was a bare mean,
    which hides exactly the spread balance work needs to see."""
    if not xs:
        return {f"p{p}": 0.0 for p in ps}
    s = sorted(xs)
    out = {}
    for p in ps:
        i = min(len(s) - 1, max(0, round(p / 100 * len(s)) - 1))
        out[f"p{p}"] = float(s[i])
    return out


def divergence(a: dict[str, float], b: dict[str, float]) -> float:
    """Total variation distance between two label distributions.

    0.0 means the two profiles make the same choices in the same proportions. 1.0 means
    they share no behaviour at all. This is the number that says whether six profiles are
    six playstyles or one playstyle with six names.
    """
    keys = set(a) | set(b)
    return sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys) / 2


def divergence_matrix(shares: dict[str, dict[str, float]]) -> dict[str, float]:
    """Pairwise divergence for every profile pair, keyed 'a|b'."""
    names = sorted(shares)
    out = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            out[f"{a}|{b}"] = divergence(shares[a], shares[b])
    return out


def persistence_fingerprint() -> dict:
    """What cross-run state this batch ran against.

    run_agents.py from a clean ~/.vaultcrawl wins 6 of 6; the identical command against
    warm state wins 4 of 6. Graves, the forge cache and the chronicle all persist between
    runs, so a win rate reported without this is not comparable to any other win rate.
    """
    import os
    root = os.path.expanduser("~/.vaultcrawl")
    out = {"root": root, "exists": os.path.isdir(root), "files": {}}
    if not out["exists"]:
        return out
    for name in ("graves.json", "chronicle.json", "eval_stats.json"):
        p = os.path.join(root, name)
        out["files"][name] = os.path.getsize(p) if os.path.exists(p) else 0
    forge = os.path.join(root, "forge")
    out["files"]["forge/"] = len(os.listdir(forge)) if os.path.isdir(forge) else 0
    return out
