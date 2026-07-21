# PEM GraphRAG Architecture And Pipeline

This document explains the current PEM GraphRAG pipeline from document upload
to retrieval through ChatGPT. It is meant as a practical map for future changes:
each stage lists what happens, the relevant code paths, the technologies in use,
and the usual place to modify behavior.

Important distinction: the MCP server is currently read-only for ChatGPT. It
does not ingest documents. Documents are ingested through the LightRAG WebUI or
LightRAG REST API. ChatGPT reaches the already-ingested knowledge base through
the MCP connector.

## Current Stack

| Layer | Current Technology | Main Configuration |
| --- | --- | --- |
| Web UI | React 19, TypeScript, Vite, Bun, Tailwind | `lightrag_webui/` |
| Backend API | FastAPI inside LightRAG | `lightrag/api/lightrag_server.py` |
| Ingestion pipeline | LightRAG pipeline mixin | `lightrag/pipeline.py` |
| Graph database | Neo4j 5 Community | `LIGHTRAG_GRAPH_STORAGE=Neo4JStorage` |
| Graph storage implementation | Neo4j driver backend | `lightrag/kg/neo4j_impl.py` |
| Vector storage | NanoVectorDB by default | `LIGHTRAG_VECTOR_STORAGE=NanoVectorDBStorage` |
| KV/doc status storage | LightRAG configured storage, file-backed by default | `lightrag/kg/json_kv_impl.py`, `lightrag/kg/json_doc_status_impl.py` |
| Local embeddings | Ollama + `nomic-embed-text` | `EMBEDDING_BINDING=ollama`, `EMBEDDING_MODEL=nomic-embed-text`, `EMBEDDING_DIM=768` |
| Extraction LLM | Configurable; often Azure/OpenAI-compatible for extraction | `EXTRACT_LLM_*` |
| Optional batch extraction | Azure/OpenAI-compatible Batch API, experimental | `AZURE_BATCH_*`, `lightrag/api/azure_batch.py` |
| ChatGPT connector | MCP Streamable HTTP server | `lightrag_mcp/` |
| Auth | Auth0 for MCP and oauth2-proxy for WebUI | `.env`, `.env.staging`, `deploy/mcp/` |
| Deployment | Docker Compose on VPS | `deploy/mcp/docker-compose.vps.yml`, `deploy/mcp/docker-compose.staging.yml` on VPS |

## Data Flow Overview

```text
Developer / Admin Browser
  -> LightRAG WebUI
  -> POST /documents/upload
  -> Save file under INPUT_DIR
  -> Enqueue document status
  -> Parse document
  -> Chunk document
  -> Embed chunks into vector storage
  -> Mark document as Chunked if extraction is deferred
  -> User chooses:
       A. normal extraction
       B. Azure Batch extraction
  -> Extract entities and relations
  -> Merge entities/relations
  -> Write graph to Neo4j
  -> Write entity/relation vectors
  -> Mark document as processed

ChatGPT
  -> MCP connector
  -> lightrag_mcp service
  -> LightRAG /query or document endpoints
  -> vector search and/or graph retrieval
  -> grounded answer with references/citations
```

## Deployment Files

| Purpose | Path |
| --- | --- |
| Production/VPS compose template | `deploy/mcp/docker-compose.vps.yml` |
| Staging compose on VPS | `deploy/mcp/docker-compose.staging.yml` |
| Example env without secrets | `deploy/mcp/env.example` |
| Caddy config, if Caddy is used | `deploy/mcp/Caddyfile` |
| MCP gateway Dockerfile | `Dockerfile.mcp` |
| Main LightRAG Dockerfile | `Dockerfile` |

The local repository does not store real `.env` files. Real secrets live only on
the VPS in `.env` / `.env.staging`.

## 1. Document Upload

### What Happens

The WebUI uploads a file to the LightRAG API. In this fork, WebUI uploads are
usually chunk-first: the document is parsed and chunked, but knowledge graph
extraction is deferred until the user confirms.

### Frontend Code

| Concern | Path |
| --- | --- |
| Upload dialog | `lightrag_webui/src/components/documents/UploadDocumentsDialog.tsx` |
| API wrapper | `lightrag_webui/src/api/lightrag.ts` |
| Document table and extract buttons | `lightrag_webui/src/features/DocumentManager.tsx` |

The relevant frontend API call is:

```text
uploadDocument(file, ..., { deferExtraction: true })
```

### Backend Code

| Concern | Path |
| --- | --- |
| Upload endpoint | `lightrag/api/routers/document_routes.py` |
| Upload route | `POST /documents/upload` |
| File save and enqueue | `upload_to_input_dir`, `pipeline_enqueue_file` in `document_routes.py` |
| Pipeline reservation/concurrency | `_reserve_enqueue_slot`, `_release_enqueue_slot` in `document_routes.py` |

### Current Storage Impact

The uploaded file is saved under the configured input directory:

```env
INPUT_DIR=/app/data/inputs
```

On the VPS this maps to:

```text
data/inputs/              production
data-staging/inputs/      staging
```

The document also receives a `track_id`, for example:

```text
upload_20260625_101533_b720f20a
```

## 2. Document Status And Pipeline Queue

### What Happens

LightRAG records document state in doc status storage and runs the ingestion
pipeline asynchronously. The WebUI polls status endpoints to show progress.

Typical statuses:

```text
pending
parsing
analyzing
processing
processed
failed
```

In the PEM fork, a document that has only been chunked is technically
`processed` internally, but it carries:

```json
{"skip_kg": true}
```

The WebUI displays this as `Chunked` and groups it under Processing so users can
manually start extraction.

### Relevant Code

| Concern | Path |
| --- | --- |
| Status model | `lightrag/base.py` (`DocStatus`, `DocProcessingStatus`) |
| Pipeline status endpoint | `GET /documents/pipeline_status` in `document_routes.py` |
| Track status endpoint | `GET /documents/track_status/{track_id}` in `document_routes.py` |
| Paginated document listing | `POST /documents/paginated` in `document_routes.py` |
| Chunked status adjustment | `_adjust_status_counts_for_deferred_extraction` in `document_routes.py` |
| WebUI status grouping | `lightrag_webui/src/features/documentStatusFilters.ts` |
| WebUI document table | `lightrag_webui/src/features/DocumentManager.tsx` |

## 3. Parsing

### What Happens

Parsing extracts text and optionally structured artifacts from files. The exact
parser depends on file type and parser hints.

LightRAG supports:

```text
legacy
native
mineru
docling
```

The current WebUI uploads commonly use the legacy/raw path unless a parser hint
or configuration selects another parser.

### Relevant Code

| Concern | Path |
| --- | --- |
| Pipeline orchestration | `lightrag/pipeline.py` |
| Parser routing | `lightrag/parser/routing.py` |
| Native parser package | `lightrag/parser/` |
| DOCX native parser | `lightrag/parser/docx/` |
| External parser adapters | `lightrag/parser/external/` |
| Parser constants | `lightrag/constants.py` |

### Metadata Written

Document metadata may include:

```text
parse_format
parse_engine
parsing_start_time
parse_stage_skipped
analyzing_start_time
analyzing_stage_skipped
```

## 4. Chunking

### What Happens

After parsing, the document text is split into chunks. Chunks are the unit used
for vector search and entity/relation extraction.

In the current PEM WebUI flow, chunking happens before expensive extraction.
This allows cost/time estimation before the LLM is used for graph extraction.

### Current Default

The common current default is fixed-token chunking:

```text
process_options: F
chunking_method: fixed_token
chunk_opts: size=1200, split_only=False, overlap=100
```

If extraction is deferred, the process option includes:

```text
!
```

Example:

```text
process_options: F!
skip_kg: true
```

### Chunking Strategies

| Code | Strategy | Implementation |
| --- | --- | --- |
| `F` | Fixed token | `lightrag/chunker/token_size.py` |
| `R` | Recursive character | `lightrag/chunker/recursive_character.py` |
| `V` | Semantic vector chunking | `lightrag/chunker/semantic_vector.py` |
| `P` | Paragraph semantic | `lightrag/chunker/paragraph_semantic.py` |

Dispatcher and pipeline code:

```text
lightrag/pipeline.py
lightrag/chunker/__init__.py
lightrag/constants.py
```

### Where To Tune

To change chunk size, overlap, or strategy, start with:

```text
lightrag/api/routers/document_routes.py
lightrag/pipeline.py
lightrag/chunker/
```

For UI behavior around chunking estimates:

```text
lightrag_webui/src/components/documents/UploadDocumentsDialog.tsx
lightrag_webui/src/features/DocumentManager.tsx
```

## 5. Chunk Embedding

### What Happens

Chunks are embedded into vector storage so they can be retrieved by semantic
similarity. With NanoVectorDB/Faiss/OpenSearch/Postgres-style vector backends,
the vector store calls the configured embedding function.

### Current Technology

The staging/production setup has been using local Ollama embeddings:

```env
EMBEDDING_BINDING=ollama
EMBEDDING_BINDING_HOST=http://ollama:11434
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIM=768
EMBEDDING_TOKEN_LIMIT=8192
EMBEDDING_TIMEOUT=300
```

### Relevant Code

| Concern | Path |
| --- | --- |
| Embedding binding config | `lightrag/api/config.py` |
| Embedding function creation | `lightrag/api/lightrag_server.py` (`create_optimized_embedding_function`) |
| Ollama embedding provider | `lightrag/llm/ollama.py` (`ollama_embed`) |
| OpenAI/Azure embedding provider | `lightrag/llm/openai.py` (`openai_embed`, `azure_openai_embed`) |
| Embedding wrapper | `lightrag/utils.py` (`EmbeddingFunc`, `wrap_embedding_func_with_attrs`) |
| Vector storage base contract | `lightrag/base.py` (`BaseVectorStorage`) |
| NanoVectorDB storage | `lightrag/kg/nano_vector_db_impl.py` |

### Vector Stores Created By LightRAG

The main `LightRAG` object creates three vector stores:

```text
chunks_vdb          chunk embeddings
entities_vdb        entity embeddings
relationships_vdb   relationship embeddings
```

Relevant code:

```text
lightrag/lightrag.py
```

### Stored Files With NanoVectorDB

For file-backed NanoVectorDB:

```text
data/rag_storage/vdb_chunks.json
data/rag_storage/vdb_entities.json
data/rag_storage/vdb_relationships.json
```

For staging:

```text
data-staging/rag_storage/vdb_chunks.json
data-staging/rag_storage/vdb_entities.json
data-staging/rag_storage/vdb_relationships.json
```

### Important Warning

Changing embedding model or dimension requires rebuilding vector data. For
example, switching from `nomic-embed-text` at 768 dimensions to
`text-embedding-3-small` at 1536 dimensions makes old vectors incompatible.

## 6. Chunk-Only Completion

### What Happens

When `defer_extraction=true`, LightRAG stops after chunking and chunk
embedding. It does not yet extract entities or relations.

The document metadata contains:

```json
{
  "skip_kg": true
}
```

The WebUI displays this as:

```text
Chunked
```

The user can then choose one of two extraction modes:

```text
Start normal extraction
Start Azure Batch
```

### Relevant Code

| Concern | Path |
| --- | --- |
| Deferred upload flag | `lightrag/api/routers/document_routes.py` |
| Pipeline skip logic | `lightrag/pipeline.py` (`doc_process_opts.skip_kg`) |
| Confirm normal extraction | `POST /documents/{doc_id}/confirm_extraction` in `document_routes.py` |
| Batch extraction endpoints | `POST/GET /documents/{doc_id}/batch_extraction/*` in `document_routes.py` |
| WebUI buttons | `lightrag_webui/src/features/DocumentManager.tsx` |

## 7. Normal Entity And Relation Extraction

### What Happens

Normal extraction is synchronous from LightRAG's perspective. For each chunk,
LightRAG prepares an extraction prompt, calls the configured extraction LLM,
parses the returned entities/relations, and merges them into the graph.

### Relevant Code

| Concern | Path |
| --- | --- |
| Extraction entrypoint | `lightrag/operate.py` (`extract_entities`) |
| Per-chunk extraction prompt | `lightrag/operate.py` inside `extract_entities` |
| JSON extraction parser | `lightrag/operate.py` (`_process_json_extraction_result`) |
| Delimiter extraction parser | `lightrag/operate.py` (`_process_extraction_result`) |
| Pipeline call into extraction | `lightrag/lightrag.py` (`_process_extract_entities`) |
| Pipeline orchestration | `lightrag/pipeline.py` (`process_single_document`) |
| Merge into graph/vector stores | `lightrag/operate.py` (`merge_nodes_and_edges`) |

### Prompt Preparation

Prompt templates are loaded from:

```text
lightrag/prompt.py
```

The PEM-specific prompt profile is:

```text
prompts/entity_type/pem_graphrag_entity_type_prompt.yml
prompts/samples/pem_graphrag_entity_type_prompt.sample.yml
data/prompts/entity_type/pem_graphrag_entity_type_prompt.yml
```

The active configuration is:

```env
ENTITY_TYPE_PROMPT_FILE=pem_graphrag_entity_type_prompt.yml
ENTITY_EXTRACTION_USE_JSON=true
```

The PEM profile uses broad entity types:

```text
ResearchField
Concept
Method
Process
Artifact
Material
Organization
Content
Data
Other
```

### Current Extraction LLM Configuration

Extraction can be configured separately from normal query answering:

```env
EXTRACT_LLM_BINDING=openai
EXTRACT_LLM_BINDING_HOST=https://.../openai/v1
EXTRACT_LLM_MODEL=...
EXTRACT_LLM_BINDING_API_KEY=...
EXTRACT_LLM_TIMEOUT=900
EXTRACT_MAX_ASYNC_LLM=1
MAX_ASYNC=1
```

For local LLM extraction:

```env
EXTRACT_LLM_BINDING=ollama
EXTRACT_LLM_BINDING_HOST=http://ollama:11434
EXTRACT_LLM_MODEL=qwen3:14b
EXTRACT_LLM_TIMEOUT=7200
EXTRACT_MAX_ASYNC_LLM=1
MAX_ASYNC=1
```

### Where To Tune Extraction

| Goal | Main Files |
| --- | --- |
| Change entity types | `prompts/entity_type/*.yml` |
| Change extraction prompt logic | `lightrag/prompt.py`, `lightrag/operate.py` |
| Change extraction model/provider | `.env`, compose env, `lightrag/api/lightrag_server.py` |
| Change parsing of LLM output | `lightrag/operate.py` |
| Change graph merge behavior | `lightrag/operate.py`, `lightrag/utils_graph.py` |

## 8. Azure Batch Entity Extraction

### What Happens

Azure Batch extraction is an alternative to normal extraction. It is intended
for cheaper asynchronous processing of already-chunked documents.

Flow:

```text
Chunked document
  -> Start Azure Batch
  -> Build JSONL file, one request per chunk
  -> Upload JSONL to Azure Files API
  -> Create Azure Batch job
  -> Store batch id in document metadata
  -> Refresh batch status until completed
  -> Import result JSONL
  -> Parse entity/relation outputs
  -> Merge into graph/vector stores
```

### Relevant Code

| Concern | Path |
| --- | --- |
| Batch client and JSONL creation | `lightrag/api/azure_batch.py` |
| Batch REST routes | `lightrag/api/routers/document_routes.py` |
| WebUI batch buttons | `lightrag_webui/src/features/DocumentManager.tsx` |
| Frontend API calls | `lightrag_webui/src/api/lightrag.ts` |

### Batch Endpoints

```text
POST /documents/{doc_id}/batch_extraction/start
GET  /documents/{doc_id}/batch_extraction/status
POST /documents/{doc_id}/batch_extraction/import
```

### Current Batch Env

```env
AZURE_BATCH_ENABLED=true
AZURE_BATCH_BINDING_HOST=https://.../openai/v1
AZURE_BATCH_API_KEY=...
AZURE_BATCH_MODEL=...
AZURE_BATCH_ENDPOINT=/responses
AZURE_BATCH_COMPLETION_WINDOW=24h
AZURE_BATCH_POLL_SECONDS=60
AZURE_BATCH_HTTP_TIMEOUT=120
```

`AZURE_BATCH_MODEL` should be the Azure deployment name if Azure requires a
deployment name rather than a raw model name.

The code supports:

```text
AZURE_BATCH_ENDPOINT=/chat/completions
AZURE_BATCH_ENDPOINT=/responses
```

## 9. Graph Merge And Neo4j Storage

### What Happens

After entity/relation extraction, LightRAG merges duplicate entities and
relationships, creates or updates graph nodes/edges, and writes related vectors.

Neo4j stores the knowledge graph structure. It does not store all document
chunks or all embeddings in the default setup.

### Current Neo4j Configuration

```env
LIGHTRAG_GRAPH_STORAGE=Neo4JStorage
NEO4J_URI=neo4j://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j
```

### Relevant Code

| Concern | Path |
| --- | --- |
| Graph merge | `lightrag/operate.py` (`merge_nodes_and_edges`) |
| Graph utilities | `lightrag/utils_graph.py` |
| Neo4j backend | `lightrag/kg/neo4j_impl.py` |
| Graph storage base class | `lightrag/base.py` (`BaseGraphStorage`) |
| LightRAG graph object creation | `lightrag/lightrag.py` |

### How To Inspect Neo4j

On the VPS:

```bash
PASS=$(grep '^NEO4J_PASSWORD=' .env.staging | cut -d= -f2-)

docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  exec -T neo4j cypher-shell -u neo4j -p "$PASS" \
  "MATCH (n) RETURN labels(n), count(n) ORDER BY count(n) DESC;"
```

## 10. Community Detection And Global Retrieval

### What Happens

LightRAG supports retrieval modes that use broader graph/community-style
context. The exact community support depends on the storage backend and graph
features available in the current LightRAG version/configuration.

For this project, the practical query modes are:

```text
naive   vector search over chunks
local   entity-focused graph retrieval
global  broad graph/community retrieval
hybrid  local + global
mix     graph + vector retrieval
```

### Relevant Code

| Concern | Path |
| --- | --- |
| Query orchestration | `lightrag/operate.py` |
| Query route | `lightrag/api/routers/query_routes.py` |
| Query mode param | `lightrag/base.py` (`QueryParam`) |
| Graph storage support | `lightrag/kg/` |

### Where To Tune

For retrieval quality, first inspect:

```text
lightrag/operate.py
```

Search terms:

```bash
rg -n "local|global|hybrid|mix|naive|top_k|chunk_top_k|community" lightrag/operate.py
```

## 11. Query And Retrieval

### What Happens

When a user asks a question, LightRAG retrieves relevant chunks and graph
context, builds a prompt, calls the query LLM, and returns an answer plus
references.

The MCP connector calls LightRAG internally. It does not directly access Neo4j.

### Relevant Code

| Concern | Path |
| --- | --- |
| Query route | `lightrag/api/routers/query_routes.py` |
| Query operation | `lightrag/operate.py` |
| Query params | `lightrag/base.py` (`QueryParam`) |
| MCP tool definitions | `lightrag_mcp/server.py` |
| MCP LightRAG client | `lightrag_mcp/lightrag_client.py` |

### MCP Tools

Current tools:

```text
query_pem_graphrag(question, mode="mix")
search_pem_documents(query, limit=10)
fetch_pem_document_context(document_id, query=None, max_chunks=5)
```

### MCP References And Citations

MCP maps LightRAG references into:

```text
answer
references
citations
mode
retrieval
```

Citation mapping lives in:

```text
lightrag_mcp/lightrag_client.py
```

The future hook for stable source URLs is:

```text
_citation_url(...)
```

## 12. Authentication And Public Access

### MCP

The public ChatGPT-facing endpoint should be protected with OAuth/JWT:

```text
https://mcp.<domain>/mcp/
```

Relevant code:

```text
lightrag_mcp/auth.py
lightrag_mcp/config.py
lightrag_mcp/server.py
```

Relevant env:

```env
MCP_AUTH_REQUIRED=true
AUTH0_DOMAIN=...
AUTH0_AUDIENCE=...
AUTH0_ALGORITHMS=RS256
```

### WebUI

The WebUI is a developer/admin ingestion interface. It can be exposed through
Traefik and protected by oauth2-proxy/Auth0.

Relevant deployment variables:

```env
LIGHTRAG_WEBUI_DOMAIN=lightrag.example.edu
OAUTH2_PROXY_CLIENT_ID=...
OAUTH2_PROXY_CLIENT_SECRET=...
OAUTH2_PROXY_COOKIE_SECRET=...
OAUTH2_PROXY_ISSUER_URL=https://...
```

## 13. Where To Change Common Things

| Goal | Main Files |
| --- | --- |
| Change upload behavior | `lightrag/api/routers/document_routes.py`, `UploadDocumentsDialog.tsx` |
| Change chunk-first flow | `document_routes.py`, `pipeline.py`, `DocumentManager.tsx` |
| Change chunking size/strategy | `lightrag/chunker/`, `lightrag/pipeline.py`, `document_routes.py` |
| Change embedding model | `.env`, compose env, `lightrag/api/lightrag_server.py`, `lightrag/llm/*` |
| Change vector storage | `.env`, `lightrag/kg/`, `lightrag/kg/factory.py` |
| Change extraction model | `.env`, compose env, `lightrag/api/lightrag_server.py` |
| Change entity types/prompt | `prompts/entity_type/*.yml`, `lightrag/prompt.py` |
| Change extraction parsing | `lightrag/operate.py` |
| Change Azure Batch behavior | `lightrag/api/azure_batch.py`, `DocumentManager.tsx` |
| Change Neo4j behavior | `lightrag/kg/neo4j_impl.py` |
| Change retrieval behavior | `lightrag/operate.py`, `query_routes.py` |
| Change MCP tools | `lightrag_mcp/server.py`, `lightrag_mcp/lightrag_client.py` |
| Change MCP auth | `lightrag_mcp/auth.py`, `lightrag_mcp/config.py` |
| Change WebUI theme/branding | `lightrag_webui/src/index.css`, `lightrag_webui/src/lib/constants.ts`, `lightrag_webui/src/features/SiteHeader.tsx`, `lightrag_webui/index.html` |

## 14. Useful Debug Commands

### Check Active Embedding Config

```bash
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  exec -T lightrag sh -lc 'printenv EMBEDDING_BINDING; printenv EMBEDDING_MODEL; printenv EMBEDDING_DIM'
```

### Check Active Extraction Config

```bash
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  exec -T lightrag sh -lc 'printenv EXTRACT_LLM_BINDING; printenv EXTRACT_LLM_BINDING_HOST; printenv EXTRACT_LLM_MODEL'
```

### List Documents

```bash
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  exec -T mcp-gateway python - <<'PY'
import os, httpx

headers = {"X-API-Key": os.environ["LIGHTRAG_API_KEY"]}
r = httpx.post(
    "http://lightrag:9621/documents/paginated",
    headers=headers,
    json={"page": 1, "page_size": 50, "status_filter": None, "status_filters": None},
    timeout=30,
)
print(r.status_code)
for d in r.json().get("documents", []):
    print(d.get("id"), d.get("status"), d.get("chunks_count"), d.get("file_path"), (d.get("metadata") or {}).get("skip_kg"))
PY
```

### Check Batch Env

```bash
docker compose \
  --project-name pem-staging \
  --env-file .env.staging \
  -f deploy/mcp/docker-compose.staging.yml \
  exec -T lightrag sh -lc 'printenv AZURE_BATCH_BINDING_HOST; printenv AZURE_BATCH_ENDPOINT; printenv AZURE_BATCH_MODEL'
```

### Check MCP Health

```bash
curl -i https://mcp.<domain>/healthz
```

## 15. Mental Model

The PEM fork separates cheap structural work from expensive LLM work:

```text
Parsing + chunking + chunk embeddings are the preparation layer.
Entity/relation extraction is the expensive graph-building layer.
Retrieval combines vector search and graph search.
MCP exposes only safe read/query tools to ChatGPT.
```

When future developers want to improve quality, the best order is usually:

1. Improve parsing quality.
2. Improve chunking strategy.
3. Improve embedding model or retrieval parameters.
4. Improve entity prompt and extraction model.
5. Improve graph merge/retrieval logic.

