"""Stable provenance for entity and relationship extraction.

The graph is derived data. Documents, chunks, embeddings, and editable source
metadata must survive an extraction refresh, while the graph can be rebuilt
from the retained chunks. This module deliberately stores only the active
revision on a document; source-controlled prompt/code history stays in Git.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping


EXTRACTION_REVISION_METADATA_KEY = "extraction_revision"


def validate_reextract_selection(*, outdated_only: bool, force: bool) -> None:
    """Prevent an accidental full graph rebuild without explicit consent."""

    if not outdated_only and not force:
        raise ValueError("A full re-extraction requires force=true")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _string_env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def build_extraction_revision(rag: Any) -> dict[str, Any]:
    """Build a reproducible snapshot of the active extraction configuration.

    ``EXTRACTION_ALGORITHM_VERSION`` is intentionally a human-managed semantic
    version. The fingerprint additionally captures the resolved prompt and
    relevant runtime parameters, so a prompt change is detected even when the
    operator forgot to increment the version.
    """

    addon_params = dict(getattr(rag, "addon_params", {}) or {})
    prompt_profile = dict(
        getattr(rag, "_entity_extraction_prompt_profile", {}) or {}
    )
    prompt_file = str(addon_params.get("entity_type_prompt_file") or "builtin")
    model_identity = {}
    builder = getattr(rag, "_build_role_llm_cache_identity", None)
    role_states = getattr(rag, "_role_llm_states", None) or {}
    if callable(builder):
        try:
            model_identity = dict(builder("extract", role_states.get("extract")) or {})
        except Exception:
            model_identity = {}

    components: dict[str, Any] = {
        "algorithm_version": _string_env("EXTRACTION_ALGORITHM_VERSION", "1.0.0"),
        "relation_schema_version": _string_env("RELATION_SCHEMA_VERSION", "1"),
        "prompt_profile": prompt_file,
        "resolved_prompt_profile": prompt_profile,
        "entity_extraction_use_json": bool(
            getattr(rag, "entity_extraction_use_json", False)
        ),
        "model": model_identity.get("model") or getattr(rag, "llm_model_name", ""),
        "model_binding": model_identity.get("binding"),
        "max_gleaning": getattr(rag, "max_gleaning", None),
        "max_extraction_records": getattr(rag, "max_extraction_records", None),
        "max_extraction_entities": getattr(rag, "max_extraction_entities", None),
    }
    prompt_profile_sha256 = hashlib.sha256(
        _canonical_json(prompt_profile).encode("utf-8")
    ).hexdigest()
    fingerprint = hashlib.sha256(_canonical_json(components).encode("utf-8")).hexdigest()

    return {
        "version": components["algorithm_version"],
        "fingerprint": fingerprint,
        "prompt_profile": prompt_file,
        "prompt_profile_sha256": prompt_profile_sha256,
        "relation_schema_version": components["relation_schema_version"],
        "model": components["model"],
        "model_binding": components["model_binding"],
        "entity_extraction_use_json": components["entity_extraction_use_json"],
        "git_commit": os.getenv("EXTRACTION_GIT_COMMIT", "").strip() or None,
    }


def extraction_revision_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a normalized revision record stored on a document, if present."""

    if not isinstance(metadata, Mapping):
        return None
    revision = metadata.get(EXTRACTION_REVISION_METADATA_KEY)
    if not isinstance(revision, Mapping):
        return None
    fingerprint = revision.get("fingerprint")
    version = revision.get("version")
    if not isinstance(fingerprint, str) or not fingerprint:
        return None
    if not isinstance(version, str) or not version:
        return None
    return dict(revision)


def is_extraction_revision_current(
    metadata: Mapping[str, Any] | None, current_revision: Mapping[str, Any]
) -> bool:
    """Whether document metadata records exactly the active configuration."""

    stored = extraction_revision_from_metadata(metadata)
    if stored is None:
        return False
    return stored.get("fingerprint") == current_revision.get("fingerprint")


def with_extraction_revision(
    metadata: Mapping[str, Any] | None, revision: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a metadata copy with the active revision attached."""

    merged = dict(metadata or {})
    merged[EXTRACTION_REVISION_METADATA_KEY] = dict(revision)
    return merged
