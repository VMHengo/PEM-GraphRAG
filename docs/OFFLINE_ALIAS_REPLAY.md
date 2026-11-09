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

## Run (local PowerShell)

```powershell
.venv\Scripts\python.exe -m scripts.offline_alias_replay `
  "$env:TEMP\bounded_graph_export.json" `
  evaluation/aliases/exploratory_aliases_v1.json `
  "$env:TEMP\alias_replay_result.json" `
  --max-hops 4
```

The output has `additional_paths` and the strict subset
`causal_additional_paths`. Each hop retains its original endpoint names,
predicate, source ID and optional description. The causal subset requires
every predicate to be in the script's explicit causal allowlist; `produces`,
`studies`, `used_for` and `measures` are not assumed causal.

Path identity is the ordered sequence of exported edge IDs. An additional
path is newly traversable through an alias join, not a new source assertion.
Aliases are lexical joins, not causal hops. Repeated concepts are rejected to
avoid projected cycles. This is neither a recall score nor proof that
conditions, attribution and predicates compose correctly. Review source
passages for a sample of high-value bridges before enabling any live path.
