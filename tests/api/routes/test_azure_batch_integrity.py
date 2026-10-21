from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lightrag.api.azure_batch import (
    AzureBatchOutputValidationError,
    _parse_output_jsonl,
    _validate_current_chunk_manifest,
    build_batch_submission_manifest,
)


class _Chunks:
    def __init__(self, chunks: dict[str, dict]):
        self.chunks = chunks

    async def get_by_id(self, chunk_id: str):
        return self.chunks.get(chunk_id)

    async def get_by_ids(self, chunk_ids: list[str]):
        return [self.chunks.get(chunk_id) for chunk_id in chunk_ids]


def _rag(chunks: dict[str, dict]) -> SimpleNamespace:
    return SimpleNamespace(text_chunks=_Chunks(chunks))


def _response_line(chunk_id: str, body: dict) -> str:
    return json.dumps(
        {
            "custom_id": chunk_id,
            "response": {"status_code": 200, "body": body},
        }
    )


def test_submission_manifest_records_immutable_request_and_chunk_fingerprints(monkeypatch):
    monkeypatch.setenv("AZURE_BATCH_MODEL", "batch-test-model")
    monkeypatch.setenv("AZURE_BATCH_ENDPOINT", "/responses")
    chunks = {"chunk-a": {"content": "Electrode stacking affects thickness."}}
    lines = [
        {
            "custom_id": "chunk-a",
            "method": "POST",
            "url": "/responses",
            "body": {
                "model": "batch-test-model",
                "instructions": "Extract PEM assertions.",
                "input": "Electrode stacking affects thickness.",
            },
        }
    ]
    revision = {"version": "1.2.3", "fingerprint": "submitted-revision"}

    manifest = build_batch_submission_manifest(
        chunks=chunks,
        request_lines=lines,
        use_json_extraction=True,
        extraction_revision=revision,
    )

    assert manifest["expected_chunk_ids"] == ["chunk-a"]
    assert manifest["chunks"]["chunk-a"]["chunk_content_sha256"]
    assert manifest["chunks"]["chunk-a"]["request_body_sha256"]
    assert manifest["extraction_revision"] == revision
    assert manifest["model"] == "batch-test-model"
    assert manifest["input_sha256"]


def test_submission_manifest_rejects_duplicate_request_chunk_ids(monkeypatch):
    monkeypatch.setenv("AZURE_BATCH_MODEL", "batch-test-model")
    chunks = {"chunk-a": {"content": "same"}}
    line = {
        "custom_id": "chunk-a",
        "method": "POST",
        "url": "/chat/completions",
        "body": {"messages": [{"role": "system", "content": "Extract"}]},
    }

    with pytest.raises(ValueError, match="duplicate"):
        build_batch_submission_manifest(
            chunks=chunks,
            request_lines=[line, dict(line)],
            use_json_extraction=True,
            extraction_revision={},
        )


def test_completed_response_with_incomplete_status_is_rejected_before_json_repair():
    rag = _rag({"chunk-a": {"file_path": "source.pdf"}})
    output = _response_line(
        "chunk-a",
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output_text": '{"entities": [], "relationships": []}',
        },
    )

    with pytest.raises(AzureBatchOutputValidationError, match="not complete"):
        asyncio.run(
            _parse_output_jsonl(
                rag, output, True, expected_chunk_ids={"chunk-a"}
            )
        )


def test_chat_completion_length_finish_reason_is_rejected():
    rag = _rag({"chunk-a": {"file_path": "source.pdf"}})
    output = _response_line(
        "chunk-a",
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": '{"entities": [], "relationships": []}'},
                }
            ]
        },
    )

    with pytest.raises(AzureBatchOutputValidationError, match="finished with 'length'"):
        asyncio.run(
            _parse_output_jsonl(
                rag, output, True, expected_chunk_ids={"chunk-a"}
            )
        )


def test_valid_empty_json_result_is_accepted():
    rag = _rag({"chunk-a": {"file_path": "source.pdf"}})
    output = _response_line(
        "chunk-a",
        {
            "status": "completed",
            "output_text": '{"entities": [], "relationships": []}',
        },
    )

    parsed = asyncio.run(
        _parse_output_jsonl(rag, output, True, expected_chunk_ids={"chunk-a"})
    )

    assert [chunk_id for chunk_id, _ in parsed] == ["chunk-a"]
    assert parsed[0][1] == ({}, {})


def test_json_output_requires_exact_entity_relationship_contract():
    rag = _rag({"chunk-a": {"file_path": "source.pdf"}})
    output = _response_line(
        "chunk-a",
        {
            "status": "completed",
            "output_text": '{"entities": [], "relationships": [], "note": "extra"}',
        },
    )

    with pytest.raises(AzureBatchOutputValidationError, match="only entities and relationships"):
        asyncio.run(
            _parse_output_jsonl(
                rag, output, True, expected_chunk_ids={"chunk-a"}
            )
        )


def test_output_chunk_ids_must_be_complete_unique_and_expected():
    rag = _rag(
        {
            "chunk-a": {"file_path": "source.pdf"},
            "chunk-b": {"file_path": "source.pdf"},
        }
    )
    valid_body = {
        "status": "completed",
        "output_text": '{"entities": [], "relationships": []}',
    }

    with pytest.raises(AzureBatchOutputValidationError, match="missing 1 expected"):
        asyncio.run(
            _parse_output_jsonl(
                rag,
                _response_line("chunk-a", valid_body),
                True,
                expected_chunk_ids={"chunk-a", "chunk-b"},
            )
        )

    duplicate_output = "\n".join(
        [_response_line("chunk-a", valid_body), _response_line("chunk-a", valid_body)]
    )
    with pytest.raises(AzureBatchOutputValidationError, match="duplicate"):
        asyncio.run(
            _parse_output_jsonl(
                rag, duplicate_output, True, expected_chunk_ids={"chunk-a"}
            )
        )

    with pytest.raises(AzureBatchOutputValidationError, match="unexpected"):
        asyncio.run(
            _parse_output_jsonl(
                rag,
                _response_line("foreign-chunk", valid_body),
                True,
                expected_chunk_ids={"chunk-a"},
            )
        )


def test_manifest_validation_rejects_retained_chunk_changes(monkeypatch):
    monkeypatch.setenv("AZURE_BATCH_MODEL", "batch-test-model")
    submitted_chunks = {"chunk-a": {"content": "Original retained chunk."}}
    line = {
        "custom_id": "chunk-a",
        "method": "POST",
        "url": "/chat/completions",
        "body": {"messages": [{"role": "system", "content": "Extract"}]},
    }
    manifest = build_batch_submission_manifest(
        chunks=submitted_chunks,
        request_lines=[line],
        use_json_extraction=True,
        extraction_revision={},
    )
    rag = _rag({"chunk-a": {"content": "Modified retained chunk."}})

    with pytest.raises(AzureBatchOutputValidationError, match="changed after batch submission"):
        asyncio.run(
            _validate_current_chunk_manifest(
                rag,
                {"batch_id": "batch-a", "submission_manifest": manifest},
                {"chunk-a"},
            )
        )


def test_invalid_output_never_reaches_graph_merge(monkeypatch, tmp_path):
    import lightrag.api.azure_batch as azure_batch

    monkeypatch.setenv("AZURE_BATCH_BINDING_HOST", "https://batch.example.test")
    monkeypatch.setenv("AZURE_BATCH_MODEL", "batch-test-model")
    chunks = {"chunk-a": {"content": "Retained content.", "file_path": "source.pdf"}}
    line = {
        "custom_id": "chunk-a",
        "method": "POST",
        "url": "/responses",
        "body": {"instructions": "Extract", "input": "Retained content."},
    }
    manifest = build_batch_submission_manifest(
        chunks=chunks,
        request_lines=[line],
        use_json_extraction=True,
        extraction_revision={"version": "submitted", "fingerprint": "snapshot"},
    )
    job = {
        "batch_id": "batch-a",
        "status": "completed",
        "output_file_id": "file-a",
        "use_json_extraction": True,
        "submission_manifest": manifest,
    }
    status = {"chunks_list": ["chunk-a"], "metadata": {"skip_kg": True}}
    rag = SimpleNamespace(
        working_dir=str(tmp_path),
        workspace="",
        text_chunks=_Chunks(chunks),
        doc_status=SimpleNamespace(
            get_by_id=AsyncMock(return_value=status), upsert=AsyncMock()
        ),
    )

    merge = AsyncMock()
    record_failure = AsyncMock()
    monkeypatch.setattr(azure_batch, "refresh_azure_batch_status", AsyncMock(return_value=job))
    monkeypatch.setattr(
        azure_batch,
        "_download_file_content",
        AsyncMock(
            return_value=_response_line(
                "chunk-a",
                {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output_text": '{"entities": [], "relationships": []}',
                },
            )
        ),
    )
    monkeypatch.setattr(azure_batch, "merge_nodes_and_edges", merge)
    monkeypatch.setattr(azure_batch, "_record_import_validation_failure", record_failure)

    with pytest.raises(AzureBatchOutputValidationError, match="not complete"):
        asyncio.run(azure_batch.import_azure_batch_extraction(rag, "doc-a"))

    merge.assert_not_awaited()
    record_failure.assert_awaited_once()
