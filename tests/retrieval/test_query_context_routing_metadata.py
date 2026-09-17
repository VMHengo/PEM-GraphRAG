from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from lightrag import operate
from lightrag.base import QueryParam


def _patch_context_dependencies(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Replace retrieval stages so route metadata can be tested in isolation."""

    calls: dict[str, list] = {"search_params": []}

    async def fake_search(*args, **kwargs):
        calls["search_params"].append(args[7])
        return {
            "final_entities": [{"entity_name": "Defect X"}],
            "final_relations": [],
            "vector_chunks": [],
            "chunk_tracking": {},
            "query_embedding": None,
        }

    async def fake_truncation(*args, **kwargs):
        return {
            "filtered_entities": [{"entity_name": "Defect X"}],
            "filtered_relations": [],
            "entities_context": [{"entity": "Defect X"}],
            "relations_context": [],
            "entity_id_to_original": {},
            "relation_id_to_original": {},
        }

    async def fake_merge(*args, **kwargs):
        return []

    async def fake_context(*args, **kwargs):
        return "stable context", {
            "data": {"entities": [], "relationships": [], "chunks": []},
            "metadata": {"query_mode": kwargs["query_param"].mode},
        }

    monkeypatch.setattr(operate, "_perform_kg_search", fake_search)
    monkeypatch.setattr(operate, "_apply_token_truncation", fake_truncation)
    monkeypatch.setattr(operate, "_merge_all_chunks", fake_merge)
    monkeypatch.setattr(operate, "_build_context_str", fake_context)
    return calls


async def _build_context(
    query: str,
    query_param: QueryParam,
    knowledge_graph_inst: object | None = None,
    text_chunks_db: object | None = None,
):
    return await operate._build_query_context(
        query=query,
        ll_keywords="defect",
        hl_keywords="",
        knowledge_graph_inst=knowledge_graph_inst or object(),
        entities_vdb=object(),
        relationships_vdb=object(),
        text_chunks_db=text_chunks_db or SimpleNamespace(global_config={}),
        query_param=query_param,
    )


@pytest.mark.asyncio
@pytest.mark.offline
async def test_query_context_exposes_root_cause_route_metadata(monkeypatch):
    _patch_context_dependencies(monkeypatch)

    result = await _build_context(
        "What causes defect X?", QueryParam(retrieval_strategy="auto")
    )

    assert result is not None
    assert result.context == "stable context"
    assert result.raw_data["metadata"]["retrieval_route"] == {
        "query_type": "root_cause",
        "effective_strategy": "combined",
        "use_normal_retrieval": True,
        "use_directed_paths": True,
        "edge_direction": "in",
        "target_relation_types": (
            "causes",
            "affects",
            "influences",
            "leads_to",
            "results_in",
            "degrades",
        ),
        "matched_rule": "root_cause",
    }


@pytest.mark.asyncio
@pytest.mark.offline
async def test_query_context_exposes_normal_route_for_general_query(monkeypatch):
    _patch_context_dependencies(monkeypatch)

    result = await _build_context(
        "Explain PEM electrolysis.", QueryParam(retrieval_strategy="auto")
    )

    assert result is not None
    route = result.raw_data["metadata"]["retrieval_route"]
    assert route["query_type"] == "general"
    assert route["effective_strategy"] == "normal"
    assert route["use_normal_retrieval"] is True
    assert route["use_directed_paths"] is False
    assert route["edge_direction"] == "both"
    assert result.raw_data["metadata"]["directed_paths"]["status"] == "skipped"
    assert result.raw_data["metadata"]["directed_paths"]["reason"] == "strategy_normal"


@pytest.mark.asyncio
@pytest.mark.offline
async def test_route_metadata_does_not_change_existing_retrieval_inputs(monkeypatch):
    calls = _patch_context_dependencies(monkeypatch)
    query_param = QueryParam(retrieval_strategy="normal")
    graph = _DirectedGraph({"Defect X": []})

    result = await _build_context("What causes defect X?", query_param, graph)

    assert result is not None
    assert result.context == "stable context"
    assert calls["search_params"] == [query_param]
    assert graph.calls == []
    route = result.raw_data["metadata"]["retrieval_route"]
    assert route["effective_strategy"] == "normal"
    assert route["use_directed_paths"] is False


class _DirectedGraph:
    def __init__(
        self,
        graph: dict[str, list[dict[str, Any]]],
        error: Exception | None = None,
    ):
        self.graph = graph
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    async def get_directed_neighbor_edges_batch(self, node_ids: Sequence[str]):
        self.calls.append(tuple(node_ids))
        if self.error is not None:
            raise self.error
        return {node_id: self.graph.get(node_id, []) for node_id in node_ids}


class _ChunkStore(SimpleNamespace):
    def __init__(self, chunks: dict[str, dict[str, Any]]):
        super().__init__(global_config={})
        self.chunks = chunks

    async def get_by_ids(self, ids: list[str]):
        return [self.chunks.get(chunk_id) for chunk_id in ids]


@pytest.mark.asyncio
@pytest.mark.offline
async def test_combined_route_appends_semantically_ordered_directed_evidence(monkeypatch):
    _patch_context_dependencies(monkeypatch)
    graph = _DirectedGraph(
        {
            "Defect X": [
                {
                    "semantic_src_id": "Uneven Coating",
                    "semantic_tgt_id": "Defect X",
                    "relation_type": "causes",
                    "directionality": "directed",
                    "relation_importance": 0.95,
                    "file_path": "defects.pdf",
                }
            ],
            "Uneven Coating": [
                {
                    "semantic_src_id": "Process Instability",
                    "semantic_tgt_id": "Uneven Coating",
                    "relation_type": "influences",
                    "directionality": "directed",
                    "relation_importance": 0.9,
                    "file_path": "coating.pdf",
                }
            ],
        }
    )

    result = await _build_context(
        "What causes defect X?",
        QueryParam(retrieval_strategy="auto", hop_depth=2),
        graph,
    )

    assert result is not None
    assert result.context.startswith(
        "stable context\n\nDirected Evidence Paths (semantic source -> relation -> target):"
    )
    assert (
        "Process Instability --[influences]--> Uneven Coating --[causes]--> Defect X"
        in result.context
    )
    diagnostics = result.raw_data["metadata"]["directed_paths"]
    assert diagnostics["status"] == "completed"
    assert diagnostics["reason"] == "paths_found"
    assert diagnostics["anchor_entities"] == ["Defect X"]
    assert diagnostics["path_count"] == 2
    assert graph.calls == [("Defect X",), ("Uneven Coating",)]


@pytest.mark.asyncio
@pytest.mark.offline
async def test_directed_path_sources_are_merged_into_citeable_references(monkeypatch):
    _patch_context_dependencies(monkeypatch)
    graph = _DirectedGraph(
        {
            "Defect X": [
                {
                    "semantic_src_id": "Uneven Coating",
                    "semantic_tgt_id": "Defect X",
                    "relation_type": "causes",
                    "directionality": "directed",
                    "relation_importance": 0.95,
                    "source_id": "chunk-coating",
                    "file_path": "defects.pdf",
                }
            ]
        }
    )
    text_chunks = _ChunkStore(
        {
            "chunk-coating": {
                "content": "Uneven coating causes Defect X.",
                "file_path": "defects.pdf",
            }
        }
    )

    result = await _build_context(
        "What causes defect X?",
        QueryParam(retrieval_strategy="combined"),
        graph,
        text_chunks,
    )

    assert result is not None
    assert "references: [1]" in result.context
    assert result.raw_data["data"]["references"] == [
        {"reference_id": "1", "file_path": "defects.pdf"}
    ]
    assert result.raw_data["data"]["chunks"] == [
        {
            "chunk_id": "chunk-coating",
            "content": "Uneven coating causes Defect X.",
            "file_path": "defects.pdf",
            "reference_id": "1",
        }
    ]
    path_diagnostic = result.raw_data["metadata"]["directed_paths"]["paths"][0]
    assert path_diagnostic["reference_ids"] == ["1"]
    assert path_diagnostic["unresolved_source_ids"] == []


@pytest.mark.asyncio
@pytest.mark.offline
async def test_directed_route_returns_a_clear_path_only_context_when_no_path_exists(monkeypatch):
    _patch_context_dependencies(monkeypatch)
    graph = _DirectedGraph({"Defect X": []})

    result = await _build_context(
        "Explain defect X.",
        QueryParam(retrieval_strategy="directed"),
        graph,
    )

    assert result is not None
    assert result.context == (
        "Directed Evidence Paths:\n"
        "No usable directed evidence paths were found (no matching paths)."
    )
    diagnostics = result.raw_data["metadata"]["directed_paths"]
    assert diagnostics["status"] == "completed"
    assert diagnostics["reason"] == "no_matching_paths"


@pytest.mark.asyncio
@pytest.mark.offline
async def test_combined_route_falls_back_to_normal_context_when_provider_fails(monkeypatch):
    _patch_context_dependencies(monkeypatch)
    graph = _DirectedGraph({}, error=OSError("Neo4j unavailable"))

    result = await _build_context(
        "What causes defect X?",
        QueryParam(retrieval_strategy="combined"),
        graph,
    )

    assert result is not None
    assert result.context == "stable context"
    diagnostics = result.raw_data["metadata"]["directed_paths"]
    assert diagnostics["status"] == "error"
    assert diagnostics["reason"] == "provider_error"
