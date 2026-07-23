"""WhisperBrain — wins through communion, negotiation, and quiet exploration."""
from __future__ import annotations

from collections import deque

from runtime.sense import (
    Brain, register_brain,
    step_toward, step_toward_safe, step_toward_avoiding_elites, step_away, attack_dir, is_dangerous,
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


def _nearest_safe_unseen(game, actor, floor, radius):
    know = game.system("knowledge")
    if know is None:
        return None
    seen = know.seen.get(floor, set())
    start = (actor.x, actor.y)
    visited = {start}
    queue = deque([start])
    while queue:
        cx, cy = queue.popleft()
        if (cx, cy) not in seen and not is_dangerous(game, cx, cy) and (cx, cy) != start:
            return (cx, cy)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in visited:
                continue
            if max(abs(nx - actor.x), abs(ny - actor.y)) > radius:
                continue
            if not game.level.walkable(nx, ny) or is_dangerous(game, nx, ny):
                continue
            visited.add((nx, ny))
            queue.append((nx, ny))
    return None


class WhisperBrain(Brain):
    name = "whisper"

    def decide(self, game, actor):
        s = agent_state(game, actor)

        # ---- UNIVERSAL PRIORITY 1: Panic flee when critically low ----
        hp_pct = s["vitals"]["hp_pct"]
        if hp_pct < 25:
            if s["near_hostiles"]:
                for i, sig in enumerate(s["sigils"]):
                    if sig.get("ability") == "Phase" or sig.get("base") == "Phase":
                        return AgentAction("cast", index=i)
            if s["position"]["on_stairs"]:
                return AgentAction("descend")
            st = _stairs(game)
            if st:
                step = step_toward_avoiding_elites(game, actor, st[0], st[1])
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
                step = step_toward_avoiding_elites(game, actor, st[0], st[1])
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
                step = step_toward_avoiding_elites(game, actor, st[0], st[1])
                return AgentAction("move", dx=step[0], dy=step[1])

        # ---- UNIVERSAL PRIORITY 3: Rest only when effective ----
        if (not s["adjacent_hostiles"] and not s["near_hostiles"] and
            hp_pct < 70 and s["rest_effective"]):
            return AgentAction("rest")

        # ---- UNIVERSAL PRIORITY 3b: Rest anyway in weather ----
        if (not s["adjacent_hostiles"] and not s["near_hostiles"] and
            hp_pct < 50 and not s["rest_effective"] and s["weather_hazard"]):
            return AgentAction("rest")

        # ---- WHISPER PERSONALITY ----
        # 1) Win through communion
        if s["knowledge"]["truths_read"] >= 3 and s["nav"]["any_boss_near"]:
            for h in s["adjacent_hostiles"]:
                if h["is_boss"]:
                    return AgentAction("commune")
        if s["matter"]["total"] >= 8 and s["nav"]["any_boss_near"]:
            for h in s["adjacent_hostiles"]:
                if h["is_boss"]:
                    return AgentAction("commune")

        # 2) Wear small effect if collected but not worn
        if "small" in s["effects"]["collected"] and s["effects"]["worn_effect"] != "small":
            game.system("effects").wear("small")
            return AgentAction("wait")

        # 3) Parley with elite/boss within 6 tiles
        if "parley" in s["encounter_options"]:
            elite = None
            elite_dist = 7
            for h in s["hostiles"]:
                if h.get("tier", 0) >= 3 or h.get("is_boss"):
                    if h["dist"] < elite_dist:
                        elite = h
                        elite_dist = h["dist"]
            if elite is not None:
                return AgentAction("negotiate", target=elite["name"])

        # 4) Negotiate with non-boss adjacent hostiles
        for h in s["adjacent_hostiles"]:
            if not h["is_boss"]:
                return AgentAction("negotiate", target=h["name"])

        # 5) Becalm if can and adjacent hostile has known source
        if s["can_becalm"] and s["adjacent_hostiles"] and s["knowledge"]["learned_notes"] > 0:
            for h in s["adjacent_hostiles"]:
                if h.get("source"):
                    return AgentAction("becalm")

        # 6) Cast Phase if near hostiles
        if s["near_hostiles"]:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Phase" or sig.get("base") == "Phase":
                    return AgentAction("cast", index=i)

        # 7) Rest on town tiles
        if s["position"]["on_town"] and s["vitals"]["hp"] < s["vitals"]["max_hp"]:
            return AgentAction("rest")

        # 8) Interact with landmarks
        if game.commune_landmark() is not None:
            return AgentAction("interact")

        # 9) Cast Recall
        if s["can_heal_meaningfully"] and hp_pct < 70:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Recall" or sig.get("base") == "Recall":
                    return AgentAction("cast", index=i)

        # 10) Descend or walk to stairs
        if s["position"]["on_stairs"]:
            return AgentAction("descend")
        st = _stairs(game)
        if st is not None:
            step = step_toward_avoiding_elites(game, actor, st[0], st[1])
            if step != WAIT:
                return AgentAction("move", dx=step[0], dy=step[1])

        # 11) Explore safe unseen tiles
        unseen = _nearest_safe_unseen(game, actor, s["position"]["floor"], 10)
        if unseen is not None:
            step = step_toward_safe(game, actor, unseen[0], unseen[1])
            return AgentAction("move", dx=step[0], dy=step[1])

        # 12) Collect safe POIs
        safe_pois = []
        for p in s["pois"]:
            try:
                px_val, py_val = (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])
            except (TypeError, ValueError, KeyError, IndexError):
                continue
            if not is_dangerous(game, px_val, py_val):
                safe_pois.append(p)
        if safe_pois:
            poi_xy = _nearest_xy(actor, safe_pois)
            if poi_xy is not None:
                step = step_toward(game, actor, poi_xy[0], poi_xy[1], safe=True)
                if step != WAIT:
                    return AgentAction("move", dx=step[0], dy=step[1])

        # 13) Wait
        return AgentAction("wait")


register_brain("whisper", WhisperBrain)
