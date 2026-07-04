"""Procedural creature portraits — a Spore-style face assembled from PARTS.

A creature is not drawn from a fixed sprite sheet; its portrait is BUILT, part by
part, from what the creature IS. Each facet picks a part:

  archetype  -> the SILHOUETTE family (a scribe is angular, a seraph winged, a
                swarm a scatter of motes, a beast a fanged maw)
  note hash  -> which VARIANT of each part (eyes, brow, mouth, markings) — so every
                note grows a distinct face, but the SAME note always the same face
  tier       -> SIZE (a tier-4 warden looms; a tier-1 wisp is small)
  quality    -> ORNAMENT (a Legendary wears a crown/halo)
  damage     -> the AURA that frames it (flame licks, frost rimes, arc sparks)

Pure, deterministic (seeded off the note id + traits), stdlib only. Returns a list
of text rows the dialog frame draws above the transcript. No colour here — the
front-end can tint by the creature's element later.
"""
from __future__ import annotations

import hashlib


def _rng(*key):
    h = hashlib.sha256("|".join(str(k) for k in key).encode()).hexdigest()
    # a tiny deterministic picker: returns an int stream from the hash
    return [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]


# ---- part sets, keyed to be picked by a hash byte -------------------------- #
# each part is a small string; a face is 5 rows tall, ~9 wide, drawn between a
# silhouette's shoulders.

# each fill slot is a fixed 3-char field so every silhouette row is the same width.
_EYES = ["o o", "O O", "* *", "^ ^", "- -", "@ @", "0 0", ">.<", "v v", "x x"]
_BROWS = ["   ", "═══", "╲ ╱", "╱ ╲", "───", "~ ~"]
_MOUTHS = ["╲_╱", " ─ ", "vvv", "===", " ~ ", "wWw", " o ", ">-<", " = ", "___"]

# archetype -> 5 rows forming the silhouette. {B}=brow {E}=eyes {M}=mouth are each
# a 3-char slot, and every row of a given silhouette is built to one fixed width, so
# the face never ragged. All rows here are 9 wide.
_SILHOUETTE = {
    # angular scholars
    "scribe":   ("┌───────┐", "│  {B}  │", "│  {E}  │", "│  {M}  │", "└──┬┬───┘"),
    "sentinel": ("╔═══════╗", "║  {B}  ║", "║  {E}  ║", "║  {M}  ║", "╚══╤╤═══╝"),
    "gloom":    (".───────.", "(  {B}  )", "(  {E}  )", " ╲ {M} ╱ ", "  `───'  "),
    # winged / radiant
    "seraph":   ("╲╲ ─ ╱╱", "  {B}  ", " ⟨{E}⟩ ", " ╱{M}╲ ", " ╱───╲ "),
    "wisp":     ("  ·˚·  ", "  {B}  ", " ·{E}· ", "  {M}  ", "  ╲·╱  "),
    "chorus":   ("(°)(°)(°)", "   {B}   ", " ( {E} ) ", "   {M}   ", " ╲│││││╱ "),
    # heavy / commanding
    "warden":   ("▐███████▌", "▐  {B}  ▌", "▐  {E}  ▌", "▐  {M}  ▌", "▐▄▄▄▄▄▄▄▌"),
    "colossus": ("▟███████▙", "█  {B}  █", "█  {E}  █", "█  {M}  █", "▜███████▛"),
    "golem":    ("[#######]", "[  {B}  ]", "[  {E}  ]", "[  {M}  ]", "[==(_)==]"),
    "construct": ("+───────+", "|  {B}  |", "|  {E}  |", "|  {M}  |", "+──┴┴───+"),
    # feral
    "beast":    (" ╱╲   ╱╲ ", "  >{B}<  ", "  ({E})  ", "  ╲{M}╱  ", "   `v'   "),
    "hound":    (" ╱╲  ╱╲  ", "   {B}   ", "  ={E}=  ", "  ╲{M}╱  ", "   `U'   "),
    "drifter":  ("  ,───.  ", " (  {B} )", "    {E}   ", " ( {M} ) ", "   `─'   "),
    # swarms / many
    "swarm":    (" . :·: . ", ": . {B}. :", ".·  {E} ·.", ": . {M}. :", " . :·: . "),
    "myriad":   ("·:·:·:·:·", ":·· {B}··:", "·:· {E} ·:", ":·· {M}··:", "·:·:·:·:·"),
    # spectral
    "echo":     ("( ( ( ( (", "    {B}   ", " ·· {E} ··", "    {M}   ", ") ) ) ) )"),
    "revenant": (" ╷     ╷ ", " │ {B} │ ", " │ {E} │ ", " │ {M} │ ", " ╵     ╵ "),
    "shade":    (" ▓▓▓▓▓▓▓ ", " ▓ {B} ▓ ", " ▓ {E} ▓ ", " ▓ {M} ▓ ", " ▓▓▓▓▓▓▓ "),
}
_DEFAULT_SIL = _SILHOUETTE["construct"]

# damage element -> the aura character that frames the face
_AURA = {"flame": "*", "frost": "*", "arc": "!", "venom": ";", "decay": "'",
         "psychic": "~", "blade": "/", "": ""}

# quality tier -> a crown row worn above the head (0 = none)
_CROWN = ["", "", " .-. ", " vvv ", " ♦♦♦ "]


def portrait(archetype: str, nid: str = "", tier: int = 1, quality: int = 0,
             damage: str = "") -> list:
    """Build the creature's portrait rows. Deterministic in (archetype, nid, tier,
    quality, damage)."""
    r = _rng("portrait", nid, archetype)
    sil = _SILHOUETTE.get(archetype, _DEFAULT_SIL)
    eyes = _EYES[r[0] % len(_EYES)]
    brow = _BROWS[r[1] % len(_BROWS)]
    mouth = _MOUTHS[r[2] % len(_MOUTHS)]
    face = [row.replace("{E}", eyes).replace("{B}", brow).replace("{M}", mouth)
            for row in sil]
    # pad every row to the widest, so a hand-drawn silhouette can never render ragged
    fw = max(len(row) for row in face)
    face = [row.ljust(fw) for row in face]

    # ornament: a crown for high quality, worn above the silhouette
    crown = _CROWN[max(0, min(len(_CROWN) - 1, quality))]
    if crown:
        pad = max((len(face[0]) - len(crown)) // 2, 0)
        face = [" " * pad + crown] + face

    # aura: high-tier creatures are framed by their element's mark on both flanks
    aura = _AURA.get(damage, "")
    if aura and tier >= 3:
        w = max(len(row) for row in face)
        face = [f"{aura} {row.ljust(w)} {aura}" for row in face]

    return face
