# Offline alias replay

This pilot is read-only and does not modify Neo4j, ingestion, retrieval or
benchmark scoring. It compares directed paths of 2-4 edges using original
entity names against paths using the reviewed aliases in
`evaluation/aliases/exploratory_aliases_v1.json`.

## Input

Export a bounded, non-secret graph snapshot as JSON with an `edges` array.
Each edge needs a unique `id`, `semantic_src_id`, `semantic_tgt_id`,
`directionality`, `relation_type`, `source_id`, and optionally `file_path`
and `description`. Do not substitute Neo4j's physical start/end node for
the semantic endpoints when these differ. Example:

```json
{
  "edges": [
    {"id": "edge-1", "semantic_src_id": "Model",
     "semantic_tgt_id": "Temperature Prediction", "directionality": "directed",
     "relation_type": "produces", "source_id": "doc-x-chunk-001"}
  ]
}
```

Limit the snapshot to at most 10,000 edges, preferably a fixed set of
documents or a bounded neighborhood around the candidate aliases. Keep
exported document content and graph descriptions outside Git. When exporting
from Neo4j, select semantic endpoints, not just the stored relationship
direction; use a stable relationship ID for this one snapshot. The export
must represent the same graph state for both baseline and projected paths.
Physical pair edges may collapse multiple assertions; this pilot cannot
recover assertions absent from the export.

With a staging Neo4j SSH tunnel open and `NEO4J_URI`, `NEO4J_USERNAME` and
`NEO4J_PASSWORD` set locally, create the private export with:

```powershell
.venv\Scripts\python.exe -m scripts.export_alias_graph `
  "$env:TEMP\bounded_graph_export.json" --limit 5000
```

The exporter uses a read-access Neo4j session and reports whether its result
was truncated. It does not store credentials in the output. A truncated
snapshot can miss paths; its counts are not whole-graph totals. Descriptions
may contain private document text, so keep the JSON and review report out of
Git.

## Run (local PowerShell)

```powershell
.venv\Scripts\python.exe -m scripts.offline_alias_replay `
  "$env:TEMP\bounded_graph_export.json" `
  evaluation/aliases/exploratory_aliases_v1.json `
  "$env:TEMP\alias_replay_result.json" `
  --max-hops 4 `
  --review-markdown "$env:TEMP\alias_path_review.md"
```

The output has `additional_paths` and the strict subset
`causal_additional_paths` and `mixed_additional_paths`. Each hop retains its original endpoint names,
predicate, source ID and optional description. The causal subset requires
every predicate to be in the script's explicit causal allowlist; `produces`,
`studies`, `used_for` and `measures` are not assumed causal.
Mixed paths contain at least one causal and one noncausal predicate. They are
exploration leads, never inferred causal statements. The Markdown report
prioritizes causal, then mixed candidates for a bounded manual source review.
The `suggested_aliases` list contains lexical singular/plural leads only when
both names touch causal edges; these require expert approval and are not
used by the replay until explicitly entered in the versioned alias file.

Path identity is the ordered sequence of exported edge IDs. An additional
path is newly traversable through an alias join, not a new source assertion.
Aliases are lexical joins, not causal hops. Repeated concepts are rejected to
avoid projected cycles. This is neither a recall score nor proof that
conditions, attribution and predicates compose correctly. Review source
passages for a sample of high-value bridges before enabling any live path.
If a reviewed sample of candidate bridges produces no useful, supported
mechanisms, stop the alias expansion pilot and investigate missing assertions
or predicate quality instead of broadening aliases just to raise path counts.
