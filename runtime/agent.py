"""Universal agent brain — identity-driven scoring. Profile weights act as FLOORS:
identity actions always score at least their profile weight when reachable.
State urgency can exceed the floor for survival. Turn bonus biases initial divergence."""
from __future__ import annotations

from runtime.sense import (
    Brain, register_brain,
    step_toward, step_toward_safe, step_toward_avoiding_elites,
    step_away, flee_toward_safety, attack_dir, is_dangerous,
    hostiles as _hostiles, adjacent,
)
from runtime.agent_action import AgentAction
from runtime.agent_perception import agent_state
from runtime.tactics import _stairs

# Game.absorb_aspect grants its buff on the third consecutive rest on one tile.
ABSORB_ATTEMPTS = 3


PROFILES = {
    "artisan": {
        "forge": 15, "breakdown": 10, "explore": 6,
        "shield": 4, "recall": 4, "rest": 3,
        "fight": 1, "flee": 2, "commune": 1,
        "parley": 1, "becalm": 2, "stairs": 2,
        "shove": 3, "toss": 2, "ward": 2,
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
        "shove": 1, "toss": 5, "ward": 1,
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
        "shove": 10, "toss": 3, "ward": 8,
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
        "shove": 4, "toss": 8, "ward": 4,
        "workspace_fabricator": 6,
        "workspace_terminal": 3,
        "workspace_depleted": 3,
        "workspace_camp": 10,
    },
    "seeker": {
        "forge": 8, "explore": 8, "fight": 8, "shield": 8,
        "recall": 6, "rest": 5, "flee": 5, "breakdown": 5,
        "commune": 3, "parley": 3, "becalm": 3, "stairs": 3,
        "shove": 5, "toss": 5, "ward": 5,
        "workspace_fabricator": 6,
        "workspace_terminal": 6,
        "workspace_depleted": 6,
        "workspace_camp": 6,
    },
    "whisper": {
        "parley": 15, "commune": 10, "becalm": 10, "flee": 6,
        "rest": 5, "explore": 8, "recall": 3,
        "forge": 1, "breakdown": 1, "shield": 1,
        "fight": -5, "stairs": 2,
        "shove": 1, "toss": 6, "ward": 1,
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
#
# The trailing urgency term breaks ties. Several candidates share one profile key
# (explore covers explore_unseen, interact, salvage and cache), so whenever the profile
# weight sits above all their state values they score identically, and a stable sort then
# hands the turn to whichever was appended first. That made salvage and cache unreachable
# for every profile with explore >= 4. The term is small enough never to overturn a
# genuine one-point difference in the floor, and it only ever prefers the candidate the
# situation more urgently wants.
def _score(profile, key, state_bonus, turn_bonus, reachable: bool = True) -> float:
    if not reachable:
        return 0
    floor = profile.get(key, 0)
    return max(floor, state_bonus) + turn_bonus + max(0, state_bonus) * 0.01


class UniversalBrain(Brain):
    def __init__(self, name: str = "seeker"):
        self._name = name
        self._profile = PROFILES.get(name, PROFILES["seeker"])
        # Set every decide(): the scored candidate list, sorted, and the index actually
        # taken. Read by the balance harness; nothing in the game loop depends on it.
        self._last_candidates: list = []
        self._last_choice: int | None = None
        # Consecutive absorb-hazard rests on the current tile, so the attempt is bounded.
        self._hazard_tile: tuple | None = None
        self._hazard_tries: int = 0

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
        # Non-fighters panic sooner: 35% for fight<=2, 25% for fighters
        fw = self.profile.get("fight", 0)
        panic_cutoff = 35 if fw <= 2 else 25
        if hp_pct < panic_cutoff:
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
        truths = s["knowledge"]["truths_read"]
        factions = s.get("factions", {})
        standings = factions.get("standings", {})
        standing = max(standings.values()) if standings else 0
        discount = 1 if standing >= 4 else (0 if standing >= 2 else -1)
        needed = max(0, 2 - discount)
        can_commune = truths >= needed or s["matter"]["total"] >= 4
        elites = [h for h in s.get("near_hostiles", []) if h.get("tier", 1) >= 3 or h.get("is_boss")]
        elite_near = bool(elites)
        floor = s["position"]["floor"]
        boss_near = any(h.get("is_boss") for h in elites)
        # Boss floor: always try commune even if resources are low
        if boss_near and floor >= 26:
            can_commune = True
        reachable = can_commune and elite_near
        # Late-game surge: floors 20+ raise commune priority for healing sustain
        late_bonus = max(0, floor - 19) * 8  # +0 at 19, +8 at 20, +48 at 26
        # Boss proximity: if any nearby elite is the final boss, override priority
        boss_bonus = 100 if boss_near and floor >= 26 else 0
        score = _score(self.profile, "commune", 25 + late_bonus + boss_bonus, bonus, reachable)
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
        adj_hostiles = s.get("adjacent_hostiles", [])
        truths_avail = s["knowledge"]["truths_read"]
        matter_avail = s["matter"]["total"]
        # Cost: highest-tier adjacent enemy determines cost (2×tier matter or 1×tier truths)
        highest_tier = max((h.get("tier", 1) for h in adj_hostiles), default=1) if adj_hostiles else 1
        truth_cost = max(1, highest_tier)
        matter_cost = max(1, 2 * highest_tier)
        reachable = bool(adj_hostiles and (truths_avail >= truth_cost or matter_avail >= matter_cost))
        if reachable:
            state = 0
            if s["can_becalm"]:
                state += 15
            state += s.get("factions", {}).get("reputation_sum", 0) * 2
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
            if sig.get("durability", 2) <= 2:
                # Higher score when truths are low — agent needs commune fuel
                state = 12
                if s["knowledge"]["truths_read"] < 2:
                    state += 8  # urgent: need truths for commune
                score = _score(self.profile, "breakdown", state, bonus, True)
                candidates.append(("breakdown", score, AgentAction("breakdown", target=sig["ability"])))
                break

        # ---- SHOVE-TO-HAZARD (push enemy onto environmental damage tiles) ----
        if s["adjacent_hostiles"]:
            t = s["adjacent_hostiles"][0]
            hb = t.get("hazard_behind")
            if hb:
                # game.shove(dx,dy) uses (dx,dy) for BOTH targeting AND shove direction.
                # So the hazard direction must match the player→enemy direction.
                target_dx = (t["x"] > actor.x) - (t["x"] < actor.x)
                target_dy = (t["y"] > actor.y) - (t["y"] < actor.y)
                if hb["dx"] == target_dx and hb["dy"] == target_dy:
                    dx, dy = hb["dx"], hb["dy"]
                    tx, ty = t["x"] + dx, t["y"] + dy
                    is_adjacent_hazard = hb.get("adjacent", False)
                    is_hazard_dest = any(
                        hz["x"] == tx and hz["y"] == ty
                        for hz in s.get("hazard_tiles", [])
                    ) or is_adjacent_hazard
                    if not is_hazard_dest and not is_adjacent_hazard:
                        tx2, ty2 = t["x"] + 2*dx, t["y"] + 2*dy
                        is_hazard_dest = any(
                            hz["x"] == tx2 and hz["y"] == ty2
                            for hz in s.get("hazard_tiles", [])
                        )
                        is_adjacent_hazard = is_hazard_dest
                    if is_hazard_dest or is_adjacent_hazard:
                        affinity_mult = 1.0
                        weak = s.get("boss_weak_element")
                        props = hb.get("props", [])
                        if weak:
                            import_map = {"acid": "corrosive", "charged": "charged", "fire": "flammable"}
                            for p in props:
                                mapped = import_map.get(p, p)
                                if mapped == weak:
                                    affinity_mult = 2.5
                                    break
                        base = 5 if is_adjacent_hazard else 8
                        score = _score(self.profile, "shove" if "shove" in self.profile else "fight",
                                       base + int(affinity_mult * 3), bonus, True)
                        if score > 0:
                            candidates.append(("shove_to_hazard", score,
                                AgentAction("shove", dx=dx, dy=dy)))

        # ---- TOSS-TO-HAZARD (throw matter to draw enemy onto hazard) ----
        if (len(s.get("adjacent_hostiles", [])) == 0 and s["matter"]["total"] >= 1
                and s.get("hazard_tiles") and s["near_hostiles"]):
            # Any hazard tile near a hostile makes for a good toss target
            best_hazard = None
            best_score = 0
            for hz in s["hazard_tiles"]:
                for nh in s["near_hostiles"]:
                    dist_enemy_to_hz = max(abs(hz["x"] - nh["x"]), abs(hz["y"] - nh["y"]))
                    if dist_enemy_to_hz <= 2:
                        if hz["dist"] < 8:  # within toss range
                            h_score = 6 - hz["dist"] // 2 + (3 if dist_enemy_to_hz < 2 else 0)
                            if h_score > best_score:
                                best_score = h_score
                                best_hazard = hz
            if best_hazard:
                score = _score(self.profile, "toss" if "toss" in self.profile else "commune",
                               15 + best_score, bonus, True)
                if score > 0:
                    candidates.append(("toss_to_hazard", score,
                        ("toss_toward", best_hazard["x"], best_hazard["y"])))

        # ---- CAST-WARD (sigil auto-shoves enemies onto hazards) ----
        if len(s.get("adjacent_hostiles", [])) > 0:
            for i, sig in enumerate(s["sigils"]):
                if sig.get("ability") == "Ward" or sig.get("base") == "Ward":
                    # Ward is especially valuable when hazards are nearby
                    has_hazard_near = bool(s.get("hazard_tiles"))
                    state = 15 + (10 if has_hazard_near else 0)
                    score = _score(self.profile, "ward" if "ward" in self.profile else "shield",
                                   state, bonus, True)
                    if score > 0:
                        candidates.append(("cast_ward", score, AgentAction("cast", index=i)))
                    break

        # ---- SHIELD (pre-combat defense prep; heal when capped and wounded) ----
        shield_def = s["vitals"]["defense"]
        in_melee = len(s.get("adjacent_hostiles", [])) > 0
        reachable = (not in_melee
                     and (shield_def < 3 or hp_pct < 65))
        if reachable:
            state = 12 if shield_def < 3 else 8
            score = _score(self.profile, "shield", state, bonus, True)
            if score > 0:
                candidates.append(("shield", score, AgentAction("shield")))

        # ---- CONSUMABLE (score higher when forge slots full) ----
        known = getattr(game.player, "_known_recipes", set())
        reachable = bool(known and s["matter"]["total"] >= 1
                         and len(s.get("adjacent_hostiles", [])) == 0
                         and len(s.get("near_hostiles", [])) <= 2)
        if reachable:
            from runtime.wear import RECIPE_COSTS
            affordable = [r for r in known if RECIPE_COSTS.get(r, 99) <= s["matter"]["total"]]
            # Hazard-reactive consumables get priority when hazards are nearby
            hazard_consumables = {"trap_kit", "crystal_seed", "sparkwire", "frost_ampoule",
                                   "root_tendril", "noise_lure", "wardstone"}
            has_hazards = bool(s.get("hazard_tiles"))
            hostile_near = bool(s.get("near_hostiles"))
            if affordable:
                # Prioritize hazard consumables when enemies and hazards both present
                hazard_afford = [r for r in affordable if r in hazard_consumables]
                chosen = affordable[0]
                state_bonus = 3
                if s["nav"]["free_sigil_slots"] == 0:
                    state_bonus = 12
                if has_hazards and hostile_near and hazard_afford:
                    state_bonus = max(state_bonus, 15)
                    chosen = hazard_afford[0]
                elif has_hazards and not hostile_near and hazard_afford:
                    # Neutralize-hazard: craft consumable to clear path or set trap
                    for hz in s["hazard_tiles"]:
                        if hz.get("dist", 99) <= 3:
                            state_bonus = max(state_bonus, 8)
                            break
                    chosen = hazard_afford[0] if hazard_afford else chosen
                score = _score(self.profile, "forge", state_bonus, bonus, True)
                candidates.append(("consumable", score, ("consumable", chosen)))

        # ---- FLEE ----
        # Non-fighters flee sooner — the lower the fight weight, the earlier the panic
        fight_weight = self.profile.get("fight", 0)
        flee_hp_cutoff = 40 + max(0, (5 - fight_weight) * 5)  # 40@fight=5, 55@fight=1, 65@fight=-5
        reachable = bool(s["adjacent_hostiles"] and hp_pct < flee_hp_cutoff)
        if reachable:
            # Multi-step BFS flee: find nearest tile 5+ tiles from any hostile
            away = flee_toward_safety(game, actor, min_safe_dist=5)
            if away == (0, 0):
                # Fallback: single-step away from nearest hostile
                t = s["adjacent_hostiles"][0]
                away = step_away(game, actor, t["x"], t["y"], safe=True)
            if away != (0, 0) and not s["has_trap_near"]:
                # More desperate when surrounded: multiple hostiles = flee harder
                escape_urgency = 5 + min(len(s["adjacent_hostiles"]), 3) * 3
                score = _score(self.profile, "flee", escape_urgency, bonus, True)
                candidates.append(("flee", score, AgentAction("move", dx=away[0], dy=away[1])))
            elif away == (0, 0) and len(s["adjacent_hostiles"]) >= 2:
                # --- Tier 2: Phase/Ward fallback when truly cornered ---
                for i, sig in enumerate(s["sigils"]):
                    ability = sig.get("ability", sig.get("base", ""))
                    if ability in ("Phase", "Ward"):
                        score = _score(self.profile, "flee", 20, bonus, True)
                        candidates.append(("sigil_escape", score,
                                          AgentAction("cast", index=i)))
                        break
 
        # ---- STUCK DETECTION (computed here, used by explore + stairs) ----
        no_targets = (len(s.get("adjacent_hostiles", [])) == 0
                      and len(s.get("near_hostiles", [])) == 0
                      and not s.get("caches") and not s.get("pois")
                      and not s.get("loci_count", 0) and hp_pct >= 40)

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
                # Boss floor: explore everything to find the boss
                if game.floor >= getattr(game, "max_floor", 26):
                    state += 10
                # Stuck boost: when no targets, explore urgently
                if no_targets:
                    state += 5
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

        # ---- LOCUS ----
        loc = s.get("nearest_locus")
        if loc and len(loc) >= 3 and loc[2] is not None and loc[2] <= 12:
            dist = loc[2]
            state = max(0, 12 - dist)
            # Profile match: agent's highest-weight action determines locus type
            top_action = max(self.profile.items(), key=lambda x: x[1])[0]
            if top_action in ("forge", "parley", "explore", "fight", "commune", "shield"):
                state += 5  # this locus will type-cast favorably
            score = _score(self.profile, "explore", state, bonus, True)
            if score > 0:
                candidates.append(("locus", score, ("salvage", loc[0], loc[1])))

        # ---- DEPLOY SIGIL (check all sigils, pick best) ----
        best_deploy_score = 0
        best_deploy_action = None
        for i, sig in enumerate(s["sigils"]):
            ability = sig.get("ability", sig.get("base", ""))
            deployable = {"Recall", "Phase", "Rally", "Ward", "Echo"}
            if ability not in deployable:
                continue
            has_hostiles = bool(s.get("near_hostiles"))
            has_hazards = bool(s.get("hazard_tiles"))
            state = 8
            if has_hostiles: state += 5
            if has_hazards: state += 5
            if ability == "Recall" and hp_pct < 50: state += 10
            if ability == "Echo" and s["position"]["floor"] >= getattr(game, "max_floor", 26) - 3: state += 15
            if ability == "Ward" and has_hostiles: state += 8
            if ability == "Rally" and len(s.get("companions", [])) > 0: state += 8
            score = _score(self.profile, "explore", state, bonus, True)
            if score > best_deploy_score:
                best_deploy_score = score
                best_deploy_action = AgentAction("deploy", index=i)
        if best_deploy_action:
            candidates.append(("deploy", best_deploy_score, best_deploy_action))

        # ---- RECOVER DEPLOYED SIGIL ----
        recover_pos = None
        for a in game.actors:
            if getattr(a, "_is_deployed", False) and a.hp > 0:
                dist = max(abs(a.x - actor.x), abs(a.y - actor.y))
                if dist <= 5:
                    recover_pos = (a.x, a.y)
                    break
        if recover_pos:
            score = _score(self.profile, "explore", 6, bonus, True)
            if score > 0:
                candidates.append(("recover", score, ("recover", recover_pos[0], recover_pos[1])))

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
        reachable = (len(s.get("adjacent_hostiles", [])) == 0
                     and len(s.get("near_hostiles", [])) == 0 and hp_pct < 55)
        if reachable:
            state = (100 - hp_pct) // 5
            score = _score(self.profile, "rest", state, bonus, True)
            if score > 0:
                candidates.append(("rest", score, AgentAction("rest")))

        # ---- ABSORB-HAZARD (rest on hazard to gain aspect buff) ----
        here = (s["position"]["x"], s["position"]["y"])
        hazard_on_player = any(
            here == (hz["x"], hz["y"]) for hz in s.get("hazard_tiles", [])
        )
        if here != self._hazard_tile:
            self._hazard_tile, self._hazard_tries = here, 0
        # Game.absorb_aspect needs 3 consecutive rests on one tile. Give it exactly that
        # many and no more: the tile may carry a hazard this candidate can see but that
        # absorb_aspect cannot use, and without a cap the agent rests on it forever
        # chasing a buff that can never land.
        if (hazard_on_player and self._hazard_tries < ABSORB_ATTEMPTS
                and not s.get("adjacent_hostiles") and not s.get("near_hostiles")):
            score = _score(self.profile, "rest", 15, bonus, True)
            if score > 0:
                self._hazard_tries += 1
                candidates.append(("absorb_hazard", score, AgentAction("rest")))

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
        stuck_pull = 5 if no_targets else 0
        if s["position"]["on_stairs"]:
            candidates.append(("descend", _score(self.profile, "stairs", 2 + commune_pull + stuck_pull, bonus, True),
                                AgentAction("descend")))
        elif st:
            step = step_toward_avoiding_elites(game, actor, st[0], st[1])
            if step != (0, 0):
                candidates.append(("stairs", _score(self.profile, "stairs", commune_pull + stuck_pull, bonus, True),
                                    AgentAction("move", dx=step[0], dy=step[1])))

        # ---- Pick highest ----
        # Candidates are kept on the brain so a harness can read what was decided and,
        # more usefully, how close the runner-up was. A game with hard choices produces
        # narrow margins often; a dominant strategy produces one wide margin every turn.
        if not candidates:
            self._last_candidates, self._last_choice = [], None
            return AgentAction("wait")

        candidates.sort(key=lambda c: c[1], reverse=True)
        self._last_candidates = candidates

        # Walk the list in score order and take the first candidate that resolves to a
        # real action. A candidate whose target turns out to be unreachable used to
        # collapse the whole decision to `wait`, which handed the turn to the next-best
        # option's worst case instead of to the next-best option.
        for idx, (_label, _cand_score, cand) in enumerate(candidates):
            act = self._resolve(game, actor, s, cand)
            if act is not None:
                self._last_choice = idx
                return act

        self._last_choice = None
        return AgentAction("wait")

    def _resolve(self, game, actor, s, winner):
        """Turn a candidate payload into an AgentAction, or None if it cannot be acted on."""
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
                            # Skip visible AND predicted traps (room profile learning)
                            if any((x, y) == t for t in s.get("traps_visible", [])):
                                continue
                            if any((x, y) == t for t in s.get("predicted_traps", [])):
                                continue
                            d = max(abs(x-pk), abs(y-pk_y))
                            # Dead-end penalty: leaf rooms have one exit — avoid them
                            ridx = game.room_at(x, y)
                            nid = getattr(game, "room_notes", {}).get(ridx) if ridx is not None else None
                            if nid and hasattr(game.player, "_room_profiles"):
                                try:
                                    role = game.player._room_profiles.role_for(game.m, nid)
                                    if role == "leaf":
                                        d += 4  # effectively 4 tiles further — prefer hubs/bridges
                                except Exception:
                                    pass
                            if d < bd:
                                best, bd, bt = (x, y), d, step_toward_safe(game, actor, x, y)
                if bt and bt != (0, 0):
                    return AgentAction("move", dx=bt[0], dy=bt[1])
                return None
            elif kind in ("salvage", "cache", "poi", "workspace", "recover"):
                tx, ty = winner[1], winner[2]
                # Arriving at a deployed sigil is the point of the recover candidate, so
                # check it before pathing: standing on the tile yields no step.
                if kind == "recover" and max(abs(actor.x - tx), abs(actor.y - ty)) <= 1:
                    return AgentAction("recover")
                step = step_toward(game, actor, tx, ty, safe=True)
                if step != (0, 0):
                    return AgentAction("move", dx=step[0], dy=step[1])
                return None
            elif kind == "toss_toward":
                # Toss matter toward a hazard tile to draw enemies onto it
                tx, ty = winner[1], winner[2]
                px, py = actor.x, actor.y
                # Determine toss direction toward the hazard
                dx = 1 if tx > px else (-1 if tx < px else 0)
                dy = 1 if ty > py else (-1 if ty < py else 0)
                if dx != 0 or dy != 0:
                    return AgentAction("toss", dx=dx, dy=dy)
                return None
            else:
                return None

        return winner


register_brain("artisan", UniversalBrain)
register_brain("cartographer", UniversalBrain)
register_brain("emergent", UniversalBrain)
register_brain("exploiter", UniversalBrain)
register_brain("seeker", UniversalBrain)
register_brain("whisper", UniversalBrain)
