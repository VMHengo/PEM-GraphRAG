from collections.abc import Sequence
from typing import Any

import pytest

from lightrag.adaptive_retrieval import route_retrieval_query
from lightrag.base import QueryParam
from lightrag.directed_retrieval import find_directed_paths


def _route(query: str, query_param: QueryParam):
    return route_retrieval_query(query, query_param)


@pytest.mark.asyncio
@pytest.mark.offline
async def test_normal_route_does_not_call_neighbor_provider():
    async def unexpected_provider(nodes: Sequence[str]):
        raise AssertionError(f"provider must not be called for normal routing: {nodes}")

    query_param = QueryParam(retrieval_strategy="normal")
    paths = await find_directed_paths(
        ["Defect X"],
        unexpected_provider,
        route=_route("What causes defect X?", query_param),
        query_param=query_param,
    )

    assert paths == []


@pytest.mark.asyncio
@pytest.mark.offline
async def test_outgoing_bfs_returns_a_two_hop_causal_chain_and_batches_frontiers():
    calls: list[tuple[str, ...]] = []
    graph: dict[str, list[dict[str, Any]]] = {
        "Process Instability": [
            {
                "semantic_src_id": "Process Instability",
                "semantic_tgt_id": "Uneven Coating",
                "relation_type": "influences",
                "directionality": "directed",
                "relation_importance": 0.9,
                "source_id": "chunk-1",
                "file_path": "coating.pdf",
            }
        ],
        "Uneven Coating": [
            {
                "semantic_src_id": "Uneven Coating",
                "semantic_tgt_id": "Defect X",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.95,
                "source_id": "chunk-2",
                "file_path": "defects.pdf",
            }
        ],
    }

    async def provider(nodes: Sequence[str]):
        calls.append(tuple(nodes))
        return {node: graph.get(node, []) for node in nodes}

    query_param = QueryParam(retrieval_strategy="auto", hop_depth=2)
    paths = await find_directed_paths(
        ["Process Instability"],
        provider,
        route=_route("What can process instability lead to?", query_param),
        query_param=query_param,
    )

    two_hop = next(path for path in paths if len(path.edges) == 2)
    assert two_hop.nodes == ("Process Instability", "Uneven Coating", "Defect X")
    assert two_hop.source_ids == ("chunk-1", "chunk-2")
    assert two_hop.file_paths == ("coating.pdf", "defects.pdf")
    assert calls == [("Process Instability",), ("Uneven Coating",)]


@pytest.mark.asyncio
@pytest.mark.offline
async def test_incoming_bfs_traces_a_root_cause_chain_in_reverse_semantic_order():
    graph: dict[str, list[dict[str, Any]]] = {
        "Defect X": [
            {
                "semantic_src_id": "Uneven Coating",
                "semantic_tgt_id": "Defect X",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.9,
            }
        ],
        "Uneven Coating": [
            {
                "semantic_src_id": "Process Instability",
                "semantic_tgt_id": "Uneven Coating",
                "relation_type": "influences",
                "directionality": "directed",
                "relation_importance": 0.9,
            }
        ],
    }

    async def provider(nodes: Sequence[str]):
        return {node: graph.get(node, []) for node in nodes}

    query_param = QueryParam(retrieval_strategy="auto", hop_depth=2)
    paths = await find_directed_paths(
        ["Defect X"],
        provider,
        route=_route("What causes defect X?", query_param),
        query_param=query_param,
    )

    two_hop = next(path for path in paths if len(path.edges) == 2)
    assert two_hop.nodes == ("Defect X", "Uneven Coating", "Process Instability")
    assert [edge.relation_type for edge in two_hop.edges] == ["causes", "influences"]


@pytest.mark.asyncio
@pytest.mark.offline
async def test_unknown_edges_remain_traversable_for_backward_compatibility():
    async def provider(nodes: Sequence[str]):
        return {
            "Defect X": [
                {
                    "src_id": "Legacy Process Parameter",
                    "tgt_id": "Defect X",
                    "keywords": "causes",
                    "relation_importance": 0.8,
                }
            ]
            for node in nodes
        }

    query_param = QueryParam(retrieval_strategy="auto")
    paths = await find_directed_paths(
        ["Defect X"],
        provider,
        route=_route("What causes defect X?", query_param),
        query_param=query_param,
    )

    assert [path.nodes for path in paths] == [
        ("Defect X", "Legacy Process Parameter")
    ]


@pytest.mark.asyncio
@pytest.mark.offline
async def test_bfs_prevents_cycles_and_respects_fanout_and_path_limits():
    graph: dict[str, list[dict[str, Any]]] = {
        "A": [
            {
                "semantic_src_id": "A",
                "semantic_tgt_id": "B",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.95,
            },
            {
                "semantic_src_id": "A",
                "semantic_tgt_id": "C",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.8,
            },
        ],
        "B": [
            {
                "semantic_src_id": "B",
                "semantic_tgt_id": "A",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.99,
            },
            {
                "semantic_src_id": "B",
                "semantic_tgt_id": "D",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.9,
            },
        ],
    }

    async def provider(nodes: Sequence[str]):
        return {node: graph.get(node, []) for node in nodes}

    query_param = QueryParam(
        retrieval_strategy="auto",
        hop_depth=3,
        chain_fanout=1,
        chain_top_k=2,
    )
    paths = await find_directed_paths(
        ["A"],
        provider,
        route=_route("What can A lead to?", query_param),
        query_param=query_param,
    )

    assert len(paths) <= 2
    assert all(len(path.edges) <= 3 for path in paths)
    assert all(len({node.casefold() for node in path.nodes}) == len(path.nodes) for path in paths)
    assert all(path.nodes[1] == "B" for path in paths)
    assert ("A", "B", "D") in [path.nodes for path in paths]
