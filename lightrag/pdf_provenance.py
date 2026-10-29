"""Deterministic PDF page provenance for legacy text chunks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lightrag.evidence_quotes import normalized_with_offsets


def page_ranges_from_text(pages: list[str]) -> list[dict[str, int]]:
    """Offsets into the exact text produced by the legacy PDF parser."""
    result = []
    offset = 0
    for page_number, page in enumerate(pages, start=1):
        end = offset + len(page)
        result.append({"page": page_number, "start": offset, "end": end})
        offset = end + 1  # The legacy parser joins pages with one newline.
    return result


def sanitized_page_ranges(pages: list[str]) -> list[dict[str, int]]:
    """Shift legacy page offsets after the enqueue-time whitespace trim."""
    from lightrag.utils import sanitize_text_for_encoding

    raw = "".join(page + "\n" for page in pages)
    cleaned = sanitize_text_for_encoding(raw)
    if not cleaned or cleaned != raw.strip():
        return []
    prefix = len(raw) - len(raw.lstrip())
    ranges = []
    for item in page_ranges_from_text(pages):
        start = max(0, item["start"] - prefix)
        end = min(len(cleaned), item["end"] - prefix)
        if start < end:
            ranges.append({**item, "start": start, "end": end})
    return ranges


def page_ranges_from_sidecar(
    blocks_path: Path, document_text: str
) -> list[dict[str, int]]:
    """Map sidecar block positions into its merged text without guessing pages."""
    blocks = []
    with blocks_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("type") == "content" and str(row.get("content") or "").strip():
                blocks.append(row)
    if "\n\n".join(str(row["content"]) for row in blocks) != document_text:
        return []
    result = []
    offset = 0
    for row in blocks:
        end = offset + len(row["content"])
        pages = set()
        for position in row.get("positions") or []:
            anchor = str(position.get("anchor") or "")
            if position.get("type") == "bbox" and anchor.isdecimal():
                page = int(anchor)
                if page > 0:
                    pages.add(page)
        result.extend(
            {"page": page, "start": offset, "end": end}
            for page in sorted(pages)
        )
        offset = end + 2
    return result


def attach_pdf_page_locations(
    chunks: dict[str, dict[str, Any]],
    document_text: str,
    page_ranges: list[dict[str, int]],
) -> None:
    """Attach page spans only for a unique verbatim normalized chunk match."""
    normalized, offsets = normalized_with_offsets(document_text)
    if (
        not normalized
        or not offsets
        or not page_ranges
        or max(item["end"] for item in page_ranges) != len(document_text)
    ):
        return
    for chunk in chunks.values():
        chunk_text = chunk.get("content") or ""
        needle, _ = normalized_with_offsets(chunk_text)
        if len(needle) < 18:
            continue
        found = normalized.find(needle)
        if found < 0 or normalized.find(needle, found + 1) >= 0:
            continue
        start = offsets[found]
        end = offsets[found + len(needle) - 1] + 1
        pages = list(dict.fromkeys(
            item["page"]
            for item in page_ranges
            if start < item["end"] and end > item["start"]
        ))
        if pages:
            chunk["pdf_location"] = {
                "page": pages[0],
                "pages": pages,
                "status": "chunk_text_match",
            }
