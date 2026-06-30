"""Quests — your unfinished `- [ ]` TODOs, made into dungeon objectives.

Every quest in the manifest (`game.m["quests"]`) is a transformed TODO: `{id, objective,
kind, sourceNoteId}` with `kind ∈ {fetch, slay, escort, cleanse, recover}`. The *objective*
text is the note's charge ("Unmake the Marginal Annex …"); this system binds each abstract
kind to a CONCRETE, checkable condition grounded in the live world:

  - slay    -> kill the boss whose `sourceNoteId` is graph-nearest the quest's note
              (we store the boss id + its source note);
  - recover -> accrue N total `matter` (`inv(game.player).total()`);
  - fetch /
    escort  -> reach a target region (a floor inside its `depthBand`) or descend ≥ N floors;
  - cleanse -> no hostile enemies remain on the current floor.

Quests start inactive; an NPC `offer(game)`s them one at a time (NPCs in the dialogue
layer call this). Active quests are watched on the bus + lifecycle hooks; when an objective
is met we log `Quest complete: <objective>` and grant a deterministic reward (faction
standing, recovered matter, or a revealed region — whichever fits the kind, with a matter
fallback so a reward always lands).

Opt-in System: registered explicitly, so the bare game/tests are untouched. Pure stdlib,
deterministic (graph distance + hash-derived targets), and every cross-system call is
None-guarded.
"""
from __future__ import annotations

import hashlib
from collections import deque

from runtime.components import inv, world_materials
from runtime.systems import System

# how many distinct quests a single offer-chain will hand out before repeating None
REACH_KINDS = ("fetch", "escort")


def _h(*parts) -> int:
    """Stable positive hash of the given parts (deterministic across runs)."""
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


class QuestSystem(System):
    name = "quests"

    def __init__(self):
        self.quests: list = []          # bound quest dicts (manifest order)
        self.active: list = []           # subset currently being tracked
        self.completed: set = set()      # ids of finished quests
        self._slain_bosses: set = set()  # sourceNoteIds of bosses the player has killed
        self._built = False
        self.game = None                 # stashed for the param-less query API

    # ---- lifecycle ----------------------------------------------------------
    def on_world_start(self, game):
        self.game = game
        self._load(game)

    def on_floor_enter(self, game):
        self.game = game
        self._load(game)
        # arriving on a new floor can satisfy reach (fetch/escort) and cleanse objectives
        self._check(game)

    def on_player_act(self, game):
        self.game = game
        # matter growth (recover) and the floor going quiet (cleanse) are observed here
        self._check(game)

    def on_enemy_killed(self, game, enemy):
        # the bus also delivers this as `enemy_killed`; record here too for robustness
        self._record_kill(enemy)

    # ---- loading & binding --------------------------------------------------
    def _load(self, game):
        """Load `game.m["quests"]` once, binding each to a concrete objective by kind."""
        if self._built:
            return
        self.game = game
        for raw in (game.m.get("quests", []) or []):
            q = dict(raw)                       # copy; never mutate the manifest
            self._bind(game, q)
            self.quests.append(q)
        self._built = True

    def _bind(self, game, q):
        """Attach checkable binding fields to a quest dict, keyed off its `kind`."""
        kind = q.get("kind")
        note = q.get("sourceNoteId", "")
        if kind == "slay":
            boss = self._nearest_boss(game, note)
            if boss is not None:
                q["target_source"] = boss.get("sourceNoteId", "")
                q["target_boss_id"] = boss.get("id", "")
                q["region_id"] = boss.get("regionId", "")
        elif kind == "recover":
            # a modest, deterministic matter goal (2..5) — reachable in a normal descent
            q["need"] = 2 + _h("recover", q.get("id", "")) % 4
            q["region_id"] = self._region_id_for_note(game, note)
        elif kind in REACH_KINDS:
            region = self._nearest_region(game, note)
            if region is not None:
                band = region.get("depthBand", [1, 1]) or [1, 1]
                q["region_id"] = region.get("id", "")
                q["band"] = [band[0], band[-1]]
                q["descend_to"] = band[0]
        elif kind == "cleanse":
            q["region_id"] = self._region_id_for_note(game, note)
        return q

    # ---- graph helpers ------------------------------------------------------
    def _nodes(self, game):
        return game.m.get("graph", {}).get("nodes", {}) or {}

    def _graph_dist(self, game, a, b):
        """BFS distance over the vault's link graph; inf if unreachable."""
        if not a or not b:
            return float("inf")
        if a == b:
            return 0
        nodes = self._nodes(game)
        seen = {a}
        dq = deque([(a, 0)])
        while dq:
            cur, d = dq.popleft()
            node = nodes.get(cur)
            if not node:
                continue
            for nb in node.get("neighbors", []) or []:
                if nb == b:
                    return d + 1
                if nb not in seen:
                    seen.add(nb)
                    dq.append((nb, d + 1))
        return float("inf")

    def _nearest_boss(self, game, note):
        """The boss whose source note is graph-nearest `note` (ties: shallower, then id)."""
        bosses = game.m.get("bosses", []) or []
        if not bosses:
            return None
        return min(
            bosses,
            key=lambda b: (self._graph_dist(game, note, b.get("sourceNoteId", "")),
                           b.get("depth", 0), b.get("id", "")),
        )

    def _nearest_region(self, game, note):
        """The region whose anchor note is graph-nearest `note` (ties: shallower band)."""
        regions = game.m.get("regions", []) or []
        if not regions:
            return None
        return min(
            regions,
            key=lambda r: (self._graph_dist(game, note, r.get("sourceNoteId", "")),
                           (r.get("depthBand", [1, 1]) or [1, 1])[0], r.get("id", "")),
        )

    def _region_id_for_note(self, game, note):
        r = self._nearest_region(game, note)
        return r.get("id", "") if r is not None else ""

    # ---- bus ----------------------------------------------------------------
    def on_event(self, game, etype, data):
        self.game = game
        data = data or {}
        if etype == "enemy_killed":
            self._record_kill(data.get("enemy"))
        # `enemy_killed`, `actor_died`, a floor going quiet, or a plain tick can all move
        # an active objective forward — re-evaluate them on every event.
        self._check(game)

    def _record_kill(self, enemy):
        if enemy is None:
            return
        if getattr(enemy, "is_boss", False):
            src = getattr(enemy, "source", "")
            if src:
                self._slain_bosses.add(src)

    # ---- objective evaluation ----------------------------------------------
    def _check(self, game):
        if game is None:
            return
        for q in list(self.active):
            if q.get("id") in self.completed:
                continue
            if self._satisfied(game, q):
                self._complete(game, q)

    def _satisfied(self, game, q) -> bool:
        kind = q.get("kind")
        if kind == "slay":
            return bool(q.get("target_source")) and q["target_source"] in self._slain_bosses
        if kind == "recover":
            player = getattr(game, "player", None)
            if player is None:
                return False
            return inv(player).total() >= q.get("need", 1)
        if kind in REACH_KINDS:
            band = q.get("band")
            floor = getattr(game, "floor", 0)
            if band and band[0] <= floor <= band[1]:
                return True
            return floor >= q.get("descend_to", float("inf"))
        if kind == "cleanse":
            return self._floor_clear(game)
        return False

    @staticmethod
    def _floor_clear(game) -> bool:
        """True when no living, faction-hostile (`monster`) actor remains on the floor."""
        for a in getattr(game, "actors", []) or []:
            if getattr(a, "allegiance", "") == "monster" and getattr(a, "hp", 0) > 0:
                return False
        return True

    def _complete(self, game, q):
        self.completed.add(q.get("id"))
        if q in self.active:
            self.active.remove(q)
        game.log(f"Quest complete: {q.get('objective', '')}")
        self._grant_reward(game, q)

    # ---- rewards (deterministic; one per kind, with a matter fallback) ------
    def _grant_reward(self, game, q):
        kind = q.get("kind")
        applied = False
        if kind == "slay":
            # the warden's faction owes you safe-conduct: standing rises
            fid = self._faction_for_region(game, q.get("region_id"))
            if self._raise_standing(game, fid, 2):
                q["reward"] = f"standing +2 with {fid}"
                applied = True
        elif kind == "cleanse" or kind in REACH_KINDS:
            # you mapped/secured the place: its region loads onto the knowledge frontier
            if self._reveal(game, q.get("region_id")):
                q["reward"] = f"revealed {q.get('region_id')}"
                applied = True
        # recover (and any reward whose system was absent) pays out in recovered matter
        if not applied:
            mat, amt = self._grant_matter(game, q)
            q["reward"] = f"+{amt} {mat}"
            applied = True
        q["reward_applied"] = applied
        game.log(f"You are rewarded: {q.get('reward', 'nothing')}.")
        return applied

    def _grant_matter(self, game, q):
        mats = world_materials(game) or ["scrap"]
        mat = mats[_h("reward", q.get("id", "")) % len(mats)]
        amt = 2 + _h("amt", q.get("id", "")) % 2   # 2..3, deterministic
        player = getattr(game, "player", None)
        if player is not None:
            inv(player).add({mat: amt})
        return mat, amt

    def _faction_for_region(self, game, rid):
        if not rid:
            return None
        for r in game.m.get("regions", []) or []:
            if r.get("id") == rid:
                return r.get("factionId")
        return None

    def _raise_standing(self, game, fid, k) -> bool:
        if not fid:
            return False
        fac = game.system("factions") if game is not None else None
        standing = getattr(fac, "standing", None) if fac is not None else None
        if standing is None:
            return False
        standing[fid] = standing.get(fid, 0) + k
        return True

    def _reveal(self, game, target) -> bool:
        if not target:
            return False
        kn = game.system("knowledge") if game is not None else None
        reveal = getattr(kn, "reveal", None) if kn is not None else None
        if not callable(reveal):
            return False
        reveal(target)
        return True

    # ---- offer / query API --------------------------------------------------
    def offer(self, game):
        """Activate and return the next not-yet-active, not-yet-completed quest.

        NPCs call this to entrust a charge to the player. Returns the bound quest dict,
        or None when every quest is already active or completed."""
        self.game = game
        self._load(game)
        for q in self.quests:
            if q.get("id") in self.completed:
                continue
            if any(a.get("id") == q.get("id") for a in self.active):
                continue
            self.active.append(q)
            game.log(f"New charge: {q.get('objective', '')}")
            return q
        return None

    def status_line(self, game):
        return f"Quests: {len(self.completed)}/{len(self.quests)}"
