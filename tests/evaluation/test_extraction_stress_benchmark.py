"""Structural and negative-control checks for the synthetic extraction corpus."""

import json
from pathlib import Path

import pytest

from lightrag.evaluation.live_benchmark import (
    benchmark_document_preflight,
    load_benchmark_file,
    score_graph_cases,
)
from scripts.evaluate_extraction_stress import inspect_artifact


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "evaluation/benchmarks/pem_extraction_stress_v1.json"
DOCUMENTS = ROOT / "test_documents/extraction_stress"


@pytest.mark.offline
def test_stress_gold_is_grounded_in_nine_isolated_one_chunk_sources():
    benchmark = load_benchmark_file(BENCHMARK)
    cases = benchmark["cases"]
    scope = {item["id"]: item["file"] for item in benchmark["document_scope"]}

    assert len(cases) == len(scope) == 9
    assert len({case["id"] for case in cases}) == len(cases)
    assert {path.name for path in DOCUMENTS.glob("*.txt")} == set(scope.values())
    assert benchmark_document_preflight(benchmark, list(scope.values()))["compatible"]
    assert not benchmark_document_preflight(benchmark, list(scope.values())[1:])["compatible"]

    for case in cases:
        text = (DOCUMENTS / scope[case["source_document"]]).read_text(
            encoding="utf-8"
        )
        assert 20 < len(text.split()) < 200
        assert case["title"] and not case["question"]
        assert case["expected_relations"] and case["forbidden_relations"]
        evidence = {item["id"]: item for item in case["evidence"]}
        for item in evidence.values():
            assert item["anchor"].casefold() in text.casefold()
        for relation in case["expected_relations"]:
            assert relation["directionality"] == "directed"
            assert relation["source"] != relation["target"]
            assert set(relation["evidence_ids"]) <= evidence.keys()
        for forbidden in case["forbidden_relations"]:
            assert forbidden["reason"]
            assert not any(
                (forbidden["source"], forbidden["relation_type"], forbidden["target"])
                == (relation["source"], relation["relation_type"], relation["target"])
                for relation in case["expected_relations"]
            )


@pytest.mark.offline
def test_every_gold_case_is_scorable_with_an_ideal_isolated_graph():
    benchmark = load_benchmark_file(BENCHMARK)
    for case in benchmark["cases"]:
        nodes = [
            {"entity_id": value["name"] if isinstance(value, dict) else value}
            for value in case["expected_entities"]
        ]
        edges = [
            {
                "semantic_src_id": relation["source"],
                "semantic_tgt_id": relation["target"],
                "relation_type": relation["relation_type"],
                "directionality": "directed",
            }
            for relation in case["expected_relations"]
        ]
        results, summary = score_graph_cases({"cases": [case]}, nodes, edges)
        assert results[0]["title"] == case["title"]
        assert summary["entity_exact_score"] == 100, case["id"]
        assert summary["relation_exact_score"] == 100, case["id"]


@pytest.mark.offline
def test_forbidden_edge_audit_is_source_scoped_and_catches_reverse_cause():
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    artifact = {
        "documents": [
            {
                "file_path": item["file"],
                "chunk_results": [{"edges": []}],
            }
            for item in benchmark["document_scope"]
        ]
    }
    reverse = {
        "source": "DC Resistance",
        "target": "High-Temperature Storage",
        "records": [
            {
                "semantic_src_id": "DC Resistance",
                "semantic_tgt_id": "High-Temperature Storage",
                "relation_type": "increases",
                "source_id": "chunk-1",
            }
        ],
    }
    artifact["documents"][1]["chunk_results"][0]["edges"].append(reverse)
    assert inspect_artifact(benchmark, artifact)["violations"] == []

    artifact["documents"][0]["chunk_results"][0]["edges"].append(reverse)
    violations = inspect_artifact(benchmark, artifact)["violations"]
    assert len(violations) == 1
    assert violations[0]["case"] == "aging_direction"
    assert violations[0]["assertion"]["source_id"] == "chunk-1"


@pytest.mark.offline
def test_forbidden_edge_audit_rejects_missing_or_duplicate_source_files():
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="Missing selected source document"):
        inspect_artifact(benchmark, {"documents": []})
    with pytest.raises(ValueError, match="Duplicate selected source filename"):
        inspect_artifact(
            benchmark,
            {"documents": [
                {"file_path": "01_aging_direction.txt"},
                {"file_path": "01_aging_direction.txt"},
            ]},
        )


@pytest.mark.offline
def test_ambiguous_referent_causal_variant_is_forbidden():
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    documents = [
        {"file_path": item["file"], "chunk_results": [{"edges": []}]}
        for item in benchmark["document_scope"]
    ]
    documents[2]["chunk_results"][0]["edges"].append(
        {
            "source": "Calendering",
            "target": "Contact Resistance",
            "records": [{"relation_type": "causes", "source_id": "ambiguous-chunk"}],
        }
    )
    violations = inspect_artifact(benchmark, {"documents": documents})["violations"]
    assert len(violations) == 1
    assert violations[0]["case"] == "ambiguous_this"


@pytest.mark.offline
def test_positive_exact_coverage_is_scoped_to_each_document():
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    documents = [
        {"file_path": item["file"], "chunk_results": [{"nodes": [], "edges": []}]}
        for item in benchmark["document_scope"]
    ]
    documents[0]["chunk_results"][0]["nodes"] = [
        {"entity_id": "DC Resistance"}, {"entity_id": "Irreversible Heat"}
    ]
    documents[0]["chunk_results"][0]["edges"] = [
        {
            "source": "DC Resistance", "target": "Irreversible Heat",
            "records": [{"relation_type": "increases", "directionality": "directed"}],
        }
    ]
    report = inspect_artifact(benchmark, {"documents": documents})
    by_id = {case["id"]: case for case in report["cases"]}
    assert by_id["aging_direction"]["relations_found"] == 1
    assert by_id["background_attribution"]["relations_found"] == 0


@pytest.mark.offline
def test_source_scoped_positive_audit_honors_reviewed_inverse_and_alias():
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    documents = [
        {"file_path": item["file"], "chunk_results": [{"nodes": [], "edges": []}]}
        for item in benchmark["document_scope"]
    ]
    documents[3]["chunk_results"][0]["edges"] = [
        {
            "source": "Irreversible Heat", "target": "Total Heat",
            "records": [{"relation_type": "part_of", "directionality": "directed"}],
        },
    ]
    documents[4]["chunk_results"][0]["nodes"] = [{"entity_id": "SEM"}]
    report = inspect_artifact(benchmark, {"documents": documents})
    by_id = {case["id"]: case for case in report["cases"]}
    assert by_id["heat_components"]["relations_found"] == 1
    assert by_id["passive_methods"]["entities_found"] == 1


@pytest.mark.offline
def test_ideal_candidate_artifact_passes_all_positive_and_negative_controls():
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    scope = {item["id"]: item["file"] for item in benchmark["document_scope"]}
    documents = []
    for case in benchmark["cases"]:
        nodes = [
            {"entity_id": value["name"] if isinstance(value, dict) else value}
            for value in case["expected_entities"]
        ]
        edges = [
            {
                "source": relation["source"],
                "target": relation["target"],
                "records": [{
                    "relation_type": relation["relation_type"],
                    "directionality": "directed",
                }],
            }
            for relation in case["expected_relations"]
        ]
        documents.append({
            "file_path": scope[case["source_document"]],
            "chunk_results": [{"nodes": nodes, "edges": edges}],
        })
    report = inspect_artifact(benchmark, {"documents": documents})
    assert report["violations"] == []
    assert all(
        not case["missing_entities"] and not case["missing_relations"]
        for case in report["cases"]
    )
