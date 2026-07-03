"""The corpus layer: your notes' own words, baked as a weavable chain.

Each community's note bodies become one order-2 word chain (Caves-of-Qud style), plus
per-note starter phrases, stored as manifest["corpus"]. The runtime walks the chain,
seeded per floor, to weave marginalia in the vault's own voice: never verbatim whole
notes, but never generic templates either. Deterministic, pure stdlib, no LLM.

Privacy note: this ships fragments of your actual wording into world.json. It is the
one place the pipeline is transcription rather than transformation, by design.
"""
from __future__ import annotations

import re

_STRIP = (
    (re.compile(r"```.*?```", re.S), " "),                   # code fences
    (re.compile(r"!\[\[[^\]]+\]\]|!\[[^\]]*\]\([^)]*\)"), " "),   # image embeds
    (re.compile(r"\[\[(?:[^\]|#^]+)(?:[#^][^\]|]*)?\|([^\]]*)\]\]"), r"\1"),  # [[x|alias]]
    (re.compile(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?\]\]"), r"\1"),  # [[x]]
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),            # [text](url)
    (re.compile(r"https?://\S+"), " "),
    (re.compile(r"^\s*#{1,6}\s+", re.M), ""),                 # heading markers
    (re.compile(r"^\s*[-*]\s+\[[ xX]\]\s*", re.M), ""),       # checkbox markers
    (re.compile(r"^\s*[-*>]\s+", re.M), ""),                  # list/quote markers
    (re.compile(r"(?:^|\s)#[\w/-]+"), " "),                   # tags are metadata
    (re.compile(r"[`*_|]"), ""),                              # emphasis noise
)

# ponytail: 1500 tokens per note bounds manifest size; sample more cleverly if a
# journal-sized vault ever makes world.json unwieldy
_MAX_TOKENS = 1500


def _clean(body: str) -> str:
    for rx, repl in _STRIP:
        body = rx.sub(repl, body)
    return body


def _tokens(body: str) -> list:
    return _clean(body).split()[:_MAX_TOKENS]


def _lines(body: str) -> list:
    """Intact prose sentences, verbatim. These are the recognition payload: the
    runtime speaks them back unchanged, so a wanderer meets their own words whole.
    Filtered to sentence-shaped prose; headings, fragments, and lists don't qualify."""
    out, seen = [], set()
    for sent in re.split(r"(?<=[.!?])\s+|\n+", _clean(body)):
        words = sent.split()
        # bare leading numerals (word counts, list indices) are structure, not voice
        while words and words[0].strip(".,:;)").isdigit():
            words.pop(0)
        sent = " ".join(words)
        if not (4 <= len(words) <= 24) or not sent or sent[-1] not in ".!?":
            continue
        # prose has lowercase flow; Title Case Runs and ALL-CAPS are structure, not voice
        lower = sum(1 for w in words if w[:1].islower())
        if lower < len(words) // 2 or sent in seen:
            continue
        seen.add(sent)
        out.append(sent)
    return out[:10]


def _starters(body: str) -> list:
    """The first two words of each sentence: natural entry points into the chain."""
    out, seen = [], set()
    for sent in re.split(r"(?<=[.!?])\s+|\n+", _clean(body)):
        words = sent.split()
        if len(words) < 3:
            continue
        prefix = f"{words[0]} {words[1]}"
        if prefix not in seen:
            seen.add(prefix)
            out.append(prefix)
    return out[:12]


def build_corpus(vault, an) -> dict:
    """communityId (str) -> {"chain": {"w1 w2": [w3, ...]}, "starters": {noteId: [...]}}.

    Duplicate successors are kept: rng.choice over them is natural frequency weighting.
    Notes are visited in sorted order so the chain is byte-stable across bakes.
    """
    comms: dict = {}
    for nid in sorted(vault.notes):
        note = vault.notes[nid]
        lines = _lines(note.body)
        # the chain is built from PROSE SENTENCES, not raw tokens: weaving from
        # heading/list debris produced structural garbage ("How this folder is
        # organized Reference (root)..."). Notes with no qualifying prose (dice
        # tables, inventories) fall back to their cleaned tokens so they still speak.
        toks = " ".join(lines).split() if lines else _tokens(note.body)
        toks = toks[:_MAX_TOKENS]
        if len(toks) < 3:
            continue
        c = comms.setdefault(str(an.community.get(nid, -1)),
                             {"chain": {}, "starters": {}, "lines": {}})
        for i in range(len(toks) - 2):
            c["chain"].setdefault(f"{toks[i]} {toks[i + 1]}", []).append(toks[i + 2])
        if lines:
            c["lines"][nid] = lines
            starts, seen = [], set()
            for ln in lines:
                ws = ln.split()
                pre = f"{ws[0]} {ws[1]}"
                if pre not in seen:
                    seen.add(pre)
                    starts.append(pre)
            c["starters"][nid] = starts[:12]
        else:
            starts = _starters(note.body)
            if starts:
                c["starters"][nid] = starts
    return comms
