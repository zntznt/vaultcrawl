"""SHOWCASE for vaultcrawl's salvage / inventory / forge layer.

The premise, in one line: *everything breaks into the world's own materials, and you can
rebuild from the matter.* A world's matter vocabulary IS the words its bible coined
(`world_materials` -> the `aesthetic` list); `components_of(...)` deterministically breaks any
thing — a fallen creature, a shattered sigil, a detonated crystal, a salvaged item — into a
handful of those materials. Three systems close the Cogmind-style loop over the event bus:

    SHATTER  (sigils.py emits `broke`; game.py emits `actor_died`)
       -> SALVAGE  (SalvageSystem scatters `components_of(...)` on the ground; standing on it
                    pours it into the player's persistent Inventory)
       -> FORGE    (ForgeSystem spends matter to re-craft one of the five utility sigils)

The dumb auto-player can never line these up, so each set-piece builds the situation directly
on a FRESH fully-wired `Game`, runs the real code path, and prints a before->after with a
checkmark verdict computed from LIVE state. Deterministic (`components_of` is a pure hash;
collection is positional; no clock / rng of our own).

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m runtime.salvage_scenario
"""
from __future__ import annotations

import sys
import traceback

from runtime.game import Game, load_manifest
from runtime.dungeon import free_floor_tiles
from runtime.entities import make_enemy
from runtime.components import components_of, world_materials, inv

# import the systems so they exist to register (and so this script documents the wiring)
from runtime.sigils import SigilSystem
from runtime.reactions import ReactionSystem
from runtime.salvage import SalvageSystem
from runtime.forge import ForgeSystem

MANIFEST = "examples/world.json"
OK, NO = "✓", "✗"   # checkmark / cross


# ---------------------------------------------------------------- helpers ----
def build() -> Game:
    """A fresh, fully-wired world for every set-piece. Sigils first (they emit `broke`),
    then reactions (charged-field partner), then salvage (collects matter), then forge
    (spends it) — the matter cycle reads left to right."""
    return Game(load_manifest(MANIFEST),
                systems=[SigilSystem(), ReactionSystem(), SalvageSystem(), ForgeSystem()])


def free(game, extra=()):
    """Open floor tiles, excluding the player, the stairs, every actor/item, and any extras
    — a deterministic clean lane to stage drops on (top-left first)."""
    ex = {(game.player.x, game.player.y), game.level.stairs}
    ex |= {(a.x, a.y) for a in game.actors}
    ex |= {(it.x, it.y) for it in game.items}
    ex |= set(extra)
    return free_floor_tiles(game.level, ex)


def header(n, title):
    print("\n" + "=" * 74)
    print(f"SET-PIECE {n}: {title}")
    print("-" * 74)


def show_logs(game, start, indent="   | "):
    for m in game.messages[start:]:
        print(indent + str(m))


def verdict(ok, text):
    print(f"   {OK if ok else NO} {text}")
    return bool(ok)


# ------------------------------------------------------------- set-pieces ----
def sp1_everything_breaks():
    header(1, "Everything breaks into the world's materials  (components)")
    g = build()
    mats = world_materials(g)
    matset = set(mats)
    print("   A world's matter IS its bible vocabulary. components_of breaks any thing into")
    print(f"   a handful of exactly those words. World vocabulary: {mats}")

    en = g.m["enemies"][0]            # a real creature spec
    it = g.m["items"][0]              # a real item spec
    breakdowns = {
        "creature": components_of(g, kind="creature", source=en["sourceNoteId"],
                                  tier=en["tier"], name=en["name"]),
        "sigil   ": components_of(g, kind="sigil", source="memento mori", name="Ward"),
        "crystal ": components_of(g, kind="crystal", source="", name="crystal", tier=2),
        "item    ": components_of(g, kind="item", source=it["sourceNoteId"], name=it["name"]),
    }
    yielded = set()
    print()
    for label, comps in breakdowns.items():
        yielded |= set(comps)
        stray = set(comps) - matset
        flag = "" if not stray else f"   <-- STRAY {sorted(stray)}"
        print(f"   {label} -> {comps}{flag}")

    all_nonempty = all(breakdowns.values())
    all_in_vocab = yielded <= matset
    ok = all_nonempty and all_in_vocab
    return verdict(ok, f"every yielded material {sorted(yielded)} is in the world's own "
                       f"vocabulary (none invented); all four break into matter.")


def sp2_death_to_inventory():
    header(2, "Death -> salvage -> inventory  (actor_died on the bus)")
    g = build()
    sal = g.system("salvage")
    spot = free(g)[0]
    spec = g.m["enemies"][0]
    foe = make_enemy(spec, *spot)
    print(f"   A {foe.name} (tier {foe.tier}) falls at {spot}. The bus carries actor_died;")
    print("   salvage scatters its matter on that tile. Walk onto it and it's yours.")

    m0 = sal.matter(g)
    print(f"\n   Before: matter carried = {m0}; ground salvage tiles = {len(sal.ground)}")
    s = len(g.messages)
    g.emit("actor_died", actor=foe, cause="melee", pos=spot)
    dropped = sal.ground.get(spot)
    tile_exists = bool(dropped)
    print(f"   emit(actor_died, pos={spot}) -> ground[{spot}] = {dropped}")

    g.player.x, g.player.y = spot          # stand on the salvage
    sal.on_player_act(g)                   # real collection path
    show_logs(g, s)
    m1 = sal.matter(g)
    cleared = spot not in sal.ground
    print(f"   After:  matter carried = {m1}; tile cleared = {cleared}")
    ok = tile_exists and m1 > m0 and cleared
    return verdict(ok, f"death dropped salvage; collecting grew inventory {m0}->{m1} and the "
                       f"tile cleared.")


def sp3_shatter_to_salvage():
    header(3, "Shatter -> salvage  (broke on the bus)")
    g = build()
    sal = g.system("salvage")
    spot = free(g)[0]
    note = "memento mori"             # the Ward sigil's source note (a leaf node)
    expected = components_of(g, kind="sigil", source=note, tier=1, name="Ward")
    print("   When a sigil shatters, sigils.py emits broke(kind='sigil'). Salvage turns the")
    print("   shards into that sigil's OWN matter and drops them where it broke.")
    print(f"   A Ward sigil of {note!r} breaks down to {expected}.")

    s = len(g.messages)
    g.emit("broke", kind="sigil", source=note, name="Ward", tier=1, pos=spot)
    got = sal.ground.get(spot)
    show_logs(g, s)
    print(f"   ground[{spot}] = {got}")
    ok = bool(got) and got == expected
    return verdict(ok, f"broke(sigil 'Ward') dropped salvage carrying that sigil's matter "
                       f"{expected} at {spot}.")


def sp4_breakdown():
    header(4, "Breakdown  (melt a slotted sigil back into matter)")
    g = build()
    sal, sig = g.system("salvage"), g.system("sigils")
    sig.slots = [{"note": "memento mori", "role": "leaf",
                  "ability": "Ward", "durability": 2}]
    print("   A player command: voluntarily melt a slotted sigil. The slot frees and its")
    print("   matter pours straight into your inventory — feedstock for the forge.")
    slots0, m0 = len(sig.slots), sal.matter(g)
    print(f"\n   Before: slots = {slots0} ({[s['ability'] for s in sig.slots]}); matter = {m0}")

    s = len(g.messages)
    comps = sal.breakdown_sigil(g)         # ability=None -> the first slotted sigil
    show_logs(g, s)
    slots1, m1 = len(sig.slots), sal.matter(g)
    print(f"   breakdown_sigil() -> {comps}")
    print(f"   After:  slots = {slots1}; matter = {m1}")
    ok = bool(comps) and slots1 == slots0 - 1 and m1 == m0 + sum(comps.values()) and m1 > m0
    return verdict(ok, f"breakdown freed the slot ({slots0}->{slots1}) and added its matter "
                       f"({m0}->{m1}).")


def sp5_forge_closes_loop():
    header(5, "Forge closes the loop  (shatter -> salvage -> forge, one cycle)")
    g = build()
    sal, sig, frg = g.system("salvage"), g.system("sigils"), g.system("forge")
    note = "memento mori"
    print("   The whole cycle in one breath: a Ward sigil SHATTERS, its shards SALVAGE into")
    print("   matter, and once you've banked enough you FORGE a fresh Ward — power recovered")
    print("   with zero stat creep (it's still just one utility verb).")

    # --- beat 1: SHATTER ---------------------------------------------------
    spot = free(g)[0]
    s = len(g.messages)
    g.emit("broke", kind="sigil", source=note, name="Ward", tier=1, pos=spot)
    shattered = bool(sal.ground.get(spot))
    print(f"\n   [SHATTER] broke(sigil 'Ward') -> ground[{spot}] = {sal.ground.get(spot)}")

    # --- beat 2: SALVAGE ---------------------------------------------------
    g.player.x, g.player.y = spot
    sal.on_player_act(g)
    m_salvaged = sal.matter(g)
    print(f"   [SALVAGE] stood on the shards -> matter carried = {m_salvaged}")
    # a run banks matter from many kills/shatters; top up to a craftable reserve
    inv(g.player).add({"brass": 6})
    print(f"   ...banking more salvage from across the run -> matter = {sal.matter(g)}")

    # --- beat 3: FORGE -----------------------------------------------------
    slots0 = len(sig.slots)
    cost = frg.cost(g)                 # public cost model: _COST total, most-abundant first
    spend = sum(cost.values())
    m_before = sal.matter(g)
    s = len(g.messages)
    crafted = frg.forge(g, "Ward")     # real craft path
    show_logs(g, s)
    slots1 = len(sig.slots)
    m_after = sal.matter(g)
    has_ward = any(x["ability"] == "Ward" for x in sig.slots)
    print(f"   [FORGE]   cost = {cost} ({spend} matter); slots {slots0}->{slots1}; "
          f"matter {m_before}->{m_after}")
    ok = (shattered and m_salvaged > 0 and crafted and has_ward
          and slots1 == slots0 + 1 and (m_before - m_after) == spend)
    return verdict(ok, f"shatter dropped salvage, salvage fed the pool, forge re-crafted a "
                       f"Ward: slots +1 and matter -{spend} (the loop closed).")


def sp6_inventory_persists():
    header(6, "Inventory persists, ground is per-floor  (on_floor_enter)")
    g = build()
    sal = g.system("salvage")
    inv(g.player).add({"brass": 5})        # matter you carry between floors
    spot = free(g)[0]
    g.emit("broke", kind="crystal", source="", name="crystal", tier=2, pos=spot)
    carried0, ground0 = sal.matter(g), len(sal.ground)
    print("   Descending a floor wipes the ground clean (this floor's spilled matter is gone)")
    print("   but the matter you CARRY is bound to you and crosses the threshold intact.")
    print(f"\n   Before: matter carried = {carried0}; ground salvage tiles = {ground0}")

    sal.on_floor_enter(g)                  # the per-floor reset
    carried1, ground1 = sal.matter(g), len(sal.ground)
    print(f"   on_floor_enter() ...")
    print(f"   After:  matter carried = {carried1}; ground salvage tiles = {ground1}")
    ok = ground0 >= 1 and ground1 == 0 and carried1 == carried0
    return verdict(ok, f"ground salvage cleared ({ground0}->{ground1}) while carried matter "
                       f"persisted ({carried0}->{carried1}).")


# -------------------------------------------------------------------- main ----
def main():
    print("VAULTCRAWL — SALVAGE / INVENTORY / FORGE SHOWCASE")
    print("Everything breaks into the world's own materials, and you can rebuild from the")
    print("matter. Each set-piece stages the situation on a fresh world and verifies it live.")
    pieces = [sp1_everything_breaks, sp2_death_to_inventory, sp3_shatter_to_salvage,
              sp4_breakdown, sp5_forge_closes_loop, sp6_inventory_persists]
    results = []
    for fn in pieces:
        try:
            results.append(fn())
        except Exception:
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 74)
    line = "  ".join((OK if r else NO) + str(i + 1) for i, r in enumerate(results))
    print(f"VERDICTS: {line}    ({sum(results)}/{len(results)} passed)")
    if all(results):
        print("OVERALL: PASS — shatter -> salvage -> forge verified end to end.")
        return 0
    print("OVERALL: FAIL — see set-pieces marked above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
