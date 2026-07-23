<!-- Status: Phase 5 done, Phase 6 (full integration) pending | Written: 2026-07-03 | Compiler works in sandbox mode only; not yet the default level generator -->
# ARCHITECTURE_SPEC — Pattern-language generation for vaultcrawl

> *"When you build a thing you cannot merely build that thing in isolation, but must repair
> the world around it."* — Christopher Alexander

This is the design for replacing vaultcrawl's level generator with one that grows **living
architecture** from the vault corpus. It is grounded in Alexander's *A Pattern Language*,
*The Timeless Way of Building*, *A City Is Not a Tree*, *A New Theory of Urban Design*, *The
Production of Houses*, and *The Nature of Order* (esp. Book 3, *A Vision of a Living World*).

It is a spec, not code. It is written to be **directly buildable** against the codebase we
already have (the graph block in `world.json`, `analyze.py`, `mapping.py`, `dungeon.py`, the
runtime systems) and **reviewable** before any implementation.

---

## 0. The thesis

Our current generator is a **tree**: `dungeon.py` connects rooms with a *minimum spanning
tree* of corridors, and `mapping.py` partitions notes into *disjoint* region-zones. "A City
Is Not a Tree" names this precisely as the structure that kills places — a tree forbids
**overlap**, and overlap is where life lives. But the vault's link graph **is a semilattice**
(notes belong to many overlapping contexts). We have been collapsing the richest structure we
own into the poorest.

The pivot, in one sentence: **stop imposing a tree; grow a field of centers, as a
semilattice, where each increment heals the whole, and let the style emerge from the words.**

Five commitments, one per book:

| Book | Commitment |
|---|---|
| *Timeless Way* | No imposed aesthetic. Style is *read from* the corpus; patterns are structural relationships only. |
| *A Pattern Language* | A generative grammar: `context → forces → solution`; patterns **compound** (large completed by small). |
| *A City Is Not a Tree* | Connectivity is a **semilattice** (loops + overlap), never an MST. Shared-membership notes are shared spaces. |
| *A New Theory of Urban Design* | Growth rule: **every increment must make the larger whole more whole.** |
| *Nature of Order* | The world is a recursive **field of centers**; generation = **unfolding** via the 15 properties of living structure. |

---

## 1. Inputs — the corpus' dynamics

Everything is computed from the vault graph. We already emit most of this in
`world.json["graph"]["nodes"][id]`: `pagerank, degree, community, bridge, role, activity,
tags, neighbors`. The spec adds the metrics in **bold** (new work in `analyze.py`):

| Signal | Source | Architectural meaning |
|---|---|---|
| **importance** | PageRank | a center's *intensity* (how strong a center) |
| **flow** | **betweenness centrality (Brandes)** — NEW | "what flows becomes the facilitator": promenades, gateways |
| membership | community label(s) — **allow multi-membership**, NEW | district(s) a center belongs to; **overlap** = shared court |
| adjacency | `neighbors` (link graph) | which centers want to be near / connected |
| **interlock** | **edge weight = co-link / shared-tag count**, NEW | how deeply two centers should interpenetrate |
| friction | weak / cross-community / rival edges | boundaries, seams, the void between |
| age | `activity` (mtime, normalized) | growth rings, gradients (old core → new frontier) |
| inner scale | headings + length | levels of scale *within* a center |
| outlier-ness | low degree / orphan | discoveries, hung off an inflection point |
| tag field | `tags` | echoes, gradients, the emergent "style" vocabulary |

**New metric — betweenness.** Add `betweenness` to each node via Brandes' algorithm
(unweighted, O(V·E), deterministic). This is the load-bearing "flow" signal the current
engine lacks. **New metric — multi-membership.** Community detection currently assigns one
label per note; the architecture needs the *semilattice*, so we also record, per note, the
set of communities its neighbors belong to (a note bridging two clusters has membership
`{A, B}` → it is a shared court). **New metric — interlock weight** on each edge:
`1 + (shared tags) + (mutual link ? 1 : 0)` — how hard two centers should interpenetrate.

---

## 2. Data model

```
Center        # one per note (and, recursively, sub-centers inside it)
  id, source_note
  intensity    # 0..1  (PageRank-derived)  -> size + importance
  flow         # 0..1  (betweenness)        -> is it a facilitator?
  members      # set[community]             -> 1 = district room; 2+ = shared court (overlap!)
  age          # 0..1                        -> gradient / growth ring
  scale_levels # list of inner sub-centers from headings/length
  tags         # the style vocabulary
  role         # hub | bridge | leaf | orphan | cluster
  # filled by the compiler:
  pos, footprint   # placed geometry (an organic region of tiles, not a rectangle)
  sub_centers      # focal void, boundary ring, alcoves (the recursive unfolding)

Seam          # between two centers / districts
  a, b, kind   # "path" | "gateway" | "shared_court" | "boundary" | "void"
  strength     # from interlock weight / friction

SitePlan      # the whole, BEFORE carving
  centers: dict[id -> Center]
  seams:   list[Seam]            # a SEMILATTICE (cycles + overlap), never a tree
  growth_order: list[id]         # the order wholeness-growth placed them
  wholeness: float               # the score the plan achieved
```

The `SitePlan` is the living structure; carving turns it into `Level` tilemaps the existing
runtime consumes. The semilattice lives in `seams` (a center may share courts with several
districts and sit on several route-systems at once).

---

## 3. The pattern catalogue

A pattern is `{ id, scale, context (a predicate over the graph), forces, solution (a site
operator), properties (which of the 15 it advances) }`. Patterns **compound**: higher-scale
patterns are *completed* by lower-scale ones (the `completed_by` field). The catalogue below
is the v1 language (~15 patterns); it is extensible — new patterns register like our brains.

### Region / town scale
- **P1 · Megastructure** — *context:* a dense super-cluster (a community whose internal edge
  density and summed intensity exceed a threshold). *forces:* many strong, tightly-linked
  ideas want to be one great thing, yet must stay legible. *solution:* a multi-wing edifice
  spanning several depth-levels, its wings = sub-communities, its core = the cluster's most
  central note. *completed_by:* P4, P5, P7. *properties:* Levels of Scale, Strong Centers.
- **P2 · Organic City / Town** — *context:* several communities of moderate density linked by
  bridges. *solution:* districts placed around shared courts and a main promenade; grown, not
  gridded. *completed_by:* P4, P6, P8. *properties:* Not-Separateness, Gradients.
- **P3 · Hamlet / The House** — *context:* a small/thin corpus (few notes). *solution:* one
  intimate map — a homestead or a single Discovery; quiet, complete, small. (*Production of
  Houses* scale: economy + inner calm.) *properties:* Simplicity & Inner Calm, Positive Space.

### District / neighbourhood scale
- **P4 · Identifiable Neighbourhood** — *context:* one community. *forces:* a cluster of ideas
  is one place but each idea wants its own room. *solution:* a clustered, cellular quarter
  (rooms budding off shared courts), bounded, with one or two gateways — **never a grid**.
  *completed_by:* P9, P10, P11. *properties:* Boundaries, Echoes, Good Shape.
- **P5 · Wing** — *context:* a sub-community inside a Megastructure. *solution:* a coherent
  limb of the great structure, repeating the cluster's motif (Echoes). *properties:* Echoes,
  Alternating Repetition.
- **P6 · Shared Court (the semilattice node)** — *context:* a note with `|members| ≥ 2`.
  *forces:* it belongs to two districts at once; a tree would force a false choice.
  *solution:* a court that **both** districts open onto — the overlap made spatial. This is
  the pattern that makes the world a semilattice. *properties:* Deep Interlock & Ambiguity,
  Not-Separateness.

### Connective scale
- **P7 · Promenade** — *context:* a high-betweenness chain (a flow spine). *solution:* a main
  way with activity along it; loops back (no dead tree-branch). "What flows becomes the
  facilitator." *completed_by:* P8, P12. *properties:* Gradients, Alternating Repetition.
- **P8 · Main Gateway / Threshold** — *context:* a path crossing a community boundary (a
  bridge edge). *solution:* a marked threshold — a deepening, a narrowing, a gate.
  *properties:* Boundaries, Levels of Scale.
- **P9 · Activity Node** — *context:* a center where ≥3 paths meet (local betweenness peak).
  *solution:* a small busy square where ways converge. *properties:* Strong Centers, Positive
  Space.

### Room / detail scale
- **P10 · Strong-Centered Room** — *context:* any placed center. *solution:* an organic room
  with a **focal sub-center** (a void, a column, a feature) so the room is itself a field of
  centers. *properties:* Strong Centers, Local Symmetries.
- **P11 · Levels of Scale (within)** — *context:* a note with headings / long body.
  *solution:* nested sub-rooms / alcoves inside the center, sized in a smooth ~2–3× gradient.
  *properties:* Levels of Scale, Roughness.
- **P12 · Discovery** — *context:* an orphan / low-degree outlier. *forces:* the outlier is
  precious *because* it is hard to reach. *solution:* a hidden nook **attached only at its
  inflection point** — the bridge/center nearest it in graph terms — reached by a single
  quiet way. *properties:* Contrast, The Void.
- **P13 · Boundary / Friction Seam** — *context:* a weak or rival edge between communities.
  *solution:* a thick boundary — a wall, a chasm, a contested seam, or **The Void** (a large
  calm empty positive space) where two fields refuse to merge. *properties:* Boundaries, The
  Void, Contrast.
- **P14 · Growth Ring / Gradient** — *context:* the `age` field across centers. *solution:*
  arrange so a quality varies *gradually* across the map — oldest/most-central deepest, recent
  notes on the frontier; public→private, bright→dark. *properties:* Gradients, Levels of Scale.
- **P15 · Roughness & Echo pass** — *context:* the finished carve. *solution:* break mechanical
  regularity with adapted jitter, and reuse each district's room-motif so its spaces *rhyme*.
  *properties:* Roughness, Echoes, Not-Separateness.

A pattern's `solution` is a pure function `apply(siteplan, center|seam, rng) -> siteplan'`
(structure-preserving — it only intensifies the field, never destroys placed wholeness).

---

## 4. Wholeness — the 15 properties, operationalized

The growth algorithm and the validator both need a single number: how *alive* is a (partial)
plan? We operationalize each of Alexander's 15 properties as a measurable term in `[0,1]`,
then `Wholeness = Σ wᵢ · propertyᵢ`. The weights `wᵢ` are tunable; defaults below.

| # | Property | Measurable proxy (on the SitePlan / carved grid) | w |
|---|---|---|---|
| 1 | **Levels of Scale** | center-size histogram fits a smooth ~2–3× geometric ladder (KL-divergence from ideal, inverted) | 1.0 |
| 2 | **Strong Centers** | fraction of major rooms that contain a focal sub-center | 1.0 |
| 3 | **Boundaries** | mean boundary thickness/definition around centers (wall ring present) | 0.7 |
| 4 | **Alternating Repetition** | rhythm score of solid/void (and room/court) along promenades | 0.5 |
| 5 | **Positive Space** | (area in compact, convex-ish regions) / (total non-wall area); penalize slivers | 1.0 |
| 6 | **Good Shape** | mean room compactness `4π·area / perimeter²` | 0.8 |
| 7 | **Local Symmetries** | count of *small* local symmetries (centered doors, paired alcoves), not global | 0.4 |
| 8 | **Deep Interlock & Ambiguity** | for strongly-interlocked center pairs, presence of a fingered/shared transition (shared courts) | 1.0 |
| 9 | **Contrast** | variance of (size, openness, element) across *adjacent* centers | 0.6 |
| 10 | **Gradients** | monotonicity of a field (centrality / age / public→private) along principal axes | 0.8 |
| 11 | **Roughness** | controlled irregularity: penalize perfect grids AND pure noise; reward adapted variation | 0.5 |
| 12 | **Echoes** | motif reuse within a community (room-shape family resemblance) | 0.5 |
| 13 | **The Void** | presence of exactly one large calm empty positive space | 0.7 |
| 14 | **Simplicity & Inner Calm** | penalize redundant corridors / clutter (edges beyond what richness needs) | 0.8 |
| 15 | **Not-Separateness** | every center reachable + *softly* joined (no abrupt isolated blob); semilattice connected | 1.2 |

Notes:
- **#15 is also a hard constraint**, not just a score: the carve MUST be fully connected
  (solvable). The score rewards *soft* joining beyond mere reachability.
- **#5 Positive Space** is the workhorse that stops the "leftover corridor sludge" failure
  mode that afflicts naive room placement.
- The same function doubles as a **regression metric**: a generated map's wholeness can be
  asserted to stay above a floor in tests (so "aliveness" can't silently regress).

---

## 5. The growth algorithm — *unfolding*

Per *A New Theory of Urban Design*: the plan is **grown**, one structure-preserving step at a
time, each step chosen to **maximize the gain in wholeness**. Per *Nature of Order*: each step
is the application of a pattern that intensifies the field of centers.

```
def grow(graph, rng) -> SitePlan:
    plan = SitePlan(empty)
    centers = [Center(n) for n in graph.nodes]           # §2
    order = sort(centers, key=intensity, desc)           # strongest centers first
    # 1. SEED THE VOID + the great center
    place(plan, order[0], at=field_origin)               # the single most-central note
    intensify(plan, order[0])                             # P10/P11: focal void, inner scale

    # 2. PIECEMEAL GROWTH — each center placed where it heals the whole most
    for c in order[1:]:
        candidates = candidate_placements(plan, c)        # near its strong-link neighbours
        best = argmax(candidates, key=lambda pl: wholeness(plan.with(c@pl)) - wholeness(plan))
        place(plan, c, best)                              # New Theory: choose by Δwholeness
        intensify(plan, c)                                # recursive unfolding (sub-centers)
        # apply any patterns whose context now fires (megastructure, district, gateway...)
        for P in PATTERNS:
            if P.context(plan, c): plan = P.apply(plan, c, rng)

    # 3. CONNECT AS A SEMILATTICE (§6)  — NOT a tree
    plan.seams = connect_semilattice(plan, graph)

    # 4. OVERLAPS, DISCOVERIES, FRICTIONS
    for c in centers where |c.members| >= 2: P6.apply(plan, c)        # shared courts
    for c in centers where c.role == "orphan": P12.apply(plan, c)     # discoveries @ inflection
    for (a,b) in friction_edges: P13.apply(plan, a, b)                # boundaries / the void

    # 5. GLOBAL PASSES
    P14.apply(plan)   # gradients / growth rings (oldest+central deepest)
    P15.apply(plan)   # roughness + echoes
    return plan
```

`candidate_placements` proposes locations adjacent to a center's already-placed
strong-interlock neighbours (Deep Interlock), offset to leave **positive space** for a court
between them and a **boundary** ring around each. The greedy "place by Δwholeness" rule is the
literal encoding of "every increment must make the larger whole more whole." Determinism: `rng`
seeded from the vault content hash, identical to today's `seed`.

---

## 6. Semilattice connection (the heart of "a city is not a tree")

```
def connect_semilattice(plan, graph) -> seams:
    seams = []
    # (a) every real link becomes a way (NOT a spanning subset) -> cycles exist by construction
    for (a, b) in graph.edges:
        seams.append(Seam(a, b, kind="path", strength=interlock(a,b)))
    # (b) promenades: contract high-betweenness chains into main ways
    for chain in high_flow_chains(graph):  seams += promenade(chain)        # P7
    # (c) gateways where a way crosses a community boundary
    for s in seams where community(s.a) != community(s.b):  s.kind = "gateway"   # P8
    # (d) shared courts: a center with >=2 memberships is reachable from EACH district
    for c where |members(c)| >= 2:  ensure_reachable_from_each_district(c)        # P6 (overlap)
    # (e) guarantee Not-Separateness: if the note graph had disconnected components,
    #     join them at their nearest centers (the only place we *add* an edge for connectivity)
    seams += bridge_components(plan)
    # (f) Simplicity pass: drop a redundant way only if removing it leaves wholeness >= before
    seams = prune_for_calm(seams, plan)
    return seams
```

Contrast with the MST we replace:

| | MST (today) | Semilattice (this spec) |
|---|---|---|
| edges | exactly V−1 | the actual links + promenade loops + overlaps |
| cycles | none (tree) | yes (loops, alternate routes) |
| overlap | impossible | shared courts belong to multiple districts |
| feel | branching, dead-ends | woven, looping, alive |
| solvable | yes | yes (still connected; #15 is a hard check) |

The carve guarantees connectivity (a flood-fill from the entrance must reach the stairs and
every center), but it is a *network*, not a tree — which is the entire point.

---

## 7. Carving — organic geometry

Patterns emit **organic regions**, not rectangles. A center's footprint is grown by a small
deterministic blob/relaxation (e.g., a seeded metaball / cellular-automaton smoothing) sized
by `intensity` and shaped for **Good Shape** (#6, compactness target) and **Positive Space**
(#5). Sub-centers (P10/P11) carve a focal void and alcoves inside. Seams carve ways: paths are
1–2 wide, promenades wider with alternating bays (P7/#4), gateways narrow then open (P8),
shared courts are open positive space two districts touch (P6), boundaries are thick walls or
**The Void** (P13/#13). A final **Roughness/Echo** pass (P15) jitters edges off the grid and
reuses each district's room-motif so its spaces rhyme (#11, #12).

Output is the existing `Level` shape (`tiles[y][x]`, `walkable`, `player_start`, `stairs`) plus
a richer, **overlapping** region map (see §8).

---

## 8. How it slots into the codebase

New package `runtime/arch/` (compiler) + `vaultcrawl/architect.py` (bake-time site-plan).
Minimal, compatibility-preserving changes:

- **`analyze.py`**: add `betweenness` (Brandes), multi-membership sets, and edge interlock
  weights to the graph block. (Additive; existing consumers ignore new fields.)
- **`world.json`**: add an optional `siteplan` block (centers, seams, growth order) baked once.
- **`dungeon.py`**: `generate_level(...)` gains an architecture path. Two modes:
  - **continuous megastructure** (default): the whole SitePlan is one structure; floor *N* is
    the *slice* of it at depth-band *N* (depth still = centrality, consistent with today), so
    descending walks levels of scale of one great edifice.
  - **stacked**: each district → its own floor (for very large corpora).
  Falls back to today's rooms+MST when no siteplan is present (so the bare game still runs).
- **`mapping.py` regions become overlapping.** A tile may belong to several regions (the
  semilattice). For compatibility, every floor still exposes a **primary region** so
  `game.region_for(floor)` and all 18 runtime systems keep working unchanged; the overlap is
  extra structure the architecture carries (and that systems *may* later exploit, e.g. a
  shared court counting toward two factions).
- **Everything else rides unchanged.** Perception, ecology, brains, memory, salvage, quality,
  quests, NPCs, machines all consume `tiles` + `region_for` + the bus; they get living
  architecture instead of MST tunnels for free.
- **Invariants & determinism preserved.** The full-stack integration test already asserts
  connectivity, no-overlap, and determinism across worlds; the carve must pass it. Plus a new
  **wholeness regression**: generated maps must score ≥ a floor on §4.

---

## 9. Style is emergent (Timeless Way)

The compiler decides **structure only**. Surface — region/space names, materials, lore — comes
from the existing two-pass LLM + the bible `aesthetic` vocabulary + the quality system. A
dense, technical vault and a sparse, poetic one run the *same* pattern language and yield
utterly different worlds: a sprawling charged megastructure vs. a quiet mossy hamlet. We never
hand-author "the dungeon look"; it is the shadow the words cast.

---

## 10. The deeper layer — word-level dynamics (Phase 2+)

Graph-level (§1) is Phase 1. Below it lies the *text*: a note's headings already give inner
Levels of Scale (P11); going further, sentence/paragraph **flow** (transitions, rhythm,
question→answer structure) can shape promenade rhythm and intimacy gradients *inside* a center
(*Flow Through Rooms*, *Intimacy Gradient*). This is the most speculative claim ("the spaces
emerge from the dynamics of the words within") and is explicitly deferred until the
graph-level architecture reads as alive.

---

## 11. Validation — "how will we know it's alive?"

Two gates, both required:
1. **Measured.** The §4 wholeness score (and its 15-property breakdown) reported per generated
   map, across sample vaults of escalating size (hamlet → town → megastructure). Regression
   floors in tests.
2. **Seen.** Rendered maps (ASCII now; image export later) for the same vaults — because, per
   Alexander, the quality without a name is *recognized*, not proven. The prototype's job is to
   put those maps in front of us so we can feel whether the QWAN is there before the runtime
   commits to it.

---

## 12. Risks, constraints, phasing

**Risks.** (a) The wholeness heuristic is the whole game — too weak and it's noise, too rigid
and it's a grid; it needs iteration against *seen* maps. (b) Cost: Brandes is O(V·E) and the
greedy growth is O(V · candidates · wholeness-cost) — fine for vaults up to a few thousand
notes; needs spatial indexing / locality caps beyond that. (c) Connectivity under a semilattice
is easy to keep (we add, not remove, edges) — the risk is *too* connected (mush); the
Simplicity/Calm prune (#14) and boundaries (P13) counteract it. (d) Determinism must survive
the greedy argmax (stable tie-breaks, seeded rng).

**Phasing (proposed build order, each a fleet-able chunk):**
1. **[DONE]** **Metrics** — betweenness + multi-membership + interlock weights in
   `analyze.py`/manifest. (`tests/test_metrics.py`)
2. **[DONE]** **SitePlan + wholeness** — the data model (§2, `runtime/arch/model.py`) and the
   scorer (§4, `runtime/arch/wholeness.py`), pure, unit-tested. (`tests/test_wholeness.py`)
3. **[DONE]** **Growth + semilattice** — §5 + §6 (`runtime/arch/grow.py`), producing a
   SitePlan; asserted a connected semilattice with cycles and shared courts.
   (`tests/test_grow.py`)
4. **[DONE]** **Carver + patterns** — §7 (`runtime/arch/carve.py`): footprints → floor, seams
   dispatched by pattern (gateway narrow-then-open P8, promenade with bays P7, plain path),
   focal voids hollowed at strong centers (P10) with the great center keeping the Void (P13),
   a roughness/edge pass (P15). Connectivity enforced LAST so no operator can strand a room.
   `grid_wholeness()` is the carve's regression metric (§4/§11): the §7 carve scores ~0.97 vs
   ~0.70 for a plain stamp on the sample worlds. (`tests/test_carve.py`)
   *Still open within §3:* the full pattern *catalogue* as registered operators (Megastructure,
   Wing, Activity Node, Growth Ring, Echo-motif) — the carver implements the load-bearing
   operators, not yet all 15 as pluggable Pattern objects.
5. **[DONE]** **Prototype/visualizer** — `runtime/arch/visualize.py` renders maps + the full
   15-property wholeness report across vaults of escalating scale (hamlet 3 notes → town 10/11
   → dense mega 18), the §11 *Seen* + *Measured* gates side by side
   (`python -m runtime.arch.visualize --gallery`). Looking at the maps drove two real fixes:
   (a) `alternating_repetition` was pinned at 0 — it measured rhythm along the size-sorted
   growth order (which can't alternate); now it measures spatial rhythm along a BFS of the
   seam graph. (b) Shared courts over-fired on dense vaults (every seam touching a
   multi-member node → "a court everywhere is a court nowhere"); now a court requires a
   genuine member-set boundary, so a single-cluster hamlet gets 0 and the dense mega gets
   many but legibly. Both lifted plan-wholeness across every scale.
   (`tests/test_visualize.py` locks the Measured gate as a regression.)
   *Still open:* full weight-tuning against human-judged "alive" maps (the deepest, most
   felt part of this gate) and image export — the ASCII gallery is the v1 *Seen* surface.
6. **Integrate** — wire into `dungeon.py`/`mapping.py` behind the fallback; full-stack
   integration + wholeness regression; README.

Phases 1–2 are foundation; 3–5 are the heart and the place to *look before leaping*; 6 commits
the runtime. Nothing before phase 6 touches the live game, so the current world keeps working
throughout.

---

## Appendix A — pattern object (for implementers)

```python
@dataclass
class Pattern:
    id: str
    scale: str            # "region" | "district" | "connective" | "room"
    def context(self, plan, focus) -> bool: ...     # a predicate over graph/plan
    forces: str                                     # the tension it resolves (doc)
    def apply(self, plan, focus, rng) -> SitePlan: ...   # structure-preserving operator
    properties: tuple                               # which of the 15 it advances
    completed_by: tuple                             # lower-scale patterns that finish it
# Patterns register into a catalogue exactly like brains/sense-profiles, so the language
# is extensible without touching the compiler.
```

## Appendix B — glossary mapping (your words → this spec)

- *"the frictions are seen"* → §3 P13 Boundary/Friction Seam; §1 friction edges.
- *"the outliers accessible from their inflection points"* → §3 P12 Discovery, attached at the
  nearest bridge (graph inflection point).
- *"what flows becomes the facilitator"* → §1 betweenness → §3 P7 Promenade / P8 Gateway / P9
  Activity Node.
- *"compound into organic patterns"* → §3 `completed_by` (large completed by small) + §5
  unfolding.
- *"style a unique world out of the interconnectedness and dynamics"* → §9 emergent style;
  the whole pipeline is corpus-driven, aesthetic-free.
- *"sprawling megastructures, smaller discoveries, organic cities"* → §3 P1 / P12 / P2; §8
  scaling by corpus size.

---

## 13. Realms & thresholds — the world-graph is a semilattice (the "JRPG shape")

Agreed with Zeo (re-established 2026-07-02 after the original conversation was lost;
LOGGED THIS TIME). One flat map is still a tree — branches on a plane. A chain of
floors is still a tree. The structure that is neither: a GRAPH OF MAPS.

- **Realms are nodes**: the surface overworld (§8's grown world) plus one
  depths-realm per region. Depths use the classic rooms+MST generator; both kinds of
  map carry note-rooms, tints, motifs, caches.
- **Gates are edges**: each district's TOWN (its anchor room — settled ground, its
  Keeper, rest, no hostile may enter) holds the door (>) down into its region's
  depths, where the region's warden dwells. A stair (<) climbs home. And PASSAGES (>)
  join the depths of BORDERING regions — the bridge notes made spatial.
- **Loops abound**: down through one district's door, across beneath the border, up
  another district's stair — a cycle no tree contains. "A City is Not a Tree" is now
  true of the map-graph itself, not only of each map's corridors.
- **Realms persist** (engine snapshots per realm): what you kill stays dead, what you
  search stays searched. Travel is geography, not an encounter generator.

Alexander mapping: towns = activity nodes / common land (safe, social hearts);
gates = P8 Main Gateway (a threshold that changes the rules); surface-to-depths =
the intimacy gradient (public square above, private depths, the innermost room —
the warden — at the bottom); the realm graph = semilattice (§6, lifted a level).

Implementation: `Game.traverse()` + `_generate_depths()` + per-realm snapshots
(`runtime/game.py`); tests in `tests/test_realms.py`.
