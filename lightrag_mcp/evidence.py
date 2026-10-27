"""Source-text matches for review; matching text does not verify a relation."""

from __future__ import annotations

import re

from lightrag.constants import GRAPH_FIELD_SEP
from lightrag.evidence_quotes import locate_exact_quote, normalized_with_offsets

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|\n\s*\n")
_WORD = re.compile(r"[\w-]{4,}", re.UNICODE)
_STOP = frozenset(
    {
        "that",
        "this",
        "with",
        "from",
        "during",
        "which",
        "under",
        "between",
        "through",
        "becomes",
        "strongly",
        "more",
        "than",
        "their",
        "there",
        "have",
        "also",
        "into",
    }
)


def _sentence_bounds(content: str) -> list[tuple[int, int]]:
    bounds = []
    cursor = 0
    for separator in _SENTENCE_BREAK.finditer(content):
        if separator.start() > cursor:
            bounds.append((cursor, separator.start()))
        cursor = separator.end()
    if cursor < len(content):
        bounds.append((cursor, len(content)))
    return bounds


def propose_relation_span(
    content: str,
    source: str,
    target: str,
    *,
    description: str = "",
    evidence_quote: str = "",
) -> dict[str, object] | None:
    """Locate a quote, description or co-mention without asserting entailment."""

    if not content:
        return None
    for quote in (evidence_quote, *description.split(GRAPH_FIELD_SEP)):
        match = locate_exact_quote(content, quote)
        if match:
            return match
    if not source.strip() or not target.strip():
        return None
    source_name, _ = normalized_with_offsets(source.strip())
    target_name, _ = normalized_with_offsets(target.strip())
    for left, right in _sentence_bounds(content):
        sentence = content[left:right]
        normalized, _ = normalized_with_offsets(sentence)
        if source_name in normalized and target_name in normalized:
            return {
                "text": sentence[:700],
                "start": left,
                "end": right,
                "status": "candidate_mention_only",
            }
    description_text = description.split(GRAPH_FIELD_SEP)[0]
    terms = {
        word for word in _WORD.findall(description_text.casefold()) if word not in _STOP
    }
    if len(terms) >= 2:
        candidates = []
        for left, right in _sentence_bounds(content):
            sentence_terms = set(_WORD.findall(content[left:right].casefold()))
            overlap = len(terms & sentence_terms)
            if overlap >= 2 and overlap / len(terms) >= 0.4:
                candidates.append((overlap / len(terms), overlap, left, right))
        if candidates:
            _, _, left, right = max(candidates)
            return {
                "text": content[left:right][:700],
                "start": left,
                "end": right,
                "status": "candidate_related_text",
            }
    return None


def propose_relation_context(
    content: str,
    source: str,
    target: str,
    *,
    max_characters: int = 1500,
    description: str = "",
    evidence_quote: str = "",
) -> dict[str, object] | None:
    """Show neighboring sentences around a text match, without verifying it."""

    span = propose_relation_span(
        content,
        source,
        target,
        description=description,
        evidence_quote=evidence_quote,
    )
    if span is None:
        return None
    bounds = _sentence_bounds(content)
    index = next(
        (i for i, (left, right) in enumerate(bounds) if left <= span["start"] < right),
        None,
    )
    if index is None:
        return None
    paragraph = len(re.findall(r"\n\s*\n", content[: bounds[index][0]]))
    neighbors = [
        position
        for position in range(max(0, index - 1), min(len(bounds), index + 2))
        if len(re.findall(r"\n\s*\n", content[: bounds[position][0]])) == paragraph
    ]
    left = bounds[neighbors[0]][0]
    right = bounds[neighbors[-1]][1]
    if right - left > max_characters:
        left = max(left, span["start"] - 250)
        right = min(right, left + max_characters)
        if right < span["end"]:
            right = min(len(content), span["end"])
            left = max(0, right - max_characters)
    return {
        "text": content[left:right],
        "match_start": max(0, span["start"] - left),
        "match_end": min(right - left, span["end"] - left),
        "status": span["status"],
    }
