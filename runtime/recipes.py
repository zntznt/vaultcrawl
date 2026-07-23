"""25 consumable recipes with a deterministic discovery system.

Recipes are crafted from salvaged matter via the wear module's
``register_recipe`` / ``craft_consumable`` interface. Discovery is
sourced from lore, parley, bosses, caches, terminals, and confide —
each with its own probability and theming.
"""
from __future__ import annotations

import random as _random

from runtime.components import inv
from runtime.wear import register_recipe


HEAP_MATTER = 2  # matter awarded by corpse_compost
SCARAB_HP = 6


# ── helpers ──────────────────────────────────────────────────────────────────

def _rng(seed_str: str) -> float:
    """Deterministic float 0-1 from a seed string."""
    return (hash(seed_str) % 10000) / 10000.0


def _tile_in_radius(game, r: int):
    """A random floor tile within Chebyshev radius r of the player."""
    px, py = game.player.x, game.player.y
    rng = _random.Random(f"{game.seed}:{game.turn}:radius_tile")
    candidates = []
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            tx, ty = px + dx, py + dy
            lvl = game.level
            if 0 <= tx < lvl.w and 0 <= ty < lvl.h and lvl.tiles[ty][tx] == ".":
                candidates.append((tx, ty))
    if candidates:
        return rng.choice(candidates)
    return (px, py)


def _free_at_player(game):
    """Returns True if the player's tile is free floor (no actor, no wall)."""
    lvl = game.level
    px, py = game.player.x, game.player.y
    if not (0 <= px < lvl.w and 0 <= py < lvl.h):
        return False
    if lvl.tiles[py][px] != ".":
        return False
    return True


# ── recipe 1: noise_lure ─────────────────────────────────────────────────────

def _eff_noise_lure(game):
    pos = _tile_in_radius(game, 8)
    game.emit("noise", pos=pos, volume=15)
    game.log("A sharp crack echoes from the lure.")

register_recipe("noise_lure", 2, _eff_noise_lure)


# ── recipe 2: faction_token ──────────────────────────────────────────────────

def _eff_faction_token(game):
    factions = game.system("factions")
    if factions is None:
        return
    rng = _random.Random(f"{game.seed}:{game.turn}:faction_token")
    fac_ids = [fid for fid in factions.standing if factions.standing.get(fid, 0)]
    if not fac_ids:
        fac_ids = [f["id"] for f in game.m.get("bible", {}).get("factions", [])]
    if not fac_ids:
        return
    fid = rng.choice(fac_ids)
    factions.standing[fid] = factions.standing.get(fid, 0) + 1
    name = factions.faction_name(fid)
    game.emit("standing_changed", faction=fid, standing=factions.standing[fid])
    game.log(f"The token bears the mark of {name}. (+1 standing)")

register_recipe("faction_token", 3, _eff_faction_token)


# ── recipe 3: growth_spore ───────────────────────────────────────────────────

def _eff_growth_spore(game):
    flora = game.system("flora")
    if flora is None:
        game.log("The spore drifts — but there is nothing here to grow.")
        return
    if not _free_at_player(game):
        game.log("The spore settles but finds no purchase.")
        return
    flora.plants.add((game.player.x, game.player.y))
    game.log("A plant bursts up through the floor at your feet.")

register_recipe("growth_spore", 1, _eff_growth_spore)


# ── recipe 4: scent_mask ─────────────────────────────────────────────────────

def _eff_scent_mask(game):
    scent = game.system("scent")
    if scent is None:
        return
    px, py = game.player.x, game.player.y
    cleared = 0
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            tx, ty = px + dx, py + dy
            lvl = game.level
            if 0 <= tx < lvl.w and 0 <= ty < lvl.h:
                if scent.grid.get((tx, ty), 0) > 0:
                    del scent.grid[(tx, ty)]
                    cleared += 1
    game.log(f"Your scent vanishes from {cleared} tiles. Nothing can track you.")

register_recipe("scent_mask", 2, _eff_scent_mask)


# ── recipe 5: weather_vane ───────────────────────────────────────────────────

def _eff_weather_vane(game):
    weather = game.system("weather")
    if weather is None:
        return
    old = weather.weather
    rng = _random.Random(f"{game.seed}:{game.turn}:weather_vane")
    from runtime.weather import _WEATHER
    options = [w for w in _WEATHER.values() if w != old]
    if not options:
        weather.weather = "still air"
    else:
        weather.weather = rng.choice(options)
    game.log(f"The vane spins. The {old} lifts; {weather.weather} settles in.")

register_recipe("weather_vane", 3, _eff_weather_vane)


# ── recipe 6: portal_anchor ──────────────────────────────────────────────────

def _eff_portal_anchor(game):
    portals = game.system("portals")
    if portals is None or not portals.portals:
        game.log("No gate shimmers near enough to anchor.")
        return
    px, py = game.player.x, game.player.y
    nearest = min(portals.portals.items(),
                  key=lambda kv: max(abs(kv[0][0] - px), abs(kv[0][1] - py)),
                  default=None)
    if nearest is None:
        return
    pos, p = nearest
    p["ttl"] = p.get("ttl", 0) + 200
    p["max_ttl"] = p.get("max_ttl", 0) + 200
    game.log("You drive the anchor into the gate. Its shimmer steadies, the "
             "collapse held at bay.")

register_recipe("portal_anchor", 4, _eff_portal_anchor)


# ── recipe 7: trap_kit ───────────────────────────────────────────────────────

def _eff_trap_kit(game):
    structs = game.system("structures")
    if structs is None:
        return
    pos = (game.player.x, game.player.y)
    if not _free_at_player(game):
        game.log("This ground won't hold a trap.")
        return
    structs.traps[pos] = "spike"
    game.log("You anchor a spike plate flush with the floor.")

register_recipe("trap_kit", 3, _eff_trap_kit)


# ── recipe 8: corpse_compost ─────────────────────────────────────────────────

def _eff_corpse_compost(game):
    decay = game.system("decay")
    salv = game.system("salvage")
    if decay is None:
        return
    px, py = game.player.x, game.player.y
    if not decay.corpse_at(px, py):
        game.log("There is nothing here to compost.")
        return
    decay.consume(px, py)
    if salv is not None:
        inventory = salv.inventory(game)
        rng = _random.Random(f"{game.seed}:{game.turn}:compost")
        mats = inventory.comp
        mat = rng.choice(list(mats.keys())) if mats else "scrap"
        inventory.add({mat: HEAP_MATTER})
    game.log("The corpse collapses into rich, dark matter.")

register_recipe("corpse_compost", 1, _eff_corpse_compost)


# ── recipe 9: crystal_seed ───────────────────────────────────────────────────

def _eff_crystal_seed(game):
    structs = game.system("structures")
    if structs is None:
        return
    pos = (game.player.x, game.player.y)
    if not _free_at_player(game):
        game.log("No room for a crystal to take root.")
        return
    structs.crystals[pos] = 0
    game.log("A crystal seed embeds itself in the stone. It waits.")

register_recipe("crystal_seed", 4, _eff_crystal_seed)


# ── recipe 10: beacon_fragment ────────────────────────────────────────────────

def _eff_beacon_fragment(game):
    if not hasattr(game.player, "_waypoints"):
        game.player._waypoints = {}
    pos = (game.player.x, game.player.y)
    game.player._waypoints[pos] = game.turn + 50
    game.log("The fragment anchors here. You will see it for 50 turns — "
             "a fixed star in the dark.")

register_recipe("beacon_fragment", 5, _eff_beacon_fragment)


# ── recipe 11: hush_chime ────────────────────────────────────────────────────

def _eff_hush_chime(game):
    px, py = game.player.x, game.player.y
    calmed = 0
    for a in game.actors:
        if not getattr(a, "alive", False):
            continue
        if getattr(a, "allegiance", "") != "wild":
            continue
        if max(abs(a.x - px), abs(a.y - py)) > 8:
            continue
        a.allegiance = "calmed"
        a._calmed = True
        calmed += 1
    if calmed:
        game.log(f"The chime rings; {calmed} creatures grow still.")
    else:
        game.log("The chime rings; no one is near enough to hear.")

register_recipe("hush_chime", 2, _eff_hush_chime)


# ── recipe 12: cache_decoy ───────────────────────────────────────────────────

def _eff_cache_decoy(game):
    pos = (game.player.x, game.player.y)
    if hasattr(game, "_overlay"):
        game._overlay[pos] = "□"
    game.emit("noise", pos=pos, volume=12)
    game.log("The decoy clatters to the floor. Every ear for a hundred paces "
             "must know.")

register_recipe("cache_decoy", 3, _eff_cache_decoy)


# ── recipe 13: blight_salve ──────────────────────────────────────────────────

def _eff_blight_salve(game):
    body = getattr(game.player, "body", None)
    if body is None:
        game.log("The salve finds nothing to mend.")
        return
    worn = [p for p in ("head", "torso", "legs")
            if body[p].get("hp", 0) < body[p].get("max", 1)]
    if not worn:
        game.log("Your body is whole; the salve stays dry.")
        return
    rng = _random.Random(f"{game.seed}:{game.turn}:blight_salve")
    part = rng.choice(worn)
    body[part]["hp"] = min(body[part]["hp"] + body[part]["max"] // 4,
                           body[part]["max"])
    from runtime.body_parts import sync_hp
    sync_hp(game.player)
    game.log(f"Your {part} knits under the salve.")

register_recipe("blight_salve", 2, _eff_blight_salve)


# ── recipe 14: echo_shard ────────────────────────────────────────────────────

def _eff_echo_shard(game):
    knows = game.system("knowledge")
    if knows is None:
        game.log("The shard hums, but no knowledge lingers to hold.")
        return
    nodes = game.m.get("graph", {}).get("nodes", {})
    unknown = [nid for nid in nodes if nid not in knows.known]
    if not unknown:
        game.log("You have learned all there is. The shard rests.")
        return
    rng = _random.Random(f"{game.seed}:{game.turn}:echo_shard")
    nid = rng.choice(sorted(unknown))
    knows.reveal(nid)
    title = nodes[nid].get("title", nid) if nodes else nid
    game.log(f"The shard whispers of '{title}' — a note you never touched.")

register_recipe("echo_shard", 3, _eff_echo_shard)


# ── recipe 15: root_tendril ──────────────────────────────────────────────────

def _eff_root_tendril(game):
    reactions = game.system("reactions")
    if reactions is None:
        game.log("The tendril writhes, but no hazard answers it.")
        return
    px, py = game.player.x, game.player.y
    lvl = game.level
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        tx, ty = px + dx, py + dy
        if not (0 <= tx < lvl.w and 0 <= ty < lvl.h):
            continue
        if lvl.tiles[ty][tx] != ".":
            continue
        if reactions.is_hazard(tx, ty):
            reactions.clear_prop(tx, ty, "acid")
            reactions.clear_prop(tx, ty, "fire")
            reactions.clear_prop(tx, ty, "wet")
            reactions.clear_prop(tx, ty, "charged")
            if not hasattr(game, "_tendril_bridges"):
                game._tendril_bridges = {}
            game._tendril_bridges[(tx, ty)] = game.turn + 10
            game.log("The tendril weaves across the hazard — a span of 10 turns.")
            return
    game.log("The tendril probes but finds no hazard to bridge.")

register_recipe("root_tendril", 2, _eff_root_tendril)


# ── recipe 16: scarab_charm ──────────────────────────────────────────────────

def _eff_scarab_charm(game):
    from runtime.entities import make_critter
    rng = _random.Random(f"{game.seed}:{game.turn}:scarab")
    px, py = game.player.x, game.player.y
    lvl = game.level
    free = []
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            tx, ty = px + dx, py + dy
            if (0 <= tx < lvl.w and 0 <= ty < lvl.h
                    and lvl.tiles[ty][tx] == "."
                    and game.actor_at(tx, ty) is None
                    and (tx, ty) != (px, py)):
                free.append((tx, ty))
    if not free:
        free = [(px, py)]
    tx, ty = rng.choice(free)
    scarab = make_critter("scavenger", tx, ty)
    scarab.allegiance = "companion"
    scarab.name = "scarab"
    scarab.glyph = "o"
    scarab.hp = SCARAB_HP
    scarab.max_hp = SCARAB_HP
    scarab.atk = 1
    scarab._companion = True
    scarab._scarab = True
    game.actors.append(scarab)
    game.log("A scarab crawls out of the charm and looks up at you.")

register_recipe("scarab_charm", 4, _eff_scarab_charm)


# ── recipe 17: frost_ampoule ──────────────────────────────────────────────────

def _eff_frost_ampoule(game):
    reactions = game.system("reactions")
    if reactions is None:
        game.log("The ampoule shatters — nothing to freeze.")
        return
    px, py = game.player.x, game.player.y
    lvl = game.level
    count = 0
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            tx, ty = px + dx, py + dy
            if not (0 <= tx < lvl.w and 0 <= ty < lvl.h):
                continue
            if lvl.tiles[ty][tx] != ".":
                continue
            props = reactions.props_at(tx, ty)
            if "acid" in props or "wet" in props:
                reactions.clear_prop(tx, ty, "acid")
                reactions.clear_prop(tx, ty, "wet")
                reactions.add_prop(tx, ty, "ice")
                count += 1
            else:
                reactions.add_prop(tx, ty, "ice")
    if not hasattr(game, "_frost_tiles"):
        game._frost_tiles = {}
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            tx, ty = px + dx, py + dy
            if 0 <= tx < lvl.w and 0 <= ty < lvl.h and lvl.tiles[ty][tx] == ".":
                game._frost_tiles[(tx, ty)] = game.turn + 10
    game.log(f"The ampoule shatters. A 3x3 freeze spreads — {count} tiles "
             f"hardened to ice.")

register_recipe("frost_ampoule", 3, _eff_frost_ampoule)


# ── recipe 18: memory_dust ───────────────────────────────────────────────────

def _eff_memory_dust(game):
    px, py = game.player.x, game.player.y
    nearest = None
    nearest_dist = 999
    for a in game.actors:
        if not getattr(a, "alive", False):
            continue
        if getattr(a, "is_player", False):
            continue
        if getattr(a, "allegiance", "") in ("npc", "companion", "calmed"):
            continue
        d = max(abs(a.x - px), abs(a.y - py))
        if d < nearest_dist:
            nearest = a
            nearest_dist = d
    if nearest is None:
        game.log("The dust swirls — no one here to forget.")
        return
    from runtime.memory import Memory
    nearest._mem = Memory()
    game.log(f"{nearest.name} blinks, confused. It has forgotten why it is here.")

register_recipe("memory_dust", 2, _eff_memory_dust)


# ── recipe 19: sparkwire ──────────────────────────────────────────────────────

def _eff_sparkwire(game):
    reactions = game.system("reactions")
    if reactions is None:
        game.log("No substrate for the spark to cross.")
        return
    px, py = game.player.x, game.player.y
    lvl = game.level
    charged_tiles = []
    for dx in range(-5, 6):
        for dy in range(-5, 6):
            tx, ty = px + dx, py + dy
            if not (0 <= tx < lvl.w and 0 <= ty < lvl.h):
                continue
            if lvl.tiles[ty][tx] != ".":
                continue
            if "charged" in reactions.props_at(tx, ty):
                charged_tiles.append((tx, ty))
    if len(charged_tiles) < 2:
        game.log("The wire crackles, but needs two charged tiles to arc.")
        return
    rng = _random.Random(f"{game.seed}:{game.turn}:sparkwire")
    a = rng.choice(charged_tiles)
    b = a
    while b == a:
        b = rng.choice(charged_tiles)
    # 3 damage to any actor standing on or adjacent to the arc path
    arc_tiles = set()
    arc_tiles.add(a)
    arc_tiles.add(b)
    mid_x = (a[0] + b[0]) // 2
    mid_y = (a[1] + b[1]) // 2
    arc_tiles.add((mid_x, mid_y))
    hit = 0
    for actor in game.actors:
        if not getattr(actor, "alive", False):
            continue
        if (actor.x, actor.y) in arc_tiles:
            actor.hp = max(0, actor.hp - 3)
            hit += 1
            if actor.hp <= 0 and not actor.is_player:
                game.kill(actor, "sparkwire")
    if (game.player.x, game.player.y) in arc_tiles:
        game.player.hp = max(0, game.player.hp - 3)
        hit += 1
        if game.player.hp <= 0:
            game.alive = False
            game.log("The arc courses through you. You fall.")
            return
    game.log(f"An arc leaps between charged tiles — {hit} caught in the flash.")

register_recipe("sparkwire", 3, _eff_sparkwire)


# ── recipe 20: lantern_oil ────────────────────────────────────────────────────

def _eff_lantern_oil(game):
    effects = game.system("effects")
    if effects is None or not effects.worn_is("lantern"):
        game.log("The oil can only feed a worn lantern effect.")
        return
    cur = getattr(game.player, "_lantern_duration", 0)
    game.player._lantern_duration = cur + 30
    game.log("Your lantern burns brighter. (+30 turns)")

register_recipe("lantern_oil", 1, _eff_lantern_oil)


# ── recipe 21: wardstone ──────────────────────────────────────────────────────

def _eff_wardstone(game):
    pos = (game.player.x, game.player.y)
    if not hasattr(game, "_warded_tiles"):
        game._warded_tiles = {}
    game._warded_tiles[pos] = game.turn + 10
    game.log("The wardstone anchors here. Enemies will route around this tile "
             "for 10 turns.")

register_recipe("wardstone", 3, _eff_wardstone)


# ── recipe 22: prophecy_ink ──────────────────────────────────────────────────

def _eff_prophecy_ink(game):
    regions = game.m.get("regions", [])
    ahead = [r for r in regions if r.get("depthBand", [1, 1])[0] > game.floor]
    if not ahead:
        game.log("No region lies ahead to scry.")
        return
    nxt = min(ahead, key=lambda r: r["depthBand"][0])
    region_name = nxt.get("name", "an unknown region")
    element = nxt.get("element", "inert")
    boss_source = ""
    bosses = game.m.get("bosses", [])
    for b in bosses:
        b_region = None
        for r in regions:
            if r.get("sourceNoteId") == b.get("sourceNoteId"):
                b_region = r
                break
        if b_region and b_region.get("id") == nxt.get("id"):
            boss_source = b.get("sourceNoteId", "")
            break
    boss_name = ""
    if boss_source:
        node = game.m.get("graph", {}).get("nodes", {}).get(boss_source, {})
        boss_name = node.get("title", boss_source) if node else boss_source
    game.log(f"The ink writes: {region_name}. "
             f"{'Its keeper: ' + boss_name + '. ' if boss_name else ''}"
             f"The air is {element}.")

register_recipe("prophecy_ink", 4, _eff_prophecy_ink)


# ── recipe 23: graft_patch ────────────────────────────────────────────────────

def _eff_graft_patch(game):
    game.player._graft_ward = game.turn + 30
    game.log("Your grafts lock tight. No wear for 30 turns.")

register_recipe("graft_patch", 3, _eff_graft_patch)


# ── recipe 24: brewers_yeast ──────────────────────────────────────────────────

def _eff_brewers_yeast(game):
    salv = game.system("salvage")
    if salv is None:
        return
    bag = salv.inventory(game)
    if not bag.comp or len(bag.comp) < 2:
        game.log("You need at least two materials to brew.")
        return
    richest = max(bag.comp, key=lambda k: bag.comp[k])
    poorest = min(bag.comp, key=lambda k: bag.comp[k])
    if richest == poorest:
        game.log("Only one material type; nothing to transmute.")
        return
    take = min(bag.comp[richest], 3)
    bag.comp[richest] -= take
    if bag.comp[richest] <= 0:
        del bag.comp[richest]
    bag.comp[poorest] = bag.comp.get(poorest, 0) + take
    game.log(f"The yeast works: {take} {richest} becomes {poorest}.")

register_recipe("brewers_yeast", 2, _eff_brewers_yeast)


# ── recipe 25: kinship_bond ───────────────────────────────────────────────────

def _eff_kinship_bond(game):
    factions = game.system("factions")
    if factions is None:
        return
    region = game.region_for(game.floor)
    fid = region.get("factionId", "")
    if not fid:
        game.log("No faction claims this place.")
        return
    if not hasattr(game.player, "_kinship_duration"):
        game.player._kinship_duration = {}
    game.player._kinship_duration[fid] = game.turn + 20
    name = factions.faction_name(fid)
    game.log(f"You wear the token of {name}. They will treat you as neutral "
             f"for 20 turns.")

register_recipe("kinship_bond", 5, _eff_kinship_bond)


# ═══════════════════════════════════════════════════════════════════════════════
# Discovery system
# ═══════════════════════════════════════════════════════════════════════════════

_ALL_RECIPE_NAMES = [

    "noise_lure", "faction_token", "growth_spore", "scent_mask",
    "weather_vane", "portal_anchor", "trap_kit", "corpse_compost",
    "crystal_seed", "beacon_fragment", "hush_chime", "cache_decoy",
    "blight_salve", "echo_shard", "root_tendril", "scarab_charm",
    "frost_ampoule", "memory_dust", "sparkwire", "lantern_oil",
    "wardstone", "prophecy_ink", "graft_patch", "brewers_yeast",
    "kinship_bond",
]


def _pick_undiscovered(game, seed_tag: str) -> str | None:
    known = getattr(game.player, "_known_recipes", set())
    undiscovered = [r for r in _ALL_RECIPE_NAMES if r not in known]
    if not undiscovered:
        return None
    choice = _rng(f"{game.seed}:{game.turn}:recipe_pick:{seed_tag}")
    idx = int(choice * len(undiscovered)) % len(undiscovered)
    recipe = undiscovered[idx]
    if not hasattr(game.player, "_known_recipes"):
        game.player._known_recipes = set()
    game.player._known_recipes.add(recipe)
    return recipe


def _scholar_bonus(game) -> float:
    from runtime.proficiency import skills as _skills
    return _skills().tier("scholarship") * 0.02


# ── discovery sources ────────────────────────────────────────────────────────

def discover_from_lore(game) -> str | None:
    if _rng(f"{game.seed}:{game.turn}:lore_recipe") < 0.10:
        return _pick_undiscovered(game, "lore")
    return None


def discover_from_parley(game) -> str | None:
    parleys = getattr(game, "_total_parleys", 0)
    base = 0.15 + _scholar_bonus(game)
    if _rng(f"{game.seed}:{parleys}:parley_recipe") < base:
        return _pick_undiscovered(game, "parley")
    return None


def discover_from_boss(game) -> str | None:
    if _rng(f"{game.seed}:{game.turn}:boss_recipe") < 0.30:
        return _pick_undiscovered(game, "boss")
    return None


def discover_from_cache(game) -> str | None:
    searched = getattr(game.system("caches"), "searched", 0) if game.system("caches") else 0
    base = 0.12 + _scholar_bonus(game)
    if _rng(f"{game.seed}:{searched}:cache_recipe") < base:
        return _pick_undiscovered(game, "cache")
    return None


def discover_from_terminal(game) -> str | None:
    terminals = getattr(game.system("machines"), "terminals", set()) if game.system("machines") else set()
    base = 0.20 + _scholar_bonus(game)
    if _rng(f"{game.seed}:{len(terminals)}:terminal_recipe") < base:
        return _pick_undiscovered(game, "terminal")
    return None


def discover_from_confide(game) -> str | None:
    truths = getattr(game, "_truths_spent", 0)
    base = 0.18 + _scholar_bonus(game)
    if _rng(f"{game.seed}:{truths}:confide_recipe") < base:
        return _pick_undiscovered(game, "confide")
    return None
