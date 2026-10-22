"""Storage-agnostic helpers for assertions stored on pair-based graph edges.

Graph backends still store one edge for an unordered entity pair.  The
``relation_assertions_json`` scalar preserves the individual semantic
relations represented by that edge without requiring backend-specific value
types.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Set
from typing import Any

from lightrag.constants import GRAPH_FIELD_SEP
from lightrag.relation_identity import relation_identity
from lightrag.utils import compute_mdhash_id


RELATION_ASSERTIONS_FIELD = "relation_assertions_json"


def assertion_retrieval_enabled() -> bool:
    return os.environ.get("ONTOLOGY_ASSERTION_RETRIEVAL_ENABLED", "false").lower() in {
        "1", "true", "yes", "on"
    }

_CORE_FIELDS = (
    "semantic_src_id",
    "semantic_tgt_id",
    "relation_type",
    "directionality",
)
_OPTIONAL_FIELDS = (
    "raw_relation_type",
    "description",
    "evidence",
    "keywords",
    "source_id",
    "file_path",
    "ontology_iri",
    "ontology_mapping_status",
    "ontology_mapping_version",
    "ontology_source",
    "relation_importance",
    "chain_role",
    "weight",
    "direction_confidence",
    "direction_rationale",
    # Accept shorter names as well so callers do not lose upstream metadata.
    "ontology_status",
    "ontology_version",
)
_ASSERTION_FIELDS = _CORE_FIELDS + _OPTIONAL_FIELDS


def _text(value: object) -> str:
    return str(value or "").strip()


def _is_json_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _normalise_assertion(
    assertion: Mapping[str, Any],
    source: str = "",
    target: str = "",
) -> dict[str, Any] | None:
    """Copy supported flat fields and fill endpoint/identity defaults."""

    if any(
        key in assertion and not _is_json_scalar(assertion[key])
        for key in _ASSERTION_FIELDS
    ):
        return None

    result = {
        key: assertion[key]
        for key in _ASSERTION_FIELDS
        if key in assertion and assertion[key] is not None
    }
    result["semantic_src_id"] = _text(result.get("semantic_src_id")) or _text(
        source
    )
    result["semantic_tgt_id"] = _text(result.get("semantic_tgt_id")) or _text(
        target
    )
    result["relation_type"] = _text(result.get("relation_type")) or "related_to"
    result["directionality"] = (
        _text(result.get("directionality")) or "unknown"
    )

    # ``source_chunk_id`` is accepted as an input compatibility spelling, but
    # persisted assertions use the graph's established ``source_id`` name.
    if not _text(result.get("source_id")):
        source_chunk_id = assertion.get("source_chunk_id")
        if source_chunk_id is not None:
            if not _is_json_scalar(source_chunk_id):
                return None
            result["source_id"] = source_chunk_id

    return result


def relation_assertion_identity(
    source: str,
    target: str,
    assertion: Mapping[str, Any],
) -> str:
    """Return stable identity for one semantic relation assertion.

    The existing relation identity separates predicate and direction.  A
    source chunk suffix makes repeated extraction idempotent while preserving
    independently supported assertions of the same semantic relation.
    """

    semantic_identity = relation_identity(source, target, assertion)
    source_id = _text(
        assertion.get("source_id") or assertion.get("source_chunk_id")
    )
    return GRAPH_FIELD_SEP.join((semantic_identity, source_id))


def make_assertion_vdb_id(
    source: str, target: str, assertion: Mapping[str, Any]
) -> str:
    """Stable vector key for a predicate, direction and source chunk."""

    return compute_mdhash_id(
        relation_assertion_identity(source, target, assertion), prefix="assert-"
    )


def _legacy_assertions(
    edge: Mapping[str, Any], source: str, target: str
) -> list[dict[str, Any]]:
    base = _normalise_assertion(edge, source, target)
    if base is None:
        return []

    raw_source_ids = edge.get("source_id")
    if isinstance(raw_source_ids, str):
        source_ids = [
            value for value in raw_source_ids.split(GRAPH_FIELD_SEP) if value
        ]
    elif _is_json_scalar(raw_source_ids) and raw_source_ids is not None:
        source_ids = [_text(raw_source_ids)]
    else:
        source_ids = []

    if not source_ids:
        return [base]

    raw_paths = edge.get("file_path")
    paths = raw_paths.split(GRAPH_FIELD_SEP) if isinstance(raw_paths, str) else []
    pair_paths = len(paths) == len(source_ids)
    assertions = []
    for index, source_id in enumerate(source_ids):
        assertion = dict(base)
        assertion["source_id"] = source_id
        if pair_paths:
            assertion["file_path"] = paths[index]
        assertions.append(assertion)
    return assertions


def parse_relation_assertions(
    edge: Mapping[str, Any],
    source: str = "",
    target: str = "",
) -> list[dict[str, Any]]:
    """Parse assertions from an edge, falling back only for legacy edges.

    Presence of ``relation_assertions_json`` marks the edge as new-schema.
    Invalid JSON, a non-list value, or any malformed assertion raises rather
    than silently dropping persisted facts or reviving lossy legacy metadata.
    """

    if RELATION_ASSERTIONS_FIELD not in edge:
        return _legacy_assertions(edge, source, target)

    raw_assertions = edge.get(RELATION_ASSERTIONS_FIELD)
    if not isinstance(raw_assertions, str):
        raise ValueError("Invalid relation assertions: expected JSON string")
    try:
        decoded = json.loads(raw_assertions)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid relation assertions JSON") from exc
    if not isinstance(decoded, list):
        raise ValueError("Invalid relation assertions: expected list")

    assertions: list[dict[str, Any]] = []
    for value in decoded:
        if not isinstance(value, Mapping):
            raise ValueError("Invalid relation assertion record")
        assertion = _normalise_assertion(value, source, target)
        if assertion is None:
            raise ValueError("Invalid relation assertion properties")
        assertions.append(assertion)
    return assertions


def _deduplicate_assertions(
    assertions: Iterable[Mapping[str, Any]],
    source: str,
    target: str,
) -> list[dict[str, Any]]:
    by_identity: dict[str, dict[str, Any]] = {}
    for value in assertions:
        assertion = _normalise_assertion(value, source, target)
        if assertion is None:
            continue
        identity = relation_assertion_identity(source, target, assertion)
        if identity in by_identity:
            merged = by_identity[identity]
            merged.update(
                {
                    key: item
                    for key, item in assertion.items()
                    if item not in (None, "")
                    or key in ("ontology_iri", "ontology_source")
                }
            )
        else:
            by_identity[identity] = assertion
    return [by_identity[key] for key in sorted(by_identity)]


def merge_relation_assertions(
    existing_edge: Mapping[str, Any] | None,
    new_assertions: Iterable[Mapping[str, Any]],
    source: str = "",
    target: str = "",
) -> list[dict[str, Any]]:
    """Merge persisted/legacy and newly extracted assertions idempotently."""

    existing = (
        parse_relation_assertions(existing_edge, source, target)
        if existing_edge is not None
        else []
    )
    return _deduplicate_assertions((*existing, *new_assertions), source, target)


def filter_relation_assertions(
    assertions: Iterable[Mapping[str, Any]],
    deleted_chunk_ids: Set[str],
    source: str = "",
    target: str = "",
) -> list[dict[str, Any]]:
    """Remove assertions whose source chunk is in ``deleted_chunk_ids``."""

    deleted = {_text(chunk_id) for chunk_id in deleted_chunk_ids}
    retained = [
        assertion
        for assertion in assertions
        if _text(assertion.get("source_id") or assertion.get("source_chunk_id"))
        not in deleted
    ]
    return _deduplicate_assertions(retained, source, target)


def serialize_relation_assertions(
    assertions: Iterable[Mapping[str, Any]],
    source: str = "",
    target: str = "",
) -> str:
    """Serialize assertions as a deterministic flat graph property value."""

    canonical = _deduplicate_assertions(assertions, source, target)
    return json.dumps(
        canonical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
