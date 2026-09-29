# Prompt Experiments

The Evaluation page can compare multiple extraction-prompt profiles without
modifying the active knowledge graph. A profile experiment uses retained chunks
from selected completed documents, creates a temporary isolated LightRAG
workspace for each profile, extracts and benchmarks it, then deletes the
temporary workspace. It stores the candidate's parsed per-chunk artefact under
`rag_storage/prompt_experiments/<experiment-id>/` so a final winner can be
promoted without another parsing or chunking pass.

## Enable on staging

Add the following non-secret settings to `.env.staging` and recreate the
`lightrag` service:

```env
PROMPT_EXPERIMENTS_ENABLED=true
# Keep false until final-prompt promotion has been tested on staging.
PROMPT_EXPERIMENT_PROMOTION_ENABLED=false

# Cost-estimation defaults for GPT-5.4 mini standard processing. Adjust these
# to the contracted Azure price rather than treating them as billing data.
PROMPT_EXPERIMENT_INPUT_COST_PER_MILLION=0.75
PROMPT_EXPERIMENT_OUTPUT_COST_PER_MILLION=4.50
PROMPT_EXPERIMENT_SYSTEM_OVERHEAD_TOKENS=1800
PROMPT_EXPERIMENT_ESTIMATED_OUTPUT_TOKENS=800
PROMPT_EXPERIMENT_SCREENING_CHUNKS_PER_DOCUMENT=10
PROMPT_EXPERIMENT_MAX_DOCUMENTS=20
PROMPT_EXPERIMENT_MAX_PROFILES=5
```

The UI lists valid `*.yml` / `*.yaml` files in
`PROMPT_DIR/entity_type`. Prompt text is never accepted directly from the
browser: only server-side YAML profiles can run. This keeps an experiment
reproducible and prevents arbitrary prompt payloads from being persisted.

When using Neo4j, leave `NEO4J_WORKSPACE` unset. The experiment runner gives
each candidate its own temporary workspace label; a globally forced workspace
would make those candidates overlap with the live graph and is rejected.

## Cost-aware workflow

1. Use **Screening** for 2-4 profiles. It uses the first configured number of
   chunks from each selected document and disables continuation extraction.
   It is deliberately not promotable.
2. Use **Validation** for the strongest one or two profiles. It uses all chunks
   but still disables continuation extraction.
3. Use **Final** only for the winner. It uses all chunks and retains the active
   continuation-extraction behaviour. Retrieval is the normal benchmark mode;
   Full QA additionally permits generated answers and can incur more query
   cost.

The shown estimate covers **extraction** requests. It estimates prompt tokens
from the selected YAML profile, retained chunk token counts, one continuation
pass when enabled, and the configurable input/output rates. Benchmark query
calls are intentionally reported as a separate, unpriced residual because they
depend on the benchmark cases and provider cache.

## Promotion

Promotion is a separate, confirmed operation and requires:

```env
PROMPT_EXPERIMENT_PROMOTION_ENABLED=true
```

Only a completed **Final** candidate can be promoted. Before promotion the API
verifies that every retained source chunk still has the fingerprint used by the
experiment. It then reserves the graph-maintenance slot, replaces only the
selected documents' entity/relation contribution with the stored candidate
artefact, and keeps the document, chunk embeddings, source metadata, and
download URL untouched.

The chosen YAML file is copied to a runtime snapshot in
`PROMPT_DIR/entity_type/promoted_prompt_<hash>.yml`. A pointer at
`rag_storage/active_extraction_prompt_profile.json` makes the selected profile
survive an API/container restart without changing `.env` or a tracked YAML
file. Documents not included in the promotion become outdated according to the
new extraction revision and can later be refreshed through **Documents**.

Do not run promotion during ingestion, scanning, deletion, or regular graph
maintenance. The route refuses work while the pipeline is busy. If a merge
fails, already changed selected documents are rebuilt from their retained
chunks using the previous prompt configuration before the maintenance slot is
released.

## Storage and cleanup

Manifests, artefacts, and benchmark results are intentionally retained under
`rag_storage/prompt_experiments/` for comparison and audit. Candidate vector
and graph workspaces are dropped after a run by default. Set
`PROMPT_EXPERIMENT_KEEP_CANDIDATE_WORKSPACE=true` only while debugging a
candidate workspace; it increases disk and Neo4j use.
