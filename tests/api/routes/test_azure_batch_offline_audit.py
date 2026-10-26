from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_azure_batch_completeness import audit_batch_artifacts


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in values), encoding="utf-8"
    )


def _job(doc_id: str, output_file_id: str, chunks: list[str], budget: int) -> dict:
    return {
        "doc_id": doc_id,
        "batch_id": f"batch-{doc_id}",
        "output_file_id": output_file_id,
        "submission_manifest": {
            "expected_chunk_ids": chunks,
            "max_output_tokens": budget,
            "extraction_revision": {
                "version": "1.0.1",
                "fingerprint": f"revision-{doc_id}",
            },
        },
    }


def _response(chunk_id: str, body: dict, status_code: int = 200) -> dict:
    return {
        "custom_id": chunk_id,
        "response": {"status_code": status_code, "body": body},
    }


def test_audit_reports_revision_budgets_finish_reasons_and_evidence(tmp_path):
    jobs = tmp_path / "batch_jobs"
    outputs = tmp_path / "outputs"
    jobs.mkdir()
    outputs.mkdir()
    _write_json(jobs / "doc-a.json", _job("doc-a", "file-a", ["a1", "a2"], 1200))
    _write_jsonl(
        jobs / "doc-a.jsonl",
        [
            {"custom_id": "a1", "body": {"max_output_tokens": 1200}},
            {"custom_id": "a2", "body": {"max_output_tokens": 1200}},
        ],
    )
    _write_jsonl(
        outputs / "file-a.jsonl",
        [
            _response(
                "a1",
                {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                },
            ),
            _response("a2", {"status": "completed"}),
        ],
    )

    report = audit_batch_artifacts(jobs, outputs)

    assert report["audit_mode"] == "offline_read_only"
    assert report["repair_document_count"] == 1
    document = report["documents"][0]
    assert document["extraction_revision"] == {
        "version": "1.0.1",
        "fingerprint": "revision-doc-a",
    }
    assert document["output_budgets"] == {
        "manifest": 1200,
        "request_lines": {"1200": 2},
    }
    assert document["finish_reasons"] == {
        "completed": 1,
        "max_output_tokens": 1,
    }
    assert document["incomplete_response_count"] == 1
    assert document["incomplete_count"] == 1
    assert document["evidence_paths"]["job"] == str((jobs / "doc-a.json").resolve())
    assert document["evidence_paths"]["incomplete_lines"] == [
        f"{(outputs / 'file-a.jsonl').resolve()}:1"
    ]


def test_audit_marks_length_missing_and_invalid_outputs_for_repair(tmp_path):
    jobs = tmp_path / "jobs"
    outputs = tmp_path / "outputs"
    jobs.mkdir()
    outputs.mkdir()
    _write_json(
        jobs / "doc-chat.json",
        _job("doc-chat", "file-chat", ["c1", "c2", "c3"], 2048),
    )
    _write_jsonl(
        jobs / "doc-chat.jsonl",
        [
            {"custom_id": "c1", "body": {"max_completion_tokens": 2048}},
            {"custom_id": "c2", "body": {"max_completion_tokens": 2048}},
            {"custom_id": "c3", "body": {"max_completion_tokens": 2048}},
        ],
    )
    output_path = outputs / "file-chat"
    output_path.write_text(
        json.dumps(_response("c1", {"choices": [{"finish_reason": "length"}]}))
        + "\nnot-json\n",
        encoding="utf-8",
    )

    document = audit_batch_artifacts(jobs, outputs)["documents"][0]

    assert document["finish_reasons"] == {"length": 1}
    assert document["incomplete_response_count"] == 1
    assert document["missing_output_count"] == 2
    assert document["invalid_output_count"] == 1
    assert document["incomplete_count"] == 4
    assert document["repair_required"] is True
    assert document["evidence_paths"]["incomplete_lines"] == [
        f"{output_path.resolve()}:1",
        f"{output_path.resolve()}:2",
    ]


def test_audit_is_read_only_and_accepts_complete_chat_output(tmp_path):
    jobs = tmp_path / "jobs"
    outputs = tmp_path / "outputs"
    jobs.mkdir()
    outputs.mkdir()
    _write_json(jobs / "doc-ok.json", _job("doc-ok", "file-ok", ["ok1"], 4096))
    _write_jsonl(
        jobs / "doc-ok.jsonl",
        [{"custom_id": "ok1", "body": {"max_completion_tokens": 4096}}],
    )
    _write_jsonl(
        outputs / "file-ok.jsonl",
        [_response("ok1", {"choices": [{"finish_reason": "stop"}]})],
    )
    artifacts = [*jobs.iterdir(), *outputs.iterdir()]
    before = {path: path.read_bytes() for path in artifacts}

    report = audit_batch_artifacts(jobs, outputs)

    assert report["repair_document_count"] == 0
    assert report["documents"][0]["repair_required"] is False
    assert report["documents"][0]["finish_reasons"] == {"stop": 1}
    assert {path: path.read_bytes() for path in artifacts} == before


def test_audit_reports_missing_output_artifact_without_network_access(tmp_path):
    jobs = tmp_path / "jobs"
    outputs = tmp_path / "outputs"
    jobs.mkdir()
    outputs.mkdir()
    _write_json(jobs / "doc-old.json", _job("doc-old", "file-missing", ["x"], 1200))

    document = audit_batch_artifacts(jobs, outputs)["documents"][0]

    assert document["output_count"] == 0
    assert document["missing_output_count"] == 1
    assert document["repair_required"] is None
    assert document["audit_status"] == "output_artifact_missing"
    assert audit_batch_artifacts(jobs, outputs)["unassessed_document_count"] == 1
    assert document["evidence_paths"]["output"] is None


def test_legacy_job_uses_request_ids_when_manifest_is_absent(tmp_path):
    jobs = tmp_path / "jobs"
    outputs = tmp_path / "outputs"
    jobs.mkdir()
    outputs.mkdir()
    _write_json(
        jobs / "doc-legacy.json",
        {
            "doc_id": "doc-legacy",
            "batch_id": "batch-legacy",
            "output_file_id": "file-legacy",
        },
    )
    _write_jsonl(
        jobs / "doc-legacy.jsonl",
        [
            {"custom_id": "old-1", "body": {"max_output_tokens": 1200}},
            {"custom_id": "old-2", "body": {"max_output_tokens": 1200}},
        ],
    )
    _write_jsonl(
        outputs / "file-legacy.jsonl",
        [
            _response("old-1", {"status": "completed"}),
            _response("foreign", {"status": "completed"}),
        ],
    )

    document = audit_batch_artifacts(jobs, outputs)["documents"][0]

    assert document["extraction_revision"] is None
    assert document["expected_chunk_count"] == 2
    assert document["missing_output_count"] == 1
    assert document["unexpected_output_count"] == 1
    assert document["incomplete_count"] == 2
    assert document["repair_required"] is True
