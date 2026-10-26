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
