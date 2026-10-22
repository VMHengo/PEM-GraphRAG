"""Summarize an existing benchmark run without querying models or the graph."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


def _score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _failed_checks(case: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        check
        for check in case.get(key, [])
        if isinstance(check, dict) and not check.get("passed")
    ]


def _classify_case(
    graph_case: dict[str, Any],
    selected: dict[str, Any],
    query_case: dict[str, Any],
) -> tuple[str, str]:
    path_checks = [
        check
        for check in selected.get("checks", [])
        if isinstance(check, dict) and check.get("kind") == "expected_path"
    ]
    if any(
        not check.get("passed")
        and _score((check.get("partial") or {}).get("score")) == 1
        for check in path_checks
    ):
        return (
            "strict_only_scoring_mismatch",
            "result: semantic path score is full, strict check fails",
        )
    if any(
        not check.get("passed")
        and _score((check.get("partial") or {}).get("edge_recall")) == 1
        and _score((check.get("partial") or {}).get("citation_coverage")) == 0
        for check in path_checks
    ):
        return "provenance_failure", "result: matched path has no required citations"
    if _failed_checks(graph_case, "relation_checks"):
        return (
            "graph_assertion_unverified",
            "result: pair-level relation check failed; inspect stored assertions",
        )
    if _failed_checks(query_case, "reference_checks"):
        return "provenance_failure", "result: expected document reference missing"
    if path_checks and any(not check.get("passed") for check in path_checks):
        return (
            "retrieval_miss_unattributed",
            "result: path check failed; inspect anchors, filters and pruning",
        )
    if _failed_checks(graph_case, "entity_checks"):
        return "entity_mismatch", "result: entity check failed"
    return "no_attributable_failure", "result alone does not identify a failure"


def diagnose_run(
    result: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    benchmark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    benchmark = benchmark or {}
    graph = {
        case.get("id"): case
        for case in result.get("cases", {}).get("graph", [])
        if isinstance(case, dict) and case.get("id")
    }
    directed = {
        case.get("id"): case
        for case in result.get("cases", {}).get("directed", [])
        if isinstance(case, dict) and case.get("id")
    }
    query = {
        case.get("id"): case
        for case in result.get("cases", {}).get("query", [])
        if isinstance(case, dict) and case.get("id")
    }
    gold = {
        case.get("id"): case
        for key in ("cases", "directed_cases")
        for case in benchmark.get(key, [])
        if isinstance(case, dict) and case.get("id")
    }
    rows = []
    for case_id in sorted(graph.keys() | directed.keys() | query.keys()):
        graph_case = graph.get(case_id, {})
        directed_case = directed.get(case_id, {})
        query_case = query.get(case_id, {})
        strategies = {
            item.get("strategy"): item
            for item in directed_case.get("strategies", [])
            if isinstance(item, dict) and item.get("strategy")
        }
        selected = strategies.get("directed") or strategies.get("combined") or {}
        entity_score = _score(graph_case.get("entity_score"))
        relation_score = _score(graph_case.get("relation_score"))
        path_score = _score(selected.get("score"))
        classification, basis = _classify_case(graph_case, selected, query_case)

        if entity_score is not None and entity_score < 50:
            next_check = "inspect_entity_names"
        elif relation_score is not None and relation_score < 50:
            next_check = "inspect_expected_edges_and_source_evidence"
        elif path_score is not None and path_score < 50:
            next_check = "inspect_path_anchors_and_retrieval_filters"
        else:
            next_check = "review_answer_grounding"

        missing_edges = []
        for check in graph_case.get("relation_checks", []):
            if not isinstance(check, dict) or check.get("passed"):
                continue
            expected = check.get("expected") or {}
            if not isinstance(expected, dict):
                continue
            missing_edges.append(
                {
                    "source": expected.get("source"),
                    "relation_type": expected.get("relation_type"),
                    "target": expected.get("target"),
                    "partial_score": _score(check.get("score")),
                }
            )

        rows.append(
            {
                "id": case_id,
                "entity_score": entity_score,
                "relation_score": relation_score,
                "directed_score": path_score,
                "path_count": selected.get("path_count"),
                "path_status": selected.get("path_status"),
                "next_check": next_check,
                "non_exact_expected_edges": missing_edges,
                "classification": classification,
                "classification_basis": basis,
                "failed_entities": _failed_checks(graph_case, "entity_checks"),
                "failed_relations": _failed_checks(graph_case, "relation_checks"),
                "failed_paths": [
                    check
                    for check in selected.get("checks", [])
                    if isinstance(check, dict)
                    and check.get("kind") == "expected_path"
                    and not check.get("passed")
                ],
                "failed_references": _failed_checks(query_case, "reference_checks"),
                "source_evidence": gold.get(case_id, {}).get("evidence", []),
            }
        )

    counts = Counter(row["classification"] for row in rows)
    return {
        "benchmark_id": result.get("benchmark", {}).get("id"),
        "run_generated_at": result.get("run", {}).get("generated_at"),
        "run": result.get("run", {}),
        "scores": result.get("scores", {}),
        "scoring": result.get("scoring", {}),
        "extraction_revision": metadata.get("extraction_revision")
        or result.get("run", {}).get("extraction_revision"),
        "benchmark_version": benchmark.get("version"),
        "document_scope": benchmark.get("document_scope"),
        "classification_counts": dict(sorted(counts.items())),
        "note": (
            "Classifications only use saved checks. Graph-assertion presence, "
            "retrieval rejection stage and source chunks require separate read-only evidence."
        ),
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "result", type=Path, help="Existing evaluation_runs/.../result.json"
    )
    parser.add_argument("--metadata", type=Path, help="Adjacent metadata.json")
    parser.add_argument("--benchmark", type=Path, help="Benchmark fixture JSON")
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    metadata_path = args.metadata or args.result.with_name("metadata.json")
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.is_file()
        else None
    )
    benchmark = (
        json.loads(args.benchmark.read_text(encoding="utf-8"))
        if args.benchmark
        else None
    )
    print(
        json.dumps(
            diagnose_run(result, metadata=metadata, benchmark=benchmark),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
