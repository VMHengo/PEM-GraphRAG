import json

from lightrag.pdf_provenance import (
    attach_pdf_page_locations,
    page_ranges_from_sidecar,
    page_ranges_from_text,
    sanitized_page_ranges,
)


def test_page_ranges_match_legacy_newline_join():
    assert page_ranges_from_text(["First page", "Second page"]) == [
        {"page": 1, "start": 0, "end": 10},
        {"page": 2, "start": 11, "end": 22},
    ]


def test_sanitized_page_ranges_keep_source_page_after_trim():
    pages = ["\nFirst passage\n", "Second passage on the next PDF page\n"]
    ranges = sanitized_page_ranges(pages)
    text = "".join(page + "\n" for page in pages).strip()
    chunks = {"c": {"content": "Second passage on the next PDF page"}}
    attach_pdf_page_locations(chunks, text, ranges)
    assert chunks["c"]["pdf_location"]["page"] == 2


def test_unique_chunk_can_span_two_pages():
    pages = ["The first passage ends", "and the second passage begins here."]
    chunks = {"chunk-1": {"content": "passage ends\nand the second passage"}}
    attach_pdf_page_locations(chunks, "\n".join(pages), page_ranges_from_text(pages))
    assert chunks["chunk-1"]["pdf_location"] == {
        "page": 1,
        "pages": [1, 2],
        "status": "chunk_text_match",
    }


def test_ambiguous_or_missing_chunk_is_not_grounded():
    pages = ["Battery aging changed resistance.", "Battery aging changed resistance."]
    chunks = {
        "duplicate": {"content": "Battery aging changed resistance."},
        "absent": {"content": "Electrode porosity decreased under pressure."},
    }
    attach_pdf_page_locations(chunks, "\n".join(pages), page_ranges_from_text(pages))
    assert all("pdf_location" not in chunk for chunk in chunks.values())


def test_changed_document_text_does_not_reuse_stale_page_offsets():
    ranges = page_ranges_from_text(["Battery aging raises DC resistance."])
    chunks = {"c": {"content": "Battery aging raises DC resistance."}}
    attach_pdf_page_locations(chunks, "Prefix " + "Battery aging raises DC resistance.", ranges)
    assert "pdf_location" not in chunks["c"]


def test_sidecar_page_positions_follow_merged_text(tmp_path):
    path = tmp_path / "paper.blocks.jsonl"
    rows = [
        {"type": "meta"},
        {"type": "content", "content": "Aging raises resistance.", "positions": [
            {"type": "bbox", "anchor": "2", "range": [1, 2, 3, 4]}
        ]},
        {"type": "content", "content": "Resistance raises heat.", "positions": [
            {"type": "bbox", "anchor": "3", "range": [1, 2, 3, 4]}
        ]},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    text = "Aging raises resistance.\n\nResistance raises heat."
    ranges = page_ranges_from_sidecar(path, text)
    chunks = {"c": {"content": "Resistance raises heat."}}
    attach_pdf_page_locations(chunks, text, ranges)
    assert chunks["c"]["pdf_location"]["page"] == 3
    assert page_ranges_from_sidecar(path, "different extraction") == []
