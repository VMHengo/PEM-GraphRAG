"""The coverage sample must remain stable and not quietly sample references."""

from pypdf import PdfWriter
import pytest

from scripts.sample_relation_coverage import sample_documents


def test_sample_is_reproducible_and_document_scoped(tmp_path, monkeypatch):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    for path in (first, second):
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with path.open("wb") as handle:
            writer.write(handle)

    def passages(path, *, max_pages):
        return [
            {"page": 1, "passage_number": index, "text": f"Sentence {index}"}
            for index in range(20)
        ]

    monkeypatch.setattr("scripts.sample_relation_coverage.candidates", passages)
    sample = sample_documents([first, second], seed=42, per_document=4, max_pages=1)
    assert sample == sample_documents([first, second], seed=42, per_document=4, max_pages=1)
    assert all(len(item["sample"]) == 4 for item in sample["documents"])
    assert all(item["review"]["eligible_fact"] is None for doc in sample["documents"] for item in doc["sample"])
    assert sample["documents"][0]["file_name"] == "first.pdf"


def test_rejects_too_few_passages(tmp_path, monkeypatch):
    path = tmp_path / "one.pdf"
    path.write_bytes(b"content")
    monkeypatch.setattr("scripts.sample_relation_coverage.candidates", lambda path, *, max_pages: [])
    with pytest.raises(ValueError, match="eligible passages"):
        sample_documents([path], seed=42, per_document=1, max_pages=1)
