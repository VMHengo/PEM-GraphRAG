"""Structural quality checks for the reviewed three-document benchmark."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from lightrag import QueryParam
from lightrag.adaptive_retrieval import (
    CAUSAL_RELATIONS,
    PRODUCTION_RELATIONS,
    route_retrieval_query,
)
from lightrag.evaluation.live_benchmark import load_benchmark_file


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = (
    REPO_ROOT
    / "evaluation"
    / "benchmarks"
    / "pem_three_document_multihop_quality.json"
)

EXPECTED_DOCUMENTS = {
    "Komponentenherstellung+einer+Lithium-Ionen-Batteriezelle+2023+(ENG).pdf",
    "Production+of+a+Solid-State+Battery+Cell+(2026-03).pdf",
    "Production+Process+of+Battery+Modules+and+Battery+Packs+(2026-03).pdf",
}


def _load_raw_benchmark() -> dict:
    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def test_benchmark_loads_with_unique_balanced_cases():
    benchmark = load_benchmark_file(BENCHMARK_PATH)
    cases = benchmark["cases"]

    assert benchmark["id"] == "pem_three_document_multihop_quality"
    assert benchmark["version"] == 2
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == len(cases)

    document_counts = Counter(
        document
        for case in cases
        for document in case.get("expected_documents", [])
    )
    assert set(document_counts) == EXPECTED_DOCUMENTS
    assert all(count >= 5 for count in document_counts.values())
    assert sum(len(case["expected_documents"]) == 1 for case in cases) == 15
    assert sum(len(case["expected_documents"]) > 1 for case in cases) == 5


def test_every_case_is_a_grounded_multihop_acceptance_case():
    cases = _load_raw_benchmark()["cases"]

    for case in cases:
        assert case["question"].strip(), case["id"]
        assert case["category"] in {
            "root_cause",
            "causal_chain",
            "production_chain",
        }, case["id"]
        assert case["hop_depth"] == 3, case["id"]
        assert case["expected_auto_strategy"] == "combined", case["id"]
        assert case["expected_edge_direction"] in {"in", "out"}, case["id"]
        assert len(case["expected_entities"]) >= 3, case["id"]
        assert len(case["expected_relations"]) >= 2, case["id"]
        assert len(case["must_include"]) >= 4, case["id"]
        assert 1 <= len(case["expected_documents"]) <= 3, case["id"]
        assert case["expected_directed_paths"], case["id"]
        assert case["evidence"]["pages"], case["id"]
        assert len(case["evidence"]["rationale"]) >= 80, case["id"]

        for relation in case["expected_relations"]:
            assert relation["source"], case["id"]
            assert relation["target"], case["id"]
            assert relation["relation_type"], case["id"]
            assert relation["directionality"] == "directed", case["id"]


def test_directed_paths_are_bounded_ordered_citable_and_route_compatible():
    cases = _load_raw_benchmark()["cases"]

    for case in cases:
        allowed_types = (
            set(PRODUCTION_RELATIONS)
            if case["category"] == "production_chain"
            else set(CAUSAL_RELATIONS)
        )

        cited_documents: set[str] = set()
        expected_documents = set(case["expected_documents"])
        for path in case["expected_directed_paths"]:
            nodes = path.get("traversal_nodes") or path.get("nodes")
            relation_types = path["relation_types"]

            assert 3 <= len(nodes) <= 4, case["id"]
            assert len(relation_types) == len(nodes) - 1, case["id"]
            assert set(relation_types) <= allowed_types, case["id"]
            assert path["source_documents"], case["id"]
            assert set(path["source_documents"]) <= expected_documents, case["id"]
            assert path["require_citations"] is True, case["id"]
            cited_documents.update(path["source_documents"])

        assert cited_documents == expected_documents, case["id"]

        if case["category"] == "root_cause":
            assert case["expected_edge_direction"] == "in", case["id"]
            assert all(
                "traversal_nodes" in path
                for path in case["expected_directed_paths"]
            ), case["id"]
        else:
            assert case["expected_edge_direction"] == "out", case["id"]


def test_auto_router_activates_the_declared_directed_strategy():
    cases = _load_raw_benchmark()["cases"]

    for case in cases:
        route = route_retrieval_query(
            case["question"],
            QueryParam(retrieval_strategy="auto"),
        )

        assert route.effective_strategy == case["expected_auto_strategy"], case["id"]
        assert route.edge_direction == case["expected_edge_direction"], case["id"]
        assert route.use_directed_paths is True, case["id"]


def test_benchmark_has_cross_page_branching_and_multilingual_challenges():
    cases = _load_raw_benchmark()["cases"]

    assert sum(len(case["expected_directed_paths"]) for case in cases) >= 30
    assert sum(len(case["evidence"]["pages"]) > 1 for case in cases) >= 4
    assert sum(len(case["expected_directed_paths"]) > 1 for case in cases) >= 7
    assert sum(len(case["expected_documents"]) > 1 for case in cases) == 5
    assert any(len(case["expected_documents"]) == 3 for case in cases)
    assert sum(
        any(token in case["question"] for token in ("Welche", "Prozesskette"))
        for case in cases
    ) >= 3


def test_quality_gates_cover_all_live_benchmark_dimensions():
    gates = _load_raw_benchmark()["quality_gates"]

    assert set(gates["min_scores"]) == {
        "overall",
        "graph",
        "metadata",
        "retrieval",
        "directed",
    }
    assert set(gates["min_metadata_coverage"]) == {
        "directionality",
        "relation_type",
        "relation_importance",
        "chain_role",
        "specific_relation_type",
    }
    assert set(gates["min_directed_strategy_scores"]) == {
        "directed",
        "combined",
        "auto",
    }
    assert gates["require_directed_cases"] is True
