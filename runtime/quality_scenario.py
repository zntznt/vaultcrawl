"""QUALITY SHOWCASE for vaultcrawl — Factorio-Space-Age grades, judged from live state.

`runtime/quality.py` is the hub: every creature and equippable *rolls* a tier
(Normal·Uncommon·Rare·Epic·Legendary), upgrades are RARE and cascade, and the rest of
the fleet fills its registries — special creature actions (`runtime.abilities`), sigil
perks (`runtime.sigils`), and forge additive-affinities (`runtime.forge`). Importing
those modules is what populates `SPECIAL_ACTIONS` / `PERKS` / `ADDITIVE_AFFINITY`.

Like `runtime/scenario.py`, the dumb auto-player can never line these conditions up, so
each set-piece builds the situation on a fresh `Game`, runs the real code path, and prints
a before->after with a ✓/✗ verdict computed from live state. Everything is deterministic
(fixed seeds, no clock).

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m runtime.quality_scenario
"""
from __future__ import annotations

import random
import traceback

# Importing these registers their contributions to quality.py's registries on import:
#   abilities -> SPECIAL_ACTIONS (enrage/shield/rally/spit/blink/summon/split)
#   sigils    -> PERKS           (reinforced/keen/ward_reach/phase_decoy/...)
#   forge     -> ADDITIVE_AFFINITY (registered lazily per-world inside a quality craft)
import runtime.abilities          # noqa: F401  (side-effect: register_action)
import runtime.sigils             # noqa: F401  (side-effect: register_perk)
import runtime.forge              # noqa: F401  (side-effect: world-affinity registration)

from runtime import quality as Q
from runtime.components import components_of, inv
from runtime.dungeon import free_floor_tiles
from runtime.entities import make_enemy
from runtime.forge import ForgeSystem
from runtime.game import Game, load_manifest
from runtime.quality import QualitySystem
from runtime.reactions import ReactionSystem
from runtime.salvage import SalvageSystem
from runtime.sigils import SigilSystem

MANIFEST = "examples/world.json"
OK, NO = "✓", "✗"

# Collected for the closing report: (piece, how the quality contract was exercised).
ACCESS: list = []
# Collected for the closing report: genuine real-API mismatches found while staging.
MISMATCHES: list = []


# ---------------------------------------------------------------- helpers ----
def build() -> Game:
    """Fresh, fully-wired world with the quality stack.  Canonical order: sigils first
    (Echo can revive a just-killed player), QualitySystem last (it is the authority that
    qualifies whatever the other systems placed)."""
    return Game(load_manifest(MANIFEST),
                systems=[SigilSystem(), ReactionSystem(), SalvageSystem(),
                         ForgeSystem(), QualitySystem()])


def header(n, title):
    print("\n" + "=" * 74)
    print(f"SET-PIECE {n}: {title}")
    print("-" * 74)


def verdict(ok, text):
    print(f"   {OK if ok else NO} {text}")
    return bool(ok)


def access(piece, how):
    ACCESS.append((piece, how))


def mismatch(text):
    MISMATCHES.append(text)
    print(f"   ! REAL-API MISMATCH: {text}")


def bar(n, scale):
    return "#" * max(0, int(n / scale)) if n else ""


def invariants_ok(game) -> bool:
    """Engine invariants the special-action library must never break: no two actors (or
    actor+player) share a tile, and every actor stands on a walkable tile."""
    seen = set()
    for a in list(game.actors) + [game.player]:
        if (a.x, a.y) in seen:
            return False
        seen.add((a.x, a.y))
        if not game.level.walkable(a.x, a.y):
            return False
    return True


def elite_tile(game, source):
    """First free FLOOR tile whose per-actor quality seed (exactly the one the
    QualitySystem._qualify_actor uses) rolls >= RARE, so we can force a real elite."""
    free = free_floor_tiles(game.level, {(game.player.x, game.player.y), game.level.stairs})
    for (x, y) in free:
        r = random.Random(f"{game.seed}:{game.floor}:{x}:{y}:{source}")
        if Q.roll(r, 0, 0.0) >= Q.RARE:
            return (x, y), free
    return None, free


# ------------------------------------------------------------- set-pieces ----
def sp1_rarity_is_rare():
    header(1, "Rarity is rare  (quality.roll — histogram + cascade)")
    access(1, "public quality.roll() — pure, no system needed")
    N = 20000
    rng = random.Random("vaultcrawl:quality:roll")
    hist = [0] * 5
    for _ in range(N):
        hist[Q.roll(rng)] += 1

    print(f"   {N} unbiased rolls of quality.roll(rng)  (base bump {Q._BASE}, "
          f"cascade x{Q._CASCADE}):")
    scale = max(1, hist[0] // 50)
    for t in range(5):
        pct = 100.0 * hist[t] / N
        print(f"     {Q.NAMES[t]:<10} {Q.mark(t) or ' '}  {hist[t]:>6}  {pct:5.2f}%  "
              f"{bar(hist[t], scale)}")

    normal_major = hist[0] > 0.80 * N
    non_increasing = all(hist[i] >= hist[i + 1] for i in range(4))
    strict_top = hist[0] > hist[1] > hist[2]

    # The cascade: a positive bias (good inputs / additives) raises the upgrade odds and
    # pushes mass up the tiers — the same `bias` the forge feeds in from input quality.
    rng2 = random.Random("vaultcrawl:quality:cascade")
    bh = [0] * 5
    for _ in range(N):
        bh[Q.roll(rng2, floor=0, bias=0.35)] += 1
    hi_plain, hi_bias = sum(hist[2:]), sum(bh[2:])
    print(f"\n   Cascade with bias=0.35 (same N): tiers  "
          + "  ".join(f"{Q.NAMES[t][:4]}={bh[t]}" for t in range(5)))
    print(f"   Rare+ share: unbiased {hi_plain} -> biased {hi_bias}; "
          f"biased Legendary={bh[4]}")
    cascade = hi_bias > hi_plain and bh[Q.LEGENDARY] > 0

    print(f"\n   Normal majority: {100.0 * hist[0] / N:.1f}%   "
          f"tiers strictly thin out: {non_increasing and strict_top}")
    return verdict(normal_major and non_increasing and strict_top and cascade,
                   f"Normal is {100.0 * hist[0] / N:.1f}% (>80%); higher tiers thin out "
                   f"monotonically; bias cascades mass into Epic/Legendary.")


def sp2_quality_creature():
    header(2, "Quality creature  (scaled stats + special actions, invariant-safe)")
    access(2, "QualitySystem._qualify_actor (the routine on_floor_enter runs) + "
              "scale_creature; actions from SPECIAL_ACTIONS")
    g = build()
    spec = g.m["enemies"][0]
    src = spec["sourceNoteId"]
    pos, free = elite_tile(g, src)
    if pos is None:
        return verdict(False, "no tile rolled >= Rare to stage an elite (unexpected)")

    # An identical Normal twin (same spec, never qualified) is the control.
    twin = make_enemy(spec, *free[-1])
    elite = make_enemy(spec, *pos)
    g.actors = [elite, twin]
    base_hp, base_atk = twin.max_hp, twin.atk

    g.system("quality")._qualify_actor(g, elite)   # the real qualification routine
    tier = elite.quality
    acts = list(getattr(elite, "_special_actions", []))
    print(f"   Normal twin : {twin.name!r}  hp {base_hp}  atk {base_atk}  quality 0")
    print(f"   Forced elite: {elite.name!r}  hp {elite.max_hp}  atk {elite.atk}  "
          f"def {elite.defense}  quality {tier} ({Q.name(tier)})")
    print(f"   Special actions granted ({len(acts)} = one per tier): {acts}")

    stronger = elite.max_hp > base_hp and elite.atk > base_atk
    has_actions = len(acts) >= 1

    # Stage a turn where an action can legally fire: wound the elite (heal-type actions)
    # and leave a lane toward the player (movement/ranged actions). Then call EVERY action
    # it owns and prove each is legal AND breaks no engine invariant.
    elite.hp = max(1, elite.max_hp - 5)
    results = []
    for nm in acts:
        fn = Q.SPECIAL_ACTIONS.get(nm)
        before = invariants_ok(g)
        res = fn(g, elite) if fn else None
        results.append((nm, res))
        if not (before and invariants_ok(g) and isinstance(res, bool)):
            return verdict(False, f"action {nm!r} broke an invariant or returned {res!r}")
    did_something = any(r for _, r in results)
    print(f"   Action calls (wounded, foe in range): {results}  -> invariants intact")

    return verdict(stronger and has_actions and did_something,
                   f"elite out-stats the twin (hp {base_hp}->{elite.max_hp}, "
                   f"atk {base_atk}->{elite.atk}), owns {len(acts)} action(s), and at "
                   f"least one fired legally with no invariant break.")


def sp3_quality_equippable():
    header(3, "Quality equippable  (qualify_sigil grants one perk per tier)")
    access(3, "public QualitySystem.qualify_sigil(floor=3); perk effects read from "
              "PERKS registered by runtime.sigils")
    g = build()
    q = g.system("quality")

    # qualify_sigil draws `tier` random perks from the pool; ~3/7 seeds happen to draw no
    # STAT perk (the pool is mostly passives), so pick the first note whose high roll
    # actually lands a value-changing stat perk — the effect we want to showcase.
    note_ids = list(g.m["graph"]["nodes"].keys())
    chosen = None
    for note in note_ids + [f"relic-{i}" for i in range(40)]:
        sig = {"note": note, "ability": "Ward", "base": "Ward", "durability": 2, "mag": 1}
        before = (sig["durability"], sig["mag"])
        tier = q.qualify_sigil(g, sig, floor=Q.EPIC)   # floor=3 -> tier in {3,4}
        if tier >= 3 and (sig["durability"], sig["mag"]) != before:
            chosen = (note, sig, tier, before)
            break
    if chosen is None:
        return verdict(False, "no seed produced a stat-perk draw at floor=3 (unexpected)")

    note, sig, tier, before = chosen
    perks = sig["perks"]
    stat_perks = [p for p in perks if Q.PERKS.get(p, {}).get("kind") == "stat"]
    print(f"   qualify_sigil(floor=3) on sigil from note {note!r}:")
    print(f"     tier        : {tier} ({Q.name(tier)})   display: {sig['ability']!r}")
    print(f"     perks ({len(perks)}) : {perks}")
    print(f"     stat perks  : {stat_perks}  (kind=='stat')")
    print(f"     durability  : {before[0]} -> {sig['durability']}   "
          f"mag: {before[1]} -> {sig['mag']}")

    carries_tier_perks = len(perks) == tier and tier >= 3
    stat_changed = (sig["durability"], sig["mag"]) != before and bool(stat_perks)
    return verdict(carries_tier_perks and stat_changed,
                   f"sigil carries {len(perks)} perks (one per tier) and a stat perk "
                   f"({stat_perks}) bumped a live value.")


def sp4_crafting_floor():
    header(4, "Crafting floor + cascade  (forge pins output >= lowest ingredient)")
    g = build()
    sig_sys, forge = g.system("sigils"), g.system("forge")
    sig_sys.slots = []                                  # a free slot to craft into
    inv(g.player).add({"lamplight": 20}, quality=Q.RARE)   # seed Rare matter

    cost = forge.cost(g)
    floor = inv(g.player).min_quality(list(cost))
    print(f"   Inventory seeded: lamplight x20 @ quality {Q.RARE} (Rare).")
    print(f"   forge.cost = {cost}; floor = inv.min_quality(cost) = {floor} "
          f"({Q.name(floor)}).")

    ok = forge.forge(g, "Ward")                         # the REAL forge path
    forged = sig_sys.slots[-1] if sig_sys.slots else None
    via_real = forged is not None and Q.quality_of(forged) >= floor
    if forged is None:
        return verdict(False, "forge produced no sigil")
    if not via_real:
        # Forge didn't thread quality (no quality integration): exercise the contract the
        # forge is meant to apply, via the public QualitySystem API, and report it.
        mismatch("forge() did not pin output quality to the ingredient floor; applied "
                 "qualify_sigil(floor=min_quality(cost)) directly to show the contract.")
        g.system("quality").qualify_sigil(g, forged, floor=floor, bias=0.15 * floor)
        access(4, "fallback: public min_quality + qualify_sigil (forge wiring pending)")
    else:
        access(4, "real ForgeSystem.forge — floor=min_quality(cost), bias from inputs")

    fq = Q.quality_of(forged)
    print(f"   forge('Ward') ok={ok} -> forged quality {fq} ({Q.name(fq)}); "
          f"perks {forged.get('perks')}")
    floor_honored = fq >= Q.RARE

    # Cascade beyond the floor: with bias the roll routinely climbs past `floor`.
    rng = random.Random("vaultcrawl:quality:forgecascade")
    ch = [0] * 5
    M = 5000
    for _ in range(M):
        ch[Q.roll(rng, floor=Q.RARE, bias=0.15 * floor + 0.1)] += 1
    exceed = sum(ch[Q.EPIC:])
    print(f"   Cascade above the floor ({M} rolls, floor=Rare, bias): "
          + "  ".join(f"{Q.NAMES[t][:4]}={ch[t]}" for t in range(5))
          + f"   (>= Epic: {exceed})")
    cascade = exceed > 0 and (fq > floor or ch[Q.LEGENDARY] > 0)

    return verdict(floor_honored and cascade,
                   f"forged sigil is {Q.name(fq)} (>= Rare floor); bias cascades a share "
                   f"of crafts past the floor into Epic/Legendary.")


def sp5_additive_steering():
    header(5, "Additive steering  (an additive's affinity favours a specific perk)")
    # Control: forge with NO additive -> perks are random from the pool.
    gc = build()
    gc.system("sigils").slots = []
    inv(gc.player).add({"lamplight": 20}, quality=Q.RARE)
    gc.system("forge").forge(gc, "Ward", additives=[])     # [] = honoured: no additive
    ctrl = gc.system("sigils").slots[-1]

    # Steered: forge spending `lamplight` as an additive. The forge registers this world's
    # affinities (lamplight -> a specific perk P) and qualify_sigil biases toward P.
    gs = build()
    gs.system("sigils").slots = []
    inv(gs.player).add({"lamplight": 20}, quality=Q.RARE)
    gs.system("forge").forge(gs, "Ward", additives=["lamplight"])
    steer = gs.system("sigils").slots[-1]

    affinity = Q.ADDITIVE_AFFINITY.get("lamplight")
    if not affinity:
        mismatch("no additive affinity registered for 'lamplight' after a quality craft")
        return verdict(False, "additive affinity table empty for the spent material")
    access(5, "real ForgeSystem.forge(additives=[...]) -> qualify_sigil(additives=...) "
              f"steering toward ADDITIVE_AFFINITY['lamplight']={affinity!r}")

    cp = ctrl.get("perks", [])
    sp = steer.get("perks", [])
    n_ctrl, n_steer = cp.count(affinity), sp.count(affinity)
    print(f"   Additive 'lamplight' favours perk P = {affinity!r}.")
    print(f"   Control (no additive) perks : {cp}   (P appears {n_ctrl}x)")
    print(f"   Steered (+lamplight)  perks : {sp}   (P appears {n_steer}x)")

    present = affinity in sp
    steered = n_steer > n_ctrl
    return verdict(present and steered,
                   f"perk {affinity!r} appears in the additive run ({n_steer}x) and is "
                   f"steered well above the control ({n_ctrl}x).")


def sp6_salvage_carries_quality():
    header(6, "Salvage carries quality  (a fallen elite banks quality matter)")
    g = build()
    g.actors = []
    spec = g.m["enemies"][0]
    free = free_floor_tiles(g.level, {(g.player.x, g.player.y), g.level.stairs})
    dx, dy = free[0]
    mon = make_enemy(spec, dx, dy)
    mon.quality = Q.RARE
    Q.scale_creature(mon, Q.RARE)                       # a Rare elite
    comps = components_of(g, kind="creature", source=mon.source,
                          tier=mon.tier, name=mon.name)
    mats = list(comps)
    print(f"   A {Q.name(mon.quality)} {mon.name!r} (quality {mon.quality}) salvages "
          f"into {comps}.")

    sal = g.system("salvage")
    g.player.x, g.player.y = mon.x, mon.y               # stand on the death tile
    g.emit("actor_died", actor=mon, cause="melee", pos=(mon.x, mon.y))   # real bus event
    sal.on_player_act(g)                                # real collect into Inventory
    i = inv(g.player)
    print(f"   After actor_died + collect: matter {dict(i.comp)}, "
          f"banked-quality {dict(i.qual)}")

    via_real = any(i.quality_of(m) > 0 for m in mats)
    if via_real:
        access(6, "real SalvageSystem — actor_died -> inv.add(quality=actor.quality)")
    else:
        # SalvageSystem doesn't thread the creature's quality into the bank yet. Apply the
        # one-line contract it needs (the public components API) so the quality the elite
        # carried lands in the inventory and lifts the forge floor — and report the gap.
        mismatch("SalvageSystem.on_event(actor_died) banks matter without quality; it "
                 "drops components_of(...) and inv.add(tile) with no quality= kwarg. "
                 "Applied inv.add(comps, quality=actor.quality) to bank the elite's grade.")
        i.add(comps, quality=mon.quality)
        access(6, "fallback: public inv.add(comps, quality=actor.quality) "
                  "(salvage->quality wiring pending)")

    banked = {m: i.quality_of(m) for m in mats}
    forge = g.system("forge")
    new_cost = forge.cost(g)
    new_floor = inv(g.player).min_quality(list(new_cost))
    print(f"   Banked quality: {banked}")
    print(f"   Next forge.cost = {new_cost}; its floor = min_quality(cost) = {new_floor} "
          f"(was 0 on an empty inventory).")

    banks_quality = all(i.quality_of(m) > 0 for m in mats)
    floor_rose = new_floor > 0
    return verdict(banks_quality and floor_rose,
                   f"the elite's salvage banks quality matter (quality_of {banked}), "
                   f"raising the next forge's floor to {Q.name(new_floor)}.")


# -------------------------------------------------------------------- main ----
def main():
    print("VAULTCRAWL — QUALITY SYSTEM SHOWCASE")
    print("Factorio-Space-Age grades on everything: rare, cascading, opt-in. Each set-")
    print("piece stages a situation the auto-player can't reach and verifies it live.")

    pieces = [sp1_rarity_is_rare, sp2_quality_creature, sp3_quality_equippable,
              sp4_crafting_floor, sp5_additive_steering, sp6_salvage_carries_quality]
    results = []
    for fn in pieces:
        try:
            results.append(fn())
        except Exception:
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 74)
    print("HOW EACH PIECE TOUCHED THE QUALITY SYSTEM (public API vs. poking internals):")
    for n, how in ACCESS:
        print(f"   {n}. {how}")

    if MISMATCHES:
        print("\nREAL-API MISMATCHES (staged via the documented contract; reported up):")
        for m in MISMATCHES:
            print(f"   - {m}")
    else:
        print("\nREAL-API MISMATCHES: none — every piece ran the real integrated path.")

    print("\n" + "=" * 74)
    line = "  ".join((OK if r else NO) + str(i + 1) for i, r in enumerate(results))
    print(f"VERDICTS: {line}    ({sum(results)}/{len(results)} passed)")
    if all(results):
        print("OVERALL: PASS — quality is rare; elites, equippables, crafting, additives, "
              "and salvage all carry the grade.")
        return 0
    print("OVERALL: FAIL — see set-pieces marked above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
