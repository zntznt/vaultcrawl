"""Universal agent brain — Berlin Convention compliant.
Every agent can do everything. Starting state determines which branches
are reachable on turn 1. Behavioral divergence compounds from there."""
from __future__ import annotations

from runtime.sense import (
    Brain, register_brain,
    step_toward, step_toward_safe, step_toward_avoiding_elites,
    step_away, attack_dir, is_dangerous, hostiles, adjacent,
)
from runtime.agent_action import AgentAction
from runtime.agent_perception import agent_state
from runtime.tactics import _stairs


class UniversalBrain(Brain):
    """One decision tree for all agents. Personality emerges from starting state,
    not from different code paths."""

    def __init__(self, name: str = "seeker"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def decide(self, game, actor):
        s = agent_state(game, actor)
        hp_pct = s["vitals"]["hp_pct"]
        st = _stairs(game)

        # ---- 1. PANIC: survival trumps all ----
        if hp_pct < 25:
            if s["near_hostiles"]:
                for i, sig in enumerate(s["sigils"]):
                    if sig.get("ability") == "Phase" or sig.get("base") == "Phase":
                        return AgentAction("cast", index=i)
            if s["position"]["on_stairs"]:
                return AgentAction("descend")
            if st:
                step = step_toward_avoiding_elites(game, actor, st[0], st[1])
                return AgentAction("move", dx=step[0], dy=step[1])

        # ---- 2. COMMUNE: alternate win condition ----
        can_commune = s["knowledge"]["truths_read"] >= 2 or s["matter"]["total"] >= 4
        if can_commune and s["nav"]["any_boss_near"]:
            return AgentAction("commune")

        # ---- 3. HEAL: cast Recall when damaged ----
        if hp_pct < 50 and s["can_heal_meaningfully"] and s["vitals"]["hp"] < s["vitals"]["max_hp"]:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Recall" or sig.get("base") == "Recall":
                    return AgentAction("cast", index=i)

        # ---- 4. PARLEY: talk to elites before fighting ----
        if s.get("encounter_options"):
            opts = s["encounter_options"]
            for prefer in ("parley", "coerce", "appease", "flee"):
                if prefer in opts and prefer == "parley" and s["hostiles"]:
                    for h in s["hostiles"]:
                        if h.get("tier", 1) >= 3 or h.get("is_boss"):
                            return AgentAction("negotiate", target=h["name"])
                if prefer == "coerce" and s["matter"]["total"] >= 1:
                    return AgentAction("talk")
            if "flee" in opts and s["matter"]["total"] >= 1:
                return AgentAction("talk")

        # ---- 5. BECALM: pacify adjacent hostiles ----
        if s["adjacent_hostiles"] and s["matter"]["total"] >= 2 and s["can_becalm"]:
            return AgentAction("becalm")

        # ---- 6. FORGE: craft sigils ----
        if s["matter"]["total"] >= 2 and s["nav"]["free_sigil_slots"] > 0:
            slotted = {sig.get("ability") for sig in s["sigils"]}
            for ability in ("Recall", "Ward", "Phase", "Echo", "Rally"):
                if ability not in slotted:
                    return AgentAction("forge", target=ability)

        # ---- 7. BREAKDOWN: recover matter from worn sigils ----
        for sig in s["sigils"]:
            if sig.get("durability", 2) <= 1:
                return AgentAction("breakdown", target=sig["ability"])

        # ---- 8. SHIELD: build defense ----
        if s["vitals"]["defense"] < 3 and not s["adjacent_hostiles"]:
            return AgentAction("shield")

        # ---- 9. FLEE: escape adjacent threats ----
        if s["adjacent_hostiles"] and hp_pct < 40:
            t = s["adjacent_hostiles"][0]
            away = step_away(game, actor, t["x"], t["y"], safe=True)
            if away != (0, 0) and not s["has_trap_near"]:
                return AgentAction("move", dx=away[0], dy=away[1])

        # ---- 10. EXPLORE: unseen tiles, POIs, caches, salvage ----
        # Unseen tiles
        know = game.system("knowledge")
        if know:
            seen = know.seen.get(game.floor, set())
            px, py = actor.x, actor.y
            best, bd = None, 999
            for y in range(max(0, py - 20), min(game.level.h, py + 21)):
                for x in range(max(0, px - 20), min(game.level.w, px + 21)):
                    if game.level.walkable(x, y) and (x, y) not in seen:
                        d = max(abs(x - px), abs(y - py))
                        if d < bd:
                            best, bd = (x, y), d
            if best is not None:
                step = step_toward(game, actor, best[0], best[1], safe=True)
                if step != (0, 0):
                    return AgentAction("move", dx=step[0], dy=step[1])
        # Landmarks
        if game.commune_landmark() is not None:
            return AgentAction("interact")
        # Salvage
        salvage_sys = game.system("salvage")
        if salvage_sys:
            ground = getattr(salvage_sys, "ground", {})
            if ground:
                nearest = min(ground.keys(), key=lambda p: abs(p[0]-actor.x) + abs(p[1]-actor.y))
                step = step_toward(game, actor, nearest[0], nearest[1], safe=True)
                if step != (0, 0):
                    return AgentAction("move", dx=step[0], dy=step[1])
        # Caches
        if s["caches"]:
            cc = s["caches"][0]
            step = step_toward(game, actor, cc["x"], cc["y"], safe=True)
            if step != (0, 0):
                return AgentAction("move", dx=step[0], dy=step[1])
        # POIs
        if s["pois"]:
            px, py = s["pois"][0]
            step = step_toward(game, actor, px, py, safe=True)
            if step != (0, 0):
                return AgentAction("move", dx=step[0], dy=step[1])

        # ---- 11. REST: heal when safe ----
        if not s["adjacent_hostiles"] and not s["near_hostiles"] and hp_pct < 70:
            return AgentAction("rest")

        # ---- 12. FACTION DE-ESCALATION ----
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
            if st:
                step = step_toward_avoiding_elites(game, actor, st[0], st[1])
                return AgentAction("move", dx=step[0], dy=step[1])

        # ---- 13. FIGHT: last resort ----
        if s["adjacent_hostiles"]:
            t = s["adjacent_hostiles"][0]
            return AgentAction("move", dx=(t["x"] > actor.x) - (t["x"] < actor.x),
                                          dy=(t["y"] > actor.y) - (t["y"] < actor.y))

        # ---- 14. STAIRS ----
        if s["position"]["on_stairs"]:
            return AgentAction("descend")
        if st:
            step = step_toward_avoiding_elites(game, actor, st[0], st[1])
            if step != (0, 0):
                return AgentAction("move", dx=step[0], dy=step[1])
        return AgentAction("wait")


# Register all 6 agents under their names — same UniversalBrain, no per-class differences.
# Behavioral divergence comes exclusively from the Berlin starting kit.
register_brain("artisan", UniversalBrain)
register_brain("cartographer", UniversalBrain)
register_brain("emergent", UniversalBrain)
register_brain("exploiter", UniversalBrain)
register_brain("seeker", UniversalBrain)
register_brain("whisper", UniversalBrain)
