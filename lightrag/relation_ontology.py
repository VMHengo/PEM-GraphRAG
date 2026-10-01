"""Small, deterministic relation ontology shared by extraction and evaluation.

The graph keeps the extractor's original evidence, but relation labels are not
always expressed with exactly the same surface form.  This module centralises
the conservative normalisation and similarity rules used to compare labels.
It intentionally does not decide whether a relation is true; that remains the
responsibility of the extraction prompt and the benchmark's reviewed gold data.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


def normalize_relation_label(value: object, default: str = "related_to") -> str:
    """Return a stable, storage-friendly relation label."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or default


_RELATION_ALIASES = {
    "affect": "affects",
    "cause": "causes",
    "collaborate_with": "collaborates_with",
    "compared_to": "compared_with",
    "depend_on": "depends_on",
    "degrade": "degrades",
    "evidence_for": "evidenced_by",
    "follow": "follows",
    "influence": "influences",
    "lead_to": "leads_to",
    "measure": "measures",
    "optimize": "optimizes",
    "precede": "precedes",
    "produce": "produces",
    "publish_by": "published_by",
    "require": "requires",
    "result_in": "results_in",
    "study": "studies",
    "support": "supports",
    "use": "uses",
}

# These labels express the same predicate in the opposite grammatical order.
# They are deliberately limited to clear ``*_by`` forms.  We do not infer an
# inverse for structural predicates such as ``part_of`` because projects may
# choose different ontological conventions for them.
_INVERSE_RELATION_ALIASES = {
    "affected_by": "affects",
    "caused_by": "causes",
    "influenced_by": "influences",
    "resulted_from": "results_in",
    "produced_by": "produces",
    "used_by": "uses",
    "required_by": "requires",
    "supported_by": "supports",
    "described_by": "described_in",
}


def canonical_relation_type(value: object, *, keywords: object = None) -> str:
    """Canonicalise one predicate without changing its endpoint orientation."""

    for candidate in (value, keywords):
        for part in re.split(r"[,;|]", str(candidate or "")):
            label = normalize_relation_label(part, "")
            if label:
                return _INVERSE_RELATION_ALIASES.get(
                    label, _RELATION_ALIASES.get(label, label)
                )
    return "related_to"


def canonicalize_relation(
    source: object,
    target: object,
    relation_type: object,
    *,
    keywords: object = None,
    normalize_inverse: bool = True,
) -> tuple[str, str, str, bool]:
    """Return semantic endpoints and predicate plus whether endpoints flipped.

    The endpoint swap is only used for unambiguous inverse surface forms.  It
    lets a later directed traversal treat ``B caused_by A`` as ``A causes B``
    while keeping legacy rows and regular relation labels backwards compatible.
    """

    raw_value = relation_type if str(relation_type or "").strip() else keywords
    raw_part = re.split(r"[,;|]", str(raw_value or ""))[0]
    raw_label = normalize_relation_label(raw_part, "")
    inverse = normalize_inverse and raw_label in _INVERSE_RELATION_ALIASES
    canonical_type = canonical_relation_type(relation_type, keywords=keywords)
    source_text = str(source or "")
    target_text = str(target or "")
    if inverse:
        return target_text, source_text, canonical_type, True
    return source_text, target_text, canonical_type, False


_PREDICATE_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"causes", "results_in", "leads_to"}),
    frozenset({"affects", "influences", "degrades", "increases", "decreases"}),
    frozenset({"uses", "requires", "depends_on"}),
    frozenset({"produces", "contains", "part_of"}),
    frozenset({"published_by", "authored_by", "described_in", "evidenced_by"}),
)


def _accepted_score(actual: str, accepted: object) -> float | None:
    """Resolve benchmark-provided accepted predicates, if configured."""

    if isinstance(accepted, Mapping):
        for value, score in accepted.items():
            if canonical_relation_type(value) == actual:
                try:
                    return max(0.0, min(1.0, float(score)))
                except (TypeError, ValueError):
                    return 1.0
        return None
    if isinstance(accepted, Sequence) and not isinstance(accepted, str):
        return 1.0 if actual in {canonical_relation_type(item) for item in accepted} else None
    return None


@dataclass(frozen=True)
class PredicateSimilarity:
    score: float
    expected: str
    actual: str
    exact: bool
    reason: str


def predicate_similarity(
    expected: object,
    actual: object,
    *,
    accepted_relation_types: object = None,
) -> PredicateSimilarity:
    """Score ontology-compatible predicates without treating them as exact.

    Exact labels score 1.0.  Benchmark authors can explicitly grant full or
    weighted credit through ``accepted_relation_types``.  Otherwise, closely
    related causal/effect labels receive partial credit; unrelated labels do
    not receive accidental points merely because both occur in a graph.
    """

    expected_type = canonical_relation_type(expected)
    actual_type = canonical_relation_type(actual)
    if expected_type == actual_type:
        return PredicateSimilarity(1.0, expected_type, actual_type, True, "exact")

    accepted = _accepted_score(actual_type, accepted_relation_types)
    if accepted is not None:
        return PredicateSimilarity(
            accepted,
            expected_type,
            actual_type,
            accepted >= 1.0,
            "benchmark_accepted",
        )

    expected_family = next(
        (family for family in _PREDICATE_FAMILIES if expected_type in family), None
    )
    actual_family = next(
        (family for family in _PREDICATE_FAMILIES if actual_type in family), None
    )
    if expected_family is not None and expected_family == actual_family:
        # Effects and causation are related but not fully interchangeable. A
        # benchmark can override this conservative default when appropriate.
        return PredicateSimilarity(0.78, expected_type, actual_type, False, "same_family")
    if {expected_family, actual_family} == {
        _PREDICATE_FAMILIES[0],
        _PREDICATE_FAMILIES[1],
    }:
        return PredicateSimilarity(0.55, expected_type, actual_type, False, "causal_effect_family")
    return PredicateSimilarity(0.0, expected_type, actual_type, False, "unrelated")
