# Exploratory Connection Discovery

Status: 2026-10-25 local MVP with provisional taxonomy and mention spans;
Staging behavior and expert utility are untested.
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
- `ontology/exploration_subjects_v1.json` contains provisional, exact-alias,
  multi-label subjects and optional source-file scopes. A versioned multi-label
  keyword fallback preserves coverage for unmapped graph names; its status is
  exposed separately. It is not yet an expert-reviewed ontology. Unknown and
  ambiguous concepts stay unclassified; no UI layout coordinates enter path
  selection.
- `lightrag_mcp/exploration.py` contains predicate policy and deterministic
  formatting. One endpoint per candidate
  keeps initial results diverse; round-robin across endpoint areas is bounded.
- The tool requires an exact starting node label. It does not perform entity
  resolution, proof checking, sentence-level citation or contradiction search.
  It may find no candidate despite relevant corpus evidence; matching retrieved
  node names are returned as suggestions for a second call.
- An excerpt of at most 900 characters from the first resolved source per hop
  is a *chunk preview*. A separate same-sentence mention with original chunk
  offsets is provided when found. Neither is an automatically verified causal
  assertion. File URL is supplied when document metadata provides one.

## M2 review sheet

The Evaluation > Human Review tab creates a saved snapshot of up to 20
cross-area, 2-4-hop proposals from up to five exact graph-node seeds. It does
not guarantee 20 results; empty seeds and failures are visible. The same
snapshot can be exported as a Markdown review sheet. Each row has the endpoint
connection, subject areas, ordered hop assertions, source document and URL,
chunk identifier, a candidate passage and extracted PDF text. Review sessions
retain up to three source chunks per hop, each capped at 12,000 characters
with truncation disclosed. The compact MCP response still uses one abbreviated
source. A passage is located by entity-name co-occurrence, not by relation
entailment; the reviewer must check direction, sign and conditions.

New review candidates also show a deterministic, versioned *indirect
hypothesis* for X -> Z. Signed `increases`/`decreases` hops compose by sign
only under an explicit monotonic-variable assumption. A path containing
`affects` or mixed broad predicates has unknown polarity. Non-causal or
unsupported predicates do not compose. The result never becomes a direct
Neo4j edge, and no numeric confidence is inferred from relation importance.
Up to two paths per target can enter the review pool; opposite signed routes
receive limited reserved slots so they are not silently collapsed. Automatic
checks do not establish source entailment or compatible physical conditions.

For each candidate, record each hop's verdict (`supported`, `partial`,
`contradicted`, `unclear`), condition compatibility, overall correctness,
interest, follow-up value and a note. Review events are append-only and retain
the extraction revision captured at session start. Reviewer names are entered
by users, not independently verified by the application. Currently there is
no calibrated novelty score or random-audit sample; those remain M6 work.
The separately recorded inferred-connection verdict is a human judgment, not
a model-verified fact. Existing session snapshots stay unchanged; create a new
session to use a later inference-rule version.
Report both: (a) fraction with *all* hops supported and compatible and (b)
fraction rated worth follow-up. Do not call the latter causal accuracy. Include
rejected candidates; they reveal ranking and extraction failure modes.

## Safe progression

Do not promote from Staging to Production on a synthetic benchmark score alone.
Use a fixed corpus and seed list, compare the unchanged normal/combined query
experience, and record resource use. The later Human-in-the-Loop interface
reviews individual assertions plus complete paths; a model may propose a
verdict with an explicit source span, but human labels stay separate.
