"""NPCs & dialogue — note-derived inhabitants you parley with.

Each region is personified by a single neutral **Keeper** (glyph ``P``, allegiance
``"npc"`` — never fights, never targeted; bumping it emits ``interact`` on the bus
instead of an attack). Talking to a Keeper resolves a deterministic *parley*, picking
the first boon that applies:

  1. **Quest**  — if the quest system still has an unoffered quest, the Keeper entrusts
     it to you (``quests.offer(game)``).
  2. **Offering** — else, if you carry any salvaged *matter*, the Keeper accepts a small
     offering (one unit of a material you hold), your **standing** with their faction
     rises, and they **reveal** a region that lies ahead. This is the reputation
     mechanic of this layer: a gift of the world's own matter, NOT a shared draught of
     water — it ties NPCs to the components economy, not to Qud's water-ritual.
  3. **Gossip** — else they murmur of a boss/secret location, revealing it on the map.

A per-NPC interaction count rotates the gossip target so one Keeper does not loop the
same revelation forever; the quest and offering boons are self-limiting (quests run out;
matter is spent). Every cross-system call (quests / factions / knowledge) is None-guarded,
so the system degrades gracefully when a partner is absent.

Self-contained: the Keeper is a real Actor drawn by the core renderer (its ``P`` glyph),
so this system needs no ``render_overlay`` — but it should be registered BEFORE the
knowledge system so distant Keepers are correctly veiled by the knowledge-fog overlay.
"""
from __future__ import annotations

import random

from runtime.components import inv
from runtime.dungeon import free_floor_tiles
from runtime.entities import make_npc
from runtime.systems import System

NPC_GLYPH = "P"   # free glyph in the budget; overlays floor '.' only


class DialogueSystem(System):
    name = "dialogue"

    def __init__(self):
        self.npcs: list = []   # Keepers spawned on the CURRENT floor (game.actors is rebuilt per descent)
        self.game = None

    # ---- lifecycle ------------------------------------------------------------
    def on_world_start(self, game):
        self.game = game
        self.npcs = []

    def on_floor_enter(self, game):
        """Spawn one Keeper for the floor's region on a deterministic free tile."""
        self.game = game
        self.npcs = []
        player = getattr(game, "player", None)
        level = getattr(game, "level", None)
        if player is None or level is None:
            return
        region = game.region_for(game.floor) or {}
        name = region.get("name") or "the Vault"
        anchor = region.get("sourceNoteId", "")   # the region's anchor note = NPC source
        exclude = {(player.x, player.y), level.stairs}
        exclude |= {(a.x, a.y) for a in game.actors}   # never spawn atop another actor
        free = free_floor_tiles(level, exclude)
        if not free:
            return
        rng = random.Random(f"{game.seed}:dialogue:{game.floor}")
        rng.shuffle(free)
        x, y = free[0]
        npc = make_npc(f"Keeper of {name}", NPC_GLYPH, x, y, source=anchor)
        npc._parleys = 0
        game.actors.append(npc)
        self.npcs.append(npc)

    # ---- the parley (cross-system bus) ----------------------------------------
    def on_event(self, game, etype, data):
        if etype != "interact":
            return
        self.game = game
        data = data or {}
        npc = data.get("target")
        if npc is None or getattr(npc, "allegiance", "") != "npc":
            return
        if npc not in self.npcs:          # not one of ours (another system's NPC) — ignore
            return
        npc._parleys = getattr(npc, "_parleys", 0) + 1
        # First applicable boon wins; each is deterministic.
        if self._try_quest(game, npc):
            return
        if self._try_offering(game, npc):
            return
        self._gossip(game, npc)

    # ---- 1) Quest -------------------------------------------------------------
    def _try_quest(self, game, npc) -> bool:
        quests = game.system("quests")
        offer = getattr(quests, "offer", None) if quests is not None else None
        if not callable(offer):
            return False
        quest = offer(game)
        if not quest:
            return False
        objective = quest.get("objective") if isinstance(quest, dict) else None
        objective = objective or "a charge left unfinished in your own hand"
        game.log(f"{npc.name} entrusts you: {objective}")
        return True

    # ---- 2) Offering (matter, NOT water) --------------------------------------
    def _try_offering(self, game, npc) -> bool:
        purse = inv(game.player)
        if purse is None or purse.total() <= 0:
            return False
        # Pick an affordable material deterministically: the most-held, ties by name.
        mat = sorted(purse.comp.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if not purse.pay({mat: 1}):       # take a small matter offering (one unit)
            return False
        faction = "keepers"
        fsys = game.system("factions")
        if fsys is not None:
            fof = getattr(fsys, "faction_of", None)
            fid = fof(npc.source) if callable(fof) else None
            standing = getattr(fsys, "standing", None)
            if fid and isinstance(standing, dict):
                standing[fid] = standing.get(fid, 0) + 1   # standing rises with the gift
                fname = getattr(fsys, "faction_name", None)
                if callable(fname):
                    faction = fname(fid)
        self._reveal(game, self._region_ahead(game))        # they share what lies ahead
        game.log(f"{npc.name} accepts your offering; the {faction} share what lies ahead.")
        return True

    # ---- 3) Gossip ------------------------------------------------------------
    def _gossip(self, game, npc) -> None:
        targets = self._secret_targets(game)
        if targets:
            idx = (getattr(npc, "_parleys", 1) - 1) % len(targets)   # rotate per visit
            self._reveal(game, targets[idx])
        game.log(f"{npc.name} murmurs of what waits in the deeper dark.")

    # ---- helpers --------------------------------------------------------------
    def _reveal(self, game, target) -> None:
        if not target:
            return
        kn = game.system("knowledge")
        reveal = getattr(kn, "reveal", None) if kn is not None else None
        if callable(reveal):
            reveal(target)

    def _region_ahead(self, game) -> str:
        """A region the player has not yet reached (revealing the current one is moot)."""
        regions = game.m.get("regions", [])
        cur = game.region_for(game.floor) or {}
        cur_id = cur.get("id")
        ahead = [r for r in regions if r.get("depthBand", [1, 1])[0] > game.floor]
        if ahead:
            return min(ahead, key=lambda r: r["depthBand"][0]).get("id", "")
        for r in regions:                 # nothing strictly deeper: any other region
            if r.get("id") != cur_id:
                return r.get("id", "")
        return cur_id or ""

    def _secret_targets(self, game) -> list:
        """Boss regions + secret notes — the lore a Keeper can hint at."""
        out: list = []
        for b in game.m.get("bosses", []):
            rid = b.get("regionId")
            if rid and rid not in out:
                out.append(rid)
        for s in game.m.get("secrets", []):
            nid = s.get("sourceNoteId")
            if nid and nid not in out:
                out.append(nid)
        return out

    # ---- integrator surface ---------------------------------------------------
    def points_of_interest(self, game):
        """Keeper tiles — so the auto-exploiter walks over to parley."""
        return [(n.x, n.y) for n in self.npcs
                if getattr(n, "alive", True) and n in game.actors]

    def status_line(self, game):
        living = [n for n in self.npcs if n in game.actors]
        if not living:
            return None
        return f"Keepers: {len(living)}"
