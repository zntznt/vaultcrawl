"""Universal agent brain — dynamic priority scoring. Berlin Convention compliant.
Every agent can do everything. Starting state + scoring profile produce
behavioral divergence. One tree, six scoring profiles, zero personality gates."""
from __future__ import annotations

from runtime.sense import (
    Brain, register_brain,
    step_toward, step_toward_safe, step_toward_avoiding_elites,
    step_away, attack_dir, is_dangerous, hostiles as _hostiles, adjacent,
)
from runtime.agent_action import AgentAction
from runtime.agent_perception import agent_state
from runtime.tactics import _stairs


# ---- Scoring profiles (starting bonuses decay over first 5 turns) ----
PROFILES = {
    "artisan": {
        "forge": 15, "breakdown": 10, "explore": 6,
        "shield": 4, "recall": 4, "rest": 3,
        "fight": 1, "flee": 2, "commune": 1,
        "parley": 1, "becalm": 2, "stairs": 2,
    },
    "cartographer": {
        "explore": 15, "shield": 5, "recall": 6, "rest": 5,
        "forge": 2, "breakdown": 2,
        "fight": -5, "flee": 3, "commune": 2,
        "parley": 2, "becalm": 1, "stairs": 2,
    },
    "emergent": {
        "fight": 15, "shield": 10, "recall": 5, "flee": 4,
        "forge": 3, "breakdown": 2, "explore": 1,
        "rest": 2, "commune": 0,
        "parley": 0, "becalm": 0, "stairs": 1,
    },
    "exploiter": {
        "shield": 15, "fight": 10, "forge": 6, "flee": 5,
        "recall": 4, "rest": 3, "explore": 3,
        "breakdown": 2, "commune": 0,
        "parley": 1, "becalm": 1, "stairs": 2,
    },
    "seeker": {
        "forge": 8, "explore": 8, "fight": 8, "shield": 8,
        "recall": 6, "rest": 5, "flee": 5, "breakdown": 5,
        "commune": 3, "parley": 3, "becalm": 3, "stairs": 3,
    },
    "whisper": {
        "parley": 15, "commune": 10, "becalm": 10, "flee": 6,
        "rest": 5, "explore": 3, "recall": 3,
        "forge": 1, "breakdown": 1, "shield": 1,
        "fight": -5, "stairs": 2,
    },
}


def _starting_bonus(turn: int) -> int:
    """Scores get an extra push in the first few turns to bias initial divergence."""
    if turn <= 1:
        return 12
    elif turn <= 3:
        return 8
    elif turn <= 5:
        return 4
    return 0


class UniversalBrain(Brain):
    """One decision function. Six scoring profiles. Behavioral divergence
    emerges from starting-state + scoring-preference interaction."""

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
        turn_bonus = _starting_bonus(game.turn)
        candidates = []

        # ---- PANIC OVERRIDE: survival above all ----
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

        # ---- COMMUNE: alternate win condition ----
        if s["knowledge"]["truths_read"] >= 2 or s["matter"]["total"] >= 4:
            if s["nav"]["any_boss_near"]:
                score = self.profile.get("commune", 0) + turn_bonus + 25
                candidates.append(("commune", score, AgentAction("commune")))

        # ---- HEAL: cast Recall ----
        if hp_pct < 60 and s["can_heal_meaningfully"] and s["vitals"]["hp"] < s["vitals"]["max_hp"]:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Recall" or sig.get("base") == "Recall":
                    score = self.profile.get("recall", 0) + turn_bonus + (100 - hp_pct) // 4
                    candidates.append(("recall", score, AgentAction("cast", index=i)))
                    break

        # ---- PARLEY: negotiate with elites ----
        if s.get("encounter_options"):
            opts = s["encounter_options"]
            for h in s["hostiles"]:
                if h.get("tier", 1) >= 3 or h.get("is_boss"):
                    if "parley" in opts:
                        score = self.profile.get("parley", 0) + turn_bonus
                        score += s.get("faction_standings", {}).get(h.get("faction", ""), 0) * 3
                        if s.get("danger_ahead"):
                            score += 10
                        candidates.append(("parley", score, AgentAction("negotiate", target=h["name"])))
                    break

        # ---- BECALM: pacify adjacent hostiles ----
        if s["adjacent_hostiles"] and s["matter"]["total"] >= 2:
            score = self.profile.get("becalm", 0) + turn_bonus
            if s["can_becalm"]:
                score += 10
            score += s.get("reputation_summary", 0) * 2
            candidates.append(("becalm", score, AgentAction("becalm")))

        # ---- FORGE: craft sigils ----
        if s["matter"]["total"] >= 2 and s["nav"]["free_sigil_slots"] > 0:
            slotted = {sig.get("ability") for sig in s["sigils"]}
            for ability in ("Recall", "Ward", "Phase", "Echo", "Rally"):
                if ability not in slotted:
                    score = self.profile.get("forge", 0) + turn_bonus
                    score += s["nav"]["free_sigil_slots"] * 2
                    score += s["matter"]["total"] // 2
                    candidates.append(("forge", score, AgentAction("forge", target=ability)))
                    break

        # ---- BREAKDOWN: recover matter ----
        for sig in s["sigils"]:
            if sig.get("durability", 2) <= 1:
                score = self.profile.get("breakdown", 0) + turn_bonus
                score += 5  # urgency — about to shatter
                candidates.append(("breakdown", score, AgentAction("breakdown", target=sig["ability"])))
                break

        # ---- SHIELD: build defense ----
        if not s["adjacent_hostiles"]:
            score = self.profile.get("shield", 0) + turn_bonus
            if s["vitals"]["defense"] < 3:
                score += 5
            else:
                score -= 10  # don't shield at cap
            candidates.append(("shield", score, AgentAction("shield")))

        # ---- FLEE: escape adjacent hostiles ----
        if s["adjacent_hostiles"] and hp_pct < 40:
            t = s["adjacent_hostiles"][0]
            away = step_away(game, actor, t["x"], t["y"], safe=True)
            if away != (0, 0) and not s["has_trap_near"]:
                score = self.profile.get("flee", 0) + turn_bonus + 5
                candidates.append(("flee", score, AgentAction("move", dx=away[0], dy=away[1])))

        # ---- EXPLORE: unseen tiles, POIs, caches, salvage, landmarks ----
        # Unseen tiles
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
                score = self.profile.get("explore", 0) + turn_bonus + min(unseen_count // 5, 5)
                candidates.append(("explore_unseen", score, "unseen"))

        # Landmarks
        if game.commune_landmark() is not None:
            score = self.profile.get("explore", 0) + turn_bonus + 8
            candidates.append(("interact", score, AgentAction("interact")))

        # Salvage
        salvage_sys = game.system("salvage")
        if salvage_sys:
            ground = getattr(salvage_sys, "ground", {})
            if ground:
                nearest = min(ground.keys(), key=lambda p: abs(p[0]-actor.x)+abs(p[1]-actor.y))
                score = self.profile.get("explore", 0) + turn_bonus + 5
                candidates.append(("salvage", score, ("salvage", nearest[0], nearest[1])))

        # Caches
        if s["caches"]:
            cc = s["caches"][0]
            score = self.profile.get("explore", 0) + turn_bonus + 4
            candidates.append(("cache", score, ("cache", cc["x"], cc["y"])))

        # POIs
        if s["pois"]:
            px, py = s["pois"][0]
            score = self.profile.get("explore", 0) + turn_bonus + 3
            candidates.append(("poi", score, ("poi", px, py)))

        # ---- REST: heal when safe ----
        if not s["adjacent_hostiles"] and not s["near_hostiles"] and hp_pct < 70:
            score = self.profile.get("rest", 0) + turn_bonus
            score += (100 - hp_pct) // 5
            candidates.append(("rest", score, AgentAction("rest")))

        # ---- FIGHT: combat as option (not last resort — scored alongside others) ----
        if s["adjacent_hostiles"]:
            t = s["adjacent_hostiles"][0]
            score = self.profile.get("fight", 0) + turn_bonus
            if hp_pct > 60:
                score += 5
            if hp_pct < 30:
                score -= 15
            score += s["vitals"]["defense"]
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

        # ---- STAIRS (fallback) ----
        if s["position"]["on_stairs"]:
            candidates.append(("descend", self.profile.get("stairs", 0) + 2, AgentAction("descend")))
        elif st:
            step = step_toward_avoiding_elites(game, actor, st[0], st[1])
            if step != (0, 0):
                candidates.append(("stairs", self.profile.get("stairs", 0), AgentAction("move", dx=step[0], dy=step[1])))

        # ---- Pick highest-scoring action ----
        if not candidates:
            return AgentAction("wait")

        candidates.sort(key=lambda c: c[1], reverse=True)
        winner = candidates[0][2]

        # Resolve explore-like actions to actual AgentAction moves
        if isinstance(winner, tuple):
            kind = winner[0]
            if kind == "unseen":
                know = game.system("knowledge")
                seen = know.seen.get(game.floor, set()) if know else set()
                px, py = actor.x, actor.y
                best, bd = None, 999
                for y in range(max(0, py-20), min(game.level.h, py+21)):
                    for x in range(max(0, px-20), min(game.level.w, px+21)):
                        if game.level.walkable(x, y) and (x, y) not in seen:
                            d = max(abs(x-px), abs(y-py))
                            if d < bd:
                                best, bd = (x, y), d
                if best:
                    step = step_toward(game, actor, best[0], best[1], safe=True)
                    if step != (0, 0):
                        return AgentAction("move", dx=step[0], dy=step[1])
                return AgentAction("wait")
            elif kind in ("salvage", "cache", "poi"):
                tx, ty = winner[1], winner[2]
                step = step_toward(game, actor, tx, ty, safe=True)
                if step != (0, 0):
                    return AgentAction("move", dx=step[0], dy=step[1])
                return AgentAction("wait")
            else:
                return AgentAction("wait")

        return winner


# Berlin-compliant: all 6 agents use the same UniversalBrain.
# Behavioral divergence comes from PROFILES dict + game.py starting_kit().
register_brain("artisan", UniversalBrain)
register_brain("cartographer", UniversalBrain)
register_brain("emergent", UniversalBrain)
register_brain("exploiter", UniversalBrain)
register_brain("seeker", UniversalBrain)
register_brain("whisper", UniversalBrain)
