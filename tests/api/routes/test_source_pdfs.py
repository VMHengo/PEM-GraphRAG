from io import BytesIO
import asyncio
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pypdf import PdfWriter

from lightrag.api.source_pdfs import locate_source_page, resolve_source_pdf


def test_resolves_only_one_retained_pdf(tmp_path):
    archived = tmp_path / "__parsed__"
    archived.mkdir()
    pdf = archived / "study_001.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert resolve_source_pdf(tmp_path, "study.pdf") == pdf.resolve()
    assert resolve_source_pdf(tmp_path, "../study.pdf") is None
    assert resolve_source_pdf(tmp_path, "study.txt") is None
    (archived / "study_002.pdf").write_bytes(b"%PDF-1.4")
    assert resolve_source_pdf(tmp_path, "study.pdf") is None


def test_locate_page_does_not_claim_unsupported_quote(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buffer = BytesIO()
    writer.write(buffer)
    pdf = tmp_path / "blank.pdf"
    pdf.write_bytes(buffer.getvalue())
    assert locate_source_page(pdf, "Electrode calendering decreased cathode porosity.") == (None, "not_found")
    assert locate_source_page(pdf, "short") == (None, "insufficient_quote")


def test_locate_page_reports_only_text_actually_found(monkeypatch, tmp_path):
    from lightrag.api import source_pdfs

    class Reader:
        def __init__(self, _path):
            self.pages = [
                SimpleNamespace(extract_text=lambda: "Unrelated introduction."),
                SimpleNamespace(extract_text=lambda: "Electrode calendering\ndecreased cathode porosity."),
            ]

    monkeypatch.setattr(source_pdfs, "PdfReader", Reader)
    (tmp_path / "study.pdf").write_bytes(b"mock")
    assert locate_source_page(tmp_path / "study.pdf", "Electrode calendering decreased cathode porosity.") == (
        2, "exact_text_match"
    )


def test_locate_page_rejects_repeated_quote(monkeypatch, tmp_path):
    from lightrag.api import source_pdfs

    class Reader:
        def __init__(self, _path):
            text = "Electrode calendering decreased cathode porosity."
            self.pages = [SimpleNamespace(extract_text=lambda: text)] * 2

    monkeypatch.setattr(source_pdfs, "PdfReader", Reader)
    (tmp_path / "study.pdf").write_bytes(b"mock")
    assert locate_source_page(tmp_path / "study.pdf", "Electrode calendering decreased cathode porosity.") == (
        None, "ambiguous"
    )


def test_pdf_route_requires_login_and_serves_only_document_id(tmp_path):
    original_argv = sys.argv[:]
    try:
        sys.argv = [sys.argv[0]]
        from lightrag.api.routers.document_routes import create_document_routes
        from lightrag.evaluation.reviewer_identity import resolve_reviewer_identity
    finally:
        sys.argv = original_argv

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    pdf = tmp_path / "study.pdf"
    with pdf.open("wb") as output:
        writer.write(output)

    class DocStatus:
        async def get_by_id(self, doc_id):
            return {"file_path": "study.pdf"} if doc_id == "doc-known" else None

    app = FastAPI()
    app.include_router(create_document_routes(
        SimpleNamespace(doc_status=DocStatus()), SimpleNamespace(input_dir=tmp_path)
    ))
    client = TestClient(app)
    assert client.get("/documents/doc-known/source-pdf").status_code == 401
    app.dependency_overrides[resolve_reviewer_identity] = lambda: SimpleNamespace(email="reviewer@example.org")
    response = client.get("/documents/doc-known/source-pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert client.get("/documents/doc-other/source-pdf").status_code == 404


def test_query_references_keep_unambiguous_document_id():
    original_argv = sys.argv[:]
    try:
        sys.argv = [sys.argv[0]]
        from lightrag.api.routers.query_routes import _enrich_references_with_source_metadata
    finally:
        sys.argv = original_argv

    class DocStatus:
        async def get_docs_by_statuses(self, _statuses):
            return {"doc-known": {"file_path": "study.pdf", "metadata": {}}}

    result = asyncio.run(_enrich_references_with_source_metadata(
        SimpleNamespace(doc_status=DocStatus()),
        [{"reference_id": "1", "file_path": "study.pdf"}],
    ))
    assert result[0]["document_id"] == "doc-known"
