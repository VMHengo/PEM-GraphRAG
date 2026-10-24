# High-Temperature Aging Retrieval Repair

## Frozen observation

The supplied one-document prompt experiment scored Graph 57.49, Directed 1.33,
and Directed Exact 0. The extraction artifact contains the complete three-edge
chain Electrolyte Decomposition -> Gas Generation -> Local Current Nonuniformity
-> Lithium Plating, yet the directed query did not return it. The old candidate
list contained mostly one- and two-hop paths. This is a graph-present retrieval
miss, not proof that another extraction call is necessary.

The benchmark's 100 retrieval score counted document references; it did not
check whether the answer contained the expected mechanism. Some zero relation
scores also came from reversed but semantically equivalent `part_of`/`contains`
component assertions. Other gold nodes and steps are genuinely absent in this
artifact; scoring changes do not reconstruct them.

## Implemented sequence

1. Route unambiguous English causal/root-cause questions in the correct
   direction. Keep `normal` as the default and explicit strategies authoritative.
2. Rank at most eight graph-confirmed anchors from entity/relation results and
   bounded keyword lookups. Prefer query-relevant nodes over generic paper
   concepts.
3. Permit bounded 1-5-hop traversal (default 2), score query keyword coverage,
   reduce the long-hop penalty, and preserve a mix of short and long paths
   within the existing top-k and context-token budgets.
4. Reject generic-label-only entity matches. Accept reversed predicates only
   when a reviewed gold item explicitly lists the inverse. Correct the
   IC-shift gold traversal direction; never reverse a causal assertion merely
   to raise the score.
5. Opt the aging fixture out of reference-only retrieval scoring. Keep
   reference coverage visible, and mark answer-quality evaluation as absent.

## Acceptance and limitations

Focused local tests cover routing, 1/3/5-hop bounds, diverse path selection,
inverse relations, false entity matches, and benchmark scoring. A local replay
of the supplied extracted chain put its three-hop path first within top 20.
This replay is not a Staging Neo4j or answer-quality result.

Before paying for another extraction, deploy only to Staging and run the same
benchmark against the frozen graph. Compare per-case path nodes, direction,
evidence chunks, score components, path-depth counts, latency and citations
against the saved baseline; do not compare overall scores across scorer/fixture
revisions. Then run a held-out answer check for conditional language and
unsupported causal claims. Re-extract only after graph-present retrieval misses
and gold/scorer mismatches have been separated from genuinely missing evidence.
