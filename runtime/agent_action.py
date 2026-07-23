"""AgentAction — the 14-verb vocabulary every brain speaks, and the dispatch
function that turns each verb into a deterministic game call.

A brain returns an AgentAction; dispatch() applies it and returns True when the
action spent the player's turn, False when nothing happened (so the runner can
fall back to an anti-stall move). All system calls are None-guarded; all
exceptions are caught and return False.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AgentAction:
    kind: str   # move, wait, cast, shield, shove, interact, descend, ascend,
                # forge, rest, talk, toss, negotiate, breakdown, commune, becalm
    dx: int = 0
    dy: int = 0
    index: int = 0      # sigil slot index for cast
    target: str = ""    # ability name (forge/cast) or creature name (negotiate)
    additive: bool = False


_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _adjacent_monster(game):
    for dx, dy in _ORTH:
        a = game.actor_at(game.player.x + dx, game.player.y + dy)
        if a is not None and getattr(a, "allegiance", "") == "monster":
            return a
    return None


def _adjacent_monster_matching(game, target: str):
    for dx, dy in _ORTH:
        a = game.actor_at(game.player.x + dx, game.player.y + dy)
        if a is not None and getattr(a, "allegiance", "") == "monster":
            if a.name == target or target in getattr(a, "source", ""):
                return a
    return None


def dispatch(game, action: AgentAction) -> bool:
    try:
        kind = action.kind
        # -- move ---------------------------------------------------------------
        if kind == "move":
            if action.dx == 0 and action.dy == 0:
                return False
            game.try_move(action.dx, action.dy)
            return True

        # -- wait ---------------------------------------------------------------
        if kind == "wait":
            if hasattr(game, "wait"):
                game.wait()
            else:
                game.turn += 1
                game.enemies_act()
            return True

        # -- cast ---------------------------------------------------------------
        if kind == "cast":
            sigs = game.system("sigils")
            if sigs is None:
                return False
            slots = getattr(sigs, "slots", [])
            if action.index < 0 or action.index >= len(slots):
                return False
            return sigs.cast(game, action.index)

        # -- shield -------------------------------------------------------------
        if kind == "shield":
            game.shield()
            return True

        # -- shove --------------------------------------------------------------
        if kind == "shove":
            game.shove(action.dx, action.dy)
            return True

        # -- interact -----------------------------------------------------------
        if kind == "interact":
            game.interact()
            return True

        # -- descend ------------------------------------------------------------
        if kind == "descend":
            if not game.on_stairs():
                return False
            game.descend()
            return True

        # -- ascend -------------------------------------------------------------
        if kind == "ascend":
            if not hasattr(game, "ascend"):
                return False
            game.ascend()
            return True

        # -- forge --------------------------------------------------------------
        if kind == "forge":
            forge = game.system("forge")
            if forge is None:
                return False
            if hasattr(forge, "forge"):
                ok = forge.forge(game, ability=action.target or None)
                if ok:
                    game.wait()
                    return True
                return False
            if hasattr(forge, "on_player_forge"):
                forge.on_player_forge(game)
                return True
            return False

        # -- rest ---------------------------------------------------------------
        if kind == "rest":
            game.wait()
            return True

        # -- talk ---------------------------------------------------------------
        if kind == "talk":
            for dx, dy in _ORTH:
                a = game.actor_at(game.player.x + dx, game.player.y + dy)
                if a is not None and getattr(a, "allegiance", "") == "monster":
                    if game.becalm(a):
                        game.wait()
                        return True
            result = game.commune_landmark()
            if result is not None:
                return True
            return False

        # -- toss ---------------------------------------------------------------
        if kind == "toss":
            return game.toss(action.dx, action.dy)

        # -- negotiate ----------------------------------------------------------
        if kind == "negotiate":
            target_actor = _adjacent_monster_matching(game, action.target)
            if target_actor is None:
                return False
            from .negotiate import Parley, MOVES
            parley = Parley(game, game.player, target_actor)
            moves = list(MOVES)
            if not moves:
                return False
            parley.hear(game, target_actor, moves[-1])
            if parley.outcome == "enraged":
                return False
            game.wait()
            return True

        # -- breakdown ----------------------------------------------------------
        if kind == "breakdown":
            salv = game.system("salvage")
            if salv is None:
                return False
            try:
                got = salv.breakdown_sigil(game, action.target or None)
                if got is not None:
                    game.wait()
                    return True
                return False
            except Exception:
                return False

        # -- becalm -------------------------------------------------------------
        if kind == "becalm":
            a = _adjacent_monster(game)
            if a is None:
                return False
            if game.becalm(a):
                game.wait()
                return True
            return False

        # -- commune ------------------------------------------------------------
        if kind == "commune":
            result = game.commune()
            if result is True or result is False:
                return True
            return False

        return False

    except Exception:
        return False
