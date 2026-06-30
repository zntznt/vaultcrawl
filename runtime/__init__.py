"""A small, engine-agnostic reference runtime that renders a baked world.json into a
playable traditional roguelike.

The manifest is a *content palette*, not a map: every floor's layout is generated fresh
and procedurally (rooms + a minimum-spanning-tree of corridors => a guaranteed path from
entrance to stairs), while WHICH enemies/items/boss appear -- and at what depth -- comes
from the manifest. Pure stdlib; no dependencies.

    python -m runtime.play world.json --auto --floors 3     # headless demo
    python -m runtime.play world.json                       # interactive (needs a TTY)
"""
