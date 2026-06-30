"""Cross-system SHOWCASE for vaultcrawl.

The five systems (reactions, factions, knowledge, sigils, history) run over a
single event bus (`game.emit` / `System.on_event`) plus a small query API
(`game.system(name)` -> `reveal/is_known/is_hazard/props_at/faction_of/...`).
This script proves they actually COMPOSE: the output of one system becomes the
input of another, producing Qud/Cogmind-style emergence.

The dumb auto-player can never line these conditions up, so each set-piece
constructs the situation directly on a fresh `Game`, runs the real code path,
and prints a before->after with a checkmark verdict computed from live state.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m runtime.scenario
"""
from __future__ import annotations

import sys
import traceback

from runtime.game import Game, load_manifest
from runtime.dungeon import free_floor_tiles
from runtime.entities import Actor
from runtime.sigils import SigilSystem
from runtime.reactions import ReactionSystem
from runtime.factions import FactionSystem
from runtime.history import HistorySystem
from runtime.knowledge import KnowledgeSystem

MANIFEST = "examples/world.json"
OK, NO = "✓", "✗"   # checkmark / cross


# ---------------------------------------------------------------- helpers ----
def build() -> Game:
    """Fresh, fully-wired world. Canonical order: sigils first (Echo can revive
    a just-killed player), knowledge last (its fog paints over every overlay)."""
    return Game(load_manifest(MANIFEST),
                systems=[SigilSystem(), ReactionSystem(), FactionSystem(),
                         HistorySystem(), KnowledgeSystem()])


def enemy(x, y, name, source, hp=20, tier=1) -> Actor:
    """A plain non-player, non-boss actor with a real `source` note so the
    affinity/faction lookups resolve exactly as they do in normal play."""
    a = Actor(x=x, y=y, glyph="?", name=name, hp=hp, max_hp=hp, atk=1,
              tier=tier, source=source)
    a.is_player = False
    a.is_boss = False
    return a


def free(game, extra=()):
    ex = {(game.player.x, game.player.y), game.level.stairs} | set(extra)
    return free_floor_tiles(game.level, ex)


def h_run(level, n):
    """Top-left of the first run of `n` horizontal floor tiles (a clean lane)."""
    for y in range(level.h):
        for x in range(level.w - n):
            if all(level.tiles[y][x + i] == "." for i in range(n)):
                return x, y
    raise RuntimeError("no horizontal floor run found")


def anchor_for(game, region_id):
    if not region_id:
        return None
    for r in game.m["regions"]:
        if r["id"] == region_id:
            return r.get("sourceNoteId")
    return None


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
def sp1_loud_vs_quiet():
    header(1, "Loud vs quiet kill  (reactions x factions)")
    g = build()
    react, fac = g.system("reactions"), g.system("factions")
    src = "stoicism"                       # note in community 0 -> faction_0
    fid = fac.faction_of(src)              # public query API
    print("   A melee kill is HEARD and raises the faction's alert; luring a")
    print("   creature onto a hazard kills it UNSEEN, so the alert never rises")
    print(f"   (and even cools). Tracking {fac.faction_name(fid)} ({fid}).")

    g.actors, react.props, react.fire_life = [], {}, {}
    spots = free(g)
    g.player.x, g.player.y = spots[0]
    d0 = fac.disturbance.get(fid, 0)

    print(f"\n   [LOUD]  game.emit(enemy_killed, cause='melee')   disturbance={d0}")
    s = len(g.messages)
    g.emit("enemy_killed", enemy=enemy(0, 0, "Annotated Warden", src), cause="melee")
    show_logs(g, s)
    d1 = fac.disturbance.get(fid, 0)
    print(f"           -> disturbance={d1}")

    fx, fy = spots[-1]
    react.props[(fx, fy)] = {"fire"}       # poke a hazard tile under a weak foe
    victim = enemy(fx, fy, "Quiet Echo", src, hp=1)
    g.actors = [victim]
    print(f"\n   [QUIET] foe on a fire tile, run the reactions tick")
    print(f"           reactions emits enemy_killed(cause='environment') on the bus")
    s = len(g.messages)
    react.on_player_act(g)                 # real path: tick -> emit -> factions
    show_logs(g, s)
    d2 = fac.disturbance.get(fid, 0)
    print(f"           -> disturbance={d2}")

    ok = d1 > d0 and d2 <= d0 and victim not in g.actors
    return verdict(ok, f"melee raised alert {d0}->{d1}; environment did not "
                       f"({d1}->{d2}, decayed) — loud alerts, quiet doesn't.")


def sp2_ward_shove():
    header(2, "Ward shove-to-kill  (sigils x reactions)")
    g = build()
    react, sig = g.system("reactions"), g.system("sigils")
    g.actors, react.props, react.fire_life = [], {}, {}
    x, y = h_run(g.level, 3)               # lane: (x,y) (x+1,y) (x+2,y)
    g.player.x, g.player.y = x, y
    a = enemy(x + 1, y, "Hollow Construct", "rust")
    b = enemy(x - 1, y, "Patient Scribe", "rust")
    g.actors = [a, b]
    react.props[(x + 2, y)] = {"acid"}     # hazard exactly where Ward will shove
    sig.slots = [{"note": "memento mori", "role": "leaf",
                  "ability": "Ward", "durability": 2}]
    print("   Pinned by two adjacent foes, the Ward doesn't merely push them away —")
    print("   it shoves one ONTO an acid tile so reactions does the killing next tick.")
    print(f"   Before: {a.name} at {(a.x, a.y)}; acid tile at {(x + 2, y)}.")

    s = len(g.messages)
    sig.on_player_act(g)                   # real Ward path (sigils -> reactions.is_hazard)
    show_logs(g, s)
    moved = (a.x, a.y) == (x + 2, y)
    on_haz = "acid" in react.props_at(a.x, a.y)
    shoved = any("ward shoves" in m.lower() for m in g.messages[s:])
    print(f"   After:  {a.name} at {(a.x, a.y)}  (sitting on hazard: {on_haz})")
    return verdict(moved and on_haz and shoved,
                   f"Ward shoved {a.name} onto the acid tile; reactions owns the kill.")


def sp3_em_corruption():
    header(3, "EM corruption frays sigils  (sigils x reactions)")
    g = build()
    react, sig = g.system("reactions"), g.system("sigils")
    g.actors, react.props = [], {}
    px, py = g.player.x, g.player.y
    react.props[(px, py)] = {"charged"}    # charged field under the player
    sig.slots = [{"note": "rust", "role": "hub", "ability": "Recall", "durability": 2}]
    d0 = sig.slots[0]["durability"]
    print("   Standing in a charged field, EM noise corrupts your configuration:")
    print("   a slotted sigil loses durability (and shatters that much sooner).")
    print(f"   Before: Recall durability = {d0}; charged tile under player {(px, py)}.")

    s = len(g.messages)
    sig.on_player_act(g)                   # real path: sigils reads reactions.props_at
    show_logs(g, s)
    d1 = sig.slots[0]["durability"] if sig.slots else 0
    frayed = any("em corruption frays" in m.lower() for m in g.messages[s:])
    print(f"   After:  Recall durability = {d1}")
    return verdict(d1 == d0 - 1 and frayed,
                   f"charged tile drained 1 durability ({d0}->{d1}) via reactions.props_at.")


def sp4_lore_reveals():
    header(4, "Lore reveals the map  (history x knowledge)")
    g = build()
    hist, kn = g.system("history"), g.system("knowledge")
    # choose a boss/secret fragment whose region knowledge has NOT mapped yet
    idx = anchor = rid = None
    for i, item in enumerate(hist._knowledge):
        _note, r = hist._lore_target(g, item)
        a = anchor_for(g, r)
        if a and not kn.is_known(a):
            idx, anchor, rid = i, a, r
            break
    if idx is None:
        return verdict(False, "no unmapped boss/secret region available")

    print("   A buried fragment names a boss in a region you've never mapped.")
    print("   Reading it (history) emits lore_read; knowledge reveals that region.")
    before = kn.is_known(anchor)           # public query API
    print(f"   Target {rid!r} (anchor {anchor!r}); is_known before = {before}")

    hist.ground[(g.player.x, g.player.y)] = "An elder project overgrew its bounds."
    hist._kidx = idx                       # aim the next revelation at our target
    s = len(g.messages)
    hist.on_player_act(g)                  # real read path -> emit('lore_read', ...)
    show_logs(g, s)
    after = kn.is_known(anchor)
    print(f"   is_known after = {after}")
    return verdict((not before) and after,
                   f"reading lore flipped knowledge.is_known({anchor!r}) False->True.")


def sp5_hunter_intel():
    header(5, "Hunter intel  (factions x knowledge)")
    g = build()
    fac, kn = g.system("factions"), g.system("knowledge")
    region = g.region_for(g.floor)
    anchor, rid = region["sourceNoteId"], region["id"]
    fname = fac.faction_name(region.get("factionId"))
    print("   A provoked faction dispatches a Hunter. Kill it LOUD and the faction")
    print("   scavenges its sensors, handing the floor's survey to knowledge via")
    print("   knowledge.reveal(current_region).")

    kn.known = set()                       # reset fog so the reveal is visible
    before = kn.is_known(anchor)
    hunter = enemy(5, 5, f"Hunter of {fname}", anchor, hp=30, tier=3)
    hunter.is_hunter = True                # flagged exactly like a spawned hunter
    print(f"   Before: is_known({anchor!r}) = {before}  (fog reset)")

    s = len(g.messages)
    g.emit("enemy_killed", enemy=hunter, cause="melee")
    show_logs(g, s)
    after = kn.is_known(anchor)
    intel = any("strip the hunter" in m.lower() for m in g.messages[s:])
    print(f"   After:  is_known({anchor!r}) = {after}")
    return verdict((not before) and after and intel,
                   "loud hunter kill scavenged sensors; knowledge mapped the floor.")


def sp6_affinity():
    header(6, "Elemental affinity  (reactions)")
    g = build()
    react = g.system("reactions")
    g.actors, react.props, react.fire_life = [], {}, {}
    rx, ry = h_run(g.level, 4)
    wet, charged = (rx, ry), (rx + 1, ry)  # adjacent -> a LIVE chain-shock
    react.props[wet] = {"wet"}
    react.props[charged] = {"charged"}
    acid = next(p for p in free(g, extra=[wet, charged]))
    react.props[acid] = {"acid"}
    g.player.x, g.player.y = next(p for p in free(g, extra=[wet, charged, acid]))

    e_cor = enemy(acid[0], acid[1], "Gilded Shade", "stoicism", hp=40)  # home corrosive
    e_chg = enemy(wet[0], wet[1], "Brimming Echo", "rust", hp=40)       # home charged
    g.actors = [e_cor, e_chg]
    m_imm = react._affinity(react._enemy_home_element(g, e_cor), "corrosive")
    m_weak = react._affinity(react._enemy_home_element(g, e_chg), "wet")
    print("   An enemy is IMMUNE to its own region's element and takes DOUBLE from")
    print("   the opposite. Corrosive native on acid (own); charged native on a live")
    print("   wet tile (charged's opposite).")
    print(f"   Multipliers: corrosive-on-acid = {m_imm}x   charged-on-wet = {m_weak}x")

    c0, h0 = e_cor.hp, e_chg.hp
    react.on_player_act(g)                 # real tick applies affinity-scaled damage
    cd, hd = c0 - e_cor.hp, h0 - e_chg.hp
    print(f"   Damage taken: corrosive native = {cd}   charged native = {hd}")
    return verdict(m_imm == 0 and m_weak == 2 and cd == 0 and hd >= 2,
                   f"own element 0x (took {cd}); opposite 2x (took {hd}).")


# -------------------------------------------------------------------- main ----
def main():
    print("VAULTCRAWL — CROSS-SYSTEM INTERACTION SHOWCASE")
    print("Five systems, one event bus. Each set-piece constructs an emergent")
    print("situation the auto-player can't reach and verifies it from live state.")
    pieces = [sp1_loud_vs_quiet, sp2_ward_shove, sp3_em_corruption,
              sp4_lore_reveals, sp5_hunter_intel, sp6_affinity]
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
        print("OVERALL: PASS — all six cross-system interactions verified.")
        return 0
    print("OVERALL: FAIL — see set-pieces marked above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
