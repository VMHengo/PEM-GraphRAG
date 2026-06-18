# PEM GraphRAG Architecture And Pipeline

This document describes the current PEM GraphRAG fork at a practical level:
where documents enter the system, where chunking and entity/relation extraction
happen, where Neo4j is used, and how ChatGPT reaches the knowledge base through
the MCP connector.

The upstream project is LightRAG. The PEM-specific additions in this fork are:

- a PEM domain entity prompt profile,
- Neo4j graph storage for the knowledge graph,
- a read-only MCP gateway for ChatGPT,
- a two-stage ingestion flow: chunk first, confirm extraction later,
- WebUI changes for document upload, extraction estimates, and manual extraction.

## High-Level Stack

```text
Browser / WebUI
  -> LightRAG FastAPI server
     -> document status storage
     -> full document KV storage
     -> text chunk KV/vector storage
     -> entity/relation vector storage
     -> Neo4j graph storage
     -> LLM provider for extraction/querying

ChatGPT
  -> MCP connector
     -> lightrag_mcp service
        -> internal LightRAG /query and document endpoints
```

On the VPS deployment, the main compose file is:

```text
deploy/mcp/docker-compose.vps.yml
```

It wires together LightRAG, Neo4j, Ollama, the MCP gateway, and optional
oauth2-proxy/WebUI routing through Traefik.

## Important Directories

```text
lightrag/
  Core backend package.

lightrag/api/
  FastAPI server and REST routes.

lightrag/api/routers/document_routes.py
  Document upload, status, deletion, paginated document listing,
  two-stage extraction confirmation.

lightrag/pipeline.py
  Document ingestion pipeline: parse/analyze/chunk/extract/write status.

lightrag/operate.py
  Core entity/relation extraction and query logic.

lightrag/prompt.py
  Prompt templates and loading of custom entity prompt profiles.

lightrag/kg/
  Storage backends, including Neo4j.

lightrag/llm/
  LLM and embedding provider bindings.

lightrag_webui/
  React/Vite/Bun WebUI.

lightrag_webui/src/components/documents/UploadDocumentsDialog.tsx
  Upload UI and chunking/extraction estimate dialog.

lightrag_webui/src/features/DocumentManager.tsx
  Document table, status tabs, chunked document action button.

lightrag_mcp/
  MCP gateway used by ChatGPT.

deploy/mcp/
  VPS deployment files.

prompts/entity_type/
  Runtime prompt profiles. Usually gitignored.

prompts/samples/
  Versioned sample prompt profiles.
```

## Document Ingestion Pipeline

The user-facing path starts in the WebUI:

```text
lightrag_webui/src/components/documents/UploadDocumentsDialog.tsx
```

The upload API call is defined in:

```text
lightrag_webui/src/api/lightrag.ts
```

The backend route is:

```text
POST /documents/upload
lightrag/api/routers/document_routes.py
```

In this fork, WebUI uploads use:

```text
defer_extraction=true
```

That means the document is accepted, parsed, and chunked first. Entity/relation
extraction is skipped until the user explicitly starts it.

## Two-Stage Ingestion

Current intended flow:

```text
1. Upload document
2. LightRAG parses/chunks document
3. Document appears as "Chunked" in the Processing tab
4. User clicks Extract
5. WebUI shows estimated chunks/time/cost
6. User confirms
7. Entity/relation extraction runs
8. Graph/vector stores are updated
9. Document becomes Completed
```

The mechanism uses LightRAG's existing process option:

```text
!
```

Internally this sets `skip_kg`, so the pipeline skips knowledge-graph extraction
after chunking. The metadata marker is:

```text
metadata.skip_kg = true
```

Relevant backend code:

```text
lightrag/api/routers/document_routes.py
  pipeline_enqueue_file(..., defer_extraction=True)
  POST /documents/{doc_id}/confirm_extraction

lightrag/pipeline.py
  checks doc_process_opts.skip_kg
  writes metadata.skip_kg
```

Relevant frontend code:

```text
lightrag_webui/src/components/documents/UploadDocumentsDialog.tsx
  uploads with defer_extraction
  polls track status until chunking finishes
  shows extraction estimate

lightrag_webui/src/features/DocumentManager.tsx
  treats metadata.skip_kg documents as Processing/Chunked
  shows Extract button
```

## Parsing And Chunking

Parsing/chunking is coordinated by:

```text
lightrag/pipeline.py
```

The parser routing logic is in:

```text
lightrag/parser/routing.py
```

Chunking implementations live in:

```text
lightrag/chunker/
```

The document status metadata currently records values such as:

```text
parse_format
parse_engine
chunking_method
chunk_opts
chunks_count
content_length
```

For fixed-token chunking, the visible status often includes something like:

```text
chunk_opts: size=1200, split_only=False, overlap=100
chunking_method: fixed_token
```

## Entity And Relation Extraction

Entity/relation extraction is mainly in:

```text
lightrag/operate.py
```

The pipeline calls into extraction from:

```text
lightrag/pipeline.py
lightrag/lightrag.py
```

Prompt preparation is handled by:

```text
lightrag/prompt.py
```

Role-specific LLM configuration is handled by:

```text
lightrag/llm_roles.py
```

The extraction role can be configured independently from query answering:

```env
EXTRACT_LLM_BINDING=openai
EXTRACT_LLM_BINDING_HOST=https://...
EXTRACT_LLM_MODEL=gpt-4.1-mini
EXTRACT_LLM_BINDING_API_KEY=...
EXTRACT_LLM_TIMEOUT=900
EXTRACT_MAX_ASYNC_LLM=1
```

For a local model server:

```env
EXTRACT_LLM_BINDING=ollama
EXTRACT_LLM_BINDING_HOST=http://llm-vm:11434
EXTRACT_LLM_MODEL=qwen3:14b
EXTRACT_LLM_TIMEOUT=7200
EXTRACT_MAX_ASYNC_LLM=1
MAX_ASYNC=1
```

## PEM Entity Prompt Profile

The PEM-specific entity extraction prompt lives at runtime in:

```text
prompts/entity_type/pem_graphrag_entity_type_prompt.yml
```

The versioned sample copy is:

```text
prompts/samples/pem_graphrag_entity_type_prompt.sample.yml
```

For Docker/VPS deployment, the compose stack maps data prompts from:

```text
data/prompts/entity_type/pem_graphrag_entity_type_prompt.yml
```

The active env variable is:

```env
ENTITY_TYPE_PROMPT_FILE=pem_graphrag_entity_type_prompt.yml
ENTITY_EXTRACTION_USE_JSON=true
```

The prompt profile defines broad PEM-relevant types such as:

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

## Neo4j Graph Storage

Neo4j is configured as LightRAG's graph storage:

```env
LIGHTRAG_GRAPH_STORAGE=Neo4JStorage
NEO4J_URI=neo4j://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j
```

The storage implementation is:

```text
lightrag/kg/neo4j_impl.py
```

Only the graph structure is stored in Neo4j. LightRAG still also uses KV/vector
storages for document content, chunks, entity embeddings, relation embeddings,
and status tracking.

## Query Pipeline

The query API is exposed by the LightRAG FastAPI server. The MCP gateway calls
the internal LightRAG query endpoint.

Common query modes:

```text
naive   direct vector search over chunks
local   entity-focused graph retrieval
global  broader graph/community retrieval
hybrid  local + global
mix     graph + vector retrieval
```

For debugging retrieval in the WebUI, use the Retrieval tab. For ChatGPT, use
the MCP connector.

## ChatGPT MCP Connector

The MCP service is in:

```text
lightrag_mcp/
```

Main server:

```text
lightrag_mcp/server.py
```

Client wrapper around LightRAG:

```text
lightrag_mcp/lightrag_client.py
```

Current MCP tools:

```text
query_pem_graphrag(question, mode="mix")
search_pem_documents(query, limit=10)
fetch_pem_document_context(document_id, question, mode="naive")
```

The MCP endpoint is intended to be public only through HTTPS and OAuth:

```text
https://mcp.<domain>/mcp/
```

The LightRAG WebUI is an admin/developer ingestion interface, not the ChatGPT
facing API.

## WebUI Authentication And Deployment

The WebUI can be exposed through Traefik and protected by oauth2-proxy/Auth0.
The domain is controlled by environment variables in the VPS `.env`, for
example:

```env
MCP_DOMAIN=mcp.example.edu
LIGHTRAG_WEBUI_DOMAIN=lightrag.example.edu
TRAEFIK_NETWORK=n8n-compose_default
TRAEFIK_ENTRYPOINT=websecure
TRAEFIK_CERTRESOLVER=mytlschallenge
```

Branding is controlled in:

```text
lightrag_webui/index.html                 browser tab title and favicon
lightrag_webui/favicon.png                browser tab icon
lightrag_webui/src/lib/constants.ts       SiteInfo.name in the header
lightrag_webui/src/features/SiteHeader.tsx header icon/layout
lightrag_webui/src/index.css              theme variables
```

## Where To Change What

| Task | Main Files |
| --- | --- |
| Change upload behavior | `lightrag/api/routers/document_routes.py`, `UploadDocumentsDialog.tsx` |
| Change two-stage extraction | `document_routes.py`, `pipeline.py`, `DocumentManager.tsx` |
| Change entity types/prompt | `prompts/entity_type/*.yml`, `lightrag/prompt.py` |
| Change extraction LLM | `.env`, `deploy/mcp/docker-compose.vps.yml`, `lightrag/llm_roles.py` if deeper behavior is needed |
| Change retrieval/query behavior | `lightrag/operate.py`, query routes, MCP client |
| Change ChatGPT tools | `lightrag_mcp/server.py`, `lightrag_mcp/lightrag_client.py` |
| Change Neo4j behavior | `lightrag/kg/neo4j_impl.py` |
| Change WebUI document table | `lightrag_webui/src/features/DocumentManager.tsx` |
| Change WebUI theme/branding | `lightrag_webui/src/index.css`, `constants.ts`, `SiteHeader.tsx`, `index.html` |

## Batch API Status

Azure/OpenAI Batch API is not currently wired into the LightRAG extraction
pipeline. The current extraction path expects synchronous LLM calls during
pipeline processing.

A future Batch API integration would likely add a third extraction path:

```text
Chunked document
  -> create JSONL batch file
  -> upload batch file to Azure
  -> store batch id in document metadata
  -> poll/sync completed batch
  -> import entity/relation extraction results
  -> write graph/vector stores
```

This is feasible, but it is more than a `.env` change because Batch results
return later and must be merged back into LightRAG's extraction pipeline.

## Useful Commands

Build/recreate the VPS LightRAG service after code changes:

```bash
cd ~/PEM-GraphRAG
docker compose --env-file .env -f deploy/mcp/docker-compose.vps.yml up -d --build --force-recreate lightrag
```

Check services:

```bash
docker compose --env-file .env -f deploy/mcp/docker-compose.vps.yml ps
```

Check LightRAG logs:

```bash
docker compose --env-file .env -f deploy/mcp/docker-compose.vps.yml logs --tail=120 lightrag
```

Check MCP health:

```bash
curl -i https://mcp.<domain>/healthz
```

Build the WebUI locally:

```bash
cd lightrag_webui
bun install
bun run build
```

## Mental Model

The most important distinction in this fork is:

```text
Chunking is cheap and structural.
Extraction is expensive and LLM-driven.
```

The current WebUI intentionally lets users upload and chunk first, then decide
whether to spend LLM time/cost on extraction. That makes large PDFs safer to
handle and prepares the system for future local-LLM or Batch-API extraction.
