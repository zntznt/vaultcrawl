"""Deterministic seeding helpers.

Core invariant 4: seed RNG from SHA-256 of stable keys, never from `hash()`. Python
salts `hash()` on str and bytes per process (PYTHONHASHSEED), so `hash(f"{seed}:{turn}")`
gives different answers in different runs of the same code with the same game seed. That
is not a theoretical worry: it decided combat targets, locus placement, becalm outcomes
and lore reveals, and it made tests/test_becalm.py pass or fail depending on the hash
seed the interpreter happened to start with.

Use `droll(key, n)` where the old code said `hash(key) % n`, and `drng(key)` where it
built a Random from a hashed key.
"""
from __future__ import annotations

import hashlib
from random import Random


def dhash(key: str) -> int:
    """A stable non-negative int for a string key. Same answer in every process."""
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def droll(key: str, n: int) -> int:
    """Stable `hash(key) % n`. Returns 0 when n is not positive."""
    return dhash(key) % n if n > 0 else 0


def drng(key: str) -> Random:
    """A Random seeded stably from a string key."""
    return Random(dhash(key))
