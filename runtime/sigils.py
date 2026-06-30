"""Sigils — Cogmind's "you are your configuration, lossily" applied to notes.

The anti-power-creep core. Power is not bigger numbers; it is a few slotted *verbs*
(utility, never flat damage) drawn from the notes of the region you are walking through.
Every ability is LOSSY: each time it fires it loses durability, and at zero the sigil
shatters and is gone for good — the part-loss feel of Cogmind.

A sigil's ability comes from the graph *role* of its source note:
    hub -> Recall   bridge -> Phase   cluster -> Rally   leaf -> Ward   orphan -> Echo

Self-contained System: reads game state, mutates only through the public Game API
(player.hp, game.actors, player position, game.alive, game.log), draws via render_overlay.
"""
from __future__ import annotations

import random

from runtime.dungeon import free_floor_tiles
from runtime.systems import System
from runtime import quality

# node graph-role -> sigil ability
ROLE_ABILITY = {
    "hub": "Recall",
    "bridge": "Phase",
    "cluster": "Rally",
    "leaf": "Ward",
    "orphan": "Echo",
}

SIGIL_GLYPH = "$"
MAX_SLOTS = 3
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))

# --- quality perks --------------------------------------------------------- #
# Registered at import so the QualitySystem can grant them (one per tier). Factorio-
# style grades are utility, NOT flat damage: stat perks nudge a value the abilities
# already read; passive perks are flags the abilities interpret where they fire.
#   stat    -> apply(sigil) mutates the dict immediately when the perk is granted.
#   passive -> apply is None; the sigil dict just carries the name in ["perks"].
# `mag` is the effect-magnitude the abilities read (default 1); `keen` raises it.
quality.register_perk(
    "reinforced", "stat",
    lambda s: s.__setitem__("durability", s.get("durability", 2) + 1))   # +1 use
quality.register_perk(
    "keen", "stat",
    lambda s: s.__setitem__("mag", s.get("mag", 1) + 1))                  # +1 magnitude
quality.register_perk("ward_reach", "passive", None)      # Ward shoves 2 tiles, not 1
quality.register_perk("phase_decoy", "passive", None)     # Phase leaves a decoy lure
quality.register_perk("recall_cleanse", "passive", None)  # Recall also clears feared
quality.register_perk("thrifty", "passive", None)         # 1-in-2 uses cost no durability
quality.register_perk("echo_twin", "passive", None)       # Echo revives at 2 hp, not 1


class SigilSystem(System):
    name = "sigils"

    def __init__(self):
        # each slot / ground sigil: {note, role, ability, durability}
        self.slots: list[dict] = []
        self.ground: dict = {}          # (x, y) -> sigil
        self.rng = random.Random(0)

    # ---- lifecycle ----------------------------------------------------------
    def on_world_start(self, game):
        self.slots = []
        self.ground = {}

    def on_floor_enter(self, game):
        # One deterministic stream per floor (placement + any phase blinks).
        self.rng = random.Random(f"{game.seed}:{game.floor}:sigils")
        self._place(game)
        # passive / on-arrival effects from already-slotted sigils
        self._recall(game)
        self._rally(game)

    def on_player_act(self, game):
        # Echo is a one-shot save: it must run even though the player is "dead".
        if not game.alive:
            self._echo(game)
            return
        self._pickup(game)
        self._ward(game)
        self._phase(game)
        self._corrode(game)

    # ---- placement ----------------------------------------------------------
    def _region_community(self, game):
        region = game.region_for(game.floor)
        fid = region.get("factionId", "")
        if isinstance(fid, str) and fid.startswith("faction_"):
            try:
                return int(fid[len("faction_"):])
            except ValueError:
                pass
        src = region.get("sourceNoteId")
        node = game.m["graph"]["nodes"].get(src)
        if node is not None:
            return node.get("community")
        return None

    def _make_sigil(self, note_id: str, node: dict) -> dict:
        role = node.get("role")
        ability = ROLE_ABILITY.get(role, "Echo")
        durability = 1 if ability == "Echo" else 2
        # `base` is the dispatch verb; `ability` is the display name that quality may
        # prefix (e.g. "Epic Ward"). Effects route through _ab() so any tier still slots.
        return {"note": note_id, "role": role, "ability": ability,
                "base": ability, "durability": durability}

    def _place(self, game):
        self.ground = {}
        nodes = game.m["graph"]["nodes"]
        comm = self._region_community(game)
        candidates = [(nid, n) for nid, n in nodes.items()
                      if n.get("community") == comm]
        if not candidates:                       # defensive fallback
            candidates = list(nodes.items())
        if not candidates:
            return

        count = min(self.rng.randint(1, 2), len(candidates))
        chosen = self.rng.sample(candidates, count)

        exclude = {(game.player.x, game.player.y), game.level.stairs}
        exclude |= {(a.x, a.y) for a in game.actors}
        exclude |= {(it.x, it.y) for it in game.items}
        tiles = free_floor_tiles(game.level, exclude)
        self.rng.shuffle(tiles)

        # None-guard quality: no QualitySystem registered -> sigils stay Normal (0/[]),
        # behaving exactly as before. A picked-up sigil is the same dict moved into a
        # slot, so it is qualified here at birth and never re-qualified at slot time.
        q = game.system("quality")
        for (nid, node), pos in zip(chosen, tiles):
            sigil = self._make_sigil(nid, node)
            if q is not None:
                q.qualify_sigil(game, sigil)   # tier + per-tier perks; stat perks now
            self.ground[pos] = sigil

    # ---- pickup / inventory -------------------------------------------------
    def _title(self, game, sigil) -> str:
        node = game.m["graph"]["nodes"].get(sigil["note"], {})
        return node.get("title", sigil["note"])

    def _pickup(self, game):
        pos = (game.player.x, game.player.y)
        sigil = self.ground.pop(pos, None)
        if sigil is None:
            return
        title = self._title(game, sigil)
        if len(self.slots) < MAX_SLOTS:
            self.slots.append(sigil)
            game.log(f"You slot the {sigil['ability']} sigil of {title}.")
        else:
            weakest = min(self.slots, key=lambda s: s["durability"])
            self.slots.remove(weakest)
            self.slots.append(sigil)
            game.log(f"You discard your worn {weakest['ability']} sigil for "
                     f"the {sigil['ability']} sigil of {title}.")

    # ---- lossiness ----------------------------------------------------------
    def _consume(self, game, sigil):
        """One use of an active effect (or one Recall floor). Shatter at 0."""
        # 'thrifty' (a quality passive): every other use is free, deterministically.
        if "thrifty" in sigil.get("perks", []):
            sigil["_uses"] = sigil.get("_uses", 0) + 1
            if sigil["_uses"] % 2 == 0:
                game.log(f"Your {sigil['ability']} sigil holds together (thrifty).")
                return
        sigil["durability"] -= 1
        if sigil["durability"] <= 0:
            if sigil in self.slots:
                self.slots.remove(sigil)
            game.log(f"Your {sigil['ability']} sigil shatters.")
            game.emit("broke", kind="sigil", source=sigil.get("note", ""),
                      name=sigil["ability"], tier=1,
                      pos=(game.player.x, game.player.y))   # shards are salvageable

    def _ab(self, sigil) -> str:
        """The dispatch verb for a sigil, immune to a quality name-prefix. qualify_sigil
        prefixes the *display* name (e.g. 'Epic Ward'); abilities still match the bare
        verb (via stored `base`, else by stripping a leading tier word)."""
        base = sigil.get("base")
        if base:
            return base
        ability = sigil.get("ability", "")
        head, _, tail = ability.partition(" ")
        return tail if (tail and head in quality.NAMES) else ability

    def _first(self, ability):
        return next((s for s in self.slots if self._ab(s) == ability), None)

    # ---- effects ------------------------------------------------------------
    def _recall(self, game):
        # hub, passive: heal a little each floor; the sigil wears with every floor.
        for s in [x for x in self.slots if self._ab(x) == "Recall"]:
            p = game.player
            amount = 6 + 2 * (s.get("mag", 1) - 1)        # 'keen' (mag) scales the mend
            healed = min(p.max_hp, p.hp + amount) - p.hp
            p.hp += healed
            game.log(f"The Recall sigil mends you (+{healed} HP).")
            if "recall_cleanse" in s.get("perks", []):
                # also wash away the player's learned dreads (memory may be absent)
                try:
                    from runtime.memory import mem
                    mem(p).feared.clear()
                    game.log("Recall washes away your remembered fears.")
                except Exception:
                    pass
            self._consume(game, s)

    def _rally(self, game):
        # cluster: pacify the single lowest-hp enemy on the floor.
        for s in [x for x in self.slots if self._ab(x) == "Rally"]:
            foes = [a for a in game.actors
                    if a.allegiance == "monster" and a.hp > 0 and not a.is_boss]
            if not foes:
                continue
            victim = min(foes, key=lambda a: a.hp)   # a real enemy, not a critter or boss
            game.actors.remove(victim)
            game.log(f"{victim.name} answers your call and stands aside.")
            self._consume(game, s)

    def _can_shove_to(self, game, p, bx, by) -> bool:
        # a legal destination for a shoved enemy: open floor, unoccupied, not the player
        return (game.level.walkable(bx, by) and game.actor_at(bx, by) is None
                and (bx, by) != (p.x, p.y))

    def _shove_path(self, game, p, a, mx, my, dist, r):
        """Slide enemy `a` up to `dist` tiles along (mx, my). Returns (dest, hazard):
        `dest` is the farthest legal tile reached (or None if blocked at once); `hazard`
        is the first hazard tile reached (stopping there) or None. Each step must be a
        legal shove tile, so a 2-tile push never tunnels through walls/actors."""
        dest = None
        hazard = None
        cx, cy = a.x, a.y
        for _ in range(max(1, dist)):
            cx, cy = cx + mx, cy + my
            if not self._can_shove_to(game, p, cx, cy):
                break
            dest = (cx, cy)
            if r is not None and r.is_hazard(cx, cy):
                hazard = (cx, cy)
                break
        return dest, hazard

    def _element_name(self, game, r, x, y) -> str:
        # flavor name of the hazard underfoot; guarded — reactions may be absent
        if r is not None:
            el = r.element_at(x, y)
            if el:
                return el
        return "hazard"

    def _ward(self, game):
        # leaf: under pressure (>=2 adjacent), shove the press back -- and, if a hazard
        # lies in a shove direction, shove the enemy ONTO it so reactions does the killing.
        ward = self._first("Ward")
        if ward is None:
            return
        p = game.player
        adj = []
        for dx, dy in _ORTHO:
            a = game.actor_at(p.x + dx, p.y + dy)
            if a is not None:
                adj.append((a, dx, dy))
        if len(adj) < 2:
            return
        # reactions partner may be unregistered; None-guard every call to it
        r = game.system("reactions")
        # 'ward_reach' (a quality passive) doubles the shove distance.
        reach = 2 if "ward_reach" in ward.get("perks", []) else 1
        shoved = False
        for a, dx, dy in adj:
            # prefer the natural away push, then any other orthogonal escape
            dirs = [(dx, dy)] + [d for d in _ORTHO if d != (dx, dy)]
            away_dest = None
            hazard_dest = None
            for mx, my in dirs:
                dest, hazard = self._shove_path(game, p, a, mx, my, reach, r)
                if dest is None:
                    continue
                if away_dest is None and (mx, my) == (dx, dy):
                    away_dest = dest
                if hazard is not None:
                    hazard_dest = hazard
                    break
            if hazard_dest is not None:
                a.x, a.y = hazard_dest
                elem = self._element_name(game, r, *hazard_dest)
                game.log(f"Your ward shoves {a.name} toward the {elem}.")
                shoved = True
            elif away_dest is not None:
                a.x, a.y = away_dest
                shoved = True
        if shoved:
            game.log("Your ward repels the press.")
            self._consume(game, ward)

    def _phase(self, game):
        # bridge: if boxed in (no walkable, enemy-free neighbor), blink away.
        phase = self._first("Phase")
        if phase is None:
            return
        p = game.player
        for dx, dy in _ORTHO:
            nx, ny = p.x + dx, p.y + dy
            if game.level.walkable(nx, ny) and game.actor_at(nx, ny) is None:
                return  # has an escape; not boxed in
        exclude = {(p.x, p.y), game.level.stairs}
        exclude |= {(a.x, a.y) for a in game.actors}
        tiles = free_floor_tiles(game.level, exclude)
        if not tiles:
            return
        old = (p.x, p.y)
        p.x, p.y = self.rng.choice(tiles)
        game.log("You phase through the wall.")
        if "phase_decoy" in phase.get("perks", []):
            # leave a flickering after-image that draws attention to the old tile
            game.log("A phantom of you lingers as a decoy.")
            game.emit("noise", pos=old, volume=6)   # harmless if no system listens
        self._consume(game, phase)

    def _echo(self, game):
        # orphan: one-shot save — soak the killing blow once.
        echo = self._first("Echo")
        if echo is None:
            return
        game.alive = True
        # 'echo_twin' (a quality passive) brings you back a touch sturdier.
        game.player.hp = 2 if "echo_twin" in echo.get("perks", []) else 1
        game.log("An echo of you takes the blow.")
        self._consume(game, echo)

    def _corrode(self, game):
        # EM corruption: standing on/next to a 'charged' tile frays a slotted sigil,
        # draining 1 durability (and shattering it if that empties it).
        if not self.slots:
            return
        r = game.system("reactions")          # partner may be absent -> None-guard
        if r is None:
            return
        p = game.player
        charged = False
        for mx, my in ((0, 0),) + _ORTHO:
            props = r.props_at(p.x + mx, p.y + my)
            if props and "charged" in props:
                charged = True
                break
        if not charged:
            return
        # deterministic victim from the per-floor seeded stream
        victim = self.rng.choice(self.slots)
        game.log(f"EM corruption frays your {victim['ability']}.")
        self._consume(game, victim)           # normal shatter handling at 0

    # ---- query API ----------------------------------------------------------
    def has_ability(self, name) -> bool:
        """True if any slotted sigil grants `name` (used by partners for flavor)."""
        return any(self._ab(s) == name for s in self.slots)

    # ---- presentation -------------------------------------------------------
    def render_overlay(self, game, grid):
        h = len(grid)
        w = len(grid[0]) if h else 0
        for (x, y), _sig in self.ground.items():
            if 0 <= y < h and 0 <= x < w and grid[y][x] == ".":
                grid[y][x] = SIGIL_GLYPH

    def status_line(self, game):
        if not self.slots:
            return "Sigils: [0/3]"
        parts = " ".join(f"{s['ability']}({s['durability']})" for s in self.slots)
        return f"Sigils: {parts} [{len(self.slots)}/{MAX_SLOTS}]"
