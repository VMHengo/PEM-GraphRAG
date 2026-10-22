# Project TODO

This is the canonical, ordered implementation queue. Detailed rationale lives
in linked plans. One checkbox represents one reviewable implementation step.
The long-term product goal is in the
[PEM GraphRAG Roadmap](PEM-GRAPHRAG-IMPROVEMENT-ROADMAP.md): evidence-grounded
battery-engineering multi-hop retrieval, product readiness, ChatGPT access via
MCP, and seamless developer and user workflows. Tasks here should state how
they contribute to these goals or identify themselves as necessary enabling work.
New long-term goals require explicit user input before changing the roadmap.

## How To Use This Queue

- "Implementiere den naechsten Schritt in der TODO" means: implement only the
  first unchecked, unblocked item in the **Ordered Queue** below, including its
  acceptance checks. Do not silently start the following item.
- Before coding, check the current source and prerequisites. If the item is
  already complete, verify its acceptance checks, mark it done, and continue
  to the next item. If genuinely blocked, mark it `[blocked]` with the concrete
  reason and select the next unblocked item; do not guess around the blocker.
- After implementation, update the checkbox, evidence (tests or manual check),
  and any newly discovered follow-up. Keep new plans reflected here as small,
  ordered tasks with a link to their detailed plan. Preserve unfinished work.
- Do not change staging or production as part of a TODO item unless that item
  explicitly includes deployment. Report any deployment steps separately.

## Ordered Queue

### Quality Benchmark Triage (before further extraction changes)

The last shared v2 Staging result was Overall 38.89, Graph 64.31 (Entity
94.51, Relation 34.11), Retrieval 96.52, Directed 3.81 and Directed Exact 0.
The formula is correct for the stress profile (Graph 35%, Retrieval 15%,
Directed 50%), but this is **not** answer accuracy. The saved result and live
graph were not available for this local audit, so run-specific attribution
remains provisional. The current stress fixture has 20 expected paths of
length two or three, not a four/five-hop accuracy test. Complete these checks
before paying for a broad re-run.

- [ ] **QUAL-01: Freeze and decompose one Staging failure run.** Read an
  existing `result.json` with `scripts/diagnose_benchmark_run.py`; record the
  benchmark/scorer/extraction revisions, document scope, active assertion and
  retrieval flags, and per-case entity, relation, path and citation failures.
  Use the developer diagnostic connector for bounded read-only graph checks
  when its tools become available; preserve the run and source evidence.
  Done when at least ten low-scoring cases are classified as missing graph
  assertion, present-but-filtered assertion, anchor/pruning miss, provenance
  failure, gold-granularity mismatch or strict-only scoring mismatch, with
  counts and representative source chunks. No model calls are needed.
- [ ] **QUAL-02: Score stored assertions, not only pair summaries.** The graph
  scorer currently reads physical edges from `get_all_edges()` and ignores
  `relation_assertions_json` except in optional ontology diagnostics. A local
  two-assertion example stores `causes` but scores it zero when the pair-level
  representative says `supports`. Expand valid assertions for graph scoring,
  retain legacy fallback and report physical-pair versus assertion counts;
  avoid counting Neo4j's undirected `MATCH` orientations twice. Done when
  focused tests cover two predicates/opposite directions on one pair and an
  unchanged graph can be re-scored without extraction or generation calls.
- [ ] **QUAL-03: Resolve Directed Exact semantics.** `Directed Exact` ignores
  reviewed `node_aliases` and `accepted_relation_types`, while semantic
  scoring honors them. Either accept full-credit reviewed alternatives or
  rename the metric to representation-exact; never accept reversed causes.
  Done when alias, predicate, direction and citation tests match the name.
- [ ] **QUAL-04: Review gold path granularity.** Audit the 20 gold paths in
  18 stress cases against PDF evidence. In the aging source, gas affects
  electrode spacing before current nonuniformity; the three-hop gold skips
  that intermediate. Record expert-reviewed alternative paths/conditions or
  an explicitly justified shortcut, not an invented causal edge. Done when
  every allowed path has a cited source span and a documented hop policy.
- [ ] **QUAL-05: Add source-scoped graph scoring.** The active runner reads
  all graph nodes/edges, while `document_scope` is only a prompt-experiment
  preflight. Add explicit scoped versus whole-KB coverage and bind scored
  assertions to declared source documents. Done when an edge from the wrong
  paper cannot earn scoped credit and legacy whole-KB mode remains available.
- [ ] **QUAL-06: Expose benchmark denominators and duplicates.** One edge can
  satisfy multiple gold items and extra wrong edges are not penalized. Report
  unique-edge/micro and per-case macro coverage, duplicate gold paths, and
  separate directed/combined/auto scores. Add precision only within a fully
  annotated scope; do not call other open-world edges false. Done when raw
  numerators and denominators explain every aggregate.
- [ ] **QUAL-07: Attribute directed retrieval losses on a frozen graph.** Only
  five entity-search hits seed paths; importance, Neo4j candidate cap,
  fanout and beam pruning can then hide a present chain. Add bounded counters
  for anchors, candidate assertions, predicate/direction rejects, surviving
  hops and citations. Done when each graph-present failure in QUAL-01 names
  its first failing retrieval stage without new extraction calls.
- [ ] **QUAL-08: Align reviewed predicates with traversal.** The router's
  allowlists exclude some full-credit gold alternatives (`increases`,
  `produces`, `contributes_to`); evidence fallback is off by default. Test a
  shared, query-specific predicate policy on held-out causal/process cases.
  Done when supported-path recall rises without unacceptable false positives,
  latency or context growth. Normal retrieval stays the default.
- [ ] **QUAL-09: Audit historic extraction completeness offline.** A local
  2026-10-16 Staging review found `status=incomplete` in 10/10 sampled
  aging-paper Batch outputs and 60/74 parameter-paper outputs at a 1,200-token
  cap; repaired JSON retained entities but lost relations. Current import
  validation cannot repair already imported data. Identify affected document
  revisions, finish reasons and output budgets using stored artifacts only.
  Done when a per-document repair list has source evidence and no new calls.
- [ ] **QUAL-10: Pilot one paid, reversible re-extraction.** After QUAL-09,
  re-extract one affected Staging document from retained chunks with a measured
  output budget, preserving ID, URL and source metadata. Compare completion,
  grounded edges, cost and rollback with its frozen baseline. Do not run
  Extract All until this pilot and scorer fixes pass; obtain explicit approval
  before starting paid model calls.
- [ ] **QUAL-11: Add claim-level answer checks.** Retrieval 96.52 currently
  measures `must_include` terms and expected document references, not truth;
  failed query status does not zero that score. Keep coverage metrics separate,
  gate failed queries, and score reviewed condition, negation and source
  support for full answers. Done when a cited but unsupported or reversed
  causal claim fails a test fixture.
- [ ] **QUAL-12: Run a paired end-to-end comparison.** On the same held-out
  documents and fixed scorer, compare normal, combined and directed answers.
  Done when the report states scorer version, graph/extraction revision,
  source scope, claim quality, path quality, latency and actual model cost.

Detailed plan: [Ontology Integration Plan](ONTOLOGY_INTEGRATION_PLAN.md).
These tasks introduce ontology support incrementally; current extraction and
retrieval remain the baseline until a measured staging pilot passes.

- [x] **ONT-01: Audit and reproducible ontology input.** Verify source-file
  closure, licenses, version/provenance and existing merged counts. Add a
  read-only validation command/test that reports differences without replacing
  `ontology/merged/merged.ttl` or its reports. Fix stale documentation for the
  now-present BTO files. Done when all 51 listed source files are accounted for,
  source/manifest mismatches are visible, and the command is covered by a test.
- [x] **ONT-01B: Reconcile the pinned ontology snapshot.** Adopted the locally
  corroborated BattINFO 0.7.0/Apache-2.0 source as a new curated baseline;
  archived the prior 0.8.0-beta merge, reviewed the 46 added/27 removed named
  triples, rebuilt in isolation, pinned SHA-256 for all 51 source files and
  updated the manifest, report and active graph together. The full separate
  BattINFO checkout is ignored. The read-only audit exits 0. Source licenses
  are recorded separately; the old 0.8.0-beta source is not recoverable.
- [x] **ONT-02: Reviewed mapping schema.** Add a versioned mapping from current
  PEM entity types and relation labels to ontology IRIs, preferred labels,
  aliases, inverses and source attribution. Mark unmapped/ambiguous cases
  explicitly. Done when the mapping validates against the merged ontology and
  reviewed causal, process and part-whole examples have deterministic results.
  Review the BattINFO 0.7.0 import pins against the older electrochemistry and
  chemical-substance modules in this union; do not infer compatibility from
  `owl:imports` without resolving their versions.
- [x] **ONT-03: Read-only ontology resolver.** Implement a small Python module
  that loads the reviewed mapping and resolves labels and inverses without
  modifying graph writes. Test German/English aliases, collisions, missing
  mappings, placeholder terms and incompatible domain/range hints. Done when
  existing extraction output is unchanged with ontology mode disabled.
- [ ] **ONT-04: Optional extraction annotation.** On an isolated path, attach
  ontology IRIs and mapping version to extracted entities/relations while
  retaining original labels, direction, evidence and document provenance.
  Extend the parser/merge/storage contract only after checking all backends and
  Batch import. Done when a staging document can be re-extracted without losing
  URL, chunks or old relation semantics, and legacy documents remain readable.
- [ ] **ONT-05: Ontology-aware evaluation and retrieval pilot.** Add separate
  exact, alias, inverse and hierarchy diagnostics to the benchmark; use mapped
  predicates in optional directed-path selection only after review. Done when
  held-out DE/EN queries and causal chains are compared with the unchanged
  baseline, including false positives, answer support, latency and cost.
- [ ] **ONT-06: Staging decision and migration runbook.** Document pilot results,
  schema/ontology version policy, rollback, and whether existing documents need
  retained-chunk re-extraction or metadata-only backfill. Done when a reviewed
  go/no-go decision and repeatable staging procedure exist; production rollout
  requires a separate explicit task.

Implementation hardening identified after the assertion-preservation work.
These tasks improve ingestion correctness and evidence-grounded multi-hop
answers; they do not change the long-term roadmap or authorize deployment.

- [x] **IMP-01: Optional entity VDB during edge merge.** Keep the existing-node
  VDB upsert inside the `entity_vdb is not None` guard in `operate.py`. Done
  when an existing endpoint can gain a relation source with no entity VDB,
  its graph provenance updates, and focused regression tests pass.
- [ ] **IMP-02: Assertion-native indexing.** Specify a stable per-assertion
  identity and index separately from the pair-level graph edge, with legacy
  read compatibility. Done when two predicates/opposite directions on one pair
  remain discoverable in normal and directed retrieval after write, restart,
  re-extraction and single-document deletion; measure storage and query cost.
  Local implementation and restart/delete regression tests are in place.
  Pending: staging cost and query-latency measurements on representative data.
- [ ] **IMP-03: Query-aware Neo4j neighbor selection.** Avoid discarding a
  relevant assertion when physical pair edges are capped before assertion
  expansion. Done when high-degree-node fixtures show recall under the
  candidate limit, the database query remains bounded, and latency is measured.
  The query now ranks route predicates before a per-anchor database LIMIT.
  Pending: live Neo4j EXPLAIN and high-degree recall/latency measurement.
- [ ] **IMP-04: Evidence-aware path ranking and predicate coverage.** Compare
  mean-only path scores with a weakest-link/evidence-aware score; review the
  router's hard relation-type allowlists. Done when held-out causal and process
  questions improve supported-path recall without an unacceptable rise in
  false-positive paths or context size.
  Optional ranking and evidence-backed predicate fallback are implemented.
  Pending: paired held-out benchmark comparison and domain review.
- [ ] **IMP-05: Validate normal extraction completion.** Reject missing,
  malformed or truncated per-chunk outputs before a document is marked fully
  extracted. Done when normal-provider and Batch imports enforce equivalent
  completeness checks and failures identify affected chunk IDs. Local normal
  extraction now checks the terminal legacy marker and strict JSON structure
  before tolerant parsing; invalid initial/gleaning cache entries are evicted
  without discarding valid earlier calls. Focused mocked tests cover both.
  Pending: confirm provider finish-reason propagation where
  available and verify one failed-chunk recovery on Staging.
- [ ] **IMP-06: Retry only failed extraction chunks.** Persist per-chunk
  failure state and retry without repeating successful calls. Done when a
  partially failed document recovers with bounded duplicate model calls and
  unchanged provenance for successful chunks.
- [ ] **IMP-07: Idempotent merge recovery.** Make graph/vector writes and
  document status recoverable after a partial merge failure. Done when a
  failure-injection test can rerun import or re-extraction without duplicate
  assertions, orphaned indexes or lost source metadata.
- [ ] **OPS-01: Isolated staging graph diagnostics MCP.** Implement bounded
  fixed graph-inspection tools behind a separate Auth0 audience and the
  `read:graph-diagnostics` permission. Done when unauthorized tokens receive
  401/403, developer-only Staging queries expose semantic edges with source
  provenance, and normal/Production MCP tools remain unchanged. Local code,
  focused tests and runbook are in place. Staging has returned 200 for health
  and protected-resource metadata and 401 for unauthenticated MCP access;
  authorized tool discovery, 403 without the permission, Neo4j behavior and
  Production isolation remain unverified. The diagnostic tools are not yet
  available in this Codex session. See
  [Staging Graph Diagnostics](STAGING_GRAPH_DIAGNOSTICS.md).

IMP-01 evidence (2026-10-22): an existing relation endpoint now updates graph
source IDs without an entity VDB; the guarded VDB path remains covered too.
Focused relationship/ontology tests: 16 passed; Ruff and `git diff --check`
passed. The broader extraction subset had 55 passes and two unrelated prompt
profile assertion failures; the full extraction suite could not collect its
optional Ollama driver test in the local environment.

ONT-01 evidence (2026-10-21): `python -m ontology.validate_sources` accounted
for and parsed all 51 files, then correctly exited 1 on the documented source
snapshot mismatch. `tests/ontology/test_validate_sources.py` covers matching
sources, missing files, version/license/count drift and stored-merge drift.
The audit details and safe command are in `ontology/README.md`.

ONT-01B evidence (2026-10-21): isolated build parsed 51 files with zero
failures; the read-only audit passed with 65,882 triples, matching structure
and zero grounded-triple differences. The previous report/graph are under
`ontology/history/`. Focused ontology tests: 10 passed; Ruff passed.
The exact `--deep` isomorphism check was stopped after sustained CPU work;
the structural/grounded audit passed, but formal isomorphism remains unverified.

ONT-02 evidence (2026-10-21): `ontology/pem_mapping_v1.json` covers ten PEM
entity types and 31 relation labels. Its conservative EMMO core mappings,
conditional cases, explicit ambiguity/unmapped entries and source-version
warning are validated read-only by `python -m ontology.validate_mapping`.
`tests/ontology/test_validate_mapping.py` covers causal orientation, process
output, part-whole inverses, unknowns, drift and malformed mappings. The
mapping is an offline candidate, not runtime-approved; expert review of
conditional semantics remains a gate before enabling annotations.

ONT-03 evidence (2026-10-21): `ontology/resolver.py` is a read-only optional
CLI/Python adapter that validates the pinned mapping before use. It resolves
curated DE/EN aliases, RDF/SKOS labels and inverse endpoint swaps while
reporting unknown, ambiguous, conditional and incompatible results without
asserting an IRI. Placeholder records are excluded. Ontology and extraction
regressions: 33 passed; Ruff passed. Extraction and retrieval do not import
the resolver, so the disabled baseline is unchanged.

ONT-04/05 partial work (2026-10-22): default-off, scalar graph annotations
record mapping status/version and reviewed mapped IRIs. A separate JSON
property retains distinct semantic assertions, source chunks and raw labels
for new opt-in extractions on one physical pair edge. Azure Batch import
checks its submitted mapping snapshot. Optional benchmark diagnostics inspect
the stored assertions without changing baseline scores; optional Neo4j
directed-neighbor expansion has its own default-off switch. See
`docs/ONTOLOGY_STAGING_PILOT.md` for the pending measurements. **Do not mark
ONT-04/05/06 complete yet:** legacy collapsed predicates cannot be recovered,
source URLs live on document metadata, and domain-reviewed gold data, live
staging compatibility, held-out comparisons and rollback evidence are absent.
These are gates before production or broader ontology-aware retrieval.

## Other Planned Work

The existing quality roadmap remains in
[Pipeline Research And Improvement Plan](PIPELINE_RESEARCH_AND_IMPROVEMENT_PLAN_2026-10.md).
Its P0-P7 packages are background until split into concrete tasks here. In
particular, normal-provider completion validation, targeted retries, and
idempotent merge recovery remain open. Add such work to the Ordered Queue when
it becomes the next implementation priority; do not infer completion from this
summary.
