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

# modular property vector — enum of all possible sigil properties
_PROP_NAMES = ("durability", "magnitude", "reach", "decoy", "cleanse",
               "thrifty", "twin", "fire_resist", "cold_resist", "shock_resist")
_PROP_IDX = {n: i for i, n in enumerate(_PROP_NAMES)}


def _props(sigil: dict) -> list[int]:
    """Return the property vector for a sigil (creates if absent).
    Backward-compatible: converts old 'perks' list on first access."""
    if "props" not in sigil:
        sigil["props"] = [0] * len(_PROP_NAMES)
        # migrate old perk names to new prop indices
        _OLD_MAP = {"reinforced": "durability", "keen": "magnitude",
                    "ward_reach": "reach", "phase_decoy": "decoy",
                    "recall_cleanse": "cleanse", "thrifty": "thrifty",
                    "echo_twin": "twin"}
        for perk in sigil.pop("perks", []):
            prop = _OLD_MAP.get(perk, perk)
            if prop in _PROP_IDX:
                sigil["props"][_PROP_IDX[prop]] = 1
    return sigil["props"]


def _prop(sigil: dict, name: str) -> int:
    """Read one property value O(1)."""
    ps = sigil.get("props")
    if ps is None:
        return 0
    return ps[_PROP_IDX.get(name, -1)] if name in _PROP_IDX else 0


def _add_prop(sigil: dict, name: str, val: int = 1):
    """Add a property value to a sigil."""
    ps = sigil.get("props")
    if ps is not None and name in _PROP_IDX:
        ps[_PROP_IDX[name]] += val

# --- quality perks (now registered into the property vector) ---
quality.register_perk(
    "reinforced", "stat",
    lambda s: (s.__setitem__("durability", s.get("durability", 2) + 1),
               _props(s).__setitem__(_PROP_IDX["durability"],
               _prop(s, "durability") + 1))[0])
quality.register_perk(
    "keen", "stat",
    lambda s: _props(s).__setitem__(_PROP_IDX["magnitude"],
                                    _prop(s, "magnitude") + 1))
quality.register_perk("ward_reach", "passive", None)     # reach prop checked in _ward
quality.register_perk("phase_decoy", "passive", None)     # decoy prop checked in _phase
quality.register_perk("recall_cleanse", "passive", None)   # cleanse prop
quality.register_perk("thrifty", "passive", None)          # thrifty prop
quality.register_perk("echo_twin", "passive", None)        # twin prop


class SigilSystem(System):
    name = "sigils"

    def __init__(self):
        # each slot / ground sigil: {note, role, ability, durability}
        self.slots: list[dict] = []
        self.ground: dict = {}          # (x, y) -> sigil
        self.rng = random.Random(0)
        self._seen: set[str] = set()   # ability types whose tutorial was shown

    # ---- lifecycle ----------------------------------------------------------
    def on_world_start(self, game):
        self.slots = []
        self.ground = {}
        self.slots.append({"note": "__starter__", "role": "leaf",
                            "ability": "Ward", "base": "Ward",
                            "durability": 2, "quality": 0})
        self._seen = set()
        game.log("You feel a Ward within you — press c to cast; it pushes threats away.")

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
        cap = self.max_slots(game)
        if cap > getattr(self, "_last_cap", MAX_SLOTS):
            self._last_cap = cap
            game.log(f"Your grasp widens with understanding: "
                     f"you can bear {cap} sigils now.")
        self._pickup(game)
        self._ward(game)
        self._phase(game)
        self._corrode(game)

    def on_event(self, game, etype, data):
        # Cogmind's circle: a capable creature's fall leaves its PART. The node
        # is a slottable, lossy sigil carrying that body's own verb.
        if etype != "actor_died":
            return
        actor = (data or {}).get("actor")
        acts = getattr(actor, "_special_actions", None) if actor is not None else None
        if not acts:
            return
        pos = (data or {}).get("pos", (actor.x, actor.y))
        ability = sorted(acts)[0].title()
        self.ground[pos] = {"note": getattr(actor, "source", ""), "role": "part",
                            "ability": ability, "base": ability, "durability": 2,
                            "part": True}
        game.log(f"Something of {actor.name} survives: a {ability} node ($).")

    # ---- capacity: understanding widens what you can bear (Cogmind evolve) ---
    def max_slots(self, game) -> int:
        know = game.system("knowledge")
        extra = 0
        if know is not None:
            anchors = {r.get("sourceNoteId") for r in game.m.get("regions", [])}
            extra = len(anchors & getattr(know, "learned", set()))
        return min(6, MAX_SLOTS + extra)

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
        room_of = getattr(game, "room_of_note", None)   # showcase Games may lack rooms
        for (nid, node) in chosen:
            if not tiles:
                break
            room = room_of(nid) if room_of else None
            pos = next((t for t in tiles if room is not None and room.contains(*t)),
                       tiles[0])
            tiles.remove(pos)
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
        ab = sigil["ability"]
        if len(self.slots) < self.max_slots(game):
            self.slots.append(sigil)
            game.log(f"You slot the {ab} sigil of {title}.")
        else:
            weakest = min(self.slots, key=lambda s: s["durability"])
            self.slots.remove(weakest)
            self.slots.append(sigil)
            game.log(f"You discard your worn {weakest['ability']} sigil for "
                     f"the {ab} sigil of {title}.")
        base = sigil.get("base", ab)
        if base not in self._seen:
            self._seen.add(base)
            hints = {
                "Ward": "Ward shimmers in your grasp — press c to cast; it pushes threats away.",
                "Phase": "Phase flickers — press c to cast; it blinks you past danger.",
                "Recall": "Recall hums deep — press c to cast; it mends your wounds.",
                "Rally": "Rally stirs — press c to cast; it placates a single foe.",
                "Echo": "Echo lies dormant — it will save you once from the killing blow.",
            }
            hint = hints.get(base)
            if hint:
                game.log(hint)

    # ---- lossiness ----------------------------------------------------------
    def _consume(self, game, sigil):
        """One use of an active effect (or one Recall floor). Shatter at 0."""
        # 'thrifty' (a quality passive): every other use is free, deterministically.
        if _prop(sigil, "thrifty"):
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
    # Each verb is split in two: the trigger (_recall/_rally/_ward/_phase decide WHEN
    # the passive fires) and the effect (_fire_* does the deed). cast() reuses the
    # effects with the player deciding the WHEN instead.
    def _recall(self, game):
        # hub, passive: heal a little each floor; the sigil wears with every floor.
        for s in [x for x in self.slots if self._ab(x) == "Recall"]:
            self._fire_recall(game, s)

    def _fire_recall(self, game, s):
        p = game.player
        mag = max(1, _prop(s, "magnitude"))
        amount = 6 + 2 * (mag - 1)
        from .body_parts import heal_body
        before = p.hp
        heal_body(p, amount)
        healed = max(0, p.hp - before)
        game.log(f"The Recall sigil mends you (+{healed} HP).")
        if _prop(s, "cleanse"):
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
            self._fire_rally(game, s)

    def _fire_rally(self, game, s) -> bool:
        foes = [a for a in game.actors
                if a.allegiance == "monster" and a.hp > 0 and not a.is_boss]
        if not foes:
            return False
        victim = min(foes, key=lambda a: a.hp)   # a real enemy, not a critter or boss
        game.actors.remove(victim)
        game.log(f"{victim.name} answers your call and stands aside.")
        self._consume(game, s)
        return True

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

    def _adjacent(self, game):
        p = game.player
        out = []
        for dx, dy in _ORTHO:
            a = game.actor_at(p.x + dx, p.y + dy)
            if a is not None:
                out.append((a, dx, dy))
        return out

    def _ward(self, game):
        # leaf: under pressure (>=2 adjacent), shove the press back -- and, if a hazard
        # lies in a shove direction, shove the enemy ONTO it so reactions does the killing.
        ward = self._first("Ward")
        if ward is None:
            return
        adj = self._adjacent(game)
        if len(adj) < 2:
            return
        self._fire_ward(game, ward, adj)

    def _fire_ward(self, game, ward, adj) -> bool:
        p = game.player
        # reactions partner may be unregistered; None-guard every call to it
        r = game.system("reactions")
        # 'ward_reach' (a quality passive) doubles the shove distance.
        reach = 2 if _prop(ward, "reach") else 1
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
        return shoved

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
        self._fire_phase(game, phase)

    def _fire_phase(self, game, phase) -> bool:
        p = game.player
        exclude = {(p.x, p.y), game.level.stairs}
        exclude |= {(a.x, a.y) for a in game.actors}
        tiles = free_floor_tiles(game.level, exclude)
        if not tiles:
            return False
        old = (p.x, p.y)
        p.x, p.y = self.rng.choice(tiles)
        game.log("You phase through the wall.")
        if _prop(phase, "decoy"):
            # leave a flickering after-image that draws attention to the old tile
            game.log("A phantom of you lingers as a decoy.")
            game.emit("noise", pos=old, volume=6)   # harmless if no system listens
        self._consume(game, phase)
        return True

    # ---- player command: cast a slotted sigil NOW ----------------------------
    def cast(self, game, index: int) -> bool:
        """Fire slot `index`'s verb at the player's chosen moment, consuming
        durability as usual. Manual timing beats the passive triggers: Ward shoves
        even a single foe, Phase blinks without being boxed in, Recall mends
        mid-fight. Returns True if it fired; False (free, with a log line) when
        the verb has no valid use this instant. Echo stays a death-trigger."""
        if not (0 <= index < len(self.slots)):
            game.log("No sigil in that slot.")
            return False
        s = self.slots[index]
        verb = self._ab(s)
        if verb == "Recall":
            if game.player.hp >= game.player.max_hp:
                game.log("You are unhurt; the Recall sigil stays quiet.")
                return False
            self._fire_recall(game, s)
            return True
        if verb == "Rally":
            fired = self._fire_rally(game, s)
            if not fired:
                game.log("No foe here will answer a Rally.")
            return fired
        if verb == "Ward":
            adj = self._adjacent(game)
            if not adj:
                game.log("Nothing stands close enough to ward away.")
                return False
            if not self._fire_ward(game, s, adj):
                game.log("The press has nowhere to be shoved.")
                return False
            return True
        if verb == "Phase":
            if not self._fire_phase(game, s):
                game.log("There is nowhere to phase to.")
                return False
            return True
        # part nodes: a fallen creature's own verb, salvaged and slotted
        from .abilities import player_cast   # importing registers the actions
        from .quality import SPECIAL_ACTIONS
        if verb.lower() in SPECIAL_ACTIONS:
            if player_cast(game, verb.lower()):
                self._consume(game, s)
                return True
            game.log(f"Your {verb} node finds no purchase here.")
            return False
        game.log("The Echo sigil waits for the killing blow; it cannot be forced.")
        return False

    def _echo(self, game):
        echo = self._first("Echo")
        if echo is None:
            return
        game.alive = True
        from .body_parts import init_body, sync_hp
        p = game.player
        # restore all parts, then cap at echo_twin threshold
        if getattr(p, "body", None):
            for pt in p.body.values():
                pt["hp"] = pt["max"]
            if not _prop(echo, "twin"):
                for pt in p.body.values():
                    pt["hp"] = min(1, pt["max"])
            sync_hp(p)
            p.speed = getattr(p, "_base_speed", 1.0)
            p._slowed = 0
        else:
            p.hp = 2 if _prop(echo, "twin") else 1
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
        cap = self.max_slots(game)
        if not self.slots:
            return f"Sigils: [0/{cap}]"
        parts = " ".join(f"{s['ability']}({s['durability']})" for s in self.slots)
        dur_blink = any(s.get("durability", 0) == 1 for s in self.slots)
        prefix = "c:" if not dur_blink else "!"
        return f"Sigils: {prefix} {parts} [{len(self.slots)}/{cap}]"
