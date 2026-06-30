"""Creature sense-profiles for vaultcrawl's perception layer.

Importing this module registers the supernatural / non-visual ``SenseProfile``s that
``runtime.senses.profile_name_for`` points at by monster glyph.  Until a profile name is
registered, that policy silently falls back to the plain ``"sighted"`` archetype -- so the
live game (``play.py``) and any showcase must ``import runtime.creatures`` exactly once for
these niches to come alive.

Each creature perceives by *capacity*, not omniscience (see SENSES_SPEC.md):

- ``echolocator`` (glyph ``e`` -- the echo): blind.  Hears a very long way (SOUND) but has
  no SIGHT at all, so it can only *locate* prey by noise and must close to TOUCH to confirm
  what it is.  The textbook detect-then-investigate creature.
- ``scent_hound`` (glyph ``b`` -- the beast, and ALL wildlife): a strong nose and good ears,
  weak eyes.  Follows SMELL/SOUND leads, then identifies by a short SIGHT or by TOUCH.
- ``life_wraith`` (glyph ``h`` -- the shade): no ordinary sight; it feels the LIFE of the
  living straight through walls.  Blind to the unliving -- golems/constructs emit no life.
- ``mind_seer`` (glyph ``s`` -- the scribe): feels thought (MIND) at range, with modest eyes.
  Blind to the mindless (swarm, constructs, grazers) even point-blank, unless it can manage
  a plain look (SIGHT+LOS) or a touch.

Ranges are deliberately modest and tuned so the *kind* of sense, not raw reach, decides what
each creature can know.
"""
from __future__ import annotations

from .senses import (
    SIGHT, SOUND, SMELL, TOUCH, LIFE, MIND,
    SenseProfile, register_profile,
)

# Blind echo: hears far, no eyes, confirms identity only by bumping into something.
register_profile("echolocator", SenseProfile({SOUND: 16, TOUCH: 1}))

# Beast / wildlife: nose first, ears second, a sliver of sight, touch when adjacent.
register_profile("scent_hound", SenseProfile({SMELL: 10, SOUND: 8, SIGHT: 4, TOUCH: 1}))

# Shade: senses the living through walls; some hearing; no ordinary sight.
register_profile("life_wraith", SenseProfile({LIFE: 10, SOUND: 6, TOUCH: 1}))

# Scribe: feels thought at range; modest eyes; touch when adjacent.
register_profile("mind_seer", SenseProfile({MIND: 10, SIGHT: 5, TOUCH: 1}))
