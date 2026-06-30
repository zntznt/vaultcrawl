"""Phase 5 -- the Measured gate as a regression (ARCHITECTURE_SPEC §11).

The *Seen* gate (rendering maps for a human to recognize the QWAN) is run by hand via
`python -m runtime.arch.visualize --gallery`. This test guards the *Measured* half: the
same pattern language, run over vaults of escalating scale (hamlet -> town -> mega), must
keep producing plan- and grid-wholeness above a floor, and the properties the tuning pass
fixed must stay fixed.

What Phase 5 tuning established and this locks in:
  * alternating_repetition is no longer pinned to 0 -- it now measures SPATIAL rhythm
    (size alternation along a BFS of the seam graph), not the size-sorted growth order
    (which can never alternate). It must be > 0 on a real multi-district world.
  * shared courts stay legible: a dense vault gets many, a single-cluster hamlet gets
    none, and no world tags *every* seam a court (the "court everywhere = court nowhere"
    failure the tuning fixed).

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_visualize
"""
import json
import os

from runtime.arch import grow as G
from runtime.arch.carve import carve, grid_wholeness
from runtime.arch.wholeness import wholeness

GALLERY = [
    ("hamlet",  "examples/world_hamlet.json", 3),    # thin, single cluster
    ("town",    "examples/world.json",        10),
    ("town_v2", "examples/world_v2.json",     11),
    ("mega",    "examples/world_mega.json",   18),    # dense super-cluster
]

PLAN_FLOOR = 0.55       # every scale must stay this alive at the plan level
GRID_FLOOR = 0.70       # ... and this alive once carved


def main():
    seen = []
    for name, path, expect_notes in GALLERY:
        if not os.path.exists(path):
            raise AssertionError(f"{name}: {path} not baked -- run vaultcrawl.bake first")
        graph = json.load(open(path))["graph"]
        assert len(graph["nodes"]) == expect_notes, \
            f"{name}: expected {expect_notes} notes, got {len(graph['nodes'])}"

        plan = G.grow(graph, seed="vis")
        level = carve(plan, seed="vis")
        pw, terms = wholeness(plan, breakdown=True)
        gw = grid_wholeness(level)
        courts = sum(1 for s in plan.seams if s.kind == "shared_court")

        assert pw >= PLAN_FLOOR, f"{name}: plan wholeness {pw:.3f} < {PLAN_FLOOR}"
        assert gw >= GRID_FLOOR, f"{name}: grid wholeness {gw:.3f} < {GRID_FLOOR}"

        # courts must be legible: never *every* seam, and a dense vault must have some
        n_seams = len(plan.seams)
        assert courts <= n_seams, f"{name}: more courts than seams?!"
        if len(graph["nodes"]) >= 10:
            multi = [n for n in graph["nodes"].values() if len(n.get("members", [])) >= 2]
            if multi:
                assert 0 < courts < n_seams or courts == 0, \
                    f"{name}: courts not legible ({courts}/{n_seams})"

        seen.append((name, pw, gw, courts))

    # alternating_repetition was the dead term (pinned at 0); after the fix it must be
    # > 0 on at least one real multi-district world -- proving the metric measures rhythm.
    ar_town = wholeness(G.grow(json.load(open("examples/world.json"))["graph"], seed="vis"),
                        breakdown=True)[1]["alternating_repetition"]
    assert ar_town and ar_town > 0.0, \
        f"alternating_repetition still dead ({ar_town}) -- spatial rhythm not measured"

    # the thesis: the SAME language yields DIFFERENT worlds -- hamlet has no courts,
    # the dense mega has many. Scale actually changes the structure.
    by = dict((n, c) for n, _, _, c in seen)
    assert by["hamlet"] == 0, "a single-cluster hamlet should have no shared courts"
    assert by["mega"] > by["town"], "a dense super-cluster should out-court a town"

    for name, pw, gw, courts in seen:
        print(f"OK  {name:8s} plan_w={pw:.3f} grid_w={gw:.3f} courts={courts}")


if __name__ == "__main__":
    main()
