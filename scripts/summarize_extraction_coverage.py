"""Summarize exported sentence annotations without mistaking links for recall."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.build_extraction_coverage_review import build_coverage


def coverage_from_html(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    match = re.search(
        r'<script id="coverage" type="application/json">(.*?)</script>',
        content,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("No embedded coverage data found in HTML report")
    return json.loads(match.group(1))


def summarize_annotations(coverage: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    if review.get("document_id") != coverage["document_id"]:
        raise ValueError("Review document ID does not match the extraction artifact")
    if review.get("artifact_fingerprint") != coverage["fingerprint"]:
        raise ValueError("Review fingerprint does not match the extraction artifact")
    sentences = {
        sentence["id"]: sentence
        for chunk in coverage["chunks"] for sentence in chunk["sentences"]
    }
    reviewed = set()
    findings = Counter()
    importance = Counter()
    missing_relations = []
    for item in review.get("annotations") or []:
        sentence_id = item.get("sentence_id")
        if sentence_id not in sentences or sentence_id in reviewed:
            raise ValueError(f"Unknown or duplicate sentence ID: {sentence_id}")
        reviewed.add(sentence_id)
        verdict = item.get("verdict")
        if verdict not in {"missing", "no_missing", "unclear"}:
            raise ValueError(f"Invalid finding for {sentence_id}")
        link = "linked" if sentences[sentence_id]["relations"] else "unlinked"
        findings[(link, verdict)] += 1
        additions = item.get("missing_relations") or []
        if verdict == "missing" and not additions:
            raise ValueError(f"Missing finding has no relations: {sentence_id}")
        if verdict != "missing" and additions:
            raise ValueError(f"Non-missing finding includes relations: {sentence_id}")
        for relation in additions:
            if not all(str(relation.get(key) or "").strip() for key in ("source", "predicate", "target")):
                raise ValueError(f"Incomplete missing relation at {sentence_id}")
            level = relation.get("importance")
            if level not in {"high", "medium", "low"}:
                raise ValueError(f"Invalid importance at {sentence_id}")
            importance[level] += 1
            if relation.get("intermediate"):
                importance["intermediate"] += 1
            missing_relations.append({"sentence_id": sentence_id, **relation})
    return {
        "document_id": coverage["document_id"],
        "artifact_fingerprint": coverage["fingerprint"],
        "total_segments": len(sentences),
        "reviewed_segments": len(reviewed),
        "unreviewed_segments": len(sentences) - len(reviewed),
        "findings": {
            f"{link}_{verdict}": count for (link, verdict), count in sorted(findings.items())
        },
        "marked_missing_relations": len(missing_relations),
        "missing_by_importance": dict(importance),
        "missing_relations": missing_relations,
        "warning": (
            "Candidate text links are not verified relations. Missing counts cover only reviewed "
            "segments; no document-wide extraction recall is inferred."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_or_artifact", type=Path)
    parser.add_argument("review_json", type=Path)
    parser.add_argument("--chunks", type=Path, help="Chunk JSON when input is an artifact")
    args = parser.parse_args()
    if args.report_or_artifact.suffix.lower() == ".html":
        coverage = coverage_from_html(args.report_or_artifact)
    elif args.chunks:
        coverage = build_coverage(
            json.loads(args.report_or_artifact.read_text(encoding="utf-8")),
            json.loads(args.chunks.read_text(encoding="utf-8")),
        )
    else:
        parser.error("--chunks is required when the first argument is an artifact")
    report = summarize_annotations(
        coverage, json.loads(args.review_json.read_text(encoding="utf-8"))
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
