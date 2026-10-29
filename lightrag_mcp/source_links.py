"""Build browser links to retained PDFs without exposing internal service URLs."""

from urllib.parse import quote, urlparse


def source_pdf_url(public_base_url: str, document_id: str | None) -> str | None:
    parsed = urlparse(public_base_url)
    if not document_id or parsed.scheme != "https" or not parsed.netloc:
        return None
    return f"{public_base_url.rstrip('/')}/documents/{quote(document_id, safe='')}/source-pdf"
