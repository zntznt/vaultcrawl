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
    # de-dupe preserving order
    seen, out = set(), []
    for m in mats:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out or ["scrap"]


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
    """A pool of materials, plus a small list of carried (un-slotted) things."""

    def __init__(self):
        self.comp: dict = {}     # material -> count
        self.qual: dict = {}     # material -> best quality tier banked (for the forge floor)
        self.held: list = []     # carried items/sigils not yet used (dicts)

    def add(self, comps: dict, quality: int = 0):
        for m, q in (comps or {}).items():
            self.comp[m] = self.comp.get(m, 0) + q
            if quality > self.qual.get(m, 0):
                self.qual[m] = quality

    def quality_of(self, material) -> int:
        return self.qual.get(material, 0)

    def min_quality(self, materials) -> int:
        mats = list(materials or [])
        return min((self.qual.get(m, 0) for m in mats), default=0)

    def total(self) -> int:
        return sum(self.comp.values())

    def can_pay(self, cost: dict) -> bool:
        return all(self.comp.get(m, 0) >= q for m, q in (cost or {}).items())

    def pay(self, cost: dict) -> bool:
        if not self.can_pay(cost):
            return False
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
