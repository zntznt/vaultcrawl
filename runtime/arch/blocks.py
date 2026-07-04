"""Design blocks — the legos. An environment is an ORDERED BLEND of blocks.

Zeo's model: environments are not monolithic themes but permutations of small design
blocks melded together, and the ORDER changes what manifests. A 'drowned foundry' is
the WATER block over the INDUSTRY block; reverse the order and it reads as a rusted
works that happens to be damp. Same pieces, different dominance, different place.

A block contributes four channels (so a vibe is objects + space + palette + voice, all
agreeing):
  feats   : [(glyph, weight, noun)]  — ground features/decor this block strews
  tend    : "open" | "dense" | "broken" | "linear" | "scattered" — its spatial pull
  palette : a color-lean name ("cold", "holy", "rust", "verdant", "pale", "harsh", ...)
  voice   : [lines]  — what a place of this block murmurs (ambient, sensory)

An Environment blends N blocks: the first is DOMINANT (its features are common, its
palette wins, its voice leads); each later block tints (rarer features, a secondary
voice). Blending is deterministic. Blocks compose from any signal — element, biome,
note-role — so the same 20 blocks make thousands of environments by permutation.
"""
from __future__ import annotations

# ---- feature glyphs (the expanded brick set; plain ASCII, non-colliding) -------
# ground/decor features are walkable texture. one glyph = one kind of thing.
BLOCKS = {
    # ---- element blocks -------------------------------------------------------
    "charged": dict(
        feats=[("!", 2, "a sparking node"), ("`", 3, "slag"), ("|", 1, "a dead conduit")],
        tend="linear", palette="harsh",
        voice=["A current hums in the floor.", "Static lifts the hair on your arms.",
               "Something crackles, then is still."]),
    "wet": dict(
        feats=[('"', 3, "reeds"), ("-", 2, "shallows"), ("~", 1, "a still pool")],
        tend="open", palette="cold",
        voice=["Water drips somewhere you cannot see.", "The ground gives, wet underfoot.",
               "A ripple crosses a black pool."]),
    "flammable": dict(
        feats=[('"', 4, "tinder-scrub"), (";", 1, "scorch")],
        tend="scattered", palette="rust",
        voice=["The air is dry and waiting.", "Ash lifts and settles.",
               "Everything here would burn."]),
    "frozen": dict(
        feats=[("`", 3, "rime"), (";", 1, "a frost-cracked stone")],
        tend="open", palette="cold",
        voice=["Your breath fogs and hangs.", "The cold has a sound, very faint.",
               "Ice ticks as it shifts."]),
    "sacred": dict(
        feats=[('"', 2, "fernbrush"), ("o", 2, "a standing stone"), (";", 1, "an offering")],
        tend="open", palette="holy",
        voice=["A stillness here asks for quiet.", "Something was revered in this place.",
               "The light falls as if through glass."]),
    "corrosive": dict(
        feats=[("`", 3, "salt-crust"), (";", 1, "a pitted thing")],
        tend="broken", palette="pale",
        voice=["The air bites, faintly acid.", "Metal here is eaten thin.",
               "Nothing green survives."]),
    "inert": dict(
        feats=[("`", 1, "a few pebbles")], tend="scattered", palette="dim",
        voice=["Nothing stirs.", "The quiet is complete."]),
    # ---- biome blocks ---------------------------------------------------------
    "foundry": dict(
        feats=[("|", 3, "a pipe"), ("[", 2, "a broken machine"), ("`", 2, "slag")],
        tend="dense", palette="rust",
        voice=["Cold machinery looms, long dead.", "The works ran here once, and stopped.",
               "Rust flakes underfoot."]),
    "archive": dict(
        feats=[("=", 3, "a laden shelf"), ("(", 2, "a fallen tome"), (";", 1, "loose leaves")],
        tend="linear", palette="pale",
        voice=["Rows of shelving recede into dark.", "Paper-dust hangs in the air.",
               "So much was written and left here."]),
    "garden": dict(
        feats=[('"', 4, "greenery"), (";", 1, "a bloom"), ("o", 1, "a mossy stone")],
        tend="open", palette="verdant",
        voice=["Green has taken this place back.", "Something grows, slow and patient.",
               "The air is thick and living."]),
    "catacomb": dict(
        feats=[("]", 2, "a niche"), (";", 2, "bone-dust"), ("o", 1, "a sealed urn")],
        tend="dense", palette="dim",
        voice=["The dead were kept here, orderly.", "Your footsteps are the only sound.",
               "Something is interred behind the wall."]),
    "observatory": dict(
        feats=[("o", 2, "a lens-mount"), ("|", 1, "a sighting-rod"), (";", 1, "star-charts")],
        tend="open", palette="holy",
        voice=["This place watched the far dark.", "A great eye once turned here.",
               "The ceiling opens to nothing now."]),
    "marsh": dict(
        feats=[('"', 4, "reeds"), ("-", 2, "shallows"), (";", 1, "sedge")],
        tend="scattered", palette="cold",
        voice=["The mire sucks at your steps.", "Mist lies low over black water.",
               "Something moves in the reeds, or doesn't."]),
    "spire": dict(
        feats=[("|", 3, "a fluted column"), ("o", 1, "a finial")],
        tend="linear", palette="pale",
        voice=["Everything here reaches upward.", "The heights are lost above you.",
               "Wind sounds in the high stone."]),
    "wastes": dict(
        feats=[("`", 2, "grit"), (";", 1, "a bleached bone")],
        tend="scattered", palette="dim",
        voice=["The waste runs flat to the horizon.", "Nothing has come this way in an age.",
               "The wind carries only dust."]),
    # ---- role blocks (a third, tinting layer from the note's graph nature) -----
    "hub": dict(
        feats=[("I", 3, "a worn pillar")], tend="dense", palette="",
        voice=["Many roads met here once.", "This was a place of gathering."]),
    "bridge": dict(
        feats=[(":", 2, "a meeting-stone")], tend="linear", palette="",
        voice=["Two worlds touch at this seam.", "You stand on the edge of things."]),
    "orphan": dict(
        feats=[("o", 1, "a lone marker")], tend="scattered", palette="",
        voice=["Nothing links to this place.", "It was left, and forgotten."]),
    "leaf": dict(
        feats=[("]", 1, "an alcove")], tend="open", palette="",
        voice=["The road ends here.", "There is nowhere further to go."]),
    "cluster": dict(
        feats=[(";", 1, "a common mark")], tend="dense", palette="",
        voice=["This place belonged to many.", "Others were here, and near."]),
}

# every feature glyph the block system can place (walkable texture/decor)
BLOCK_GLYPHS = frozenset(g for b in BLOCKS.values() for (g, _w, _n) in b["feats"])
BLOCK_NOUN = {g: n for b in BLOCKS.values() for (g, _w, n) in b["feats"]}


class Environment:
    """An ordered blend of blocks. Dominant-first: the head block sets the palette
    and leading voice and contributes the most features; tail blocks tint."""

    def __init__(self, block_names):
        self.names = [b for b in block_names if b in BLOCKS]
        if not self.names:
            self.names = ["inert"]

    @property
    def dominant(self):
        return self.names[0]

    def palette(self) -> str:
        for n in self.names:                       # first block with a real palette wins
            p = BLOCKS[n].get("palette")
            if p:
                return p
        return "dim"

    def tendency(self) -> str:
        return BLOCKS[self.dominant]["tend"]

    def features(self):
        """(glyph, weight, noun) with dominance falloff: head block full weight,
        each later block cut to a third, so the blend reads as mostly-A-tinted-B.
        (Halving proved too shallow: the tint blocks' shared filler glyphs topped
        every region's histogram and all ground read alike.)"""
        out = []
        for i, n in enumerate(self.names):
            scale = 1.0 / (3 ** i)
            for g, w, noun in BLOCKS[n]["feats"]:
                out.append((g, w * scale, noun))
        return out

    def voice(self):
        """Ambient lines, dominant block's first, then one from each tint block."""
        lines = list(BLOCKS[self.dominant]["voice"])
        for n in self.names[1:]:
            v = BLOCKS[n]["voice"]
            if v:
                lines.append(v[0])
        return lines

    def label(self) -> str:
        return "-".join(self.names)


def environment_for(element, biome, role=None, favors=()) -> Environment:
    """Compose a place's environment from its signals, ordered by dominance: the
    biome is the ground truth of the LAND, the element is its CHARGE, the role a
    faint personal tint. `favors` are the region's AREA-KIND blocks (labyrinth ->
    archive, grove -> garden); they lead, so the kind reads strongest of all. Order =
    which reads strongest. (A different vault, or a swapped element/biome, permutes to
    a different place from the same blocks.)"""
    order = [b for b in favors if b in BLOCKS]
    order += [b for b in (biome, element) if b in BLOCKS and b not in order]
    if role in BLOCKS and role not in order:
        order.append(role)
    return Environment(order or ["inert"])
