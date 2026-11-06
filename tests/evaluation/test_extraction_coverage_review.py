"""Candidate text links never become asserted evidence or recall scores."""

from __future__ import annotations

import pytest

from scripts.build_extraction_coverage_review import build_coverage, render_html


def _fixture() -> tuple[dict, dict]:
    chunk_id = "doc-1-chunk-000"
    content = (
        "Higher current rate increases heat generation. "
        "Electrolyte decomposition produces gas. "
        "Gas changes electrode spacing. "
        "The device weighs 10 grams."
    )
    artifact = {
        "profile_file": "test-profile.yml",
        "documents": [{
            "doc_id": "doc-1", "file_path": "battery.pdf", "chunk_ids": [chunk_id],
            "chunk_results": [{"edges": [
                {"source": "Higher Current Rate", "target": "Heat Generation", "records": [{
                    "semantic_src_id": "Higher Current Rate",
                    "semantic_tgt_id": "Heat Generation",
                    "relation_type": "increases", "directionality": "directed",
                    "source_id": chunk_id,
                    "description": "Higher current rate increases heat generation.",
                }]},
                {"source": "Gas", "target": "Electrode Spacing", "records": [{
                    "semantic_src_id": "Gas", "semantic_tgt_id": "Electrode Spacing",
                    "relation_type": "changes", "directionality": "directed",
                    "source_id": chunk_id,
                    "description": "Gas changes electrode spacing.",
                }]},
            ]}],
        }],
    }
    return artifact, {chunk_id: {"full_doc_id": "doc-1", "content": content}}


def test_coverage_links_only_candidate_passages_and_preserves_gaps():
    artifact, chunks = _fixture()
    data = build_coverage(artifact, chunks)

    assert data["summary"]["sentences"] == 4
    assert data["summary"]["assertions"] == 2
    assert data["summary"]["sentences_with_candidate_links"] == 2
    sentences = data["chunks"][0]["sentences"]
    assert sentences[0]["relations"] == ["r0001"]
    assert sentences[1]["relations"] == []
    assert sentences[2]["relations"] == ["r0002"]
    assert sentences[3]["relations"] == []
    assert all(relation["match_status"] == "exact_text_match" for relation in data["relations"])


def test_does_not_render_untrusted_pdf_text_as_html_markup():
    artifact, chunks = _fixture()
    chunks["doc-1-chunk-000"]["content"] += " <script>alert('x')</script>"
    page = render_html(build_coverage(artifact, chunks))
    assert "<script>alert('x')</script>" not in page
    assert "\\u003cscript>" in page


def test_rejects_wrong_document_chunk_and_unselected_assertion():
    artifact, chunks = _fixture()
    chunks["doc-1-chunk-000"]["full_doc_id"] = "doc-other"
    with pytest.raises(ValueError, match="mismatched source chunk"):
        build_coverage(artifact, chunks)

    artifact, chunks = _fixture()
    artifact["documents"][0]["chunk_results"][0]["edges"][0]["records"][0]["source_id"] = "other"
    with pytest.raises(ValueError, match="unselected chunk"):
        build_coverage(artifact, chunks)
