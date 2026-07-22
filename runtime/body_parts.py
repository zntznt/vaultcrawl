"""Body-part injury model — hit locations for every actor.

Three parts (head/torso/legs) with independent HP. Hits land by weighted
random (remaining HP = larger target). Elite enemies target weak spots.
Healing pours into the worst injury first. Legs at 0 HP = immobilized
(speed 0, can still act). Head or torso at 0 = death.

Self-contained System: initialises bodies on floor enter, ticks status
effects, provides status_line. Deterministic (seeded per-action RNG).
"""
from __future__ import annotations

from runtime.systems import System

_PART_NAMES = {"head": "head", "torso": "torso", "legs": "legs"}
_DIST = {"head": 1, "torso": 2, "legs": 1}  # HP fractions of 4
_SLOW_MULT = 0.5


def init_body(actor):
    """Assign body-part HP from the actor's max_hp. Idempotent — does not
    re-init if actor.body already exists with valid parts."""
    if getattr(actor, "body", None):
        return
    hp = max(3, actor.max_hp)
    h = max(1, hp * _DIST["head"] // 4)
    t = max(1, hp * _DIST["torso"] // 4)
    l = max(1, hp - h - t)
    actor.body = {
        "head":  {"hp": h, "max": h},
        "torso": {"hp": t, "max": t},
        "legs":  {"hp": l, "max": l},
    }
    sync_hp(actor)


def sync_hp(actor):
    """Keep actor.hp = sum of part HPs. Also restore speed if legs healed."""
    if not getattr(actor, "body", None):
        return
    actor.hp = sum(p["hp"] for p in actor.body.values())
    actor.max_hp = sum(p["max"] for p in actor.body.values())
    if actor.body["legs"]["hp"] > 0 and getattr(actor, "speed", 1.0) == 0:
        actor.speed = getattr(actor, "_base_speed", 1.0)


def hit_part(actor, rng, elite_aim=False):
    """Choose which part a hit lands on. Weighted by remaining HP.
    Falls back to "torso" if actor has no body parts."""
    body = getattr(actor, "body", None)
    if body is None:
        return "torso"
    alive = [p for p in ("head", "torso", "legs") if body[p]["hp"] > 0]
    if not alive:
        return "torso"
    if elite_aim and len(alive) > 1 and rng.random() < 0.5:
        return min(alive, key=lambda p: body[p]["hp"])
    weights = [body[p]["hp"] for p in alive]
    total = sum(weights)
    roll = rng.random() * total
    acc = 0
    for p, w in zip(alive, weights):
        acc += w
        if roll < acc:
            return p
    return alive[-1]


def damage_part(actor, part, dmg):
    """Apply damage to one body part. Syncs HP and handles leg break.
    Falls back to flat HP subtraction if actor has no body parts."""
    body = getattr(actor, "body", None)
    if body is None:
        actor.hp = max(0, actor.hp - dmg)
        return
    if part not in body:
        return
    body[part]["hp"] = max(0, body[part]["hp"] - dmg)
    if part == "legs" and body["legs"]["hp"] <= 0:
        if getattr(actor, "speed", 1.0) > 0:
            actor._base_speed = actor.speed
            actor.speed = 0
    sync_hp(actor)


def heal_body(actor, amount):
    """Distribute healing across parts, worst injury first.
    Falls back to flat HP heal if actor has no body parts."""
    body = getattr(actor, "body", None)
    if body is None:
        actor.hp = min(actor.max_hp, actor.hp + amount)
        return
    parts = sorted(["head", "torso", "legs"],
                   key=lambda p: body[p]["hp"] / max(1, body[p]["max"]))
    for p in parts:
        need = body[p]["max"] - body[p]["hp"]
        give = min(amount, need)
        body[p]["hp"] += give
        amount -= give
        if amount <= 0:
            break
    sync_hp(actor)


def is_immobilized(actor) -> bool:
    body = getattr(actor, "body", None)
    if body is None:
        return False
    return body.get("legs", {}).get("hp", 1) <= 0


class BodySystem(System):
    name = "body"

    def __init__(self):
        self._initialized: set[int] = set()

    def on_world_start(self, game):
        self._initialized = set()

    def on_floor_enter(self, game):
        init_body(game.player)
        for a in game.actors:
            init_body(a)

    def on_player_act(self, game):
        p = game.player
        slowed = getattr(p, "_slowed", 0)
        if slowed > 0:
            p._slowed -= 1
            if p._slowed <= 0 and getattr(p, "speed", 1.0) < 0.6:
                p.speed = getattr(p, "_base_speed", 1.0)

    def on_event(self, game, etype, data):
        if etype == "actor_died":
            a = (data or {}).get("actor")
            if a is not None:
                a._slowed = 0
                if getattr(a, "speed", 1.0) < 0.6:
                    a.speed = getattr(a, "_base_speed", 1.0)

    def status_line(self, game):
        p = game.player
        if not getattr(p, "body", None):
            return None
        injuries = []
        if p.body["legs"]["hp"] <= 0:
            injuries.append("legs broken")
        if getattr(p, "_bleeding", 0) > 0:
            injuries.append("bleeding")
        if getattr(p, "_slowed", 0) > 0 and p.body["legs"]["hp"] > 0:
            injuries.append("slowed")
        if getattr(p, "_staggered", 0) > 0:
            injuries.append("dazed")
        return "Injuries: " + ", ".join(injuries) if injuries else None
