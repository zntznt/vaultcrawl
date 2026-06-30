"""Invariant + behaviour tests for the creature special-action library.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_abilities

Everything runs against a REAL Game built from the example world with a real
QualitySystem. The floor is overwritten with a fully controlled arena (walls
everywhere except a known open rectangle, or -- for the boxed-in cases -- only the
two occupied tiles) so every assertion is deterministic across runs: no rng, no
clock, fixed positions only.

The core contract checked after EVERY action call:
  * the action returns a bool;
  * no two living actors share a tile (the player included while alive);
  * every actor -- including any freshly spawned one -- stands on a walkable tile;
  * the player was neither moved nor overwritten.
"""
from runtime import quality
import runtime.abilities as abilities      # registers the actions on import
from runtime.game import Game, load_manifest
from runtime.entities import make_enemy


WORLD = "examples/world.json"


# --------------------------------------------------------------------------- #
# staging helpers (fully controlled, deterministic arenas)
# --------------------------------------------------------------------------- #

def _blank_level(game):
    w, h = game.level.w, game.level.h
    game.level.tiles = [["#"] * w for _ in range(h)]
    return w, h


def _elite(x, y, hp=None):
    e = make_enemy({"tier": 3, "archetype": "beast", "name": "brute",
                    "sourceNoteId": "n1"}, x, y)
    e.quality = 3
    e._qualified = True
    e._special_actions = list(quality.SPECIAL_ACTIONS.keys())
    if hp is not None:
        e.hp = e.max_hp = hp
    return e


def _stage(extra_allies=0):
    """Open arena: rows 2..6, cols 2..22 are floor. Elite at (10,4); player at (14,4)
    on the same row (clear orthogonal line, distance 4). Returns (game, elite, allies)."""
    game = Game(load_manifest(WORLD), systems=[quality.QualitySystem()])
    _blank_level(game)
    for y in range(2, 7):
        for x in range(2, 23):
            game.level.tiles[y][x] = "."
    game.actors = []
    game.alive = True
    elite = _elite(10, 4)
    game.actors.append(elite)
    game.player.x, game.player.y = 14, 4
    game.player.hp = game.player.max_hp
    allies = []
    for i in range(extra_allies):
        a = make_enemy({"tier": 1, "archetype": "swarm", "name": f"ally{i}",
                        "sourceNoteId": "n1"}, 9 - i, 4)   # adjacent west of the elite
        a._qualified = True
        a._special_actions = []
        game.actors.append(a)
        allies.append(a)
    return game, elite, allies


def _stage_boxed():
    """Boxed-in arena: ONLY the elite's and the player's tiles are floor, both occupied,
    so `free_floor_tiles` is empty. Used to prove summon/split decline gracefully."""
    game = Game(load_manifest(WORLD), systems=[quality.QualitySystem()])
    _blank_level(game)
    game.level.tiles[4][10] = "."
    game.level.tiles[4][12] = "."
    game.actors = []
    game.alive = True
    elite = _elite(10, 4, hp=20)        # well above the split threshold
    game.actors.append(elite)
    game.player.x, game.player.y = 12, 4
    game.player.hp = game.player.max_hp
    return game, elite


# --------------------------------------------------------------------------- #
# the universal invariant check
# --------------------------------------------------------------------------- #

def _check(game, result, label, ppos):
    assert isinstance(result, bool), f"{label}: action returned {type(result).__name__}, not bool"

    # every actor (incl. spawned) on a walkable tile
    for a in game.actors:
        assert game.level.walkable(a.x, a.y), \
            f"{label}: actor {a.name!r} on non-walkable tile {(a.x, a.y)}"
    assert game.level.walkable(game.player.x, game.player.y), \
        f"{label}: player on non-walkable tile {(game.player.x, game.player.y)}"

    # no two LIVING actors share a tile (player included while alive)
    occ = [(a.x, a.y) for a in game.actors if a.hp > 0]
    if game.alive:
        occ.append((game.player.x, game.player.y))
    dupes = sorted({t for t in occ if occ.count(t) > 1})
    assert not dupes, f"{label}: overlapping living actors at {dupes}"

    # the player was neither moved nor overwritten
    assert (game.player.x, game.player.y) == ppos, \
        f"{label}: player moved from {ppos} to {(game.player.x, game.player.y)}"


# --------------------------------------------------------------------------- #
# 1. the literal brief: call EACH registered action directly; bool + invariants
# --------------------------------------------------------------------------- #

def _check_every_action_is_invariant_safe():
    for name in sorted(quality.SPECIAL_ACTIONS):
        fn = quality.SPECIAL_ACTIONS[name]
        game, elite, _ = _stage()
        ppos = (game.player.x, game.player.y)
        result = fn(game, elite)
        _check(game, result, f"every[{name}]", ppos)
        # player must survive these staged calls (hp 32 vs tiny spit damage)
        assert game.alive, f"every[{name}]: unexpectedly ended the run"


# --------------------------------------------------------------------------- #
# 2. targeted behaviour + caps for each owned action
# --------------------------------------------------------------------------- #

def _check_enrage():
    game, elite, _ = _stage()
    ppos = (game.player.x, game.player.y)
    base = elite.atk
    for i in range(abilities.ENRAGE_CAP):
        assert abilities.act_enrage(game, elite) is True, "enrage should fire under the cap"
        _check(game, True, "enrage", ppos)
    assert elite.atk == base + abilities.ENRAGE_CAP, "enrage bonus not capped/applied correctly"
    # capped out -> declines, no further bump
    assert abilities.act_enrage(game, elite) is False, "enrage past the cap must decline"
    assert elite.atk == base + abilities.ENRAGE_CAP


def _check_shield():
    game, elite, _ = _stage()
    ppos = (game.player.x, game.player.y)
    base_def = elite.defense
    for _ in range(abilities.SHIELD_CAP):
        assert abilities.act_shield(game, elite) is True
        _check(game, True, "shield", ppos)
    assert elite.defense == base_def + abilities.SHIELD_CAP, "defense not capped/applied correctly"
    # defense capped -> falls back to a capped self-heal
    elite.hp = elite.max_hp - 1
    assert abilities.act_shield(game, elite) is True, "shield should self-heal once def is capped"
    assert elite.hp == elite.max_hp
    assert elite.defense == base_def + abilities.SHIELD_CAP, "self-heal must not raise defense"
    # fully healed + capped -> declines
    assert abilities.act_shield(game, elite) is False


def _check_rally():
    game, elite, allies = _stage(extra_allies=1)
    ally = allies[0]
    ppos = (game.player.x, game.player.y)
    base = ally.atk
    for i in range(abilities.RALLY_CAP):
        assert abilities.act_rally(game, elite) is True, "rally should buff the adjacent ally"
        _check(game, True, "rally", ppos)
    assert ally.atk == base + abilities.RALLY_CAP, "ally atk not capped/applied correctly"
    assert abilities.act_rally(game, elite) is False, "rally past the ally cap must decline"
    # with no adjacent ally, rally declines
    game2, elite2, _ = _stage()
    assert abilities.act_rally(game2, elite2) is False, "rally with no ally must decline"


def _check_spit():
    game, elite, _ = _stage()
    ppos = (game.player.x, game.player.y)
    hp0 = game.player.hp
    assert abilities.act_spit(game, elite) is True, "spit should hit the player on a clear line"
    _check(game, True, "spit", ppos)
    assert 0 < hp0 - game.player.hp <= abilities.SPIT_DAMAGE, "spit damage out of the modest range"

    # blocked by a wall on the line -> declines
    g2, e2, _ = _stage()
    g2.level.tiles[4][12] = "#"
    assert abilities.act_spit(g2, e2) is False, "spit through a wall must decline"

    # blocked by an actor on the line -> declines
    g3, e3, _ = _stage()
    blocker = make_enemy({"tier": 1, "archetype": "swarm", "name": "wall",
                          "sourceNoteId": "n1"}, 12, 4)
    g3.actors.append(blocker)
    assert abilities.act_spit(g3, e3) is False, "spit through an actor must decline"

    # diagonal / out of range -> declines
    g4, e4, _ = _stage()
    g4.player.x, g4.player.y = 13, 5            # diagonal, not orthogonal
    assert abilities.act_spit(g4, e4) is False, "spit off the orthogonal line must decline"
    g5, e5, _ = _stage()
    g5.player.x = 10 + abilities.SPIT_RANGE + 1   # same row, just past range
    assert abilities.act_spit(g5, e5) is False, "spit past range must decline"


def _check_blink():
    game, elite, _ = _stage()
    ppos = (game.player.x, game.player.y)
    before = max(abs(elite.x - ppos[0]), abs(elite.y - ppos[1]))
    assert abilities.act_blink(game, elite) is True, "blink should find a nearer tile"
    _check(game, True, "blink", ppos)
    after = max(abs(elite.x - ppos[0]), abs(elite.y - ppos[1]))
    assert after < before, "blink must end strictly nearer the player"

    # already adjacent with nowhere strictly nearer free -> declines (no player overlap)
    g2, e2, _ = _stage()
    g2.player.x, g2.player.y = 11, 4            # elite at (10,4): already Chebyshev 1
    # box the elite so the only nearer tile would be the player's -> must decline
    _blank_level(g2)
    g2.level.tiles[4][10] = "."
    g2.level.tiles[4][11] = "."
    assert abilities.act_blink(g2, e2) is False, "blink must decline rather than land on the player"
    assert (e2.x, e2.y) == (10, 4)


def _check_summon():
    game, elite, _ = _stage()
    ppos = (game.player.x, game.player.y)
    n0 = len(game.actors)
    assert abilities.act_summon(game, elite) is True, "summon should spawn an ally"
    _check(game, True, "summon", ppos)
    assert len(game.actors) == n0 + 1, "summon must add exactly one actor"
    ally = game.actors[-1]
    assert ally.allegiance == elite.allegiance, "summon must match the summoner's allegiance"
    assert ally._special_actions == [], "a summon must not carry special actions"
    assert ally.quality == 0, "a summon must be Normal quality"

    # determinism: a second identical game summons onto the identical tile
    game_b, elite_b, _ = _stage()
    assert abilities.act_summon(game_b, elite_b) is True
    assert (game.actors[-1].x, game.actors[-1].y) == (game_b.actors[-1].x, game_b.actors[-1].y), \
        "summon placement is not deterministic"

    # no free tile -> declines, nothing spawned
    gbx, ebx = _stage_boxed()
    n = len(gbx.actors)
    assert abilities.act_summon(gbx, ebx) is False, "boxed-in summon must decline"
    assert len(gbx.actors) == n, "declined summon must not spawn anything"
    _check(gbx, False, "summon:boxed", (gbx.player.x, gbx.player.y))


def _check_split():
    game, elite, _ = _stage()
    ppos = (game.player.x, game.player.y)
    hp0 = elite.hp
    n0 = len(game.actors)
    assert abilities.act_split(game, elite) is True, "split should spawn a half-HP copy"
    _check(game, True, "split", ppos)
    assert len(game.actors) == n0 + 1, "split must add exactly one copy"
    copy = game.actors[-1]
    assert copy.hp == hp0 // 2, "copy should carry half the parent's HP"
    assert elite.hp == hp0 - hp0 // 2, "parent should give up the copied HP"
    assert copy.glyph == elite.glyph and copy.allegiance == elite.allegiance
    # the copy can NEVER split again (no chain explosion)
    assert copy._is_split_spawn is True
    assert abilities.act_split(game, copy) is False, "a split copy must not split again"

    # below the HP threshold -> declines
    g2, e2, _ = _stage()
    e2.hp = abilities.SPLIT_MIN_HP - 1
    assert abilities.act_split(g2, e2) is False, "split below the HP threshold must decline"

    # no free tile -> declines, nothing spawned (even though HP is high)
    gbx, ebx = _stage_boxed()
    n = len(gbx.actors)
    assert abilities.act_split(gbx, ebx) is False, "boxed-in split must decline"
    assert len(gbx.actors) == n, "declined split must not spawn anything"
    _check(gbx, False, "split:boxed", (gbx.player.x, gbx.player.y))


# --------------------------------------------------------------------------- #
# 3. guards: missing player / level must never raise, just decline where relevant
# --------------------------------------------------------------------------- #

def _check_guards():
    game, elite, _ = _stage()
    game.alive = False                          # run is over
    assert abilities.act_spit(game, elite) is False, "spit must decline when the run is over"
    assert abilities.act_blink(game, elite) is False, "blink must decline when the run is over"
    # placement actions don't need a live player, but must stay invariant-safe
    assert isinstance(abilities.act_summon(game, elite), bool)


# --------------------------------------------------------------------------- #
# 4. determinism: the whole sweep run twice yields identical board state
# --------------------------------------------------------------------------- #

def _snapshot():
    game, elite, allies = _stage(extra_allies=1)
    for name in sorted(quality.SPECIAL_ACTIONS):
        quality.SPECIAL_ACTIONS[name](game, elite)
    return [(a.name, a.x, a.y, a.hp, a.atk, a.defense, a.allegiance) for a in game.actors] + \
           [("@", game.player.x, game.player.y, game.player.hp, game.alive)]


def _check_determinism():
    assert _snapshot() == _snapshot(), "the action sweep is not deterministic"


def main():
    _check_every_action_is_invariant_safe()
    _check_enrage()
    _check_shield()
    _check_rally()
    _check_spit()
    _check_blink()
    _check_summon()
    _check_split()
    _check_guards()
    _check_determinism()
    print("OK")


if __name__ == "__main__":
    main()
