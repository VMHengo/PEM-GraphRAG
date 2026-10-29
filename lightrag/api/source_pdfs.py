"""Resolve retained original PDFs and locate review excerpts without trusting URLs."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from lightrag.constants import PARSED_DIR_NAME


def resolve_source_pdf(input_dir: Path, stored_file_path: str) -> Path | None:
    """Return one retained PDF matching a document's stored canonical basename."""
    if (
        not stored_file_path
        or Path(stored_file_path).name != stored_file_path
        or Path(stored_file_path).suffix.lower() != ".pdf"
    ):
        return None
    root = input_dir.resolve()
    exact = []
    variants = []
    for directory in (input_dir, input_dir / PARSED_DIR_NAME):
        if not directory.is_dir():
            continue
        for candidate in directory.iterdir():
            if candidate.suffix.lower() != ".pdf" or not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                continue
            if candidate.name == stored_file_path:
                exact.append(resolved)
            elif re.sub(r"_\d{3}$", "", candidate.stem) + candidate.suffix == stored_file_path:
                variants.append(resolved)
    # An ambiguous archive is not evidence that any particular copy belongs to this ID.
    matches = exact or variants
    return matches[0] if len(matches) == 1 else None


def locate_source_page(path: Path, quote: str) -> tuple[int | None, str]:
    """Find a page containing the quoted text; never claim a PDF highlight."""
    normalized = re.sub(r"\s+", " ", quote).strip().casefold()
    if len(normalized) < 20:
        return None, "insufficient_quote"
    if path.stat().st_size > 50_000_000:
        return None, "too_large"
    reader = PdfReader(str(path))
    if len(reader.pages) > 500:
        return None, "too_many_pages"
    for index, page in enumerate(reader.pages):
        page_text = re.sub(r"\s+", " ", page.extract_text() or "").casefold()
        if normalized in page_text:
            return index + 1, "exact_text_match"
    return None, "not_found"
