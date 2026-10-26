import pytest

from lightrag.adaptive_retrieval import route_retrieval_query
from lightrag.base import QueryParam
from lightrag.directed_retrieval import find_directed_paths, select_directed_edges


def _record(source, target, predicate="causes", importance=0.9):
    return {
        "semantic_src_id": source,
        "semantic_tgt_id": target,
        "relation_type": predicate,
        "directionality": "directed",
        "relation_importance": importance,
        "source_id": "chunk-1",
    }


@pytest.mark.offline
def test_selection_counters_do_not_change_ranked_edges():
    param = QueryParam(
        retrieval_strategy="directed", min_relation_importance=0.6, chain_fanout=1
    )
    route = route_retrieval_query("What causes Defect X?", param)
    records = [
        _record("A", "Defect X", importance=0.2),
        _record("B", "Defect X", predicate="uses"),
        _record("Defect X", "C"),
        _record("D", "Defect X"),
        _record("E", "Defect X"),
    ]
    counters = {}
    expected = select_directed_edges(
        records, anchor="Defect X", route=route, query_param=param
    )
    actual = select_directed_edges(
        records,
        anchor="Defect X",
        route=route,
        query_param=param,
        diagnostics=counters,
    )
    assert actual == expected
    assert counters == {
        "record_evaluations": 5,
        "below_importance": 1,
        "predicate_rejected": 1,
        "direction_rejected": 1,
        "eligible_edges": 2,
        "fanout_rejected": 1,
    }


@pytest.mark.asyncio
@pytest.mark.offline
async def test_bfs_counters_expose_provider_fanout_and_beam_without_extra_calls():
    calls = []

    async def provider(nodes):
        calls.append(tuple(nodes))
        return {"A": [_record("A", "B"), _record("A", "C")]}

    param = QueryParam(
        retrieval_strategy="directed", hop_depth=1, chain_fanout=2, chain_top_k=1
    )
    counters = {}
    paths = await find_directed_paths(
        ["A", "A"],
        provider,
        route=route_retrieval_query("What can A cause?", param),
        query_param=param,
        diagnostics=counters,
        provider_candidate_limit=2,
    )
    assert len(paths) == 1
    assert calls == [("A",)]
    assert counters["anchors_requested"] == 2
    assert counters["anchors_unique"] == 1
    level = counters["levels"][0]
    assert level["provider_records"] == 2
    assert level["provider_nodes_at_cap"] == 1
    assert level["selection"]["eligible_edges"] == 2
    assert level["expanded_paths"] == 2
    assert level["beam_rejected"] == 1
    assert level["surviving_paths"] == 1
