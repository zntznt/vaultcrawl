"""Capacity-matters tests for the creature sense-profiles registered by runtime.creatures.

Run:  cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_creatures

Every check runs the REAL perception core (`runtime.senses.perceive`) on a real
`Game(load_manifest("examples/world.json"), systems=[SenseField()])`.  We stage fully
controlled, deterministic arenas by carving a clean horizontal lane straight into
`game.level.tiles` (independent of the rng-seeded layout) and placing actors by hand, then
assert that *what a creature can know is decided by its sense kind*, not raw reach:

  * a `life_wraith` (glyph `h`) feels a LIVING player through a wall (no line-of-sight) while
    a plain `sighted` creature standing on the wraith's tile cannot -- yet the wraith is blind
    to a golem (not alive) at the same range, which the sighted creature DOES see.
  * an `echolocator` (glyph `e`) never identifies the player by sight at range, but a fresh
    `noise` gives it a lead to investigate.
  * a `mind_seer` (glyph `s`) identifies the minded player but not a mindless grazer at the
    same range (both beyond its short SIGHT, so only MIND can bite).
"""
from __future__ import annotations

import runtime.creatures  # noqa: F401  -- import side-effect: registers the named profiles
from runtime import senses
from runtime.senses import SenseField, perceive, has_los
from runtime.entities import make_enemy, make_critter
from runtime.game import Game, load_manifest

MANIFEST = "examples/world.json"


# --------------------------------------------------------------------------- helpers ----
def build() -> Game:
    """A fresh world wired with only the perception system (SenseField)."""
    return Game(load_manifest(MANIFEST), systems=[SenseField()])


def carve_lane(game, y):
    """Overwrite row `y` with floor (deterministic arena, independent of the seeded map)."""
    lvl = game.level
    for x in range(1, lvl.w - 1):
        lvl.tiles[y][x] = "."


def set_wall(game, x, y):
    game.level.tiles[y][x] = "#"


def observer(glyph, x, y, name="watcher"):
    """A faction monster whose glyph drives `profile_name_for` to the profile under test."""
    o = make_enemy({"tier": 1, "archetype": "warden", "name": name, "sourceNoteId": ""}, x, y)
    o.glyph = glyph
    return o


def golem(x, y):
    """A construct: glyph `g` => `is_alive` is False, so it emits no LIFE."""
    g = make_enemy({"tier": 1, "archetype": "golem", "name": "Golem", "sourceNoteId": ""}, x, y)
    g.glyph = "g"
    return g


# ------------------------------------------------------------- profiles registered ----
def test_profiles_registered():
    for name in ("echolocator", "scent_hound", "life_wraith", "mind_seer"):
        assert name in senses.PROFILES, f"{name} not registered by runtime.creatures"
    # the policy must route the selecting glyphs to our profiles
    assert senses.profile_name_for(observer("h", 0, 0)) == "life_wraith"
    assert senses.profile_name_for(observer("e", 0, 0)) == "echolocator"
    assert senses.profile_name_for(observer("s", 0, 0)) == "mind_seer"
    assert senses.profile_name_for(observer("b", 0, 0)) == "scent_hound"
    print("profiles registered:", {n: senses.PROFILES[n].ranges
                                    for n in ("echolocator", "scent_hound",
                                              "life_wraith", "mind_seer")})


# --------------------------------------------------- life_wraith: LIFE through a wall ----
def test_life_wraith_through_wall():
    g = build()
    Y = g.level.h // 2
    carve_lane(g, Y)
    OX = 10
    # Player (alive) walled off to the right; golem (not alive) in clear LOS to the left.
    g.player.x, g.player.y = OX + 5, Y          # distance 5
    g.player.hp = g.player.max_hp
    gol = golem(OX - 5, Y)                       # distance 5, clear lane
    g.actors = [gol]
    set_wall(g, OX + 2, Y)                       # blocks the wraith<->player sight-line

    # staging sanity: no LOS to the player, clear LOS to the golem
    assert not has_los(g, OX, Y, g.player.x, g.player.y)
    assert has_los(g, OX, Y, gol.x, gol.y)

    wraith = observer("h", OX, Y, "Shade")       # {LIFE:10, SOUND:6, TOUCH:1}, no SIGHT
    sighted = observer("r", OX, Y, "Sentry")     # falls back to 'sighted' {SIGHT:8,...}
    assert senses.profile_name_for(wraith) == "life_wraith"
    assert senses.profile_name_for(sighted) == "sighted"

    wp = perceive(g, wraith).identified
    sp = perceive(g, sighted).identified

    # LIFE pierces the wall: the wraith knows the living player, is blind to the golem.
    assert g.player in wp, "wraith should sense the living player through the wall"
    assert gol not in wp, "wraith must be blind to the (unliving) golem"
    # The sighted creature is the mirror image: eyes need LOS.
    assert g.player not in sp, "sighted creature must NOT see the player through a wall"
    assert gol in sp, "sighted creature SHOULD see the golem in clear LOS"
    print(f"life_wraith identified={[a.name for a in wp]}  "
          f"sighted identified={[a.name for a in sp]}")


# ------------------------------------------------ echolocator: blind, led by sound ----
def test_echolocator_leads_on_noise():
    g = build()
    Y = g.level.h // 2
    carve_lane(g, Y)
    OX = 10
    g.player.x, g.player.y = OX + 6, Y          # distance 6: out of TOUCH, and echo has no SIGHT
    g.player.hp = g.player.max_hp
    g.actors = []

    echo = observer("e", OX, Y, "Echo")         # {SOUND:16, TOUCH:1}, no SIGHT
    assert senses.profile_name_for(echo) == "echolocator"

    before = perceive(g, echo)
    assert g.player not in before.identified, "echolocator cannot identify the player by sight"
    assert before.leads == [], "no stimuli yet -> no leads"

    g.emit("noise", pos=(OX + 1, Y), volume=8)  # something clatters one tile away
    g.turn += 1                                 # advance the turn so perception recomputes

    after = perceive(g, echo)
    assert g.player not in after.identified, "still no identifying sense -> still unidentified"
    assert after.leads, "a heard noise must produce a lead to investigate"
    assert any((lx, ly) == (OX + 1, Y) for (lx, ly, _sal) in after.leads), \
        "the lead should point at the noise"
    print(f"echolocator leads after noise: {after.leads}")


# --------------------------------------------- mind_seer: selective thought-sense ----
def test_mind_seer_minds_not_mindless():
    g = build()
    Y = g.level.h // 2
    carve_lane(g, Y)
    OX = 10
    g.player.x, g.player.y = OX + 7, Y          # distance 7: beyond SIGHT(5), within MIND(10)
    g.player.hp = g.player.max_hp
    grazer = make_critter("Moss-grazer", "n", OX - 7, Y, 6, 1, source="fauna:grazer")  # d=7, mindless
    g.actors = [grazer]

    seer = observer("s", OX, Y, "Scribe")       # {MIND:10, SIGHT:5, TOUCH:1}
    assert senses.profile_name_for(seer) == "mind_seer"
    # prove the selectivity is MIND, not sight: both targets are out of SIGHT range
    assert senses.is_minded(g.player) and not senses.is_minded(grazer)

    ident = perceive(g, seer).identified
    assert g.player in ident, "mind_seer should feel the minded player"
    assert grazer not in ident, "mind_seer must be blind to the mindless grazer"
    print(f"mind_seer identified={[a.name for a in ident]} (grazer excluded)")


def main():
    test_profiles_registered()
    test_life_wraith_through_wall()
    test_echolocator_leads_on_noise()
    test_mind_seer_minds_not_mindless()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
