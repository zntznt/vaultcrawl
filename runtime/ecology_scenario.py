"""Autonomous-ECOLOGY showcase for vaultcrawl.

The five ecology systems (reactions, flora, fauna, weather, structures, decay)
model a world that lives, reacts and dies on its OWN logic — flora, fauna,
weather, structures and decay pursue no one's interest. The player and the
factions can exploit them or get caught in them, but these systems are
indifferent: the wild hunts monsters because monsters are hostile to it, fire
runs through dry growth because it is fuel, a pressure plate fires under whatever
foot lands on it.

The dumb auto-player can never line these conditions up, so — exactly like
``runtime/scenario.py`` — each set-piece builds a fresh ``Game`` with just the
systems that piece needs, stages the situation by poking documented internals
(``reactions.props``, ``flora.plants``, ``structures.crystals/traps``,
``decay.corpses``, ``make_enemy``/``make_critter`` into ``game.actors``), runs
the REAL hooks / ``enemies_act`` and computes a ✓/✗ verdict from live state.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m runtime.ecology_scenario
"""
from __future__ import annotations
from runtime._showcase import OK, NO, show_logs, header, verdict

import traceback

from runtime.game import Game, load_manifest
from runtime.dungeon import free_floor_tiles
from runtime.entities import make_enemy, make_critter
from runtime.systems import System
from runtime.reactions import ReactionSystem
from runtime.factions import FactionSystem
from runtime.flora import FloraSystem
from runtime.fauna import FaunaSystem
from runtime.weather import WeatherSystem, WEATHER_PROPS
from runtime.structures import StructureSystem, SPIKE_DMG, DET_DMG
from runtime.decay import DecaySystem

MANIFEST = "examples/world.json"


# ---------------------------------------------------------------- probe ------
class BusProbe(System):
    """A passive recorder: captures every bus event so a set-piece can assert
    exactly which deaths the world announced (and that a faction-relevant
    `enemy_killed` did NOT fire when the wild does the killing)."""
    name = "_probe"

    def __init__(self):
        self.events: list = []

    def on_event(self, game, etype, data):
        self.events.append((etype, dict(data or {})))

    def kinds(self, etype):
        return [d for (e, d) in self.events if e == etype]


# --------------------------------------------------------------- helpers -----
def build(systems) -> Game:
    """Fresh world wired with just `systems` (+ a passive BusProbe at the tail).
    Game.__init__ runs on_world_start then descends to floor 1, so every system's
    on_floor_enter has already fired and seeded itself before we stage anything."""
    probe = BusProbe()
    g = Game(load_manifest(MANIFEST), systems=list(systems) + [probe])
    g.probe = probe
    return g


def mk_monster(x, y, name="Faction Drone", src="stoicism", hp=8, atk=2, tier=1):
    """A plain `monster`-allegiance foe with a real `source` (so faction lookups
    resolve), with hp/atk pinned for determinism."""
    a = make_enemy({"name": name, "archetype": "warden", "tier": tier,
                    "sourceNoteId": src}, x, y)
    a.hp = a.max_hp = hp
    a.atk = atk
    return a


def free(game, extra=()):
    ex = {(game.player.x, game.player.y), game.level.stairs} | set(extra)
    return free_floor_tiles(game.level, ex)


def is_floor(level, x, y):
    return 0 <= x < level.w and 0 <= y < level.h and level.tiles[y][x] == "."


def open_spot(game):
    """A floor tile whose whole 8-neighbourhood is floor — a clean room interior
    where a blast footprint / adjacency all land on real ground."""
    lvl = game.level
    skip = {(game.player.x, game.player.y), game.level.stairs}
    for (x, y) in free(game):
        if (x, y) in skip:
            continue
        if all(is_floor(lvl, x + dx, y + dy)
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            return (x, y)
    raise RuntimeError("no open 3x3 spot found")


def h_corridor(level, n):
    """Leftmost isolated 1-tall horizontal lane of exactly `n` floor tiles: the
    run is floor, everything directly above/below is wall, and the two ends are
    wall-capped. Fire can then ONLY travel along the row, so propagation is a
    clean, deterministic march. Returns the list of tiles or None."""
    def wall(x, y):
        return not is_floor(level, x, y)
    for y in range(level.h):
        for x in range(level.w - n):
            run = [(x + i, y) for i in range(n)]
            if not all(is_floor(level, cx, cy) for cx, cy in run):
                continue
            if not all(wall(cx, cy - 1) and wall(cx, cy + 1) for cx, cy in run):
                continue
            if not (wall(x - 1, y) and wall(x + n, y)):
                continue
            return run
    return None


def h_run(level, n, exclude=()):
    """Fallback: top-left of the first horizontal run of `n` floor tiles."""
    ex = set(exclude)
    for y in range(level.h):
        for x in range(level.w - n):
            run = [(x + i, y) for i in range(n)]
            if all(is_floor(level, cx, cy) and (cx, cy) not in ex for cx, cy in run):
                return run
    raise RuntimeError("no horizontal floor run found")
# ------------------------------------------------------------ set-pieces -----
def sp1_predation_thins_faction():
    header(1, "Predation thins the faction  (fauna x core x factions)")
    g = build([FactionSystem()])
    fac = g.system("factions")
    src = "stoicism"                         # community 0 -> faction_0
    fid = fac.faction_of(src)
    print("   The wild does your dirty work, indifferent to your interests: a")
    print("   `wild` predator and a `monster` are mutual enemies, so the core")
    print("   turn-loop pits them against each other. The world kills the faction's")
    print(f"   creature — and {fac.faction_name(fid)} ({fid}) never hears a thing,")
    print("   because a wild kill emits actor_died but NOT enemy_killed.")

    x, y = open_spot(g)
    g.actors = []
    monster = mk_monster(x, y, "Annotated Warden", src, hp=7, atk=2)
    predator = make_critter("dire-stalker", "Y", x + 1, y, hp=30, atk=9)
    g.actors = [predator, monster]           # predator first -> it strikes first
    d_before = dict(fac.disturbance)
    print(f"\n   Before: monster {monster.name!r} hp={monster.hp} at {(x, y)};")
    print(f"           wild predator hp={predator.hp} at {(x + 1, y)};")
    print(f"           faction disturbance = {d_before or '{}'}")

    s = len(g.messages)
    for _ in range(6):                       # run the REAL allegiance-aware loop
        if monster not in g.actors:
            break
        g.enemies_act()
    show_logs(g, s)

    d_after = dict(fac.disturbance)
    killed = g.probe.kinds("enemy_killed")
    died = g.probe.kinds("actor_died")
    print(f"   After:  monster present = {monster in g.actors};  "
          f"disturbance = {d_after or '{}'}")
    print(f"           bus: actor_died x{len(died)} (cause "
          f"{[d.get('cause') for d in died]}), enemy_killed x{len(killed)}")
    ok = (monster not in g.actors and d_after == d_before and not killed)
    return verdict(ok, "the wild felled the monster; faction disturbance unchanged "
                       "and no enemy_killed reached the factions.")


def sp2_fire_runs_through_flora():
    header(2, "Fire runs through vegetation  (flora x reactions)")
    g = build([ReactionSystem(), FloraSystem()])
    react, flora = g.system("reactions"), g.system("flora")
    g.actors, react.props, react.fire_life = [], {}, {}

    row = h_corridor(g.level, 5) or h_run(g.level, 5)
    flora.plants = set(row)
    flora.cap = len(row) + 8                 # leave headroom; we measure the originals
    original = set(row)
    react.ignite(*row[0], life=8)            # touch a flame to one end
    print("   A contiguous row of growth, lit at one end. A plant standing on a")
    print("   `fire` tile is kindling: flora removes it and leaps the flame to a")
    print("   neighbouring floor tile, so fire walks the whole row on its own.")
    print(f"   Lane of {len(row)} plants {row[0]}..{row[-1]}; ignited {row[0]}.")

    s = len(g.messages)
    for _ in range(len(row) + 4):            # canonical order: reactions, then flora
        react.on_player_act(g)
        flora.on_player_act(g)
    show_logs(g, s)

    consumed = original - flora.plants       # originally-green tiles now cleared
    burning = {p for p in original if "fire" in react.props_at(*p)}
    touched = consumed | burning
    print(f"   After:  {len(consumed)}/{len(original)} original plants consumed; "
          f"{len(burning)} still ablaze; {len(touched)} total touched by fire.")
    return verdict(len(touched) >= 3 and len(consumed) >= 3,
                   f"fire propagated along the vegetation — {len(touched)} of "
                   f"{len(original)} original tiles burned or consumed.")


def sp3_crystal_detonation():
    header(3, "Crystal detonation  (structures x reactions)")
    g = build([ReactionSystem(), StructureSystem()])
    react, st = g.system("reactions"), g.system("structures")
    g.actors, react.props, react.fire_life = [], {}, {}
    st.traps, st.crystals = {}, {}

    cx, cy = open_spot(g)
    st.crystals = {(cx, cy): 0}
    victim = mk_monster(cx + 1, cy, "Brittle Sentinel", "stoicism", hp=12, atk=2)
    g.actors = [victim]
    react.ignite(cx, cy, life=4)             # a flame licks the volatile cluster
    print("   A crystal cluster sits on the floor; a flame reaches it. The cluster")
    print("   is indifferent to allegiance — it simply bursts, scattering fire and")
    print("   charge across a small radius and battering whoever stands too close.")
    print(f"   Crystal at {(cx, cy)} (on fire); {victim.name!r} adjacent at "
          f"{(cx + 1, cy)} hp={victim.hp}.")

    hp0 = victim.hp
    s = len(g.messages)
    st.on_player_act(g)                      # real path: structures reads reactions.props
    show_logs(g, s)

    gone = (cx, cy) not in st.crystals
    nearby = set()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            nearby |= react.props_at(cx + dx, cy + dy)
    new_props = nearby & {"fire", "charged"}
    dmg = hp0 - victim.hp
    print(f"   After:  crystal present = {not gone};  new props near blast = "
          f"{sorted(new_props)};  {victim.name} took {dmg} dmg "
          f"(hp {hp0}->{victim.hp}).")
    return verdict(gone and {"fire", "charged"} <= new_props and dmg == DET_DMG,
                   f"detonation cleared the crystal, sowed fire+charge, and dealt "
                   f"{dmg} to the adjacent actor.")


def sp4_dungeon_is_impartial():
    header(4, "The dungeon is impartial  (structures x any actor)")
    g = build([StructureSystem(), DecaySystem()])
    st = g.system("structures")
    g.actors, st.traps, st.crystals = [], {}, {}

    tx, ty = open_spot(g)
    st.traps = {(tx, ty): "spike"}           # an armed spike plate
    monster = mk_monster(tx, ty, "Trespassing Golem", "roguelike project", hp=3, atk=2)
    g.actors = [monster]
    print("   A pressure plate doesn't care whose foot lands on it. Here it's a")
    print("   faction `monster`, not the player, standing on an armed spike plate —")
    print("   the trap fires all the same and routes the death through game.kill.")
    print(f"   {monster.name!r} (hp={monster.hp}) on a spike plate at {(tx, ty)}.")

    s = len(g.messages)
    st.on_player_act(g)                      # the plate triggers under the monster
    show_logs(g, s)

    trap_died = [d for d in g.probe.kinds("actor_died") if d.get("cause") == "trap"]
    spent = (tx, ty) not in st.traps
    decay = g.system("decay")
    corpse = decay.corpse_at(tx, ty)         # the death fed the ecology too
    print(f"   After:  monster present = {monster in g.actors};  plate spent = "
          f"{spent};  actor_died(cause='trap') x{len(trap_died)};  "
          f"corpse_at(plate) = {corpse}")
    return verdict(monster not in g.actors and spent and len(trap_died) == 1
                   and trap_died[0].get("pos") == (tx, ty),
                   "the spike plate killed the monster via game.kill(cause='trap') "
                   "— allegiance-blind.")


def sp5_death_feeds_the_ecology():
    header(5, "Death feeds the ecology  (decay x fauna)")
    g = build([DecaySystem(), FaunaSystem()])
    decay = g.system("decay")
    g.actors = []                            # clear fauna's own floor-spawn

    vx, vy = open_spot(g)
    victim = mk_monster(vx, vy, "Slain Drudge", "stoicism", hp=1)
    print("   Every death flows through game.kill -> actor_died, and decay turns it")
    print("   into a corpse: food and terrain. A wild scavenger, driven only by")
    print("   hunger, shuffles over and eats it — no one directed it to.")

    s = len(g.messages)
    g.kill(victim, "predation")              # universal death -> decay drops a corpse
    spawned = decay.corpse_at(vx, vy)
    scav = make_critter("carrion-eater", "z", vx + 1, vy, hp=5, atk=1,
                        source="fauna:scavenger")
    g.actors = [scav]
    print(f"   A creature dies at {(vx, vy)} -> corpse_at = {spawned}.")
    print(f"   Wild scavenger placed adjacent at {(vx + 1, vy)}.")

    g.system("fauna").on_player_act(g)       # real fauna drive: seek + decay.consume
    show_logs(g, s)
    eaten = not decay.corpse_at(vx, vy)
    print(f"   After:  corpse_at({(vx, vy)}) = {decay.corpse_at(vx, vy)}")
    return verdict(spawned and eaten,
                   "the kill became a corpse and the wild scavenger consumed it.")


def sp6_grazer_eats_the_weed():
    header(6, "Grazer eats the weed  (fauna x flora)")
    g = build([FloraSystem(), FaunaSystem()])
    flora = g.system("flora")
    g.actors = []                            # clear fauna's own floor-spawn

    px, py = open_spot(g)
    flora.plants = {(px, py)}                # a single weed to be grazed
    grazer = make_critter("meadow-grazer", "n", px + 1, py, hp=6, atk=1,
                          source="fauna:grazer")
    g.actors = [grazer]
    print("   Wildlife answers to drives, not to you. A grazer next to a plant")
    print("   simply eats it (flora.consume) — vegetation is food, nothing more.")
    print(f"   Plant at {(px, py)} (flora_at={flora.flora_at(px, py)}); "
          f"grazer adjacent at {(px + 1, py)}.")

    before = flora.flora_at(px, py)
    g.system("fauna").on_player_act(g)       # real grazer drive
    after = flora.flora_at(px, py)
    print(f"   After:  flora_at({(px, py)}) = {after}")
    return verdict(before and not after,
                   f"the grazer consumed the plant (flora_at {before}->{after}).")


def sp7_weather_reshapes_world():
    header(7, "Weather reshapes the world  (weather x reactions)")
    g = build([ReactionSystem(), WeatherSystem()])
    react, weather = g.system("reactions"), g.system("weather")
    g.floor = 20                             # a charged region -> a static storm
    weather.on_floor_enter(g)                # re-seed the sky for that region
    react.props, react.fire_life = {}, {}    # clean slate so every prop is the weather's
    word = weather.current(g)
    print("   The sky pursues no one's interest; it just acts on the whole floor.")
    print(f"   In a charged region the weather is a {word!r}: on its cadence it")
    print("   sows fresh charge across the ground and now and then throws a bolt")
    print("   that sets a tile alight — all of it written into the reactions layer.")

    s = len(g.messages)
    for _ in range(3):                       # tick across the weather's cadence
        weather.on_player_act(g)
    show_logs(g, s)

    seen = {p for props in react.props.values() for p in props}
    weather_typed = seen & WEATHER_PROPS[word]
    fired = "fire" in seen
    print(f"   After:  props now on the ground = {sorted(seen)};  "
          f"weather-typed = {sorted(weather_typed)}")
    note = "  (bonus: a lightning bolt struck — fire on the ground)" if fired else ""
    ok = bool(weather_typed) and "charged" in seen
    return verdict(ok, f"the {word} sowed {sorted(weather_typed)} into "
                       f"reactions.props.{note}")


# -------------------------------------------------------------------- main ---
def main():
    print("VAULTCRAWL — AUTONOMOUS-ECOLOGY SHOWCASE")
    print("World systems that act independently of the player and the factions.")
    print("Each set-piece builds a fresh Game, stages a situation the auto-player")
    print("can never reach, runs the REAL hooks, and judges it from live state.")
    pieces = [
        sp1_predation_thins_faction,
        sp2_fire_runs_through_flora,
        sp3_crystal_detonation,
        sp4_dungeon_is_impartial,
        sp5_death_feeds_the_ecology,
        sp6_grazer_eats_the_weed,
        sp7_weather_reshapes_world,
    ]
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
        print("OVERALL: PASS — all seven autonomous-ecology set-pieces verified.")
        return 0
    print("OVERALL: FAIL — see set-pieces marked above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
