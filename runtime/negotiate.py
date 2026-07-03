"""Negotiation with hostile creatures (SMT-style, but note-embodied).

A hostile is a note made flesh, so it converses AS its note: its lines are woven
from its own corpus chain (the same recombination marginalia use), and its
temperament follows its graph role. It is fickle the way SMT demons are fickle,
but deterministically so: each reaction can swing on a seeded "strange humor"
roll, reproducible per creature/turn/round.

  role      temperament   loves          spurns
  hub       proud         praise         gifts (it wants for nothing)
  bridge    curious       truths         --
  leaf      timid         gifts          truths (too sharp)
  orphan    lonely        being asked    --
  cluster   communal      gifts          --

Sway it past its goal: it stands down into the wild AND teaches you its note
(direct knowledge -- conversation as intel). Drive it to fury: it never talks
again. Bore it: it disengages, and being fickle, may hear you out another day.
Pure engine logic; the front-end drives rounds and renders lines.
"""
from __future__ import annotations

import random

from .marginalia import weave

MOVES = ("praise", "ask", "truth", "gift")

TEMPERAMENT = {
    "hub": ("proud", {"praise": 2, "truth": 1, "ask": 0, "gift": -1}),
    "bridge": ("curious", {"truth": 2, "ask": 1, "praise": 0, "gift": 0}),
    "leaf": ("timid", {"gift": 2, "ask": 1, "praise": 0, "truth": -1}),
    "orphan": ("lonely", {"ask": 2, "praise": 1, "gift": 1, "truth": 0}),
    "discovery": ("lonely", {"ask": 2, "praise": 1, "gift": 1, "truth": 0}),
    "cluster": ("communal", {"gift": 2, "praise": 1, "truth": 0, "ask": 0}),
}

SILENT = {
    "proud": "It regards you from a great height.",
    "curious": "It circles you, considering.",
    "timid": "It trembles at the edge of speech.",
    "lonely": "It watches you, starved for witness.",
    "communal": "It waits to see what you bring.",
}

REACT = {2: "brightens", 1: "softens", 0: "is unmoved", -1: "bristles", -2: "darkens"}

ENRAGE_AT = -3
MAX_ROUNDS = 4


class Parley:
    def __init__(self, game, target, fickle=True):
        node = game.m.get("graph", {}).get("nodes", {}).get(target.source, {})
        role = node.get("role", "cluster")
        self.temperament, self.taste = TEMPERAMENT.get(role, TEMPERAMENT["cluster"])
        age = node.get("activity", 0.5)
        self.goal = 3 if age >= 0.7 else (5 if age <= 0.15 else 4)
        if getattr(target, "_legend", False):
            self.goal -= 1   # legends LIKE being spoken with; that is how legends grow
        self.fickle = fickle
        self.rounds = 0
        self.truths_used = 0
        self.outcome = None    # None | "swayed" | "enraged" | "bored"
        self.disposition = 0
        know = game.system("knowledge")
        if know is not None and target.source in getattr(know, "learned", set()):
            self.disposition += 2      # it senses that you know it
        if target.hp < target.max_hp:
            self.disposition -= 1      # you have drawn its blood

    # ---- its voice: the note's own words ------------------------------------
    def speak(self, game, target) -> str:
        node = game.m.get("graph", {}).get("nodes", {}).get(target.source, {})
        comm = (game.m.get("corpus") or {}).get(str(node.get("community", -1)))
        rng = random.Random(f"{game.seed}:parley:{target.source}:{game.turn}:{self.rounds}")
        line = weave(comm, target.source, rng, max_words=12) if comm else ""
        return f'"{line}"' if line else SILENT[self.temperament]

    # ---- your move -----------------------------------------------------------
    def _truths(self, game) -> int:
        return sum(getattr(game.system(n), "read", 0)
                   for n in ("marginalia", "history") if game.system(n))

    def hear(self, game, target, move: str) -> str:
        """Apply one player move; returns the narration line. Requirements that
        cannot be met (no truth left, no matter) cost nothing and no round."""
        if move == "truth":
            if self._truths(game) <= self.truths_used:
                return "You have no unspoken truth left to offer."
            self.truths_used += 1
        elif move == "gift":
            salv = game.system("salvage")
            bag = salv.inventory(game) if salv is not None else None
            if bag is None or bag.total() < 1:
                return "You have nothing to give."
            from .game import _spend_matter
            _spend_matter(bag, 1)

        self.rounds += 1
        delta = self.taste.get(move, 0)
        rng = random.Random(f"{game.seed}:humor:{target.source}:{game.turn}:{self.rounds}")
        humored = self.fickle and rng.random() < 0.25
        if humored:
            delta = -delta
        self.disposition += delta

        if self.disposition >= self.goal:
            self.outcome = "swayed"
        elif self.disposition <= ENRAGE_AT:
            self.outcome = "enraged"
        elif self.rounds >= MAX_ROUNDS:
            self.outcome = "bored"
        mood = REACT.get(max(-2, min(2, delta)), "is unmoved")
        strange = " -- it is in a strange humor" if humored and delta else ""
        return f"{target.name} {mood}{strange}."

    # ---- resolution ------------------------------------------------------------
    def resolve(self, game, target, recruit=False) -> str:
        if self.outcome == "swayed":
            know = game.system("knowledge")
            if know is not None:
                know._reveal(game, target.source, direct=True)
                game.log(f"{target.name} tells you of itself; you understand its note.")
            if recruit:
                game.recruit(target)
                return f"{target.name} walks with you now."
            game._join_wild(target)
            return f"{target.name} stands down and goes its own way."
        if self.outcome == "enraged":
            if getattr(target, "_legend", False):
                return f"{target.name} laughs it off; a legend holds no grudge."
            target._enraged = True
            return f"{target.name} howls; it will never hear you again."
        return f"{target.name} loses interest and turns away."
