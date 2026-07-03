"""Per-note history — every note has a STORY, told where you meet it.

The History system narrates the vault's GLOBAL chronicle (ages, schisms) in the depths.
This is the complement: each individual note's own biography, read straight from its
graph facts, so the thing in front of you (a creature, a landmark, a fixture, a boss)
can recount the history of the note it sprang from. A note that has been edited for
years, that bridges two worlds, that 21 other notes lean on — that is a life, and the
world should be able to tell it.

All lines are deterministic pure functions of the manifest (no clock, no rng unless a
seed is passed for variety). One fact per call by default (seeded rotation), or the
full biography for a lore fragment.
"""
from __future__ import annotations


def _age_epoch(activity: float) -> str:
    # activity is recency 0..1 (1 = freshly tended). Turn it into an "age of the world".
    if activity >= 0.85:
        return "of the present age, its ink still wet"
    if activity >= 0.6:
        return "of a recent age"
    if activity >= 0.3:
        return "of a middle age, half-forgotten"
    if activity >= 0.1:
        return "of an elder age, seldom visited"
    return "of the first age, all but lost"


def _standing(node: dict) -> str:
    deg = node.get("degree", 0)
    if deg >= 12:
        return f"a keystone: {deg} roads lead to it"
    if deg >= 5:
        return f"well-trodden, joined to {deg} others"
    if deg >= 2:
        return f"quietly linked to {deg} kin"
    if deg == 1:
        return "a leaf, hanging from a single thread"
    return "an orphan, bound to nothing"


def facts(node: dict, title: str) -> list:
    """Every biographical line this note's graph facts support, richest first."""
    out = []
    out.append(f"'{title}' is {_standing(node)}.")
    out.append(f"It is a thought {_age_epoch(node.get('activity', 0.5))}.")
    if node.get("bridge"):
        out.append("It stands athwart a border, a bridge between two worlds — "
                   "and bridges are where heresies cross.")
    role = node.get("role")
    if role == "hub":
        out.append("Much turns around it; it is a center others orbit.")
    elif role == "orphan":
        out.append("Nothing points to it and it points to nothing; it drifted here alone.")
    elif role == "leaf":
        out.append("It is an end of a road — reached, then no further.")
    tags = node.get("tags") or []
    if tags:
        named = ", ".join(t.replace("-", " ") for t in tags[:3])
        out.append(f"Its concerns: {named}.")
    nbrs = node.get("neighbors") or []
    if nbrs:
        names = ", ".join(n.replace("-", " ") for n in nbrs[:3])
        more = f", and {len(nbrs) - 3} more" if len(nbrs) > 3 else ""
        out.append(f"From it run ways to {names}{more}.")
    return out


def one_fact(node: dict, title: str, salt="") -> str:
    """A single history line, rotated deterministically by `salt` (e.g. a position),
    so different tellers of the same note say different true things about it."""
    fs = facts(node, title)
    if not fs:
        return ""
    # a stable index from the salt string (no rng, fully reproducible)
    h = 0
    for ch in str(salt):
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return fs[h % len(fs)]
