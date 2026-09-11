from types import SimpleNamespace

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


async def _build_context(query: str, query_param: QueryParam):
    return await operate._build_query_context(
        query=query,
        ll_keywords="defect",
        hl_keywords="",
        knowledge_graph_inst=object(),
        entities_vdb=object(),
        relationships_vdb=object(),
        text_chunks_db=SimpleNamespace(global_config={}),
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


@pytest.mark.asyncio
@pytest.mark.offline
async def test_route_metadata_does_not_change_existing_retrieval_inputs(monkeypatch):
    calls = _patch_context_dependencies(monkeypatch)
    query_param = QueryParam(retrieval_strategy="normal")

    result = await _build_context("What causes defect X?", query_param)

    assert result is not None
    assert result.context == "stable context"
    assert calls["search_params"] == [query_param]
    route = result.raw_data["metadata"]["retrieval_route"]
    assert route["effective_strategy"] == "normal"
    assert route["use_directed_paths"] is False
