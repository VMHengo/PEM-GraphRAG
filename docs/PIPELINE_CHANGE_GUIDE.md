# PEM GraphRAG: Change Guide

This is a practical map of the files that change PEM GraphRAG behaviour. It
is intentionally organised by the pipeline stage rather than by source tree.
Use staging first for every change that affects extraction, embeddings, graph
storage, or access control.

## Before Changing Anything

1. Keep secrets in `.env` or `.env.staging`; never place them in source code
   or a committed example file.
2. Make the change locally, run the focused tests, and deploy it to staging.
3. Ingest a small representative document and compare the result with the
   evaluation benchmark before production deployment.
4. Treat changes to embeddings, chunking, ontology, or extraction prompts as
   data-model changes. Existing data will not automatically become consistent
   with the new behaviour.

## Fast Behaviour Controls

| Goal | Primary file or setting | What to change | Re-index required? |
| --- | --- | --- | --- |
| Change the PEM entity types and extraction examples | [`prompts/entity_type/pem_graphrag_entity_type_prompt.yml`](../prompts/entity_type/pem_graphrag_entity_type_prompt.yml) | Entity taxonomy, relationship instructions, directionality examples, domain terminology | New or re-extracted documents |
| Choose the active prompt profile | `ENTITY_TYPE_PROMPT_FILE` in [`.env` via `deploy/mcp/env.example`](../deploy/mcp/env.example) | Select a YAML prompt profile by file name | Restart; re-extract for effect on old documents |
| Change query defaults | [`lightrag/base.py`](../lightrag/base.py) | `QueryParam`: retrieval mode, top-k, token budgets, reranking, directed-retrieval defaults | No |
| Expose or constrain query settings over REST | [`lightrag/api/routers/query_routes.py`](../lightrag/api/routers/query_routes.py) | `QueryRequest` fields, API validation, allowed ranges | No |
| Tune retrieval without code | [`.env` via `env.example`](../env.example) | `TOP_K`, `CHUNK_TOP_K`, token budgets, reranker settings | No |
| Change automatic multi-hop query classification | [`lightrag/adaptive_retrieval.py`](../lightrag/adaptive_retrieval.py) | Query patterns, priority, direction, relation-type families | No |
| Change final answer wording or context instructions | [`lightrag/prompt.py`](../lightrag/prompt.py) | `rag_response`, keyword extraction, standard entity extraction templates | No, but test carefully |
| Change extraction model/provider/cost behaviour | [`.env` via `deploy/mcp/env.example`](../deploy/mcp/env.example) | `EXTRACT_LLM_*`, concurrency, timeouts, Azure Batch settings | No for queries; re-extract to improve existing graph |
| Change embedding model/provider | [`.env` via `deploy/mcp/env.example`](../deploy/mcp/env.example) | `EMBEDDING_*`, model, dimension, token limit | **Yes: full re-index** |
| Change chunk size or strategy | [`.env` via `env.example`](../env.example), [`lightrag/lightrag.py`](../lightrag/lightrag.py) | `CHUNK_SIZE`, overlap, F/R/P/V chunker-specific settings | **Yes: re-chunk and re-extract** |
| Tune relation filtering | [`lightrag/operate.py`](../lightrag/operate.py) | `RELATION_IMPORTANCE_THRESHOLD`, metadata parsing, relation merge behaviour | Re-extract documents affected |

## Prompt And Ontology

### PEM prompt profile: the first place to change domain behaviour

Edit [`prompts/entity_type/pem_graphrag_entity_type_prompt.yml`](../prompts/entity_type/pem_graphrag_entity_type_prompt.yml) when changing:

- the allowed entity types, such as `Process`, `Material`, `Artifact`, or
  `Measurement`;
- canonical terminology, aliases, and abbreviations used at PEM;
- meaningful relation types such as `causes`, `produces`, `uses`,
  `influences`, or `published_by`;
- directionality, `relation_importance`, and `chain_role` instructions;
- positive and negative extraction examples.

For a new profile, copy the sample at
[`prompts/samples/pem_graphrag_entity_type_prompt.sample.yml`](../prompts/samples/pem_graphrag_entity_type_prompt.sample.yml), assign a new file name,
and set `ENTITY_TYPE_PROMPT_FILE` to that name.

The running Docker deployment reads prompt profiles from its mounted
`data/prompts/entity_type/` directory. Keep the runtime copy of the active
profile in sync with the repository profile before recreating `lightrag`.
The loader and schema validation are in [`lightrag/prompt.py`](../lightrag/prompt.py).

Changing ontology or examples does not rewrite existing nodes or edges. For a
fair comparison, ingest the same small test corpus in staging after the
change, then re-extract selected production documents only after evaluation.

### Global prompt templates: use sparingly

[`lightrag/prompt.py`](../lightrag/prompt.py) contains built-in prompt
templates for entity extraction, keyword extraction, context construction, and
answer generation. It is the right place only when a change must apply to all
profiles. Prefer the PEM YAML profile for domain wording because it is easier
to test, review, and replace.

## Retrieval Parameters And Query API

### `QueryParam` defaults

[`lightrag/base.py`](../lightrag/base.py) is the central Python-level query
configuration. Relevant fields include:

| Field | Effect |
| --- | --- |
| `mode` | Normal LightRAG mode: `local`, `global`, `hybrid`, `naive`, or `mix` |
| `top_k` | Number of graph entities or relationships initially retrieved |
| `chunk_top_k` | Number of vector-retrieved chunks retained |
| `max_entity_tokens`, `max_relation_tokens`, `max_total_tokens` | Query context budget |
| `enable_rerank` | Enables chunk reranking if configured |
| `retrieval_strategy` | `normal`, `directed`, `combined`, or `auto`; currently defaults to `normal` for safe rollout |
| `edge_direction` | Requested directed traversal direction: `both`, `in`, or `out` |
| `hop_depth`, `chain_top_k`, `chain_fanout` | Bound future multi-hop traversal work |
| `min_relation_importance` | Minimum relation score for directed path selection |

The REST representation and validation live in
[`lightrag/api/routers/query_routes.py`](../lightrag/api/routers/query_routes.py).
Add a `QueryRequest` field there whenever a new `QueryParam` option should be
available to the WebUI, MCP gateway, or external API users.

### Environment-level retrieval tuning

Use the documented settings in [`env.example`](../env.example) before editing
Python defaults:

```dotenv
TOP_K=40
CHUNK_TOP_K=20
MAX_ENTITY_TOKENS=6000
MAX_RELATION_TOKENS=8000
MAX_TOTAL_TOKENS=30000
RERANK_BY_DEFAULT=true
MIN_RERANK_SCORE=0.0
```

These settings alter query behaviour after a service restart and do not need a
re-index. Keep the total token budget comfortably below the context window of
the query model.

### Automatic multi-hop routing

[`lightrag/adaptive_retrieval.py`](../lightrag/adaptive_retrieval.py) is the
single location for deterministic query classification. It currently does not
perform a retrieval call. Change it to adjust:

- German and English trigger phrases;
- priority of rules, in `_ROUTING_RULES`;
- the inferred `in`, `out`, or `both` direction;
- which canonical relation types a query family may traverse;
- the automatic choice between `normal` and `combined`.

Every rule change should have an example in
[`tests/retrieval/test_adaptive_retrieval.py`](../tests/retrieval/test_adaptive_retrieval.py).

## Ingestion, Chunking, And Extraction

### File parsing and pipeline stages

[`lightrag/pipeline.py`](../lightrag/pipeline.py) controls document enqueueing,
parser dispatch, chunking, extraction stage execution, and document status.
Edit it for a new pipeline stage, a different parser workflow, upload-state
behaviour, or safe cancellation logic. This is shared infrastructure: add
tests under `tests/pipeline/` before deploying changes.

### Chunking behaviour

Use environment settings first. `CHUNK_SIZE`, `CHUNK_OVERLAP_SIZE`, and the
F/R/P/V strategy-specific settings are documented in [`env.example`](../env.example).
The resolution of those settings is in [`lightrag/lightrag.py`](../lightrag/lightrag.py),
while pipeline execution is in [`lightrag/pipeline.py`](../lightrag/pipeline.py).

Use [`lightrag/chunker/`](../lightrag/chunker/) only to implement or repair a
chunking algorithm itself:

- `token_size.py`: fixed-token chunks;
- `recursive_character.py`: recursive text splitting;
- `paragraph_semantic.py`: heading/paragraph-aware chunks;
- `semantic_vector.py`: semantic-vector chunking.

Changing a chunking algorithm or its size requires re-chunking and normally
re-extracting affected documents, because all later graph and vector data was
derived from the old chunks.

### Entity and relationship extraction

[`lightrag/operate.py`](../lightrag/operate.py) is the core extraction and
retrieval implementation. It is the correct place for changes to:

- JSON and delimiter extraction parsing;
- relation metadata defaults and validation;
- entity/relation merge and deduplication;
- `RELATION_IMPORTANCE_THRESHOLD` filtering;
- query-context construction and citation assembly.

It is a high-impact file. Prefer changing the PEM prompt first; if code is
necessary, add regression tests under `tests/extraction/` or
`tests/evaluation/`.

### Batch extraction

[`lightrag/api/azure_batch.py`](../lightrag/api/azure_batch.py) translates
LightRAG extraction requests into Azure/OpenAI Batch API requests, polls their
status, and imports completed output. Change this file when debugging batch
JSONL formats, Azure Responses API compatibility, batch polling, or import
behaviour. Use staging and one chunk before submitting a large batch.

## Models, Embeddings, And Reranking

The deployed PEM settings are documented in
[`deploy/mcp/env.example`](../deploy/mcp/env.example). It is the source for
safe configuration examples, while actual secrets belong only in `.env` and
`.env.staging`.

| Need | Preferred first change | Important consequence |
| --- | --- | --- |
| Better extraction quality | `EXTRACT_LLM_MODEL` and PEM prompt profile | Re-extract documents to improve their graph |
| Lower extraction cost | `EXTRACT_LLM_*`, concurrency, Azure Batch configuration | Batch results require explicit import |
| Better semantic retrieval | `EMBEDDING_MODEL`, provider, dimension | Full re-index is mandatory |
| Better ranking of retrieved chunks | `RERANK_BINDING`, model, threshold | No re-index; evaluate query quality |
| Provider-specific output controls | [`lightrag/llm/binding_options.py`](../lightrag/llm/binding_options.py) | Prefer `.env` options before code changes |

Never change an embedding model or dimension against existing vectors. Clear
or migrate the vector/index data and re-ingest the corpus into a clean storage
workspace.

## Graph Storage And Multi-Hop Retrieval

[`lightrag/kg/neo4j_impl.py`](../lightrag/kg/neo4j_impl.py) owns Neo4j labels,
edge upserts, graph reads, and Cypher queries. Change it only for graph schema,
index, storage, or database traversal work. Test on staging and take a Neo4j
backup first.

For the directed multi-hop work, keep these responsibilities separate:

| Concern | File |
| --- | --- |
| Query classification | [`lightrag/adaptive_retrieval.py`](../lightrag/adaptive_retrieval.py) |
| Directed edge normalization, filtering, and ranking | [`lightrag/directed_retrieval.py`](../lightrag/directed_retrieval.py) |
| Actual directed path traversal | planned extension of `lightrag/directed_retrieval.py` |
| Normal/context merge | [`lightrag/operate.py`](../lightrag/operate.py) |
| Neo4j storage and Cypher | [`lightrag/kg/neo4j_impl.py`](../lightrag/kg/neo4j_impl.py) |

The current graph merge still uses an undirected Neo4j `MERGE` form. For the
first directed-retrieval MVP, use `semantic_src_id` and `semantic_tgt_id` as
the source of semantic direction rather than trusting the physical Neo4j arrow
alone.

`lightrag/directed_retrieval.py` is intentionally storage-independent. Its
`normalize_relation_type()` aliases, generic-edge exclusion, importance filter,
and ranking are the narrowest controls for improving future chain quality.
Legacy edges without metadata remain `unknown`; they can be traversed in either
direction but score below explicitly directed edges.

## Evaluation And Safe Change Workflow

Use the benchmark files to turn a proposed quality change into a measurable
comparison:

- [`lightrag/evaluation/benchmarks/pem_real_document_quality.json`](../lightrag/evaluation/benchmarks/pem_real_document_quality.json): real-document benchmark packaged with the backend;
- [`evaluation/benchmarks/pem_real_document_quality.json`](../evaluation/benchmarks/pem_real_document_quality.json): repository-level copy for editing and review;
- [`lightrag/evaluation/live_benchmark.py`](../lightrag/evaluation/live_benchmark.py): benchmark execution and scoring;
- [`docs/WEBUI_EVALUATION_BENCHMARKS.md`](WEBUI_EVALUATION_BENCHMARKS.md): WebUI benchmark workflow.

Recommended workflow:

```text
small code or config change
  -> focused unit tests
  -> staging deployment
  -> ingest/re-extract a representative test set if needed
  -> compare normal and changed retrieval in the benchmark
  -> inspect sources, citations, and Neo4j edges
  -> production deployment only after the result is better or unchanged
```

## WebUI And Connector Surface

| User-facing concern | File | Notes |
| --- | --- | --- |
| Document ingestion, statuses, extraction actions | [`lightrag_webui/src/features/DocumentManager.tsx`](../lightrag_webui/src/features/DocumentManager.tsx) | Admin workflow; rebuild the WebUI after changes |
| Interactive retrieval options | [`lightrag_webui/src/features/RetrievalTesting.tsx`](../lightrag_webui/src/features/RetrievalTesting.tsx) | Good place for future strategy/direction/hop debug controls |
| WebUI REST client/types | [`lightrag_webui/src/api/lightrag.ts`](../lightrag_webui/src/api/lightrag.ts) | Keep it aligned with `QueryRequest` |
| ChatGPT MCP tools | [`lightrag_mcp/server.py`](../lightrag_mcp/server.py) | Tool parameters and public descriptions |
| MCP-to-LightRAG requests | `lightrag_mcp/lightrag_client.py` | Forward new query options only after API behaviour is tested |

WebUI and MCP changes do not alter the graph by themselves, but they can make
new backend controls available to administrators or ChatGPT users.

## Quick Decision Guide

```text
Wrong entities or vague relations?
  -> PEM prompt profile, then re-extract test documents.

Missing relevant chunks?
  -> retrieval budgets/reranker first; chunking only after evaluation.

Poor semantic similarity everywhere?
  -> embedding model or embedding configuration, then full re-index.

Need causal or root-cause chains?
  -> adaptive router, directed path retriever, then context merge.

Need a new document format or ingestion workflow?
  -> pipeline/parser layer, with staging tests.

Need to change graph persistence or Cypher?
  -> Neo4j implementation, backup first.
```
