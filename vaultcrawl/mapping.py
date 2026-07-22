"""Deterministic metrics -> mechanical slots.

This layer owns every balance-relevant number (tier, depth, powerBudget) and every
structural reference (which region, which faction). The LLM is handed the *result*
and only writes names/flavor into it -- it can never move a tier or a depth.

Output is a Blueprint: dict of slot lists. Each slot carries its mechanical fields,
an `id`, and a private `_src` block (note title/excerpt/tags) used only to ground the
LLM prompt. `_src` is stripped before baking.
"""
from __future__ import annotations

import bisect
import hashlib

from .analyze import Analysis
from .ingest import Vault

MAX_DEPTH = 26  # classic 26-floor descent

BIOMES = ["archive", "garden", "foundry", "catacomb", "observatory", "marsh", "spire", "wastes"]
# The bestiary is READ from a note's nature, not blind-hashed. A note's graph ROLE
# sets the creature FAMILY; its age and degree pick the member within it — so a lonely
# ancient note and a fresh well-connected one yield visibly different creatures.
#   hub (busy, central)     -> orchestrators & swarms of activity
#   bridge (spans clusters) -> liminal, two-natured things
#   cluster (in the thick)  -> social pack creatures
#   leaf (a dead-end)       -> solitary specialists
#   orphan (unlinked)       -> wild, feral, unbound
ARCHETYPES = ["scribe", "golem", "swarm", "warden", "echo", "beast", "construct", "shade",
              "seraph", "wisp", "colossus", "chorus", "revenant", "gloom", "sentinel",
              "drifter", "hound", "myriad"]
# family -> ordered members: [fresh/vivid ... old/decayed], picked by the note's age
_FAMILY = {
    "hub":     ["seraph", "warden", "colossus"],   # central, commanding
    "bridge":  ["wisp", "echo", "revenant"],        # liminal, spanning
    "cluster": ["chorus", "swarm", "myriad"],       # social, many
    "leaf":    ["scribe", "sentinel", "gloom"],     # solitary specialists
    "orphan":  ["beast", "hound", "drifter"],       # feral, unbound
    "discovery": ["beast", "hound", "drifter"],
}
DAMAGE = ["blade", "flame", "frost", "venom", "psychic", "decay", "arc"]


# family -> inherited properties (template-based trait inheritance)
# Every member of a family inherits these base traits.
_FAMILY_TRAITS = {
    "hub":     {"actions": ["shield", "rally"], "desc": "commanding presence"},
    "bridge":  {"actions": ["blink", "spit"], "desc": "liminal nature"},
    "cluster": {"actions": ["rally", "summon"], "desc": "social cohesion"},
    "leaf":    {"actions": ["shield"], "desc": "solitary guard"},
    "orphan":  {"actions": ["enrage", "split"], "desc": "feral instinct"},
    "discovery": {"actions": ["enrage"], "desc": "wild discovery"},
}

# per-archetype overrides: specific members add or remove inherited actions
_ARCHETYPE_OVERRIDES: dict[str, dict] = {
    "seraph":    {"add": ["blink"], "remove": {"rally"}},
    "warden":    {"add": [], "remove": set()},
    "colossus":  {"add": ["enrage"], "remove": {"rally"}},
    "wisp":      {"add": [], "remove": set()},
    "echo":      {"add": ["summon"], "remove": set()},
    "revenant":  {"add": ["enrage"], "remove": {"spit"}},
    "chorus":    {"add": ["split"], "remove": {"summon"}},
    "swarm":     {"add": [], "remove": set()},
    "myriad":    {"add": ["blink"], "remove": {"rally"}},
    "scribe":    {"add": [], "remove": set()},
    "sentinel":  {"add": ["enrage"], "remove": set()},
    "gloom":     {"add": ["spit"], "remove": {"shield"}},
    "beast":     {"add": ["shield"], "remove": set()},
    "hound":     {"add": [], "remove": set()},
    "drifter":   {"add": ["blink"], "remove": {"split"}},
}


def family_actions(role: str, archetype: str) -> list[str]:
    """Inherited special actions for an enemy: family base + archetype overrides."""
    base = list(_FAMILY_TRAITS.get(role, {}).get("actions", []))
    over = _ARCHETYPE_OVERRIDES.get(archetype, {})
    for a in over.get("add", []):
        if a not in base:
            base.append(a)
    for r in over.get("remove", set()):
        if r in base:
            base.remove(r)
    return base


def family_desc(role: str) -> str:
    return _FAMILY_TRAITS.get(role, {}).get("desc", "")


def _archetype_for(role, age, degree, nid=""):
    """A creature's kind, read from its note: role -> family, then a within-family
    member chosen from the signals that actually VARY across a vault. Age alone
    collapses when a whole vault was edited at once (everything reads 'fresh'), so
    we blend age, connection-degree, and a stable per-note hash to spread the three
    members of each family. Still deterministic and note-driven, just not degenerate."""
    fam = _FAMILY.get(role, ["construct", "golem", "shade"])
    # combine: old notes lean decayed (+), highly-connected lean vivid (-), plus a
    # per-note jitter so equal-signal notes still differ across the family.
    score = 0
    score += 0 if age >= 0.5 else 1           # older -> later member
    score += 1 if degree >= 4 else 0          # busy note -> a different member
    score += _shash("archmember", nid) % 3    # stable spread within the family
    return fam[score % len(fam)]
ITEM_SLOTS = ["weapon", "armor", "trinket", "consumable", "relic"]
RARITY_BY_TIER = ["common", "common", "uncommon", "rare", "epic", "legendary"]  # index by tier 0..5
POWER_BAND = {"common": 4, "uncommon": 8, "rare": 14, "epic": 22, "legendary": 32}
SECRET_KINDS = ["hidden_room", "lost_artifact", "hidden_boss"]
QUEST_KINDS = ["fetch", "slay", "escort", "cleanse", "recover"]

# Soft hints so a note tagged #garden lands in a garden; everything else hashes in.
_TAG_BIOME_HINTS = {
    "idea": "garden", "note": "archive", "ref": "archive", "reference": "archive",
    "project": "foundry", "work": "foundry", "build": "foundry",
    "journal": "catacomb", "daily": "catacomb", "log": "catacomb",
    "philosophy": "observatory", "theory": "observatory", "math": "observatory",
    "draft": "marsh", "wip": "marsh", "messy": "marsh",
    "goal": "spire", "vision": "spire",
    "archive": "archive", "dead": "wastes", "dropped": "wastes",
}

# A region's reactive *element* (Qud-style) is generated from its dominant tags. The
# runtime uses it to seed tile properties so each region fights differently.
ELEMENTS = ["charged", "wet", "flammable", "frozen", "sacred", "corrosive", "inert"]
_TAG_ELEMENT_HINTS = {
    "project": "charged", "code": "charged", "work": "charged", "build": "charged", "lang": "charged",
    "architecture": "charged",
    "journal": "wet", "daily": "wet", "emotion": "wet", "writing": "wet",
    "idea": "flammable", "draft": "flammable", "wip": "flammable", "brainstorm": "flammable",
    "philosophy": "frozen", "theory": "frozen", "math": "frozen", "mind": "frozen",
    "music": "sacred", "art": "sacred", "ritual": "sacred", "mortality": "sacred", "hobby": "sacred",
    "health": "corrosive", "habit": "corrosive", "finance": "corrosive", "system": "corrosive",
}

_CAP = 24  # cap quests/secrets so a journal-heavy vault doesn't explode the manifest


def _shash(*parts) -> int:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16)


def _pick(seq, *parts):
    return seq[_shash(*parts) % len(seq)]


def _tier_of(value: float, pr_sorted: list) -> int:
    if not pr_sorted:
        return 1
    r = bisect.bisect_right(pr_sorted, value) / len(pr_sorted)
    return min(5, max(1, int(r * 5) + 1))


def _excerpt(body: str, n: int = 240) -> str:
    flat = " ".join(body.split())
    return flat[:n]


def _region_biome(tags, ci, seed):
    for t in tags:
        stem = t.lower().split("/")[0]
        if stem in _TAG_BIOME_HINTS:
            return _TAG_BIOME_HINTS[stem]
    return _pick(BIOMES, "biome", seed, ci)


def _region_element(tags, ci, seed):
    for t in tags:
        stem = t.lower().split("/")[0]
        if stem in _TAG_ELEMENT_HINTS:
            return _TAG_ELEMENT_HINTS[stem]
    return _pick(ELEMENTS, "element", seed, ci)


def _node_role(nid, an, hub_threshold):
    """Coarse graph role used by systems (e.g. sigil abilities)."""
    if an.degree.get(nid, 0) == 0:
        return "orphan"
    if nid in an.bridges:
        return "bridge"
    if an.pagerank.get(nid, 0.0) >= hub_threshold:
        return "hub"
    if an.degree.get(nid, 0) == 1:
        return "leaf"
    return "cluster"


def build_graph_block(vault: Vault, an: Analysis) -> dict:
    """Per-note graph data the runtime systems consume (sigils, knowledge, history)."""
    nbrs = {nid: set() for nid in vault.notes}
    for s, ts in vault.out_adj.items():
        for t in ts:
            nbrs[s].add(t)
            nbrs[t].add(s)
    mtimes = [nt.mtime for nt in vault.notes.values()] or [0.0]
    lo, hi = min(mtimes), max(mtimes)
    span = (hi - lo) or 1.0
    hub_threshold = an.pr_sorted[int(len(an.pr_sorted) * 0.8)] if an.pr_sorted else 1.0
    nodes = {}
    for nid, note in vault.notes.items():
        nodes[nid] = {
            "title": note.title,
            "pagerank": round(an.pagerank.get(nid, 0.0), 5),
            "betweenness": round(an.betweenness.get(nid, 0.0), 5),   # flow / facilitator
            "degree": an.degree.get(nid, 0),
            "community": an.community.get(nid, -1),
            "members": an.members.get(nid, []),                       # semilattice membership
            "bridge": nid in an.bridges,
            "role": _node_role(nid, an, hub_threshold),
            "activity": round((note.mtime - lo) / span, 3),
            "tags": note.tags[:8],
            "neighbors": sorted(nbrs[nid]),
        }
    # Interlock-weighted undirected edge list: how deeply two centers should interpenetrate.
    # weight = 1 + (shared tags) + (mutual link ? 1 : 0).
    out = vault.out_adj
    seen, edges = set(), []
    for a in sorted(nbrs):
        ta = set(vault.notes[a].tags)
        for b in sorted(nbrs[a]):   # sorted: edge order must not float run-to-run
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            shared = len(ta & set(vault.notes[b].tags))
            mutual = 1 if (b in out.get(a, []) and a in out.get(b, [])) else 0
            edges.append({"a": key[0], "b": key[1], "interlock": 1 + shared + mutual})
    return {"nodes": nodes, "edges": edges}


def build_blueprint(vault: Vault, an: Analysis) -> dict:
    seed = vault.seed
    notes = vault.notes
    n = len(notes)

    # --- depth: least-central = shallow, most-central = deep ---
    order = sorted(notes, key=lambda nid: (an.pagerank.get(nid, 0.0), nid))
    if n > 1:
        depth_map = {nid: 1 + round(i / (n - 1) * (MAX_DEPTH - 1)) for i, nid in enumerate(order)}
    else:
        depth_map = {nid: 1 for nid in notes}

    # --- mtime -> activity 0..1 ---
    mtimes = [nt.mtime for nt in notes.values()] or [0.0]
    lo, hi = min(mtimes), max(mtimes)
    span = (hi - lo) or 1.0
    activity = {nid: (notes[nid].mtime - lo) / span for nid in notes}

    hub_threshold = an.pr_sorted[int(len(an.pr_sorted) * 0.8)] if an.pr_sorted else 1.0
    regions, enemies, bosses, items, secrets, quests = [], [], [], [], [], []

    # --- one region + one faction + one boss per community ---
    for ci, members in enumerate(an.communities):
        if not members:
            continue
        # boss = most central note in the community
        top = max(members, key=lambda nid: (an.pagerank.get(nid, 0.0), nid))
        member_depths = [depth_map[m] for m in members]
        region_tags = sorted({t for m in members for t in notes[m].tags})
        rid = f"region_{ci}"
        regions.append({
            "id": rid,
            "biome": _region_biome(region_tags, ci, seed),
            "element": _region_element(region_tags, ci, seed),
            "depthBand": [min(member_depths), max(member_depths)],
            "factionId": f"faction_{ci}",
            "sourceNoteId": top,
            "themeTags": region_tags[:8],
            "activity": round(sum(activity[m] for m in members) / len(members), 3),
            "_src": {"title": notes[top].title, "excerpt": _excerpt(notes[top].body), "tags": region_tags[:8]},
        })
        bosses.append({
            "id": f"boss_{ci}",
            "tier": _tier_of(an.pagerank.get(top, 0.0), an.pr_sorted),
            "depth": depth_map[top],
            "regionId": rid,
            "sourceNoteId": top,
            "_src": {"title": notes[top].title, "excerpt": _excerpt(notes[top].body),
                     "tags": notes[top].tags, "backlinks": an.degree.get(top, 0)},
        })

        # remaining members -> enemies, themed by their own tags
        for m in members:
            if m == top:
                continue
            tags = notes[m].tags
            enemies.append({
                "id": f"enemy_{len(enemies)}",
                "archetype": _archetype_for(_node_role(m, an, hub_threshold),
                                            activity.get(m, 0.5), an.degree.get(m, 0), m),
                "tier": _tier_of(an.pagerank.get(m, 0.0), an.pr_sorted),
                "damageType": _pick(DAMAGE, "dmg", tags[0] if tags else m, m),
                "regionId": rid,
                "sourceNoteId": m,
                "_src": {"title": notes[m].title, "excerpt": _excerpt(notes[m].body), "tags": tags},
            })

    # --- items: notes carrying attachments become loot; ensure a floor of a few ---
    item_sources = [nid for nid in order if notes[nid].images]
    if len(item_sources) < min(5, n):
        # pad with the highest-degree notes so even attachment-free vaults have loot
        extra = sorted(notes, key=lambda nid: (-an.degree.get(nid, 0), nid))
        for nid in extra:
            if nid not in item_sources:
                item_sources.append(nid)
            if len(item_sources) >= min(5, n):
                break
    for nid in item_sources:
        tier = _tier_of(an.pagerank.get(nid, 0.0), an.pr_sorted)
        rarity = RARITY_BY_TIER[tier]
        items.append({
            "id": f"item_{len(items)}",
            "slot": _pick(ITEM_SLOTS, "slot", nid),
            "rarity": rarity,
            "powerBudget": POWER_BAND[rarity],
            "sourceNoteId": nid,
            "_src": {"title": notes[nid].title, "excerpt": _excerpt(notes[nid].body), "tags": notes[nid].tags},
        })

    # --- secrets from orphan notes ---
    for nid in an.orphans[:_CAP]:
        secrets.append({
            "id": f"secret_{len(secrets)}",
            "kind": _pick(SECRET_KINDS, "secret", nid),
            "sourceNoteId": nid,
            "_src": {"title": notes[nid].title, "excerpt": _excerpt(notes[nid].body), "tags": notes[nid].tags},
        })

    # --- quests from open checkboxes ---
    for nid in order:
        for todo in notes[nid].todos:
            if len(quests) >= _CAP:
                break
            quests.append({
                "id": f"quest_{len(quests)}",
                "kind": _pick(QUEST_KINDS, "quest", nid, todo),
                "sourceNoteId": nid,
                "_todo": todo,
                "_src": {"title": notes[nid].title, "excerpt": todo, "tags": notes[nid].tags},
            })

    return {
        "regions": regions,
        "bosses": bosses,
        "enemies": enemies,
        "items": items,
        "secrets": secrets,
        "quests": quests,
        "_graph": build_graph_block(vault, an),
        "_communities": an.communities,
        "_bridges": sorted(an.bridges),
    }
