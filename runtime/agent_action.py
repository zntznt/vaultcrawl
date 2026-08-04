"""AgentAction, the 19-verb vocabulary every brain speaks, and the dispatch
function that turns each verb into a deterministic game call.

Nineteen, counted off dispatch() below. Four documents said fourteen and two of them
went on to enumerate sixteen, a different sixteen each. runtime/metrics.py was the only
place in the repo that had it right. Two of the nineteen, `talk` and `ascend`, are
dispatched but emitted by no brain; `talk` is a strictly worse duplicate of `becalm`,
scanning four neighbours where `becalm` scans eight.

A brain returns an AgentAction; dispatch() applies it and returns True when the
action spent the player's turn, False when nothing happened (so the runner can
fall back to an anti-stall move). All system calls are None-guarded; all
exceptions are caught and return False.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AgentAction:
    kind: str   # move, wait, cast, shield, shove, interact, descend, ascend, forge,
                # rest, talk, toss, negotiate, breakdown, becalm, craft_consumable,
                # commune, deploy, recover
    dx: int = 0
    dy: int = 0
    index: int = 0      # sigil slot index for cast
    target: str = ""    # ability name (forge/cast) or creature name (negotiate)
    additive: bool = False


_ORTH = ((1, 0), (-1, 0), (0, 1), (0, -1))
# The game is eight-directional everywhere else (Chebyshev distance <= 1). Scanning only
# the orthogonals meant a diagonally adjacent creature was invisible to talk, becalm and
# negotiate, which is why negotiate never once succeeded across a full run.
_ADJ8 = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0))


def _adjacent_monster(game):
    for dx, dy in _ADJ8:
        a = game.actor_at(game.player.x + dx, game.player.y + dy)
        if a is not None and getattr(a, "allegiance", "") == "monster":
            return a
    return None


def _adjacent_monster_matching(game, target: str):
    """The named creature if it is adjacent, else any adjacent creature.

    The brain picks its target from perception a turn before dispatch, so the exact name
    can drift as creatures move. Falling back to whoever is actually next to you is what
    the player would do, and it is the difference between negotiate working and negotiate
    never once succeeding.
    """
    fallback = None
    for dx, dy in _ADJ8:
        a = game.actor_at(game.player.x + dx, game.player.y + dy)
        if a is not None and getattr(a, "allegiance", "") == "monster":
            if target and (a.name == target or target in getattr(a, "source", "")):
                return a
            if fallback is None:
                fallback = a
    return fallback


def dispatch(game, action: AgentAction) -> bool:
    try:
        # Metrics: record every verb usage
        try:
            from runtime.metrics import metrics
            metrics().record_verb(action.kind)
            metrics().turns_survived += 1
        except Exception:
            pass
        kind = action.kind
        # -- move ---------------------------------------------------------------
        if kind == "move":
            if action.dx == 0 and action.dy == 0:
                return False
            game.try_move(action.dx, action.dy)
            return True

        # -- wait ---------------------------------------------------------------
        # A bare turn pass. This used to be the same call as rest, so a stalled decision
        # or a cancelled action healed the player for standing still.
        if kind == "wait":
            if hasattr(game, "wait"):
                game.wait(allow_heal=False)
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
            # The verb's own verdict, not an assumption. Returning True unconditionally
            # meant `note_result` was never told about a failed interact, so the brain
            # kept choosing it from an unchanged state at 3.75 decisions per turn.
            return bool(game.interact())

        # -- descend ------------------------------------------------------------
        if kind == "descend":
            if not game.on_stairs():
                return False
            # `on_stairs` is a glyph test, and a glyph is not a promise. In sandbox the
            # surface carries an orphaned `>` left by the level generator that leads
            # nowhere, so the two disagree and the descend does nothing. Report the verb's
            # own verdict so the brain can stop choosing it.
            return bool(game.descend())

        # -- ascend -------------------------------------------------------------
        if kind == "ascend":
            if not hasattr(game, "ascend"):
                return False
            return bool(game.ascend())

        # -- forge --------------------------------------------------------------
        if kind == "forge":
            forge = game.system("forge")
            if forge is None:
                return False
            if hasattr(forge, "forge"):
                ok = forge.forge(game, ability=action.target or None)
                if ok:
                    # Forging costs the turn; it should not also be a rest.
                    game.wait(allow_heal=False)
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
                        game.wait(allow_heal=False)
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
            game.wait(allow_heal=False)
            return True

        # -- breakdown ----------------------------------------------------------
        if kind == "breakdown":
            salv = game.system("salvage")
            if salv is None:
                return False
            try:
                got = salv.breakdown_sigil(game, action.target or None)
                if got is not None:
                    game.wait(allow_heal=False)
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
                game.wait(allow_heal=False)
                return True
            return False

        # -- craft_consumable --------------------------------------------------
        if kind == "craft_consumable":
            try:
                from runtime.wear import craft_consumable
                return craft_consumable(game, action.target)
            except Exception:
                return False

        # -- commune ------------------------------------------------------------
        if kind == "commune":
            result = game.commune()
            if result is True or result is False:
                return True
            return False

        # -- deploy -------------------------------------------------------------
        if kind == "deploy":
            return game.deploy(action.index)

        # -- recover ------------------------------------------------------------
        if kind == "recover":
            return game.recover()

        return False

    except Exception:
        return False
