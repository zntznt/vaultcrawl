"""Self-test for the faction-response system (core + cross-system interaction).

Drives the REAL Game built from examples/world.json with the faction system and a tiny
`knowledge` STUB registered on the bus (so `game.emit` and `game.system` wire up exactly
as in play), then asserts:

  core
    * a LOUD kill (cause melee/sigil) raises the victim faction's disturbance and lowers
      your standing with it, while pleasing its rivals;
    * a QUIET kill (cause environment) never raises disturbance — it cools the alert;
    * a disturbed faction dispatches flagged 'H' hunters on the next floor;
    * the HUD line renders.

  interaction (via knowledge stub)
    * a LOUD kill of one of our own hunters scavenges its sensors → knowledge.reveal()
      marks the current region known (a plain loud kill does not);
    * standing >= 3 with the region's faction shares its map → knowledge.reveal() on
      floor enter.
"""
from runtime.game import Game, load_manifest
from runtime.entities import make_enemy
from runtime.factions import FactionSystem
from runtime.systems import System


class KnowledgeStub(System):
    """Minimal stand-in for the knowledge system: records reveal targets.

    Matches the query API in INTERACTIONS_SPEC.md (`reveal(target)`, `is_known(note_id)`)
    so the faction system's None-guarded calls land here during the test."""

    name = "knowledge"

    def __init__(self):
        self.revealed: set = set()

    def reveal(self, target):
        if target:
            self.revealed.add(target)

    def is_known(self, note_id):
        return note_id in self.revealed


def _new_world(manifest=None):
    """A real Game with the faction system + a knowledge stub on the bus."""
    m = manifest if manifest is not None else load_manifest("examples/world.json")
    g = Game(m, systems=[FactionSystem(), KnowledgeStub()])
    return g, g.system("factions"), g.system("knowledge")


def test_factions():
    g, s, kn = _new_world()

    # Resolve the faction that enemy_0 belongs to (query API: no game arg).
    spec = g.m["enemies"][0]
    victim = s.faction_of(spec["sourceNoteId"])
    assert victim is not None, "enemy_0 should map to a clustered faction"
    assert s.standing_of(victim) == 0, "standing_of defaults to 0 before any interaction"

    d0, st0 = s.disturbance.get(victim, 0), s.standing.get(victim, 0)

    # --- LOUD kills over the bus: disturbance up, standing down, per kill ---
    for _ in range(3):
        g.emit("enemy_killed", enemy=make_enemy(spec, 0, 0), cause="melee")
    assert s.disturbance.get(victim, 0) == d0 + 3, "loud melee kills raise disturbance"
    assert s.standing_of(victim) == st0 - 3, "victim faction standing drops per loud kill"
    assert s.standing_of(victim) < 0, "standing shifts negative for the victim faction"

    # A sigil kill is loud as well.
    g.emit("enemy_killed", enemy=make_enemy(spec, 0, 0), cause="sigil")
    assert s.disturbance.get(victim, 0) == d0 + 4, "sigil kills are loud too"

    # A loud NON-hunter kill scavenges nothing (no map reveal).
    rid = g.region_for(g.floor).get("id")
    assert not kn.is_known(rid), "ordinary loud kills do not reveal the map"

    # --- QUIET (environment) kills never raise disturbance; they cool it ---
    before = s.disturbance.get(victim, 0)
    g.emit("enemy_killed", enemy=make_enemy(spec, 0, 0), cause="environment")
    after = s.disturbance.get(victim, 0)
    assert after <= before, "environment kills must NOT raise disturbance"
    assert after == before - 1, "a quiet kill cools the alert by one (min 0)"

    # From a baseline of zero, a quiet kill stays at zero (never raised, never negative).
    gz, sz, _ = _new_world()
    sz.disturbance.clear()
    sz.on_event(gz, "enemy_killed", {"enemy": make_enemy(spec, 0, 0), "cause": "environment"})
    assert sz.disturbance.get(victim, 0) == 0, "quiet kill from zero stays at zero"

    # --- live diplomacy: provoking A pleases its rival B ---
    m2 = load_manifest("examples/world.json")
    for f in m2["bible"]["factions"]:
        if f["id"] == "faction_0":
            f["relations"] = [{"factionId": "faction_1", "stance": "rival"}]
    g2, s2, _ = _new_world(m2)
    rival_spec = next(e for e in g2.m["enemies"]
                      if s2.faction_of(e["sourceNoteId"]) == "faction_0")
    g2.emit("enemy_killed", enemy=make_enemy(rival_spec, 0, 0), cause="melee")
    assert s2.standing_of("faction_0") < 0, "the provoked faction loses favor"
    assert s2.standing_of("faction_1") > 0, "its rival gains favor"

    # --- hunter intel: a LOUD hunter kill scavenges sensors → knowledge.reveal ---
    g3, s3, kn3 = _new_world()
    region3 = g3.region_for(g3.floor).get("id")
    hunter = make_enemy(spec, 0, 0)
    hunter.is_hunter = True              # flagged at spawn
    hunter.name = "Hunter of Test"       # ...and name-prefix detectable
    g3.emit("enemy_killed", enemy=hunter, cause="melee")
    assert kn3.is_known(region3), "a loud hunter kill reveals the current region"

    # A QUIET hunter kill yields no scavenged intel.
    g4, s4, kn4 = _new_world()
    region4 = g4.region_for(g4.floor).get("id")
    hq = make_enemy(spec, 0, 0)
    hq.is_hunter = True
    g4.emit("enemy_killed", enemy=hq, cause="environment")
    assert not kn4.is_known(region4), "a quiet hunter kill scavenges nothing"

    # --- shared map: standing >= 3 with the region faction reveals it on floor enter ---
    g5, s5, kn5 = _new_world()
    region5 = g5.region_for(g5.floor)
    cur_fac, region5_id = region5.get("factionId"), region5.get("id")
    assert cur_fac, "the current region should declare a factionId"
    s5.standing[cur_fac] = 5            # court this faction
    kn5.revealed.clear()               # ignore anything revealed during construction
    s5.on_floor_enter(g5)
    assert kn5.is_known(region5_id), "a trusted faction (standing>=3) shares the floor map"

    # --- escalation: disturbance past threshold dispatches flagged 'H' hunters ---
    s.disturbance[victim] = 6
    before_n = len(g.actors)
    s.on_floor_enter(g)
    hunters = [a for a in g.actors if a.glyph == "H"]
    assert len(hunters) >= 1, "a disturbed faction dispatches at least one hunter"
    assert all(getattr(h, "is_hunter", False) for h in hunters), "hunters are flagged for intel"
    assert len(g.actors) > before_n or before_n == 0, "hunters were appended to g.actors"
    assert s.disturbance[victim] == 0, "disturbance resets after dispatch"

    # --- HUD line renders as a non-empty string ---
    line = s.status_line(g)
    assert isinstance(line, str) and line, "status_line returns a non-empty string"

    print("OK")


if __name__ == "__main__":
    test_factions()
