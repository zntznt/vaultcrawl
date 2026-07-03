"""Debug toolkit — engine-side operators behind the --debug flag.

Each tool is a plain function over the public Game API, so they work from the
in-game debug menu (backtick), from scripts, and from tests alike. Debug actions
are free (no turn passes) and deliberately quiet on the bus where it matters:
smite kills without faction blame, warp emits no noise.
"""
from __future__ import annotations


def reveal_all(game) -> str:
    """Lift every fog: learn every note directly, mark the whole floor seen."""
    know = game.system("knowledge")
    if know is None:
        return "no knowledge system to reveal through"
    for nid in game.m.get("graph", {}).get("nodes", {}):
        know._reveal(game, nid, direct=True)
    know.seen[game.floor] = {(x, y) for y in range(game.level.h)
                             for x in range(game.level.w)}
    return "the whole vault lies bare"


def warp(game, idx) -> str:
    """Teleport to room `idx` (its first walkable, unoccupied tile)."""
    tiles = [t for t in game.room_tiles(idx)
             if game.actor_at(*t) is None]
    if not tiles:
        return "no open ground there"
    game.player.x, game.player.y = tiles[0]
    game._rooms_seen.add(idx)
    label = game.room_label(idx) or f"room {idx}"
    return f"warped to {label}"


def warp_heart(game) -> str:
    """Teleport beside the final boss (or into its note's room)."""
    boss = next((a for a in game.actors if a.is_boss
                 and a.source == game.final_boss_source), None)
    if boss is not None:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (game.level.walkable(boss.x + dx, boss.y + dy)
                    and game.actor_at(boss.x + dx, boss.y + dy) is None):
                game.player.x, game.player.y = boss.x + dx, boss.y + dy
                return f"warped before {boss.name}"
    for idx, nid in game.room_notes.items():
        if nid == game.final_boss_source:
            return warp(game, idx)
    return "the heart is nowhere to be found"


def grant_matter(game, amount: int = 25) -> str:
    salv = game.system("salvage")
    if salv is None:
        return "no salvage system to hold matter"
    mats = (game.m.get("bible", {}).get("aesthetic") or ["debug-stuff"])[:3]
    from .salvage import inv
    inv(game.player).add({m: amount for m in mats}, quality=2)
    return f"granted {amount} each of {', '.join(mats)} (quality 2)"


def grant_sigils(game) -> str:
    sigs = game.system("sigils")
    if sigs is None:
        return "no sigil system to fill"
    cap = sigs.max_slots(game)
    for ability in ("Ward", "Phase", "Recall", "Rally", "Echo"):
        if len(sigs.slots) >= cap:
            break
        if not any(s.get("base") == ability for s in sigs.slots):
            sigs.slots.append({"note": "debug", "role": "", "ability": ability,
                               "base": ability, "durability": 9})
    return f"slots filled [{len(sigs.slots)}/{cap}], durability 9"


def smite(game, radius: int = 8) -> str:
    """Remove every hostile in range. No faction blame, no kill credit."""
    px, py = game.player.x, game.player.y
    doomed = [a for a in game.actors
              if game.hostile(game.player, a)
              and max(abs(a.x - px), abs(a.y - py)) <= radius]
    for a in doomed:
        game.kill(a, "debug")
    return f"smote {len(doomed)} hostile(s)"


def inspect(game) -> list:
    """A full readout of here and everything beside you."""
    p = game.player
    out = [f"@({p.x},{p.y}) turn {game.turn} seed {game.seed} "
           f"hp {p.hp}/{p.max_hp} atk {p.atk} def {p.defense}"]
    idx = game.room_at(p.x, p.y)
    if idx is not None:
        nid = game.room_notes.get(idx)
        node = game.m.get("graph", {}).get("nodes", {}).get(nid, {})
        out.append(f"room {idx}: note '{nid}' role={node.get('role')} "
                   f"community={node.get('community')} tags={node.get('tags')}")
    el = game._tint.get((p.x, p.y))
    r = game.system("reactions")
    props = r.props_at(p.x, p.y) if r is not None else None
    out.append(f"ground: tint={el} substrate={sorted(props) if props else None}")
    for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
        a = game.actor_at(p.x + dx, p.y + dy)
        if a is None:
            continue
        out.append(f"beside: {a.name} [{a.allegiance}/{a.faction or 'no house'}] "
                   f"hp {a.hp}/{a.max_hp} tier {a.tier} q{a.quality} "
                   f"acts={getattr(a, '_special_actions', [])} "
                   f"home={getattr(a, '_home', None)} "
                   f"provoked={getattr(a, '_provoked', False)}")
    return out
