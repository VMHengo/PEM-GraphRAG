"""Triage zero-scored aging relations against a saved extraction artifact.

This is a read-only attribution aid. A missing parsed assertion does not prove
the source PDF lacks the fact, and a present assertion does not prove the live
graph contains it.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from lightrag.evaluation.semantic_matching import relation_match, text_match


def _records(artifact: dict[str, Any], field: str) -> list[dict[str, Any]]:
    return [
        record
        for document in artifact.get("documents", [])
        for chunk in document.get("chunk_results", [])
        for group in chunk.get(field, [])
        for record in group.get("records", [])
        if isinstance(record, dict)
    ]


def audit_zero_relations(
    result: dict[str, Any], artifact: dict[str, Any]
) -> dict[str, Any]:
    edges = _records(artifact, "edges")
    nodes = _records(artifact, "nodes")
    entity_names = [
        str(node.get("entity_name") or node.get("entity_id") or "") for node in nodes
    ]
    rows: list[dict[str, Any]] = []
    for case in result.get("cases", {}).get("graph", []):
        for check in case.get("relation_checks", []):
            if check.get("score") != 0 or not isinstance(check.get("expected"), dict):
                continue
            expected = check["expected"]
            matches = [relation_match(expected, edge) for edge in edges]
            best = max(matches, key=lambda match: match["score"], default=None)
            matched = best["matched"] if best and best["score"] else None
            if matched and best["score"] == 1:
                category = "parsed_full_match_graph_or_scoring_miss"
            elif matched:
                category = "parsed_partial_match_review_alias_or_predicate"
            else:
                endpoints = [
                    str(expected.get(key) or "") for key in ("source", "target")
                ]
                present = [
                    any(
                        text_match(name, actual).score >= 0.85
                        for actual in entity_names
                    )
                    for name in endpoints
                ]
                category = (
                    "parsed_endpoint_absent_or_gold_mismatch"
                    if not all(present)
                    else "parsed_relation_absent_or_gold_mismatch"
                )
            nearby = []
            for edge in edges:
                source_score = text_match(
                    expected.get("source"), edge.get("semantic_src_id")
                ).score
                target_score = text_match(
                    expected.get("target"), edge.get("semantic_tgt_id")
                ).score
                inverse_source_score = text_match(
                    expected.get("source"), edge.get("semantic_tgt_id")
                ).score
                inverse_target_score = text_match(
                    expected.get("target"), edge.get("semantic_src_id")
                ).score
                proximity = max(
                    source_score + target_score,
                    inverse_source_score + inverse_target_score,
                )
                if proximity < 0.85:
                    continue
                nearby.append((proximity, edge))
            nearby.sort(key=lambda item: item[0], reverse=True)
            rows.append(
                {
                    "case_id": case.get("id"),
                    "expected": expected,
                    "category": category,
                    "artifact_match_score": best["score"] if best else 0,
                    "artifact_match": matched,
                    "nearby_artifact_assertions": [
                        {
                            "source": edge.get("semantic_src_id"),
                            "relation_type": edge.get("relation_type"),
                            "target": edge.get("semantic_tgt_id"),
                            "source_id": edge.get("source_id"),
                            "proximity": round(proximity, 2),
                        }
                        for proximity, edge in nearby[:3]
                    ],
                }
            )
    return {
        "benchmark_id": result.get("benchmark", {}).get("id"),
        "scorer_version": result.get("scoring", {}).get("version"),
        "artifact_profile": artifact.get("profile_file"),
        "parsed_entities": len(nodes),
        "parsed_assertions": len(edges),
        "zero_checks": len(rows),
        "categories": dict(Counter(row["category"] for row in rows)),
        "limitations": [
            "Parsed artifact is not a snapshot of the live graph.",
            "Missing parsed facts require source-PDF and raw-output review.",
            "No model or graph calls were made.",
        ],
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    print(json.dumps(audit_zero_relations(result, artifact), indent=2))


if __name__ == "__main__":
    main()
