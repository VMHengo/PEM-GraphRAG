# Directed Multi-Hop Retrieval Plan

## Goal

Extend PEM GraphRAG with direction-aware multi-hop retrieval so the system can answer questions about causal chains, production chains, material-process-artifact dependencies, and organizational/document provenance paths.

The implementation must stay backward compatible:

- Existing queries keep working with `edge_direction="both"`.
- Existing indexed graphs are not silently treated as semantically directed.
- Neo4j is the first fully supported backend for directed retrieval.
- UI and MCP additions are optional layers after the backend is reliable.

## Current State

LightRAG currently stores Neo4j relationships as technically directed relationships with type `DIRECTED`, but the application treats them mostly as undirected graph edges.

Important current code observations:

- [lightrag/base.py](../lightrag/base.py): `BaseGraphStorage` explicitly says graph edge operations are undirected, and methods such as `get_node_edges()` do not accept direction.
- [lightrag/kg/neo4j_impl.py](../lightrag/kg/neo4j_impl.py): `upsert_edge()` and `upsert_edges_batch()` use `MERGE (source)-[r:DIRECTED]-(target)`, which matches and merges regardless of direction.
- [lightrag/kg/neo4j_impl.py](../lightrag/kg/neo4j_impl.py): `get_node_edges()` and `get_nodes_edges_batch()` use undirected `MATCH (n)-[r]-(connected)`.
- [lightrag/operate.py](../lightrag/operate.py): relationship merge and retrieval deduplication often use `tuple(sorted(...))`, so `A -> B` and `B -> A` collapse into the same relation.
- [lightrag/utils.py](../lightrag/utils.py): `make_relation_chunk_key()` sorts the pair, so relation chunk tracking is also undirected.
- [lightrag/prompt.py](../lightrag/prompt.py): default extraction prompts explicitly tell the model to treat relationships as undirected unless stated otherwise.
- [prompts/entity_type/pem_graphrag_entity_type_prompt.yml](../prompts/entity_type/pem_graphrag_entity_type_prompt.yml): the PEM prompt does not yet include a directionality field.
- [lightrag_webui/src/hooks/useLightragGraph.tsx](../lightrag_webui/src/hooks/useLightragGraph.tsx): the WebUI uses `UndirectedGraph` for display.
- [lightrag/api/routers/graph_routes.py](../lightrag/api/routers/graph_routes.py): `/graphs` exposes subgraph retrieval by label, max depth, and max nodes, but not by direction.

This means a full directed rewrite would require changes across extraction, merge identity, graph storage, retrieval ranking, tests, and eventually WebUI/MCP surfaces. The recommended plan below avoids that as the first step. It keeps normal LightRAG retrieval intact and adds an adaptive directed path retrieval layer next to it.

## Updated Architectural Decision

The recommended architecture is not "replace LightRAG retrieval with directed retrieval". It is an adaptive hybrid retrieval router:

```text
User query
  -> Query-type detection
  -> Normal LightRAG retrieval
  -> Optional directed Neo4j path retrieval
  -> Context merge
  -> Answer generation
```

This approach is preferable because:

- General conceptual questions still benefit from LightRAG's existing `mix`, `local`, and `global` retrieval.
- Chain questions can use explicit Neo4j traversal without rewriting the full LightRAG storage and vector pipeline.
- The connector and WebUI can expose one simple `retrieval_strategy="auto"` option.
- Directed retrieval can fail open: if no reliable directed paths are found, the system falls back to normal LightRAG context.
- Existing indexed documents remain usable.

Supported retrieval strategies:

```text
normal
  Use current LightRAG retrieval only.

directed
  Use directed path retrieval only. Useful for debugging and evaluation.

combined
  Use normal LightRAG retrieval plus directed paths.

auto
  Classify the query and choose normal, directed, or combined.
```

Initial query types:

```text
general
causal_chain
production_chain
dependency_chain
provenance_chain
comparison_or_association
```

Routing recommendation:

| Query type | Retrieval strategy |
|---|---|
| `general` | `normal` |
| `comparison_or_association` | `normal` or `combined` |
| `causal_chain` | `combined` with directed paths |
| `production_chain` | `combined` with directed paths |
| `dependency_chain` | `combined` with directed paths |
| `provenance_chain` | `combined` with directed paths |

## Recommended Scope

Do not start with a full LightRAG core rewrite. Start with an additive router and a separate directed path retriever. Only move relation identity, VDB keys, and all storage backends to true direction-aware behavior after the directed path retriever proves useful.

Recommended phases:

1. Direction metadata extraction and storage.
2. Adaptive retrieval router with explicit `normal`, `directed`, `combined`, and `auto` strategies.
3. Separate Neo4j directed path retriever with bounded one-hop/two-hop traversal.
4. Context formatting for directed paths/chains.
5. MCP and API parameters for retrieval strategy, direction, and hop depth.
6. Evaluation set and regression tests.
7. Optional WebUI controls for debugging.
8. Later: direction-aware relation identity, VDB keys, and full storage API behavior.
9. Later: automatic query planning and soft direction ranking.

## Domain Semantics

For PEM GraphRAG, direction matters most for these relationship families:

- `causes`: degradation mechanism -> failure/safety outcome.
- `produces`: process -> artifact/output.
- `uses`: process/method/artifact -> material/component/method.
- `contains` / `part_of`: system -> component or component -> system, depending on chosen canonical direction.
- `optimizes`: method/control/model -> process/system.
- `supports`: method/data/tool -> process/decision.
- `published_by`: content -> organization or organization -> content, depending on canonical direction.
- `studies` / `characterizes`: method/organization/publication -> object/phenomenon.
- `depends_on`: process/model/system -> prerequisite/input.

Direction matters less for symmetric or associative relationships:

- `collaborates_with`
- `similar_to`
- `related_to`
- `compared_with`
- `co-occurs_with`

These should remain `directionality="undirected"` or `directionality="unknown"`.

## Data Model

Add direction metadata to every relationship:

```json
{
  "src_id": "Laser-Based Drying",
  "tgt_id": "Electrode Drying Process",
  "keywords": "optimizes, process improvement",
  "description": "Laser-based drying optimizes the electrode drying process.",
  "directionality": "directed",
  "relation_type": "optimizes",
  "direction_confidence": 0.86
}
```

Required fields:

- `directionality`: `directed | undirected | unknown`
- `relation_type`: short canonical predicate such as `causes`, `uses`, `produces`, `optimizes`, `supports`

Recommended fields:

- `direction_confidence`: float between `0.0` and `1.0`
- `direction_rationale`: short phrase explaining why source and target were ordered this way

Default migration behavior:

- Existing edges without `directionality` should be treated as `unknown`.
- `unknown` behaves like `both` in retrieval.
- Do not reinterpret old edges as directed unless the documents are re-extracted with the new prompt.

## Canonical Direction Rules

Use stable, domain-specific canonical directions:

| Predicate | Direction |
|---|---|
| `causes` | cause -> effect |
| `degrades` | mechanism -> affected artifact/material |
| `produces` | process -> output artifact |
| `uses` | actor/process/artifact -> used method/material/component |
| `contains` | container/system -> component |
| `part_of` | component -> system |
| `optimizes` | method/control/model -> optimized process/system |
| `supports` | method/data/tool -> supported process/decision |
| `studies` | organization/method/content -> studied object |
| `published_by` | content -> organization |
| `authored_by` | content -> person/organization |
| `located_at` | organization/unit/facility -> location |
| `collaborates_with` | undirected |
| `similar_to` | undirected |
| `compared_with` | undirected |

These rules should be copied into the PEM entity prompt examples so extraction and retrieval agree.

## Phase 0: Baseline And Safety

Purpose: establish current answer quality before changing graph semantics.

Tasks:

- Create an evaluation file with 30-50 queries in `tests/evaluation/fixtures/`.
- Include at least these classes:
  - 10 production-chain questions.
  - 10 causal/degradation-chain questions.
  - 10 material-process-artifact questions.
  - 5 organization/publication provenance questions.
  - 5 symmetric relation questions.
- For each query, store expected entities, expected relation predicates, expected sources, and whether direction matters.
- Run current `mix`, `local`, and `global` retrieval and save outputs.

Files:

- [tests/evaluation/](../tests/evaluation/)
- [tests/evaluation/test_evaluation_offline_retrieval_check.py](../tests/evaluation/test_evaluation_offline_retrieval_check.py)

Estimated time with Codex:

- 0.5-1 day for a first evaluation fixture.
- 1-2 days if manually checking answer quality with real PEM documents.

Acceptance criteria:

- Baseline queries run reproducibly.
- We can compare directed changes against current `both` behavior.

## Phase 1: Direction-Aware Extraction

Purpose: extract relationship direction before touching retrieval.

Tasks:

- Extend JSON extraction prompt to require `directionality`, `relation_type`, and optionally `direction_confidence`.
- Extend delimiter extraction only if still needed. JSON mode should be primary.
- Update PEM prompt examples with directed and undirected examples.
- Parse the new fields in extraction and preserve them in relationship data.
- Default missing values to:
  - `directionality="unknown"`
  - `relation_type` from `keywords` fallback
  - no confidence if absent

Files:

- [lightrag/prompt.py](../lightrag/prompt.py)
- [lightrag/operate.py](../lightrag/operate.py)
- [prompts/entity_type/pem_graphrag_entity_type_prompt.yml](../prompts/entity_type/pem_graphrag_entity_type_prompt.yml)
- [prompts/samples/pem_graphrag_entity_type_prompt.sample.yml](../prompts/samples/pem_graphrag_entity_type_prompt.sample.yml)
- [data/prompts/entity_type/pem_graphrag_entity_type_prompt.yml](../data/prompts/entity_type/pem_graphrag_entity_type_prompt.yml)

Important code points:

- `_handle_single_relationship_extraction()` in [lightrag/operate.py](../lightrag/operate.py)
- `_handle_single_json_relationship_extraction()` area in [lightrag/operate.py](../lightrag/operate.py)

Estimated time with Codex:

- 1 day for prompt and parser support.
- 1 additional day for robust tests and examples.

Acceptance criteria:

- New documents store relation metadata with `directionality`.
- Old documents still process when the model omits direction metadata.
- Unit tests cover directed, undirected, and unknown relationship extraction.

## Phase 2: Central Relation Identity Helpers Later

Purpose: remove ad hoc `tuple(sorted(...))` without breaking undirected behavior.

This phase is important for a full directed LightRAG core, but it is not required for the first adaptive-router MVP. The MVP can keep existing LightRAG relation identity unchanged and run directed paths directly against Neo4j.

Add a central helper module, for example:

```text
lightrag/relation_identity.py
```

Suggested API:

```python
RelationDirectionality = Literal["directed", "undirected", "unknown"]
EdgeTraversalDirection = Literal["in", "out", "both"]

def normalize_directionality(value: object) -> RelationDirectionality: ...

def relation_key(src: str, tgt: str, directionality: str = "unknown") -> tuple[str, str, str]: ...

def relation_vdb_id(src: str, tgt: str, directionality: str = "unknown") -> str: ...

def relation_chunk_key(src: str, tgt: str, directionality: str = "unknown") -> str: ...

def direction_matches(query_direction: str, edge_directionality: str, anchor: str, src: str, tgt: str) -> bool: ...
```

Rules:

- Directed key: `(src, tgt, "directed")`.
- Undirected key: `(min(src, tgt), max(src, tgt), "undirected")`.
- Unknown key: `(min(src, tgt), max(src, tgt), "unknown")`.
- Existing undirected behavior maps to `unknown` or `undirected`, depending on migration policy.

Files:

- New: `lightrag/relation_identity.py`
- [lightrag/utils.py](../lightrag/utils.py): replace or wrap `make_relation_chunk_key()`.
- [lightrag/operate.py](../lightrag/operate.py): replace relation deduplication sites incrementally.

Estimated time with Codex:

- 1-2 days for helpers and local usage.
- 2-3 days if all sorted-edge call sites are converted immediately.

Acceptance criteria:

- Tests prove `A -> B` and `B -> A` are distinct only for `directed`.
- Tests prove undirected/unknown relations keep backward-compatible deduplication.

## Phase 3: Neo4j Direction-Aware Storage Later

Purpose: make Neo4j capable of storing and retrieving true edge direction.

This phase is also not required in full for the adaptive-router MVP if the directed path retriever uses explicit Cypher against already stored relationship direction and `directionality` properties. It becomes necessary once normal LightRAG local/global retrieval should become truly direction-aware.

Tasks:

- Change directed writes from undirected merge:

```cypher
MERGE (source)-[r:DIRECTED]-(target)
```

to directed merge for directed relations:

```cypher
MERGE (source)-[r:DIRECTED]->(target)
```

- For undirected or unknown relations, choose one canonical physical direction but set `directionality`.
- Extend read APIs to return physical source and target from `startNode(r)` and `endNode(r)`.
- Add `direction="both"` parameter to:
  - `get_node_edges()`
  - `get_nodes_edges_batch()`
- Implement Cypher variants:
  - `out`: `MATCH (n)-[r]->(connected)`
  - `in`: `MATCH (n)<-[r]-(connected)`
  - `both`: `MATCH (n)-[r]-(connected)`
- Make `get_edge()`, `get_edges_batch()`, `has_edge()`, and removal behavior aware of `directionality`.

Files:

- [lightrag/base.py](../lightrag/base.py)
- [lightrag/kg/neo4j_impl.py](../lightrag/kg/neo4j_impl.py)
- Other graph storage implementations should keep default `both` behavior.

Estimated time with Codex:

- 2-4 days for Neo4j-only storage changes.
- 1-2 additional days for integration tests with a live Neo4j container.

Acceptance criteria:

- `get_node_edges("A", direction="out")` returns only `A -> ?` plus undirected/unknown edges if configured.
- `get_node_edges("B", direction="in")` returns `A -> B`.
- `both` matches current behavior.
- Existing storage backends do not break.

## Phase 4: Adaptive Retrieval Router And Public API Surface

Purpose: expose direction controls and retrieval strategy in a backward-compatible way, without forcing all queries through directed retrieval.

Add fields to `QueryParam`:

```python
retrieval_strategy: Literal["auto", "normal", "directed", "combined"] = "auto"
edge_direction: Literal["both", "in", "out"] = "both"
hop_depth: int = 2
chain_top_k: int = 20
chain_fanout: int = 20
chain_query_type: Literal[
    "auto",
    "general",
    "causal_chain",
    "production_chain",
    "dependency_chain",
    "provenance_chain",
    "comparison_or_association",
] = "auto"
```

MVP defaults:

- `retrieval_strategy="auto"`
- `edge_direction="both"`
- `hop_depth=2`
- `chain_query_type="auto"`

Add a small router module:

```text
lightrag/adaptive_retrieval.py
```

Suggested router output:

```python
{
    "query_type": "production_chain",
    "use_normal_retrieval": True,
    "use_directed_paths": True,
    "edge_direction": "out",
    "hop_depth": 2,
    "target_relation_types": ["contains", "uses", "produces", "optimizes"],
}
```

The first version can use deterministic keyword rules before adding LLM-based planning. For example:

- `führt zu`, `causes`, `effect`, `failure`, `degradation` -> `causal_chain`
- `production chain`, `process chain`, `manufacturing steps`, `Herstellungskette` -> `production_chain`
- `depends on`, `requires`, `uses`, `input materials` -> `dependency_chain`
- `published by`, `authored by`, `source`, `document` -> `provenance_chain`

Files:

- New: `lightrag/adaptive_retrieval.py`
- [lightrag/base.py](../lightrag/base.py)
- [lightrag/api/routers/query_routes.py](../lightrag/api/routers/query_routes.py)
- [lightrag/operate.py](../lightrag/operate.py)
- [lightrag_mcp/lightrag_client.py](../lightrag_mcp/lightrag_client.py)
- [lightrag_mcp/server.py](../lightrag_mcp/server.py)
- [lightrag_webui/src/api/lightrag.ts](../lightrag_webui/src/api/lightrag.ts)
- [lightrag_webui/src/features/RetrievalTesting.tsx](../lightrag_webui/src/features/RetrievalTesting.tsx)

Estimated time with Codex:

- 1-2 days for backend parameters and deterministic router.
- 1 additional day including MCP and WebUI controls.

Acceptance criteria:

- Existing API calls without new fields behave exactly as before.
- `retrieval_strategy="normal"` forces current LightRAG behavior.
- `retrieval_strategy="directed"` forces directed path retrieval for debugging.
- `retrieval_strategy="combined"` merges normal and path contexts.
- `retrieval_strategy="auto"` chooses a route based on query type and falls back to normal retrieval.

## Phase 5: Separate Directed Path Retriever MVP

Purpose: add directed retrieval as a separate side-channel instead of modifying `_find_most_related_edges_from_entities()` first.

Tasks:

- Add a new module:

```text
lightrag/directed_retrieval.py
```

- Use top entities from normal local retrieval as anchors.
- Run bounded Neo4j Cypher traversal from those anchors.
- Support one-hop and two-hop paths first.
- Include directed, undirected, and unknown edges, but score exact directed matches higher.
- Keep `hop_depth <= 3` and `chain_fanout <= 20` initially.
- Do not change relationship VDB IDs yet.
- Do not replace sorted dedup in the full LightRAG pipeline yet.

Example Cypher shape:

```cypher
MATCH path = (start {entity_id: $anchor})-[rels*1..$hop_depth]->(end)
WHERE all(r IN rels WHERE coalesce(r.directionality, "unknown") IN ["directed", "unknown", "undirected"])
RETURN path
LIMIT $limit
```

For incoming chains:

```cypher
MATCH path = (start {entity_id: $anchor})<-[rels*1..$hop_depth]-(end)
RETURN path
LIMIT $limit
```

Files:

- New: `lightrag/directed_retrieval.py`
- [lightrag/operate.py](../lightrag/operate.py)
- [lightrag/kg/neo4j_impl.py](../lightrag/kg/neo4j_impl.py)
- [lightrag/base.py](../lightrag/base.py)

Estimated time with Codex:

- 2-4 days for Neo4j path retrieval and integration into query context.
- 1-2 days for tests and tuning.

Acceptance criteria:

- `retrieval_strategy="directed"` returns path context for simple production and causal queries.
- `retrieval_strategy="normal"` remains unchanged.
- `retrieval_strategy="combined"` contains normal LightRAG context plus directed path context.
- If no path is found, the query still returns normal context in `auto` and `combined`.

## Phase 6: Adaptive Multi-Hop Context Merge

Purpose: retrieve and merge chains without letting path context drown out normal RAG context.

Add a retrieval helper rather than overloading existing relation retrieval too much:

```python
async def _find_directed_multihop_paths_from_entities(
    node_datas: list[dict],
    query_param: QueryParam,
    knowledge_graph_inst: BaseGraphStorage,
) -> list[dict]:
    ...
```

Suggested path object:

```json
{
  "path_id": "Battery Cell Manufacturing -> Electrode Drying Process -> Laser-Based Drying",
  "nodes": ["Battery Cell Manufacturing", "Electrode Drying Process", "Laser-Based Drying"],
  "edges": [
    {
      "src_id": "Battery Cell Manufacturing",
      "tgt_id": "Electrode Drying Process",
      "relation_type": "contains",
      "directionality": "directed",
      "description": "..."
    }
  ],
  "score": 12.4,
  "source_ids": ["chunk-..."],
  "file_paths": ["...pdf"]
}
```

Traversal MVP:

- Start from top local entities.
- BFS up to `hop_depth`, default maximum `2`.
- Use `edge_direction` for traversal:
  - `out`: follow outgoing directed edges and unknown/undirected edges.
  - `in`: follow incoming directed edges and unknown/undirected edges.
  - `both`: current broad behavior.
- Stop expansion after:
  - `chain_top_k` retained paths.
  - `max_relation_tokens`.
  - per-anchor fanout cap, for example 20 edges.
- Avoid cycles with a visited path node set.

Scoring MVP:

```text
path_score =
  sum(edge.weight)
  + source_entity_similarity
  + predicate_bonus
  - hop_penalty
```

Recommended initial constants:

- direct edge: no penalty
- second hop: `-0.15`
- third hop: `-0.35`
- directed match: `1.0`
- unknown edge: `0.75`
- undirected edge: `0.85`

Files:

- [lightrag/operate.py](../lightrag/operate.py)
- [lightrag/directed_retrieval.py](../lightrag/directed_retrieval.py)
- [lightrag/adaptive_retrieval.py](../lightrag/adaptive_retrieval.py)
- [lightrag/base.py](../lightrag/base.py)

Estimated time with Codex:

- 2-4 days for a stable context merge after Phase 5.
- 1-2 additional days for tests and tuning.

Acceptance criteria:

- A query about a production chain returns ordered path context.
- A query about a causal chain returns cause -> mechanism -> effect context.
- Cycles do not explode the number of retrieved paths.
- Normal LightRAG context and path context are both visible with `only_need_context=true`.

## Phase 7: Context Formatting For Chains

Purpose: make the LLM use path structure instead of seeing a flat relation table.

Add a chain context section alongside entities, relationships, and chunks:

```text
Directed Paths:
[P1] Battery Cell Manufacturing --contains--> Electrode Drying Process --optimized_by--> Laser-Based Drying
Evidence: chunk-1, chunk-8
```

Prompt guidance:

- Treat path direction as semantic, not merely visual.
- Do not reverse a directed relation unless the path explicitly supports it.
- For unknown/undirected edges, phrase cautiously.

Files:

- [lightrag/operate.py](../lightrag/operate.py)
- [lightrag/prompt.py](../lightrag/prompt.py)

Estimated time with Codex:

- 1-2 days.

Acceptance criteria:

- `only_need_context=true` includes a clearly separated directed path section.
- Generated answers cite documents from path edges.
- The LLM distinguishes "X causes Y" from "Y is caused by X".

## Phase 8: Relationship Vector Store And Chunk Tracking

Purpose: make VDB and relation chunk tracking safe for directed edges.

Tasks:

- Replace VDB IDs based on sorted pairs with `relation_vdb_id()`.
- Replace `make_relation_chunk_key(src, tgt)` with direction-aware keys.
- Keep compatibility reader for old keys:
  - first try new key
  - fallback to old sorted key
- For migration, avoid in-place rewrite unless needed. Re-indexing is safer.

Files:

- [lightrag/operate.py](../lightrag/operate.py)
- [lightrag/utils.py](../lightrag/utils.py)
- New: `lightrag/relation_identity.py`

Estimated time with Codex:

- 2-4 days.

Acceptance criteria:

- Directed `A -> B` and `B -> A` can have different relationship vectors.
- Old data remains queryable in `both` mode.
- Re-indexed data uses new direction-aware keys.

## Phase 9: WebUI Support

Purpose: make direction and paths inspectable by developers/admins.

Tasks:

- Add graph settings:
  - edge direction: `Both | Outgoing | Incoming`
  - hop depth: `1 | 2 | 3`
  - show arrows for directed edges
  - show unknown/undirected edges toggle
- Change WebUI graph model from `UndirectedGraph` to a directed or mixed graph where possible.
- Keep edge labels from recent UI work.
- Add path display panel for selected node:
  - outgoing paths
  - incoming paths
  - evidence chunks/files

Files:

- [lightrag_webui/src/hooks/useLightragGraph.tsx](../lightrag_webui/src/hooks/useLightragGraph.tsx)
- [lightrag_webui/src/features/GraphViewer.tsx](../lightrag_webui/src/features/GraphViewer.tsx)
- [lightrag_webui/src/components/graph/Settings.tsx](../lightrag_webui/src/components/graph/Settings.tsx)
- [lightrag_webui/src/components/graph/PropertiesView.tsx](../lightrag_webui/src/components/graph/PropertiesView.tsx)
- [lightrag_webui/src/api/lightrag.ts](../lightrag_webui/src/api/lightrag.ts)
- [lightrag/api/routers/graph_routes.py](../lightrag/api/routers/graph_routes.py)

Estimated time with Codex:

- 2-4 days for useful controls.
- 5-8 days if switching the rendered graph cleanly to directed arrows and path visualization.

Acceptance criteria:

- Developers can visually inspect direction and multi-hop paths.
- The graph does not become unreadable for large subgraphs.

## Phase 10: MCP And ChatGPT Connector Surface

Purpose: expose directed path search to ChatGPT without making the connector unsafe.

Add a read-only MCP tool:

```python
query_pem_graphrag_paths(
    question: str,
    start_entity: str | None = None,
    retrieval_strategy: Literal["auto", "normal", "directed", "combined"] = "auto",
    edge_direction: Literal["both", "in", "out"] = "both",
    hop_depth: int = 2,
)
```

Alternatively, extend the existing `query_pem_graphrag` MCP tool with the same optional parameters. This is simpler for non-technical ChatGPT users because they keep using one connector action.

Return:

- answer
- paths
- references
- citations
- mode

Files:

- [lightrag_mcp/server.py](../lightrag_mcp/server.py)
- [lightrag_mcp/lightrag_client.py](../lightrag_mcp/lightrag_client.py)
- [lightrag/api/routers/query_routes.py](../lightrag/api/routers/query_routes.py)

Estimated time with Codex:

- 1-2 days.

Acceptance criteria:

- ChatGPT can ask "Show the production chain from electrode drying to battery cell output."
- ChatGPT can also ask a general question without triggering unnecessary path traversal.
- The connector remains read-only.
- OAuth behavior remains unchanged.

## Phase 11: Optional Automatic Query Planning

Purpose: infer direction and path intent from natural language.

Do this only after manual direction and hop parameters work.

Possible extension:

```json
{
  "low_level_keywords": ["battery cell manufacturing"],
  "high_level_keywords": ["production chain"],
  "relation_direction": "out",
  "hop_depth": 2,
  "target_relation_types": ["contains", "produces", "uses"]
}
```

Files:

- [lightrag/prompt.py](../lightrag/prompt.py)
- [lightrag/operate.py](../lightrag/operate.py)
- [tests/extraction/](../tests/extraction/)

Estimated time with Codex:

- 2-4 days for a simple planner.
- 1-2 weeks for robust domain-specific query planning.

Acceptance criteria:

- Manual settings still override auto planning.
- Bad planner output falls back to `both`.

## Test Plan

Backend unit tests:

- `relation_key("A", "B", "directed") != relation_key("B", "A", "directed")`
- `relation_key("A", "B", "undirected") == relation_key("B", "A", "undirected")`
- missing `directionality` becomes `unknown`
- extraction accepts older JSON without direction fields

Neo4j integration tests:

- insert `A -> B`
- insert `B -> A`
- insert `A -- C` as undirected
- assert `out`, `in`, and `both` behavior

Retrieval tests:

- `edge_direction="out"` retrieves production outputs from process anchors.
- `edge_direction="in"` retrieves upstream causes/processes for an artifact.
- `hop_depth=2` finds a two-step process/material chain.
- cycles do not create duplicate endless paths.
- `both` remains close to baseline.

MCP tests:

- invalid direction is rejected.
- hop depth is capped.
- paths include references/citations.

WebUI tests:

- Graph query sends direction and hop depth.
- selected node shows incoming/outgoing paths.
- relation labels remain visible after path expansion.

## Evaluation Metrics

Answer quality:

- Does the answer state the correct chain order?
- Does it avoid reversing cause/effect?
- Are cited sources relevant?

Retrieval quality:

- Precision@k for expected relations.
- Path recall for expected chains.
- Number of irrelevant side branches.
- No-context rate.

Robustness:

- Behavior when directionality is missing.
- Behavior when extraction direction is wrong.
- Behavior on dense high-degree nodes.
- Latency under `hop_depth=2` and `hop_depth=3`.

Admin/dev experience:

- Can direction be inspected in Neo4j?
- Can direction be inspected in WebUI?
- Can a single document be re-extracted after prompt changes?

## Risk Assessment

Main risks:

- LLM may extract inconsistent direction.
- Strict direction can lower recall.
- Multi-hop expansion can explode on high-degree nodes.
- Existing indexed data has unreliable source/target semantics.
- Relationship VDB migration can silently mismatch if not handled carefully.

Mitigations:

- Keep `both` as default.
- Treat old edges as `unknown`.
- Add fanout caps and hop depth caps.
- Add soft direction scoring before strict filtering becomes default.
- Re-index representative documents before evaluating quality.
- Do not rewrite all storage backends at once.

## Expected Impact

Answer quality:

- Medium to high improvement for causal-chain and production-chain questions.
- Low improvement for broad summarization questions.

Domain understanding:

- High improvement for process flows, degradation mechanisms, system composition, and publication provenance.

Robustness:

- Short-term risk increases because more semantics depend on extraction quality.
- Long-term robustness improves if `unknown` fallback and evaluation are implemented.

Latency:

- One-hop directed retrieval should be similar to current local retrieval.
- Two-hop retrieval may be moderately slower.
- Three-hop retrieval can become expensive unless fanout is capped.

Maintenance cost:

- Low to medium for the adaptive-router MVP because it is additive.
- Medium to high only if relation identity, VDB keys, and all graph storage backends are later converted to true directed behavior.
- Tests are not optional here; without them, regressions are likely.

## Time Estimate With Codex

Assuming one developer using Codex for implementation and code navigation:

| Work package | Estimate |
|---|---:|
| Baseline eval fixture | 0.5-1 day |
| Direction extraction + parser | 1-2 days |
| Adaptive retrieval router | 1-2 days |
| QueryParam/API/MCP fields | 1-2 days |
| Separate Neo4j directed path retriever | 2-4 days |
| Multi-hop context merge | 2-4 days |
| Context formatting for paths | 1-2 days |
| Minimal WebUI controls/inspection | 1-2 days |
| Tests and evaluation | 2-4 days |
| Later: relation identity helpers | 1-2 days |
| Later: VDB/chunk-key migration support | 2-4 days |
| Later: full Neo4j directed storage API | 2-4 days |

Minimal useful MVP:

- 5-10 working days.

Good production-ready version:

- 2-3 weeks.

Full version with auto planning and polished UI:

- 4-6 weeks.

## Recommended Implementation Order

1. Add extraction metadata fields, but keep retrieval unchanged.
2. Re-index 5-10 representative test documents.
3. Add `QueryParam.retrieval_strategy`, `edge_direction`, `hop_depth`, and `chain_top_k`.
4. Create `lightrag/adaptive_retrieval.py` with deterministic query-type routing.
5. Create `lightrag/directed_retrieval.py` with bounded Neo4j path traversal.
6. Merge directed path context into normal LightRAG context for `combined` and `auto`.
7. Add MCP parameters, preferably to the existing query tool.
8. Add `only_need_context=true` diagnostics for paths.
9. Evaluate against baseline.
10. Add minimal WebUI controls for strategy, direction, and hop depth.
11. Only after evaluation: create `lightrag/relation_identity.py` and migrate relation/VDB identity.

Stop and evaluate after step 9. If answer quality does not improve on production-chain and causal-chain queries, do not continue into full LightRAG core directionality migration yet.

## Self-Review Of This Plan

What is strong:

- It does not break current retrieval by default.
- It avoids a premature full LightRAG core rewrite.
- It recognizes that Neo4j direction alone is not enough.
- It handles old data safely as `unknown`.
- It separates normal retrieval, directed-only retrieval, and combined retrieval.
- It includes evaluation before investing in a full path planner.

What is intentionally postponed:

- Full automatic query planning.
- Full storage-backend parity beyond Neo4j.
- In-place migration of all existing relation vector IDs.
- Visual path exploration as a first milestone.
- Full replacement of `_find_most_related_edges_from_entities()`.

Open decisions before coding:

- Should `unknown` edges be included in `in`/`out` retrieval by default? Recommendation: yes, with lower score.
- Should canonical predicate labels be a closed enum? Recommendation: start with a recommended list, not a hard enum.
- Should existing documents be re-indexed? Recommendation: yes for evaluation and production quality.
- Should WebUI use a directed graph renderer immediately? Recommendation: not in the first backend MVP; add arrows once storage and retrieval are proven.

Final recommendation:

Build an adaptive hybrid retrieval router first. Keep normal LightRAG retrieval as the default fallback and add bounded directed Neo4j path retrieval only for chain-like query types. This gives most of the benefit for PEM production and causal chains while avoiding the risk of rewriting LightRAG's core undirected relation pipeline too early.
