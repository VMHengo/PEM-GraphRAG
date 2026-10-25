# PEM GraphRAG Project Memory

Read only the relevant section. Code and live configuration outrank this file.
Keep secrets and private document content out of memory.

## Working Context

- Development is usually on `feature/azure-batch-extraction`; verify the
  active branch. Local shell is PowerShell; Python venv is `.venv`.
- VPS repo: `/root/PEM-GraphRAG`. Staging project `pem-staging` uses
  `.env.staging`; production project `mcp` uses `.env`. The staging Compose
  file is on the VPS, not in this checkout. Benchmark deployments also need
  `deploy/mcp/compose.evaluation-benchmarks.yml`.
- Git is the normal delivery path. SCP alone does not activate container code.

## Architecture Map

- Ingestion: `lightrag/pipeline.py`; extraction and query context:
  `lightrag/operate.py`; extraction profiles: `prompts/entity_type/*.yml`.
- Routing and paths: `lightrag/adaptive_retrieval.py` and
  `lightrag/directed_retrieval.py`; graph storage: `lightrag/kg/neo4j_impl.py`.
- Batch: `lightrag/api/azure_batch.py`; evaluation: `lightrag/evaluation/`.
- Directed/combined/auto retrieval is optional; public directed paths are
  bounded to 1-5 hops (default 2). Neo4j pair-based merge needs per-assertion
  handling for parallel claims.
- Exploratory MCP prototype: `explore_pem_connections` uses `/query/data` and
  provisional domain labels in `lightrag_mcp/exploration.py`; see
  `docs/EXPLORATORY_DISCOVERY_PLAN.md`. It is not expert-validated.

## Extraction And Batch State

- Chunk-first uploads use `skip_kg: true` until extraction. Re-extraction
  retains source documents, chunks and URLs; revisions live in document metadata.
- Azure Batch submission manifests bind chunks, hashes, model, prompt and
  extraction revision. Import validates complete outputs before graph writes.
- Still open: normal-provider completion validation, targeted retry and
  idempotent recovery after merge failure.

## Evaluation And Prompt Experiments

- Prompt experiments use isolated retained-chunk workspaces. Screening
  samples; Validation uses all chunks without gleaning; Final includes gleaning.
- Scoring v2 excludes Metadata from Overall. Entity precision and answer-level
  support remain limited; directed-path scores are not end-to-end answer quality.
- The product North Star now prioritizes evidence-visible, cross-subject-area
  discovery of *unreviewed* indirect battery-engineering connections.

## Ontology Material

- ONT-01B reconciled 51 SHA-256-pinned sources into the active 65,882-triple
  union. BattINFO 0.7.0 declares Apache-2.0; six other roots declare CC BY 4.0.
  The old 0.8.0-beta merge is archived under `ontology/history/`.
- BattINFO imports newer electrochemistry/chemical-substance versions than
  this union contains. Do not assume a compatible OWL import closure.
- `ontology/relation_types.json` is provisional pilot material, not gold.
  `ontology/pem_mapping_v1.json` and optional `ontology.resolver` are offline
  only; conditional matches do not assert a canonical IRI. Runtime extraction
  and retrieval do not load them. Preserve raw labels/direction/evidence.
  See `docs/ONTOLOGY_INTEGRATION_PLAN.md` and `docs/PROJECT_TODO.md`.

## Read On Demand

- Architecture/change locations: `docs/PEM-GRAPHRAG-ARCHITECTURE.md`,
  `docs/PIPELINE_CHANGE_GUIDE.md`.
- Evaluation: `docs/BENCHMARK_SCORING.md`.
- Deployment: `docs/STAGING_TO_PRODUCTION.md` and, for directed retrieval,
  `docs/DIRECTED_MULTIHOP_STAGING_RUNBOOK.md`.
- Long-term goals: `docs/PEM-GRAPHRAG-IMPROVEMENT-ROADMAP.md`.

## Update Rule

Update only for changed durable facts; put procedures and evidence in `docs/`.
