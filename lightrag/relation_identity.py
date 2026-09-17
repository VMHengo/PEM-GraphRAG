"""Compatibility-safe identifiers for semantically directed relationships.

The legacy LightRAG graph treats an edge as an unordered node pair.  Directed
retrieval needs a stronger identity for vector and chunk-tracking records, but
must still be able to read those historical pair-based records.  This module is
intentionally storage-agnostic: it does not alter graph storage semantics.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from lightrag.constants import GRAPH_FIELD_SEP
from lightrag.utils import compute_mdhash_id, make_relation_vdb_ids


RELATION_IDENTITY_VERSION = "rel-v2"


def _text(value: object) -> str:
    return str(value or "").strip()


def _slug(value: object, default: str) -> str:
    text = unicodedata.normalize("NFKC", _text(value)).casefold()
    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or default


def semantic_relation_endpoints(
    source: str,
    target: str,
    relation: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Return extractor-preserved endpoints when relation metadata supplies them."""

    relation = relation or {}
    semantic_source = _text(relation.get("semantic_src_id")) or _text(source)
    semantic_target = _text(relation.get("semantic_tgt_id")) or _text(target)
    return semantic_source, semantic_target


def relation_identity(
    source: str,
    target: str,
    relation: Mapping[str, Any] | None = None,
) -> str:
    """Return a deterministic identity including direction and predicate.

    Directed relations retain semantic endpoint order.  Symmetric and legacy
    relations preserve stable pair ordering, which makes their identity
    compatible with the existing graph model while still separating predicates.
    """

    relation = relation or {}
    semantic_source, semantic_target = semantic_relation_endpoints(
        source, target, relation
    )
    directionality = _slug(relation.get("directionality"), "unknown")
    relation_type = _slug(relation.get("relation_type"), "related_to")
    if directionality != "directed":
        semantic_source, semantic_target = sorted((semantic_source, semantic_target))
    return GRAPH_FIELD_SEP.join(
        (
            RELATION_IDENTITY_VERSION,
            directionality,
            semantic_source,
            relation_type,
            semantic_target,
        )
    )


def make_directional_relation_chunk_key(
    source: str,
    target: str,
    relation: Mapping[str, Any] | None = None,
) -> str:
    """Create a chunk-tracking key for a semantically directed relation."""

    return relation_identity(source, target, relation)


def make_directional_relation_vdb_id(
    source: str,
    target: str,
    relation: Mapping[str, Any] | None = None,
) -> str:
    """Create the relation VDB ID used for all new direction-aware writes."""

    return compute_mdhash_id(relation_identity(source, target, relation), prefix="rel-")


def legacy_relation_vdb_ids(source: str, target: str) -> list[str]:
    """Return old pair-hash candidates for compatibility reads and cleanup."""

    return make_relation_vdb_ids(source, target)
