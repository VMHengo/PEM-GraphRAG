"""Compare reviewed source claims with parsed, isolated extraction artifacts.

This is an offline structural audit, not a PDF judge or a replacement for the
live benchmark. Related shortcuts never receive full direct-edge credit.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def _key(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _edges(artifact: dict[str, Any]) -> list[dict[str, str]]:
    if len(artifact.get("documents", [])) != 1:
        raise ValueError("Expected exactly one isolated document per artifact")
    edges = []
    for chunk in artifact["documents"][0].get("chunk_results", []):
        for edge in chunk.get("edges", []):
            for record in edge.get("records", []):
                edges.append(
                    {
                        "source": str(record.get("semantic_src_id") or edge.get("source") or ""),
                        "type": str(record.get("relation_type") or ""),
                        "target": str(record.get("semantic_tgt_id") or edge.get("target") or ""),
                        "chunk": str(record.get("source_id") or ""),
                        "directionality": str(record.get("directionality") or ""),
                    }
                )
    return edges


def _matches(edge: dict[str, str], pattern: dict[str, Any]) -> bool:
    return edge["directionality"] == "directed" and all(
        _key(edge[field]) in {_key(name) for name in pattern[field]}
        for field in ("source", "type", "target")
    )


def _evaluate_case(case: dict[str, Any], edges: list[dict[str, str]]) -> dict[str, Any]:
    direct = [edge for edge in edges if any(_matches(edge, p) for p in case["direct"])]
    related = [
        {**edge, "reason": pattern["reason"]}
        for edge in edges
        for pattern in case.get("related", [])
        if _matches(edge, pattern)
    ]
    if direct:
        status = "direct_match"
    elif related:
        status = "related_only"
    else:
        status = "missing"
    return {
        "status": status,
        "direct": direct,
        "related": related,
        "related_reasons": sorted({edge["reason"] for edge in related}),
    }


def audit(
    gold: dict[str, Any], baseline: dict[str, Any], variant: dict[str, Any]
) -> dict[str, Any]:
    """Require a frozen document/chunk selection, then classify reviewed edges."""

    if len(baseline.get("documents", [])) != 1 or len(variant.get("documents", [])) != 1:
        raise ValueError("Expected exactly one isolated document per artifact")
    source = baseline["documents"][0]
    candidate = variant["documents"][0]
    for field in ("doc_id", "source_fingerprint", "selected_fingerprint", "chunk_ids"):
        if source.get(field) != candidate.get(field):
            raise ValueError(f"A/B artifacts do not have the same {field}")
    if Path(source.get("file_path", "")).name != gold["source_document"]:
        raise ValueError("Gold source document does not match the artifact")
    baseline_edges = _edges(baseline)
    variant_edges = _edges(variant)
    cases = [
        {
            "id": case["id"],
            "claim": case["claim"],
            "pages": case["pages"],
            "pdf_support": case["pdf_support"],
            "baseline": _evaluate_case(case, baseline_edges),
            "variant": _evaluate_case(case, variant_edges),
        }
        for case in gold["cases"]
    ]
    return {
        "gold_id": gold["id"],
        "doc_id": source["doc_id"],
        "source_fingerprint": source["source_fingerprint"],
        "selected_fingerprint": source["selected_fingerprint"],
        "chunk_count": len(source["chunk_ids"]),
        "baseline_summary": dict(Counter(case["baseline"]["status"] for case in cases)),
        "variant_summary": dict(Counter(case["variant"]["status"] for case in cases)),
        "cases": cases,
    }


def render_markdown(report: dict[str, Any], scores: dict[str, Any] | None = None) -> str:
    lines = [
        "# Reviewed aging relations: frozen-artifact audit",
        "",
        "This offline audit applies the same reviewer-approved, case-specific",
        "endpoint/predicate alternatives to both parsed artifacts. `Related only`",
        "means a shortcut, generic state, or measurement-target mismatch; it",
        "does **not** count as a complete multi-hop edge. PDF support was judged",
        "by the human reviewer and is not inferred by this script. The audit",
        "does not verify raw LLM output, final Neo4j merge, or answer quality.",
        "",
        f"Document: `{report['doc_id']}`; frozen chunks: {report['chunk_count']}.",
        "",
    ]
    if scores:
        lines.extend([
            "Original live-benchmark scores (context only; **not** rescored here):",
            "",
            "| Metric | Baseline | Variant |",
            "| --- | ---: | ---: |",
        ])
        for metric in ("overall", "graph", "directed", "directed_exact"):
            lines.append(
                f"| {metric} | {scores['baseline'].get(metric)} | {scores['variant'].get(metric)} |"
            )
        lines.append("")
    lines.extend([
        "| Case | PDF review | Baseline graph | Variant graph | Diagnosis |",
        "| --- | --- | --- | --- | --- |",
    ])
    for case in report["cases"]:
        baseline = case["baseline"]
        variant = case["variant"]
        reasons = ", ".join(variant["related_reasons"] or baseline["related_reasons"])
        lines.append(
            f"| {case['id']} | {case['pdf_support']} | {baseline['status']} | "
            f"{variant['status']} | {reasons or '-'} |"
        )
    lines.extend([
        "",
        f"Baseline: {report['baseline_summary']}; variant: {report['variant_summary']}.",
        "",
        "A direct match is a structural match under the reviewed case-specific",
        "aliases, **not** independent verification that the saved edge is true",
        "or that its source quote supports it. Conditions and signs still need",
        "manual inspection where they are stored only in prose.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold", type=Path)
    parser.add_argument("baseline_artifact", type=Path)
    parser.add_argument("variant_artifact", type=Path)
    parser.add_argument("--baseline-result", type=Path)
    parser.add_argument("--variant-result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    gold, baseline, variant = (
        json.loads(path.read_text(encoding="utf-8"))
        for path in (args.gold, args.baseline_artifact, args.variant_artifact)
    )
    report = audit(gold, baseline, variant)
    scores = None
    if args.baseline_result and args.variant_result:
        scores = {
            "baseline": json.loads(args.baseline_result.read_text(encoding="utf-8"))["scores"],
            "variant": json.loads(args.variant_result.read_text(encoding="utf-8"))["scores"],
        }
    output = render_markdown(report, scores)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
