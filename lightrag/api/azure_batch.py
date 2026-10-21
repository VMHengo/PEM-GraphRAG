from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
import httpx

from lightrag.base import DocStatus
from lightrag.constants import (
    DEFAULT_SUMMARY_LANGUAGE,
    PROCESS_OPTION_CHUNK_FIXED,
)
from lightrag.chunk_schema import strip_internal_multimodal_markup_for_extraction
from lightrag.kg.shared_storage import get_namespace_data, get_namespace_lock
from lightrag.ontology_annotation import ontology_annotation_revision
from lightrag.operate import (
    _process_extraction_result,
    _process_json_extraction_result,
    merge_nodes_and_edges,
)
from lightrag.prompt import PROMPTS, resolve_entity_extraction_prompt_profile
from lightrag.utils import logger, update_chunk_cache_list


class AzureBatchConfigError(RuntimeError):
    pass


class AzureBatchOutputValidationError(ValueError):
    """Raised when a completed Batch job cannot be safely merged.

    Azure marks a batch as completed when its transport work is over.  That
    does not guarantee that every individual model completion is complete or
    belongs to the submitted document.  This error is intentionally raised
    before any graph write takes place.
    """

    pass


def _validate_ontology_batch_snapshot(job: dict[str, Any]) -> None:
    submitted_revision = (job.get("submission_manifest") or {}).get(
        "extraction_revision"
    ) or {}
    submitted_ontology = submitted_revision.get(
        "ontology_annotation", {"enabled": False}
    )
    if submitted_ontology != ontology_annotation_revision():
        raise AzureBatchOutputValidationError(
            "Ontology mapping changed since Batch submission; import requires "
            "the original mapping snapshot"
        )


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def azure_batch_enabled() -> bool:
    return _env_bool("AZURE_BATCH_ENABLED", False)


def _batch_dir(rag) -> Path:
    path = Path(rag.working_dir) / "batch_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(rag, doc_id: str) -> Path:
    return _batch_dir(rag) / f"{doc_id}.json"


def _job_jsonl_path(rag, doc_id: str) -> Path:
    return _batch_dir(rag) / f"{doc_id}.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_payload(status_doc: Any) -> dict[str, Any]:
    if is_dataclass(status_doc):
        return asdict(status_doc)
    if isinstance(status_doc, dict):
        return dict(status_doc)
    return dict(getattr(status_doc, "__dict__", {}))


def _batch_error_payload(batch: dict[str, Any]) -> Any:
    return batch.get("errors") or batch.get("error") or batch.get("last_error")


async def load_batch_job(rag, doc_id: str) -> dict[str, Any] | None:
    path = _job_path(rag, doc_id)
    if not path.exists():
        return None
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        return json.loads(await f.read())


async def save_batch_job(rag, doc_id: str, job: dict[str, Any]) -> None:
    path = _job_path(rag, doc_id)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(job, indent=2, ensure_ascii=False))


def _azure_headers() -> dict[str, str]:
    api_key = os.getenv("AZURE_BATCH_API_KEY")
    if not api_key:
        raise AzureBatchConfigError("AZURE_BATCH_API_KEY is not configured")
    return {"Authorization": f"Bearer {api_key}", "api-key": api_key}


def _azure_base_url() -> str:
    base_url = (os.getenv("AZURE_BATCH_BINDING_HOST") or "").strip()
    if not base_url:
        raise AzureBatchConfigError("AZURE_BATCH_BINDING_HOST is not configured")
    return base_url.rstrip("/")


def _azure_model() -> str:
    model = (os.getenv("AZURE_BATCH_MODEL") or "").strip()
    if not model:
        raise AzureBatchConfigError("AZURE_BATCH_MODEL is not configured")
    return model


def _azure_batch_endpoint() -> str:
    return (os.getenv("AZURE_BATCH_ENDPOINT") or "/chat/completions").strip()


def _uses_responses_endpoint() -> bool:
    return _azure_batch_endpoint().rstrip("/").endswith("/responses")


def _completion_window() -> str:
    return (os.getenv("AZURE_BATCH_COMPLETION_WINDOW") or "24h").strip()


def _batch_timeout() -> float:
    return float(os.getenv("AZURE_BATCH_HTTP_TIMEOUT", "120"))


def _max_output_tokens() -> int | None:
    value = (os.getenv("AZURE_BATCH_MAX_OUTPUT_TOKENS") or "").strip()
    if not value:
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _response_format(use_json_extraction: bool) -> dict[str, str] | None:
    return {"type": "json_object"} if use_json_extraction else None


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _chunk_content_sha256(chunk: dict[str, Any]) -> str:
    content = strip_internal_multimodal_markup_for_extraction(
        chunk.get("content", "") or ""
    )
    return _sha256_text(content)


def _system_prompt_from_request(line: dict[str, Any]) -> str:
    body = line.get("body") or {}
    instructions = body.get("instructions")
    if isinstance(instructions, str):
        return instructions
    for message in body.get("messages") or []:
        if isinstance(message, dict) and message.get("role") == "system":
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""


def build_batch_submission_manifest(
    *,
    chunks: dict[str, dict[str, Any]],
    request_lines: list[dict[str, Any]],
    use_json_extraction: bool,
    extraction_revision: dict[str, Any],
) -> dict[str, Any]:
    """Create an immutable, non-secret record of the submitted batch input."""

    requests: dict[str, dict[str, str]] = {}
    for line in request_lines:
        chunk_id = line.get("custom_id")
        if not isinstance(chunk_id, str) or chunk_id not in chunks:
            raise ValueError("Batch request line has an unknown chunk id")
        requests[chunk_id] = {
            "chunk_content_sha256": _chunk_content_sha256(chunks[chunk_id]),
            "request_body_sha256": _sha256_text(_canonical_json(line.get("body") or {})),
        }

    if len(requests) != len(request_lines):
        raise ValueError("Batch request lines contain duplicate chunk ids")

    system_prompts = {_system_prompt_from_request(line) for line in request_lines}
    return {
        "schema_version": 1,
        "expected_chunk_ids": sorted(requests),
        "chunks": requests,
        "input_sha256": _sha256_text(_canonical_json(request_lines)),
        "system_prompt_sha256": _sha256_text(_canonical_json(sorted(system_prompts))),
        "model": _azure_model(),
        "endpoint": _azure_batch_endpoint(),
        "completion_window": _completion_window(),
        "max_output_tokens": _max_output_tokens(),
        "use_json_extraction": use_json_extraction,
        "extraction_revision": dict(extraction_revision),
    }


def _build_extraction_prompt_context(global_config: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    use_json_extraction = bool(global_config.get("entity_extraction_use_json", False))
    addon_params = global_config.get("addon_params") or {}
    language = global_config.get("_resolved_summary_language")
    if language is None:
        language = addon_params.get("language", DEFAULT_SUMMARY_LANGUAGE)

    prompt_profile = global_config.get("_entity_extraction_prompt_profile")
    if prompt_profile is None:
        prompt_profile = resolve_entity_extraction_prompt_profile(
            addon_params, use_json_extraction
        )

    entity_types_guidance = prompt_profile["entity_types_guidance"]
    max_total_records = global_config["entity_extract_max_records"]
    max_entity_records = global_config["entity_extract_max_entities"]

    if use_json_extraction:
        examples = "\n".join(prompt_profile["entity_extraction_json_examples"])
        return use_json_extraction, dict(
            entity_types_guidance=entity_types_guidance,
            examples=examples,
            language=language,
            max_total_records=max_total_records,
            max_entity_records=max_entity_records,
        )

    examples = "\n".join(prompt_profile["entity_extraction_examples"])
    example_context_base = dict(
        tuple_delimiter=PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        completion_delimiter=PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
        entity_types_guidance=entity_types_guidance,
        language=language,
    )
    examples = examples.format(**example_context_base)
    return use_json_extraction, dict(
        tuple_delimiter=PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        completion_delimiter=PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
        entity_types_guidance=entity_types_guidance,
        examples=examples,
        language=language,
        max_total_records=max_total_records,
        max_entity_records=max_entity_records,
    )


def build_batch_request_lines(
    chunks: dict[str, dict[str, Any]], global_config: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    use_json_extraction, context_base = _build_extraction_prompt_context(global_config)
    lines: list[dict[str, Any]] = []
    model = _azure_model()
    endpoint = _azure_batch_endpoint()

    for chunk_id, chunk_dp in chunks.items():
        content = strip_internal_multimodal_markup_for_extraction(
            chunk_dp.get("content", "") or ""
        )
        max_output_tokens = _max_output_tokens()
        if use_json_extraction:
            system_prompt = PROMPTS["entity_extraction_json_system_prompt"].format(
                **context_base
            )
            user_prompt = PROMPTS["entity_extraction_json_user_prompt"].format(
                **{**context_base, "input_text": content}
            )
        else:
            system_prompt = PROMPTS["entity_extraction_system_prompt"].format(
                **context_base
            )
            user_prompt = PROMPTS["entity_extraction_user_prompt"].format(
                **{**context_base, "input_text": content}
            )

        if _uses_responses_endpoint():
            body = {
                "model": model,
                "instructions": system_prompt,
                "input": user_prompt,
            }
            response_format = _response_format(use_json_extraction)
            if response_format:
                body["text"] = {"format": response_format}
            if max_output_tokens:
                body["max_output_tokens"] = max_output_tokens
        else:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            response_format = _response_format(use_json_extraction)
            if response_format:
                body["response_format"] = response_format
            if max_output_tokens:
                body["max_completion_tokens"] = max_output_tokens

        lines.append(
            {
                "custom_id": chunk_id,
                "method": "POST",
                "url": endpoint,
                "body": body,
            }
        )

    return lines, use_json_extraction


async def _write_jsonl(path: Path, lines: list[dict[str, Any]]) -> None:
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        for line in lines:
            await f.write(json.dumps(line, ensure_ascii=False) + "\n")


async def _upload_file(client: httpx.AsyncClient, base_url: str, path: Path) -> str:
    with path.open("rb") as f:
        response = await client.post(
            f"{base_url}/files",
            headers=_azure_headers(),
            data={"purpose": "batch"},
            files={"file": (path.name, f, "application/jsonl")},
        )
    response.raise_for_status()
    return response.json()["id"]


async def _create_batch(client: httpx.AsyncClient, base_url: str, input_file_id: str) -> dict[str, Any]:
    response = await client.post(
        f"{base_url}/batches",
        headers={**_azure_headers(), "Content-Type": "application/json"},
        json={
            "input_file_id": input_file_id,
            "endpoint": _azure_batch_endpoint(),
            "completion_window": _completion_window(),
        },
    )
    response.raise_for_status()
    return response.json()


async def _get_batch(client: httpx.AsyncClient, base_url: str, batch_id: str) -> dict[str, Any]:
    response = await client.get(f"{base_url}/batches/{batch_id}", headers=_azure_headers())
    response.raise_for_status()
    return response.json()


async def _download_file_content(
    client: httpx.AsyncClient, base_url: str, file_id: str
) -> str:
    response = await client.get(
        f"{base_url}/files/{file_id}/content", headers=_azure_headers()
    )
    response.raise_for_status()
    return response.text


async def start_azure_batch_extraction(rag, doc_id: str) -> dict[str, Any]:
    if not azure_batch_enabled():
        raise AzureBatchConfigError("Azure Batch extraction is disabled")

    existing = await load_batch_job(rag, doc_id)
    if existing and existing.get("status") not in {"failed", "cancelled", "expired"}:
        return existing

    status_doc = await rag.doc_status.get_by_id(doc_id)
    if not status_doc:
        raise FileNotFoundError("Document not found")
    status_payload = _status_payload(status_doc)
    metadata = dict(status_payload.get("metadata") or {})
    if not metadata.get("skip_kg"):
        raise ValueError("Document is not chunked or is already extracted")

    chunk_ids = list(status_payload.get("chunks_list") or [])
    if not chunk_ids:
        raise ValueError("Document has no chunks_list metadata")

    chunk_values = await rag.text_chunks.get_by_ids(chunk_ids)
    chunks = {
        chunk_id: chunk
        for chunk_id, chunk in zip(chunk_ids, chunk_values)
        if isinstance(chunk, dict)
    }
    if not chunks:
        raise ValueError("No text chunks found for document")

    request_lines, use_json_extraction = build_batch_request_lines(
        chunks, rag._build_global_config()
    )
    submission_manifest = build_batch_submission_manifest(
        chunks=chunks,
        request_lines=request_lines,
        use_json_extraction=use_json_extraction,
        extraction_revision=rag.get_extraction_revision(),
    )
    jsonl_path = _job_jsonl_path(rag, doc_id)
    await _write_jsonl(jsonl_path, request_lines)

    base_url = _azure_base_url()
    async with httpx.AsyncClient(timeout=_batch_timeout()) as client:
        input_file_id = await _upload_file(client, base_url, jsonl_path)
        batch = await _create_batch(client, base_url, input_file_id)

    now = _now_iso()
    job = {
        "doc_id": doc_id,
        "batch_id": batch["id"],
        "input_file_id": input_file_id,
        "output_file_id": batch.get("output_file_id"),
        "error_file_id": batch.get("error_file_id"),
        "errors": _batch_error_payload(batch),
        "status": batch.get("status", "validating"),
        "chunk_count": len(request_lines),
        "use_json_extraction": use_json_extraction,
        "endpoint": _azure_batch_endpoint(),
        "completion_window": _completion_window(),
        "submission_manifest": submission_manifest,
        "created_at": now,
        "updated_at": now,
        "imported_at": None,
    }
    await save_batch_job(rag, doc_id, job)

    metadata.update(
        {
            "batch_extraction": True,
            "batch_id": job["batch_id"],
            "batch_status": job["status"],
            "batch_started_at": now,
        }
    )
    status_payload.update({"metadata": metadata, "updated_at": now, "error_msg": None})
    await rag.doc_status.upsert({doc_id: status_payload})
    await rag._insert_done()
    return job


async def refresh_azure_batch_status(rag, doc_id: str) -> dict[str, Any]:
    job = await load_batch_job(rag, doc_id)
    if not job:
        raise FileNotFoundError("Batch job not found")

    base_url = _azure_base_url()
    async with httpx.AsyncClient(timeout=_batch_timeout()) as client:
        batch = await _get_batch(client, base_url, job["batch_id"])

    job.update(
        {
            "status": batch.get("status", job.get("status")),
            "output_file_id": batch.get("output_file_id"),
            "error_file_id": batch.get("error_file_id"),
            "request_counts": batch.get("request_counts"),
            "errors": _batch_error_payload(batch),
            "updated_at": _now_iso(),
        }
    )
    await save_batch_job(rag, doc_id, job)

    status_doc = await rag.doc_status.get_by_id(doc_id)
    if status_doc:
        status_payload = _status_payload(status_doc)
        metadata = dict(status_payload.get("metadata") or {})
        metadata.update(
            {
                "batch_extraction": True,
                "batch_id": job["batch_id"],
                "batch_status": job["status"],
            }
        )
        status_payload.update({"metadata": metadata, "updated_at": job["updated_at"]})
        await rag.doc_status.upsert({doc_id: status_payload})
        await rag._insert_done()

    return job


def _validate_completed_response(
    body: dict[str, Any], *, chunk_id: str | None, line_number: int
) -> None:
    """Reject provider responses that were transported successfully but truncated."""

    label = chunk_id or str(line_number)
    status = body.get("status")
    if status in {"incomplete", "failed", "cancelled"}:
        details = body.get("incomplete_details") or body.get("error") or status
        raise AzureBatchOutputValidationError(
            f"Batch response for {label} is not complete: {details}"
        )
    if body.get("incomplete_details"):
        raise AzureBatchOutputValidationError(
            f"Batch response for {label} is incomplete: {body['incomplete_details']}"
        )
    if body.get("refusal"):
        raise AzureBatchOutputValidationError(f"Batch response for {label} was refused")

    choices = body.get("choices") or []
    if choices:
        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        finish_reason = first_choice.get("finish_reason")
        if finish_reason not in {None, "stop"}:
            raise AzureBatchOutputValidationError(
                f"Batch response for {label} finished with {finish_reason!r}"
            )

    for output in body.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content_item in output.get("content") or []:
            if isinstance(content_item, dict) and content_item.get("type") == "refusal":
                raise AzureBatchOutputValidationError(
                    f"Batch response for {label} was refused"
                )


def _validate_json_extraction_content(content: str, *, chunk_id: str) -> None:
    """Validate the structured-output contract before tolerant extraction parsing."""

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise AzureBatchOutputValidationError(
            f"Batch JSON response for {chunk_id} is not valid JSON: {error.msg}"
        ) from error

    if not isinstance(payload, dict):
        raise AzureBatchOutputValidationError(
            f"Batch JSON response for {chunk_id} must be an object"
        )
    expected_keys = {"entities", "relationships"}
    if set(payload) != expected_keys:
        raise AzureBatchOutputValidationError(
            f"Batch JSON response for {chunk_id} must contain only entities and relationships"
        )
    for key in expected_keys:
        if not isinstance(payload[key], list):
            raise AzureBatchOutputValidationError(
                f"Batch JSON response for {chunk_id} has a non-list {key} field"
            )


async def _parse_output_jsonl(
    rag,
    text: str,
    use_json_extraction: bool,
    *,
    expected_chunk_ids: set[str] | None = None,
) -> list[tuple[str, tuple[dict, dict]]]:
    parsed: list[tuple[str, tuple[dict, dict]]] = []
    seen_chunk_ids: set[str] = set()
    timestamp = int(time.time())
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise AzureBatchOutputValidationError(
                f"Batch output line {line_number} is not valid JSON: {error.msg}"
            ) from error
        if not isinstance(payload, dict):
            raise AzureBatchOutputValidationError(
                f"Batch output line {line_number} must be an object"
            )
        chunk_id = payload.get("custom_id")
        response = payload.get("response") or {}
        if not isinstance(chunk_id, str) or not chunk_id:
            raise AzureBatchOutputValidationError(
                f"Batch response missing custom_id at line {line_number}"
            )
        if expected_chunk_ids is not None and chunk_id not in expected_chunk_ids:
            raise AzureBatchOutputValidationError(
                f"Batch output contains unexpected chunk id {chunk_id}"
            )
        if chunk_id in seen_chunk_ids:
            raise AzureBatchOutputValidationError(
                f"Batch output contains duplicate chunk id {chunk_id}"
            )
        seen_chunk_ids.add(chunk_id)
        if not isinstance(response, dict):
            raise AzureBatchOutputValidationError(
                f"Batch response for {chunk_id} is not an object"
            )
        if response.get("status_code") != 200:
            raise AzureBatchOutputValidationError(
                f"Batch request failed for {chunk_id or line_number}: {response}"
            )
        body = response.get("body") or {}
        if not isinstance(body, dict):
            raise AzureBatchOutputValidationError(
                f"Batch response body for {chunk_id} is not an object"
            )
        _validate_completed_response(body, chunk_id=chunk_id, line_number=line_number)
        content = _extract_batch_response_text(body)
        if not content:
            raise AzureBatchOutputValidationError(
                f"Batch response missing content for {chunk_id}"
            )
        if use_json_extraction:
            _validate_json_extraction_content(content, chunk_id=chunk_id)

        chunk_data = await rag.text_chunks.get_by_id(chunk_id)
        file_path = (
            chunk_data.get("file_path", "unknown_source")
            if isinstance(chunk_data, dict)
            else "unknown_source"
        )

        if use_json_extraction:
            result = await _process_json_extraction_result(
                content, chunk_id, timestamp, file_path
            )
        else:
            result = await _process_extraction_result(
                content,
                chunk_id,
                timestamp,
                file_path,
                tuple_delimiter=PROMPTS["DEFAULT_TUPLE_DELIMITER"],
                completion_delimiter=PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
            )
        parsed.append((chunk_id, result))

    if expected_chunk_ids is not None:
        missing_chunk_ids = sorted(expected_chunk_ids - seen_chunk_ids)
        if missing_chunk_ids:
            preview = ", ".join(missing_chunk_ids[:5])
            suffix = "..." if len(missing_chunk_ids) > 5 else ""
            raise AzureBatchOutputValidationError(
                f"Batch output is missing {len(missing_chunk_ids)} expected chunk ids: "
                f"{preview}{suffix}"
            )
    return parsed


def _extract_batch_response_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if choices:
        return ((choices[0].get("message") or {}).get("content") or "").strip()

    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output_parts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content_item in item.get("content") or []:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str) and text:
                output_parts.append(text)
    return "\n".join(output_parts).strip()


def _expected_chunk_ids(job: dict[str, Any], status_payload: dict[str, Any]) -> set[str]:
    manifest = job.get("submission_manifest")
    if isinstance(manifest, dict):
        submitted = manifest.get("expected_chunk_ids")
        if isinstance(submitted, list) and all(isinstance(item, str) for item in submitted):
            return set(submitted)
    return {
        chunk_id
        for chunk_id in status_payload.get("chunks_list") or []
        if isinstance(chunk_id, str)
    }


async def _validate_current_chunk_manifest(
    rag, job: dict[str, Any], expected_chunk_ids: set[str]
) -> None:
    """Ensure current retained chunks still match the batch submission.

    Jobs submitted before this safeguard have no manifest. They remain
    importable, but are deliberately marked as legacy in the persisted job.
    """

    manifest = job.get("submission_manifest")
    if not isinstance(manifest, dict):
        logger.warning(
            "Azure Batch job %s has no submission manifest; skipping retained chunk hash validation",
            job.get("batch_id"),
        )
        return

    expected = manifest.get("chunks")
    if not isinstance(expected, dict):
        raise AzureBatchOutputValidationError("Batch submission manifest has no chunk hashes")
    if set(expected) != expected_chunk_ids:
        raise AzureBatchOutputValidationError(
            "Batch submission manifest chunk ids do not match its expected chunk ids"
        )

    chunk_ids = sorted(expected_chunk_ids)
    current_chunks = await rag.text_chunks.get_by_ids(chunk_ids)
    if len(current_chunks) != len(chunk_ids):
        raise AzureBatchOutputValidationError(
            "Retained chunk lookup returned an unexpected number of chunks"
        )

    for chunk_id, chunk in zip(chunk_ids, current_chunks):
        if not isinstance(chunk, dict):
            raise AzureBatchOutputValidationError(
                f"Submitted chunk {chunk_id} no longer exists"
            )
        expected_hash = (expected.get(chunk_id) or {}).get("chunk_content_sha256")
        if not isinstance(expected_hash, str) or not expected_hash:
            raise AzureBatchOutputValidationError(
                f"Batch submission manifest has no content hash for {chunk_id}"
            )
        if _chunk_content_sha256(chunk) != expected_hash:
            raise AzureBatchOutputValidationError(
                f"Submitted chunk {chunk_id} changed after batch submission"
            )


async def _record_import_validation_failure(
    rag, doc_id: str, job: dict[str, Any], error: Exception
) -> None:
    """Persist a retryable validation failure without changing Azure's batch status."""

    now = _now_iso()
    message = str(error)
    job.update(
        {
            "import_validation_status": "failed",
            "import_validation_error": message,
            "import_validation_failed_at": now,
            "updated_at": now,
        }
    )
    await save_batch_job(rag, doc_id, job)

    status_doc = await rag.doc_status.get_by_id(doc_id)
    if not status_doc:
        return
    status_payload = _status_payload(status_doc)
    metadata = dict(status_payload.get("metadata") or {})
    metadata.update(
        {
            "batch_extraction": True,
            "batch_id": job.get("batch_id"),
            "batch_status": job.get("status"),
            "batch_import_validation_status": "failed",
            "batch_import_validation_error": message,
            "batch_import_validation_failed_at": now,
        }
    )
    status_payload.update({"metadata": metadata, "updated_at": now, "error_msg": message})
    await rag.doc_status.upsert({doc_id: status_payload})
    await rag._insert_done()


async def import_azure_batch_extraction(rag, doc_id: str) -> dict[str, Any]:
    job = await refresh_azure_batch_status(rag, doc_id)
    if job.get("status") != "completed":
        raise ValueError(f"Batch is not completed yet: {job.get('status')}")
    if job.get("imported_at"):
        return job
    output_file_id = job.get("output_file_id")
    if not output_file_id:
        raise ValueError("Completed batch has no output_file_id")

    base_url = _azure_base_url()
    async with httpx.AsyncClient(timeout=_batch_timeout()) as client:
        output_text = await _download_file_content(client, base_url, output_file_id)

    status_doc = await rag.doc_status.get_by_id(doc_id)
    if not status_doc:
        raise FileNotFoundError("Document not found")
    status_payload = _status_payload(status_doc)
    expected_chunk_ids = _expected_chunk_ids(job, status_payload)
    if not expected_chunk_ids:
        raise AzureBatchOutputValidationError("Document has no expected batch chunk ids")

    try:
        _validate_ontology_batch_snapshot(job)
        await _validate_current_chunk_manifest(rag, job, expected_chunk_ids)
        parsed = await _parse_output_jsonl(
            rag,
            output_text,
            bool(job.get("use_json_extraction", False)),
            expected_chunk_ids=expected_chunk_ids,
        )
    except AzureBatchOutputValidationError as error:
        await _record_import_validation_failure(rag, doc_id, job, error)
        raise

    chunk_results = [result for _, result in parsed]

    pipeline_status = await get_namespace_data(
        "pipeline_status", workspace=rag.workspace
    )
    pipeline_status_lock = get_namespace_lock(
        "pipeline_status", workspace=rag.workspace
    )
    async with pipeline_status_lock:
        pipeline_status.setdefault("history_messages", [])
        pipeline_status["latest_message"] = (
            f"Importing Azure Batch extraction for {doc_id}"
        )
        pipeline_status["history_messages"].append(pipeline_status["latest_message"])

    await merge_nodes_and_edges(
        chunk_results=chunk_results,
        knowledge_graph_inst=rag.chunk_entity_relation_graph,
        entity_vdb=rag.entities_vdb,
        relationships_vdb=rag.relationships_vdb,
        global_config=rag._build_global_config(),
        full_entities_storage=rag.full_entities,
        full_relations_storage=rag.full_relations,
        doc_id=doc_id,
        pipeline_status=pipeline_status,
        pipeline_status_lock=pipeline_status_lock,
        llm_response_cache=rag.llm_response_cache,
        entity_chunks_storage=rag.entity_chunks,
        relation_chunks_storage=rag.relation_chunks,
        file_path=status_payload.get("file_path", "batch_extraction"),
    )

    metadata = dict(status_payload.get("metadata") or {})
    metadata.pop("skip_kg", None)
    metadata.update(
        {
            "batch_extraction": True,
            "batch_id": job["batch_id"],
            "batch_status": "imported",
            "batch_imported_at": _now_iso(),
            "extraction_revision": dict(
                (job.get("submission_manifest") or {}).get("extraction_revision")
                or rag.get_extraction_revision()
            ),
        }
    )

    content_data = await rag.full_docs.get_by_id(doc_id)
    if content_data:
        process_options = str(content_data.get("process_options") or "")
        content_data["process_options"] = (
            process_options.replace("!", "") or PROCESS_OPTION_CHUNK_FIXED
        )
        await rag.full_docs.upsert({doc_id: content_data})

    status_payload.update(
        {
            "status": DocStatus.PROCESSED,
            "updated_at": metadata["batch_imported_at"],
            "error_msg": None,
            "metadata": metadata,
        }
    )
    await rag.doc_status.upsert({doc_id: status_payload})

    for chunk_id, _ in parsed:
        await update_chunk_cache_list(
            chunk_id,
            rag.text_chunks,
            [f"azure-batch:{job['batch_id']}:{chunk_id}"],
            "entity_extraction",
        )

    job.update(
        {
            "status": "imported",
            "imported_at": metadata["batch_imported_at"],
            "updated_at": metadata["batch_imported_at"],
            "imported_chunks": len(parsed),
            "import_validation_status": "passed",
            "import_validation_error": None,
        }
    )
    await save_batch_job(rag, doc_id, job)
    await rag._insert_done()
    logger.info("Imported Azure Batch extraction for doc %s", doc_id)
    return job
