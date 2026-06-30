"""Drive the real Game through the interaction-aware brains and assert each tier's
behaviour — pinned against the legacy HunterBrain as a control.

We build a real `Game(load_manifest("examples/world.json"), systems=[ReactionSystem()])`,
reset the seeded reaction props so only the staged hazards exist, find an open 3x3
patch of floor, and place actors by hand. The decisions are read directly via
`brain.decide` (the engine resolves the same value through `enemies_act`).

Key assertions:
  - survivor vs hunter: with an acid tile on the straight-line chase path, the hunter
    steps ONTO the danger tile while the survivor's step lands on a NON-danger tile
    (it routes around).
  - opportunist: two adjacent hostiles, one on acid -> it attacks the one on acid.
  - forager: a grazer adjacent to a monster steps AWAY (distance increases).
  - registration: all four tiers are wired into the shared registry.
  - determinism: every check yields identical results on a re-run.

Run: python3 -m tests.test_brains
"""
from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem
from runtime.entities import make_enemy, make_critter
from runtime.sense import HunterBrain, is_dangerous, BRAIN_REGISTRY, nearest_hostile
from runtime.brains import (  # importing registers the tiers
    SurvivorBrain, OpportunistBrain, ForagerBrain, ScavengerBrain,
)

MANIFEST = "examples/world.json"


def _fresh_game():
    """A real game on floor 1 with the reaction props cleared (we stage hazards)."""
    g = Game(load_manifest(MANIFEST), systems=[ReactionSystem()])
    r = g.system("reactions")
    r.props = {}
    r.fire_life = {}
    return g, r


def _find_open_block(level):
    """First (cx, cy) whose full 3x3 neighbourhood is plain floor ('.').

    Deterministic: the level is generated from the (seed, floor) pair, so the same
    block is returned every run. A 3x3 floor pocket guarantees both a straight-line
    triple (A, M, T) AND a hazard-free detour around the middle tile.
    """
    for cy in range(1, level.h - 1):
        for cx in range(1, level.w - 1):
            if all(level.tiles[cy + dy][cx + dx] == "."
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                return cx, cy
    raise AssertionError("no open 3x3 floor block found in the level")


def _check_survivor_vs_hunter():
    """The defining behaviour difference: hunter walks into acid, survivor routes around."""
    g, r = _fresh_game()
    cx, cy = _find_open_block(g.level)

    # Straight horizontal chase: A -> M(acid) -> T(player), one tile apart.
    ax, ay = cx - 1, cy          # the chasing monster
    mx, my = cx, cy              # the acid tile, dead centre of the path
    tx, ty = cx + 1, cy          # the target (player)

    r.props = {(mx, my): {"acid"}}
    g.player.x, g.player.y = tx, ty
    chaser = make_enemy({"tier": 1, "archetype": "beast",
                         "name": "chaser", "sourceNoteId": "x"}, ax, ay)
    g.actors = [chaser]

    assert is_dangerous(g, mx, my), "staged acid tile is not registering as danger"
    tgt, dist = nearest_hostile(g, chaser)
    assert tgt is g.player and dist == 2, "expected the player two tiles away in a line"

    hdx, hdy = HunterBrain().decide(g, chaser)
    sdx, sdy = SurvivorBrain().decide(g, chaser)

    htile = (ax + hdx, ay + hdy)
    stile = (ax + sdx, ay + sdy)

    assert htile == (mx, my), f"hunter should beeline onto the acid tile, went {htile}"
    assert is_dangerous(g, *htile), "hunter's tile should be a danger tile"
    assert (sdx, sdy) != (0, 0), "survivor should still move toward its prey"
    assert not is_dangerous(g, *stile), f"survivor stepped onto danger {stile}"
    assert stile != htile, "survivor must diverge from the reckless hunter"
    return (hdx, hdy, sdx, sdy)


def _check_opportunist():
    """Two adjacent hostiles, one on acid: the opportunist strikes the doomed one."""
    g, r = _fresh_game()
    cx, cy = _find_open_block(g.level)

    # opportunist O at centre; player to the west (safe), wild critter to the east (acid).
    r.props = {(cx + 1, cy): {"acid"}}
    g.player.x, g.player.y = cx - 1, cy
    opp = make_enemy({"tier": 3, "archetype": "warden",
                      "name": "opportunist", "sourceNoteId": "x"}, cx, cy)
    on_acid = make_critter("doomed", "z", cx + 1, cy, 6, 1, source="fauna:predator")
    g.actors = [opp, on_acid]

    assert is_dangerous(g, cx + 1, cy) and not is_dangerous(g, cx - 1, cy)
    dx, dy = OpportunistBrain().decide(g, opp)
    assert (dx, dy) == (1, 0), f"opportunist should attack east (the acid hostile), got {(dx, dy)}"
    assert (opp.x + dx, opp.y + dy) == (on_acid.x, on_acid.y), \
        "the chosen direction must point at the hostile standing on acid"

    # control: a plain survivor would just hit its nearest hostile (the player to the west)
    return (dx, dy)


def _check_forager():
    """A grazer adjacent to a monster flees — distance to the threat increases."""
    g, r = _fresh_game()
    cx, cy = _find_open_block(g.level)

    g.player.x, g.player.y = -50, -50          # keep the hero clear; wildlife ignores it
    grazer = make_critter("grazer", "n", cx, cy, 6, 1, source="fauna:grazer")
    monster = make_enemy({"tier": 1, "archetype": "beast",
                          "name": "stalker", "sourceNoteId": "x"}, cx + 1, cy)
    g.actors = [grazer, monster]

    before = max(abs(grazer.x - monster.x), abs(grazer.y - monster.y))
    dx, dy = ForagerBrain().decide(g, grazer)
    assert (dx, dy) != (0, 0), "forager should flee an adjacent monster, not freeze"
    after = max(abs(grazer.x + dx - monster.x), abs(grazer.y + dy - monster.y))
    assert after > before, f"forager must increase distance (before {before}, after {after})"
    assert not is_dangerous(g, grazer.x + dx, grazer.y + dy), "forager fled onto danger"

    # scavenger shares the reflex
    sdx, sdy = ScavengerBrain().decide(g, grazer)
    assert (sdx, sdy) == (dx, dy), "scavenger should flee identically to the forager"
    return (dx, dy)


def _check_registration():
    """All four tiers are wired into the shared registry under their exact names."""
    expected = {
        "survivor": SurvivorBrain,
        "opportunist": OpportunistBrain,
        "forager": ForagerBrain,
        "scavenger": ScavengerBrain,
    }
    for name, cls in expected.items():
        assert BRAIN_REGISTRY.get(name) is cls, f"{name!r} not registered to {cls.__name__}"


def _check_determinism():
    """Re-running every behaviour check yields identical decisions."""
    a = (_check_survivor_vs_hunter(), _check_opportunist(), _check_forager())
    b = (_check_survivor_vs_hunter(), _check_opportunist(), _check_forager())
    assert a == b, f"non-deterministic decisions: {a} != {b}"


def main():
    _check_registration()
    _check_survivor_vs_hunter()
    _check_opportunist()
    _check_forager()
    _check_determinism()
    print("OK")


if __name__ == "__main__":
    main()
