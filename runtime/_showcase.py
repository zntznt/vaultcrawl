"""Shared print helpers for the runtime/*_scenario.py showcase scripts.

These three functions + the OK/NO marks were byte-identical across every
scenario file; they live here so a tweak to the verdict format touches one
place. Each scenario still owns its own main() — the runner loops, intro
text, and per-file reporting (MISMATCHES/ACCESS tables) genuinely differ.
"""
from __future__ import annotations

OK, NO = "✓", "✗"   # checkmark / cross


def header(n, title):
    print("\n" + "=" * 74)
    print(f"SET-PIECE {n}: {title}")
    print("-" * 74)


def show_logs(game, start, indent="   | "):
    for m in game.messages[start:]:
        print(indent + str(m))


def verdict(ok, text):
    print(f"   {OK if ok else NO} {text}")
    return bool(ok)
