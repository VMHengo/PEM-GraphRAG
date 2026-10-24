"""Structural checks for the single-paper aging benchmark gold data."""

from pathlib import Path

from lightrag.adaptive_retrieval import route_retrieval_query
from lightrag.base import QueryParam
from lightrag.evaluation.live_benchmark import load_benchmark_file


BENCHMARK_PATH = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "benchmarks"
    / "pem_high_temperature_aging_benchmark.json"
)


def test_aging_benchmark_has_evidence_for_each_case_and_relation():
    benchmark = load_benchmark_file(BENCHMARK_PATH)
    cases = benchmark["cases"]
    assert len(cases) == 38
    assert len({case["id"] for case in cases}) == len(cases)
    assert "boundary_scope_and_gas" not in {case["id"] for case in cases}

    for case in cases:
        assert case["question"].strip()
        assert case["expected_documents"]
        evidence = {span["id"]: span for span in case["evidence"]}
        assert evidence
        assert len(evidence) == len(case["evidence"])
        for span in evidence.values():
            assert span["document"] == "aging"
            assert 1 <= span["page"] <= 10
            assert span["anchor"] and span["support"]
        for relation in case["expected_relations"]:
            assert relation["source"] != relation["target"]
            assert set(relation["evidence_ids"]) <= evidence.keys()
        for path in case["expected_directed_paths"]:
            nodes = path.get("traversal_nodes") or path.get("nodes")
            assert len(nodes) == len(path["relation_types"]) + 1
            assert len(path["relation_types"]) <= case["hop_depth"]


def test_new_aging_chains_route_to_combined():
    benchmark = load_benchmark_file(BENCHMARK_PATH)
    cases = {case["id"]: case for case in benchmark["cases"]}
    for case_id in (
        "causal_gas_spacing_current_plating",
        "causal_consumption_drying_current",
    ):
        route = route_retrieval_query(
            cases[case_id]["question"], QueryParam(retrieval_strategy="auto")
        )
        assert route.effective_strategy == "combined"
        assert route.edge_direction == "out"


def test_all_aging_chain_questions_use_the_expected_auto_direction():
    benchmark = load_benchmark_file(BENCHMARK_PATH)
    for case in benchmark["cases"]:
        if not case.get("expected_directed_paths"):
            continue
        route = route_retrieval_query(
            case["question"], QueryParam(retrieval_strategy="auto")
        )
        assert route.effective_strategy == case["expected_auto_strategy"], case["id"]
        assert route.edge_direction == case["expected_edge_direction"], case["id"]
