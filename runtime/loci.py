"""LocusSystem — polymorphic encounter nodes. Each locus is neutral until
an agent approaches. The agent's profile type-casts the locus: a fighter
spawns combat, a crafter finds a forge station, a diplomat finds a
conversation partner. The same world object, different outcomes."""
from __future__ import annotations

from runtime.systems import System


class LocusSystem(System):
    name = "loci"

    def __init__(self):
        self.loci: dict = {}           # {(x, y): {"type": None|"forge"|...}}
        self.depleted: set = set()     # {(x, y)} — consumed loci become records
        self._rng = None

    def on_world_start(self, game):
        pass

    def on_floor_enter(self, game):
        """Place 5-8 neutral loci per floor. Away from player and stairs."""
        from random import Random
        seed = f"{game.seed}:{game.floor}:loci"
        self._rng = Random(hash(seed) % (2**31))
        self.loci = {}
        self.depleted = set()

        count = 5 + (hash(seed + "count") % 4)  # 5-8
        # Phase 1: more loci on early floors for sustain, tapering at depth
        if game.floor <= 8:
            count += 3  # 8-11 loci on floors 1-8
        elif game.floor <= 15:
            count -= 1  # 4-7 loci on floors 9-15
        else:
            count -= 3  # 2-5 loci on floors 16+
        placed = 0
        attempts = 0
        px, py = game.player.x, game.player.y
        stairs = getattr(game.level, 'stairs', None)
        sx, sy = stairs if stairs else (px + 30, py)

        while placed < count and attempts < 200:
            x = self._rng.randint(1, game.level.w - 2)
            y = self._rng.randint(1, game.level.h - 2)
            attempts += 1

            if not game.level.walkable(x, y):
                continue
            if max(abs(x - px), abs(y - py)) < 6:
                continue  # not right next to player
            if stairs and max(abs(x - sx), abs(y - sy)) < 4:
                continue  # not blocking stairs
            if game.actor_at(x, y) is not None:
                continue
            if (x, y) in self.loci:
                continue

            self.loci[(x, y)] = {"type": None}
            placed += 1

        # Phase 2: Commune beacon — guaranteed locus near stairs on boss region entry
        boss_floors = [b["depth"] for b in game.m.get("bosses", [])]
        region_entry = min(boss_floors) if boss_floors else 99
        if game.floor == region_entry and stairs and not self.loci:
            # Place a beacon within 6 tiles of stairs
            for _ in range(50):
                bx = stairs[0] + (hash(f"{seed}:beacon:x") % 13 - 6)
                by = stairs[1] + (hash(f"{seed}:beacon:y") % 7 - 3)
                bx = max(0, min(game.level.w - 1, bx))
                by = max(0, min(game.level.h - 1, by))
                if game.level.walkable(bx, by) and (bx, by) not in self.loci:
                    self.loci[(bx, by)] = {"type": None, "beacon": True}
                    break

    def on_player_act(self, game):
        """Check proximity: if player within range 2 of an untyped locus, type-cast it."""
        if not game.alive or game.won:
            return
        px, py = game.player.x, game.player.y
        for (lx, ly), locus in list(self.loci.items()):
            if locus["type"] is not None:
                continue  # already typed or depleted
            d = max(abs(px - lx), abs(py - ly))
            if d <= 2:
                self._activate(game, lx, ly, locus)

    def _activate(self, game, lx, ly, locus):
        """Type-cast this locus based on the agent's top-scored profile action.
        Beacon loci prioritize commune if the agent has resources."""
        if not hasattr(game.player, 'brain') or not hasattr(game.player.brain, 'profile'):
            locus["type"] = "depleted"
            return

        # Beacon: commune first if agent has truths or matter
        if locus.get("beacon"):
            truths = (getattr(game.system("marginalia"), "read", 0) or 0) + \
                     (getattr(game.system("history"), "read", 0) or 0)
            salv = game.system("salvage")
            matter = salv.inventory(game).total() if salv else 0
            if truths >= 2 or matter >= 4:
                self._activate_commune(game, lx, ly, locus)
                return
            # Fall through to profile type-casting if commune not available

        profile = game.player.brain.profile
        # Find the highest-scored action that translates to a locus activation
        top_score = -999
        top_action = "depleted"
        for action, score in profile.items():
            if score > top_score:
                top_score = score
                top_action = action

        if top_action == "forge":
            self._activate_forge(game, lx, ly, locus)
            locus_type = "forge"
        elif top_action == "parley":
            self._activate_parley(game, lx, ly, locus)
            locus_type = "parley"
        elif top_action == "explore":
            self._activate_explore(game, lx, ly, locus)
            locus_type = "explore"
        elif top_action == "fight":
            self._activate_fight(game, lx, ly, locus)
            locus_type = "fight"
        elif top_action == "shield":
            self._activate_shield(game, lx, ly, locus)
            locus_type = "shield"
        elif top_action == "commune":
            self._activate_commune(game, lx, ly, locus)
            locus_type = "commune"
        elif top_action == "becalm":
            self._activate_becalm(game, lx, ly, locus)
            locus_type = "becalm"
        elif top_action == "recall":
            self._activate_becalm(game, lx, ly, locus)
            locus_type = "becalm"
        else:
            from random import Random
            rng = Random(hash(f"{game.seed}:{game.turn}:locus") % (2**31))
            choice = rng.choice(["forge", "parley", "explore", "shield"])
            locus_type = choice
            if choice == "forge":
                self._activate_forge(game, lx, ly, locus)
            elif choice == "parley":
                self._activate_parley(game, lx, ly, locus)
            elif choice == "explore":
                self._activate_explore(game, lx, ly, locus)
            else:
                self._activate_shield(game, lx, ly, locus)

        # Metrics: record locus activation type
        try:
            from runtime.metrics import metrics
            metrics().record_locus(locus_type)
        except Exception:
            pass

    def _activate_forge(self, game, lx, ly, locus):
        locus["type"] = "forge"
        locus["glyph"] = "F"
        # Craft a free sigil
        sigs = game.system("sigils")
        salv = game.system("salvage")
        if sigs and len(sigs.slots) < sigs.max_slots(game):
            slotted = {s.get("ability") for s in sigs.slots}
            for ability in ("Recall", "Ward", "Phase", "Echo", "Rally"):
                if ability not in slotted:
                    sigs.slots.append({"ability": ability, "base": ability,
                                       "durability": 3, "note": "locus-forged", "role": "hub"})
                    game.log(f"The locus hums — you forge a {ability} sigil from its essence.")
                    break
        if salv:
            salv.inventory(game).add({"essence": 2}, quality=2)
            game.log("The locus dissolves into forge matter.")
        heal_body(game.player, 5)
        game.log("The forge-fire mends you (+5 HP).")
        self._consume(game, locus)

    def _activate_parley(self, game, lx, ly, locus):
        locus["type"] = "parley"
        locus["glyph"] = "p"
        fcs = game.system("factions")
        know = game.system("knowledge")
        if fcs and hasattr(fcs, 'standing'):
            # Boost a random faction or the faction nearest to this locus
            facs = list(fcs.standing.keys())
            if facs:
                from random import Random
                rng = Random(hash(f"{game.seed}:{game.floor}:{lx}:{ly}") % (2**31))
                target = rng.choice(facs)
                current = fcs.standing.get(target, 0)
                fcs.standing[target] = min(6, current + 1)
                game.log(f"The locus whispers — your standing with {fcs.faction_name(target) if hasattr(fcs,'faction_name') else target} rises.")
        if know and hasattr(know, '_reveal'):
            nodes = game.m.get("graph", {}).get("nodes", {})
            unrevealed = [nid for nid in nodes if not know.is_known(nid)]
            if unrevealed:
                from random import Random
                rng = Random(hash(f"{game.seed}:{game.turn}:reveal") % (2**31))
                know._reveal(game, rng.choice(unrevealed))
                game.log("The locus murmurs a secret — a note reveals itself.")
        heal_body(game.player, 5)
        game.log("The parley restores your spirit (+5 HP).")
        self._consume(game, locus)

    def _activate_explore(self, game, lx, ly, locus):
        locus["type"] = "explore"
        locus["glyph"] = "e"
        know = game.system("knowledge")
        if know and hasattr(know, 'seen'):
            # Reveal all tiles in radius 10
            seen = know.seen
            floor_seen = seen.get(game.floor, set())
            for y in range(max(0, ly - 10), min(game.level.h, ly + 11)):
                for x in range(max(0, lx - 10), min(game.level.w, lx + 11)):
                    if game.level.walkable(x, y):
                        floor_seen.add((x, y))
            seen[game.floor] = floor_seen
            game.log("The locus illuminates — the map unfolds in your mind.")
        heal_body(game.player, 3)
        game.log("Knowledge strengthens you (+3 HP).")
        self._consume(game, locus)

    def _activate_fight(self, game, lx, ly, locus):
        locus["type"] = "fight"
        locus["glyph"] = "!"
        # Spawn a thrall — but WEAKENED because the agent engaged it through its preferred system
        from runtime.entities import make_enemy
        thrall = make_enemy({
            "name": "Locus Sentinel",
            "archetype": "warden",
            "tier": 2,           # tier 2 instead of 3 — weaker
            "sourceNoteId": "",
            "regionId": "",
        }, lx, ly)
        thrall.hp = 5           # reduced HP
        thrall.max_hp = 5
        game.actors.append(thrall)
        game.log("The locus stirs — a Sentinel forms from its substance.")
        self._consume(game, locus)

    def _activate_shield(self, game, lx, ly, locus):
        locus["type"] = "shield"
        locus["glyph"] = "D"
        game.player.defense = min(5, getattr(game.player, "defense", 0) + 1)
        game.log(f"The locus hardens around you. +1 DEF (now {game.player.defense}).")
        heal_body(game.player, 3)
        game.log("The bastion shields your wounds (+3 HP).")
        self._consume(game, locus)

    def _activate_commune(self, game, lx, ly, locus):
        locus["type"] = "commune"
        locus["glyph"] = "c"
        # Add a truth
        if hasattr(game, 'system'):
            marg = game.system("marginalia")
            if marg:
                marg.read = getattr(marg, 'read', 0) + 1
                game.log("The locus opens — a truth settles into your mind. +1 truth.")
        heal_body(game.player, 10)
        game.log("The truth floods through you (+10 HP).")
        self._consume(game, locus)

    def _activate_becalm(self, game, lx, ly, locus):
        locus["type"] = "becalm"
        locus["glyph"] = "b"
        # Heal 5 HP — a moment of peace
        from runtime.body_parts import heal_body
        heal_body(game.player, 5)
        game.log("The locus exhales calm. You feel restored (+5 HP).")
        self._consume(game, locus)

    def _consume(self, game, locus):
        """Mark the locus as consumed. It becomes a depleted record."""
        self.depleted.add(tuple(
            k for k, v in self.loci.items() if v is locus
        ) or [(0, 0)])
        locus["depleted"] = True

    def points_of_interest(self, game):
        """Return all untyped loci positions for agent pathfinding."""
        return [(x, y) for (x, y), loc in self.loci.items()
                if loc.get("type") is None and not loc.get("depleted")]

    def render_overlay(self, game, grid):
        """Render loci glyphs: ? for untyped, type-specific for activated."""
        for (x, y), loc in self.loci.items():
            if 0 <= y < len(grid) and 0 <= x < len(grid[y]):
                if loc.get("depleted"):
                    grid[y][x] = "·"  # depleted: faint dot
                elif loc.get("type") is None:
                    grid[y][x] = "?"  # untyped: question mark
                else:
                    grid[y][x] = loc.get("glyph", "?")

    def status_line(self, game):
        active = sum(1 for loc in self.loci.values()
                     if loc.get("type") is None and not loc.get("depleted"))
        return f"Loci: {active} remaining"
