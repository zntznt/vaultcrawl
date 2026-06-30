"""Drive the real Game through the ReactionSystem and assert the contract holds.

The example world's regions use elements ``corrosive`` (floor 1, acid) and
``charged``, both of which seed. We run a real descent, nudge the player around
for ~40 turns, and check: props are seeded after a floor enter, the overlay
draws at least one element glyph onto a floor cell, and environmental damage to
the player is capped (<=2/turn, never pushing hp below 0 from the environment
alone). A separate focused check exercises the charged+wet chain-shock path,
which the single-element example floors never trigger on their own.
"""
from runtime.game import Game, load_manifest
from runtime.reactions import ReactionSystem, _GLYPH
from runtime.systems import System
from runtime.entities import Actor


class Spy(System):
    """Records every bus event so we can assert what reactions emits."""
    name = "spy"

    def __init__(self):
        self.events = []

    def on_event(self, game, etype, data):
        self.events.append((etype, dict(data)))


class _FixedRng:
    """Deterministic stand-in for the seeded rng: randint->1, fire never spreads."""
    def randint(self, a, b):
        return 1

    def random(self):
        return 1.0


def _check_quiet_kill():
    """A hazard kill emits enemy_killed/cause=environment and is logged as quiet."""
    g = Game(load_manifest("examples/world.json"), systems=[ReactionSystem(), Spy()])
    s = g.system("reactions")
    spy = g.system("spy")
    s.rng = _FixedRng()
    g.player.x, g.player.y = -5, -5            # keep the player off every prop tile
    s.props = {(1, 1): {"acid"}}
    s.fire_life = {}
    victim = Actor(x=1, y=1, glyph="e", name="doomed", hp=1, max_hp=1, atk=1,
                   source="grocery list")     # orphan note -> neutral 1x affinity
    g.actors = [victim]
    spy.events.clear()
    s.on_player_act(g)
    assert victim not in g.actors, "hazard should have killed the enemy"
    kills = [d for (et, d) in spy.events if et == "enemy_killed"]
    assert kills, "no enemy_killed event reached the spy"
    last = kills[-1]
    assert last.get("cause") == "environment", f"expected environment, got {last.get('cause')}"
    assert last.get("enemy") is victim, "event carried the wrong enemy"
    assert any("unnoticed" in m for m in g.messages), "kill was not logged as quiet"


def _check_affinity():
    """Enemy immune (0x) to its home element, weak (2x) to the opposite."""
    g = Game(load_manifest("examples/world.json"), systems=[ReactionSystem(), Spy()])
    s = g.system("reactions")

    # multiplier table
    assert s._affinity("charged", "charged") == 0
    assert s._affinity("charged", "wet") == 2
    assert s._affinity("charged", "flammable") == 1
    assert s._affinity(None, "wet") == 1

    # home-element derivation through the manifest graph (source -> community -> element)
    e_ch = Actor(x=0, y=0, glyph="e", name="spark", hp=20, max_hp=20, atk=1, source="ecs")
    e_co = Actor(x=0, y=0, glyph="e", name="rot", hp=20, max_hp=20, atk=1, source="discipline")
    assert s._enemy_home_element(g, e_ch) == "charged", "ecs(community1) -> charged"
    assert s._enemy_home_element(g, e_co) == "corrosive", "discipline(community0) -> corrosive"

    # integration: a live charged+wet chain-shock with a fixed rng (raw damage = 1)
    s.rng = _FixedRng()
    g.player.x, g.player.y = -5, -5
    A, B = (1, 1), (2, 1)                       # adjacent -> live chain-shock
    s.props = {A: {"charged"}, B: {"wet"}}
    s.fire_life = {}
    imm = Actor(x=A[0], y=A[1], glyph="e", name="imm", hp=20, max_hp=20, atk=1, source="ecs")
    weak = Actor(x=B[0], y=B[1], glyph="e", name="weak", hp=20, max_hp=20, atk=1, source="ecs")
    base = Actor(x=B[0], y=B[1], glyph="e", name="base", hp=20, max_hp=20, atk=1, source="discipline")
    g.actors = [imm, weak, base]
    s.on_player_act(g)
    assert imm.hp == 20, f"charged enemy must be immune on a charged tile (took {20 - imm.hp})"
    assert weak.hp == 18, f"charged enemy must take 2x on a wet tile (took {20 - weak.hp})"
    assert base.hp == 19, f"corrosive enemy takes 1x baseline on a wet tile (took {20 - base.hp})"


def _check_query_api():
    """element_at / is_hazard / props_at expose the tile state to other systems."""
    g = Game(load_manifest("examples/world.json"), systems=[ReactionSystem()])
    s = g.system("reactions")
    s.props = {(3, 3): {"acid"}, (4, 4): {"sacred"},
               (5, 5): {"charged"}, (6, 5): {"wet"}, (8, 1): {"charged"}}
    s.fire_life = {}

    # props_at returns a copy
    assert s.props_at(3, 3) == {"acid"}
    assert s.props_at(9, 9) == set()
    got = s.props_at(3, 3)
    got.add("zzz")
    assert "zzz" not in s.props[(3, 3)], "props_at must return a copy, not the live set"

    # element_at -> dominant prop or None
    assert s.element_at(3, 3) == "acid"
    assert s.element_at(9, 9) is None

    # is_hazard -> acid yes; sacred no; lone charged no; live charged+wet yes
    assert s.is_hazard(3, 3) is True
    assert s.is_hazard(4, 4) is False
    assert s.is_hazard(8, 1) is False, "a lone charged tile is not a hazard"
    assert s.is_hazard(5, 5) is True, "charged adjacent to wet (live shock) is a hazard"
    assert s.is_hazard(6, 5) is True
    assert s.is_hazard(9, 9) is False


def main():
    g = Game(load_manifest("examples/world.json"))
    s = ReactionSystem()
    s.on_world_start(g)
    s.on_floor_enter(g)

    # --- props were seeded after entering the floor ---
    assert s.props, "no reactive props were seeded on floor enter"
    element = g.region_for(g.floor)["element"]
    assert element in ("corrosive", "charged"), f"unexpected seed element {element}"
    # floor 1 is the corrosive region -> acid tiles
    assert any("acid" in p for p in s.props.values()), "corrosive floor seeded no acid"

    glyphs = set(_GLYPH.values())

    # --- run ~40 turns; verify the per-step player damage cap every step ---
    for _ in range(40):
        g.try_move(1, 0)
        if not g.alive:
            break                      # robust to the player dying from enemies
        hp_before = g.player.hp
        s.on_player_act(g)
        assert s.last_player_env_damage <= 2, (
            f"environment dealt {s.last_player_env_damage} > 2 to the player in one step")
        # cap respected and environment never pushes the player below 0 on its own
        assert g.player.hp >= 0, "environment drove player hp below 0"
        assert g.player.hp >= hp_before - 2, "per-step environmental damage exceeded the cap"

    # --- overlay draws at least one element glyph onto a still-floor cell ---
    grid = [row[:] for row in g.level.tiles]
    s.render_overlay(g, grid)
    drew = sum(1 for y in range(len(grid)) for x in range(len(grid[y]))
               if grid[y][x] in glyphs and g.level.tiles[y][x] == ".")
    assert drew >= 1, "render_overlay drew no element glyph onto a floor cell"

    # --- overlay only overwrote '.' cells (never walls/stairs) ---
    for y in range(len(grid)):
        for x in range(len(grid[y])):
            if grid[y][x] in glyphs:
                assert g.level.tiles[y][x] == ".", "overlay drew on a non-floor cell"

    # --- status line reports the ground element ---
    assert s.status_line(g) == f"Ground: {element}", s.status_line(g)

    # --- focused chain-shock check: charged adjacent to wet goes live ---
    g2 = Game(load_manifest("examples/world.json"))
    s2 = ReactionSystem()
    s2.on_world_start(g2)
    s2.on_floor_enter(g2)
    px, py = g2.player.x, g2.player.y
    # player stands on a charged tile that is part of a charged+wet group
    s2.props = {(px, py): {"charged"}, (px + 1, py): {"wet"}}
    s2.fire_life = {}
    before = g2.player.hp
    s2.on_player_act(g2)
    assert "Chain shock!" in g2.messages, "chain shock did not fire on charged+wet"
    dealt = before - g2.player.hp
    assert 1 <= dealt <= 2, f"chain shock dealt {dealt}, expected 1..2 (capped)"

    # an isolated charged tile (no wet) must NOT shock
    g3 = Game(load_manifest("examples/world.json"))
    s3 = ReactionSystem()
    s3.on_floor_enter(g3)
    qx, qy = g3.player.x, g3.player.y
    s3.props = {(qx, qy): {"charged"}}
    s3.fire_life = {}
    hp0 = g3.player.hp
    s3.on_player_act(g3)
    assert g3.player.hp == hp0, "lone charged tile should not damage the player"

    # --- cross-system interactions (quiet kills, affinity, query API) ---
    _check_quiet_kill()
    _check_affinity()
    _check_query_api()

    print("OK")


if __name__ == "__main__":
    main()
