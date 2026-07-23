"""Universal agent brain — identity-driven scoring. Profile weights act as FLOORS:
identity actions always score at least their profile weight when reachable.
State urgency can exceed the floor for survival. Turn bonus biases initial divergence."""
from __future__ import annotations

from runtime.sense import (
    Brain, register_brain,
    step_toward, step_toward_safe, step_toward_avoiding_elites,
    step_away, attack_dir, is_dangerous, hostiles as _hostiles, adjacent,
)
from runtime.agent_action import AgentAction
from runtime.agent_perception import agent_state
from runtime.tactics import _stairs


PROFILES = {
    "artisan": {
        "forge": 15, "breakdown": 10, "explore": 6,
        "shield": 4, "recall": 4, "rest": 3,
        "fight": 1, "flee": 2, "commune": 1,
        "parley": 1, "becalm": 2, "stairs": 2,
        "workspace_fabricator": 12,
        "workspace_terminal": 3,
        "workspace_depleted": 4,
        "workspace_camp": 2,
    },
    "cartographer": {
        "explore": 15, "shield": 5, "recall": 6, "rest": 5,
        "forge": 2, "breakdown": 2,
        "fight": -5, "flee": 3, "commune": 2,
        "parley": 2, "becalm": 1, "stairs": 2,
        "workspace_fabricator": 3,
        "workspace_terminal": 12,
        "workspace_depleted": 4,
        "workspace_camp": 3,
    },
    "emergent": {
        "fight": 15, "shield": 10, "recall": 5, "flee": 4,
        "forge": 3, "breakdown": 2, "explore": 1,
        "rest": 2, "commune": 0,
        "parley": 0, "becalm": 0, "stairs": 1,
        "workspace_fabricator": 10,
        "workspace_terminal": 2,
        "workspace_depleted": 3,
        "workspace_camp": 3,
    },
    "exploiter": {
        "shield": 15, "fight": 10, "forge": 6, "flee": 5,
        "recall": 4, "rest": 3, "explore": 3,
        "breakdown": 2, "commune": 0,
        "parley": 1, "becalm": 1, "stairs": 2,
        "workspace_fabricator": 6,
        "workspace_terminal": 3,
        "workspace_depleted": 3,
        "workspace_camp": 10,
    },
    "seeker": {
        "forge": 8, "explore": 8, "fight": 8, "shield": 8,
        "recall": 6, "rest": 5, "flee": 5, "breakdown": 5,
        "commune": 3, "parley": 3, "becalm": 3, "stairs": 3,
        "workspace_fabricator": 6,
        "workspace_terminal": 6,
        "workspace_depleted": 6,
        "workspace_camp": 6,
    },
    "whisper": {
        "parley": 15, "commune": 10, "becalm": 10, "flee": 6,
        "rest": 5, "explore": 3, "recall": 3,
        "forge": 1, "breakdown": 1, "shield": 1,
        "fight": -5, "stairs": 2,
        "workspace_fabricator": 2,
        "workspace_terminal": 4,
        "workspace_depleted": 12,
        "workspace_camp": 5,
    },
}


def _starting_bonus(turn: int) -> int:
    if turn <= 1:
        return 12
    elif turn <= 3:
        return 8
    elif turn <= 5:
        return 4
    return 0


# Formula: score = max(profile_weight, state_bonus) + turn_bonus
# Profile = floor (identity), state = ceiling (urgency), turn = initial push
def _score(profile, key, state_bonus, turn_bonus, reachable: bool = True) -> float:
    if not reachable:
        return 0
    floor = profile.get(key, 0)
    return max(floor, state_bonus) + turn_bonus


class UniversalBrain(Brain):
    def __init__(self, name: str = "seeker"):
        self._name = name
        self._profile = PROFILES.get(name, PROFILES["seeker"])

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, val):
        self._name = val
        self._profile = PROFILES.get(val, PROFILES["seeker"])

    @property
    def profile(self) -> dict:
        return self._profile

    def decide(self, game, actor):
        s = agent_state(game, actor)
        hp_pct = s["vitals"]["hp_pct"]
        st = _stairs(game)
        bonus = _starting_bonus(game.turn)
        candidates = []

        # ---- PANIC: survival above all ----
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

        # ---- COMMUNE (any elite, not just final boss) ----
        can_commune = s["knowledge"]["truths_read"] >= 2 or s["matter"]["total"] >= 4
        elite_near = any(h.get("tier", 1) >= 3 or h.get("is_boss") for h in s.get("near_hostiles", []))
        reachable = can_commune and elite_near
        score = _score(self.profile, "commune", 25, bonus, reachable)
        if score > 0:
            candidates.append(("commune", score, AgentAction("commune")))

        # ---- BEACON ----
        if s.get("beacon_on_floor") and s.get("nearest_beacon"):
            bx, by, bd = s["nearest_beacon"]
            if bd > 2:
                urgency = 15 if (s["knowledge"]["truths_read"] >= 2 or s["matter"]["total"] >= 4) else 5
                score = _score(self.profile, "commune", urgency, bonus, True)
                candidates.append(("beacon", score, ("workspace", bx, by)))

        # ---- HEAL ----
        reachable = (hp_pct < 60 and s["can_heal_meaningfully"] and s["vitals"]["hp"] < s["vitals"]["max_hp"])
        if reachable:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Recall" or sig.get("base") == "Recall":
                    urgency = (100 - hp_pct) // 4
                    score = _score(self.profile, "recall", urgency, bonus, True)
                    candidates.append(("recall", score, AgentAction("cast", index=i)))
                    break

        # ---- PARLEY (boosted when standing >= 1 + elite nearby) ----
        if s.get("encounter_options"):
            for h in s["hostiles"]:
                if h.get("tier", 1) >= 3 or h.get("is_boss"):
                    if "parley" in s["encounter_options"]:
                        state = s.get("faction_standings", {}).get(h.get("faction", ""), 0) * 3
                        if s.get("danger_ahead"):
                            state += 10
                        # Gradient: when standing >= 1 and elite within 10 tiles, strongly prefer parley
                        standing = s.get("faction_standings", {}).get(h.get("faction", ""), 0)
                        if standing >= 1 and h.get("dist", 99) <= 10:
                            state += 15
                        score = _score(self.profile, "parley", state, bonus, True)
                        candidates.append(("parley", score, AgentAction("negotiate", target=h["name"])))
                    break

        # ---- BECALM (score higher than fight when resources available) ----
        reachable = bool(s["adjacent_hostiles"] and s["matter"]["total"] >= 2)
        if reachable:
            state = 0
            if s["can_becalm"]:
                state += 10
            state += s.get("reputation_summary", 0) * 2
            # Becalm should outscore fight when agent has the resources
            state += 8  # base preference for non-violence
            score = _score(self.profile, "becalm", state, bonus, True)
            candidates.append(("becalm", score, AgentAction("becalm")))

        # ---- FORGE ----
        reachable = bool(s["matter"]["total"] >= 2 and s["nav"]["free_sigil_slots"] > 0)
        if reachable:
            slotted = {sig.get("ability") for sig in s["sigils"]}
            for ability in ("Recall", "Ward", "Phase", "Echo", "Rally"):
                if ability not in slotted:
                    state = s["nav"]["free_sigil_slots"] * 2 + s["matter"]["total"] // 2
                    score = _score(self.profile, "forge", state, bonus, True)
                    candidates.append(("forge", score, AgentAction("forge", target=ability)))
                    break

        # ---- BREAKDOWN ----
        for sig in s["sigils"]:
            if sig.get("durability", 2) <= 1:
                score = _score(self.profile, "breakdown", 5, bonus, True)
                candidates.append(("breakdown", score, AgentAction("breakdown", target=sig["ability"])))
                break

        # ---- SHIELD ----
        reachable = len(s.get("adjacent_hostiles", [])) == 0
        if reachable:
            state = 5 if s["vitals"]["defense"] < 3 else -10
            score = _score(self.profile, "shield", state, bonus, True)
            if score > 0:
                candidates.append(("shield", score, AgentAction("shield")))

        # ---- CONSUMABLE (score higher when forge slots full) ----
        known = getattr(game.player, "_known_recipes", set())
        reachable = bool(known and s["matter"]["total"] >= 1 and len(s.get("adjacent_hostiles", [])) == 0)
        if reachable:
            from runtime.wear import RECIPE_COSTS
            affordable = [r for r in known if RECIPE_COSTS.get(r, 99) <= s["matter"]["total"]]
            if affordable:
                # Score higher when slots are full — agent has matter but can't forge
                state_bonus = 3
                if s["nav"]["free_sigil_slots"] == 0:
                    state_bonus = 12  # matter has no other use, craft something
                score = _score(self.profile, "forge", state_bonus, bonus, True)
                candidates.append(("consumable", score, ("consumable", affordable[0])))

        # ---- FLEE ----
        reachable = bool(s["adjacent_hostiles"] and hp_pct < 40)
        if reachable:
            t = s["adjacent_hostiles"][0]
            away = step_away(game, actor, t["x"], t["y"], safe=True)
            if away != (0, 0) and not s["has_trap_near"]:
                score = _score(self.profile, "flee", 5, bonus, True)
                candidates.append(("flee", score, AgentAction("move", dx=away[0], dy=away[1])))

        # ---- EXPLORE ----
        know = game.system("knowledge")
        unseen_count = 0
        if know:
            seen = know.seen.get(game.floor, set())
            px, py = actor.x, actor.y
            for y in range(max(0, py - 20), min(game.level.h, py + 21)):
                for x in range(max(0, px - 20), min(game.level.w, px + 21)):
                    if game.level.walkable(x, y) and (x, y) not in seen:
                        unseen_count += 1
            if unseen_count > 0:
                state = min(unseen_count // 5, 5)
                score = _score(self.profile, "explore", state, bonus, True)
                candidates.append(("explore_unseen", score, ("explore_unseen",)))

        if game.commune_landmark() is not None:
            score = _score(self.profile, "explore", 8, bonus, True)
            candidates.append(("interact", score, AgentAction("interact")))

        salvage_sys = game.system("salvage")
        if salvage_sys:
            ground = getattr(salvage_sys, "ground", {})
            if ground:
                nearest = min(ground.keys(), key=lambda p: abs(p[0]-actor.x)+abs(p[1]-actor.y))
                score = _score(self.profile, "explore", 5, bonus, True)
                candidates.append(("salvage", score, ("salvage", nearest[0], nearest[1])))

        if s["caches"]:
            cc = s["caches"][0]
            score = _score(self.profile, "explore", 4, bonus, True)
            candidates.append(("cache", score, ("cache", cc["x"], cc["y"])))

        if s["pois"]:
            ppx, ppy = s["pois"][0]
            score = _score(self.profile, "explore", 3, bonus, True)
            candidates.append(("poi", score, ("poi", ppx, ppy)))

        # ---- WORKSPACES + PORTALS ----
        for ws_key, ws_field in [("workspace_fabricator", "nearest_fabricator"),
                                  ("workspace_terminal", "nearest_terminal"),
                                  ("workspace_depleted", "nearest_depleted"),
                                  ("workspace_camp", "nearest_camp"),
                                  ("stairs", "nearest_portal")]:  # portals = floor skips
            ws = s.get(ws_field)
            if ws and len(ws) >= 3 and ws[2] is not None:
                dist = ws[2]
                if dist <= 8 and len(s.get("adjacent_hostiles", [])) == 0 and len(s.get("near_hostiles", [])) == 0:
                    score = _score(self.profile, ws_key if ws_key != "stairs" else "stairs",
                                   max(0, 12 - dist), bonus, True)  # portals get bonus for skip value
                    candidates.append((ws_key, score, ("workspace", ws[0], ws[1])))

        # ---- REST ----
        reachable = (len(s.get("adjacent_hostiles", [])) == 0 and len(s.get("near_hostiles", [])) == 0 and hp_pct < 70)
        if reachable:
            state = (100 - hp_pct) // 5
            score = _score(self.profile, "rest", state, bonus, True)
            if score > 0:
                candidates.append(("rest", score, AgentAction("rest")))

        # ---- WEATHER CLEAR ----
        if s["weather_hazard"] and s["matter"]["total"] >= 1 and len(s.get("adjacent_hostiles", [])) == 0:
            score = _score(self.profile, "rest", 3, bonus, True)
            candidates.append(("clear_weather", score, AgentAction("interact")))

        # ---- FIGHT ----
        if s["adjacent_hostiles"]:
            t = s["adjacent_hostiles"][0]
            state = 0
            if hp_pct > 60:
                state += 5
            if hp_pct < 30:
                state -= 15
            state += s["vitals"]["defense"]
            score = _score(self.profile, "fight", state, bonus, True)
            candidates.append(("fight", score,
                AgentAction("move", dx=(t["x"]>actor.x)-(t["x"]<actor.x),
                                  dy=(t["y"]>actor.y)-(t["y"]<actor.y))))

        # ---- FACTION DE-ESCALATION ----
        if game.kills >= 4 and not s["adjacent_hostiles"]:
            if s["position"]["on_stairs"]:
                candidates.append(("descend", 50, AgentAction("descend")))
            elif st:
                step = step_toward_avoiding_elites(game, actor, st[0], st[1])
                candidates.append(("deesc_stairs", 40, AgentAction("move", dx=step[0], dy=step[1])))

        # ---- STAIRS (boosted by commune readiness) ----
        commune_pull = 0
        if s["position"].get("commune_ready"):
            boss_floor = s["position"].get("boss_floor", 99)
            distance = boss_floor - s["position"]["floor"]
            if distance > 0 and distance <= 10:
                commune_pull = 20 + (10 - distance) * 2  # stronger pull when closer
        if s["position"]["on_stairs"]:
            candidates.append(("descend", _score(self.profile, "stairs", 2 + commune_pull, bonus, True),
                               AgentAction("descend")))
        elif st:
            step = step_toward_avoiding_elites(game, actor, st[0], st[1])
            if step != (0, 0):
                candidates.append(("stairs", _score(self.profile, "stairs", commune_pull, bonus, True),
                                   AgentAction("move", dx=step[0], dy=step[1])))

        # ---- Pick highest ----
        if not candidates:
            return AgentAction("wait")

        candidates.sort(key=lambda c: c[1], reverse=True)
        winner = candidates[0][2]

        if isinstance(winner, tuple):
            kind = winner[0]
            if kind == "consumable":
                return AgentAction("craft_consumable", target=winner[1])
            elif kind == "explore_unseen":
                best, bd, bt = None, 999, None
                pk = actor.x
                pk_y = actor.y
                kn = game.system("knowledge")
                sn = kn.seen.get(game.floor, set()) if kn else set()
                for y in range(max(0, pk_y-20), min(game.level.h, pk_y+21)):
                    for x in range(max(0, pk-20), min(game.level.w, pk+21)):
                        if game.level.walkable(x, y) and (x, y) not in sn:
                            # Skip visible traps when scholarship tier 2+
                            if any((x, y) == t for t in s.get("traps_visible", [])):
                                continue
                            d = max(abs(x-pk), abs(y-pk_y))
                            if d < bd:
                                best, bd, bt = (x, y), d, step_toward(game, actor, x, y, safe=True)
                if bt and bt != (0, 0):
                    return AgentAction("move", dx=bt[0], dy=bt[1])
                return AgentAction("wait")
            elif kind in ("salvage", "cache", "poi", "workspace"):
                tx, ty = winner[1], winner[2]
                step = step_toward(game, actor, tx, ty, safe=True)
                if step != (0, 0):
                    return AgentAction("move", dx=step[0], dy=step[1])
                return AgentAction("wait")
            else:
                return AgentAction("wait")

        return winner


register_brain("artisan", UniversalBrain)
register_brain("cartographer", UniversalBrain)
register_brain("emergent", UniversalBrain)
register_brain("exploiter", UniversalBrain)
register_brain("seeker", UniversalBrain)
register_brain("whisper", UniversalBrain)
