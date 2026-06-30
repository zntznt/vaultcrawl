"""Phase 1 architecture metrics: Brandes betweenness, multi-membership, interlock edges.

Run: cd /mnt/workspace/output/vaultcrawl && python3 -m tests.test_metrics
(assumes examples/world.json is freshly baked, like the other tests).
"""
import json

from vaultcrawl.analyze import betweenness


def main():
    # --- Brandes on a path a-b-c-d: the middles carry all the through-traffic ---
    path = {"a": ["b"], "b": ["a", "c"], "c": ["b", "d"], "d": ["c"]}
    bc = betweenness(path)
    assert bc["b"] > bc["a"] and bc["c"] > bc["d"], "path middles must out-flow the ends"
    assert abs(bc["a"]) < 1e-9 and abs(bc["d"]) < 1e-9, "leaves carry no through-flow"
    assert betweenness(path) == betweenness(path), "betweenness must be deterministic"

    # --- a star: the hub is THE facilitator (maximally between) ---
    star = {"c": ["a", "b", "d"], "a": ["c"], "b": ["c"], "d": ["c"]}
    sb = betweenness(star)
    assert sb["c"] > max(sb["a"], sb["b"], sb["d"]), "the hub of a star is the facilitator"
    assert abs(sb["c"] - 1.0) < 1e-9, "a star centre should be maximally between (1.0)"
    assert betweenness({}) == {} and betweenness({"x": []}) == {"x": 0.0}, "degenerate graphs"

    # --- on the freshly-baked sample world: new fields present + sane ---
    m = json.load(open("examples/world.json"))
    g = m["graph"]
    nodes = g["nodes"]
    assert all("betweenness" in n and "members" in n for n in nodes.values()), \
        "every node must carry betweenness + members"
    assert all(0.0 <= n["betweenness"] <= 1.0 for n in nodes.values()), "betweenness normalized"
    assert "edges" in g and g["edges"], "the interlock-weighted edge list must be emitted"
    for e in g["edges"]:
        assert e["interlock"] >= 1, "interlock weight floors at 1"
        assert e["a"] < e["b"], "edges are undirected + canonicalized (a < b)"

    # --- the semilattice: a bridge note spans >=2 communities (a future shared court) ---
    bridges = [k for k, n in nodes.items() if n.get("bridge")]
    assert bridges, "the sample world has bridge notes"
    assert any(len(nodes[b]["members"]) >= 2 for b in bridges), \
        "a bridge must span 2+ communities (the overlap that defeats the tree)"

    print("OK")


if __name__ == "__main__":
    main()
