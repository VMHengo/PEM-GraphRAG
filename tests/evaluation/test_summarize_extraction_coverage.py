"""Review counts describe only actually inspected text segments."""

from __future__ import annotations

import pytest

from scripts.build_extraction_coverage_review import render_html
from scripts.summarize_extraction_coverage import coverage_from_html, summarize_annotations


def _coverage() -> dict:
    return {
        "document_id": "doc-1", "fingerprint": "abc123",
        "chunks": [{"sentences": [
            {"id": "chunk:s000", "relations": ["r0001"]},
            {"id": "chunk:s001", "relations": []},
            {"id": "chunk:s002", "relations": []},
        ]}],
    }


def _review() -> dict:
    return {
        "document_id": "doc-1", "artifact_fingerprint": "abc123",
        "annotations": [
            {"sentence_id": "chunk:s000", "verdict": "no_missing", "missing_relations": []},
            {"sentence_id": "chunk:s001", "verdict": "missing", "missing_relations": [
                {"source": "A", "predicate": "causes", "target": "B", "importance": "high", "intermediate": True},
                {"source": "B", "predicate": "increases", "target": "C", "importance": "medium", "intermediate": False},
            ]},
        ],
    }


def test_counts_multiple_missing_relations_without_claiming_recall():
    result = summarize_annotations(_coverage(), _review())
    assert result["reviewed_segments"] == 2
    assert result["unreviewed_segments"] == 1
    assert result["marked_missing_relations"] == 2
    assert result["missing_by_importance"] == {"high": 1, "intermediate": 1, "medium": 1}
    assert result["findings"] == {"linked_no_missing": 1, "unlinked_missing": 1}
    assert "no document-wide extraction recall" in result["warning"]


@pytest.mark.parametrize("change", [
    lambda review: review.update(artifact_fingerprint="wrong"),
    lambda review: review["annotations"].append(review["annotations"][0]),
    lambda review: review["annotations"][1].update(verdict="no_missing"),
    lambda review: review["annotations"][1]["missing_relations"][0].update(importance="unknown"),
])
def test_rejects_mismatched_or_invalid_export(change):
    review = _review()
    change(review)
    with pytest.raises(ValueError):
        summarize_annotations(_coverage(), review)


def test_reads_private_html_report_without_artifact_or_chunk_files(tmp_path):
    coverage = {**_coverage(), "document_name": "example.pdf"}
    report = tmp_path / "report.html"
    report.write_text(render_html(coverage), encoding="utf-8")
    assert coverage_from_html(report) == coverage


def test_rejects_html_without_embedded_report(tmp_path):
    report = tmp_path / "report.html"
    report.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="No embedded coverage"):
        coverage_from_html(report)
