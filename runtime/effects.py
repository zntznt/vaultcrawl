"""Effects — Yume Nikki's heart, ported to a vault.

Not weapons: WAYS OF BEING. In Yume Nikki you collect effects (become a cat, hold a
lamp, ride a bike) that change how you move, what you perceive, and how the world meets
you — never how hard you hit. Here each effect is one of YOUR NOTES, found as a solitary
landmark out in the wild and taken into yourself. You wear one at a time and it changes
how you explore, not whether you win.

Effects are exploration/perception powers only. They touch movement, sight, and the mood
of creatures — never hp/atk/def (the anti-power-creep line holds, now for a gentler reason:
this is a dream of your notes, not a fight through them).

Each effect is themed from the giving note but the ROSTER is fixed and small (YN has ~24;
a handful reads better than dozens). The note lends the effect its NAME and voice; the
mechanic is one of these archetypes:

  lantern    see far in the dark — perception radius widens; the veil thins
  drift      pass over water/hazard terrain unharmed — traversal opens
  hush       creatures grow calm and approach instead of fleeing/menacing
  eyeless    the map's fog lifts wholly while worn (you dream the whole place)
  small      slip through a gap: creatures ignore you utterly (unseen)
  echo       the world answers — nearby notes murmur their words as you pass

One effect worn at a time; switch freely; costs nothing; loses nothing. Wandering is
never punished. Deterministic: which archetype a note grants is a stable hash of its id.
"""
from __future__ import annotations

from .systems import System

# archetype -> (glyph-name, one-line feel). Order is the stable assignment ring.
EFFECTS = ["lantern", "drift", "hush", "eyeless", "small", "echo"]
FEEL = {
    "lantern": "You hold a light; the dark draws back and you see further.",
    "drift":   "You go weightless; water and hazard no longer bar your way.",
    "hush":    "A stillness settles on you; wild things lose their fear and drift near.",
    "eyeless": "You close your eyes and dream the whole place at once; no fog remains.",
    "small":   "You grow small and quiet; nothing notices you pass.",
    "echo":    "The world leans in; the notes you pass murmur themselves to you.",
}
# perception-radius bonus for lantern
LANTERN_RADIUS = 6


def effect_for(note_id: str) -> str:
    """Which effect a given note grants — stable per note id."""
    h = 0
    for ch in str(note_id):
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return EFFECTS[h % len(EFFECTS)]


class EffectSystem(System):
    """Holds the effects you have collected and the one currently worn. Other systems
    and the game query `worn()` to change how the world meets you."""
    name = "effects"

    def __init__(self):
        self.collected: dict = {}   # archetype -> giving note id (first found)
        self.worn: str | None = None
        self._echoed: set = set()   # notes the 'echo' effect has already murmured

    # ---- acquisition (called by game when you commune with a wild landmark) ----
    def acquire(self, game, note_id: str) -> str | None:
        eff = effect_for(note_id)
        if eff in self.collected:
            return None
        self.collected[eff] = note_id
        if self.worn is None:
            self.worn = eff
        title = game.m.get("graph", {}).get("nodes", {}).get(note_id, {}).get(
            "title", note_id)
        game.log(f"You take the {eff} into yourself, out of '{title}'.")
        game.log(FEEL[eff])
        return eff

    def wear(self, eff: str | None):
        if eff is None or eff in self.collected:
            self.worn = eff

    # ---- the powers (queried by game/senses/brains) ----
    def worn_is(self, eff: str) -> bool:
        return self.worn == eff

    def perception_bonus(self, game) -> int:
        return LANTERN_RADIUS if self.worn == "lantern" else 0

    def all_seen(self, game) -> bool:
        return self.worn == "eyeless"

    def can_drift(self, game) -> bool:
        return self.worn == "drift"

    def unseen(self, game) -> bool:
        return self.worn == "small"

    def calms(self, game) -> bool:
        return self.worn == "hush"

    # ---- echo: the world murmurs as you pass ----
    def on_player_act(self, game):
        if self.worn != "echo":
            return
        idx = game.room_at(game.player.x, game.player.y)
        nid = game.room_notes.get(idx) if idx is not None else None
        if not nid or nid in self._echoed:
            return
        self._echoed.add(nid)
        line = game._weave_note(nid, salt="echo") if hasattr(game, "_weave_note") else ""
        if line:
            game.log(f'It murmurs: "{line}"')

    def status_line(self, game):
        if not self.collected:
            return None
        w = self.worn or "none"
        return f"Effect: {w}  ({len(self.collected)}/{len(EFFECTS)})"
