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
from lightrag.operate import (
    _process_extraction_result,
    _process_json_extraction_result,
    merge_nodes_and_edges,
)
from lightrag.prompt import PROMPTS, resolve_entity_extraction_prompt_profile
from lightrag.utils import logger, update_chunk_cache_list


class AzureBatchConfigError(RuntimeError):
    pass


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


def _completion_window() -> str:
    return (os.getenv("AZURE_BATCH_COMPLETION_WINDOW") or "24h").strip()


def _batch_timeout() -> float:
    return float(os.getenv("AZURE_BATCH_HTTP_TIMEOUT", "120"))


def _response_format(use_json_extraction: bool) -> dict[str, str] | None:
    return {"type": "json_object"} if use_json_extraction else None


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

        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        response_format = _response_format(use_json_extraction)
        if response_format:
            body["response_format"] = response_format

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
        "status": batch.get("status", "validating"),
        "chunk_count": len(request_lines),
        "use_json_extraction": use_json_extraction,
        "endpoint": _azure_batch_endpoint(),
        "completion_window": _completion_window(),
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


async def _parse_output_jsonl(
    rag, text: str, use_json_extraction: bool
) -> list[tuple[str, tuple[dict, dict]]]:
    parsed: list[tuple[str, tuple[dict, dict]]] = []
    timestamp = int(time.time())
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        chunk_id = payload.get("custom_id")
        response = payload.get("response") or {}
        if response.get("status_code") != 200:
            raise RuntimeError(
                f"Batch request failed for {chunk_id or line_number}: {response}"
            )
        body = response.get("body") or {}
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"Batch response has no choices for {chunk_id}")
        content = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not chunk_id or not content:
            raise RuntimeError(f"Batch response missing custom_id/content at line {line_number}")

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
    return parsed


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

    parsed = await _parse_output_jsonl(
        rag, output_text, bool(job.get("use_json_extraction", False))
    )
    chunk_results = [result for _, result in parsed]

    status_doc = await rag.doc_status.get_by_id(doc_id)
    if not status_doc:
        raise FileNotFoundError("Document not found")
    status_payload = _status_payload(status_doc)

    await merge_nodes_and_edges(
        chunk_results=chunk_results,
        knowledge_graph_inst=rag.chunk_entity_relation_graph,
        entity_vdb=rag.entities_vdb,
        relationships_vdb=rag.relationships_vdb,
        global_config=rag._build_global_config(),
        full_entities_storage=rag.full_entities,
        full_relations_storage=rag.full_relations,
        doc_id=doc_id,
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
        }
    )
    await save_batch_job(rag, doc_id, job)
    await rag._insert_done()
    logger.info("Imported Azure Batch extraction for doc %s", doc_id)
    return job
