"""Flag extraction descriptions that may have lost graph structure.

This is a read-only review aid. Flags never establish that an edge is false or
that a new edge is supported by the cited PDF.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.summarize_extraction_coverage import coverage_from_html


def _words(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _flags(edge: dict[str, Any]) -> list[dict[str, str]]:
    description = str(edge.get("description") or "")
    source = str(edge.get("source") or "")
    target = str(edge.get("target") or "")
    predicate = str(edge.get("predicate") or "")
    normalized_description = _words(description)
    flags: list[dict[str, str]] = []

    if (
        "temperature rise rate" in _words(target)
        and "temperature rise rate" not in normalized_description
        and re.search(r"\btemperature rise (?:decreas|increas)\w*\b", normalized_description)
    ):
        flags.append({
            "code": "rise_vs_rise_rate",
            "reason": "The description changes temperature rise, but the structured target is temperature rise rate.",
        })

    state = re.search(r"\bdegradation of (?:the )?([a-z ]+?)\s+(?:makes?|causes?|leads?\b)", description, re.I)
    if state and _words(source) and _words(source) in _words(state.group(1)) and "degrad" not in source.casefold():
        flags.append({
            "code": "stateful_source_collapsed",
            "reason": "The description refers to degradation of the source quantity, not the quantity itself.",
        })

    participant = re.search(
        r"\breacts?\s+with\s+(?:the\s+)?([a-z][a-z -]*?)(?=\s+to\b|[,.]|$)",
        description, re.I,
    )
    if participant:
        name = participant.group(1).strip()
        if name and _words(name) not in _words(source) and _words(name) not in _words(target):
            flags.append({
                "code": "reaction_participant_not_endpoint",
                "reason": f"The description names '{name}' as a reaction participant, but neither endpoint does.",
            })

    if predicate in {"increases", "decreases", "reduces"} and re.search(
        r"\b(increase|decrease|reduction|reduced)\b", target, re.I
    ):
        flags.append({
            "code": "effect_double_encoded",
            "reason": "The change appears in both predicate and target label; inspect state/quantity identity.",
        })

    condition = re.search(
        r"\b(severe|early stage|later stage|further aging|deeper aging|\d+\s*%\s*SOH)\b",
        description, re.I,
    )
    if condition and _words(condition.group()) not in _words(source + " " + target):
        flags.append({
            "code": "condition_only_in_description",
            "reason": "An operating or aging condition appears in prose; its structured compatibility is unverified.",
        })
    return flags


def audit_description_structure(
    coverage: dict[str, Any], comparison: dict[str, Any]
) -> dict[str, Any]:
    if (
        coverage.get("fingerprint") != comparison.get("artifact_fingerprint")
        or coverage.get("document_id") != comparison.get("document_id")
    ):
        raise ValueError("Comparison and coverage refer to different frozen artifacts")
    selected: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in comparison.get("rows") or []:
        for candidate in [
            *(row.get("candidates") or []),
            *(row.get("lexical_leads_not_matches") or []),
        ]:
            key = tuple(str(candidate[field]) for field in ("chunk_id", "source", "predicate", "target"))
            selected[key] = {"passage_id": row["passage_id"], "gold": row["gold"]}
    rows = []
    for edge in coverage.get("relations") or []:
        key = tuple(str(edge[field]) for field in ("chunk_id", "source", "predicate", "target"))
        if key not in selected:
            continue
        flags = _flags(edge)
        rows.append({
            "relation_id": edge.get("id"),
            "source": edge["source"], "predicate": edge["predicate"],
            "target": edge["target"], "chunk_id": edge["chunk_id"],
            "description": edge.get("description") or "",
            "match_status": edge.get("match_status"),
            "flags": flags,
        })
    return {
        "document_id": coverage["document_id"],
        "artifact_fingerprint": coverage["fingerprint"],
        "inspected_assertions": len(rows),
        "flag_counts": dict(Counter(flag["code"] for row in rows for flag in row["flags"])),
        "rows": rows,
        "limitations": [
            "Flags are text-pattern review leads, not verified errors or new relations.",
            "Only assertions surfaced by the frozen gold comparison are inspected.",
            "Source quotes and condition compatibility require document review.",
            "No graph write, model call or active-graph query occurs.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Description-to-structure audit", "",
        f"Artifact: `{report['artifact_fingerprint']}`",
        f"Inspected assertions: {report['inspected_assertions']}", "",
        "Flags are review leads, not automatic corrections.", "",
    ]
    for row in report["rows"]:
        lines.extend([
            f"## {row['source']} [{row['predicate']}] {row['target']}", "",
            f"Chunk: `{row['chunk_id']}`",
            f"Description: {row['description']}",
            "",
        ])
        if row["flags"]:
            lines.extend(f"- **{flag['code']}**: {flag['reason']}" for flag in row["flags"])
        else:
            lines.append("- No targeted heuristic flag; this is not evidence of correctness.")
        lines.extend(["", "Reviewer decision: **pending**", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_html", type=Path)
    parser.add_argument("comparison_json", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    report = audit_description_structure(
        coverage_from_html(args.coverage_html),
        json.loads(args.comparison_json.read_text(encoding="utf-8")),
    )
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = args.output_json.with_suffix(".md")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"inspected_assertions": report["inspected_assertions"], "flag_counts": report["flag_counts"]}, indent=2))
    print(f"Review sheet: {markdown}")


if __name__ == "__main__":
    main()
