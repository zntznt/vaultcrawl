"""Narrated SHOWCASE for vaultcrawl's social / objective / machine layer.

Three new systems sit on the same event bus + query API the rest of the runtime
uses (`game.emit` / `System.on_event`, `game.system(name)`):

  - quests   — your unfinished `- [ ]` TODOs become checkable dungeon objectives;
  - dialogue — note-derived neutral Keepers (`P`) you *parley* with, never fight;
  - machines — single-use Fabricators (`F`) and Terminals (`T`) seeded on each floor.

This script proves they COMPOSE with the existing matter / faction / knowledge
economies: an offering spends salvaged matter for standing + a map; a completed
charge pays out a faction boon; a fabricator turns matter into a sigil; a terminal
loads a region onto the knowledge frontier; and the neutral-allegiance contract
keeps Keepers out of combat entirely.

The dumb auto-player can never line these conditions up, so each set-piece builds
a FRESH fully-wired `Game`, stages the situation directly, runs the REAL hooks /
`try_move` / bus events, and prints a before->after with a ✓/✗ verdict computed
from live state.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m runtime.deepen_scenario
"""
from __future__ import annotations

import sys
import traceback

from runtime.game import Game, load_manifest
from runtime.entities import make_boss, make_enemy
from runtime.components import inv
from runtime.sigils import SigilSystem, MAX_SLOTS
from runtime.reactions import ReactionSystem
from runtime.knowledge import KnowledgeSystem
from runtime.factions import FactionSystem
from runtime.salvage import SalvageSystem
from runtime.forge import ForgeSystem
from runtime.quests import QuestSystem
from runtime.dialogue import DialogueSystem
from runtime.machines import MachineSystem

MANIFEST = "examples/world.json"
OK, NO = "✓", "✗"   # checkmark / cross


# ---------------------------------------------------------------- helpers ----
def build() -> Game:
    """Fresh, fully-wired world in the canonical deepen order: the configuration /
    matter / faction / knowledge substrate first, then the three layers that ride
    on top (quests -> dialogue -> machines)."""
    return Game(load_manifest(MANIFEST),
                systems=[SigilSystem(), ReactionSystem(), KnowledgeSystem(),
                         FactionSystem(), SalvageSystem(), ForgeSystem(),
                         QuestSystem(), DialogueSystem(), MachineSystem()])


def the_npc(game):
    """The floor's Keeper, found exactly as the engine's bump path finds it:
    the one neutral `npc`-allegiance actor on the map (public `game.actors`)."""
    return next((a for a in game.actors
                 if getattr(a, "allegiance", "") == "npc"), None)


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
def sp1_quest_from_a_note():
    header(1, "Quest from a note  (quests x factions)")
    g = build()
    q, fac = g.system("quests"), g.system("factions")

    # Pick the manifest's slay quest — its `objective` is a transformed TODO, and the
    # binding nails it to the boss whose source note is graph-nearest the quest's note.
    slay = next(qq for qq in q.quests
                if qq.get("kind") == "slay" and qq.get("target_source"))
    print("   A `- [ ]` TODO from the vault, bound to a concrete slay target:")
    print(f"     objective: {slay['objective']!r}")
    print(f"     slay target (graph-nearest boss source): {slay['target_source']!r}")

    # A Keeper would `offer` this; here we activate the offer-chain directly until the
    # slay charge is live (public API: QuestSystem.offer / .active / .completed).
    while not any(a.get("id") == slay["id"] for a in q.active):
        if q.offer(g) is None:
            break
    print(f"   active now: {[a['id'] for a in q.active]}   completed: {sorted(q.completed)}")

    fid = fac.faction_of(slay.get("target_source"))
    st_before = fac.standing_of(fid)
    # Fire the REAL trigger: the slay target dies LOUD on the bus.  The bound boss is
    # the manifest's own boss for that source note.
    boss_spec = next(b for b in g.m["bosses"]
                     if b.get("sourceNoteId") == slay["target_source"])
    boss = make_boss(boss_spec, 0, 0)
    print(f"\n   game.emit(enemy_killed, enemy={boss.name!r}, cause='melee')")
    s = len(g.messages)
    g.emit("enemy_killed", enemy=boss, cause="melee")
    show_logs(g, s)

    done = slay["id"] in q.completed
    rewarded = bool(slay.get("reward_applied"))
    st_after = fac.standing_of(fid)
    print(f"\n   completed contains {slay['id']}: {done}   reward: {slay.get('reward')!r}")
    print(f"   standing[{fid}] {st_before} -> {st_after}  "
          f"(loud kill -1, then charge reward +2 — systems compose)")
    return verdict(done and rewarded and st_after > st_before,
                   f"the charge moved active->completed and paid out "
                   f"({slay.get('reward')}).")


def sp2_npc_parley():
    header(2, "NPC parley — the offering, not water  (dialogue x salvage x factions x knowledge)")
    g = build()
    q, fac, kn = g.system("quests"), g.system("factions"), g.system("knowledge")
    npc = the_npc(g)
    if npc is None:
        return verdict(False, "no Keeper spawned on the floor")
    print(f"   A neutral Keeper stands the floor: {npc.name!r} "
          f"(glyph {npc.glyph!r}, allegiance {npc.allegiance!r}, source {npc.source!r}).")

    # Drain the quest offer-chain so the parley falls THROUGH the quest boon to the
    # OFFERING boon (the reputation mechanic of this layer).
    while q.offer(g) is not None:
        pass
    # Seed a single unit of salvaged matter: enough to make an offering, below the
    # smallest recover-quest goal so nothing else moves on this tick.
    inv(g.player).add({"brass": 1})

    fid = fac.faction_of(npc.source)
    m0, st0, k0 = inv(g.player).total(), fac.standing_of(fid), kn.is_known("stoicism")
    print(f"   Before: matter={m0}  standing[{fid}]={st0}  is_known('stoicism')={k0}")
    print(f"\n   game.emit(interact, target=<Keeper>)   (the bump path's parley event)")
    s = len(g.messages)
    g.emit("interact", target=npc, pos=(npc.x, npc.y))
    show_logs(g, s)
    m1, st1, k1 = inv(g.player).total(), fac.standing_of(fid), kn.is_known("stoicism")
    print(f"   After:  matter={m1}  standing[{fid}]={st1}  is_known('stoicism')={k1}")

    spent = m1 == m0 - 1
    stood = st1 > st0
    mapped = (not k0) and k1
    return verdict(spent and stood and mapped,
                   "offering: 1 matter spent -> standing +1 and a region revealed "
                   "(matter economy, not Qud's water).")


def sp3_fabricator():
    header(3, "Fabricator — matter becomes a sigil  (machines x forge x sigils)")
    g = build()
    mac, sig = g.system("machines"), g.system("sigils")
    if not mac.fabricators:
        return verdict(False, "no fabricator placed on the floor")
    fx, fy = sorted(mac.fabricators)[0]
    g.player.x, g.player.y = fx, fy          # stand the player on the F tile
    inv(g.player).add({"brass": 6})          # matter to feed the bench (forge costs 4)
    slots0, matter0, fabs0 = len(sig.slots), inv(g.player).total(), len(mac.fabricators)
    print(f"   Player on Fabricator {(fx, fy)}; free slots {slots0}/{MAX_SLOTS}; "
          f"matter={matter0}.")
    print(f"\n   machines.on_player_act(game)   (you stand on F -> it calls forge.forge)")
    s = len(g.messages)
    mac.on_player_act(g)                      # real machine-use hook
    show_logs(g, s)
    slots1, matter1, fabs1 = len(sig.slots), inv(g.player).total(), len(mac.fabricators)
    forged = [x["ability"] for x in sig.slots]
    print(f"   After:  slots {slots0}->{slots1} {forged}; matter {matter0}->{matter1}; "
          f"fabricators {fabs0}->{fabs1}.")
    return verdict(slots1 == slots0 + 1 and matter1 < matter0 and fabs1 == fabs0 - 1,
                   f"forged a {forged[-1] if forged else '?'} sigil (slots +1, "
                   f"matter -{matter0 - matter1}); the single-use bench burned out.")


def sp4_terminal():
    header(4, "Terminal — a region loads onto the map  (machines x knowledge)")
    g = build()
    mac, kn = g.system("machines"), g.system("knowledge")
    if not mac.terminals:
        return verdict(False, "no terminal placed on the floor")
    tx, ty = sorted(mac.terminals)[0]
    g.player.x, g.player.y = tx, ty           # stand the player on the T tile

    rid = mac.region_ahead(g)                 # the region the hack will load
    anchor = next((r["sourceNoteId"] for r in g.m["regions"] if r["id"] == rid), None)
    before = kn.is_known(anchor)
    terms0 = len(mac.terminals)
    print(f"   Player on Terminal {(tx, ty)}; it will load region {rid!r} "
          f"(anchor {anchor!r}).")
    print(f"   Before: is_known({anchor!r}) = {before}   terminals = {terms0}")
    print(f"\n   machines.on_player_act(game)   (you stand on T -> knowledge.reveal)")
    s = len(g.messages)
    mac.on_player_act(g)                       # real machine-use hook
    show_logs(g, s)
    after = kn.is_known(anchor)
    terms1 = len(mac.terminals)
    print(f"   After:  is_known({anchor!r}) = {after}   terminals = {terms1}")
    return verdict((not before) and after and terms1 == terms0 - 1,
                   f"hacking flipped is_known({anchor!r}) False->True; the node burned out.")


def sp5_npcs_are_neutral():
    header(5, "NPCs are neutral  (dialogue x core combat)")
    g = build()
    q = g.system("quests")
    npc = the_npc(g)
    if npc is None:
        return verdict(False, "no Keeper spawned on the floor")

    # Drop a hostile monster RIGHT NEXT TO the Keeper.  A normal foe in that spot would
    # trade blows; the neutral contract must keep the Keeper untouched.
    adj = None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        cx, cy = npc.x + dx, npc.y + dy
        if (g.level.walkable(cx, cy) and g.actor_at(cx, cy) is None
                and (cx, cy) != (g.player.x, g.player.y)):
            adj = (cx, cy)
            break
    if adj is None:
        return verdict(False, "no free tile adjacent to the Keeper")
    mon = make_enemy({"name": "Hollow Construct", "archetype": "construct", "tier": 2,
                      "sourceNoteId": "stoicism", "regionId": "region_0"}, *adj)
    g.actors.append(mon)
    print(f"   Keeper at {(npc.x, npc.y)} (hp {npc.hp}); monster {mon.name!r} "
          f"placed adjacent at {adj}.")
    print(f"   _hostile('monster','npc') = {Game._hostile('monster', 'npc')}  "
          f"(the engine never lets a foe target a Keeper)")

    hp0 = npc.hp
    print(f"\n   game.enemies_act() x5   (the monster takes its turns next to the Keeper)")
    for _ in range(5):
        g.enemies_act()
    safe = npc.hp == hp0 and npc in g.actors
    print(f"   Keeper hp {hp0} -> {npc.hp}; still on the floor: {npc in g.actors}")

    # Now the player bumps the Keeper: the bump must PARLEY, not attack.  Stand the
    # player one orthogonal step away on whichever adjacent tile is walkable.
    px = npc.x - 1 if g.level.walkable(npc.x - 1, npc.y) else npc.x + 1
    g.player.x, g.player.y = px, npc.y
    dx, dy = npc.x - g.player.x, npc.y - g.player.y
    hp_pre, active_pre = npc.hp, len(q.active)
    print(f"\n   game.try_move({dx},{dy})   (player steps INTO the Keeper -> bump)")
    s = len(g.messages)
    g.try_move(dx, dy)
    show_logs(g, s)
    parleyed = len(q.active) > active_pre or any(
        "entrusts you" in str(m) or "offering" in str(m) or "murmurs" in str(m)
        for m in g.messages[s:])
    no_attack = npc.hp == hp_pre
    print(f"   Keeper hp {hp_pre} -> {npc.hp}; active quests {active_pre} -> {len(q.active)}.")
    return verdict(safe and no_attack and parleyed,
                   "monster ignored the Keeper (0 damage over 5 turns); the player's "
                   "bump parleyed (a charge offered), never an attack.")


# -------------------------------------------------------------------- main ----
def main():
    print("VAULTCRAWL — DEEPEN SHOWCASE  (quests · NPCs · hackable machines)")
    print("A social + objective + machine layer on the shared bus. Each set-piece")
    print("stages a situation the auto-player can't reach and judges it from live state.")
    pieces = [sp1_quest_from_a_note, sp2_npc_parley, sp3_fabricator,
              sp4_terminal, sp5_npcs_are_neutral]
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
        print("OVERALL: PASS — all five deepen interactions verified.")
        return 0
    print("OVERALL: FAIL — see set-pieces marked above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
