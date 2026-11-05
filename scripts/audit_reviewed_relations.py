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
                        "description": str(record.get("description") or ""),
                    }
                )
    return edges


def _matches(edge: dict[str, str], pattern: dict[str, Any]) -> bool:
    return (
        edge["directionality"] == "directed"
        and all(
            _key(edge[field]) in {_key(name) for name in pattern[field]}
            for field in ("source", "type", "target")
        )
        and (
            not pattern.get("description_contains")
            or _key(pattern["description_contains"]) in _key(edge["description"])
        )
    )


def _evaluate_case(case: dict[str, Any], edges: list[dict[str, str]]) -> dict[str, Any]:
    direct = [
        {**edge, "matched_rule": "direct"}
        for edge in edges if any(_matches(edge, p) for p in case["direct"])
    ]
    state_only = [
        {**edge, "matched_rule": "state_in_description_only"}
        for edge in edges
        if any(_matches(edge, p) for p in case.get("state_in_description_only", []))
    ]
    related = [
        {**edge, "reason": pattern["reason"]}
        for edge in edges
        for pattern in case.get("related", [])
        if _matches(edge, pattern)
    ]
    if direct:
        status = "direct_match"
    elif state_only:
        status = "state_in_description_only"
    elif related:
        status = "related_only"
    else:
        status = "missing"
    return {
        "status": status,
        "direct": direct,
        "state_in_description_only": state_only,
        "related": related,
        "related_reasons": sorted({edge["reason"] for edge in related}),
    }


def _evaluate_chain(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    left = first["direct"] + first["state_in_description_only"]
    right = second["direct"] + second["state_in_description_only"]
    matches = [
        {"first": a, "second": b}
        for a in left for b in right
        if a["directionality"] == b["directionality"] == "directed"
        and _key(a["target"]) == _key(b["source"])
    ]
    if any(
        pair["first"]["matched_rule"] == pair["second"]["matched_rule"] == "direct"
        for pair in matches
    ):
        status = "direct_chain"
    elif matches:
        status = "partial_chain"
    else:
        status = "missing_chain"
    return {"status": status, "matched_paths": matches}


def audit(
    gold: dict[str, Any], baseline: dict[str, Any], variant: dict[str, Any],
    case_ids: set[str] | None = None,
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
    if case_ids is not None:
        unknown_cases = case_ids - {case["id"] for case in gold["cases"]}
        if unknown_cases:
            raise ValueError(f"Unknown reviewed case IDs: {sorted(unknown_cases)}")
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
        if case_ids is None or case["id"] in case_ids
    ]
    by_id = {case["id"]: case for case in cases}
    chains = []
    for chain_id, first_id, second_id in (
        ("potential_to_current", "G01", "G02"),
        ("spacing_to_current", "G03", "G04"),
    ):
        if first_id in by_id and second_id in by_id:
            chains.append({
                "id": chain_id,
                "cases": [first_id, second_id],
                "baseline": _evaluate_chain(by_id[first_id]["baseline"], by_id[second_id]["baseline"]),
                "variant": _evaluate_chain(by_id[first_id]["variant"], by_id[second_id]["variant"]),
            })

    def forbidden_matches(edges: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {"id": pattern["id"], "source": edge["source"],
             "type": edge["type"], "target": edge["target"], "chunk": edge["chunk"]}
            for pattern in gold.get("forbidden", [])
            for edge in edges
            if _matches(edge, pattern)
        ]

    return {
        "gold_id": gold["id"],
        "doc_id": source["doc_id"],
        "source_fingerprint": source["source_fingerprint"],
        "selected_fingerprint": source["selected_fingerprint"],
        "chunk_count": len(source["chunk_ids"]),
        "baseline_summary": dict(Counter(case["baseline"]["status"] for case in cases)),
        "variant_summary": dict(Counter(case["variant"]["status"] for case in cases)),
        "baseline_forbidden": forbidden_matches(baseline_edges),
        "variant_forbidden": forbidden_matches(variant_edges),
        "cases": cases,
        "chains": chains,
    }


def render_markdown(report: dict[str, Any], scores: dict[str, Any] | None = None) -> str:
    lines = [
        "# Reviewed aging relations: frozen-artifact audit",
        "",
        "This offline audit applies the same reviewer-approved, case-specific",
        "endpoint/predicate alternatives to both parsed artifacts. `Related only`",
        "means a shortcut, generic state, or measurement-target mismatch; it",
        "does **not** count as a complete multi-hop edge. `State in description",
        "only` is partial: the endpoint name omits the change, while the",
        "relationship description states it. PDF support was judged",
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
        if variant["status"] == "direct_match" and baseline["status"] != "direct_match":
            reasons = "resolved: " + ", ".join(baseline["related_reasons"] or ["missing_in_baseline"])
        elif variant["status"] == "state_in_description_only":
            reasons = "changed state only in relationship description"
        elif variant["status"] == "missing" and baseline["status"] == "related_only":
            reasons = "regressed: " + ", ".join(baseline["related_reasons"])
        elif variant["status"] == baseline["status"] == "direct_match":
            reasons = ""
        else:
            reasons = ", ".join(variant["related_reasons"] or baseline["related_reasons"])
        lines.append(
            f"| {case['id']} | {case['pdf_support']} | {baseline['status']} | "
            f"{variant['status']} | {reasons or '-'} |"
        )
    lines.extend([
        "",
        f"Baseline: {report['baseline_summary']}; variant: {report['variant_summary']}.",
        "",
        "| Chain | Baseline | Variant |",
        "| --- | --- | --- |",
    ])
    for chain in report["chains"]:
        lines.append(
            f"| {chain['id']} | {chain['baseline']['status']} | {chain['variant']['status']} |"
        )
    lines.extend(["", "Matched assertions (case-specific structural matches):", ""])
    for case in report["cases"]:
        for label in ("baseline", "variant"):
            result = case[label]
            for edge in result["direct"] + result["state_in_description_only"]:
                lines.append(
                    f"- {case['id']} {label} [{edge['matched_rule']}]: "
                    f"{edge['source']} --[{edge['type']}]--> {edge['target']} "
                    f"(`{edge['chunk']}`)"
                )
    lines.extend([
        "",
        "Forbidden reverse-direction checks:",
        "",
    ])
    for label in ("baseline", "variant"):
        matches = report[f"{label}_forbidden"]
        lines.append(f"- {label}: {len(matches)} matched assertions")
        for match in matches:
            lines.append(
                f"  - `{match['id']}`: {match['source']} --[{match['type']}]--> "
                f"{match['target']} (`{match['chunk']}`)"
            )
    lines.extend([
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
    parser.add_argument("--case-id", action="append", default=[], help="Restrict to a source-covered reviewed case")
    args = parser.parse_args()
    gold, baseline, variant = (
        json.loads(path.read_text(encoding="utf-8"))
        for path in (args.gold, args.baseline_artifact, args.variant_artifact)
    )
    report = audit(gold, baseline, variant, set(args.case_id) if args.case_id else None)
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
