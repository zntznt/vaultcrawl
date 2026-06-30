"""The LLM seam.

Interface:  complete_json(system, user, schema, context) -> dict

A real model implementation only needs `system`, `user`, and `schema` (return JSON
conforming to the schema). `context` is a convenience channel the offline stub uses
to stay fully deterministic without parsing the prompt string.

The default OfflineStubLLM produces schema-valid, evocative, *deterministic* output so
the entire pipeline runs end-to-end with no dependencies and no API key. Swap in
AnthropicLLM (sketched at the bottom) to get real prose -- nothing else changes.
"""
from __future__ import annotations

import hashlib
import random
from typing import Protocol


class LLM(Protocol):
    def complete_json(self, system: str, user: str, schema: dict, context: dict | None = None) -> dict:
        ...


# --------------------------------------------------------------------------- #
# Deterministic offline stub
# --------------------------------------------------------------------------- #

_ADJ = ["Hollow", "Gilded", "Sunken", "Fevered", "Patient", "Bound", "Severed",
        "Quiet", "Iron", "Ashen", "Veiled", "Recursive", "Forgotten", "Brimming",
        "Cold", "Marginal", "Annotated", "Unfiled"]
_EPITHET = ["the Unmoved", "the Annotated", "the Half-Remembered", "the Recurring",
            "the Unfiled", "the Overlinked", "the Severed", "the Indexed",
            "the Patient", "the Overgrown", "the Last Draft"]
_TONES = ["a hushed, archival melancholy", "wry bureaucratic dread",
          "luminous and overgrown", "austere and recursive",
          "feverish, half-finished grandeur", "cold cartographic awe"]
_AESTH = ["ink", "lamplight", "ledgers", "moss", "brass", "glass", "dust",
          "vellum", "cold iron", "running water", "marginalia", "wax seals"]
_BIOME_NOUNS = {
    "archive": ["Index", "Reliquary", "Stacks", "Codex Hall"],
    "garden":  ["Arbor", "Greenhouse", "Seedvault", "Orangery"],
    "foundry": ["Forge", "Engine-Yard", "Assembly", "Kiln"],
    "catacomb": ["Ossuary", "Crypt-Walk", "Undercroft", "Vault of Days"],
    "observatory": ["Orrery", "Star-Loom", "Meridian", "Lens-Hall"],
    "marsh": ["Fen", "Drafting-Mire", "Sloughs", "Quag"],
    "spire": ["Spire", "Ascent", "Beacon", "High Causeway"],
    "wastes": ["Wastes", "Tailings", "Dead Letters", "Salt-Flats"],
}
_NOUN = ["Atrium", "Ledger", "Choir", "Engine", "Lantern", "Causeway", "Loom",
         "Wake", "Hollow", "Sigil", "Annex"]
_QUEST_VERB = {"fetch": "Recover", "slay": "Unmake", "escort": "Shepherd",
               "cleanse": "Purge", "recover": "Reclaim"}


def _rng(*key) -> random.Random:
    h = hashlib.sha256("|".join(str(k) for k in key).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def _title(s: str) -> str:
    return " ".join(w.capitalize() for w in str(s).replace("-", " ").replace("_", " ").split()) or "Nameless"


class OfflineStubLLM:
    """Deterministic, dependency-free stand-in for a real model."""

    def complete_json(self, system: str, user: str, schema: dict, context: dict | None = None) -> dict:
        ctx = context or {}
        kind = schema.get("x-kind", "")
        seed = ctx.get("seedKey", user)
        if kind == "bible":
            return self._bible(ctx, seed)
        if kind in ("region", "boss", "enemy", "item", "secret", "quest"):
            return getattr(self, f"_{kind}")(ctx, seed)
        return {}

    # -- pass 1 --
    def _bible(self, ctx, seed):
        rng = _rng("bible", seed)
        clusters = ctx.get("clusters", [])
        top_tags = [t for c in clusters for t in c.get("tags", [])]
        anchor = _title(top_tags[0]) if top_tags else "Memory"
        world_name = rng.choice([
            f"The {anchor} Archives", f"{anchor}'s Wake", f"The Reliquary of {anchor}",
            f"Lower {anchor}", f"The {anchor} Palimpsest",
        ])
        aesthetic = rng.sample(_AESTH, 4)
        tone = rng.choice(_TONES)

        factions = []
        for c in clusters:
            ci = c["clusterId"]
            frng = _rng("faction", seed, ci)
            tag = _title(c["tags"][0]) if c.get("tags") else _title(c.get("topTitle", "the Margin"))
            name = frng.choice([
                f"The Order of {tag}", f"Keepers of {tag}", f"The {tag} Concord",
                f"House {tag}", f"The {tag} Synod",
            ])
            factions.append({
                "id": f"faction_{ci}",
                "name": name,
                "ethos": frng.choice([
                    f"They tend what the {aesthetic[0]} preserves.",
                    f"They believe nothing is finished, only filed.",
                    f"They guard the borders where one idea bleeds into another.",
                    f"They worship the deepest, most-linked truth and fear its silence.",
                ]),
                "clusterId": ci,
                "relations": [],
            })

        # symmetric stances from inter-cluster bridge weights
        by_id = {f["clusterId"]: f for f in factions}
        for i, j, w in ctx.get("pairs", []):
            if i not in by_id or j not in by_id:
                continue
            prng = _rng("stance", seed, i, j)
            if w >= 3:
                stance = prng.choice(["ally", "war"])
            elif w == 2:
                stance = prng.choice(["rival", "vassal"])
            else:
                stance = prng.choice(["rival", "neutral"])
            by_id[i]["relations"].append({"factionId": f"faction_{j}", "stance": stance})
            by_id[j]["relations"].append({"factionId": f"faction_{i}", "stance": stance})

        return {
            "worldName": world_name,
            "tone": tone,
            "namingConventions": f"Places take the form 'The <adjective> <structure>'; "
                                 f"powers borrow the vocabulary of {aesthetic[1]} and {aesthetic[2]}.",
            "aesthetic": aesthetic,
            "factions": factions,
        }

    # -- pass 2 --
    def _region(self, ctx, seed):
        rng = _rng("region", seed)
        nouns = _BIOME_NOUNS.get(ctx.get("biome", "archive"), _NOUN)
        name = f"The {rng.choice(_ADJ)} {rng.choice(nouns)}"
        return {"name": name,
                "flavor": f"Grown from your note '{_title(ctx.get('title'))}'. "
                          f"{rng.choice(['Lamplight', 'Damp', 'Static', 'Old ink'])} "
                          f"clings to every surface here."}

    def _boss(self, ctx, seed):
        rng = _rng("boss", seed)
        proper = _title(ctx.get("title"))
        return {
            "name": f"{proper}, {rng.choice(_EPITHET)}",
            "title": f"Warden of the {rng.choice(_BIOME_NOUNS.get(ctx.get('biome','archive'), _NOUN))}",
            "flavor": f"The most-linked thought in the vault, made flesh; "
                      f"{ctx.get('backlinks', 0)} roads lead to it and none lead away.",
        }

    def _enemy(self, ctx, seed):
        rng = _rng("enemy", seed)
        arch = ctx.get("archetype", "shade")
        name = f"{rng.choice(_ADJ)} {arch.capitalize()}"
        if rng.random() < 0.5:
            name += f" of the {rng.choice(_NOUN)}"
        return {"name": name,
                "flavor": f"A {arch} that drifted out of '{_title(ctx.get('title'))}', "
                          f"dealing {ctx.get('damageType','decay')} to the unwary."}

    def _item(self, ctx, seed):
        rng = _rng("item", seed)
        name = rng.choice([f"The {rng.choice(_ADJ)} {rng.choice(_NOUN)}",
                           f"{rng.choice(_NOUN)} of {rng.choice(_EPITHET)}"])
        return {"name": name,
                "flavor": f"A {ctx.get('rarity','common')} {ctx.get('slot','relic')} "
                          f"salvaged from '{_title(ctx.get('title'))}'."}

    def _secret(self, ctx, seed):
        rng = _rng("secret", seed)
        return {"flavor": f"An orphaned note with no links in or out — "
                          f"'{_title(ctx.get('title'))}' — sealed away as a "
                          f"{rng.choice(['forgotten vault','lost reliquary','hidden cell'])}."}

    def _quest(self, ctx, seed):
        rng = _rng("quest", seed)
        verb = _QUEST_VERB.get(ctx.get("kind", "recover"), "Reclaim")
        return {"objective": f"{verb} the {rng.choice(_ADJ)} {rng.choice(_NOUN)} — "
                             f"an unfinished charge left in your own hand."}


# --------------------------------------------------------------------------- #
# Real-model drop-in (sketch). Uncomment and `pip install anthropic` to use.
# The pipeline is identical -- only this class changes.
# --------------------------------------------------------------------------- #
#
# import json, os
# from anthropic import Anthropic
#
# class AnthropicLLM:
#     def __init__(self, model="claude-opus-4-8"):
#         self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
#         self.model = model
#
#     def complete_json(self, system, user, schema, context=None):
#         # Force structured output with a single tool the model must call.
#         tool = {"name": "emit", "description": "Return the world element.",
#                 "input_schema": {k: v for k, v in schema.items() if not k.startswith("x-")}}
#         resp = self.client.messages.create(
#             model=self.model, max_tokens=1024, system=system,
#             tools=[tool], tool_choice={"type": "tool", "name": "emit"},
#             messages=[{"role": "user", "content": user}],
#         )
#         for block in resp.content:
#             if block.type == "tool_use":
#                 return block.input
#         raise RuntimeError("model did not emit structured output")
