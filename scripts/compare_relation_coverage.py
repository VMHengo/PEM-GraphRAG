"""Compare a private relation review with one frozen extraction snapshot.

This is a triage report, not an extraction-recall score or a live-graph query.
"""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from lightrag.evaluation.semantic_matching import relation_match
from scripts.summarize_extraction_coverage import coverage_from_html


def _normalized(text: object) -> str:
    return " ".join(re.findall(r"[\w]+", str(text or "").casefold()))


def _predicate_for_matching(value: str) -> tuple[str, str | None]:
    parts = value.strip().split()
    if len(parts) == 2 and parts[1].casefold() in {"significantly", "slightly", "strongly"}:
        verb = parts[0].casefold()
        return {
            "increase": "increases", "decrease": "decreases", "reduce": "reduces",
            "improve": "improves", "degrade": "degrades",
        }.get(verb, verb), parts[1].casefold()
    return value, None


def _lexical_leads(fact: dict[str, Any], relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leads = []
    for edge in relations:
        source = SequenceMatcher(None, _normalized(fact["source"]), _normalized(edge["source"])).ratio()
        target = SequenceMatcher(None, _normalized(fact["target"]), _normalized(edge["target"])).ratio()
        if min(source, target) < 0.55:
            continue
        leads.append((min(source, target), (source + target) / 2, source, target, edge))
    leads.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        {"source": edge["source"], "predicate": edge["predicate"],
         "target": edge["target"], "chunk_id": edge["chunk_id"],
         "source_similarity": round(source, 3), "target_similarity": round(target, 3)}
        for _, _, source, target, edge in leads[:3]
    ]


def _reviewed_document(
    sample: dict[str, Any], review: dict[str, Any], name: str
) -> dict[str, Any]:
    if sample.get("seed") != review.get("seed"):
        raise ValueError("Sample seed and review seed differ")
    sample_docs = [
        {"sha256": item["sha256"], "file_name": item["file_name"]}
        for item in sample.get("documents") or []
    ]
    if sample_docs != review.get("documents"):
        raise ValueError("Review does not belong to these PDF versions")
    documents = [item for item in sample["documents"] if item["file_name"] == name]
    if len(documents) != 1:
        raise ValueError("Expected one matching document in the sample")
    return documents[0]


def compare_review(
    sample: dict[str, Any],
    review: dict[str, Any],
    coverage: dict[str, Any],
    *,
    pdf: Path | None = None,
) -> dict[str, Any]:
    if coverage.get("schema_version") != 1 or review.get("schema_version") != 1:
        raise ValueError("Unsupported review or coverage schema")
    document = _reviewed_document(sample, review, coverage["document_name"])
    if pdf is not None:
        if pdf.name != document["file_name"] or hashlib.sha256(pdf.read_bytes()).hexdigest() != document["sha256"]:
            raise ValueError("PDF name/hash does not match the frozen sample")
    sample_items = {item["id"]: item for item in document["sample"]}
    reviews = review.get("reviews") or {}
    unknown_ids = set(reviews) - {
        item["id"] for doc in sample["documents"] for item in doc["sample"]
    }
    if unknown_ids:
        raise ValueError(f"Review contains unknown passage IDs: {sorted(unknown_ids)[:3]}")
    rows = []
    for passage_id, passage in sample_items.items():
        entry = reviews.get(passage_id)
        if not isinstance(entry, dict) or entry.get("eligible_fact") not in {"yes", "no", "unclear"}:
            raise ValueError(f"Passage is not reviewed: {passage_id}")
        facts = entry.get("gold_assertions") or []
        if entry["eligible_fact"] != "yes" and facts:
            raise ValueError(f"Non-eligible passage has gold assertions: {passage_id}")
        if entry["eligible_fact"] == "yes" and not facts:
            raise ValueError(f"Eligible passage has no gold assertions: {passage_id}")
        context = " ".join(str(passage.get(key) or "") for key in ("context_before", "text", "context_after"))
        for index, fact in enumerate(facts, 1):
            if not all(str(fact.get(key) or "").strip() for key in ("source", "predicate", "target", "evidence")):
                raise ValueError(f"Incomplete gold assertion: {passage_id}:{index}")
            match_predicate, qualifier = _predicate_for_matching(fact["predicate"])
            expected = {
                "source": fact["source"], "relation_type": match_predicate,
                "target": fact["target"],
            }
            ranked = sorted(
                (
                    (
                        relation_match(expected, {
                            "source": edge["source"],
                            "target": edge["target"],
                            "relation_type": edge["predicate"],
                        }),
                        edge,
                    )
                    for edge in coverage.get("relations") or []
                ),
                key=lambda pair: (pair[0]["score"], pair[0]["diagnostic_score"]),
                reverse=True,
            )
            candidates = []
            for match, edge in ranked:
                if match["score"] <= 0 and not (
                    match["source"]["score"] >= 0.85
                    and match["target"]["score"] >= 0.85
                ):
                    continue
                candidates.append({
                    "source": edge["source"], "predicate": edge["predicate"],
                    "target": edge["target"], "chunk_id": edge["chunk_id"],
                    "description": edge.get("description") or "",
                    "score": match["score"], "exact_labels": match["exact"],
                    "source_match": match["source"]["score"],
                    "target_match": match["target"]["score"],
                    "predicate_match": match["predicate"]["score"],
                })
                if len(candidates) == 5:
                    break
            best = candidates[0] if candidates else None
            if best and best["exact_labels"] and not qualifier:
                outcome = "exact_labels_condition_unverified"
            elif best and best["score"] >= 0.5:
                outcome = "candidate_requires_review"
            elif best and min(best["source_match"], best["target_match"]) >= 0.85:
                outcome = "endpoint_lexical_lead_predicate_mismatch"
            else:
                outcome = "no_match_under_conservative_rules"
            evidence_status = (
                "located_in_sample_context"
                if _normalized(fact["evidence"]) in _normalized(context)
                else "not_located_in_sample_context"
            )
            rows.append({
                "passage_id": passage_id, "page": passage["page"],
                "fact_index": index, "gold": fact, "outcome": outcome,
                "evidence_status": evidence_status,
                "condition_status": "not_evaluated",
                "predicate_qualifier": qualifier,
                "candidates": candidates,
                "lexical_leads_not_matches": _lexical_leads(
                    fact, coverage.get("relations") or []
                ) if not best or best["score"] < 0.5 else [],
            })
    return {
        "document": document["file_name"],
        "pdf_sha256": document["sha256"],
        "document_id": coverage["document_id"],
        "artifact_fingerprint": coverage["fingerprint"],
        "artifact_profile": coverage.get("artifact_profile"),
        "sample_seed": sample["seed"],
        "reviewed_passages": len(sample_items),
        "gold_assertions": len(rows),
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "limitations": [
            "Exact labels do not certify condition or evidence support.",
            "Candidate scores require human adjudication; they are not recall points.",
            "The coverage snapshot is parsed extraction, not the active Neo4j graph.",
            "The snapshot lacks a complete isolated-entity inventory; missing entities cannot be proven here.",
            "One reviewed document is not a multi-document recall estimate.",
        ],
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Offline relation comparison",
        "",
        f"Document: `{report['document']}`",
        f"Artifact fingerprint: `{report['artifact_fingerprint']}`",
        f"Reviewed passages: {report['reviewed_passages']}; gold assertions: {report['gold_assertions']}",
        "",
        "These are matching leads, not a recall score or verified graph assertions.",
        "",
    ]
    for row in report["rows"]:
        fact = row["gold"]
        lines.extend([
            f"## {row['passage_id']} / assertion {row['fact_index']}",
            "",
            f"Expected: **{fact['source']} [{fact['predicate']}] {fact['target']}**",
            f"Outcome: `{row['outcome']}`; evidence: `{row['evidence_status']}`; "
            f"conditions: `not evaluated`",
            f"Conditions: {fact.get('conditions') or 'not specified'}",
            f"Source excerpt: {fact['evidence']}",
            "",
        ])
        for candidate in row["candidates"][:3]:
            lines.append(
                f"- Parsed candidate ({candidate['score']:.2f}): "
                f"{candidate['source']} [{candidate['predicate']}] {candidate['target']} "
                f"(`{candidate['chunk_id']}`)"
            )
        for lead in row["lexical_leads_not_matches"][:2]:
            lines.append(
                f"- Lexical lead only: {lead['source']} [{lead['predicate']}] "
                f"{lead['target']} (`{lead['chunk_id']}`)"
            )
        lines.extend(["", "Decision: **pending human review**", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_json", type=Path)
    parser.add_argument("review_json", type=Path)
    parser.add_argument("coverage_html", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--pdf", type=Path, help="Verify the sampled PDF hash")
    args = parser.parse_args()
    report = compare_review(
        json.loads(args.sample_json.read_text(encoding="utf-8")),
        json.loads(args.review_json.read_text(encoding="utf-8")),
        coverage_from_html(args.coverage_html), pdf=args.pdf,
    )
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = args.output_json.with_suffix(".md")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("document", "gold_assertions", "outcomes")}, ensure_ascii=False, indent=2))
    print(f"Private report: {args.output_json}")
    print(f"Review sheet: {markdown_path}")


if __name__ == "__main__":
    main()
