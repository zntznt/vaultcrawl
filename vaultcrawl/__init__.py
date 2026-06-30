"""Vaultcrawl: generate a roguelike world from a folder of markdown notes.

Pipeline (see bake.py):
    ingest  -> parse markdown into Notes + a link graph
    analyze -> deterministic graph metrics (PageRank, communities, bridges, orphans)
    mapping -> bind graph entities to mechanical slots (regions/enemies/bosses/...)
    generate-> two-pass LLM fills the *semantic* layer (bible, names, flavor)
    validate-> enforce schema + game invariants, clamp, pad sparse vaults
    bake    -> write the fixed world.json manifest

Everything except `generate` is deterministic. `generate`'s only non-deterministic
part is the LLM, which runs offline at bake time and is baked into the manifest, so
the runtime never calls a model. The default LLM is a deterministic offline stub.
"""

__version__ = "0.1.0"
