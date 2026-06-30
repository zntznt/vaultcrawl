"""Invariant validation + sparse-vault fallback. Dependency-free.

The formal contract lives in schema/world.schema.json (use any JSON Schema tool for
structural checks). This module enforces the *game-meaningful* invariants that keep a
world playable: valid enums/ranges, resolvable cross-references, monotonic boss depth,
power budgets within their rarity band, and a non-empty world even from a tiny vault.
"""
from __future__ import annotations

from .mapping import (ARCHETYPES, BIOMES, DAMAGE, ITEM_SLOTS, POWER_BAND,
                      RARITY_BY_TIER, SECRET_KINDS, QUEST_KINDS)

_STANCES = {"ally", "rival", "vassal", "neutral", "war"}
_RARITIES = set(POWER_BAND)


def validate(m: dict) -> list[str]:
    errs: list[str] = []
    region_ids = {r["id"] for r in m["regions"]}
    faction_ids = {f["id"] for f in m["bible"]["factions"]}

    def uniq(items, label):
        seen = set()
        for it in items:
            if it["id"] in seen:
                errs.append(f"duplicate {label} id {it['id']}")
            seen.add(it["id"])

    for label, items in (("region", m["regions"]), ("enemy", m["enemies"]),
                         ("boss", m["bosses"]), ("item", m["items"]),
                         ("secret", m.get("secrets", [])), ("quest", m.get("quests", []))):
        uniq(items, label)

    # bible / factions
    for f in m["bible"]["factions"]:
        for rel in f["relations"]:
            if rel["stance"] not in _STANCES:
                errs.append(f"{f['id']} bad stance {rel['stance']}")
            if rel["factionId"] not in faction_ids:
                errs.append(f"{f['id']} relation -> unknown {rel['factionId']}")

    # regions
    for r in m["regions"]:
        if r["biome"] not in BIOMES:
            errs.append(f"{r['id']} bad biome {r['biome']}")
        if r["factionId"] not in faction_ids:
            errs.append(f"{r['id']} -> unknown faction {r['factionId']}")
        a, b = r["depthBand"]
        if not (1 <= a <= b):
            errs.append(f"{r['id']} bad depthBand {r['depthBand']}")
        if not r.get("name"):
            errs.append(f"{r['id']} empty name")

    # enemies
    for e in m["enemies"]:
        if e["archetype"] not in ARCHETYPES:
            errs.append(f"{e['id']} bad archetype {e['archetype']}")
        if e["damageType"] not in DAMAGE:
            errs.append(f"{e['id']} bad damageType {e['damageType']}")
        if not (1 <= e["tier"] <= 5):
            errs.append(f"{e['id']} tier out of range {e['tier']}")
        if e["regionId"] not in region_ids:
            errs.append(f"{e['id']} -> unknown region {e['regionId']}")
        if not e.get("name"):
            errs.append(f"{e['id']} empty name")

    # bosses -- depth monotonic with tier (deeper boss is never weaker)
    if not m["bosses"]:
        errs.append("no bosses -- world has no objective")
    for bo in m["bosses"]:
        if not (1 <= bo["tier"] <= 5):
            errs.append(f"{bo['id']} tier out of range {bo['tier']}")
        if bo["depth"] < 1:
            errs.append(f"{bo['id']} bad depth {bo['depth']}")
        if bo["regionId"] not in region_ids:
            errs.append(f"{bo['id']} -> unknown region {bo['regionId']}")
        if not bo.get("name"):
            errs.append(f"{bo['id']} empty name")
    ordered = sorted(m["bosses"], key=lambda x: x["depth"])
    for x, y in zip(ordered, ordered[1:]):
        if y["tier"] < x["tier"]:
            errs.append(f"boss tier inversion: {y['id']}(d{y['depth']},t{y['tier']}) "
                        f"shallower-tier than {x['id']}(d{x['depth']},t{x['tier']})")

    # items -- power within rarity band
    for it in m["items"]:
        if it["slot"] not in ITEM_SLOTS:
            errs.append(f"{it['id']} bad slot {it['slot']}")
        if it["rarity"] not in _RARITIES:
            errs.append(f"{it['id']} bad rarity {it['rarity']}")
        elif not (1 <= it["powerBudget"] <= POWER_BAND[it["rarity"]]):
            errs.append(f"{it['id']} power {it['powerBudget']} exceeds {it['rarity']} band")
        if not it.get("name"):
            errs.append(f"{it['id']} empty name")

    for s in m.get("secrets", []):
        if s["kind"] not in SECRET_KINDS:
            errs.append(f"{s['id']} bad kind {s['kind']}")
    for q in m.get("quests", []):
        if q["kind"] not in QUEST_KINDS:
            errs.append(f"{q['id']} bad kind {q['kind']}")
        if not q.get("objective"):
            errs.append(f"{q['id']} empty objective")

    return errs


def region_graph_warnings(m: dict, bridges: list) -> list[str]:
    """Non-fatal: report a disconnected region graph. Hard reachability is enforced
    later by the runtime layout generator, not here."""
    warns: list[str] = []
    if len(m["regions"]) <= 1:
        return warns
    # connectivity over faction-border adjacency
    fac_to_region = {r["factionId"]: r["id"] for r in m["regions"]}
    adj = {r["id"]: set() for r in m["regions"]}
    for f in m["bible"]["factions"]:
        a = fac_to_region.get(f["id"])
        for rel in f["relations"]:
            b = fac_to_region.get(rel["factionId"])
            if a and b:
                adj[a].add(b)
                adj[b].add(a)
    seen, stack = set(), [m["regions"][0]["id"]]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(adj[n] - seen)
    if len(seen) < len(m["regions"]):
        warns.append(f"region graph disconnected ({len(seen)}/{len(m['regions'])} reachable "
                     "via borders); runtime layout will stitch the rest with a guaranteed path")
    return warns


def pad_if_sparse(m: dict) -> dict:
    """Guarantee a playable minimum even from an empty/near-empty vault."""
    if m["regions"] and m["bosses"]:
        return m
    m["generatedFrom"]["padded"] = True
    if not m["bible"]["factions"]:
        m["bible"]["factions"] = [{"id": "faction_0", "name": "The Marginalia",
                                   "ethos": "Keepers of an almost-empty vault.",
                                   "clusterId": 0, "relations": []}]
        m["bible"].setdefault("worldName", "The Blank Vault")
        m["bible"].setdefault("tone", "quiet, unwritten")
        m["bible"].setdefault("namingConventions", "Sparse, provisional.")
        m["bible"].setdefault("aesthetic", ["blank vellum", "first ink"])
    if not m["regions"]:
        m["regions"] = [{"id": "region_0", "name": "The Empty Index", "biome": "archive",
                         "depthBand": [1, 3], "factionId": "faction_0",
                         "sourceNoteId": "", "themeTags": [], "activity": 0.0,
                         "flavor": "A vault with too few notes to map; write more to grow it."}]
    if not m["bosses"]:
        m["bosses"] = [{"id": "boss_0", "name": "The First Blank", "title": "Warden of Nothing Yet",
                        "tier": 1, "depth": 3, "regionId": "region_0", "sourceNoteId": "",
                        "flavor": "What guards an empty vault: the blank page itself."}]
    if not m["enemies"]:
        m["enemies"] = [{"id": "enemy_0", "name": "Drifting Shade", "archetype": "shade",
                         "tier": 1, "damageType": "decay", "regionId": "region_0",
                         "sourceNoteId": "", "flavor": "A placeholder fear."}]
    if not m["items"]:
        m["items"] = [{"id": "item_0", "name": "Blank Charm", "slot": "trinket",
                       "rarity": "common", "powerBudget": POWER_BAND["common"],
                       "sourceNoteId": "", "flavor": "Holds a single unwritten wish."}]
    return m
