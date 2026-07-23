"""agent_state — a comprehensive state snapshot every brain reads once per turn.

Returns a dict with sections: vitals, status, effects, position, hostiles,
sigils, matter, caches, pois, tension, factions, knowledge, nav.

All system accesses are None-guarded; all attribute reads use getattr with
sensible defaults. The snapshot is pure data — no methods, no side effects.
"""
from __future__ import annotations

from runtime.sense import hostiles, is_dangerous, points_of_interest
from runtime.tactics import _stairs


_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))


def agent_state(game, actor) -> dict:
    p = actor
    px, py = p.x, p.y

    # -- vitals ----------------------------------------------------------------
    hp = getattr(p, "hp", 0)
    max_hp = getattr(p, "max_hp", 0)
    body = {}
    if hasattr(p, "body") and p.body:
        for part_name, part_info in p.body.items():
            body[part_name] = {
                "hp": part_info.get("hp", 0),
                "max": part_info.get("max", 0),
            }

    vitals = {
        "hp": hp,
        "max_hp": max_hp,
        "hp_pct": (hp * 100) // max_hp if max_hp else 0,
        "defense": getattr(p, "defense", 0),
        "body": body,
    }

    can_heal_meaningfully = False
    if body:
        for part_info in p.body.values():
            if part_info.get("hp", 0) < part_info.get("max", 0):
                can_heal_meaningfully = True
                break
    else:
        can_heal_meaningfully = hp < max_hp

    # -- status ----------------------------------------------------------------
    status = {
        "is_resting": getattr(game, "_resting", False),
        "consecutive_rest": getattr(game, "_consecutive_rest", 0),
        "bleeding": getattr(p, "_bleeding", 0),
        "slowed": getattr(p, "_slowed", 0),
        "staggered": getattr(p, "_staggered", 0),
        "speed": getattr(p, "speed", 1.0),
    }

    # -- effects ---------------------------------------------------------------
    eff_sys = game.system("effects")
    worn_effect = getattr(eff_sys, "worn", None) if eff_sys else None
    collected = list(getattr(eff_sys, "collected", {}).keys()) if eff_sys else []

    effects = {
        "worn_effect": worn_effect,
        "collected": collected,
    }

    # -- position --------------------------------------------------------------
    on_town = (
        bool(getattr(game, "_on_surface", lambda: False)())
        and (px, py) in getattr(game, "_town_tiles", set())
    )

    position = {
        "x": px,
        "y": py,
        "on_stairs": game.on_stairs(),
        "on_town": on_town,
        "on_surface": bool(getattr(game, "_on_surface", lambda: False)()),
        "region": getattr(game, "region_name", ""),
        "floor": getattr(game, "floor", 0),
        "max_floor": getattr(game, "max_floor", 1),
    }

    weather_sys = game.system("weather")
    if weather_sys is None:
        weather_hazard = None
    else:
        weather_hazard = getattr(weather_sys, "weather", "") == "acrid haze"

    # -- hostiles --------------------------------------------------------------
    hl = hostiles(game, actor)
    hostiles_list = []
    for h in hl:
        d = max(abs(px - h.x), abs(py - h.y))
        h_body = {}
        if hasattr(h, "body") and h.body:
            for pn, pi in h.body.items():
                h_body[pn] = {"hp": pi.get("hp", 0), "max": pi.get("max", 0)}
        hostiles_list.append({
            "name": getattr(h, "name", ""),
            "hp": getattr(h, "hp", 0),
            "max_hp": getattr(h, "max_hp", 0),
            "tier": getattr(h, "tier", 1),
            "x": h.x,
            "y": h.y,
            "dist": d,
            "faction": getattr(h, "faction", ""),
            "is_boss": getattr(h, "is_boss", False),
            "source": getattr(h, "source", ""),
            "body": h_body,
            "allegiance": getattr(h, "allegiance", ""),
            "enraged": getattr(h, "_enraged", False),
            "on_hazard": is_dangerous(game, h.x, h.y),
        })

    hostiles_list.sort(key=lambda h: h["dist"])

    adjacent_hostiles = [h for h in hostiles_list if h["dist"] <= 1]
    near_hostiles = [h for h in hostiles_list if h["dist"] <= 3]

    # -- sigils ----------------------------------------------------------------
    sig_sys = game.system("sigils")
    sigils_list = []
    if sig_sys:
        for s in getattr(sig_sys, "slots", []):
            sigils_list.append({
                "ability": s.get("ability", ""),
                "base": s.get("base", ""),
                "durability": s.get("durability", 0),
            })

    # -- matter ----------------------------------------------------------------
    salv_sys = game.system("salvage")
    matter_total = 0
    inventory_summary = {}
    forge_ready = False
    if salv_sys:
        inv_bag = salv_sys.inventory(game)
        if inv_bag is not None:
            matter_total = inv_bag.total()
            inventory_summary = dict(getattr(inv_bag, "comp", {}))
        forge_sys = game.system("forge")
        if forge_sys is not None:
            try:
                forge_ready = inv_bag is not None and inv_bag.can_pay(
                    forge_sys.cost(game))
            except Exception:
                forge_ready = False

    matter = {
        "total": matter_total,
        "inventory": inventory_summary,
        "forge_ready": forge_ready,
    }

    # -- caches ----------------------------------------------------------------
    cache_sys = game.system("caches")
    caches_list = []
    if cache_sys:
        for (cx, cy), entry in getattr(cache_sys, "caches", {}).items():
            d = max(abs(px - cx), abs(py - cy))
            if d <= 20:
                caches_list.append({
                    "x": cx,
                    "y": cy,
                    "dist": d,
                    "material": entry.get("material", ""),
                    "peril": entry.get("peril", ""),
                    "aged": entry.get("aged", False),
                })
    caches_list.sort(key=lambda c: c["dist"])

    # -- pois ------------------------------------------------------------------
    pois = points_of_interest(game)

    # -- tension ---------------------------------------------------------------
    tension = getattr(game, "_tension", 0)

    # -- noise near ------------------------------------------------------------
    noise_near = False
    sense_sys = game.system("senses")
    if sense_sys:
        for (sx, sy, _vol, _ttl) in getattr(sense_sys, "sounds", []):
            if max(abs(px - sx), abs(py - sy)) <= 8:
                noise_near = True
                break

    # -- factions --------------------------------------------------------------
    fac_sys = game.system("factions")
    standings = {}
    rep_sum = 0
    if fac_sys:
        standings = dict(getattr(fac_sys, "standing", {}))
        rep_sum = sum(standings.values())

    factions = {
        "standings": standings,
        "reputation_sum": rep_sum,
    }

    standing_critical = False
    if fac_sys:
        for standing_val in getattr(fac_sys, "standing", {}).values():
            if standing_val <= -3:
                standing_critical = True
                break

    # -- knowledge -------------------------------------------------------------
    know_sys = game.system("knowledge")
    known_notes = 0
    learned_notes = 0
    if know_sys:
        known_notes = len(getattr(know_sys, "known", set()))
        learned_notes = len(getattr(know_sys, "learned", set()))

    marg = game.system("marginalia")
    hist = game.system("history")
    truths_read = (
        (getattr(marg, "read", 0) if marg else 0)
        + (getattr(hist, "read", 0) if hist else 0)
    )

    knowledge = {
        "known_notes": known_notes,
        "learned_notes": learned_notes,
        "truths_read": truths_read,
    }

    can_becalm = False
    if know_sys is not None and matter_total >= 2:
        learned = getattr(know_sys, "learned", set())
        for h in adjacent_hostiles:
            src = h.get("source", "")
            tier = h.get("tier", 1)
            if src and src in learned:
                cost = 2 * max(1, tier)
                if matter_total >= cost:
                    can_becalm = True
                    break

    # -- nav -------------------------------------------------------------------
    sandbox = getattr(game, "sandbox", False)
    stairs_pos = None
    if not sandbox:
        try:
            stairs_pos = _stairs(game)
        except Exception:
            stairs_pos = None
    else:
        gates = getattr(game, "_gates", {})
        if gates:
            best = None
            bd = None
            for (gx, gy), _ in gates.items():
                d = max(abs(px - gx), abs(py - gy))
                if bd is None or d < bd:
                    best, bd = (gx, gy), d
            stairs_pos = best

    has_lantern = False
    has_small = False
    if eff_sys:
        w = getattr(eff_sys, "worn", None)
        has_lantern = (w == "lantern")
        has_small = (w == "small")

    max_sigils = sig_sys.max_slots(game) if sig_sys else 3
    free_sigil_slots = max_sigils - len(getattr(sig_sys, "slots", []))

    any_boss_near = any(
        h["is_boss"] for h in hostiles_list if h["dist"] <= 5
    )

    nav = {
        "stairs": stairs_pos,
        "has_lantern": has_lantern,
        "has_small": has_small,
        "max_sigils": max_sigils,
        "free_sigil_slots": free_sigil_slots,
        "any_boss_near": any_boss_near,
    }

    # -- traps -----------------------------------------------------------------
    has_trap_near = False
    if know_sys is not None:
        seen = know_sys.seen.get(game.floor, set())
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = px + dx, py + dy
                if game.level.walkable(nx, ny) and (nx, ny) not in seen:
                    has_trap_near = True
                    break
            if has_trap_near:
                break

    # -- faction kills ---------------------------------------------------------
    faction_kills = {}
    recent_kill_count = 0
    messages = list(getattr(game, "messages", []))[-40:]
    if messages:
        # Build faction map from all actors (including recently slain that may
        # still have their names in messages even if removed from actors)
        name_to_faction = {}
        for o in game.actors:
            name = getattr(o, "name", "")
            if name:
                name_to_faction[name] = getattr(o, "faction", "")
        for msg in messages:
            if "destroy" not in msg:
                continue
            recent_kill_count += 1
            for name, faction in name_to_faction.items():
                if faction and name in msg:
                    faction_kills[faction] = faction_kills.get(faction, 0) + 1
                    break

    kills_on = None
    if faction_kills:
        best_faction = max(faction_kills, key=faction_kills.get)
        kills_on = (best_faction, faction_kills[best_faction])

    # -- spawn pool (Phase 2: The Memory) ------------------------------------
    spawn_threat = []
    spawn_allies = []
    if fac_sys:
        standing = getattr(fac_sys, "standing", {})
        for fid, val in standing.items():
            if val <= -3:
                spawn_threat.append(fid)
            if val >= 3:
                spawn_allies.append(fid)

    becalm_discount = 0
    try:
        region = game.region_for(game.floor)
        if region is not None:
            anchor = region.get("sourceNoteId", "")
            if anchor and know_sys is not None:
                nodes = game.m.get("graph", {}).get("nodes", {})
                node = nodes.get(anchor, {})
                community = node.get("community")
                if community is not None:
                    learned = getattr(know_sys, "learned", set())
                    for nid in learned:
                        n = nodes.get(nid, {})
                        if n.get("community") == community:
                            becalm_discount += 1
    except Exception:
        becalm_discount = 0

    # -- companions -------------------------------------------------------------
    comp_states = getattr(game, "_companions", {}) or {}
    companions_list = []
    for a in game.actors:
        if getattr(a, "allegiance", "") != "companion":
            continue
        name = getattr(a, "name", "")
        hp = getattr(a, "hp", 0)
        max_hp = getattr(a, "max_hp", 0)
        cd = max(abs(px - a.x), abs(py - a.y))
        entry = comp_states.get(name, {})
        command = entry.get("state", "follow")
        panicking = hp < max_hp * 0.25 if max_hp else False
        companions_list.append({
            "name": name,
            "hp": hp,
            "max_hp": max_hp,
            "x": a.x,
            "y": a.y,
            "dist": cd,
            "command": command,
            "panicking": panicking,
        })

    companion_count = len(companions_list)
    if hasattr(game, "_companion_penalty"):
        companion_penalty = game._companion_penalty()
    else:
        companion_penalty = max(0, (companion_count - 1) * 4)

    # -- can recruit -----------------------------------------------------------
    can_recruit = False
    if fac_sys:
        for val in getattr(fac_sys, "standing", {}).values():
            if val >= 2:
                can_recruit = True
                break

    # -- encounter options -----------------------------------------------------
    encounter_options = []
    best_actor = None
    best_dist = 9999

    for a in game.actors:
        if a is p:
            continue
        tier = getattr(a, "tier", 1)
        is_boss = getattr(a, "is_boss", False)
        if tier < 3 and not is_boss:
            continue
        d = max(abs(px - a.x), abs(py - a.y))
        if d > 3:
            continue
        if d < best_dist:
            best_dist = d
            best_actor = a

    if best_actor is not None:
        faction = getattr(best_actor, "faction", "")
        source = getattr(best_actor, "source", "")

        if fac_sys and faction:
            if getattr(fac_sys, "standing", {}).get(faction, 0) >= 2:
                encounter_options.append("coerce")

        if know_sys and source:
            if know_sys.is_known(source):
                encounter_options.append("parley")

        if matter_total >= 2:
            encounter_options.append("flee")

        if truths_read >= 1:
            encounter_options.append("appease")

        encounter_options.append("fight")

    return {
        "vitals": vitals,
        "status": status,
        "effects": effects,
        "position": position,
        "weather_hazard": weather_hazard,
        "hostiles": hostiles_list,
        "adjacent_hostiles": adjacent_hostiles,
        "near_hostiles": near_hostiles,
        "can_becalm": can_becalm,
        "sigils": sigils_list,
        "matter": matter,
        "caches": caches_list,
        "pois": pois,
        "tension": tension,
        "noise_near": noise_near,
        "factions": factions,
        "standing_critical": standing_critical,
        "knowledge": knowledge,
        "nav": nav,
        "nearby_landmark": game.commune_landmark() is not None,
        "has_trap_near": has_trap_near,
        "faction_kills": faction_kills,
        "kills_on": kills_on,
        "recent_kill_count": recent_kill_count,
        "can_heal_meaningfully": can_heal_meaningfully,
        "rest_effective": weather_hazard is not True,
        "spawn_threat": spawn_threat,
        "spawn_allies": spawn_allies,
        "becalm_discount": becalm_discount,
        "companions": companions_list,
        "companion_penalty": companion_penalty,
        "can_recruit": can_recruit,
        "encounter_options": encounter_options,
    }
