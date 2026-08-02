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
# Below this, the panic branch in UniversalBrain.decide is live for every profile (its own
# cutoff is 25 for fighters and 35 for the rest), so the agent is one bad turn from dead.
CRITICAL_PCT = 25
# How much of the HP trace to keep per run. Twelve decisions is enough to tell a burst from
# an attrition, and short enough that 288 rows stay readable.
HP_TAIL = 12
# A verb has to be tried this often before "never worked" is a claim rather than noise.
MIN_ATTEMPTS_TO_JUDGE = 20

# Events that say "something happened somewhere" rather than naming a system's output.
# `noise` is 86.8% of every event a run emits, so any statistic computed over the raw bus is
# a statistic about noise. Excluded from coupling; its share is reported separately.
AMBIENT_EVENTS = frozenset({"noise"})

# How many recent events an event is paired against. Emergence is one system's output
# becoming another's input, so what matters is which kinds arrive close together, not which
# kinds arrive. Four is short enough that a pair is plausibly a consequence rather than a
# coincidence, and the window is over bus emissions rather than turns because the bus does
# not carry turn numbers.
COUPLING_WINDOW = 4


@dataclass
class EmergenceLog:
    """How much of the stack is actually participating.

    A 28-system game whose systems never touch is 28 games running in parallel. These are
    the numbers that say otherwise: how many kinds of thing happen, how many systems hear
    about them, and whether any verb is simply broken.
    """

    event_kinds: dict = field(default_factory=dict)
    verb_ok: dict = field(default_factory=dict)
    verb_fail: dict = field(default_factory=dict)
    # Ordered pairs of non-ambient events seen within COUPLING_WINDOW of each other.
    couplings: dict = field(default_factory=dict)
    ambient: int = 0
    _recent: list = field(default_factory=list)

    def observe_event(self, etype: str) -> None:
        self.event_kinds[etype] = self.event_kinds.get(etype, 0) + 1
        if etype in AMBIENT_EVENTS:
            self.ambient += 1
            return
        # Which kinds arrive together, not which kinds arrive. `event_kinds` counts presence
        # and saturates: 13 kinds exist and a single run sees 12.3 of them, so it cannot
        # tell a rich run from a poor one. Ordered pairs have a ceiling of 13 * 13 = 169 and
        # sit far below it, which is what a metric with headroom looks like.
        for prev in self._recent:
            key = prev + ">" + etype
            self.couplings[key] = self.couplings.get(key, 0) + 1
        self._recent.append(etype)
        if len(self._recent) > COUPLING_WINDOW:
            self._recent.pop(0)

    def observe_verb(self, kind: str, ok: bool) -> None:
        d = self.verb_ok if ok else self.verb_fail
        d[kind] = d.get(kind, 0) + 1

    def broken_verbs(self) -> list[str]:
        """Verbs attempted at least once that never once succeeded.

        This is the check that would have caught three separate bugs: the absorb-hazard
        livelock, `deploy` raising TypeError on every call for the life of the project, and
        the stable-sort tie that made salvage and cache unreachable.
        """
        return sorted(k for k, n in self.verb_fail.items()
                      if n >= MIN_ATTEMPTS_TO_JUDGE and not self.verb_ok.get(k))

    def summary(self) -> dict:
        attempts = {k: self.verb_ok.get(k, 0) + self.verb_fail.get(k, 0)
                    for k in set(self.verb_ok) | set(self.verb_fail)}
        total = sum(self.event_kinds.values()) or 1
        named = [k for k in self.event_kinds if k not in AMBIENT_EVENTS]
        return {
            "event_kinds": len(self.event_kinds),
            "event_counts": dict(sorted(self.event_kinds.items(), key=lambda kv: -kv[1])),
            # How many distinct kinds actually followed one another, against how many could.
            # This is the emergence number: `event_kinds` says which systems ran, this says
            # which ones met.
            "coupling_pairs": len(self.couplings),
            "coupling_possible": len(named) ** 2,
            "coupling_density": round(len(self.couplings) / max(1, len(named) ** 2), 3),
            "coupling_top": dict(sorted(self.couplings.items(),
                                        key=lambda kv: -kv[1])[:8]),
            # Reported so nobody computes a statistic over a bus that is mostly this.
            "ambient_share": round(self.ambient / total, 3),
            "verb_success": {k: round(self.verb_ok.get(k, 0) / n, 3)
                             for k, n in sorted(attempts.items()) if n},
            "broken_verbs": self.broken_verbs(),
            # Raw counts, so an aggregate over several runs can judge on the totals rather
            # than on the union of per-run verdicts. A verb that fails every attempt in one
            # unlucky run is not a broken verb.
            "verb_ok": dict(self.verb_ok),
            "verb_fail": dict(self.verb_fail),
        }


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
    forced: int = 0
    turns_critical: int = 0

    def observe(self, game, brain) -> None:
        """Read the decision the brain just made. Safe on brains that do not expose one."""
        cands = getattr(brain, "_last_candidates", None)
        choice = getattr(brain, "_last_choice", None)
        if cands and choice is not None and choice < len(cands):
            label = cands[choice][0]
            self.labels[label] = self.labels.get(label, 0) + 1
            if getattr(brain, "_last_forced", False):
                # A hard override: the brain returned before scoring anything. It counts as a
                # decision, because it is one, but not as a contest. Recording it as a
                # one-candidate turn would inflate `uncontested_share`, which is supposed to
                # mean "the cascade offered nothing to weigh", not "the cascade was skipped".
                self.forced += 1
            else:
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
            if pct < CRITICAL_PCT:
                self.turns_critical += 1

    def summary(self) -> dict:
        n = sum(self.labels.values())
        finite = [m for m in self.margins if m != float("inf")]
        turns = len(self.hp_pcts) or 1
        return {
            "decisions": n,
            "label_share": {k: v / n for k, v in
                            sorted(self.labels.items(), key=lambda kv: -kv[1])} if n else {},
            "top_label_share": (max(self.labels.values()) / n) if n else 0.0,
            # Three labels used to own 80% of every run. Concentration is the single
            # clearest read on whether the decision space is actually being used.
            "top3_label_share": (sum(sorted(self.labels.values(), reverse=True)[:3]) / n)
                                if n else 0.0,
            "labels_used": len(self.labels),
            "median_margin": _median(finite),
            "contested_share": (sum(1 for m in self.margins if m <= CONTESTED_MARGIN)
                                / len(self.margins)) if self.margins else 0.0,
            "uncontested_share": (sum(1 for m in self.margins if m == float("inf"))
                                  / len(self.margins)) if self.margins else 0.0,
            "avg_candidates": (sum(self.candidate_counts) / len(self.candidate_counts))
                              if self.candidate_counts else 0.0,
            "min_hp_pct": self.min_hp_pct,
            "hurt_share": self.turns_hurt / turns,
            "critical_share": self.turns_critical / turns,
            # Turns the cascade never ran on, as a share of all decisions.
            "forced_share": (self.forced / n) if n else 0.0,
            # How a run ended, in HP. 74% of losses are deaths and nothing recorded whether
            # they were ground down or hit once from full, which are different problems with
            # different levers. `hp_tail` is the last few decisions; `max_drop_pct` is the
            # worst single-turn fall anywhere in the run.
            "hp_tail": self.hp_pcts[-HP_TAIL:],
            "max_drop_pct": max((a - b for a, b in zip(self.hp_pcts, self.hp_pcts[1:])),
                                default=0),
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
