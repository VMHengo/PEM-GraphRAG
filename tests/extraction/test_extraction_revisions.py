from __future__ import annotations

from types import SimpleNamespace
import asyncio

import pytest

from lightrag.base import DocProcessingStatus, DocStatus
from lightrag.extraction_revisions import (
    build_extraction_revision,
    extraction_revision_from_metadata,
    is_extraction_revision_current,
    validate_reextract_selection,
    with_extraction_revision,
)
from lightrag.utils_pipeline import doc_status_transition_metadata
from lightrag.lightrag import LightRAG


def _rag(prompt_profile: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        addon_params={"entity_type_prompt_file": "pem-a.yml"},
        _entity_extraction_prompt_profile=prompt_profile
        or {
            "entity_types_guidance": "Use PEM ontology.",
            "entity_extraction_examples": ["example"],
            "entity_extraction_json_examples": ["json example"],
        },
        entity_extraction_use_json=True,
        llm_model_name="test-extractor",
        max_gleaning=1,
        max_extraction_records=10,
        max_extraction_entities=8,
        _build_role_llm_cache_identity=lambda role, state: {
            "model": "test-extractor",
            "binding": "test",
        },
    )


def test_revision_fingerprint_changes_when_prompt_changes(monkeypatch):
    monkeypatch.setenv("EXTRACTION_ALGORITHM_VERSION", "1.2.0")
    baseline = build_extraction_revision(_rag())
    changed = build_extraction_revision(
        _rag(
            {
                "entity_types_guidance": "Use a stricter PEM ontology.",
                "entity_extraction_examples": ["example"],
                "entity_extraction_json_examples": ["json example"],
            }
        )
    )

    assert baseline["version"] == "1.2.0"
    assert baseline["fingerprint"] != changed["fingerprint"]
    assert baseline["prompt_profile_sha256"] != changed["prompt_profile_sha256"]


def test_legacy_metadata_is_outdated_and_revision_is_detected():
    revision = build_extraction_revision(_rag())
    legacy_metadata = {"source_url": "https://example.org/document.pdf"}
    versioned_metadata = with_extraction_revision(legacy_metadata, revision)

    assert not is_extraction_revision_current(legacy_metadata, revision)
    assert is_extraction_revision_current(versioned_metadata, revision)
    assert versioned_metadata["source_url"] == legacy_metadata["source_url"]
    assert extraction_revision_from_metadata(versioned_metadata) == revision


def test_transition_metadata_preserves_source_urls_and_active_revision():
    status_doc = DocProcessingStatus(
        content_summary="document",
        content_length=8,
        file_path="document.pdf",
        status=DocStatus.PROCESSED,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        metadata={
            "source_url": "https://example.org/landing",
            "download_url": "https://example.org/document.pdf",
            "title": "Document",
            "extraction_revision": {"version": "1.0.0", "fingerprint": "abc"},
        },
    )

    metadata = doc_status_transition_metadata(status_doc, extra={"chunking_method": "fixed"})

    assert metadata["source_url"] == "https://example.org/landing"
    assert metadata["download_url"] == "https://example.org/document.pdf"
    assert metadata["title"] == "Document"
    assert metadata["extraction_revision"]["fingerprint"] == "abc"


def test_full_reextract_request_requires_explicit_force():
    with pytest.raises(ValueError, match="force=true"):
        validate_reextract_selection(outdated_only=False, force=False)

    validate_reextract_selection(outdated_only=False, force=True)


def test_graph_only_reextract_keeps_retained_chunks(monkeypatch):
    status_doc = DocProcessingStatus(
        content_summary="document",
        content_length=8,
        file_path="document.pdf",
        status=DocStatus.PROCESSED,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        chunks_list=["chunk-a"],
        chunks_count=1,
        metadata={"source_url": "https://example.org/document.pdf"},
    )
    calls: list[tuple] = []

    class FakeRag:
        doc_status = SimpleNamespace(get_by_id=lambda doc_id: _async_value(status_doc))
        text_chunks = SimpleNamespace(
            get_by_ids=lambda ids: _async_value([{"content": "chunk", "full_doc_id": "doc-a"}])
        )
        chunk_entity_relation_graph = object()
        entities_vdb = object()
        relationships_vdb = object()
        full_entities = object()
        full_relations = object()
        llm_response_cache = None
        entity_chunks = None
        relation_chunks = None

        def get_extraction_revision(self):
            return {"version": "1.0.0", "fingerprint": "revision"}

        async def _upsert_doc_status_transition(self, **kwargs):
            calls.append(("status", kwargs["status"], kwargs.get("metadata_extra")))

        async def _raise_if_cancelled(self, pipeline_status, pipeline_status_lock):
            return None

        async def _purge_doc_chunks_and_kg(self, *args, **kwargs):
            calls.append(("purge", kwargs["delete_chunks"]))

        async def _process_extract_entities(self, chunks, pipeline_status, pipeline_status_lock):
            calls.append(("extract", tuple(chunks)))
            return []

        def _build_global_config(self):
            return {}

        async def _insert_done(self, pipeline_status, pipeline_status_lock):
            calls.append(("persist",))

    async def fake_merge_nodes_and_edges(**kwargs):
        calls.append(("merge", kwargs["doc_id"], kwargs["file_path"]))

    monkeypatch.setattr("lightrag.lightrag.merge_nodes_and_edges", fake_merge_nodes_and_edges)
    result = asyncio.run(
        LightRAG.areextract_doc_kg(
            FakeRag(),
            "doc-a",
            pipeline_status={"history_messages": []},
            pipeline_status_lock=_NoopAsyncLock(),
        )
    )

    assert result["chunks_count"] == 1
    assert ("purge", False) in calls
    assert ("extract", ("chunk-a",)) in calls
    assert ("merge", "doc-a", "document.pdf") in calls
    assert status_doc.metadata["source_url"] == "https://example.org/document.pdf"


async def _async_value(value):
    return value


class _NoopAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False
