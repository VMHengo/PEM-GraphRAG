from dataclasses import asdict

import pytest

from lightrag.adaptive_retrieval import (
    CAUSAL_RELATIONS,
    DEPENDENCY_RELATIONS,
    PRODUCTION_RELATIONS,
    PROVENANCE_RELATIONS,
    route_retrieval_query,
)
from lightrag.base import QueryParam


@pytest.mark.offline
@pytest.mark.parametrize(
    ("query", "expected_type"),
    [
        (
            "Welche Ursachen können eine unzureichende Elektrodendicke verursachen?",
            "root_cause",
        ),
        ("What causes defect X?", "root_cause"),
    ],
)
def test_auto_routes_root_cause_queries_inward(query: str, expected_type: str):
    route = route_retrieval_query(query, QueryParam(retrieval_strategy="auto"))

    assert route.query_type == expected_type
    assert route.effective_strategy == "combined"
    assert route.use_normal_retrieval is True
    assert route.use_directed_paths is True
    assert route.edge_direction == "in"
    assert route.target_relation_types == CAUSAL_RELATIONS


@pytest.mark.offline
@pytest.mark.parametrize(
    ("query", "expected_rule"),
    [
        ("Zu welchen Fehlern führt eine unzureichende Elektrodendicke?", "causal_chain"),
        ("Eine unzureichende Elektrodendicke führt zu welchem Fehler?", "causal_chain"),
        ("What can insufficient electrode thickness lead to?", "causal_chain"),
    ],
)
def test_auto_routes_downstream_queries_outward(query: str, expected_rule: str):
    route = route_retrieval_query(query, QueryParam(retrieval_strategy="auto"))

    assert route.matched_rule == expected_rule
    assert route.effective_strategy == "combined"
    assert route.edge_direction == "out"
    assert route.target_relation_types == CAUSAL_RELATIONS


@pytest.mark.offline
def test_auto_routes_production_chain_outward():
    route = route_retrieval_query(
        "Welche Fertigungsschritte umfasst die Produktionskette einer Batteriezelle?",
        QueryParam(retrieval_strategy="auto"),
    )

    assert route.query_type == "production_chain"
    assert route.effective_strategy == "combined"
    assert route.edge_direction == "out"
    assert route.target_relation_types == PRODUCTION_RELATIONS


@pytest.mark.offline
def test_auto_routes_dependency_chain_outward():
    route = route_retrieval_query(
        "Wovon hängt die Elektrodenqualität ab?",
        QueryParam(retrieval_strategy="auto"),
    )

    assert route.query_type == "dependency_chain"
    assert route.effective_strategy == "combined"
    assert route.edge_direction == "out"
    assert route.target_relation_types == DEPENDENCY_RELATIONS


@pytest.mark.offline
def test_auto_routes_provenance_chain_with_both_directions():
    route = route_retrieval_query(
        "Von wem wurde dieses Dokument veröffentlicht?",
        QueryParam(retrieval_strategy="auto"),
    )

    assert route.query_type == "provenance_chain"
    assert route.effective_strategy == "combined"
    assert route.edge_direction == "both"
    assert route.target_relation_types == PROVENANCE_RELATIONS


@pytest.mark.offline
@pytest.mark.parametrize(
    "query",
    [
        "Explain PEM electrolysis.",
        "Was ist eine Lithium-Ionen-Batteriezelle?",
        "Vergleiche die Zellchemien NMC und LFP.",
    ],
)
def test_auto_keeps_general_and_comparison_queries_on_normal_retrieval(query: str):
    route = route_retrieval_query(query, QueryParam(retrieval_strategy="auto"))

    assert route.effective_strategy == "normal"
    assert route.use_normal_retrieval is True
    assert route.use_directed_paths is False
    assert route.edge_direction == "both"


@pytest.mark.offline
def test_explicit_normal_strategy_overrides_auto_routing():
    route = route_retrieval_query(
        "What causes defect X?", QueryParam(retrieval_strategy="normal")
    )

    assert route.query_type == "root_cause"
    assert route.effective_strategy == "normal"
    assert route.use_normal_retrieval is True
    assert route.use_directed_paths is False


@pytest.mark.offline
def test_explicit_directed_strategy_disables_normal_retrieval():
    route = route_retrieval_query(
        "What causes defect X?", QueryParam(retrieval_strategy="directed")
    )

    assert route.effective_strategy == "directed"
    assert route.use_normal_retrieval is False
    assert route.use_directed_paths is True


@pytest.mark.offline
def test_explicit_edge_direction_overrides_inferred_direction():
    route = route_retrieval_query(
        "What causes defect X?",
        QueryParam(retrieval_strategy="auto", edge_direction="out"),
    )

    assert route.query_type == "root_cause"
    assert route.edge_direction == "out"


@pytest.mark.offline
def test_root_cause_rule_has_priority_over_downstream_words():
    route = route_retrieval_query(
        "Welche Ursachen führen zu Defect X?", QueryParam(retrieval_strategy="auto")
    )

    assert route.query_type == "root_cause"
    assert route.edge_direction == "in"


@pytest.mark.offline
def test_router_does_not_mutate_query_param():
    param = QueryParam(retrieval_strategy="auto", edge_direction="both")
    before = asdict(param)

    route_retrieval_query("What causes defect X?", param)

    assert asdict(param) == before
