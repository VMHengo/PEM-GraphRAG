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

## Other Planned Work

The existing quality roadmap remains in
[Pipeline Research And Improvement Plan](PIPELINE_RESEARCH_AND_IMPROVEMENT_PLAN_2026-10.md).
Its P0-P7 packages are background until split into concrete tasks here. In
particular, normal-provider completion validation, targeted retries, and
idempotent merge recovery remain open. Add such work to the Ordered Queue when
it becomes the next implementation priority; do not infer completion from this
summary.
