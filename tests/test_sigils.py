"""Drive the real Game through the SigilSystem and assert the contract.

Covers the self-contained sigil economy (slots / abilities / lossy durability /
shatter) AND the cross-system interactions from INTERACTIONS_SPEC.md (Ward
shove-to-kill onto reaction hazards, EM corruption from charged tiles) using a
small stub `reactions` system so we never depend on a mid-migration partner.

Run: python3 -m tests.test_sigils   (from the vaultcrawl project root)
"""
from runtime.game import Game, load_manifest
from runtime.entities import Actor
from runtime.systems import System
from runtime.sigils import ROLE_ABILITY, SigilSystem
from runtime import quality


# --- a fixed-set stub of the reactions query API -----------------------------
class StubReactions(System):
    """Implements exactly the reactions query surface sigils calls:
    is_hazard / element_at / props_at, over a small set we control."""
    name = "reactions"

    def __init__(self):
        self._haz: dict = {}      # (x, y) -> element name (a damaging tile)
        self._props: dict = {}    # (x, y) -> set[str]

    def set_hazard(self, xy, element):
        self._haz[xy] = element
        self._props.setdefault(xy, set()).add(element)

    def set_props(self, xy, props):
        self._props[xy] = set(props)

    def is_hazard(self, x, y) -> bool:
        return (x, y) in self._haz

    def element_at(self, x, y):
        if (x, y) in self._haz:
            return self._haz[(x, y)]
        props = self._props.get((x, y))
        return next(iter(props)) if props else None

    def props_at(self, x, y) -> set:
        return set(self._props.get((x, y), set()))


def _carve_arena(g, cx, cy, rad=2):
    """Clear a deterministic floor patch so geometry doesn't depend on layout."""
    for yy in range(cy - rad, cy + rad + 1):
        for xx in range(cx - rad, cx + rad + 1):
            g.level.tiles[yy][xx] = "."


# --- 1) core economy: placement / role-mapping / lossy shatter ---------------
def test_core():
    g = Game(load_manifest("examples/world.json"))
    s = SigilSystem()
    s.on_world_start(g)
    s.on_floor_enter(g)

    # ground sigils are placed on floor enter (1-2 of them)
    assert 1 <= len(s.ground) <= 2, f"expected 1-2 ground sigils, got {len(s.ground)}"

    nodes = g.m["graph"]["nodes"]
    for (x, y), sig in s.ground.items():
        assert g.level.tiles[y][x] == ".", "sigil must sit on a free floor tile"
        assert set(("note", "role", "ability", "durability")) <= set(sig), sig
        assert sig["note"] in nodes, f"unknown source note {sig['note']!r}"
        assert nodes[sig["note"]]["role"] == sig["role"], "stored role matches manifest"
        assert ROLE_ABILITY[sig["role"]] == sig["ability"], "ability derived from role"
        assert sig["durability"] == (1 if sig["ability"] == "Echo" else 2)
        # no QualitySystem registered -> the sigil stays Normal: no tier, no perks
        assert sig.get("quality", 0) == 0 and sig.get("perks", []) == [], sig

    # the full role -> ability table (at least one known node role each way)
    assert ROLE_ABILITY == {"hub": "Recall", "bridge": "Phase", "cluster": "Rally",
                            "leaf": "Ward", "orphan": "Echo"}
    # floor 1 is community 0 (House Philosophy); it contains a known leaf note.
    assert nodes["memento mori"]["role"] == "leaf"
    assert ROLE_ABILITY[nodes["memento mori"]["role"]] == "Ward"

    # walk ~40 turns; be robust to the player dying mid-walk
    dirs = [(1, 0), (0, 1), (-1, 0), (0, 1)]
    for i in range(40):
        dx, dy = dirs[i % len(dirs)]
        g.try_move(dx, dy)
        s.on_player_act(g)
        assert (g.player.x, g.player.y) not in s.ground, "stood-on sigil was picked up"

    assert len(s.slots) <= 3
    for sl in s.slots:
        assert sl["durability"] >= 1

    sl = s.status_line(g)
    assert isinstance(sl, str) and sl.startswith("Sigils:"), sl

    grid = [row[:] for row in g.level.tiles]
    s.render_overlay(g, grid)
    for (x, y) in s.ground:
        if g.level.tiles[y][x] == "." and g.actor_at(x, y) is None:
            assert grid[y][x] == "$", "ground sigil should render as '$'"

    # lossy/shatter mechanic (deterministic, survival-independent)
    before = len(g.messages)
    fake = {"note": "stoicism", "role": "leaf", "ability": "Ward", "durability": 2}
    s.slots.append(fake)
    s._consume(g, fake)
    assert fake["durability"] == 1 and fake in s.slots, "first use just wears it"
    s._consume(g, fake)
    assert fake not in s.slots, "sigil is removed from slots when it shatters"
    assert any("Ward sigil shatters" in m for m in g.messages[before:]), "shatter logged"

    # has_ability query surface — clear the starter sigil first for a clean test
    s.slots = []
    assert s.has_ability("Ward") is False and s.has_ability("Phase") is False
    s.slots.append({"note": "x", "role": "leaf", "ability": "Ward", "durability": 2})
    assert s.has_ability("Ward") is True


# --- 2) interaction: Ward shoves an adjacent enemy ONTO a hazard tile ---------
def test_ward_shove_to_hazard():
    sig = SigilSystem()
    stub = StubReactions()
    # pass systems= so game.system("reactions") resolves and hooks fire
    g = Game(load_manifest("examples/world.json"), systems=[sig, stub])

    cx, cy = 12, 6
    _carve_arena(g, cx, cy)
    g.player.x, g.player.y = cx, cy
    g.alive = True

    # two orthogonally adjacent enemies (Ward needs >=2 in the press)
    e_east = Actor(x=cx + 1, y=cy, glyph="b", name="acolyte", hp=5, max_hp=5, atk=1)
    e_west = Actor(x=cx - 1, y=cy, glyph="b", name="zealot", hp=5, max_hp=5, atk=1)
    g.actors = [e_east, e_west]

    # a hazard sits directly behind the east enemy (its natural shove-away tile)
    haz = (cx + 2, cy)
    stub.set_hazard(haz, "acid")

    # construct the Ward slot directly (role->ability: leaf -> Ward)
    sig.slots = [{"note": "memento mori", "role": "leaf",
                  "ability": "Ward", "durability": 2}]

    before = len(g.messages)
    sig._ward(g)

    assert (e_east.x, e_east.y) == haz, "Ward shoved the east enemy onto the hazard tile"
    assert any("toward the acid" in m for m in g.messages[before:]), \
        "hazard shove names the element"
    # ward is lossy: one activation costs one durability
    assert sig.slots and sig.slots[0]["durability"] == 1, "ward wore by one use"


# --- 3) interaction: standing on a 'charged' tile drains a sigil -------------
def test_em_corruption():
    sig = SigilSystem()
    stub = StubReactions()
    g = Game(load_manifest("examples/world.json"), systems=[sig, stub])

    cx, cy = 12, 6
    _carve_arena(g, cx, cy)            # neighbors are floor -> Phase won't trigger
    g.player.x, g.player.y = cx, cy
    g.alive = True
    g.actors = []                      # no press -> Ward won't trigger
    sig.ground = {}                    # nothing to pick up underfoot

    stub.set_props((cx, cy), {"charged"})
    sig.slots = [{"note": "memento mori", "role": "leaf",
                  "ability": "Ward", "durability": 2}]

    before = len(g.messages)
    sig.on_player_act(g)               # public path: corrosion runs each act
    assert sig.slots and sig.slots[0]["durability"] == 1, "charged tile drained 1 durability"
    assert any("EM corruption frays" in m for m in g.messages[before:]), "corruption logged"

    # a second act on the same charged tile empties it -> normal shatter handling
    before = len(g.messages)
    sig.on_player_act(g)
    assert not sig.slots, "second drain shatters the emptied sigil"
    assert any("shatters" in m for m in g.messages[before:]), "shatter logged on corrupt-empty"

    # corrosion is None-guarded: no reactions partner -> no drain, no crash
    sig2 = SigilSystem()
    g2 = Game(load_manifest("examples/world.json"))   # no systems registered
    sig2.slots = [{"note": "x", "role": "leaf", "ability": "Ward", "durability": 2}]
    sig2._corrode(g2)
    assert sig2.slots[0]["durability"] == 2, "no reactions system -> nothing drains"


# --- 4) quality: a high-tier sigil gains one perk per tier (stat perks bite) -
def test_quality_qualifies_sigil():
    sig = SigilSystem()
    g = Game(load_manifest("examples/world.json"),
             systems=[sig, quality.QualitySystem()])
    q = g.system("quality")
    assert q is not None, "QualitySystem should resolve via the bus"

    # force a high tier: one perk per tier, stored in property vector
    s0 = {"note": "memento mori", "role": "leaf", "ability": "Ward",
          "base": "Ward", "durability": 2}
    tier = q.qualify_sigil(g, s0, floor=3)
    assert tier >= 3, tier
    assert s0["quality"] == tier
    # property vector: sum of non-zero entries ≥ tier
    psum = sum(v for v in (s0.get("props") or []))
    assert psum >= tier, f"expected sum >= {tier}, got {psum} in {s0.get('props')}"
    # the display name carries the tier prefix
    assert s0["ability"].endswith("Ward") and s0["ability"] != "Ward"

    # a forced-tier sigil that rolled a STAT perk must show the value it changed
    from runtime.sigils import _prop, _PROP_IDX
    probe = None
    for i in range(60):
        cand = {"note": f"probe-{i}", "role": "hub", "ability": "Recall",
                "base": "Recall", "durability": 2}
        q.qualify_sigil(g, cand, floor=3)
        if _prop(cand, "durability") > 0 or _prop(cand, "magnitude") > 0:
            probe = cand
            break
    assert probe is not None, "no forced-tier sigil rolled a stat perk in 60 tries"
    # stat perk applied: durability or magnitude increased
    if _prop(probe, "durability") > 0:
        assert probe["durability"] >= 3, f"reinforced raised durability: {probe}"
    if _prop(probe, "magnitude") > 0:
        assert _prop(probe, "magnitude") >= 1, f"keen raised magnitude: {probe}"


# --- 5) quality passive visibly changes behavior: ward_reach shoves 2 tiles --
def test_ward_reach_perk():
    sig = SigilSystem()
    g = Game(load_manifest("examples/world.json"), systems=[sig])  # reactions absent
    cx, cy = 12, 6
    _carve_arena(g, cx, cy, rad=4)
    g.player.x, g.player.y = cx, cy
    g.alive = True
    e_east = Actor(x=cx + 1, y=cy, glyph="b", name="acolyte", hp=5, max_hp=5, atk=1)
    e_west = Actor(x=cx - 1, y=cy, glyph="b", name="zealot", hp=5, max_hp=5, atk=1)
    g.actors = [e_east, e_west]

    # baseline: a Normal Ward shoves each adjacent enemy exactly 1 tile away
    sig.slots = [{"note": "memento mori", "role": "leaf", "ability": "Ward",
                  "base": "Ward", "durability": 2}]
    sig._ward(g)
    assert (e_east.x, e_east.y) == (cx + 2, cy), "normal Ward shoves 1 tile"
    assert (e_west.x, e_west.y) == (cx - 2, cy), "normal Ward shoves 1 tile"

    # same staged press, now a ward_reach sigil -> the shove reaches 2 tiles
    e_east.x, e_east.y = cx + 1, cy
    e_west.x, e_west.y = cx - 1, cy
    sig.slots = [{"note": "memento mori", "role": "leaf", "ability": "Ward",
                  "base": "Ward", "durability": 2, "props": [0, 0, 1] + [0]*7}]
    sig._ward(g)
    assert (e_east.x, e_east.y) == (cx + 3, cy), "reach prop shoves 2 tiles"
    assert (e_west.x, e_west.y) == (cx - 3, cy), "reach prop shoves 2 tiles"


def test_perk_effects_misc():
    # 'thrifty': uses alternate cost/free deterministically
    sig = SigilSystem()
    g = Game(load_manifest("examples/world.json"), systems=[sig])
    th = {"note": "x", "role": "hub", "ability": "Recall", "base": "Recall",
          "durability": 2, "props": [0, 0, 0, 0, 0, 1] + [0]*4}  # thrifty=1
    sig.slots = [th]
    sig._consume(g, th); assert th["durability"] == 1
    sig._consume(g, th); assert th["durability"] == 1  # free (thrifty)
    sig._consume(g, th); assert th["durability"] == 0  # shatters
    assert th not in sig.slots

    # magnitude prop scales Recall's mend (base 6, +2 per mag)
    sig2 = SigilSystem()
    g2 = Game(load_manifest("examples/world.json"), systems=[sig2])
    g2.player.max_hp, g2.player.hp = 100, 1
    sig2.slots = [{"note": "y", "role": "hub", "ability": "Recall", "base": "Recall",
                   "durability": 3, "props": [3, 3] + [0]*8}]  # durability=3, magnitude=3 (mag=3)
    before = g2.player.hp
    sig2._recall(g2)
    assert g2.player.hp - before == 10, g2.player.hp   # 6 + 2*(3-1)

    # 'twin' prop: revive at 2 hp
    sig3 = SigilSystem()
    g3 = Game(load_manifest("examples/world.json"), systems=[sig3])
    g3.alive = False
    sig3.slots = [{"note": "z", "role": "orphan", "ability": "Echo", "base": "Echo",
                   "durability": 1, "props": [1, 0, 0, 0, 0, 0, 1] + [0]*3}]  # durability=1, twin=1
    sig3._echo(g3)
    assert g3.alive is True and g3.player.hp == 2, "twin revives at 2 hp"


def main():
    test_core()
    test_ward_shove_to_hazard()
    test_em_corruption()
    test_quality_qualifies_sigil()
    test_ward_reach_perk()
    test_perk_effects_misc()
    print("OK")


if __name__ == "__main__":
    main()
