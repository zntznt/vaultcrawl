"""Two-pass generation: bible (global) then content (per slot).

Deterministic given (vault, blueprint, OfflineStubLLM). Swapping in a real LLM is the
only source of nondeterminism, and its output is baked, so the runtime stays pure.
"""
from __future__ import annotations

import json

from . import prompts
from .analyze import Analysis
from .ingest import Vault
from .llm import OfflineStubLLM


def _clean(slot: dict) -> dict:
    return {k: v for k, v in slot.items() if not k.startswith("_")}


def _bible_inputs(vault: Vault, an: Analysis):
    clusters = []
    for ci, members in enumerate(an.communities):
        if not members:
            continue
        counts: dict = {}
        for m in members:
            for t in vault.notes[m].tags:
                counts[t] = counts.get(t, 0) + 1
        toptags = [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:4]
        top = max(members, key=lambda nid: (an.pagerank.get(nid, 0.0), nid))
        clusters.append({"clusterId": ci, "tags": toptags,
                         "topTitle": vault.notes[top].title, "size": len(members)})

    # inter-community edge weights -> faction border strength
    pair: dict = {}
    for src, tgts in vault.out_adj.items():
        if src not in an.community:
            continue
        cs = an.community[src]
        for t in tgts:
            if t not in an.community:
                continue
            ct = an.community[t]
            if cs != ct:
                key = tuple(sorted((cs, ct)))
                pair[key] = pair.get(key, 0) + 1
    pairs = [[i, j, w] for (i, j), w in sorted(pair.items())]

    lines = [f"- cluster [{c['clusterId']}] size={c['size']} "
             f"tags={c['tags'] or ['(untagged)']} anchor='{c['topTitle']}'" for c in clusters]
    borders = [f"- clusters [{i}]<->[{j}] share {w} link(s)" for i, j, w in pairs] or ["- (no borders)"]
    summary = (f"{len(vault.notes)} notes, {vault.link_count} links, {len(clusters)} clusters.\n\n"
               "Clusters:\n" + "\n".join(lines) + "\n\nBorders:\n" + "\n".join(borders))
    return summary, {"seedKey": vault.seed, "clusters": clusters, "pairs": pairs}


def generate_world(vault: Vault, an: Analysis, blueprint: dict, llm=None) -> dict:
    from . import __version__
    llm = llm or OfflineStubLLM()

    # ---- PASS 1: world bible ----
    summary, bctx = _bible_inputs(vault, an)
    bible = llm.complete_json(prompts.BIBLE_SYSTEM,
                              prompts.BIBLE_USER.format(summary=summary),
                              prompts.BIBLE_SCHEMA, context=bctx)
    faction_name = {f["id"]: f["name"] for f in bible.get("factions", [])}
    region_biome = {r["id"]: r["biome"] for r in blueprint["regions"]}

    def fill(kind, slot, extra):
        src = slot.get("_src", {})
        mech = {k: v for k, v in slot.items() if not k.startswith("_") and k != "id"}
        fac = faction_name.get(slot.get("factionId") or extra.get("factionId"), "—")
        user = prompts.CONTENT_USER.format(
            world_name=bible["worldName"], tone=bible["tone"],
            aesthetic=", ".join(bible["aesthetic"]), naming=bible["namingConventions"],
            kind=kind, mechanical=json.dumps(mech), faction=fac,
            title=src.get("title", "?"), tags=src.get("tags", []), excerpt=src.get("excerpt", ""))
        ctx = {"seedKey": f"{vault.seed}:{slot['id']}", "kind": kind,
               "title": src.get("title"), "tags": src.get("tags", []),
               "faction_name": fac, **extra}
        return llm.complete_json(prompts.CONTENT_SYSTEM, user, prompts.CONTENT_SCHEMAS[kind], context=ctx)

    # A real LLM may return partial JSON (a missing key, a refusal). The bake must
    # never abort on that: fall back to the note's own title / a plain default, so
    # every slot always gets a name. The offline stub always supplies these keys.
    def _named(slot, out):
        raw = slot.get("_src", {}).get("title") or slot.get("id", "the nameless")
        return out.get("name") or " ".join(w.capitalize() for w in str(raw).replace("_", " ").split())

    # ---- PASS 2: local content ----
    regions = []
    for r in blueprint["regions"]:
        out = fill("region", r, {"biome": r["biome"]})
        regions.append(_clean({**r, "name": _named(r, out), "flavor": out.get("flavor", "")}))

    bosses = []
    for b in blueprint["bosses"]:
        out = fill("boss", b, {"biome": region_biome.get(b["regionId"], "archive"),
                               "backlinks": b.get("_src", {}).get("backlinks", 0)})
        bosses.append(_clean({**b, "name": _named(b, out), "title": out.get("title", ""),
                              "flavor": out.get("flavor", "")}))

    enemies = []
    for e in blueprint["enemies"]:
        out = fill("enemy", e, {"archetype": e["archetype"], "damageType": e["damageType"]})
        enemies.append(_clean({**e, "name": _named(e, out), "flavor": out.get("flavor", "")}))

    items = []
    for it in blueprint["items"]:
        out = fill("item", it, {"rarity": it["rarity"], "slot": it["slot"]})
        items.append(_clean({**it, "name": _named(it, out), "flavor": out.get("flavor", "")}))

    secrets = []
    for s in blueprint["secrets"]:
        out = fill("secret", s, {"kind": s["kind"]})
        secrets.append(_clean({**s, "flavor": out.get("flavor", "Something here resists being read.")}))

    quests = []
    for q in blueprint["quests"]:
        out = fill("quest", q, {"kind": q["kind"], "todo": q.get("_todo", "")})
        quests.append(_clean({**q, "objective": out.get("objective", "A charge left unfinished in your own hand.")}))

    return {
        "version": __version__,
        "seed": vault.seed,
        "generatedFrom": {
            "vaultPath": "",  # filled by bake
            "noteCount": len(vault.notes),
            "linkCount": vault.link_count,
            "communityCount": len([c for c in an.communities if c]),
            "padded": False,
        },
        "bible": bible,
        "graph": blueprint.get("_graph", {"nodes": {}}),
        "regions": regions,
        "enemies": enemies,
        "bosses": bosses,
        "items": items,
        "secrets": secrets,
        "quests": quests,
    }
