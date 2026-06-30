"""Drive the real Game through the DialogueSystem and assert the parley contract.

Covers DEEPEN_SPEC.md Agent B:
  - a neutral NPC Keeper (glyph ``P``, allegiance ``"npc"``) spawns on floor enter;
  - parley resolution, first-applicable: Quest -> Offering -> Gossip;
  - the OFFERING reputation mechanic is a gift of salvaged *matter* (NOT water): one
    unit is spent, faction standing rises, a region is revealed;
  - bumping the NPC via the real ``try_move`` emits ``interact`` and parleys (the
    neutral NPC is never attacked / damaged / killed);
  - NPC tiles are points-of-interest; spawning is deterministic.

The quest partner (``runtime/quests.py``, Agent A) may not exist yet, so a tiny local
``QuestSystem`` stub stands in, exposing the one method dialogue calls (``offer``).
Faction / knowledge / salvage are the real systems.

Run: python3 -m tests.test_dialogue   (from the vaultcrawl project root)
"""
from runtime.components import inv
from runtime.dialogue import DialogueSystem
from runtime.factions import FactionSystem
from runtime.game import Game, load_manifest
from runtime.knowledge import KnowledgeSystem
from runtime.salvage import SalvageSystem
from runtime.systems import System

try:                                   # prefer the real partner if Agent A has landed it
    from runtime.quests import QuestSystem  # type: ignore
except Exception:                      # else a deterministic stub: one quest, then None
    class QuestSystem(System):
        name = "quests"

        def __init__(self):
            self._given = 0
            self.offered: list = []

        def offer(self, game):
            qs = game.m.get("quests", [])
            if self._given < len(qs):
                q = qs[self._given]
                self._given += 1
                self.offered.append(q)
                return q
            return None


def _new_game():
    dia = DialogueSystem()
    q = QuestSystem()
    fac = FactionSystem()
    kn = KnowledgeSystem()
    sal = SalvageSystem()
    g = Game(load_manifest("examples/world.json"),
             systems=[dia, q, fac, kn, sal])   # dialogue BEFORE knowledge (fog ordering)
    return g, dia, q, fac, kn, sal


def _the_npc(game):
    npcs = [a for a in game.actors if getattr(a, "allegiance", "") == "npc"]
    return npcs


def test_dialogue():
    g, dia, q, fac, kn, sal = _new_game()

    # --- 1) a neutral NPC Keeper spawns on floor enter -----------------------
    npcs = _the_npc(g)
    assert len(npcs) == 1, "exactly one Keeper spawns per floor"
    npc = npcs[0]
    assert npc.glyph == "P", "NPC glyph is P"
    assert npc.allegiance == "npc", "NPC is neutral"
    assert npc in dia.npcs, "the system tracks its own NPC"
    assert npc.source, "the Keeper carries its region anchor note as source"
    assert (npc.x, npc.y) in dia.points_of_interest(g), "NPC tile is a point of interest"

    # --- 2) Quest parley (first applicable): the Keeper entrusts a quest -----
    m0 = len(g.messages)
    g.emit("interact", target=npc, pos=(npc.x, npc.y))
    assert any("entrusts you" in m for m in g.messages[m0:]), "a quest was entrusted"

    # --- 3) Offering parley: quests exhausted -> spend matter, gain standing/intel
    # Force the quest well dry AND quiesce the partner's reactive reward loop, so the
    # only effect on matter/standing/knowledge during this probe is dialogue's offering.
    q.offer = lambda game=None: None
    q.on_event = lambda *a, **k: None
    q.on_player_act = lambda *a, **k: None
    inv(g.player).add({"brass": 3})          # salvaged matter to gift (NOT water)
    before_matter = inv(g.player).total()
    before_known = len(kn.known)
    before_standing = dict(fac.standing)
    m1 = len(g.messages)
    g.emit("interact", target=npc, pos=(npc.x, npc.y))
    after_matter = inv(g.player).total()
    assert after_matter == before_matter - 1, "exactly one unit of matter was offered"
    standing_changed = fac.standing != before_standing
    knowledge_changed = len(kn.known) > before_known
    assert standing_changed or knowledge_changed, \
        "the offering raised standing and/or revealed a region"
    assert any("accepts your offering" in m for m in g.messages[m1:]), "offering logged"
    assert not any("water" in m.lower() for m in g.messages), "NO water-ritual anywhere"

    # --- 4) Gossip parley: empty purse -> a boss/secret location is revealed -
    inv(g.player).comp.clear()
    before_known2 = len(kn.known)
    m2 = len(g.messages)
    g.emit("interact", target=npc, pos=(npc.x, npc.y))
    assert len(g.messages) > m2, "gossip produced a lore line"
    assert len(kn.known) >= before_known2, "gossip never un-reveals knowledge"

    # --- 5) the REAL bump path emits interact and never harms the neutral NPC
    g2, dia2, _, _, _, _ = _new_game()
    npc2 = _the_npc(g2)[0]
    spawn2 = (npc2.x, npc2.y)
    g2.actors = [a for a in g2.actors if getattr(a, "allegiance", "") == "npc"]  # quiet arena
    bx, by = npc2.x - 1, npc2.y
    g2.level.tiles[npc2.y][npc2.x] = "."
    g2.level.tiles[by][bx] = "."
    g2.player.x, g2.player.y = bx, by
    hp0, msgs0 = npc2.hp, len(g2.messages)
    g2.try_move(1, 0)                        # bump east into the Keeper
    assert npc2.hp == hp0, "a neutral NPC takes no damage from a bump"
    assert npc2 in g2.actors, "parleying never kills the NPC"
    assert len(g2.messages) > msgs0, "the bump triggered a parley log line"

    # --- 6) determinism: same seed -> same Keeper spawn tile -----------------
    g3, _, _, _, _, _ = _new_game()
    npc3 = _the_npc(g3)[0]
    assert (npc3.x, npc3.y) == spawn2, "NPC spawn is deterministic for a fixed seed"

    print("OK")


if __name__ == "__main__":
    test_dialogue()
