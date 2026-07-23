"""Wear system: items degrade with use. Higher quality = slower wear."""
from __future__ import annotations

WEAR_TIERS = ["fine", "scuffed", "worn", "damaged", "broken"]
WEAR_EFFECTS = {"fine": 1.0, "scuffed": 0.75, "worn": 0.5, "damaged": 0.25, "broken": 0.0}

# Wear chance per use, by quality tier (0=Normal, 4=Legendary)
WEAR_CHANCE = [0.15, 0.10, 0.07, 0.04, 0.01]

# Map quality name to index for lookup
QUALITY_INDEX = {"Normal": 0, "Uncommon": 1, "Rare": 2, "Epic": 3, "Legendary": 4}
QUALITY_NAME = {0: "Normal", 1: "Uncommon", 2: "Rare", 3: "Epic", 4: "Legendary"}


def wear_tier_idx(tier_name: str) -> int:
    return WEAR_TIERS.index(tier_name) if tier_name in WEAR_TIERS else 0


def apply_wear(game, item: dict, quality_name: str = "Normal", uses: int = 1):
    """Apply wear to an item. Returns True if the item degraded a tier."""
    if "wear" not in item:
        item["wear"] = "fine"
    current_tier = wear_tier_idx(item["wear"])
    if current_tier >= 4:  # already broken
        return False

    qi = QUALITY_INDEX.get(quality_name, 0)
    chance = WEAR_CHANCE[qi]

    # Deterministic: seed from item identity + game turn
    item_id = item.get("ability", item.get("note", str(hash(str(item)))))
    roll = hash(f"{item_id}:{game.turn}") % 100 / 100.0
    if roll < chance:
        current_tier += uses
        item["wear"] = WEAR_TIERS[min(current_tier, 4)]
        return True
    return False


def maintain(game, item: dict, quality_name: str = "Normal") -> bool:
    """Restore 1-2 wear tiers. Returns True if any restoration happened."""
    if "wear" not in item or item["wear"] == "fine":
        return False
    current = wear_tier_idx(item["wear"])
    if current == 0:
        return False
    restore = 1
    # Proficiency bonus: higher tinkering skill gives chance for 2-tier restore
    from runtime.proficiency import skills as _skills
    tier = _skills().tier("tinkering")
    if tier >= 3:
        restore = 2
    elif tier >= 2:
        restore = 1 + (hash(f"{item.get('ability','')}:{game.turn}") % 2)  # 1 or 2
    new_tier = max(0, current - restore)
    item["wear"] = WEAR_TIERS[new_tier]
    return True


def is_broken(item: dict) -> bool:
    return item.get("wear") == "broken"


def wear_multiplier(item: dict) -> float:
    """Returns effectiveness multiplier based on wear."""
    tier = item.get("wear", "fine")
    return WEAR_EFFECTS.get(tier, 1.0)


# --- Consumable Crafting Dispatch ---

RECIPE_COSTS = {}
RECIPE_EFFECTS = {}


def register_recipe(name: str, cost: int, effect_fn):
    RECIPE_COSTS[name] = cost
    RECIPE_EFFECTS[name] = effect_fn


def craft_consumable(game, recipe_name: str) -> bool:
    """Craft a consumable from matter. Returns True on success."""
    salv = game.system("salvage")
    if not salv:
        return False

    # Check known recipes
    known = getattr(game.player, "_known_recipes", set())
    if recipe_name not in known:
        return False

    # Cost lookup
    cost = RECIPE_COSTS.get(recipe_name, 99)
    if salv.inventory(game).total() < cost:
        return False

    # Spend matter
    inv = salv.inventory(game)
    richest = max(inv.comp.keys(), key=lambda k: inv.comp[k]) if inv.comp else "scrap"
    for _ in range(cost):
        inv.pay({richest: 1})

    # Apply effect
    fn = RECIPE_EFFECTS.get(recipe_name)
    if fn:
        fn(game)

    game.log(f"You craft a {recipe_name}.")
    return True
