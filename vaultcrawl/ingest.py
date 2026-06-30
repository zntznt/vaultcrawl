"""Ingest a folder of markdown into Notes + a directed link graph. Pure stdlib.

A note's `id` is its filename stem, lowercased. Wikilinks resolve against those ids;
unresolved links (to notes that don't exist) are dropped from the graph but counted.

The vault *seed* is a hash of note ids + bodies + resolved links only -- NOT mtimes or
absolute paths -- so copying the vault to another machine yields the identical world.
mtimes are used solely for the per-region `activity` signal.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field

_WIKILINK = re.compile(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")
_TAG = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]*)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$", re.M)
_TODO = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+)$", re.M)
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_IMG = re.compile(r"!\[\[([^\]]+)\]\]|!\[[^\]]*\]\(([^)]+)\)")
_KV = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")


def _norm(name: str) -> str:
    return name.strip().lower()


def parse_frontmatter(text: str):
    """Tiny YAML-ish frontmatter reader: scalars, inline `[a, b]`, and block lists."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), text[m.end():]
    fm: dict = {}
    key = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if re.match(r"^\s*-\s+", line) and key is not None:
            fm.setdefault(key, [])
            if isinstance(fm[key], list):
                fm[key].append(line.split("-", 1)[1].strip().strip("\"'"))
            continue
        kv = _KV.match(line.strip())
        if not kv:
            continue
        key, val = kv.group(1).strip(), kv.group(2).strip()
        if val == "":
            fm[key] = []  # a block list likely follows
        elif val.startswith("[") and val.endswith("]"):
            fm[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
            key = None
        else:
            fm[key] = val.strip("\"'")
            key = None
    return fm, body


@dataclass
class Note:
    id: str
    title: str
    path: str
    body: str
    tags: list = field(default_factory=list)
    links: list = field(default_factory=list)        # resolved note ids
    raw_links: list = field(default_factory=list)     # all link targets (pre-resolution)
    headings: list = field(default_factory=list)
    todos: list = field(default_factory=list)
    images: list = field(default_factory=list)
    frontmatter: dict = field(default_factory=dict)
    mtime: float = 0.0
    length: int = 0


@dataclass
class Vault:
    notes: dict          # id -> Note
    out_adj: dict        # id -> [linked ids]  (directed: source -> target)
    seed: str
    link_count: int


def _iter_markdown(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files):
            if fn.lower().endswith((".md", ".markdown")):
                yield os.path.join(dirpath, fn)


def load_vault(root: str) -> Vault:
    paths = sorted(_iter_markdown(root))
    notes: dict = {}

    for path in paths:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        stem = os.path.splitext(os.path.basename(path))[0]
        nid = _norm(stem)
        fm, body = parse_frontmatter(text)

        tags = list(_TAG.findall(body))
        for t in fm.get("tags", []) if isinstance(fm.get("tags"), list) else []:
            tags.append(str(t).lstrip("#"))
        raw_links = [_norm(x) for x in _WIKILINK.findall(body)]
        images = [a or b for a, b in _IMG.findall(body)]

        notes[nid] = Note(
            id=nid,
            title=stem,
            path=path,
            body=body.strip(),
            tags=sorted(set(tags)),
            raw_links=raw_links,
            headings=[h for _lvl, h in _HEADING.findall(body)],
            todos=[t.strip() for t in _TODO.findall(body)],
            images=images,
            frontmatter=fm,
            mtime=os.path.getmtime(path),
            length=len(body),
        )

    # resolve links against existing note ids
    out_adj = {nid: [] for nid in notes}
    link_count = 0
    for nid, note in notes.items():
        seen = set()
        for tgt in note.raw_links:
            if tgt in notes and tgt != nid and tgt not in seen:
                out_adj[nid].append(tgt)
                note.links.append(tgt)
                seen.add(tgt)
                link_count += 1

    seed = _vault_seed(notes, out_adj)
    return Vault(notes=notes, out_adj=out_adj, seed=seed, link_count=link_count)


def _vault_seed(notes: dict, out_adj: dict) -> str:
    h = hashlib.sha256()
    for nid in sorted(notes):
        n = notes[nid]
        h.update(nid.encode())
        h.update(b"\x00")
        h.update(n.body.encode())
        h.update(b"\x00")
        h.update(",".join(sorted(out_adj[nid])).encode())
        h.update(b"\x01")
    return h.hexdigest()[:16]
