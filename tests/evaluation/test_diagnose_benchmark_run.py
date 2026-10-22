"""Offline triage must not confuse retrieval failure with absent graph facts."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "diagnose_benchmark_run.py"
_SPEC = importlib.util.spec_from_file_location("diagnose_benchmark_run", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_diagnose_distinguishes_graph_and_path_triage():
    result = {
        "benchmark": {"id": "sample"},
        "run": {"generated_at": "2026-10-22T00:00:00Z"},
        "cases": {
            "graph": [
                {
                    "id": "missing_edge",
                    "entity_score": 100,
                    "relation_score": 20,
                    "relation_checks": [
                        {
                            "passed": False,
                            "score": 30,
                            "expected": {
                                "source": "A",
                                "relation_type": "causes",
                                "target": "B",
                            },
                        }
                    ],
                },
                {
                    "id": "missed_path",
                    "entity_score": 100,
                    "relation_score": 90,
                    "relation_checks": [],
                },
            ],
            "directed": [
                {
                    "id": "missing_edge",
                    "strategies": [
                        {"strategy": "directed", "score": 0, "path_count": 0}
                    ],
                },
                {
                    "id": "missed_path",
                    "strategies": [
                        {"strategy": "directed", "score": 10, "path_count": 5}
                    ],
                },
            ],
        },
    }

    report = _MODULE.diagnose_run(result)
    cases = {case["id"]: case for case in report["cases"]}
    assert report["benchmark_id"] == "sample"
    assert (
        cases["missing_edge"]["next_check"]
        == "inspect_expected_edges_and_source_evidence"
    )
    assert cases["missing_edge"]["non_exact_expected_edges"][0]["partial_score"] == 30
    assert (
        cases["missed_path"]["next_check"]
        == "inspect_path_anchors_and_retrieval_filters"
    )
    assert cases["missed_path"]["path_count"] == 5


def test_diagnose_handles_legacy_or_partial_result():
    report = _MODULE.diagnose_run({"cases": {"graph": [{"id": "old"}]}})
    assert report["cases"][0]["next_check"] == "review_answer_grounding"
    assert report["cases"][0]["directed_score"] is None


def test_diagnose_keeps_graph_absence_unverified_and_links_evidence():
    result = {
        "benchmark": {"id": "quality"},
        "cases": {
            "graph": [
                {
                    "id": "case-1",
                    "relation_checks": [{"passed": False, "expected": {"source": "A"}}],
                }
            ],
            "directed": [],
        },
    }
    fixture = {
        "version": 2,
        "document_scope": [{"file": "paper.pdf"}],
        "cases": [
            {
                "id": "case-1",
                "evidence": [
                    {"document": "paper.pdf", "page": 4, "anchor": "local current"}
                ],
            }
        ],
    }
    report = _MODULE.diagnose_run(
        result,
        metadata={"extraction_revision": {"version": "1.0.1"}},
        benchmark=fixture,
    )
    assert report["classification_counts"] == {"graph_assertion_unverified": 1}
    assert report["cases"][0]["source_evidence"][0]["page"] == 4
    assert report["extraction_revision"] == {"version": "1.0.1"}
    assert report["document_scope"] == [{"file": "paper.pdf"}]


def test_diagnose_strict_only_and_provenance_are_not_conflated():
    result = {
        "cases": {
            "directed": [
                {
                    "id": "strict",
                    "strategies": [
                        {
                            "strategy": "directed",
                            "checks": [
                                {
                                    "kind": "expected_path",
                                    "passed": False,
                                    "partial": {
                                        "score": 1.0,
                                        "edge_recall": 1.0,
                                        "citation_coverage": 1.0,
                                    },
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": "citation",
                    "strategies": [
                        {
                            "strategy": "directed",
                            "checks": [
                                {
                                    "kind": "expected_path",
                                    "passed": False,
                                    "partial": {
                                        "score": 0.8,
                                        "edge_recall": 1.0,
                                        "citation_coverage": 0.0,
                                    },
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    }
    report = _MODULE.diagnose_run(result)
    assert report["classification_counts"] == {
        "provenance_failure": 1,
        "strict_only_scoring_mismatch": 1,
    }


def test_diagnose_uses_revision_embedded_in_run_history_result():
    report = _MODULE.diagnose_run(
        {"run": {"extraction_revision": {"git_commit": "abc123"}}}
    )
    assert report["extraction_revision"] == {"git_commit": "abc123"}
