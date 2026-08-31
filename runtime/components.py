"""Components & inventory — everything breaks down into the world's own materials.

The matter of the world IS the vocabulary your notes coined: a world's components are the
words in its bible `aesthetic` list ("brass", "ink", "moss", "vellum", …). Anything —
a fallen creature, a shattered sigil, a detonated crystal, a salvaged item — breaks down
via `components_of(...)` into a handful of those materials, scaled by how potent it was.

This closes the lossy-sigil loop: sigils shatter (Cogmind part-loss), their matter can be
salvaged, and the forge spends matter to re-craft. It is opt-in (a `SalvageSystem` collects
salvage into the player's `Inventory`); with no salvage system, nothing here runs.
"""
from __future__ import annotations

import hashlib


def world_materials(game) -> list:
    """The world's material vocabulary — the bible's aesthetic words (last token of each)."""
    aes = []
    try:
        aes = game.m.get("bible", {}).get("aesthetic", []) or []
    except Exception:
        aes = []
    mats = []
    for a in aes:
        tok = str(a).strip().split()
        if tok:
            mats.append(tok[-1].lower())
    return list(dict.fromkeys(mats)) or ["scrap"]   # de-dupe, order-preserving


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def components_of(game, kind="thing", source="", tier=1, name="") -> dict:
    """Break `thing` into {material: qty}. Deterministic; grounded in its source note +
    potency. A potent thing (high tier) yields more, and rarer, materials."""
    mats = world_materials(game)
    tier = max(1, int(tier or 1))
    count = min(len(mats), 1 + (tier >= 3) + (tier >= 5))   # 1..3 distinct materials
    base = _h(kind, source, name)
    out: dict = {}
    for i in range(count):
        m = mats[(base + i * 7) % len(mats)]
        out[m] = out.get(m, 0) + max(1, tier - i)
    return out


class Inventory:
    """A pool of materials banked from salvage, graded per unit.

    Matter carries the grade of whatever it was salvaged from, and the forge reads that
    grade as its quality floor. `tiers` is the ledger that makes the floor honest: it
    splits each material's stock by tier, so a single Legendary scrap is one Legendary
    scrap rather than a permanent property of the word "scrap".

    This used to be a scalar high-water mark per material, `qual[m] = best ever banked`,
    which was never decremented when the matter was spent. One good kill set that
    material's forge floor for the rest of the run: bank a Legendary scrap, spend it,
    refill with forty Normal, and the floor was still Legendary. Because `roll()` adds the
    floor and clamps, that made the floor, not the odds, the thing that decided an item's
    grade, and `ITEM_QUALITY_BASE` measured as inert across a 6x sweep. See
    `guidance/PROJECT_ASSESSMENT.md` and `runtime/quality_leverage.py`.

    Grades are spent best-first. The alternative, spending the junk and hoarding the good
    matter, would leave the floor pinned at the worst thing you own and make banked grade
    unspendable, which is a bigger change than making it finite.
    """

    def __init__(self):
        self.comp: dict = {}     # material -> count
        self.tiers: dict = {}    # material -> {tier: count}, summing to comp[material]

    def reset(self):
        """Empty the pool. Use this rather than assigning `comp`, which desyncs `tiers`."""
        self.comp = {}
        self.tiers = {}

    def add(self, comps: dict, quality: int = 0):
        gained = 0
        tier = max(0, int(quality or 0))
        for m, q in (comps or {}).items():
            if q <= 0:
                continue
            self.comp[m] = self.comp.get(m, 0) + q
            bucket = self.tiers.setdefault(m, {})
            bucket[tier] = bucket.get(tier, 0) + q
            gained += q
        if gained:
            # The `industrial` attractor scores forged-over-collected. It was reading
            # `inventory.total()` at the end of the run, which is the RESIDUAL, so
            # spending matter shrank the denominator and pushed the score UP: it was
            # directionally backwards. Collection is cumulative and this is the only
            # place matter enters an inventory.
            try:
                from .attractors import tracker
                tracker().record_matter_collected(gained)
            except Exception:
                pass

    # ---- grades -------------------------------------------------------------
    @staticmethod
    def _as_cost(cost) -> dict:
        """Accept either a cost dict (material -> qty) or a bare iterable of material
        names, which is read as one unit of each."""
        if isinstance(cost, dict):
            return {m: q for m, q in cost.items() if q > 0}
        return {m: 1 for m in (cost or [])}

    def spend_plan(self, cost) -> list:
        """The exact units paying `cost` would consume, as `(material, tier, qty)`,
        best-grade first. `min_quality` and `pay` both read this, so the floor a craft is
        quoted can never disagree with the matter it actually burns."""
        plan: list = []
        for m, need in sorted(self._as_cost(cost).items()):
            for tier in sorted(self.tiers.get(m, {}), reverse=True):
                if need <= 0:
                    break
                take = min(self.tiers[m][tier], need)
                if take > 0:
                    plan.append((m, tier, take))
                    need -= take
        return plan

    def quality_of(self, material) -> int:
        """The best grade still held of a material. Falls when that stock is spent."""
        held = self.tiers.get(material) or {}
        return max((t for t, q in held.items() if q > 0), default=0)

    def min_quality(self, cost) -> int:
        """The forge floor: the worst grade among the units `cost` would actually spend.

        Quantity matters. One Legendary scrap and twenty Normal buys a Legendary floor for
        a one-unit recipe and a Normal floor for a two-unit one, because the second unit
        comes off the Normal pile.
        """
        wanted = self._as_cost(cost)
        if not wanted:
            return 0
        plan = self.spend_plan(wanted)
        covered: dict = {}
        for m, _tier, qty in plan:
            covered[m] = covered.get(m, 0) + qty
        # an unaffordable recipe has no grade to quote
        if any(covered.get(m, 0) < need for m, need in wanted.items()):
            return 0
        return min(tier for _m, tier, _q in plan)

    def total(self) -> int:
        return sum(self.comp.values())

    def can_pay(self, cost: dict) -> bool:
        return all(self.comp.get(m, 0) >= q for m, q in (cost or {}).items())

    def pay(self, cost: dict) -> bool:
        if not self.can_pay(cost):
            return False
        for m, tier, qty in self.spend_plan(cost):
            bucket = self.tiers.get(m, {})
            bucket[tier] = bucket.get(tier, 0) - qty
            if bucket[tier] <= 0:
                del bucket[tier]
            if not bucket:
                self.tiers.pop(m, None)
        for m, q in cost.items():
            self.comp[m] -= q
            if self.comp[m] <= 0:
                del self.comp[m]
        return True

    def summary(self, top: int = 3) -> str:
        if not self.comp:
            return "empty"
        items = sorted(self.comp.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
        return " ".join(f"{m}x{q}" for m, q in items)


def inv(actor) -> Inventory:
    """Lazily attach and return an actor's Inventory."""
    i = getattr(actor, "_inv", None)
    if i is None:
        i = actor._inv = Inventory()
    return i
