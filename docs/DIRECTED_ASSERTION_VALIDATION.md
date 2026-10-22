# Directed Assertion Retrieval: Staging Validation

The pair-level graph edge remains the compatibility record. With
`ONTOLOGY_ANNOTATION_ENABLED=true`, new or re-extracted relations also receive
one relationship-vector row per assertion (predicate, semantic direction,
source chunk). `ONTOLOGY_ASSERTION_RETRIEVAL_ENABLED=true` expands those
assertions in Neo4j directed traversal. Existing pair vectors remain readable;
old documents do not gain assertion vectors until they are re-extracted.

## Safe rollout

1. Back up the staging graph, vector storage and document metadata. Do not
   rebuild production vectors as part of this check.
2. Enable both flags only in staging and re-extract a small, reviewed document.
3. Verify two predicates and opposite directions on the same entity pair in
   graph metadata, normal relationship search and directed path diagnostics.
4. Restart staging and repeat the queries. Re-extract the same document to
   check stable IDs. Delete just that document and verify that its assertions
   disappear while assertions supported by another document remain.
5. For a high-degree anchor, compare target-path recall with and without a
   restrictive candidate cap. Inspect Neo4j `EXPLAIN` for the per-anchor
   subquery and `LIMIT`; record its actual duration and returned candidate
   count. The service logs `Directed neighbor query completed` with duration
   and counts. The query bounds returned rows, but it still scans/sorts an
   anchor's physical relationships; measure that cost before wider rollout.

## Ranking comparison

Normal retrieval remains the default. Directed path ranking also keeps its
current `mean` setting by default. For paired benchmark runs, use the same
documents and directed cases with only these benchmark JSON settings changed:

```json
{
  "path_ranking_mode": "weakest_link",
  "allow_evidence_predicates": true
}
```

Both fields may also be set per directed case or sent in a REST query. Compare
supported-path recall, false-positive paths, citation coverage, directed
score, query duration and context size. The fallback accepts an out-of-list
predicate only when it is directed, source-backed, sufficiently important and
has a chain role matching the routed question. It does not make the normal
retrieval strategy use directed paths.

## Cost model

For a pair with `N` supported assertions, relationship-vector cardinality
changes from approximately one pair record to `N` assertion records. Initial
embedding work and stored vectors therefore grow roughly with `N`; the
existing `top_k` still caps results returned to normal retrieval. Repeated
pair merges may re-upsert existing assertions, so measure ingestion time and
embedding calls on a representative multi-document sample before enabling
this broadly. Record the staging baseline and revised values here after the
live validation; synthetic unit-test timings are not production estimates.
