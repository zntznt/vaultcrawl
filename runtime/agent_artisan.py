"""ArtisanBrain — crafter and forager that breaks down worn sigils, forges new ones,
opens caches, collects salvage and POIs, shields in downtime, and descends when done.
"""
from __future__ import annotations

from runtime.sense import (
    Brain, register_brain,
    step_toward, step_toward_safe, step_away, attack_dir, is_dangerous,
    lure_step, hostiles, adjacent, points_of_interest,
)
from runtime.agent_action import AgentAction
from runtime.agent_perception import agent_state
from runtime.tactics import _stairs

WAIT = (0, 0)


def _nearest_xy(actor, tiles):
    best, bd = None, 10 ** 9
    for t in tiles:
        try:
            if isinstance(t, dict):
                x, y = t["x"], t["y"]
            else:
                x, y = t
        except (TypeError, ValueError, KeyError):
            continue
        d = max(abs(actor.x - x), abs(actor.y - y))
        if d < bd or (d == bd and best is not None and (x, y) < best):
            best, bd = (x, y), d
    return best


class ArtisanBrain(Brain):
    name = "artisan"

    def decide(self, game, actor):
        s = agent_state(game, actor)

        # ---- UNIVERSAL PRIORITY 1: Panic flee when critically low ----
        hp_pct = s["vitals"]["hp_pct"]
        if hp_pct < 25:
            if s["position"]["on_stairs"]:
                return AgentAction("descend")
            st = _stairs(game)
            if st:
                step = step_toward_safe(game, actor, st[0], st[1])
                return AgentAction("move", dx=step[0], dy=step[1])

        # ---- FACTION DE-ESCALATION: once 4+ kills, beeline stairs ----
        if game.kills >= 4:
            if s["can_becalm"] and s["adjacent_hostiles"]:
                return AgentAction("becalm")
            if s["position"]["on_stairs"]:
                return AgentAction("descend")
            if s["near_hostiles"]:
                t = s["near_hostiles"][0]
                away = step_away(game, actor, t["x"], t["y"], safe=True)
                if away != (0, 0):
                    return AgentAction("move", dx=away[0], dy=away[1])
            st = _stairs(game)
            if st:
                step = step_toward_safe(game, actor, st[0], st[1])
                return AgentAction("move", dx=step[0], dy=step[1])

        # ---- UNIVERSAL PRIORITY 2: Fight or flight when adjacent ----
        if s["adjacent_hostiles"]:
            t = s["adjacent_hostiles"][0]
            if hp_pct < 40:
                away = step_away(game, actor, t["x"], t["y"], safe=True)
                if away != (0, 0) and not s["has_trap_near"]:
                    return AgentAction("move", dx=away[0], dy=away[1])
            return AgentAction("move", dx=(t["x"] > actor.x) - (t["x"] < actor.x),
                                          dy=(t["y"] > actor.y) - (t["y"] < actor.y))

        # ---- UNIVERSAL PRIORITY 3: Rest only when effective ----
        if (not s["adjacent_hostiles"] and not s["near_hostiles"] and
            hp_pct < 70 and s["rest_effective"]):
            return AgentAction("rest")

        # ---- UNIVERSAL PRIORITY 3b: Rest anyway in weather ----
        if (not s["adjacent_hostiles"] and not s["near_hostiles"] and
            hp_pct < 50 and not s["rest_effective"] and s["weather_hazard"]):
            return AgentAction("rest")

        # ---- ARTISAN PERSONALITY ----
        # 1) Breakdown worn sigils at durability 1
        for sig in s["sigils"]:
            if sig.get("durability", 2) <= 1:
                return AgentAction("breakdown", target=sig["ability"])

        # 2) Forge when ready and there is a free slot
        if s["matter"]["forge_ready"] and s["nav"]["free_sigil_slots"] > 0:
            slotted = {sig.get("ability") for sig in s["sigils"]}
            for ability in ("Recall", "Ward", "Phase", "Echo", "Rally"):
                if ability not in slotted:
                    return AgentAction("forge", target=ability)

        # 3) Shield if defense < 3 and safe
        if s["vitals"]["defense"] < 3 and not s["adjacent_hostiles"] and not s["near_hostiles"]:
            return AgentAction("shield")

        # 4) Collect salvage from salvage.ground
        salvage_positions = []
        salvage_sys = game.system("salvage")
        if salvage_sys is not None:
            ground = getattr(salvage_sys, "ground", {})
            for (gx, gy) in ground:
                salvage_positions.append((gx, gy))
        if salvage_positions:
            nearest_salvage = _nearest_xy(actor, salvage_positions)
            if nearest_salvage is not None:
                step = step_toward(game, actor, nearest_salvage[0],
                                   nearest_salvage[1], safe=True)
                if step != WAIT:
                    return AgentAction("move", dx=step[0], dy=step[1])

        # 5) Open caches — walk toward nearest
        if s["caches"]:
            nearest_cache = _nearest_xy(actor, s["caches"])
            if nearest_cache is not None:
                dist = max(abs(actor.x - nearest_cache[0]),
                           abs(actor.y - nearest_cache[1]))
                if dist <= 1:
                    return AgentAction("move", dx=nearest_cache[0] - actor.x,
                                       dy=nearest_cache[1] - actor.y)
                step = step_toward(game, actor, nearest_cache[0],
                                   nearest_cache[1], safe=True)
                if step != WAIT:
                    return AgentAction("move", dx=step[0], dy=step[1])

        # 6) Interact with landmarks
        if game.commune_landmark() is not None:
            return AgentAction("interact")

        # 7) Collect POIs
        if s["pois"]:
            poi_xy = _nearest_xy(actor, s["pois"])
            if poi_xy is not None:
                step = step_toward(game, actor, poi_xy[0], poi_xy[1], safe=True)
                if step != WAIT:
                    return AgentAction("move", dx=step[0], dy=step[1])

        # 8) Cast Recall only when it would heal meaningfully
        if s["can_heal_meaningfully"] and hp_pct < 80:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Recall" or sig.get("base") == "Recall":
                    return AgentAction("cast", index=i)

        # 9) Descend or walk to stairs
        if s["position"]["on_stairs"]:
            return AgentAction("descend")
        st = _stairs(game)
        if st is not None:
            step = step_toward_safe(game, actor, st[0], st[1])
            if step != WAIT:
                return AgentAction("move", dx=step[0], dy=step[1])

        # 10) Wait
        return AgentAction("wait")


register_brain("artisan", ArtisanBrain)
