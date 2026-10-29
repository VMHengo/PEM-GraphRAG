from lightrag_mcp.source_links import source_pdf_url
from lightrag_mcp.lightrag_client import build_citations


def test_source_link_requires_public_https_and_document_id():
    assert source_pdf_url("https://lightrag-staging.example.org/", "doc-123") == (
        "https://lightrag-staging.example.org/documents/doc-123/source-pdf"
    )
    assert source_pdf_url("http://lightrag:9621", "doc-123") is None
    assert source_pdf_url("https://lightrag.example.org", None) is None


def test_citation_retains_external_url_and_adds_protected_pdf(monkeypatch):
    monkeypatch.setenv("LIGHTRAG_PUBLIC_WEBUI_BASE_URL", "https://lightrag-staging.example.org")
    citation = build_citations([{
        "document_id": "doc-123", "file_path": "paper.pdf",
        "source_url": "https://publisher.example.org/paper",
    }])[0]
    assert citation["url"] == "https://publisher.example.org/paper"
    assert citation["pdf_url"] == "https://lightrag-staging.example.org/documents/doc-123/source-pdf"
