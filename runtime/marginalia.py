"""Marginalia — the vault speaks in your own words.

The bake ships manifest["corpus"]: per-community word chains built from the notes'
actual bodies (vaultcrawl/corpus.py). This system walks that chain at play time,
Caves-of-Qud style: half-dreamed recombinations of what you actually wrote, never a
template. A floor scatters one or two `"` marks inside note-identified rooms; stepping
on one reads a line woven FROM THAT ROOM'S NOTE, so the place and the words agree.

Fresh every run: weaving is seeded `f"{seed}:{floor}:marginalia:{turn}"`, so the same
mark rereads differently on another descent while staying deterministic in this one.
Knowledge and flavor only: nothing here touches hp/atk/def. Degrades to inert on
manifests baked before the corpus layer existed.
"""
from __future__ import annotations

import random

from .systems import System

GLYPH = '"'


def weave(community: dict, note_id: str, rng, max_words: int = 18) -> str:
    """Speak from a note. Mostly (3 in 4) an INTACT sentence the author actually
    wrote, verbatim: recognition is the payload, your own words looking back at you.
    Otherwise a chain-walk: the same words dream-garbled, the uncanny minority.

    The walk LEANS HOME: at every step, successors drawn from the speaking note's
    own sentences are favoured over the community's, so the splice starts in this
    note, drifts into a neighbor's phrasing, and comes back — two doors on the same
    street garble differently instead of dissolving into one district soup."""
    lines = community.get("lines", {}).get(note_id)
    if lines and rng.random() < 0.75:
        return rng.choice(lines)
    chain = community.get("chain", {})
    starters = community.get("starters", {}).get(note_id) or sorted(chain)[:1]
    if not starters:
        return ""
    strip = ".,!?;:\"'"   # match words, not their sentence-position punctuation
    vocab = {w.strip(strip) for ln in (lines or []) for w in ln.split()}
    words = [w for w in rng.choice(starters).split(" ") if w]
    if len(words) < 2:   # a malformed/older starter can't seed an order-2 walk
        return " ".join(words) if words else ""
    while len(words) < max_words:
        nxt = chain.get(f"{words[-2]} {words[-1]}")
        if not nxt:
            break
        own = [w for w in nxt if w.strip(strip) in vocab]
        w = rng.choice(own) if own and rng.random() < 0.7 else rng.choice(nxt)
        words.append(w)
        # stop at a sentence end, but not before the line has any body to it
        if w and w[-1] in ".!?" and len(words) >= 6:
            break
    line = " ".join(words)
    return line if line and line[-1] in ".!?" else line + "..."


class MarginaliaSystem(System):
    name = "marginalia"

    def __init__(self):
        self.corpus: dict = {}
        self.ground: dict = {}   # (x, y) -> note_id whose words are buried here
        self.read: int = 0

    def on_world_start(self, game):
        self.corpus = game.m.get("corpus", {}) or {}

    def _community_for(self, game, note_id):
        node = game.m.get("graph", {}).get("nodes", {}).get(note_id, {})
        return self.corpus.get(str(node.get("community", -1)))

    def on_floor_enter(self, game):
        self.ground = {}
        if not self.corpus:
            return
        rng = random.Random(f"{game.seed}:{game.floor}:marginalia")
        room_notes = getattr(game, "room_notes", {}) or {}
        rooms = [(i, nid) for i, nid in sorted(room_notes.items())
                 if self._community_for(game, nid)]
        rng.shuffle(rooms)
        taken = {(game.player.x, game.player.y), game.level.stairs}
        taken |= {(a.x, a.y) for a in game.actors}
        for idx, nid in rooms[:2]:
            tiles = [t for t in game.room_tiles(idx) if t not in taken]
            if tiles:
                pos = rng.choice(tiles)
                taken.add(pos)
                self.ground[pos] = nid

    def on_player_act(self, game):
        nid = self.ground.pop((game.player.x, game.player.y), None)
        if nid is None:
            return
        comm = self._community_for(game, nid)
        rng = random.Random(f"{game.seed}:{game.floor}:marginalia:{game.turn}")
        line = weave(comm, nid, rng) if comm else ""
        if line:
            self.read += 1
            game.log(f'Marginalia, in your own hand: "{line}"')

    def render_overlay(self, game, grid):
        h = len(grid)
        w = len(grid[0]) if h else 0
        for (x, y) in self.ground:
            if 0 <= y < h and 0 <= x < w and grid[y][x] == ".":
                grid[y][x] = GLYPH

    def status_line(self, game):
        return f"Marginalia: {self.read} read" if self.read else None
