"""Faction response — the world reacts to how you play.

Cogmind's investigation/alert escalation meets Qud's reputation/water-ritual, wired
onto the vault's own relation graph. Killing a faction's creatures raises its
*disturbance* (a Cogmind-style alert track) and lowers your *standing* with it; because
factions sit in a live diplomacy graph, antagonizing faction A *pleases* its rivals and
foes (your standing with them rises). Cross a disturbance threshold and the faction
dispatches hunters after you; earn enough standing with a region's faction and they
"let you pass," pacifying one of their own — a tiny water-ritual of safe conduct.

Cross-system play (see INTERACTIONS_SPEC.md). Kills now arrive on the bus as
`enemy_killed` events carrying a `cause`:
  - **loud** (`melee` / `sigil`) — heard: disturbance +1, standing −1, rivals +1;
  - **quiet** (`environment`) — a lure onto a hazard kills unseen: NO disturbance, the
    faction's alert even cools a little.
Killing one of our own *hunters* with a loud blow lets you scavenge its sensors —
we reveal the floor through the `knowledge` system. And once a region's faction trusts
you (standing ≥ 3) it shares its map as part of the same safe-conduct ritual.

The point is REACTION, not bigger numbers: hunters scale gently with the floor and
diplomacy removes exactly one weak enemy. Power here is *configuration* — which faction
you provoke and which you court — and it is lossy.
"""
from __future__ import annotations

import random

from runtime.dungeon import free_floor_tiles
from runtime.entities import make_enemy
from runtime.systems import System

LOUD_CAUSES = ("melee", "sigil")  # heard by the faction; environment kills are quiet

# faction standing perks — ranked unlocks from reputation thresholds
_FACTION_PERK_TABLE = {
    "default": [
        (1, "kin_calm"),       # standing 1+: faction creatures deal -1 damage to you
        (2, "hunter_vision"),  # standing 2+: see hunters on overworld map
        (3, "call_ally"),      # standing 3+: one friendly creature per floor
        (4, "threshold"),      # standing 4+: anchor door opens (terrain mod)
    ],
}

def _has_perk(standing: int, fac_id: str, perk_name: str) -> bool:
    perks = _FACTION_PERK_TABLE.get(fac_id, _FACTION_PERK_TABLE["default"])
    for rank, name in perks:
        if name == perk_name and standing >= rank:
            return True
    return False


class FactionSystem(System):
    name = "factions"

    def __init__(self):
        self.disturbance: dict[str, int] = {}
        self.standing: dict[str, int] = {}
        self._names: dict[str, str] = {}
        self._relations: dict[str, list] = {}
        self._built = False
        self._game = None
        self._allies_called: set = set()     # factions whose ally has been summoned this floor

    # ---- lookup construction ---------------------------------------------------
    def _build(self, game):
        self._game = game
        if self._built:
            return
        for f in game.m.get("bible", {}).get("factions", []):
            fid = f["id"]
            self._names[fid] = f.get("name", fid)
            self._relations[fid] = [
                (r["factionId"], r.get("stance", "neutral"))
                for r in f.get("relations", [])
            ]
        self._built = True

    def on_world_start(self, game):
        self._build(game)

    def on_floor_enter(self, game):
        self._allies_called = set()   # reset per floor

    def faction_name(self, fid):
        if not fid:
            return "Unknown"
        return self._names.get(fid, fid)

    def faction_perk(self, fac_id: str, perk_name: str) -> bool:
        """Check if the player has unlocked a specific faction perk at current standing."""
        return _has_perk(self.standing_of(fac_id), fac_id, perk_name)

    # ---- query API (INTERACTIONS_SPEC.md) -------------------------------------
    def faction_of(self, note_id):
        """The faction that owns a note = faction_{its graph community}.

        Returns None for a missing note or an unclustered one (community -1)."""
        if not note_id or self._game is None:
            return None
        node = self._game.m.get("graph", {}).get("nodes", {}).get(note_id)
        if not node:
            return None
        comm = node.get("community", -1)
        if comm is None or comm == -1:
            return None
        return f"faction_{comm}"

    def standing_of(self, faction_id) -> int:
        """Current favor with a faction (0 if never interacted with)."""
        return self.standing.get(faction_id, 0)

    # ---- helpers ---------------------------------------------------------------
    def _current_region_id(self, game):
        region = game.region_for(game.floor)
        return region.get("id", "") if region else ""

    def _deeper_region_id(self, game):
        """A region the player hasn't reached yet — what scavenged intel is actually
        worth (the current region is already mapped on arrival, so revealing it is a
        no-op). Prefer the nearest zone below the current floor; else the endgame."""
        cur = self._current_region_id(game)
        regions = game.m.get("regions", [])
        ahead = [r for r in regions if r.get("depthBand", [1, 1])[0] > game.floor]
        if ahead:
            return min(ahead, key=lambda r: r["depthBand"][0]).get("id", "")
        deepest = max(regions, key=lambda r: r.get("depthBand", [1, 1])[1], default=None)
        rid = deepest.get("id", "") if deepest else ""
        return rid if rid != cur else ""

    @staticmethod
    def _is_hunter(enemy) -> bool:
        """A creature we dispatched: flagged at spawn, or named 'Hunter of ...'."""
        if getattr(enemy, "is_hunter", False):
            return True
        name = getattr(enemy, "name", "") or ""
        return name.startswith("Hunter of ")

    def _share_map(self, game, region_id):
        """None-guarded scavenge/share into the knowledge system."""
        if not region_id:
            return False
        kn = game.system("knowledge")
        reveal = getattr(kn, "reveal", None) if kn is not None else None
        if not callable(reveal):
            return False
        reveal(region_id)
        return True

    # ---- kills feed the diplomacy graph (via the bus) -------------------------
    def on_event(self, game, etype, data):
        if etype != "enemy_killed":
            return
        self._build(game)
        enemy = data.get("enemy")
        if enemy is None:
            return
        cause = data.get("cause", "melee")
        if cause in LOUD_CAUSES:
            self._loud_kill(game, enemy)
        elif cause == "environment":
            self._quiet_kill(game, enemy)
        else:                       # unknown cause: treat conservatively as heard
            self._loud_kill(game, enemy)

    def _loud_kill(self, game, enemy):
        """A heard kill: alert rises, the victim faction sours, its foes are pleased."""
        fac = self.faction_of(getattr(enemy, "source", ""))
        if fac:
            self.disturbance[fac] = self.disturbance.get(fac, 0) + 1
            self.standing[fac] = self.standing.get(fac, 0) - 1
            s = self.standing[fac]
            game.emit("standing_changed", faction=fac, standing=s)
            # antagonizing a faction pleases everyone who already opposes it
            for other, stance in self._relations.get(fac, []):
                if stance in ("rival", "war"):
                    self.standing[other] = self.standing.get(other, 0) + 1
            game.log(f"The clamor carries; {self.faction_name(fac)} take note.")
        # Hunter intel: a loud hunter kill scavenges its sensors → reveal the floor.
        if self._is_hunter(enemy):
            got = self._share_map(game, self._current_region_id(game))
            self._share_map(game, self._deeper_region_id(game))  # pre-map a region ahead
            if got:
                game.log("You strip the hunter's sensors; a region ahead loads.")

    def _quiet_kill(self, game, enemy):
        """An environment kill the faction never witnesses: no alarm, alert cools."""
        fac = self.faction_of(getattr(enemy, "source", ""))
        if fac and self.disturbance.get(fac, 0) > 0:
            # nobody reports in; the search loses a thread
            self.disturbance[fac] = max(0, self.disturbance[fac] - 1)
        name = getattr(enemy, "name", "a creature")
        game.log(f"{name} dies unseen; no one comes looking.")

    # ---- the world reacts on the next descent ---------------------------------
    def on_floor_enter(self, game):
        self._build(game)
        rng = random.Random(f"{game.seed}:{game.floor}:factions")
        region = game.region_for(game.floor)
        anchor = region.get("sourceNoteId", "")
        region_id = region.get("id", "")

        # --- Escalation: a sufficiently disturbed faction sends hunters ---
        tier = min(5, 1 + game.floor // 4)
        for fac in list(self.disturbance.keys()):
            if self.disturbance.get(fac, 0) < 4:
                continue
            # Phase 3: Standing favor — call off hunters if a faction trusts you
            caller = None
            for fid, standing in list(self.standing.items()):
                if standing >= 4 and fid != fac:
                    caller = fid
                    break
            if caller:
                self.standing[caller] -= 2
                fname = self.faction_name(fac)
                cname = self.faction_name(caller)
                game.log(f"{cname} intervenes — the hunters of {fname} stand down. "
                         f"({cname} standing: {self.standing[caller]}).")
                self.disturbance[fac] = max(0, self.disturbance[fac] - 4)
                continue
            fname = self.faction_name(fac)
            count = rng.randint(1, 2)
            free = free_floor_tiles(
                game.level, {(game.player.x, game.player.y), game.level.stairs}
                | {(a.x, a.y) for a in game.actors})   # don't dispatch onto an occupied tile
            rng.shuffle(free)
            spawned = 0
            for _ in range(count):
                if not free:
                    break
                x, y = free.pop()
                hunter = make_enemy({
                    "name": f"Hunter of {fname}",
                    "archetype": "warden",
                    "tier": tier,
                    "damageType": "blade",
                    "regionId": region_id,
                    "sourceNoteId": anchor,
                }, x, y)
                hunter.glyph = "H"
                hunter.name = f"Hunter of {fname}"
                hunter.faction = fac   # it hunts FOR its house; kin and rivals apply
                hunter.is_hunter = True  # detected on death → sensor scavenge (intel)
                game.actors.append(hunter)
                spawned += 1
            if spawned:
                game.log(f"⚔ {fname} dispatches hunters.")
            self.disturbance[fac] = 0  # alert spent

        # --- Diplomacy (water-ritual): a region that favors you grants passage ---
        cur = region.get("factionId")
        if cur and self.standing_of(cur) >= 3:
            # Shared map: a trusting faction hands you its survey — here and ahead.
            self._share_map(game, self._deeper_region_id(game))
            if self._share_map(game, region_id):
                game.log(f"{self.faction_name(cur)} share their maps with you.")
            foes = [a for a in game.actors
                    if not a.is_player and not a.is_boss and a.hp > 0]
            if foes:
                weakest = min(foes, key=lambda a: a.hp)
                game.actors.remove(weakest)
                game.log(f"{self.faction_name(cur)} let you pass.")

    # ---- HUD -------------------------------------------------------------------
    def status_line(self, game):
        """Every house you have history with (plus the local one), friendship
        marked -- reputation is a real economy, so it must be visible."""
        from runtime.game import FRIEND_STANDING
        region = game.region_for(game.floor)
        cur = region.get("factionId", "")
        shown = sorted({f for f, v in self.standing.items() if v} | ({cur} - {""}))
        if not shown:
            shown = [cur] if cur else []
        parts = []
        for f in shown:
            v = self.standing.get(f, 0)
            nm = self.faction_name(f).replace("House ", "")[:10]
            mark = "♥" if v >= FRIEND_STANDING else ""
            sigil = "+ " if v >= 0 else (". " if v > -4 else "- ")
            parts.append(f"{sigil}{nm} {v:+d}{mark}")
        return ("Houses: " + " · ".join(parts)) if parts else None

    def on_interact(self, game) -> bool:
        px, py = game.player.x, game.player.y
        decay = game.system("decay")
        if decay is None:
            return False
        if not decay.corpse_at(px, py):
            return False
        fac = self._corpse_faction(game, px, py)
        if not fac:
            game.log("This fallen one held no allegiance.")
            return False
        decay.consume(px, py)
        self.standing[fac] = self.standing.get(fac, 0) + 1
        game.emit("standing_changed", faction=fac, standing=self.standing[fac])
        game.log(f"You honour the fallen. {self.faction_name(fac)} will remember.")
        return True

    def _corpse_faction(self, game, x, y):
        for a in game.actors:
            if a.x == x and a.y == y and a.hp <= 0:
                return getattr(a, "faction", "")
        return ""
