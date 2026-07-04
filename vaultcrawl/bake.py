"""Pipeline entrypoint:  python -m vaultcrawl.bake <vault_dir> -o world.json

Wires ingest -> analyze -> mapping -> generate -> validate -> write. Everything but
generate is deterministic; generate's LLM output is baked here so the runtime never
needs a model.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .analyze import analyze
from .corpus import build_corpus
from .generate import generate_world
from .ingest import load_vault
from .mapping import build_blueprint
from .validate import pad_if_sparse, region_graph_warnings, validate


def bake(vault_path: str, out_path: str, llm=None):
    vault = load_vault(vault_path)
    an = analyze(vault)
    blueprint = build_blueprint(vault, an)
    manifest = generate_world(vault, an, blueprint, llm=llm)
    manifest["generatedFrom"]["vaultPath"] = os.path.abspath(vault_path)
    manifest["corpus"] = build_corpus(vault, an)

    manifest = pad_if_sparse(manifest)
    errs = validate(manifest)
    if errs:
        raise SystemExit("Validation FAILED:\n" + "\n".join("  - " + e for e in errs))
    warns = region_graph_warnings(manifest, blueprint.get("_bridges", []))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    return manifest, warns


def _print_summary(m: dict, out_path: str, warns: list):
    gf = m["generatedFrom"]
    print(f"\n  {m['bible']['worldName']}  (seed {m['seed']})")
    print(f"  tone: {m['bible']['tone']}")
    print(f"  from: {gf['noteCount']} notes, {gf['linkCount']} links, "
          f"{gf['communityCount']} clusters{'  [PADDED]' if gf['padded'] else ''}")
    print(f"  built: {len(m['regions'])} regions, {len(m['bosses'])} bosses, "
          f"{len(m['enemies'])} enemies, {len(m['items'])} items, "
          f"{len(m.get('secrets', []))} secrets, {len(m.get('quests', []))} quests")
    deepest = max(m["bosses"], key=lambda b: b["depth"])
    print(f"  final boss (floor {deepest['depth']}): {deepest['name']} — {deepest['title']}")
    print("\n  factions:")
    for f in m["bible"]["factions"]:
        rels = ", ".join(f"{r['stance']}->{r['factionId']}" for r in f["relations"]) or "isolated"
        print(f"    - {f['name']}  [{rels}]")
    print("\n  regions:")
    for r in m["regions"]:
        print(f"    - {r['name']}  ({r['biome']}, floors {r['depthBand'][0]}-{r['depthBand'][1]})")
    for w in warns:
        print(f"\n  ! {w}")
    print(f"\n  wrote {out_path}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bake a roguelike world from a markdown vault.")
    ap.add_argument("vault", help="path to a folder of .md notes")
    ap.add_argument("-o", "--out", default="world.json", help="output manifest path")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.vault):
        print(f"error: {args.vault} is not a directory", file=sys.stderr)
        return 2

    manifest, warns = bake(args.vault, args.out)
    if not args.quiet:
        _print_summary(manifest, args.out, warns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
