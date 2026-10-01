"""Isolated, cost-aware extraction prompt experiments.

An experiment reuses retained document chunks, but never writes candidate
entities or relationships to the active LightRAG workspace.  Every candidate
prompt is evaluated in its own short-lived workspace and stores a serialised
extraction artefact.  A later, explicit promotion can merge one of those
artefacts into the active graph without reparsing or rechunking the document.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping

from lightrag.base import DocProcessingStatus, DocStatus
from lightrag.evaluation.live_benchmark import (
    benchmark_document_preflight,
    load_benchmark,
    run_live_benchmark,
)
from lightrag.llm_roles import RoleLLMConfig
from lightrag.prompt import (
    get_entity_type_prompt_dir,
    load_entity_extraction_prompt_profile,
    resolve_entity_extraction_prompt_profile,
    resolve_entity_type_prompt_path,
)
from lightrag.utils import logger

if TYPE_CHECKING:
    from lightrag.lightrag import LightRAG


PromptExperimentMode = Literal["screening", "validation", "final"]
BenchmarkMode = Literal["graph", "retrieval", "full"]

_MANIFEST_NAME = "manifest.json"
_SOURCE_SNAPSHOT_NAME = "source_snapshot.json"
_EXPERIMENT_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def prompt_experiments_enabled() -> bool:
    """Return the explicit operator switch for metered prompt experiments."""

    return _env_bool("PROMPT_EXPERIMENTS_ENABLED", False)


def prompt_experiment_promotion_enabled() -> bool:
    return _env_bool("PROMPT_EXPERIMENT_PROMOTION_ENABLED", False)


def prompt_experiment_limits() -> dict[str, int]:
    """Expose the operator-configured selection limits to API consumers."""

    return {
        "max_documents": _env_int("PROMPT_EXPERIMENT_MAX_DOCUMENTS", 20, minimum=1),
        "max_profiles": _env_int("PROMPT_EXPERIMENT_MAX_PROFILES", 5, minimum=1),
    }


def _experiments_root(working_dir: str | Path) -> Path:
    return Path(working_dir) / "prompt_experiments"


def _safe_experiment_id(experiment_id: str) -> str:
    safe = Path(experiment_id).name
    if safe != experiment_id or not safe or safe in {".", ".."}:
        raise ValueError("Invalid prompt experiment id")
    return safe


def _experiment_dir(working_dir: str | Path, experiment_id: str) -> Path:
    return _experiments_root(working_dir) / _safe_experiment_id(experiment_id)


def _manifest_path(working_dir: str | Path, experiment_id: str) -> Path:
    return _experiment_dir(working_dir, experiment_id) / _MANIFEST_NAME


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def load_prompt_experiment(working_dir: str | Path, experiment_id: str) -> dict[str, Any]:
    """Load one experiment manifest without exposing internal temporary paths."""

    manifest = _load_json(_manifest_path(working_dir, experiment_id))
    return manifest


def save_prompt_experiment(working_dir: str | Path, manifest: Mapping[str, Any]) -> None:
    experiment_id = str(manifest.get("id") or "")
    if not experiment_id:
        raise ValueError("Prompt experiment manifest is missing an id")
    payload = dict(manifest)
    payload["updated_at"] = _utc_now()
    _atomic_write_json(_manifest_path(working_dir, experiment_id), payload)


def list_prompt_experiments(
    working_dir: str | Path, *, limit: int = 30
) -> list[dict[str, Any]]:
    root = _experiments_root(working_dir)
    if not root.exists():
        return []
    manifests: list[dict[str, Any]] = []
    for path in root.glob(f"*/{_MANIFEST_NAME}"):
        try:
            manifests.append(_load_json(path))
        except ValueError as exc:
            logger.warning("Skipping invalid prompt experiment manifest %s: %s", path, exc)
    manifests.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return manifests[:limit]


def recover_interrupted_prompt_experiments(working_dir: str | Path) -> int:
    """Mark in-flight work interrupted after an API process restart."""

    recovered = 0
    for manifest in list_prompt_experiments(working_dir, limit=10_000):
        if manifest.get("status") not in {"queued", "running"}:
            continue
        manifest["status"] = "interrupted"
        manifest["error"] = "The API process restarted before this experiment finished."
        for candidate in manifest.get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("status") in {"queued", "running"}:
                candidate["status"] = "interrupted"
        save_prompt_experiment(working_dir, manifest)
        recovered += 1
    return recovered


def _cancel_unfinished_candidates(
    manifest: dict[str, Any], *, message: str = "Cancelled by an operator."
) -> None:
    """Move queued/running candidates into a terminal state after cancellation."""

    completed_at = _utc_now()
    for candidate in manifest.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("status") not in {"queued", "running"}:
            continue
        candidate.update(
            {
                "status": "cancelled",
                "completed_at": completed_at,
                "error": message,
            }
        )


def _profile_token_estimate(profile: Mapping[str, Any]) -> int:
    canonical = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    return max(1, (len(canonical) + 3) // 4)


def list_prompt_profiles(rag: Any) -> list[dict[str, Any]]:
    """List valid, server-side YAML profiles that an experiment may select."""

    active_file = str((getattr(rag, "addon_params", {}) or {}).get("entity_type_prompt_file") or "")
    prompt_dir = get_entity_type_prompt_dir()
    if not prompt_dir.exists():
        return []

    profiles: list[dict[str, Any]] = []
    for path in sorted(prompt_dir.iterdir()):
        if path.suffix.lower() not in {".yml", ".yaml"} or not path.is_file():
            continue
        try:
            profile = load_entity_extraction_prompt_profile(path)
            # A profile is usable only when it explicitly supplies examples
            # for the active extraction mode. Resolve it here so an invalid
            # candidate cannot fail after paid extraction calls have begun.
            resolve_entity_extraction_prompt_profile(
                {"entity_type_prompt_file": path.name},
                bool(getattr(rag, "entity_extraction_use_json", False)),
            )
        except Exception as exc:
            logger.warning("Skipping invalid prompt profile %s: %s", path.name, exc)
            continue
        content = path.read_bytes()
        profiles.append(
            {
                "file": path.name,
                "active": path.name == active_file,
                "fingerprint": hashlib.sha256(content).hexdigest(),
                "estimated_prompt_tokens": _profile_token_estimate(profile),
                "guidance_characters": len(str(profile.get("entity_types_guidance") or "")),
                "example_count": len(profile.get("entity_extraction_json_examples") or [])
                + len(profile.get("entity_extraction_examples") or []),
            }
        )
    return profiles


def _normalise_doc_ids(document_ids: list[str]) -> list[str]:
    normalised = list(dict.fromkeys(doc_id.strip() for doc_id in document_ids if doc_id and doc_id.strip()))
    if not normalised:
        raise ValueError("Select at least one completed document")
    maximum = prompt_experiment_limits()["max_documents"]
    if len(normalised) > maximum:
        raise ValueError(f"At most {maximum} documents may be used in one prompt experiment")
    return normalised


def _normalise_profiles(rag: Any, profile_files: list[str]) -> list[str]:
    normalised = list(dict.fromkeys(file_name.strip() for file_name in profile_files if file_name and file_name.strip()))
    if not normalised:
        raise ValueError("Select at least one prompt profile")
    maximum = prompt_experiment_limits()["max_profiles"]
    if len(normalised) > maximum:
        raise ValueError(f"At most {maximum} prompt profiles may be compared at once")
    for file_name in normalised:
        # Resolving and loading here enforces the prompt-directory sandbox and
        # validates both the file and its schema before any provider call.
        load_entity_extraction_prompt_profile(resolve_entity_type_prompt_path(file_name))
        resolve_entity_extraction_prompt_profile(
            {"entity_type_prompt_file": file_name},
            bool(getattr(rag, "entity_extraction_use_json", False)),
        )
    return normalised


def _mode_settings(rag: Any, mode: PromptExperimentMode) -> dict[str, Any]:
    if mode == "screening":
        return {
            "max_gleaning": 0,
            "benchmark_mode": "retrieval",
            "sample_limit": _env_int(
                "PROMPT_EXPERIMENT_SCREENING_CHUNKS_PER_DOCUMENT", 10, minimum=1
            ),
            "promotion_allowed": False,
        }
    if mode == "validation":
        return {
            "max_gleaning": 0,
            "benchmark_mode": "retrieval",
            "sample_limit": None,
            "promotion_allowed": False,
        }
    if mode == "final":
        return {
            # LightRAG currently performs at most one continuation pass when
            # this setting is positive. Preserve the active deployment intent.
            "max_gleaning": 1 if int(getattr(rag, "entity_extract_max_gleaning", 0)) > 0 else 0,
            "benchmark_mode": "retrieval",
            "sample_limit": None,
            "promotion_allowed": True,
        }
    raise ValueError("optimization_mode must be screening, validation, or final")


async def _load_source_documents(
    rag: Any,
    document_ids: list[str],
    *,
    sample_limit: int | None,
) -> list[dict[str, Any]]:
    processed = await rag.doc_status.get_docs_by_status(DocStatus.PROCESSED)
    documents: list[dict[str, Any]] = []
    missing = set(document_ids)
    for doc_id in document_ids:
        status_doc = processed.get(doc_id)
        if status_doc is None:
            continue
        missing.discard(doc_id)
        metadata = dict(getattr(status_doc, "metadata", {}) or {})
        chunk_ids = [chunk_id for chunk_id in (getattr(status_doc, "chunks_list", []) or []) if chunk_id]
        if metadata.get("skip_kg") or not chunk_ids:
            continue
        records = await rag.text_chunks.get_by_ids(chunk_ids)
        chunks = {
            chunk_id: record
            for chunk_id, record in zip(chunk_ids, records, strict=False)
            if isinstance(record, dict) and record
        }
        if len(chunks) != len(chunk_ids):
            raise ValueError(f"Document {doc_id} no longer has all retained chunks")
        selected_ids = chunk_ids if sample_limit is None else chunk_ids[:sample_limit]
        selected_chunks = {chunk_id: chunks[chunk_id] for chunk_id in selected_ids}
        full_doc = await rag.full_docs.get_by_id(doc_id)
        documents.append(
            {
                "doc_id": doc_id,
                "file_path": str(getattr(status_doc, "file_path", "unknown_source")),
                "metadata": metadata,
                "full_doc": full_doc if isinstance(full_doc, dict) else {},
                "chunks": selected_chunks,
                "all_chunk_count": len(chunk_ids),
                "source_fingerprint": source_fingerprint(chunks),
                "selected_fingerprint": source_fingerprint(selected_chunks),
            }
        )
    if missing:
        raise ValueError(f"Selected document(s) are not completed: {', '.join(sorted(missing))}")
    if len(documents) != len(document_ids):
        raise ValueError("Selected documents must be extracted documents with retained chunks")
    return documents


def source_fingerprint(chunks: Mapping[str, Mapping[str, Any]]) -> str:
    rows = [
        {
            "id": chunk_id,
            "content": str(chunk.get("content") or ""),
            "tokens": int(chunk.get("tokens") or 0),
            "full_doc_id": str(chunk.get("full_doc_id") or ""),
        }
        for chunk_id, chunk in sorted(chunks.items())
    ]
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _estimate_for_profile(
    profile_file: str,
    profile: Mapping[str, Any],
    documents: list[dict[str, Any]],
    *,
    max_gleaning: int,
) -> dict[str, Any]:
    profile_tokens = _profile_token_estimate(profile)
    system_overhead = _env_int("PROMPT_EXPERIMENT_SYSTEM_OVERHEAD_TOKENS", 1800)
    output_per_call = _env_int("PROMPT_EXPERIMENT_ESTIMATED_OUTPUT_TOKENS", 800)
    input_price = _env_float("PROMPT_EXPERIMENT_INPUT_COST_PER_MILLION", 0.75)
    output_price = _env_float("PROMPT_EXPERIMENT_OUTPUT_COST_PER_MILLION", 4.50)
    chunks = [chunk for document in documents for chunk in document["chunks"].values()]
    chunk_tokens = sum(max(1, int(chunk.get("tokens") or 0)) for chunk in chunks)
    chunk_count = len(chunks)
    calls_per_chunk = 2 if max_gleaning > 0 else 1
    input_tokens = chunk_tokens * calls_per_chunk + chunk_count * (system_overhead + profile_tokens) * calls_per_chunk
    output_tokens = chunk_count * calls_per_chunk * output_per_call
    estimated_cost = (input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)
    return {
        "profile_file": profile_file,
        "profile_prompt_tokens": profile_tokens,
        "selected_chunk_count": chunk_count,
        "calls_per_chunk": calls_per_chunk,
        "estimated_llm_calls": chunk_count * calls_per_chunk,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": round(estimated_cost, 4),
    }


async def estimate_prompt_experiment(
    rag: Any,
    *,
    document_ids: list[str],
    profile_files: list[str],
    optimization_mode: PromptExperimentMode,
    benchmark_id: str | None = None,
) -> dict[str, Any]:
    """Return a provider-independent extraction estimate before execution."""

    document_ids = _normalise_doc_ids(document_ids)
    profile_files = _normalise_profiles(rag, profile_files)
    settings = _mode_settings(rag, optimization_mode)
    documents = await _load_source_documents(
        rag, document_ids, sample_limit=settings["sample_limit"]
    )
    benchmark_preflight = None
    if benchmark_id:
        benchmark = load_benchmark(benchmark_id, getattr(rag, "working_dir", None))
        benchmark_preflight = benchmark_document_preflight(
            benchmark,
            [str(document.get("file_path") or "") for document in documents],
        )
    per_profile: list[dict[str, Any]] = []
    for profile_file in profile_files:
        profile = load_entity_extraction_prompt_profile(
            resolve_entity_type_prompt_path(profile_file)
        )
        per_profile.append(
            _estimate_for_profile(
                profile_file,
                profile,
                documents,
                max_gleaning=settings["max_gleaning"],
            )
        )
    return {
        "optimization_mode": optimization_mode,
        "benchmark_mode": settings["benchmark_mode"],
        "selected_documents": len(documents),
        "selected_chunks": sum(len(document["chunks"]) for document in documents),
        "all_document_chunks": sum(document["all_chunk_count"] for document in documents),
        "max_gleaning": settings["max_gleaning"],
        "per_profile": per_profile,
        "estimated_llm_calls": sum(item["estimated_llm_calls"] for item in per_profile),
        "estimated_input_tokens": sum(item["estimated_input_tokens"] for item in per_profile),
        "estimated_output_tokens": sum(item["estimated_output_tokens"] for item in per_profile),
        "estimated_cost_usd": round(sum(item["estimated_cost_usd"] for item in per_profile), 4),
        "benchmark_preflight": benchmark_preflight,
        "notes": [
            "The estimate covers extraction calls only. Retrieval benchmark keyword and answer calls are not included.",
            "Screening uses a per-document chunk sample and cannot be promoted.",
            "Validation uses all selected chunks without a continuation pass.",
            "Final preserves the active continuation setting and is the only promotable mode.",
        ],
    }


def _serialise_chunk_results(chunk_results: list[Any]) -> list[dict[str, Any]]:
    serialised: list[dict[str, Any]] = []
    for nodes, edges in chunk_results:
        serialised.append(
            {
                "nodes": [
                    {"entity_id": entity_id, "records": records}
                    for entity_id, records in nodes.items()
                ],
                "edges": [
                    {"source": edge[0], "target": edge[1], "records": records}
                    for edge, records in edges.items()
                ],
            }
        )
    return serialised


def deserialise_chunk_results(value: list[Mapping[str, Any]]) -> list[tuple[dict[str, Any], dict[tuple[str, str], Any]]]:
    """Restore extraction results written by :func:`_serialise_chunk_results`."""

    restored: list[tuple[dict[str, Any], dict[tuple[str, str], Any]]] = []
    for chunk in value:
        nodes: dict[str, Any] = {}
        edges: dict[tuple[str, str], Any] = {}
        for node in chunk.get("nodes") or []:
            if isinstance(node, Mapping) and isinstance(node.get("entity_id"), str):
                nodes[node["entity_id"]] = list(node.get("records") or [])
        for edge in chunk.get("edges") or []:
            source = edge.get("source") if isinstance(edge, Mapping) else None
            target = edge.get("target") if isinstance(edge, Mapping) else None
            if isinstance(source, str) and isinstance(target, str):
                edges[(source, target)] = list(edge.get("records") or [])
        restored.append((nodes, edges))
    return restored


def _role_llm_configs_from_rag(rag: Any) -> dict[str, RoleLLMConfig]:
    configs: dict[str, RoleLLMConfig] = {}
    for name, state in (getattr(rag, "_role_llm_states", {}) or {}).items():
        configs[name] = RoleLLMConfig(
            func=state.raw_func,
            kwargs=deepcopy(state.kwargs),
            max_async=state.max_async,
            timeout=state.timeout,
            metadata=deepcopy(state.metadata),
        )
    return configs


def _candidate_rag(
    rag: Any,
    *,
    workspace: str,
    working_dir: Path,
    profile_file: str,
    max_gleaning: int,
) -> "LightRAG":
    # Keep this import local: manifest/cost helpers should remain usable in a
    # lightweight test environment that intentionally has no LLM dependencies.
    from lightrag.lightrag import LightRAG

    if rag.graph_storage == "Neo4JStorage" and os.getenv("NEO4J_WORKSPACE", "").strip():
        raise RuntimeError(
            "Prompt experiments require NEO4J_WORKSPACE to be unset so each "
            "candidate can use its own isolated Neo4j workspace label."
        )
    addon_params = deepcopy(dict(getattr(rag, "addon_params", {}) or {}))
    addon_params["entity_type_prompt_file"] = profile_file
    return LightRAG(
        working_dir=str(working_dir),
        workspace=workspace,
        kv_storage=rag.kv_storage,
        vector_storage=rag.vector_storage,
        graph_storage=rag.graph_storage,
        doc_status_storage=rag.doc_status_storage,
        embedding_func=rag.embedding_func,
        llm_model_func=rag.llm_model_func,
        llm_model_name=rag.llm_model_name,
        llm_model_max_async=min(1, int(getattr(rag, "llm_model_max_async", 1))),
        llm_model_kwargs=deepcopy(getattr(rag, "llm_model_kwargs", {})),
        default_llm_timeout=rag.default_llm_timeout,
        default_embedding_timeout=rag.default_embedding_timeout,
        entity_extraction_use_json=rag.entity_extraction_use_json,
        entity_extract_max_gleaning=max_gleaning,
        entity_extract_max_records=rag.entity_extract_max_records,
        entity_extract_max_entities=rag.entity_extract_max_entities,
        embedding_batch_num=rag.embedding_batch_num,
        embedding_func_max_async=rag.embedding_func_max_async,
        vector_db_storage_cls_kwargs=deepcopy(rag.vector_db_storage_cls_kwargs),
        rerank_model_func=rag.rerank_model_func,
        rerank_model_max_async=rag.rerank_model_max_async,
        default_rerank_timeout=rag.default_rerank_timeout,
        max_graph_nodes=rag.max_graph_nodes,
        top_k=rag.top_k,
        chunk_top_k=rag.chunk_top_k,
        max_entity_tokens=rag.max_entity_tokens,
        max_relation_tokens=rag.max_relation_tokens,
        max_total_tokens=rag.max_total_tokens,
        enable_llm_cache=False,
        enable_llm_cache_for_entity_extract=False,
        role_llm_configs=_role_llm_configs_from_rag(rag),
        addon_params=addon_params,
        ollama_server_infos=deepcopy(getattr(rag, "ollama_server_infos", None)),
    )


async def _seed_candidate_workspace(candidate: LightRAG, documents: list[dict[str, Any]]) -> None:
    full_docs: dict[str, dict[str, Any]] = {}
    chunks: dict[str, dict[str, Any]] = {}
    for document in documents:
        doc_id = document["doc_id"]
        full_doc = dict(document.get("full_doc") or {})
        if full_doc:
            full_docs[doc_id] = full_doc
        chunks.update(document["chunks"])
    if full_docs:
        await candidate.full_docs.upsert(full_docs)
    if chunks:
        await asyncio.gather(
            candidate.text_chunks.upsert(chunks),
            candidate.chunks_vdb.upsert(chunks),
        )


async def _dispose_candidate(candidate: LightRAG) -> None:
    """Drop the disposable candidate workspace unless explicitly retained."""

    try:
        if not _env_bool("PROMPT_EXPERIMENT_KEEP_CANDIDATE_WORKSPACE", False):
            for storage in (
                candidate.full_docs,
                candidate.text_chunks,
                candidate.full_entities,
                candidate.full_relations,
                candidate.entity_chunks,
                candidate.relation_chunks,
                candidate.entities_vdb,
                candidate.relationships_vdb,
                candidate.chunks_vdb,
                candidate.chunk_entity_relation_graph,
                candidate.llm_response_cache,
                candidate.doc_status,
            ):
                try:
                    await storage.drop()
                except Exception as exc:  # Cleanup must not hide a valid result.
                    logger.warning("Could not clean prompt experiment workspace %s: %s", candidate.workspace, exc)
    finally:
        await candidate.finalize_storages()


async def create_prompt_experiment(
    rag: Any,
    *,
    title: str,
    note: str,
    document_ids: list[str],
    profile_files: list[str],
    benchmark_id: str,
    optimization_mode: PromptExperimentMode,
    benchmark_mode: BenchmarkMode | None = None,
) -> dict[str, Any]:
    """Validate and persist a queued experiment. Execution is scheduled by the API."""

    if not prompt_experiments_enabled():
        raise PermissionError("Prompt experiments are disabled. Set PROMPT_EXPERIMENTS_ENABLED=true to enable them.")
    title = title.strip()
    if not title:
        raise ValueError("A prompt experiment needs a title")
    if len(title) > 160 or len(note) > 4000:
        raise ValueError("Title or note exceeds its maximum length")
    load_benchmark(benchmark_id, getattr(rag, "working_dir", None))
    estimate = await estimate_prompt_experiment(
        rag,
        document_ids=document_ids,
        profile_files=profile_files,
        optimization_mode=optimization_mode,
        benchmark_id=benchmark_id,
    )
    preflight = estimate.get("benchmark_preflight") or {}
    if preflight and not preflight.get("compatible"):
        missing = ", ".join(str(item) for item in preflight.get("missing_documents") or [])
        raise ValueError(
            "Selected documents do not cover the benchmark source scope. "
            f"Missing: {missing}"
        )
    settings = _mode_settings(rag, optimization_mode)
    if benchmark_mode is not None and optimization_mode == "final":
        settings["benchmark_mode"] = benchmark_mode

    documents = await _load_source_documents(
        rag,
        _normalise_doc_ids(document_ids),
        sample_limit=settings["sample_limit"],
    )
    experiment_id = f"prompt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    workspace_root = _experiment_dir(rag.working_dir, experiment_id)
    source_snapshot = {
        "documents": [
            {
                "doc_id": document["doc_id"],
                "file_path": document["file_path"],
                "all_chunk_count": document["all_chunk_count"],
                "selected_chunk_count": len(document["chunks"]),
                "source_fingerprint": document["source_fingerprint"],
                "selected_fingerprint": document["selected_fingerprint"],
                "chunk_ids": list(document["chunks"].keys()),
            }
            for document in documents
        ]
    }
    _atomic_write_json(workspace_root / _SOURCE_SNAPSHOT_NAME, source_snapshot)

    manifest = {
        "id": experiment_id,
        "title": title,
        "note": note.strip(),
        "status": "queued",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "started_at": None,
        "completed_at": None,
        "error": None,
        "document_ids": [document["doc_id"] for document in documents],
        "profile_files": _normalise_profiles(rag, profile_files),
        "benchmark_id": benchmark_id,
        "optimization_mode": optimization_mode,
        "benchmark_mode": settings["benchmark_mode"],
        "settings": settings,
        "estimate": estimate,
        "source_snapshot": _SOURCE_SNAPSHOT_NAME,
        "candidates": [
            {
                "profile_file": profile_file,
                "status": "queued",
                "scores": {},
                "artifact": None,
                "result": None,
                "error": None,
            }
            for profile_file in _normalise_profiles(rag, profile_files)
        ],
    }
    save_prompt_experiment(rag.working_dir, manifest)
    return manifest


async def _extract_candidate(
    rag: Any,
    manifest: dict[str, Any],
    candidate_manifest: dict[str, Any],
    documents: list[dict[str, Any]],
) -> None:
    profile_file = str(candidate_manifest["profile_file"])
    experiment_dir = _experiment_dir(rag.working_dir, str(manifest["id"]))
    candidate_id = hashlib.sha256(profile_file.encode("utf-8")).hexdigest()[:12]
    candidate_dir = experiment_dir / "candidates" / candidate_id
    workspace = f"prompt_exp_{str(manifest['id'])[-18:]}_{candidate_id[:6]}"
    candidate_manifest.update(
        {
            "status": "running",
            "started_at": _utc_now(),
            "workspace": workspace,
            "error": None,
        }
    )
    save_prompt_experiment(rag.working_dir, manifest)

    candidate = _candidate_rag(
        rag,
        workspace=workspace,
        working_dir=candidate_dir / "workspace",
        profile_file=profile_file,
        max_gleaning=int(manifest["settings"]["max_gleaning"]),
    )
    try:
        from lightrag.operate import merge_nodes_and_edges

        await candidate.initialize_storages()
        await _seed_candidate_workspace(candidate, documents)
        artefact_documents: list[dict[str, Any]] = []
        for index, document in enumerate(documents, start=1):
            chunks = document["chunks"]
            chunk_results = await candidate._process_extract_entities(chunks)
            await merge_nodes_and_edges(
                chunk_results=chunk_results,
                knowledge_graph_inst=candidate.chunk_entity_relation_graph,
                entity_vdb=candidate.entities_vdb,
                relationships_vdb=candidate.relationships_vdb,
                global_config=candidate._build_global_config(),
                full_entities_storage=candidate.full_entities,
                full_relations_storage=candidate.full_relations,
                doc_id=document["doc_id"],
                llm_response_cache=candidate.llm_response_cache,
                entity_chunks_storage=candidate.entity_chunks,
                relation_chunks_storage=candidate.relation_chunks,
                current_file_number=index,
                total_files=len(documents),
                file_path=document["file_path"],
            )
            artefact_documents.append(
                {
                    "doc_id": document["doc_id"],
                    "file_path": document["file_path"],
                    "source_fingerprint": document["source_fingerprint"],
                    "selected_fingerprint": document["selected_fingerprint"],
                    "chunk_ids": list(chunks.keys()),
                    "chunk_results": _serialise_chunk_results(chunk_results),
                }
            )
        await candidate._insert_done()
        result = await run_live_benchmark(
            candidate,
            str(manifest["benchmark_id"]),
            mode=str(manifest["benchmark_mode"]),  # type: ignore[arg-type]
            save_result=False,
        )
        extraction_revision = candidate.get_extraction_revision()
        artifact_path = candidate_dir / "extraction_artifact.json"
        _atomic_write_json(
            artifact_path,
            {
                "experiment_id": manifest["id"],
                "profile_file": profile_file,
                "extraction_revision": extraction_revision,
                "documents": artefact_documents,
            },
        )
        result_path = candidate_dir / "benchmark_result.json"
        _atomic_write_json(result_path, result)
        candidate_manifest.update(
            {
                "status": "completed",
                "completed_at": _utc_now(),
                "scores": result.get("scores") or {},
                "summary": result.get("summary") or {},
                "artifact": str(artifact_path.relative_to(experiment_dir)),
                "result": str(result_path.relative_to(experiment_dir)),
                "extraction_revision": extraction_revision,
            }
        )
    except asyncio.CancelledError:
        candidate_manifest.update(
            {
                "status": "cancelled",
                "completed_at": _utc_now(),
                "error": "Cancelled by an operator.",
            }
        )
        raise
    except Exception as exc:
        logger.error("Prompt experiment candidate %s failed: %s", profile_file, exc, exc_info=True)
        candidate_manifest.update(
            {"status": "failed", "completed_at": _utc_now(), "error": str(exc)}
        )
    finally:
        await _dispose_candidate(candidate)
        save_prompt_experiment(rag.working_dir, manifest)


async def execute_prompt_experiment(rag: Any, experiment_id: str) -> None:
    """Run profiles sequentially so a small VPS cannot fan out LLM work."""

    manifest = load_prompt_experiment(rag.working_dir, experiment_id)
    if manifest.get("status") not in {"queued", "running"}:
        return
    manifest.update({"status": "running", "started_at": _utc_now(), "error": None})
    save_prompt_experiment(rag.working_dir, manifest)
    try:
        settings = dict(manifest.get("settings") or {})
        documents = await _load_source_documents(
            rag,
            list(manifest.get("document_ids") or []),
            sample_limit=settings.get("sample_limit"),
        )
        for candidate in manifest.get("candidates") or []:
            if not isinstance(candidate, dict) or candidate.get("status") != "queued":
                continue
            await _extract_candidate(rag, manifest, candidate, documents)
        candidates = manifest.get("candidates") or []
        succeeded = sum(1 for candidate in candidates if candidate.get("status") == "completed")
        manifest["status"] = "completed" if succeeded else "failed"
        manifest["completed_at"] = _utc_now()
        if not succeeded:
            manifest["error"] = "Every prompt candidate failed. Inspect the candidate errors."
    except asyncio.CancelledError:
        manifest["status"] = "cancelled"
        manifest["completed_at"] = _utc_now()
        manifest["error"] = "Cancelled by an operator."
        _cancel_unfinished_candidates(manifest)
        raise
    except Exception as exc:
        logger.error("Prompt experiment %s failed: %s", experiment_id, exc, exc_info=True)
        manifest["status"] = "failed"
        manifest["completed_at"] = _utc_now()
        manifest["error"] = str(exc)
    finally:
        save_prompt_experiment(rag.working_dir, manifest)


async def _acquire_promotion_slot(rag: Any) -> tuple[dict[str, Any], Any]:
    """Reserve the same exclusive graph-maintenance slot used for re-extraction."""

    from lightrag.kg.shared_storage import get_namespace_data, get_namespace_lock

    pipeline_status = await get_namespace_data("pipeline_status", workspace=rag.workspace)
    pipeline_status_lock = get_namespace_lock("pipeline_status", workspace=rag.workspace)
    async with pipeline_status_lock:
        if pipeline_status.get("busy") or pipeline_status.get("scanning"):
            raise RuntimeError("The document pipeline is busy; wait before promoting a prompt candidate.")
        if pipeline_status.get("pending_enqueues", 0) > 0:
            raise RuntimeError("A document upload is still being enqueued; wait before promoting.")
        pipeline_status.update(
            {
                "busy": True,
                "destructive_busy": True,
                "job_name": "Promoting prompt experiment candidate",
                "job_start": _utc_now(),
                "docs": 0,
                "batchs": 0,
                "cur_batch": 0,
                "latest_message": "Starting prompt experiment promotion",
                "cancellation_requested": False,
            }
        )
        pipeline_status["history_messages"][:] = ["Starting prompt experiment promotion"]
    return pipeline_status, pipeline_status_lock


async def _release_promotion_slot(rag: Any, pipeline_status: dict[str, Any], pipeline_status_lock: Any) -> None:
    async with pipeline_status_lock:
        pipeline_status["busy"] = False
        pipeline_status["destructive_busy"] = False
        pipeline_status["cancellation_requested"] = False


async def promote_prompt_experiment_candidate(
    rag: Any,
    *,
    experiment_id: str,
    profile_file: str,
) -> dict[str, Any]:
    """Replace selected documents' KG contribution with a final candidate.

    Chunks, document metadata, citations, and source URLs remain untouched. The
    active prompt is switched only after every artifact has merged successfully.
    If a merge fails, already-updated documents are rebuilt with the old active
    prompt before the maintenance slot is released.
    """

    if not prompt_experiment_promotion_enabled():
        raise PermissionError(
            "Prompt candidate promotion is disabled. Set PROMPT_EXPERIMENT_PROMOTION_ENABLED=true to enable it."
        )
    manifest = load_prompt_experiment(rag.working_dir, experiment_id)
    if manifest.get("optimization_mode") != "final":
        raise ValueError("Only a final, full-document experiment may be promoted")
    candidate = next(
        (
            item
            for item in manifest.get("candidates") or []
            if isinstance(item, dict)
            and item.get("profile_file") == profile_file
            and item.get("status") == "completed"
        ),
        None,
    )
    if candidate is None or not candidate.get("artifact"):
        raise ValueError("The selected completed candidate does not have a promotion artifact")

    experiment_dir = _experiment_dir(rag.working_dir, experiment_id)
    artifact = _load_json(experiment_dir / str(candidate["artifact"]))
    artifact_documents = artifact.get("documents") or []
    if not isinstance(artifact_documents, list) or not artifact_documents:
        raise ValueError("The selected candidate artifact has no document results")

    # Fail before changing the live graph if retained chunks changed after the
    # candidate was generated. A new experiment is then required.
    for document in artifact_documents:
        doc_id = str(document.get("doc_id") or "")
        chunk_ids = list(document.get("chunk_ids") or [])
        records = await rag.text_chunks.get_by_ids(chunk_ids)
        current_chunks = {
            chunk_id: record
            for chunk_id, record in zip(chunk_ids, records, strict=False)
            if isinstance(record, dict) and record
        }
        if len(current_chunks) != len(chunk_ids) or source_fingerprint(current_chunks) != document.get("selected_fingerprint"):
            raise ValueError(f"Document {doc_id} changed since the experiment and cannot be promoted safely")

    pipeline_status, pipeline_status_lock = await _acquire_promotion_slot(rag)
    old_profile = str(dict(getattr(rag, "addon_params", {})).get("entity_type_prompt_file") or "")
    pointer_path = rag._active_extraction_profile_pointer_path()
    old_pointer = pointer_path.read_bytes() if pointer_path.exists() else None
    promoted_docs: list[str] = []
    status_docs: dict[str, DocProcessingStatus] = {}
    try:
        from lightrag.operate import merge_nodes_and_edges

        total = len(artifact_documents)
        async with pipeline_status_lock:
            pipeline_status["docs"] = total
            pipeline_status["batchs"] = total
        for index, document in enumerate(artifact_documents, start=1):
            doc_id = str(document["doc_id"])
            status_doc = await rag.doc_status.get_by_id(doc_id)
            if status_doc is None:
                raise ValueError(f"Document {doc_id} no longer exists")
            if not isinstance(status_doc, DocProcessingStatus):
                raw_status = dict(status_doc)
                raw_status["status"] = DocStatus(raw_status["status"])
                status_doc = DocProcessingStatus(**raw_status)
            status_docs[doc_id] = status_doc
            chunk_ids = [chunk_id for chunk_id in (status_doc.chunks_list or []) if chunk_id]
            async with pipeline_status_lock:
                pipeline_status["cur_batch"] = index
                pipeline_status["latest_message"] = f"Promoting {index}/{total}: {doc_id}"
                pipeline_status["history_messages"].append(pipeline_status["latest_message"])
            await rag._upsert_doc_status_transition(
                doc_id=doc_id,
                status=DocStatus.PROCESSING,
                status_doc=status_doc,
                file_path=status_doc.file_path,
                extra_fields={"chunks_count": len(chunk_ids), "chunks_list": chunk_ids, "error_msg": None},
                metadata_extra={"prompt_experiment_promotion_started_at": _utc_now()},
            )
            await rag._purge_doc_chunks_and_kg(
                doc_id,
                set(chunk_ids),
                pipeline_status=pipeline_status,
                pipeline_status_lock=pipeline_status_lock,
                delete_chunks=False,
            )
            chunk_results = deserialise_chunk_results(list(document.get("chunk_results") or []))
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
                current_file_number=index,
                total_files=total,
                file_path=str(document.get("file_path") or status_doc.file_path),
            )
            promoted_docs.append(doc_id)

        # The snapshot keeps an accepted runtime profile stable even when an
        # operator later edits or replaces the original candidate YAML file.
        source_profile_path = resolve_entity_type_prompt_path(profile_file)
        profile_hash = hashlib.sha256(source_profile_path.read_bytes()).hexdigest()
        promoted_file = f"promoted_prompt_{profile_hash[:16]}.yml"
        promoted_path = get_entity_type_prompt_dir() / promoted_file
        promoted_path.parent.mkdir(parents=True, exist_ok=True)
        if not promoted_path.exists():
            shutil.copy2(source_profile_path, promoted_path)
        rag.set_active_entity_extraction_prompt_profile(
            promoted_file,
            metadata={
                "experiment_id": experiment_id,
                "candidate_profile": profile_file,
                "promoted_at": _utc_now(),
            },
        )
        revision = rag.get_extraction_revision()
        for doc_id in promoted_docs:
            status_doc = status_docs[doc_id]
            chunk_ids = [chunk_id for chunk_id in (status_doc.chunks_list or []) if chunk_id]
            await rag._upsert_doc_status_transition(
                doc_id=doc_id,
                status=DocStatus.PROCESSED,
                status_doc=status_doc,
                file_path=status_doc.file_path,
                extra_fields={"chunks_count": len(chunk_ids), "chunks_list": chunk_ids, "error_msg": None},
                metadata_extra={
                    "extraction_revision": revision,
                    "last_reextracted_at": _utc_now(),
                    "prompt_experiment_id": experiment_id,
                    "prompt_experiment_profile": profile_file,
                },
            )
        await rag._insert_done(pipeline_status, pipeline_status_lock)
        manifest["promotion"] = {
            "profile_file": profile_file,
            "promoted_at": _utc_now(),
            "document_ids": promoted_docs,
            "extraction_revision": revision,
        }
        save_prompt_experiment(rag.working_dir, manifest)
        return manifest["promotion"]
    except Exception:
        # Restore the prior profile before rebuilding partially promoted
        # documents. An exception can occur after the new profile pointer was
        # written, and rebuilding with that new profile would not be a rollback.
        try:
            if old_pointer is None:
                pointer_path.unlink(missing_ok=True)
            else:
                pointer_path.write_bytes(old_pointer)
            rag.addon_params["entity_type_prompt_file"] = old_profile
            rag._ensure_addon_params_cache()
        except Exception:
            logger.exception("Failed to restore the previous active prompt profile")
        # Rebuild documents that were already purged/merged from their retained
        # chunks. Files, chunks, and source metadata remain intact throughout.
        for doc_id in promoted_docs:
            try:
                await rag.areextract_doc_kg(
                    doc_id,
                    pipeline_status=pipeline_status,
                    pipeline_status_lock=pipeline_status_lock,
                )
            except Exception as restore_exc:
                logger.error("Failed to restore %s after promotion error: %s", doc_id, restore_exc, exc_info=True)
        raise
    finally:
        await _release_promotion_slot(rag, pipeline_status, pipeline_status_lock)

