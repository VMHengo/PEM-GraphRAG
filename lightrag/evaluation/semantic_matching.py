"""Deterministic partial matching primitives for benchmark evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lightrag.relation_ontology import canonical_relation_type, predicate_similarity


def canonical_text(value: object) -> str:
    return " ".join(
        part for part in "".join(
            char.lower() if char.isalnum() else " " for char in str(value or "")
        ).split()
        if part
    )


def _tokens(value: object) -> set[str]:
    return set(canonical_text(value).split())


def _expected_value(value: object) -> tuple[str, list[str]]:
    if isinstance(value, Mapping):
        name = str(value.get("name") or value.get("value") or value.get("entity") or "")
        aliases = [str(alias) for alias in value.get("aliases") or []]
        return name, aliases
    return str(value or ""), []


@dataclass(frozen=True)
class TextMatch:
    score: float
    exact: bool
    expected: str
    actual: str
    reason: str


def text_match(expected: object, actual: object, *, aliases: object = None) -> TextMatch:
    """Score names using explicit aliases, then a conservative token overlap."""

    expected_text, embedded_aliases = _expected_value(expected)
    all_aliases = embedded_aliases + [str(alias) for alias in aliases or []]
    expected_canonical = canonical_text(expected_text)
    actual_canonical = canonical_text(actual)
    candidates = [expected_canonical] + [canonical_text(alias) for alias in all_aliases]
    candidates = [candidate for candidate in candidates if candidate]
    if not actual_canonical or not candidates:
        return TextMatch(0.0, False, expected_text, str(actual or ""), "empty")
    if actual_canonical in candidates:
        return TextMatch(1.0, True, expected_text, str(actual), "exact_or_alias")

    best = 0.0
    for candidate in candidates:
        expected_tokens = _tokens(candidate)
        actual_tokens = _tokens(actual_canonical)
        if not expected_tokens or not actual_tokens:
            continue
        if expected_tokens <= actual_tokens or actual_tokens <= expected_tokens:
            best = max(best, 0.85)
            continue
        overlap = len(expected_tokens & actual_tokens)
        f1 = (2 * overlap) / (len(expected_tokens) + len(actual_tokens))
        if f1 >= 0.5:
            best = max(best, round(0.35 + 0.5 * f1, 4))
    return TextMatch(best, False, expected_text, str(actual or ""), "token_overlap" if best else "no_match")


def _edge_value(edge: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = edge.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def edge_semantics(edge: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return semantic edge endpoints for legacy and newly normalised rows."""

    return (
        _edge_value(edge, "semantic_src_id", "source", "src_id"),
        _edge_value(edge, "semantic_tgt_id", "target", "tgt_id"),
        canonical_relation_type(edge.get("relation_type"), keywords=edge.get("keywords")),
    )


def relation_match(expected: Mapping[str, Any], edge: Mapping[str, Any]) -> dict[str, Any]:
    """Return exact and semantic relation scores with component diagnostics."""

    source, target, relation_type = edge_semantics(edge)
    source_match = text_match(expected.get("source"), source, aliases=expected.get("source_aliases"))
    target_match = text_match(expected.get("target"), target, aliases=expected.get("target_aliases"))
    expected_type = expected.get("relation_type") or ""
    predicate = predicate_similarity(
        expected_type,
        relation_type,
        accepted_relation_types=expected.get("accepted_relation_types"),
    )
    expected_direction = canonical_text(expected.get("directionality"))
    actual_direction = canonical_text(edge.get("directionality") or "unknown")
    direction_score = 1.0 if not expected_direction else float(expected_direction == actual_direction)
    endpoint_score = (source_match.score + target_match.score) / 2
    score = 0.5 * endpoint_score + 0.4 * predicate.score + 0.1 * direction_score
    exact = (
        source_match.exact
        and target_match.exact
        and predicate.exact
        and direction_score == 1.0
    )
    return {
        "score": round(score, 4),
        "exact": exact,
        "source": source_match.__dict__,
        "target": target_match.__dict__,
        "predicate": predicate.__dict__,
        "direction_score": direction_score,
        "matched": {
            "source": source,
            "relation_type": relation_type,
            "target": target,
            "directionality": edge.get("directionality"),
            "relation_importance": edge.get("relation_importance"),
            "chain_role": edge.get("chain_role"),
            "description": edge.get("description") or "",
        },
    }


def _path_nodes(expected: Mapping[str, Any]) -> list[object]:
    nodes = expected.get("traversal_nodes") or expected.get("nodes") or []
    return list(nodes) if isinstance(nodes, Sequence) and not isinstance(nodes, str) else []


def _path_types(expected: Mapping[str, Any]) -> list[object]:
    value = expected.get("relation_types") or []
    return list(value) if isinstance(value, Sequence) and not isinstance(value, str) else []


def _path_accepted_types(expected: Mapping[str, Any], index: int) -> object:
    accepted = expected.get("accepted_relation_types")
    if isinstance(accepted, Sequence) and not isinstance(accepted, str):
        if accepted and all(isinstance(item, (list, tuple, dict)) for item in accepted):
            return accepted[index] if index < len(accepted) else None
    return accepted


def _documents_score(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> float:
    expected_documents = list(expected.get("source_documents") or [])
    actual_documents = [str(item) for item in actual.get("file_paths") or []]
    if not expected_documents:
        return 1.0
    matches = [
        any(text_match(document, candidate).score >= 0.85 for candidate in actual_documents)
        for document in expected_documents
    ]
    return sum(matches) / len(matches)


def path_match(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    traversal_direction: str = "both",
) -> dict[str, Any]:
    """Score a diagnostic path edge-by-edge while preserving strict exactness."""

    expected_nodes = _path_nodes(expected)
    expected_types = _path_types(expected)
    actual_nodes = list(actual.get("nodes") or [])
    actual_edges = [edge for edge in actual.get("edges") or [] if isinstance(edge, Mapping)]
    expected_edges = min(len(expected_types), max(0, len(expected_nodes) - 1))
    if expected_edges == 0:
        return {
            "score": 0.0,
            "edge_recall": 0.0,
            "predicate_score": 0.0,
            "direction_accuracy": 0.0,
            "continuity_score": 0.0,
            "document_coverage": _documents_score(expected, actual),
            "citation_coverage": (
                1.0
                if not expected.get("require_citations")
                else float(
                    bool(
                        [
                            item
                            for item in actual.get("reference_ids") or []
                            if str(item).strip()
                        ]
                    )
                )
            ),
            "edge_matches": [],
        }

    matches: list[dict[str, Any]] = []
    cursor = 0
    for index in range(expected_edges):
        expected_source = expected_nodes[index]
        expected_target = expected_nodes[index + 1]
        expected_type = expected_types[index]
        best: dict[str, Any] | None = None
        best_index = -1
        for actual_index in range(cursor, len(actual_edges)):
            edge = dict(actual_edges[actual_index])
            semantic_source, semantic_target, semantic_type = edge_semantics(edge)
            # ``DirectedPath.nodes`` follows the requested traversal order.
            # An inbound root-cause path therefore lists effect -> cause while
            # the stored semantic edge remains cause -> effect.
            traversal_source = (
                str(actual_nodes[actual_index])
                if actual_index < len(actual_nodes)
                else semantic_source
            )
            traversal_target = (
                str(actual_nodes[actual_index + 1])
                if actual_index + 1 < len(actual_nodes)
                else semantic_target
            )
            source = text_match(
                expected_source,
                traversal_source,
                aliases=(expected.get("node_aliases") or {}).get(str(index), [])
                if isinstance(expected.get("node_aliases"), Mapping)
                else None,
            )
            target = text_match(
                expected_target,
                traversal_target,
                aliases=(expected.get("node_aliases") or {}).get(str(index + 1), [])
                if isinstance(expected.get("node_aliases"), Mapping)
                else None,
            )
            predicate = predicate_similarity(
                expected_type,
                semantic_type,
                accepted_relation_types=_path_accepted_types(expected, index),
            )
            edge_score = 0.3 * source.score + 0.3 * target.score + 0.4 * predicate.score
            candidate = {
                "expected_index": index,
                "actual_index": actual_index,
                "score": round(edge_score, 4),
                "source_score": source.score,
                "target_score": target.score,
                "predicate_score": predicate.score,
                "predicate_exact": predicate.exact,
                "actual": {
                    "source": semantic_source,
                    "target": semantic_target,
                    "traversal_source": traversal_source,
                    "traversal_target": traversal_target,
                    "relation_type": semantic_type,
                },
            }
            if best is None or candidate["score"] > best["score"]:
                best, best_index = candidate, actual_index
        if best is None:
            matches.append({"expected_index": index, "score": 0.0, "predicate_score": 0.0})
        else:
            matches.append(best)
            cursor = best_index + 1

    edge_recall = sum(float(item["score"]) for item in matches) / expected_edges
    predicate_score = sum(float(item.get("predicate_score", 0.0)) for item in matches) / expected_edges
    actual_indices = [item.get("actual_index") for item in matches if item.get("actual_index") is not None]
    continuity_score = (
        1.0
        if expected_edges == 1 and actual_indices
        else (
            sum(
                1
                for left, right in zip(actual_indices, actual_indices[1:])
                if right == left + 1
            )
            / max(1, expected_edges - 1)
            if len(actual_indices) >= 2
            else 0.0
        )
    )
    direction_scores: list[float] = []
    for item in matches:
        matched_edge = item.get("actual") or {}
        semantic_source = canonical_text(matched_edge.get("source"))
        semantic_target = canonical_text(matched_edge.get("target"))
        traversal_source = canonical_text(matched_edge.get("traversal_source"))
        traversal_target = canonical_text(matched_edge.get("traversal_target"))
        if not semantic_source or not semantic_target:
            # Legacy diagnostics exposed relation labels but not semantic
            # endpoints. Their route check still proves requested traversal;
            # do not downgrade an otherwise exact historical result.
            direction_scores.append(1.0)
        elif traversal_direction == "out":
            direction_scores.append(
                float(semantic_source == traversal_source and semantic_target == traversal_target)
            )
        elif traversal_direction == "in":
            direction_scores.append(
                float(semantic_source == traversal_target and semantic_target == traversal_source)
            )
        else:
            direction_scores.append(
                float(
                    (semantic_source == traversal_source and semantic_target == traversal_target)
                    or (semantic_source == traversal_target and semantic_target == traversal_source)
                )
            )
    direction_accuracy = sum(direction_scores) / len(direction_scores) if direction_scores else 0.0
    document_coverage = _documents_score(expected, actual)
    citation_coverage = (
        1.0
        if not expected.get("require_citations")
        else float(bool([item for item in actual.get("reference_ids") or [] if str(item).strip()]))
    )
    evidence_coverage = (document_coverage + citation_coverage) / 2
    score = (
        0.55 * edge_recall
        + 0.15 * continuity_score
        + 0.15 * direction_accuracy
        + 0.15 * evidence_coverage
    )
    return {
        "score": round(score, 4),
        "edge_recall": round(edge_recall, 4),
        "predicate_score": round(predicate_score, 4),
        "direction_accuracy": round(direction_accuracy, 4),
        "continuity_score": round(continuity_score, 4),
        "document_coverage": round(document_coverage, 4),
        "citation_coverage": round(citation_coverage, 4),
        "edge_matches": matches,
    }
