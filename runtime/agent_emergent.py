"""EmergentBrain — adaptive fighter that exploits hazards, shields up, and descends when clear."""
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


class EmergentBrain(Brain):
    name = "emergent"

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

        if game.kills >= 4:
            if s["can_becalm"] and s["adjacent_hostiles"]:
                return AgentAction("becalm")
            if s["position"]["on_stairs"]:
                return AgentAction("descend")
            # Flee any nearby hostile, not toward them
            if s["near_hostiles"]:
                t = s["near_hostiles"][0]
                away = step_away(game, actor, t["x"], t["y"], safe=True)
                if away != (0, 0):
                    return AgentAction("move", dx=away[0], dy=away[1])
            st = _stairs(game)
            if st:
                step = step_toward_safe(game, actor, st[0], st[1])
                return AgentAction("move", dx=step[0], dy=step[1])

        # ---- UNIVERSAL PRIORITY 3: Rest only when effective ----
        if (not s["adjacent_hostiles"] and not s["near_hostiles"] and
            hp_pct < 70 and s["rest_effective"]):
            return AgentAction("rest")

        # ---- UNIVERSAL PRIORITY 3b: Rest anyway in weather ----
        if (not s["adjacent_hostiles"] and not s["near_hostiles"] and
            hp_pct < 50 and not s["rest_effective"] and s["weather_hazard"]):
            return AgentAction("rest")

        # ---- EMERGENT PERSONALITY ----
        # 1) Cast Phase if 3+ adjacent hostiles
        if len(s["adjacent_hostiles"]) >= 3:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Phase" or sig.get("base") == "Phase":
                    return AgentAction("cast", index=i)

        # 2) Cast Ward if 2+ adjacent hostiles
        if len(s["adjacent_hostiles"]) >= 2:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Ward" or sig.get("base") == "Ward":
                    return AgentAction("cast", index=i)

        # 3) Shield to cap
        if s["vitals"]["defense"] < 3 and not s["adjacent_hostiles"] and not s["near_hostiles"]:
            return AgentAction("shield")

        # 4) Shove adjacent hostiles onto hazards
        for h in s["adjacent_hostiles"]:
            behind_x = h["x"] + (h["x"] - actor.x)
            behind_y = h["y"] + (h["y"] - actor.y)
            if is_dangerous(game, behind_x, behind_y):
                return AgentAction("shove", dx=h["x"] - actor.x, dy=h["y"] - actor.y)

        # 5) Target weak body parts of adjacent hostiles
        for h in s["adjacent_hostiles"]:
            for part_info in h.get("body", {}).values():
                if part_info.get("hp", 0) <= 1:
                    return AgentAction("move", dx=(h["x"] > actor.x) - (h["x"] < actor.x),
                                      dy=(h["y"] > actor.y) - (h["y"] < actor.y))

        # 6) Chase nearest hostile
        if s["hostiles"]:
            t = s["hostiles"][0]
            step = step_toward(game, actor, t["x"], t["y"], safe=True)
            if step != WAIT:
                return AgentAction("move", dx=step[0], dy=step[1])

        # 7) Cast Recall when no near hostiles
        if s["can_heal_meaningfully"] and hp_pct < 60 and not s["near_hostiles"]:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Recall" or sig.get("base") == "Recall":
                    return AgentAction("cast", index=i)

        # 8) Shield again if still under cap
        if s["vitals"]["defense"] < 3 and not s["adjacent_hostiles"] and not s["near_hostiles"]:
            return AgentAction("shield")

        # 9) Descend when floor cleared
        if not s["hostiles"] and not s["pois"]:
            if s["position"]["on_stairs"]:
                return AgentAction("descend")
            st = _stairs(game)
            if st is not None:
                step = step_toward_safe(game, actor, st[0], st[1])
                if step != WAIT:
                    return AgentAction("move", dx=step[0], dy=step[1])

        # 10) Collect POIs
        if s["pois"]:
            poi_xy = _nearest_xy(actor, s["pois"])
            if poi_xy is not None:
                step = step_toward(game, actor, poi_xy[0], poi_xy[1], safe=True)
                if step != WAIT:
                    return AgentAction("move", dx=step[0], dy=step[1])

        # 11) Walk to stairs
        st = _stairs(game)
        if st is not None:
            step = step_toward_safe(game, actor, st[0], st[1])
            if step != WAIT:
                return AgentAction("move", dx=step[0], dy=step[1])

        # 12) Wait
        return AgentAction("wait")


register_brain("emergent", EmergentBrain)
