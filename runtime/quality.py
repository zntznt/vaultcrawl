"""Quality grades — a Factorio-Space-Age axis layered onto everything.

Every creature and equippable *rolls* a quality tier:

    Normal (0) · Uncommon (1) · Rare (2) · Epic (3) · Legendary (4)

Upgrades are RARE and cascade (a success can bump again, with decaying odds). Quality is
not a separate class of unique items — any instance may be of any tier:

- **Equippables (sigils)** gain **one random perk per tier** (a stat bump or a passive).
- **Creatures** gain **stat bonuses per tier** *and* **one special action per tier**.
- **Crafting** (forge / fabricator) rolls the output's quality with the floor pinned to the
  LOWEST-quality ingredient and the odds raised by better inputs + **additives**; additives
  also steer *which* perk/effect you get.

`quality.py` is the hub. It is **opt-in**: only the `QualitySystem` (registered in the live
game) assigns quality. Without it, everything stays Normal and behaves exactly as before —
so the rest of the suite is untouched. The fleet fills the registries (perks, special
actions, additive affinities); built-in defaults keep this module working on its own.
"""
from __future__ import annotations

import random

from runtime.systems import System

NORMAL, UNCOMMON, RARE, EPIC, LEGENDARY = 0, 1, 2, 3, 4
NAMES = ["Normal", "Uncommon", "Rare", "Epic", "Legendary"]
MARK = ["", "+", "*", "★", "✦"]   # terse tier marker for names/HUD

_BASE = 0.09       # per-roll chance to bump a tier (quality is rare)
_CASCADE = 0.45    # a successful bump's chance decays by this factor (Factorio-style)


def name(tier: int) -> str:
    return NAMES[max(0, min(LEGENDARY, int(tier)))]


def mark(tier: int) -> str:
    return MARK[max(0, min(LEGENDARY, int(tier)))]


def roll(rng: random.Random, floor: int = 0, bias: float = 0.0) -> int:
    """Roll a quality tier >= floor. `bias` (>=0) raises the upgrade odds (good inputs /
    additives). Cascades: each success may bump again at decaying probability."""
    tier = max(0, min(LEGENDARY, int(floor)))
    p = min(0.95, _BASE + max(0.0, bias))
    while tier < LEGENDARY and rng.random() < p:
        tier += 1
        p *= _CASCADE
    return tier


# --------------------------------------------------------------------------- #
# Creature stat scaling
# --------------------------------------------------------------------------- #

def scale_creature(actor, tier: int):
    """Apply per-tier stat bonuses to a creature (rare, so this is a real spike)."""
    if tier <= 0:
        return
    actor.max_hp = int(actor.max_hp * (1.0 + 0.5 * tier))
    actor.hp = actor.max_hp
    actor.atk += tier
    actor.defense = getattr(actor, "defense", 0) + tier // 2
    base = getattr(actor, "name", "creature")
    if NAMES[tier] not in base:
        # note-titled names read "the Seraph of 'X'": the tier slots INSIDE the
        # article ("the Rare Seraph of 'X'"), not awkwardly in front of it
        if base.startswith("the "):
            actor.name = f"the {NAMES[tier]} {base[4:]}"
        else:
            actor.name = f"{NAMES[tier]} {base}"


# --------------------------------------------------------------------------- #
# Registries (the fleet fills these; built-in defaults keep us self-sufficient)
# --------------------------------------------------------------------------- #

# special creature actions: name -> fn(game, actor) -> bool (True if it did something)
SPECIAL_ACTIONS: dict = {}
# perks for equippables: name -> {"kind": "stat"|"passive", "apply": fn(sigil)|None}
PERKS: dict = {}
# additive material -> perk name it favours at crafting
ADDITIVE_AFFINITY: dict = {}


def register_action(name, fn):
    SPECIAL_ACTIONS[name] = fn


def register_perk(name, kind="passive", apply=None):
    PERKS[name] = {"kind": kind, "apply": apply}


def register_additive(material, perk_name):
    ADDITIVE_AFFINITY[material] = perk_name


# ---- built-in defaults (so quality.py works before the fleet enriches it) ----

def _act_mend(game, actor):
    if actor.hp < actor.max_hp:
        actor.hp = min(actor.max_hp, actor.hp + 2)
        return True
    return False


def _act_lunge(game, actor):
    # dash one tile toward the player if there's a clear gap
    p = game.player
    if not getattr(game, "alive", True):
        return False
    dx = (p.x > actor.x) - (p.x < actor.x)
    dy = (p.y > actor.y) - (p.y < actor.y)
    nx, ny = actor.x + dx, actor.y + dy
    if (nx, ny) != (p.x, p.y) and game.level.walkable(nx, ny) and game.actor_at(nx, ny) is None:
        actor.x, actor.y = nx, ny
        return True
    return False


register_action("mend", _act_mend)
register_action("lunge", _act_lunge)
# Perks (reinforced, keen, ...) are registered by the sigils module, which every
# entrypoint loads; this registry just provides register_perk for it to call.


# --------------------------------------------------------------------------- #
# The QualitySystem — the authority that assigns + drives quality
# --------------------------------------------------------------------------- #

class QualitySystem(System):
    name = "quality"

    def __init__(self):
        self.rng = random.Random(0)
        self._action_cadence = 4   # a quality creature uses a special action ~every N turns

    # -- lifecycle --
    def on_floor_enter(self, game):
        self.rng = random.Random(f"{game.seed}:quality:{game.floor}")
        for a in list(game.actors):
            self._qualify_actor(game, a)

    def on_world_start(self, game):
        self.rng = random.Random(f"{game.seed}:quality:0")

    def on_player_act(self, game):
        if not getattr(game, "alive", True):
            return
        turn = getattr(game, "turn", 0)
        if turn % self._action_cadence != 0:
            return
        for a in list(game.actors):
            if a not in game.actors or not getattr(a, "alive", False):
                continue
            acts = getattr(a, "_special_actions", None)
            if not acts:
                continue
            # only act with a foe in sight-ish range, to keep it purposeful
            if max(abs(a.x - game.player.x), abs(a.y - game.player.y)) > 7:
                continue
            nm = acts[turn // self._action_cadence % len(acts)]
            fn = SPECIAL_ACTIONS.get(nm)
            if fn:
                try:
                    fn(game, a)
                except Exception:
                    pass

    # -- creatures --
    def _qualify_actor(self, game, actor):
        al = getattr(actor, "allegiance", "monster")
        if al in ("player", "npc"):
            return
        if getattr(actor, "_qualified", False):
            return
        actor._qualified = True
        r = random.Random(f"{game.seed}:{game.floor}:{actor.x}:{actor.y}:{getattr(actor,'source','')}")
        tier = roll(r, 0, 0.0)
        actor.quality = tier
        if tier <= 0:
            actor._special_actions = []
            return
        scale_creature(actor, tier)
        pool = list(SPECIAL_ACTIONS.keys())
        actor._special_actions = [pool[(r.randint(0, 10_000) + i) % len(pool)]
                                  for i in range(tier)] if pool else []
        if tier >= LEGENDARY:
            self._enlegend(game, actor, r)
        # only NAMED beings announce themselves (a note made flesh, or a Rare+ beast);
        # 261 anonymous critters each logging a stir buried the wake in noise
        if getattr(actor, "allegiance", "") != "monster" and tier < RARE:
            return
        if actor.name.startswith("the "):
            game.log(f"{actor.name} stirs.")   # log() capitalizes: "The Seraph of 'X' stirs."
        else:
            art = "An" if actor.name[:1].upper() in "AEIOU" else "A"
            game.log(f"{art} {actor.name} stirs.")

    def _enlegend(self, game, actor, r):
        """A Legendary spawn is a PERSON: it takes a name woven from its own note's
        words, negotiation comes easier to it, it holds no grudge -- and its fall
        leaves a named relic of legendary matter."""
        actor._legend = True
        try:
            from .marginalia import weave
            node = game.m.get("graph", {}).get("nodes", {}).get(actor.source, {})
            comm = (game.m.get("corpus") or {}).get(str(node.get("community", -1)))
            words = weave(comm, actor.source, r, max_words=3) if comm else ""
            nick = " ".join(w.strip('.!?,;:"').title()
                            for w in words.split(" ")[:2] if w.strip('.!?,;:"'))
        except Exception:
            nick = ""
        if nick:
            actor.name = f'{actor.name} "{nick}"'

    def on_event(self, game, etype, data):
        # a fallen legend leaves its named relic: legendary matter to salvage
        if etype != "actor_died":
            return
        actor = (data or {}).get("actor")
        if actor is None or not getattr(actor, "_legend", False):
            return
        game.log(f"{actor.name} falls; its relic remains where it stood.")
        game.emit("broke", kind="relic", source=getattr(actor, "source", ""),
                  name=actor.name, tier=LEGENDARY,
                  pos=(data or {}).get("pos", (actor.x, actor.y)))

    # -- equippables (called by sigils.py / forge.py) --
    def qualify_sigil(self, game, sigil, floor=0, bias=0.0, additives=None):
        """Roll a sigil's quality and grant one perk per tier. `floor`/`bias` come from
        crafting (input quality + additives); `additives` (list of materials) steer perks."""
        r = random.Random(f"{game.seed}:{game.floor}:{sigil.get('note','')}:{sigil.get('ability','')}")
        tier = roll(r, floor, bias)
        sigil["quality"] = tier
        perks = list(sigil.get("perks", []))
        favoured = [ADDITIVE_AFFINITY[m] for m in (additives or []) if m in ADDITIVE_AFFINITY]
        pool = list(PERKS.keys())
        for i in range(tier):
            choice = None
            if favoured:
                choice = favoured[i % len(favoured)]      # additives bias which perk
            if choice not in PERKS:
                choice = pool[(r.randint(0, 10_000) + i) % len(pool)] if pool else None
            if not choice:
                break
            perks.append(choice)
            ap = PERKS.get(choice, {}).get("apply")
            if ap:
                try:
                    ap(sigil)
                except Exception:
                    pass
        sigil["perks"] = perks
        if tier > 0:
            sigil["ability"] = f"{NAMES[tier]} {sigil.get('ability','sigil')}" \
                if not str(sigil.get("ability", "")).startswith(NAMES[tier]) else sigil["ability"]
        return tier

    def status_line(self, game):
        elites = sum(1 for a in game.actors if getattr(a, "quality", 0) > 0)
        return f"Elites: {elites}" if elites else None


def quality_of(thing) -> int:
    if isinstance(thing, dict):
        return int(thing.get("quality", 0))
    return int(getattr(thing, "quality", 0))
