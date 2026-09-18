# WebUI Evaluation Benchmarks

The WebUI has an **Evaluation** tab for repeatable quality checks against the
current knowledge base. It is intended for admin/dev use after changing prompts,
models, embeddings, extraction logic, or retrieval logic.

## Benchmark Locations

Benchmark files are JSON files. The backend searches these locations:

1. `EVALUATION_BENCHMARK_DIR`, if set
2. `<rag_storage parent>/evaluation/benchmarks`
3. `evaluation/benchmarks` in the application checkout
4. `lightrag/evaluation/benchmarks` inside the Python package

For VPS work, the easiest editable runtime location is usually:

```text
data/evaluation/benchmarks
```

Set `EVALUATION_BENCHMARK_DIR=/app/data/evaluation/benchmarks` if you want to
mount benchmark files there without rebuilding the image.

## Run Modes

The Evaluation tab supports three modes:

- `graph`: checks graph entities, relations, and metadata coverage only. This
  does not call the query pipeline.
- `retrieval`: also runs query/context checks. This can call the query pipeline,
  but benchmark cases should include `hl_keywords` and `ll_keywords` to avoid
  unnecessary keyword-generation calls.
- `full`: asks LightRAG to generate answers and then checks answer content and
  references. This is the most useful end-to-end check, but it can use LLM
  tokens.

## Benchmark Format

Example:

```json
{
  "id": "pem_phase1_directed_quality",
  "name": "PEM Phase 1 Directed Relationship Quality",
  "description": "Checks directed production and causal relationships.",
  "default_mode": "mix",
  "cases": [
    {
      "id": "electrode_root_cause_chain",
      "question": "What can cause coating defects in electrode production?",
      "mode": "mix",
      "top_k": 40,
      "chunk_top_k": 20,
      "hl_keywords": ["battery electrode production", "root cause analysis"],
      "ll_keywords": ["electrode stacking", "electrode thickness", "coating defect"],
      "expected_entities": [
        "Electrode Stacking",
        "Electrode Thickness",
        "Coating Defect"
      ],
      "expected_relations": [
        {
          "source": "Electrode Stacking",
          "relation_type": "influences",
          "target": "Electrode Thickness",
          "directionality": "directed"
        }
      ],
      "must_include": ["electrode thickness", "coating defect"],
      "expected_documents": ["example-source.pdf"]
    }
  ]
}
```

## Score Meaning

- `Graph`: expected entity and relation checks.
- `Metadata`: coverage for `directionality`, `relation_type`,
  `relation_importance`, `chain_role`, and specific non-generic relation types.
- `Retrieval`: expected terms and source documents found in retrieved context or
  generated answers, depending on run mode.
- `Overall`: weighted average of available graph, metadata, and retrieval
  scores.

## Promotion Quality Gates

Each benchmark may optionally define a `quality_gates` object. Gates make a
benchmark result actionable for staging promotion without imposing one global
threshold on every smoke test. A configured gate appears in the WebUI and is
also appended to `failed_checks` when it fails.

```json
{
  "quality_gates": {
    "min_scores": {
      "graph": 80,
      "metadata": 80,
      "directed": 80
    },
    "min_metadata_coverage": {
      "directionality": 90,
      "relation_type": 90
    },
    "min_directed_strategy_scores": {
      "directed": 80,
      "combined": 80,
      "auto": 80
    },
    "max_failed_checks": 0,
    "require_directed_cases": true
  }
}
```

All threshold values are percentages. Do not copy the example blindly: choose
them after recording a reviewed baseline for the particular document set.

## Directed Retrieval Gate

The packaged `pem_directed_retrieval_quality` benchmark additionally runs every
configured chain case four times, with `normal`, `directed`, `combined`, and
`auto`.
It uses `only_need_context=true`, so the comparison does not generate three
LLM answers. The normal run is a regression guard: it must report no directed
provider call. Directed, combined, and auto runs are scored from structured
path diagnostics, not from free-form answer text. For chain cases, `auto` must
resolve to `combined` unless the case declares another
`expected_auto_strategy`.

Add `expected_directed_paths` to a normal case to opt in:

```json
{
  "id": "root_cause",
  "question": "What causes lithium ion transport degradation?",
  "expected_edge_direction": "in",
  "expected_directed_paths": [
    {
      "traversal_nodes": [
        "Lithium ion transport",
        "Electrochemically inert phases",
        "Impurities"
      ],
      "relation_types": ["degrades", "causes"],
      "source_documents": ["battery-guide.pdf"],
      "require_citations": true
    }
  ]
}
```

Use `nodes` for an outgoing semantic path and `traversal_nodes` for an incoming
root-cause path, which is naturally traversed from effect back to cause. The
WebUI shows a `Directed` score plus per-strategy scores and individual path
status. A missing or mismatched expected path is included in Failed Checks.
Set `require_citations` for important acceptance cases: the benchmark then
requires at least one real reference ID resolved from a stored source chunk.

The query context applies the same safety rule: a discovered directed graph
path without a resolvable source chunk remains visible in retrieval diagnostics,
but is excluded from the LLM context. `citable_path_count` and
`uncited_path_count` make this distinction visible in the Retrieval tab.

The benchmark deliberately avoids exact-answer matching. Expected entities,
relations, must-include terms, and expected source documents are more robust
across model and prompt changes.
