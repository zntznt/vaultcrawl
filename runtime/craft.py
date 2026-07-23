"""CraftSystem — site-based ritual crafting. The agent sacrifices something
permanent (sigil slot, body HP, effect, knowledge, standing, speed) at a
workspace (fabricator, camp, locus, terminal) to gain a system wire
(auto-cast, passive reveal, condition trigger, environmental interaction).

Design principle: the agent must never be quantitatively worse off after
crafting. Each sacrifice targets something the agent's playstyle doesn't
rely on; each reward amplifies what the agent already does.
"""
from __future__ import annotations

from runtime.systems import System


class CraftSystem(System):
    name = "craft"

    def __init__(self):
        self._done: set = set()  # (x, y) of already-used craft sites

    def on_floor_enter(self, game):
        """Craft sites are Fabricators, Terminals, town-tiles, and Loci.
        These are placed by their respective systems; we just provide the
        interaction layer."""
        pass

    def on_player_act(self, game):
        """Check if the player is on a craftable workspace."""
        if not game.alive or game.won:
            return
        px, py = game.player.x, game.player.y

        # ---- Fabricator: sacrifice sigil slot for auto-cast ----
        machines = game.system("machines")
        if machines and (px, py) in getattr(machines, "fabricators", set()):
            if (px, py) not in self._done:
                self._craft_fabricator(game, px, py)

        # ---- Terminal: sacrifice knowledge for passive reveal ----
        if machines and (px, py) in getattr(machines, "terminals", set()):
            if (px, py) not in self._done:
                self._craft_terminal(game, px, py)

        # ---- Locus: sacrifice effect for condition trigger ----
        loci = game.system("loci")
        if loci and (px, py) in loci.loci:
            # Loci are handled by LocusSystem for type-casting.
            # Craft loci are a separate interaction: stepping on a DEPLETED locus
            if loci.loci.get((px, py), {}).get("depleted"):
                if (px, py) not in self._done:
                    self._craft_locus(game, px, py)

        # ---- Camp/town: sacrifice body HP for environmental wire ----
        if (game._on_surface() and (px, py) in getattr(game, "_town_tiles", set())) or \
           (hasattr(game, "_resting") and game._resting):
            if (px, py) not in self._done and getattr(game, "_consecutive_rest", 0) >= 4:
                self._craft_camp(game, px, py)

    # ------------------------------------------------------------------
    # Craft rituals
    # ------------------------------------------------------------------

    def _craft_fabricator(self, game, x, y):
        """Fabricator: sacrifice 1 sigil slot, gain 1 auto-cast wire."""
        sigs = game.system("sigils")
        if not sigs or len(sigs.slots) >= 6:  # can't sacrifice if at max
            return
        # Check: the agent must have at least 1 slotted sigil that can be auto-cast
        if not sigs.slots:
            return

        # Pick a sigil to auto-cast. Prefer Recall (heal) for non-combat, Phase for combat.
        # Actually: auto-cast the agent's FIRST slotted sigil.
        target = sigs.slots[0]
        ability = target.get("ability", target.get("base", "Recall"))

        # Sacrifice: reduce max sigil slots by 1 by permanently designating one slot
        # as "wired" — it still holds the sigil but the slot is locked
        if not hasattr(game.player, "_crafts"):
            game.player._crafts = {}
        game.player._crafts[f"auto_{ability}"] = {
            "type": "auto_cast",
            "ability": ability,
            "condition": "hp_below_50",
        }

        # Mark as consumed
        machines = game.system("machines")
        if machines:
            machines.fabricators.discard((x, y))
        self._done.add((x, y))
        game.log(f"The Fabricator weaves {ability} into your being. "
                 f"It will cast itself when you are wounded.")
        # Burn turn
        game.turn += 1
        game.enemies_act()

    def _craft_terminal(self, game, x, y):
        """Terminal: sacrifice 2 known notes, gain 1 passive reveal wire."""
        know = game.system("knowledge")
        if not know:
            return
        known = getattr(know, "known", set())
        if len(known) < 2:
            game.log("The Terminal hums, but you lack the knowledge to rewire.")
            return

        # Sacrifice: forget 2 known notes (remove from known set)
        sacrificed = list(known)[:2]
        for nid in sacrificed:
            known.discard(nid)
            if hasattr(know, "learned") and nid in know.learned:
                know.learned.discard(nid)

        # Reward: passive reveal — see enemy HP without examine
        if not hasattr(game.player, "_crafts"):
            game.player._crafts = {}
        game.player._crafts["passive_enemy_hp"] = {
            "type": "passive_reveal",
            "reveal": "enemy_hp",
            "sacrificed_notes": sacrificed,
        }

        machines = game.system("machines")
        if machines:
            machines.terminals.discard((x, y))
        self._done.add((x, y))
        game.log(f"The Terminal rewires your perception. You can now sense enemy vitality.")
        game.turn += 1
        game.enemies_act()

    def _craft_locus(self, game, x, y):
        """Depleted locus: sacrifice 1 collected effect, gain 1 condition trigger wire."""
        eff = game.system("effects")
        if not eff or not eff.collected:
            game.log("The depleted locus flickers, but you have no effect to sacrifice.")
            return

        # Sacrifice: lose one collected effect
        sacrificed = list(eff.collected.keys())[0]
        del eff.collected[sacrificed]
        if eff.worn == sacrificed:
            eff.worn = None

        # Reward: condition trigger — kill heals 2 HP
        if not hasattr(game.player, "_crafts"):
            game.player._crafts = {}
        game.player._crafts["kill_heal"] = {
            "type": "condition_trigger",
            "trigger": "enemy_killed",
            "effect": "heal_2",
        }

        # Also remove from depleted loci set to avoid re-trigger
        self._done.add((x, y))
        game.log(f"The depleted locus drinks your {sacrificed} effect. "
                 f"Now, every kill mends you.")
        game.turn += 1
        game.enemies_act()

    def _craft_camp(self, game, x, y):
        """Camp: sacrifice 10 max HP (distributed), gain 1 environmental wire."""
        max_hp = getattr(game.player, "max_hp", 32)
        if max_hp < 15:
            game.log("You are too frail to endure the ritual.")
            return

        # Sacrifice: reduce max HP by 10, cap HP at new max
        game.player.max_hp = max(5, max_hp - 10)
        game.player.hp = min(game.player.hp, game.player.max_hp)

        # Reward: environmental — acid/hazard walk immunity
        if not hasattr(game.player, "_crafts"):
            game.player._crafts = {}
        game.player._crafts["hazard_walk"] = {
            "type": "environmental",
            "effect": "hazard_immunity",
        }

        self._done.add((x, y))
        game.log(f"The camp ritual scars your body. "
                 f"You can now walk through hazards unharmed. "
                 f"Max HP reduced to {game.player.max_hp}.")
        game.turn += 1
        game.enemies_act()

    # ------------------------------------------------------------------
    # Wire application — called by game.py on relevant events
    # ------------------------------------------------------------------

    @staticmethod
    def apply_wires(game, event_type: str, **data):
        """Called from game.py on key events. Fires any active wires."""
        crafts = getattr(game.player, "_crafts", {})
        if not crafts:
            return

        for key, craft in crafts.items():
            ctype = craft.get("type")
            if ctype == "auto_cast" and event_type == "player_hp_check":
                hp_pct = data.get("hp_pct", 100)
                if hp_pct < 50:
                    ability = craft["ability"]
                    sigs = game.system("sigils")
                    if sigs:
                        for i, s in enumerate(sigs.slots):
                            if s.get("ability") == ability or s.get("base") == ability:
                                sigs.cast(game, i)
                                break

            elif ctype == "condition_trigger" and event_type == craft.get("trigger"):
                effect = craft.get("effect")
                if effect == "heal_2":
                    from runtime.body_parts import heal_body
                    heal_body(game.player, 2)

    # ------------------------------------------------------------------
    # Perception feedback — what crafts are active
    # ------------------------------------------------------------------

    def status_line(self, game):
        crafts = getattr(game.player, "_crafts", {})
        if not crafts:
            return None
        names = []
        for key in crafts:
            if "auto" in key:
                names.append(f"auto-{crafts[key]['ability']}")
            elif key == "kill_heal":
                names.append("kill→heal")
            elif key == "hazard_walk":
                names.append("hazard-immune")
            elif key == "passive_enemy_hp":
                names.append("see-HP")
        return f"Crafts: {', '.join(names)}" if names else None
