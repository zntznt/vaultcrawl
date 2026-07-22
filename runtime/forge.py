"""Forge — spend salvaged matter to re-craft sigils, closing the loop.

The third beat of the Cogmind-flavored matter cycle: sigils SHATTER (lossy part-loss),
their shards SALVAGE into the world's materials, and the forge SPENDS that matter to
re-craft a sigil. So a run that loses configuration can climb back to it, deterministically,
without any flat power gain — what you forge is still just one of the five utility verbs.

Self-contained System: it reads the player's `Inventory` (`inv(game.player)`) and the
`sigils` system's slots through the public Game API, mutating only those. Every cross-system
call is None-guarded: with no `sigils` system registered the forge is a no-op returning False.

Pure stdlib, deterministic (no clock / rng): the cost is derived from the current inventory
and the forged ability from the currently-slotted set, so the same state always forges the
same sigil.
"""
from __future__ import annotations

from runtime import quality
from runtime.components import inv, world_materials
from runtime.sigils import MAX_SLOTS, ROLE_ABILITY
from runtime.systems import System
from runtime.proficiency import ptracker

# ability -> graph role (inverse of sigils' role->ability table), so a forged sigil
# carries the same {note, role, ability, durability} shape a found one would.
_ABILITY_ROLE = {ability: role for role, ability in ROLE_ABILITY.items()}

# the deterministic order we prefer when auto-picking an ability to forge.
_ABILITY_ORDER = list(dict.fromkeys(ROLE_ABILITY.values()))

# Perks a chosen additive can steer a forged sigil toward (one per world material,
# in order). These are *plausible* names from Agent A's sigil-perk pool plus the two
# quality.py built-ins (`reinforced`, `keen`): qualify_sigil only honours an affinity
# whose perk actually exists in PERKS, so unregistered names are silently inert.
_ADDITIVE_PERKS = (
    "ward_reach", "keen", "reinforced", "phase_decoy",
    "recall_cleanse", "thrifty", "echo_twin",
)

# How much of a material a single additive consumes beyond the recipe.
_ADDITIVE_UNIT = 1
# How many distinct materials to auto-pick as additives when none are supplied.
_MAX_ADDITIVES = 2


class ForgeSystem(System):
    """name='forge' — re-craft sigils by spending matter from the player's Inventory."""

    name = "forge"

    # A craft costs this much *total* matter, drawn from the most-abundant materials.
    _COST = 4
    # Forged sigils come out at full durability (a found non-Echo sigil is also 2).
    _FULL_DURABILITY = 2

    # ---- cost model ---------------------------------------------------------
    def cost(self, game) -> dict:
        """The concrete material cost to forge *now*: spend `_COST` total matter, taken
        greedily from the most-abundant materials (ties broken by material name, so it is
        deterministic). Exposed for the HUD / tests.

        If the player cannot cover `_COST`, the shortfall is charged to the most-abundant
        material (or a world material when the pool is empty) so the returned cost simply
        fails `Inventory.can_pay` — i.e. an unaffordable craft yields an unpayable cost.
        """
        pool = inv(game.player).comp
        # most abundant first; stable tiebreak on name keeps it deterministic
        order = sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))
        need = self._COST
        out: dict = {}
        for mat, qty in order:
            if need <= 0:
                break
            take = min(qty, need)
            out[mat] = out.get(mat, 0) + take
            need -= take
        if need > 0:                       # under-funded -> make the cost unpayable
            if order:
                mat = order[0][0]
            else:
                mats = world_materials(game)
                mat = mats[0] if mats else "scrap"
            out[mat] = out.get(mat, 0) + need
        return out

    # ---- ability choice -----------------------------------------------------
    def _default_ability(self, game) -> str:
        """Deterministic default: the first ability (in `_ABILITY_ORDER`) not currently
        slotted, so the forge refills the configuration a shatter just stripped. With
        MAX_SLOTS < the number of abilities there is always an un-slotted one; the modulo
        fallback only guards a pathological all-slotted state."""
        sigils = game.system("sigils")
        slotted = {s.get("ability") for s in getattr(sigils, "slots", [])} if sigils else set()
        for ability in _ABILITY_ORDER:
            if ability not in slotted:
                return ability
        return _ABILITY_ORDER[len(slotted) % len(_ABILITY_ORDER)]

    # ---- additives ----------------------------------------------------------
    def _register_world_affinities(self, game):
        """Map a few of THIS world's materials to specific perks, so a chosen additive
        favours that perk at the forge (vs a random one). Non-destructive (never clobbers
        an affinity already registered, e.g. by a test or another agent) and idempotent,
        so it's safe to call on every quality craft."""
        for mat, perk in zip(world_materials(game), _ADDITIVE_PERKS):
            if mat not in quality.ADDITIVE_AFFINITY:
                quality.register_additive(mat, perk)

    def _pick_additives(self, game, cost, additives):
        """The materials to spend as additives beyond the recipe `cost`.

        If `additives` is supplied (even an empty list) it's honoured verbatim — the caller
        is steering. Otherwise auto-pick up to `_MAX_ADDITIVES` of the player's most-abundant
        materials that still have a unit to spare after the recipe is paid (most-abundant
        first, ties broken by name → deterministic)."""
        if additives is not None:
            return list(additives)
        pool = inv(game.player).comp
        order = sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))
        picks: list = []
        for mat, qty in order:
            if qty - cost.get(mat, 0) >= _ADDITIVE_UNIT:   # a spare unit after the recipe
                picks.append(mat)
            if len(picks) >= _MAX_ADDITIVES:
                break
        return picks

    # ---- craft --------------------------------------------------------------
    def forge(self, game, ability=None, additives=None) -> bool:
        """Craft one sigil if there's a free slot AND the matter to pay for it.

        Returns True on success (a new sigil appended to the sigils system's slots and the
        cost deducted from the player's Inventory); False — changing nothing — when there is
        no sigils system, no free slot, or insufficient matter.

        Quality (opt-in): when a `quality` system is registered the output's tier is rolled
        with a floor pinned to the lowest-quality ingredient and a bias that rises with the
        input quality and with each additive — extra matter spent beyond the recipe, which
        also steers *which* perk the sigil gains. With no quality system the craft behaves
        exactly as before: spend `_COST`, forge a Normal sigil, no additives.
        """
        sigils = game.system("sigils")
        if sigils is None:
            return False
        slots = getattr(sigils, "slots", None)
        cap = sigils.max_slots(game) if hasattr(sigils, "max_slots") else MAX_SLOTS
        if slots is None or len(slots) >= cap:
            return False
        ability = ability or self._default_ability(game)
        cost = self.cost(game)
        player_inv = inv(game.player)
        # Proficiency gating: must know enough notes of the required role
        if not self._has_proficiency(game, ability):
            role = _ABILITY_ROLE.get(ability, "?")
            need = self._proficiency_required(role)
            game.log(f"You need to explore {need} {role}-role notes to forge {ability}.")
            return False
        # Affordability of the recipe is the gate (checked up front so nothing mutates on a
        # failed craft); Inventory.pay below is atomic and guaranteed to succeed here.
        if not player_inv.can_pay(cost):
            return False

        sigil = {
            "note": "forged",
            "role": _ABILITY_ROLE.get(ability, ""),
            "ability": ability,
            "durability": self._FULL_DURABILITY,
        }

        q = game.system("quality")
        tier = 0
        if q is not None:
            # output never below the lowest-quality ingredient; odds rise with inputs + additives
            floor = player_inv.min_quality(list(cost))
            additive_mats = self._pick_additives(game, cost, additives)
            bias = 0.15 * floor + 0.05 * len(additive_mats)
            self._register_world_affinities(game)
            tier = q.qualify_sigil(game, sigil, floor=floor, bias=bias,
                                   additives=additive_mats)
            game.log(f"You forge a {quality.name(tier)} {ability} sigil.")
            player_inv.pay(cost)
            # additives are paid IN ADDITION to the recipe, but are optional: if the player
            # can't cover the spare matter we still let the (already-rolled) craft stand.
            extra: dict = {}
            for m in additive_mats:
                extra[m] = extra.get(m, 0) + _ADDITIVE_UNIT
            if extra and player_inv.can_pay(extra):
                player_inv.pay(extra)
        else:
            game.log(f"You forge a {ability} sigil.")
            player_inv.pay(cost)

        slots.append(sigil)
        game.emit("forge_used", ability=ability, tier=tier)
        return True

    # ---- auto-forge ---------------------------------------------------------
    # `auto` stays True for the headless demo/tests; the interactive UI sets it False
    # so the `f` key is a real choice instead of a race the autopilot always wins.
    auto = True

    def on_player_act(self, game):
        """Whenever there's a free slot and enough matter, auto-craft the missing ability,
        so a run visibly recovers after a sigil shatters. forge() is fully guarded, so this
        is a safe no-op when a craft isn't possible."""
        if not self.auto or not getattr(game, "alive", True):
            return
        self.forge(game)

    # ---- presentation -------------------------------------------------------
    def status_line(self, game):
        sigils = game.system("sigils")
        if sigils is None:
            return None
        cap = sigils.max_slots(game) if hasattr(sigils, "max_slots") else MAX_SLOTS
        if len(getattr(sigils, "slots", [])) >= cap:
            return None
        return "Forge: ready" if inv(game.player).can_pay(self.cost(game)) else None

    def _has_proficiency(self, game, ability) -> bool:
        """Check knowledge of note-role AND recent practice with the ability."""
        role = _ABILITY_ROLE.get(ability)
        # static knowledge gate: must know enough notes of the required role
        if role is not None:
            know = game.system("knowledge")
            if know is not None:
                nodes = game.m.get("graph", {}).get("nodes", {})
                count = sum(1 for nid in know.known
                            if nodes.get(nid, {}).get("role") == role)
                if count < self._proficiency_required(role):
                    return False
        # dynamic practice gate: must have exercised the ability recently
        return ptracker().can_craft(ability, required=1.0)

    @staticmethod
    def _proficiency_required(role: str) -> int:
        """How many notes of this role must be known to forge its sigil."""
        return {"hub": 2, "bridge": 2, "cluster": 2, "leaf": 1, "orphan": 1}.get(role, 1)
