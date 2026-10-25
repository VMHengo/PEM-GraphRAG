# Exploratory Connection Discovery

Status: 2026-10-25 local MVP; Staging behavior and expert utility are untested.
This plan serves the explicit exploratory product goal in the roadmap.

## Product contract

Input: a known graph node X, downstream direction, maximum 2-4 hops and result
limit. Output: multiple distinct endpoints Z in other provisionally classified
battery-engineering subject areas. For each candidate, show X and Z, an ordered
list of semantic edges X -> Y1 -> ... -> Z, and source chunks per edge. Do not
render a fabricated direct `X -> Z` predicate. Label all paths unreviewed.
An empty result is valid and must not be completed by language-model inference.

## Is the current pipeline sufficient?

Sufficient for a *hypothesis-generating demo*, not an autonomous causal
discovery claim. Directed paths, up to five hops, source IDs and `/query/data`
already exist. The four-edge synthetic fixture passed, but sign reversals and
unsupported attributions also occurred. Therefore the demo starts at 2-4 hops,
uses only directed, source-resolved, route-relevant predicates, and retains
the original chunks. It must not call the extraction service or mutate the
graph. A keyword-LLM may still be used by existing query planning; the
endpoint avoids answer generation, not all model cost.

## Milestones and acceptance

| Milestone | Work | Acceptance |
| --- | --- | --- |
| M0: Local MCP prototype | Read-only `/query/data` client, provisional subject classifier, bounded path formatting and per-edge source chunks | No path with reversed semantic endpoints, generic/negated predicate, unknown target domain or unresolved source; existing MCP tools unchanged |
| M1: Staging smoke test | Deploy backend and gateway together; inspect real path diagnostics and source resolution | At least one real 2-4-hop result can be manually opened in its documents; no unrelated service restart or graph writes |
| M2: Expert pilot | Blindly review the top 20 diverse proposals from several seed nodes | Record interest, per-hop support, sign/direction, compatibility of conditions, and follow-up value; publish counts and rejected examples |
| M3: Reliable classification | Versioned, multi-label domain taxonomy and reviewed ontology mapping; separate graph data from UI layout | Unknown and conflicting labels visible; cross-area score stable when layout changes |
| M4: Evidence improvement | Sentence/span proposals, condition extraction, negative/ambiguous-claim gating and source-backed assertion review | Reviewed errors from M2 decrease on frozen artifacts without lost recall hidden by scoring changes |
| M5: Broader exploration | Query-aware path diversity, alternative paths, 5-hop pilot, optional graphical explorer | Held-out utility, evidence quality, latency and cost improve against M0 at a fixed budget |
| M6: Review workflow | Human labels and optional model triage, immutable reviews per assertion and extraction revision | Random audit sample plus priority queue; model hint never counts as human validation |

M0 does *not* assign a calibrated novelty or truth score. Domain assignment is
a small keyword table; distance in a force-directed or UMAP UI layout is not
a scientific measure of semantic distance. A later subject taxonomy can define
auditable distances, but source support and path plausibility must gate novelty.

## Local MVP interfaces and limits

- `explore_pem_connections(start, hop_depth=3, limit=5)` is the new MCP tool;
  one call returns at most 10 detailed paths. Review 20 across several seeds.
- The LightRAG backend contributes per-edge source IDs to path diagnostics;
  the gateway joins them to `/query/data` chunks. Both changes are additive.
- `lightrag_mcp/exploration.py` contains provisional subject keywords,
  predicate policy and deterministic formatting. One endpoint per candidate
  keeps initial results diverse; round-robin across endpoint areas is bounded.
- The tool requires an exact starting node label. It does not perform entity
  resolution, proof checking, sentence-level citation or contradiction search.
  It may find no candidate despite relevant corpus evidence; matching retrieved
  node names are returned as suggestions for a second call.
- An excerpt of at most 900 characters from the first resolved source per hop
  is a *chunk preview*, not
  an automatically verified supporting sentence. File URL is supplied when
  document metadata provides one.

## M2 review sheet

For each of 20 candidates, record seed, endpoint, source domains, hop count,
retrieval rank, each hop's document and verdict (`supported`, `partly`,
`contradicted`, `unclear`), condition compatibility, overall novelty, overall
interest and next action. Keep reviewer identity and artifact/graph revision.
Report both: (a) fraction with *all* hops supported and compatible and (b)
fraction rated worth follow-up. Do not call the latter causal accuracy. Include
rejected candidates; they reveal ranking and extraction failure modes.

## Safe progression

Do not promote from Staging to Production on a synthetic benchmark score alone.
Use a fixed corpus and seed list, compare the unchanged normal/combined query
experience, and record resource use. The later Human-in-the-Loop interface
reviews individual assertions plus complete paths; a model may propose a
verdict with an explicit source span, but human labels stay separate.
