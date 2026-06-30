"""The two-pass generation contract.

PASS 1 (bible): one call. Sees only a *summary* of the graph -- cluster tags, top
note titles, stats -- and authors the world's global identity: name, tone, naming
conventions, shared aesthetic vocabulary, and the factions + their relations.

PASS 2 (content): one call per slot. Sees the bible digest, the slot's *fixed*
mechanical fields (which it must not contradict), and the source note excerpt. It
writes only names/flavor. Grounded in the note, constrained by the bible.

These strings are exactly what you would send to a real model with JSON/structured
output. The offline stub in llm.py honours the same schemas deterministically.
"""

# --------------------------------------------------------------------------- #
# PASS 1 -- WORLD BIBLE
# --------------------------------------------------------------------------- #

BIBLE_SYSTEM = """\
You are the world-architect for a traditional roguelike whose setting is generated
from a person's personal notes. You write the WORLD BIBLE: the global identity that
every later piece of content must obey.

Hard rules:
- TRANSFORM, do not transcribe. Note topics become metaphors, never literal labels.
  ("taxes" -> bureaucratic golems in a ledger-vault, never a room called "Taxes".)
- Privacy: never surface real names, places, employers, or sensitive personal facts.
  Abstract them into archetypes.
- Output ONLY valid JSON matching the provided schema. No prose outside the JSON.
- The factions you name correspond 1:1 to the clusters given, by clusterId.
- Stances must be internally consistent (if A is at war with B, B is at war with A).
"""

BIBLE_USER = """\
Graph summary of the vault:

{summary}

Author the world bible. Give it one coherent tone and a small shared aesthetic
vocabulary that all regions and creatures will draw from. Name one faction per
cluster (clusterId in brackets) and assign a stance toward each other faction it
shares a border with; everything else is neutral by default.
"""

BIBLE_SCHEMA = {
    "x-kind": "bible",
    "type": "object",
    "required": ["worldName", "tone", "namingConventions", "aesthetic", "factions"],
    "properties": {
        "worldName": {"type": "string"},
        "tone": {"type": "string"},
        "namingConventions": {"type": "string"},
        "aesthetic": {"type": "array", "items": {"type": "string"}},
        "factions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "ethos", "clusterId", "relations"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "ethos": {"type": "string"},
                    "clusterId": {"type": "integer"},
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["factionId", "stance"],
                            "properties": {
                                "factionId": {"type": "string"},
                                "stance": {"enum": ["ally", "rival", "vassal", "neutral", "war"]},
                            },
                        },
                    },
                },
            },
        },
    },
}

# --------------------------------------------------------------------------- #
# PASS 2 -- LOCAL CONTENT
# --------------------------------------------------------------------------- #

CONTENT_SYSTEM = """\
You name and describe one element of a roguelike world generated from personal notes.
You are given the WORLD BIBLE (obey its tone, aesthetic, and naming conventions), the
element's FIXED mechanical stats (never contradict or restate them as numbers), and
the SOURCE NOTE it derives from.

Hard rules:
- TRANSFORM the note into metaphor. Do not quote it or name real people/places.
- Stay consistent with the world bible's tone and the element's biome/faction.
- Flavor is 1-2 sentences, evocative, second-person-friendly.
- Output ONLY valid JSON matching the schema.
"""

CONTENT_USER = """\
WORLD: {world_name} -- {tone}
AESTHETIC: {aesthetic}
NAMING: {naming}

ELEMENT KIND: {kind}
FIXED STATS (do not change): {mechanical}
FACTION CONTEXT: {faction}

SOURCE NOTE "{title}" (tags: {tags}):
{excerpt}

Write the {kind}'s name and flavor.
"""

# One small schema per slot kind. The generator merges the returned fields into the
# mechanical slot, then strips helper keys before baking.
CONTENT_SCHEMAS = {
    "region": {
        "x-kind": "region",
        "type": "object",
        "required": ["name", "flavor"],
        "properties": {"name": {"type": "string"}, "flavor": {"type": "string"}},
    },
    "boss": {
        "x-kind": "boss",
        "type": "object",
        "required": ["name", "title", "flavor"],
        "properties": {"name": {"type": "string"}, "title": {"type": "string"}, "flavor": {"type": "string"}},
    },
    "enemy": {
        "x-kind": "enemy",
        "type": "object",
        "required": ["name", "flavor"],
        "properties": {"name": {"type": "string"}, "flavor": {"type": "string"}},
    },
    "item": {
        "x-kind": "item",
        "type": "object",
        "required": ["name", "flavor"],
        "properties": {"name": {"type": "string"}, "flavor": {"type": "string"}},
    },
    "secret": {
        "x-kind": "secret",
        "type": "object",
        "required": ["flavor"],
        "properties": {"flavor": {"type": "string"}},
    },
    "quest": {
        "x-kind": "quest",
        "type": "object",
        "required": ["objective"],
        "properties": {"objective": {"type": "string"}},
    },
}
