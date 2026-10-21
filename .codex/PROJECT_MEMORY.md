# PEM GraphRAG Project Memory

Use this as short operational context for future work. Read the relevant
section instead of rediscovering stable project facts. Source code, active
environment variables, and the documents listed below remain authoritative.
Never store passwords, API keys, tokens, or private document content here.

## Working Context

- Main development branch: `feature/azure-batch-extraction`.
- Local workspace: Windows PowerShell. Python virtual environment: `.venv`.
- Staging VPS repository: `/root/PEM-GraphRAG`; Compose project:
  `pem-staging`; runtime environment: `.env.staging`.
- Production Compose project: `mcp`; runtime environment: `.env`.
- Staging Compose file exists on the VPS and is not present in this checkout.
- When rebuilding staging with benchmarks, include both:
  `deploy/mcp/docker-compose.staging.yml` and
  `deploy/mcp/compose.evaluation-benchmarks.yml`.
- Use Git as the normal delivery path. SCP is only a temporary targeted
  runtime update and requires a container rebuild, recreate, restart, or
  `docker cp` before it becomes active.

## Delivery Convention

After code or documentation changes, provide:

1. One `git add <path>` command per file changed by the task.
2. A `git diff --cached --check`, commit, and push command for the active
   branch.
3. Optional PowerShell `scp` commands only for runtime files that can be
   safely copied individually.
4. Exact staging update commands, including the benchmark Compose overlay
   when relevant.

Do not include `.env`, `.env.staging`, data directories, backups, private
keys, generated runtime artefacts, or unrelated user files in Git commands.

## Architecture Map

- `lightrag/pipeline.py`: document ingestion, parsing dispatch, queue work.
- `lightrag/operate.py`: entity and relation extraction, merge, query context.
- `lightrag/prompt.py` and `prompts/entity_type/*.yml`: extraction profiles.
- `lightrag/relation_ontology.py`: current compact relation-label
  normalization and benchmark similarity rules.
- `lightrag/adaptive_retrieval.py`: deterministic DE/EN query router.
- `lightrag/directed_retrieval.py`: directed-edge selection and bounded paths.
- `lightrag/kg/neo4j_impl.py`: Neo4j storage and graph traversal.
- `lightrag/api/azure_batch.py`: Azure/OpenAI-compatible Batch lifecycle.
- `lightrag/evaluation/`: benchmarks, prompt experiments, scoring, run history.
- `lightrag_webui/src/features/`: Documents, graph, retrieval, evaluation UI.

The public query default remains normal retrieval. Directed, combined, and
auto retrieval are optional. Public directed traversal is bounded to 1-3 hops.
Physical Neo4j merge still groups unordered endpoint pairs, so parallel
assertions between the same two entities can be lost.

## Extraction And Batch State

- Documents are usually uploaded chunk-first. Deferred documents hold
  `skip_kg: true` and appear as Chunked in the UI until extraction begins.
- Extraction metadata includes directionality, relation type, importance,
  chain role, and semantic endpoints.
- Re-extraction retains source documents, chunks, and source URLs. Current
  extraction revisions are stored in document metadata.
- New Azure Batch jobs store a submission manifest with expected chunk IDs,
  request and chunk hashes, model, endpoint, output budget, prompt hash, and
  submitted extraction revision.
- Batch import rejects incomplete/refused outputs, invalid JSON contracts, and
  missing, duplicate, or foreign chunks before graph writes. It records
  validation failures on the job and document.
- P0 still needs normal-provider completion validation, targeted failed-chunk
  retry, and idempotent recovery after a merge failure.

## Evaluation And Prompt Experiments

- WebUI separates Benchmarks and Prompt Experiments.
- Prompt experiments run isolated candidate workspaces over retained chunks.
  Screening samples chunks, Validation uses all selected chunks without
  gleaning, and Final uses all selected chunks with active gleaning.
- Evaluation scoring version 2.0.0 keeps Metadata outside Overall. Metadata
  and reference coverage are diagnostics, not proof of scientific correctness.
- Current benchmark limitations: entity precision is incomplete, expected
  answer text and prohibited claims are not fully evaluated, and directed path
  diagnostics do not yet equal strategy-specific end-to-end answer quality.

## Ontology Material

- `ontology/merged/merged.ttl` is a CC BY 4.0 union graph of EMMO,
  domain-battery, domain-electrochemistry, CHAMEO, BTO, and BattINFO support.
- `ontology/relation_types.json` is a provisional relation schema with
  canonical labels and additional relation families, derived from a narrow
  pilot: one article, 6 paragraphs, 55 sentences, and 32 annotated relations.
  Treat it as candidate material, not established production truth.
- `ontology/type_mapping_emmo.json` maps broad free-text types to upper EMMO
  classes. `ontology/subproperties.json` records relation hierarchies and
  inverses.
- Integrate through a versioned mapping layer first: preserve existing labels
  such as `causes`, map them to ontology IRI/canonical predicate metadata, and
  compare against the current pipeline before migrating data or prompts.
- `ontology/sources/bto/` now contains 49 Turtle files; with two BattINFO
  source files this matches the merge report's 51 parsed filenames. The
  separate `sources/battinfo-repo/` is a large software checkout. Rebuilding
  the merge still needs a read-only reproducibility check before it is trusted.
- Ontology integration is planned in `docs/ONTOLOGY_INTEGRATION_PLAN.md`.
  `docs/PROJECT_TODO.md` is the canonical ordered implementation queue; its
  first open unblocked item is what "Implementiere den naechsten Schritt in
  der TODO" means.

## Verification

- Backend focused tests: `./scripts/test.sh <test path>` or
  `.\.venv\Scripts\python.exe -m pytest <test path> -q` on Windows.
- Frontend: `cd lightrag_webui`, `bun test`, `bun run lint`, and `bun run build`.
- Python lint: `.\.venv\Scripts\python.exe -m ruff check <paths>`.
- Always run `git diff --check` for edited paths.
- Mock external services in unit tests; do not require live Azure, Neo4j, or
  Ollama for local unit tests.

## Primary Documentation

- `docs/PEM-GRAPHRAG-ARCHITECTURE.md`: current end-to-end architecture.
- `docs/PIPELINE_CHANGE_GUIDE.md`: practical change locations.
- `docs/PIPELINE_RESEARCH_AND_IMPROVEMENT_PLAN_2026-10.md`: quality roadmap,
  research findings, priorities P0-P7, and known limitations.
- `docs/BENCHMARK_SCORING.md`: evaluation semantics.
- `docs/STAGING_TO_PRODUCTION.md`: promotion workflow.
- `docs/DIRECTED_MULTIHOP_STAGING_RUNBOOK.md`: directed retrieval staging runbook.

## Update Rule

Update this file whenever a completed task changes a deployment convention,
pipeline contract, storage model, active migration state, or known limitation.
Keep it concise; move detailed rationale and procedures into `docs/`.
