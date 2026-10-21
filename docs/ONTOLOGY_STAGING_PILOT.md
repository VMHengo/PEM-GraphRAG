# Ontology Staging Pilot And Decision

Status: not run; no go/no-go decision. The mapping is a curated candidate, not
approved production semantics. Normal retrieval remains the baseline.

## Scope And Safety

The optional graph annotation path is gated by
`ONTOLOGY_ANNOTATION_ENABLED=true` and uses the pinned
`ontology/pem_mapping_v1.json`. The Docker image copies this JSON to
`/app/ontology/pem_mapping_v1.json`; a custom path may be supplied with
`PEM_ONTOLOGY_MAPPING_PATH`. Only `status=mapped` records assert an IRI.
Conditional, ambiguous and unknown labels retain the raw PEM label with an
empty IRI. This is graph metadata, not a new model prompt or ontology-guided
retrieval mode. `ontology_diagnostics=true` in a benchmark adds separate case
diagnostics without changing existing quality scores. New opt-in edges also
carry `relation_assertions_json`, preserving distinct assertions on a shared
physical pair edge. `ONTOLOGY_ASSERTION_RETRIEVAL_ENABLED=true` separately
expands them for Neo4j directed-neighbor queries; normal retrieval is unchanged.

**Do not enable on the shared staging or production graph yet.** Legacy pair
edges may have irreversibly lost other predicates. The new JSON assertion
property is opt-in and has not passed an end-to-end staging pilot. A graph
backup alone does not repair lost legacy assertion identity. Use an isolated
staging copy with separate document, chunk, graph and vector stores; do not
run re-extraction on a shared graph while compatibility is unverified.

## Pilot Procedure

1. Record the Git commit, mapping version/SHA-256, prompt profile, extraction
   algorithm version, schema version and model deployment. Verify the mapping
   with `python -m ontology.validate_mapping`. Review conditional mappings
   with a battery-domain expert; do not promote them by changing their status
   merely to improve benchmark scores.
2. Make and verify a restorable copy of staging's source documents, retained
   chunks, document-status metadata (including `source_url` and
   `download_url`), graph, vector stores and Batch job manifests. Use distinct
   Compose project/volumes for the pilot. Record document/chunk/edge counts and
   a checksum or export for the selected source records before any write.
3. Run unchanged baseline queries and benchmarks on held-out document families
   in German and English. Include manufacturing chains, defect root causes and
   electrochemistry. Capture exact/partial relation matches, directed-path
   support, unsupported statements, query latency, model tokens and cost.
4. Build the pilot image from the pinned commit, start only the isolated pilot
   services, set `ONTOLOGY_ANNOTATION_ENABLED=true`, and confirm the current
   extraction revision reports `ontology_annotation.enabled=true` plus the
   intended mapping SHA-256. Test one normal extraction and one Azure Batch
   import using the *same* mapping snapshot. Changing the mapping between
   submission and import must fail before a graph write.
5. Re-extract a single retained-chunk pilot document through
   `POST /documents/reextract` with
   `{"doc_ids":["<pilot-doc-id>"],"outdated_only":false,"force":true}`.
   Verify its original document ID, chunk IDs, source/download URLs and
   original PEM relation labels are unchanged. Check mapped and unmapped
   graph properties directly, including every assertion's predicate, semantic
   endpoints, evidence and source chunk ID. Delete one document contributing
   to a shared pair and confirm the other document's assertion survives while
   the deleted assertion's directional vector/chunk records disappear. Repeat
   after a restart; verify legacy documents still load.
6. Run the same held-out benchmark with `ontology_diagnostics=true` on the
   isolated graph. Report raw-exact, mapped-IRI-exact, alias, inverse,
   hierarchy-partial, unmapped and false-positive rates separately. The
   current mapping has no reviewed hierarchy entries, so no hierarchy credit
   should appear. Compare normal, directed and combined query modes with
   matched context budgets. First measure with assertion traversal disabled,
   then enable `ONTOLOGY_ASSERTION_RETRIEVAL_ENABLED=true` only in the isolated
   pilot and repeat. Inspect extra false-positive paths, provenance and
   latency. Do not interpret metadata coverage as answer accuracy.
7. Test disabling the feature and restoring the snapshot. Confirm the
   default retrieval path and document metadata are unchanged. Record restore
   duration and any graph/vector inconsistencies. Do not promote unless
   rollback has actually been rehearsed.

## Decision Record

| Gate | Required evidence | Current status |
| --- | --- | --- |
| Domain semantics | Reviewed causal, process and part-whole mappings; no invented IRIs | Pending |
| Assertion identity | Opposite directions and multiple predicates between one pair survive write, delete and rebuild | Local opt-in JSON path implemented; staging verification pending |
| Provenance | Source URL, retained chunks, raw labels and evidence survive re-extraction | Pending staging test |
| Batch parity | Normal/Batch graph fields match, mapping drift rejected | Local guard tested; staging pending |
| Quality | Held-out DE/EN precision, recall, path and supported-answer results beat or justify baseline | Pending |
| Operations | Latency/cost within budget, verified backup and rollback | Pending |

Decision: **NO-GO for production until every gate is reviewed**. A small
isolated annotation pilot is permissible, but its results are not a substitute
for end-to-end assertion-identity verification. If metadata alone improves diagnostics,
metadata-only backfill may be preferable to rerunning model extraction; if
prompts or extracted assertions change, use retained-chunk re-extraction in
an isolated workspace. Version ontology source, mapping JSON and extraction
algorithm independently. Production promotion requires a separate explicit
task and approval.
