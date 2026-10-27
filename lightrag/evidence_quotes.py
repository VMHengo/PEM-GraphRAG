"""Locate exact extracted text while tolerating PDF whitespace and dash variants."""

from __future__ import annotations


_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2212"


def normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            if char in "\r\n" and normalized and normalized[-1] == "-":
                continue
            if normalized and normalized[-1] != " ":
                normalized.append(" ")
                offsets.append(index)
        else:
            for folded in "-" if char in _DASHES else char.casefold():
                normalized.append(folded)
                offsets.append(index)
    while normalized and normalized[-1] == " ":
        normalized.pop()
        offsets.pop()
    return "".join(normalized), offsets


def locate_exact_quote(content: str, quote: str) -> dict[str, object] | None:
    """Return offsets in source content, never the unverified supplied quote."""

    if not content or not quote or len(quote.strip()) < 8:
        return None
    normalized, offsets = normalized_with_offsets(content)
    needle, _ = normalized_with_offsets(quote.strip())
    start = normalized.find(needle)
    if start < 0 or not needle:
        return None
    left, right = offsets[start], offsets[start + len(needle) - 1] + 1
    return {
        "text": content[left:right],
        "start": left,
        "end": right,
        "status": "exact_text_match",
    }
