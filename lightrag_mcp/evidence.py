"""Conservative, non-verifying source-span proposals for graph assertions."""

from __future__ import annotations

import re


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def propose_relation_span(
    content: str, source: str, target: str
) -> dict[str, object] | None:
    """Locate a sentence mentioning both labels, without claiming entailment."""

    if not content or not source.strip() or not target.strip():
        return None
    cursor = 0
    for sentence in _SENTENCE_BREAK.split(content):
        start = content.find(sentence, cursor)
        if start < 0:
            continue
        cursor = start + len(sentence)
        normalized = " ".join(sentence.casefold().split())
        source_name = " ".join(source.casefold().split())
        target_name = " ".join(target.casefold().split())
        if source_name in normalized and target_name in normalized:
            return {
                "text": sentence[:700],
                "start": start,
                "end": start + len(sentence),
                "status": "candidate_mention_only",
            }
    return None


def propose_relation_context(
    content: str, source: str, target: str, *, max_characters: int = 1500
) -> dict[str, object] | None:
    """Show neighboring extracted sentences around a co-mention, without verifying it."""

    span = propose_relation_span(content, source, target)
    if span is None:
        return None
    bounds: list[tuple[int, int]] = []
    cursor = 0
    for separator in _SENTENCE_BREAK.finditer(content):
        if separator.start() > cursor:
            bounds.append((cursor, separator.start()))
        cursor = separator.end()
    if cursor < len(content):
        bounds.append((cursor, len(content)))
    index = next(
        (i for i, (left, right) in enumerate(bounds)
         if left <= span["start"] < right),
        None,
    )
    if index is None:
        return None
    left = bounds[max(0, index - 1)][0]
    right = bounds[min(len(bounds) - 1, index + 1)][1]
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
        "status": "candidate_mention_only",
    }
