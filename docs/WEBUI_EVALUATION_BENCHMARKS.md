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

The benchmark deliberately avoids exact-answer matching. Expected entities,
relations, must-include terms, and expected source documents are more robust
across model and prompt changes.
