import pytest

from lightrag.adaptive_retrieval import route_retrieval_query
from lightrag.base import QueryParam
from lightrag.directed_retrieval import (
    edge_matches_traversal,
    normalize_directed_edge,
    normalize_directionality,
    normalize_relation_type,
    select_directed_edges,
)


@pytest.mark.offline
def test_normalization_prefers_semantic_source_and_target_for_sorted_storage_edges():
    edge = normalize_directed_edge(
        {
            "src_id": "Coating Defect",
            "tgt_id": "Residual Solvent",
            "semantic_src_id": "Residual Solvent",
            "semantic_tgt_id": "Coating Defect",
            "relation_type": "caused by",
            "directionality": "forward",
            "relation_importance": "0.95",
            "chain_role": "root cause",
            "weight": 2.5,
        }
    )

    assert edge is not None
    assert edge.source == "Residual Solvent"
    assert edge.target == "Coating Defect"
    assert edge.relation_type == "causes"
    assert edge.directionality == "directed"
    assert edge.relation_importance == pytest.approx(0.95)
    assert edge.chain_role == "root_cause"
    assert edge.weight == pytest.approx(2.5)


@pytest.mark.offline
def test_normalization_keeps_legacy_edges_compatible():
    edge = normalize_directed_edge(
        {
            "src_id": "Thermal Runaway",
            "tgt_id": "Thermal Propagation",
            "keywords": "causes, safety event",
        }
    )

    assert edge is not None
    assert edge.directionality == "unknown"
    assert edge.relation_type == "causes"
    assert edge.relation_importance == pytest.approx(0.5)
    assert edge.chain_role == "other"


@pytest.mark.offline
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("bidirectional", "undirected"),
        ("forward", "directed"),
        (None, "unknown"),
        ("not applicable", "unknown"),
    ],
)
def test_directionality_normalization(value, expected):
    assert normalize_directionality(value) == expected


@pytest.mark.offline
def test_relation_type_normalization_uses_canonical_aliases_and_keywords():
    assert normalize_relation_type("results in") == "results_in"
    assert normalize_relation_type(None, keywords="uses, material input") == "uses"
    assert normalize_relation_type(None) == "related_to"


@pytest.mark.offline
def test_directed_edge_respects_anchor_and_requested_direction():
    edge = normalize_directed_edge(
        {
            "semantic_src_id": "Electrode Stacking",
            "semantic_tgt_id": "Electrode Thickness",
            "relation_type": "influences",
            "directionality": "directed",
        }
    )
    assert edge is not None

    assert edge_matches_traversal(edge, anchor="Electrode Stacking", direction="out")
    assert not edge_matches_traversal(edge, anchor="Electrode Stacking", direction="in")
    assert edge_matches_traversal(edge, anchor="Electrode Thickness", direction="in")
    assert not edge_matches_traversal(edge, anchor="Electrode Thickness", direction="out")


@pytest.mark.offline
def test_unknown_edge_can_be_traversed_in_both_directions_for_compatibility():
    edge = normalize_directed_edge(
        {
            "src_id": "Electrode Stacking",
            "tgt_id": "Electrode Thickness",
            "keywords": "influences",
        }
    )
    assert edge is not None

    assert edge_matches_traversal(edge, anchor="Electrode Stacking", direction="out")
    assert edge_matches_traversal(edge, anchor="Electrode Thickness", direction="in")


@pytest.mark.offline
def test_selection_filters_generic_and_low_importance_edges_and_ranks_matches():
    route = route_retrieval_query(
        "What causes defect X?", QueryParam(retrieval_strategy="auto")
    )
    query_param = QueryParam(
        retrieval_strategy="auto",
        min_relation_importance=0.6,
        chain_fanout=10,
    )

    edges = select_directed_edges(
        [
            {
                "semantic_src_id": "Residual Solvent",
                "semantic_tgt_id": "Defect X",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.91,
            },
            {
                "semantic_src_id": "Coating Thickness",
                "semantic_tgt_id": "Defect X",
                "relation_type": "affects",
                "directionality": "unknown",
                "relation_importance": 0.92,
            },
            {
                "semantic_src_id": "Document Topic",
                "semantic_tgt_id": "Defect X",
                "relation_type": "related_to",
                "directionality": "directed",
                "relation_importance": 1.0,
            },
            {
                "semantic_src_id": "Low Confidence Cause",
                "semantic_tgt_id": "Defect X",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.2,
            },
            {
                "semantic_src_id": "Material",
                "semantic_tgt_id": "Defect X",
                "relation_type": "uses",
                "directionality": "directed",
                "relation_importance": 0.99,
            },
        ],
        anchor="Defect X",
        route=route,
        query_param=query_param,
    )

    assert [(edge.source, edge.relation_type) for edge in edges] == [
        ("Residual Solvent", "causes"),
        ("Coating Thickness", "affects"),
    ]


@pytest.mark.offline
def test_selection_applies_chain_fanout_after_stable_ranking():
    route = route_retrieval_query(
        "What causes defect X?", QueryParam(retrieval_strategy="auto")
    )
    query_param = QueryParam(retrieval_strategy="auto", chain_fanout=1)

    edges = select_directed_edges(
        [
            {
                "semantic_src_id": "Lower Importance Cause",
                "semantic_tgt_id": "Defect X",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.7,
            },
            {
                "semantic_src_id": "Higher Importance Cause",
                "semantic_tgt_id": "Defect X",
                "relation_type": "causes",
                "directionality": "directed",
                "relation_importance": 0.9,
            },
        ],
        anchor="Defect X",
        route=route,
        query_param=query_param,
    )

    assert [edge.source for edge in edges] == ["Higher Importance Cause"]
