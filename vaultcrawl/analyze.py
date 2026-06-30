"""Deterministic graph analysis. No third-party deps -- PageRank and community
detection (modularity / Louvain local-moving) are implemented in pure Python and are
fully deterministic, so the same vault always yields the same analysis.

Community detection uses one level of Louvain local-moving rather than label
propagation: it maximizes modularity, so a single "bridge" note between two dense
clusters does NOT collapse them into one blob -- the clusters stay separate and the
bridge edge becomes the border that drives faction relations.

Orphans (degree-0 notes) are isolated by definition; they never join a community and
are surfaced as secrets, not regions.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ingest import Vault


@dataclass
class Analysis:
    pagerank: dict          # id -> float (importance via inbound links)
    degree: dict            # id -> int   (undirected degree)
    community: dict         # non-orphan id -> community index (0 = largest)
    communities: list       # list[list[id]], by size desc; excludes orphan singletons
    bridges: set            # ids whose neighbors span >= 2 communities
    orphans: list           # ids with degree 0
    pr_sorted: list         # sorted pagerank values ascending (for tiering)
    betweenness: dict       # id -> normalized flow centrality (the "facilitator" signal)
    members: dict           # id -> sorted communities it + its neighbors belong to (semilattice)


def _undirected_adj(vault: Vault) -> dict:
    adj = {nid: set() for nid in vault.notes}
    for src, tgts in vault.out_adj.items():
        for t in tgts:
            adj[src].add(t)
            adj[t].add(src)
    return {n: sorted(s) for n, s in adj.items()}


def pagerank(out_adj: dict, damping: float = 0.85, iters: int = 100) -> dict:
    nodes = sorted(out_adj)
    n = len(nodes)
    if n == 0:
        return {}
    in_adj = {x: [] for x in nodes}
    outdeg = {x: len(out_adj[x]) for x in nodes}
    for x in nodes:
        for y in out_adj[x]:
            in_adj[y].append(x)
    pr = {x: 1.0 / n for x in nodes}
    for _ in range(iters):
        dangling = sum(pr[x] for x in nodes if outdeg[x] == 0)
        nxt = {}
        for x in nodes:
            s = sum(pr[m] / outdeg[m] for m in in_adj[x] if outdeg[m])
            nxt[x] = (1.0 - damping) / n + damping * (s + dangling / n)
        pr = nxt
    return pr


def louvain_local(adj: dict) -> dict:
    """One level of Louvain local-moving on an unweighted undirected graph.
    Deterministic: nodes processed in sorted order, ties broken by lowest community id.
    """
    nodes = sorted(adj)
    deg = {n: len(adj[n]) for n in nodes}
    m = sum(deg.values()) / 2.0
    comm = {n: i for i, n in enumerate(nodes)}
    if m == 0:
        return comm
    tot = {i: deg[n] for i, n in enumerate(nodes)}  # sum of degrees per community

    improved = True
    while improved:
        improved = False
        for n in nodes:
            ci = comm[n]
            ki = deg[n]
            tot[ci] -= ki  # pull n out of its community
            links: dict = {}
            for nb in adj[n]:
                links[comm[nb]] = links.get(comm[nb], 0) + 1
            candidates = dict(links)
            candidates.setdefault(ci, 0)
            best_c = ci
            best_gain = links.get(ci, 0) - tot[ci] * ki / (2 * m)
            for c, k_in in sorted(candidates.items()):
                gain = k_in - tot[c] * ki / (2 * m)
                if gain > best_gain + 1e-12:  # strict; sorted order => lowest id on ties
                    best_gain, best_c = gain, c
            comm[n] = best_c
            tot[best_c] += ki
            if best_c != ci:
                improved = True
    return comm


def analyze(vault: Vault) -> Analysis:
    adj = _undirected_adj(vault)
    pr = pagerank(vault.out_adj)
    degree = {nid: len(adj[nid]) for nid in adj}

    raw = louvain_local(adj)
    groups: dict = {}
    for nid, lbl in raw.items():
        groups.setdefault(lbl, []).append(nid)
    # keep only communities with at least one non-orphan member (drops orphan singletons)
    kept = [sorted(g) for g in groups.values() if any(degree[x] > 0 for x in g)]
    kept.sort(key=lambda g: (-len(g), g[0]))
    communities = kept
    community = {nid: ci for ci, g in enumerate(communities) for nid in g}

    bridges = set()
    for nid in community:
        nbr_comms = {community[nb] for nb in adj[nid] if nb in community}
        if len(nbr_comms - {community[nid]}) >= 1:
            bridges.add(nid)

    orphans = sorted(nid for nid in adj if degree[nid] == 0)
    pr_sorted = sorted(pr.values())

    bet = betweenness(adj)

    # Multi-membership (the semilattice): the communities a note + its neighbours span.
    # A note bridging two clusters has members {A, B} -> it becomes a shared court.
    members = {}
    for nid in adj:
        ms = set()
        if nid in community:
            ms.add(community[nid])
        for nb in adj[nid]:
            if nb in community:
                ms.add(community[nb])
        members[nid] = sorted(ms)

    return Analysis(
        pagerank=pr,
        degree=degree,
        community=community,
        communities=communities,
        bridges=bridges,
        orphans=orphans,
        pr_sorted=pr_sorted,
        betweenness=bet,
        members=members,
    )


def betweenness(adj: dict) -> dict:
    """Brandes' algorithm (unweighted, undirected), normalized to [0, 1]. Deterministic.

    This is the 'flow' signal the architecture needs — which notes are the facilitators
    that the most shortest paths run through. O(V*E)."""
    from collections import deque
    nodes = sorted(adj)
    n = len(nodes)
    bc = {v: 0.0 for v in nodes}
    if n < 3:
        return bc
    for s in nodes:
        stack = []
        pred = {w: [] for w in nodes}
        sigma = {w: 0 for w in nodes}
        sigma[s] = 1
        dist = {w: -1 for w in nodes}
        dist[s] = 0
        q = deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in adj[v]:               # adj is pre-sorted -> deterministic order
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = {w: 0.0 for w in nodes}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                bc[w] += delta[w]
    # undirected double-counts each path; normalize by the max possible pair-count
    norm = (n - 1) * (n - 2) / 2.0
    return {v: (bc[v] / 2.0) / norm for v in nodes}
