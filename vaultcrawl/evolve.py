"""Diff two baked worlds into a chronicle of *events*.

Because the world derives from the vault, editing your notes between bakes changes the
world -- and the change itself is content. This compares two world.json manifests by
NOTE ANCHOR (stable across rebakes, unlike the reindexed faction_/region_ ids) and emits
events: kingdoms rise and fall, ideas ascend or wane, the throne changes hands, borders
shift.

    python -m vaultcrawl.evolve old/world.json new/world.json -o evolution.json
"""
from __future__ import annotations

import argparse
import json


def _t(note_id: str) -> str:
    # ponytail: near-dup of llm._title; kept local so this CLI stays import-light (no llm module).
    return " ".join(w.capitalize() for w in str(note_id).replace("-", " ").replace("_", " ").split()) or "?"


def _index(m: dict) -> dict:
    fname = {f["id"]: f["name"] for f in m["bible"]["factions"]}
    fid_anchor = {r["factionId"]: r["sourceNoteId"] for r in m["regions"]}
    regions = {r["sourceNoteId"]: r for r in m["regions"]}
    region_faction = {r["sourceNoteId"]: fname.get(r["factionId"], "?") for r in m["regions"]}

    tier: dict = {}
    for e in m["enemies"]:
        tier[e["sourceNoteId"]] = e["tier"]
    for b in m["bosses"]:
        tier[b["sourceNoteId"]] = b["tier"]
    depth = {b["sourceNoteId"]: b["depth"] for b in m["bosses"]}

    notes = set(regions) | set(tier) | {s["sourceNoteId"] for s in m.get("secrets", [])}
    notes.discard("")

    borders: dict = {}
    for f in m["bible"]["factions"]:
        a = fid_anchor.get(f["id"])
        for rel in f["relations"]:
            b = fid_anchor.get(rel["factionId"])
            if a and b:
                borders[frozenset((a, b))] = rel["stance"]

    return {
        "regions": regions, "region_faction": region_faction, "tier": tier, "depth": depth,
        "notes": notes, "borders": borders, "world_name": m["bible"]["worldName"],
        "final_boss": (max(m["bosses"], key=lambda b: b["depth"])["sourceNoteId"]
                       if m["bosses"] else None),
    }


def evolve(old: dict, new: dict) -> list:
    o, n = _index(old), _index(new)
    events: list = []

    def ev(kind, note, text):
        events.append({"kind": kind, "note": note, "text": text})

    # kingdoms (a region's anchor note)
    for a in sorted(set(n["regions"]) - set(o["regions"])):
        ev("kingdom_rises", a, f"A new realm forms around '{_t(a)}' — {n['region_faction'][a]} claims it.")
    for a in sorted(set(o["regions"]) - set(n["regions"])):
        ev("kingdom_falls", a, f"The realm around '{_t(a)}' breaks apart; its land becomes ruins.")

    # notes entering / leaving the world entirely
    for note in sorted(n["notes"] - o["notes"]):
        ev("note_arrives", note, f"'{_t(note)}' enters the world.")
    for note in sorted(o["notes"] - n["notes"]):
        ev("note_lost", note, f"'{_t(note)}' is gone; what it seeded crumbles to ruin.")

    # influence shifts
    for note in sorted(set(o["tier"]) & set(n["tier"])):
        if n["tier"][note] > o["tier"][note]:
            ev("idea_ascends", note, f"'{_t(note)}' gains influence (tier {o['tier'][note]}→{n['tier'][note]}).")
        elif n["tier"][note] < o["tier"][note]:
            ev("power_wanes", note, f"'{_t(note)}' loses influence (tier {o['tier'][note]}→{n['tier'][note]}).")
    for note in sorted(set(o["depth"]) & set(n["depth"])):
        if n["depth"][note] != o["depth"][note]:
            way = "deeper" if n["depth"][note] > o["depth"][note] else "toward the surface"
            ev("warden_moves", note, f"The warden '{_t(note)}' sinks {way} (floor {o['depth'][note]}→{n['depth'][note]}).")

    if n["final_boss"] and o["final_boss"] != n["final_boss"]:
        ev("throne_taken", n["final_boss"],
           f"A new obsession takes the throne: '{_t(n['final_boss'])}' is now the deepest boss.")

    # borders
    for pair in sorted(set(n["borders"]) - set(o["borders"]), key=sorted):
        a, b = sorted(pair)
        ev("border_opens", a, f"A border opens between '{_t(a)}' and '{_t(b)}' ({n['borders'][pair]}).")
    for pair in sorted(set(o["borders"]) - set(n["borders"]), key=sorted):
        a, b = sorted(pair)
        ev("border_closes", a, f"The border between '{_t(a)}' and '{_t(b)}' dissolves.")
    for pair in sorted(set(o["borders"]) & set(n["borders"]), key=sorted):
        if o["borders"][pair] != n["borders"][pair]:
            a, b = sorted(pair)
            ev("border_shifts", a, f"'{_t(a)}' and '{_t(b)}' shift from {o['borders'][pair]} to {n['borders'][pair]}.")

    return events


_ICON = {
    "kingdom_rises": "👑", "kingdom_falls": "🏚", "note_arrives": "✦", "note_lost": "†",
    "idea_ascends": "▲", "power_wanes": "▽", "warden_moves": "↧", "throne_taken": "♛",
    "border_opens": "⇌", "border_closes": "∅", "border_shifts": "⚔",
}


def render_markdown(old_name: str, new_name: str, events: list) -> str:
    lines = [f"# Chronicle: {old_name} → {new_name}", ""]
    if not events:
        lines.append("_Nothing changed; the world is identical._")
        return "\n".join(lines) + "\n"
    order = ["throne_taken", "kingdom_rises", "kingdom_falls", "note_arrives", "note_lost",
             "idea_ascends", "power_wanes", "warden_moves", "border_opens", "border_shifts", "border_closes"]
    events = sorted(events, key=lambda e: order.index(e["kind"]) if e["kind"] in order else 99)
    for e in events:
        lines.append(f"- {_ICON.get(e['kind'], '•')} {e['text']}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Diff two baked worlds into a chronicle of events.")
    ap.add_argument("old", help="earlier world.json")
    ap.add_argument("new", help="later world.json")
    ap.add_argument("-o", "--out", help="write events as JSON to this path")
    ap.add_argument("--md", help="write the narrative chronicle (markdown) to this path")
    a = ap.parse_args(argv)

    with open(a.old, encoding="utf-8") as fh:
        old = json.load(fh)
    with open(a.new, encoding="utf-8") as fh:
        new = json.load(fh)

    events = evolve(old, new)
    md = render_markdown(old["bible"]["worldName"], new["bible"]["worldName"], events)
    print(md)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(events, fh, indent=2, ensure_ascii=False)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
