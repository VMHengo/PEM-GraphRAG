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
async def test_weakest_link_ranking_prefers_supported_balanced_chain():
    graph = {
        "A": [
            {"semantic_src_id": "A", "semantic_tgt_id": "B", "relation_type": "causes",
             "directionality": "directed", "relation_importance": 1.0, "source_id": "chunk-ab"},
            {"semantic_src_id": "A", "semantic_tgt_id": "D", "relation_type": "causes",
             "directionality": "directed", "relation_importance": 0.78, "source_id": "chunk-ad"},
        ],
        "B": [{"semantic_src_id": "B", "semantic_tgt_id": "C", "relation_type": "causes",
               "directionality": "directed", "relation_importance": 0.6}],
        "D": [{"semantic_src_id": "D", "semantic_tgt_id": "E", "relation_type": "causes",
               "directionality": "directed", "relation_importance": 0.78,
               "source_id": "chunk-de"}],
    }

    async def provider(nodes):
        return {node: graph.get(node, []) for node in nodes}

    async def ranked(mode):
        param = QueryParam(retrieval_strategy="auto", hop_depth=2,
                           path_ranking_mode=mode, chain_top_k=10)
        paths = await find_directed_paths(
            ["A"], provider, route=_route("What can A lead to?", param), query_param=param
        )
        return [path.nodes for path in paths if len(path.edges) == 2]

    assert (await ranked("mean"))[0] == ("A", "B", "C")
    assert (await ranked("weakest_link"))[0] == ("A", "D", "E")


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
async def test_causal_bfs_traverses_increases_but_not_unrelated_predicates():
    graph = {
        "Cell Aging": [
            {
                "semantic_src_id": "Cell Aging",
                "semantic_tgt_id": "Resistance",
                "relation_type": "increases",
                "directionality": "directed",
                "relation_importance": 0.9,
            },
            {
                "semantic_src_id": "Cell Aging",
                "semantic_tgt_id": "Paper",
                "relation_type": "published_by",
                "directionality": "directed",
                "relation_importance": 0.9,
            },
        ],
        "Resistance": [
            {
                "semantic_src_id": "Resistance",
                "semantic_tgt_id": "Irreversible Heat",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.9,
            }
        ],
    }

    async def provider(nodes: Sequence[str]):
        return {node: graph.get(node, []) for node in nodes}

    param = QueryParam(retrieval_strategy="auto", hop_depth=2)
    paths = await find_directed_paths(
        ["Cell Aging"],
        provider,
        route=_route("What can cell aging lead to?", param),
        query_param=param,
    )

    assert any(
        path.nodes == ("Cell Aging", "Resistance", "Irreversible Heat")
        for path in paths
    )
    assert all("Paper" not in path.nodes for path in paths)


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


@pytest.mark.asyncio
@pytest.mark.offline
async def test_top_k_keeps_short_and_long_causal_evidence():
    graph = {
        "A": [
            {"semantic_src_id": "A", "semantic_tgt_id": "B", "relation_type": "causes",
             "directionality": "directed", "relation_importance": 0.95},
            {"semantic_src_id": "A", "semantic_tgt_id": "Noise", "relation_type": "causes",
             "directionality": "directed", "relation_importance": 0.99},
        ],
        "B": [{"semantic_src_id": "B", "semantic_tgt_id": "C", "relation_type": "causes",
               "directionality": "directed", "relation_importance": 0.9}],
        "C": [{"semantic_src_id": "C", "semantic_tgt_id": "D", "relation_type": "causes",
               "directionality": "directed", "relation_importance": 0.85}],
    }

    async def provider(nodes):
        return {node: graph.get(node, []) for node in nodes}

    param = QueryParam(retrieval_strategy="directed", edge_direction="out",
                       hop_depth=3, chain_top_k=2)
    paths = await find_directed_paths(
        ["A"], provider, route=_route("What can A lead to?", param), query_param=param
    )

    assert len(paths) == 2
    assert {len(path.edges) for path in paths} == {1, 3}
    assert paths[0].nodes == ("A", "B", "C", "D")


@pytest.mark.asyncio
@pytest.mark.offline
async def test_five_hops_are_bounded_but_available():
    graph = {
        source: [{"semantic_src_id": source, "semantic_tgt_id": target,
                  "relation_type": "causes", "directionality": "directed",
                  "relation_importance": 0.9}]
        for source, target in zip("ABCDE", "BCDEF")
    }

    async def provider(nodes):
        return {node: graph.get(node, []) for node in nodes}

    param = QueryParam(retrieval_strategy="directed", hop_depth=5, chain_top_k=5)
    paths = await find_directed_paths(
        ["A"], provider, route=_route("What can A lead to?", param), query_param=param
    )

    assert len(paths) == 5
    assert paths[0].nodes == tuple("ABCDEF")
    assert {len(path.edges) for path in paths} == {1, 2, 3, 4, 5}


@pytest.mark.asyncio
@pytest.mark.offline
async def test_query_focus_keeps_a_three_hop_chain_among_distractors():
    names = (
        "Electrolyte Decomposition", "Gas Generation",
        "Local Current Nonuniformity", "Lithium Plating",
    )
    graph = {
        source: [{"semantic_src_id": source, "semantic_tgt_id": target,
                  "relation_type": "causes", "directionality": "directed",
                  "relation_importance": 0.85}]
        for source, target in zip(names, names[1:])
    }
    graph["High-Temperature Aging"] = [
        {"semantic_src_id": "High-Temperature Aging", "semantic_tgt_id": f"Other {i}",
         "relation_type": "causes", "directionality": "directed",
         "relation_importance": 0.99}
        for i in range(8)
    ]

    async def provider(nodes):
        return {node: graph.get(node, []) for node in nodes}

    param = QueryParam(retrieval_strategy="auto", hop_depth=3,
                       chain_top_k=6, chain_fanout=10)
    paths = await find_directed_paths(
        [names[0], "High-Temperature Aging"], provider,
        route=_route("How can electrolyte decomposition cause plating?", param),
        query_param=param, focus_entities=names,
    )

    assert names in [path.nodes for path in paths]
    assert {len(path.edges) for path in paths} == {1, 2, 3}
