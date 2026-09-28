"""Persistent, lightweight storage for asynchronous evaluation benchmark runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lightrag.utils import logger


RunStatus = Literal["queued", "running", "completed", "failed", "interrupted"]

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_METADATA_FILE = "metadata.json"
_RESULT_FILE = "result.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runs_dir(working_dir: str | Path) -> Path:
    path = Path(working_dir).expanduser().resolve() / "evaluation_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _safe_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise FileNotFoundError("Benchmark run was not found")
    return run_id


def _run_dir(working_dir: str | Path, run_id: str) -> Path:
    return _runs_dir(working_dir) / _safe_run_id(run_id)


def _metadata_path(working_dir: str | Path, run_id: str) -> Path:
    return _run_dir(working_dir, run_id) / _METADATA_FILE


def _result_path(working_dir: str | Path, run_id: str) -> Path:
    return _run_dir(working_dir, run_id) / _RESULT_FILE


def _validate_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise ValueError("Benchmark run title must not be empty")
    if len(normalized) > 160:
        raise ValueError("Benchmark run title must not exceed 160 characters")
    return normalized


def _validate_note(note: str | None) -> str:
    normalized = (note or "").strip()
    if len(normalized) > 4000:
        raise ValueError("Benchmark run note must not exceed 4000 characters")
    return normalized


def _default_title(benchmark_name: str, mode: str) -> str:
    return f"{benchmark_name} ({mode})"


def _summary(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": metadata["id"],
        "title": metadata["title"],
        "note": metadata.get("note", ""),
        "status": metadata["status"],
        "benchmark_id": metadata["benchmark_id"],
        "benchmark_name": metadata.get("benchmark_name", metadata["benchmark_id"]),
        "mode": metadata["mode"],
        "created_at": metadata["created_at"],
        "started_at": metadata.get("started_at"),
        "completed_at": metadata.get("completed_at"),
        "updated_at": metadata.get("updated_at", metadata["created_at"]),
        "error": metadata.get("error"),
        "scores": metadata.get("scores") or {},
        "quality_gates_passed": metadata.get("quality_gates_passed"),
        "failed_check_count": int(metadata.get("failed_check_count") or 0),
        "case_count": int(metadata.get("case_count") or 0),
    }


def create_run(
    working_dir: str | Path,
    *,
    benchmark_id: str,
    benchmark_name: str,
    case_count: int,
    mode: str,
    title: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_title = _validate_title(title or _default_title(benchmark_name, mode))
    metadata = {
        "schema_version": 1,
        "id": run_id,
        "title": run_title,
        "note": _validate_note(note),
        "status": "queued",
        "benchmark_id": benchmark_id,
        "benchmark_name": benchmark_name,
        "mode": mode,
        "case_count": case_count,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "error": None,
        "scores": {},
        "quality_gates_passed": None,
        "failed_check_count": 0,
    }
    _atomic_write_json(_metadata_path(working_dir, run_id), metadata)
    return _summary(metadata)


def _load_metadata(working_dir: str | Path, run_id: str) -> dict[str, Any]:
    path = _metadata_path(working_dir, run_id)
    if not path.exists():
        raise FileNotFoundError("Benchmark run was not found")
    return _read_json(path)


def _save_metadata(working_dir: str | Path, metadata: dict[str, Any]) -> None:
    metadata["updated_at"] = _utc_now()
    _atomic_write_json(_metadata_path(working_dir, metadata["id"]), metadata)


def mark_run_running(working_dir: str | Path, run_id: str) -> dict[str, Any]:
    metadata = _load_metadata(working_dir, run_id)
    metadata["status"] = "running"
    metadata["started_at"] = _utc_now()
    metadata["error"] = None
    _save_metadata(working_dir, metadata)
    return _summary(metadata)


def complete_run(
    working_dir: str | Path,
    run_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    metadata = _load_metadata(working_dir, run_id)
    metadata["status"] = "completed"
    metadata["completed_at"] = _utc_now()
    metadata["error"] = None
    metadata["scores"] = result.get("scores") or {}
    metadata["quality_gates_passed"] = (
        result.get("quality_gates") or {}
    ).get("passed")
    metadata["failed_check_count"] = len(result.get("failed_checks") or [])

    persisted_result = dict(result)
    run_data = dict(persisted_result.get("run") or {})
    run_data.update(_summary(metadata))
    persisted_result["run"] = run_data
    _atomic_write_json(_result_path(working_dir, run_id), persisted_result)
    _save_metadata(working_dir, metadata)
    return _summary(metadata)


def fail_run(working_dir: str | Path, run_id: str, error: str) -> dict[str, Any]:
    metadata = _load_metadata(working_dir, run_id)
    metadata["status"] = "failed"
    metadata["completed_at"] = _utc_now()
    metadata["error"] = error[:4000]
    _save_metadata(working_dir, metadata)
    return _summary(metadata)


def update_run_metadata(
    working_dir: str | Path,
    run_id: str,
    *,
    title: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if run_id.startswith("legacy_"):
        return _migrate_legacy_run(
            working_dir, run_id, title=title, note=note
        )
    metadata = _load_metadata(working_dir, run_id)
    if title is not None:
        metadata["title"] = _validate_title(title)
    if note is not None:
        metadata["note"] = _validate_note(note)
    _save_metadata(working_dir, metadata)

    result_path = _result_path(working_dir, run_id)
    if result_path.exists():
        result = _read_json(result_path)
        run_data = dict(result.get("run") or {})
        run_data.update(_summary(metadata))
        result["run"] = run_data
        _atomic_write_json(result_path, result)
    return _summary(metadata)


def _migrate_legacy_run(
    working_dir: str | Path,
    legacy_id: str,
    *,
    title: str | None,
    note: str | None,
) -> dict[str, Any]:
    root = _runs_dir(working_dir)
    legacy_path = _legacy_path_for_id(root, legacy_id)
    if legacy_path is None:
        raise FileNotFoundError("Benchmark run was not found")
    legacy_result = _read_json(legacy_path)
    legacy_summary = _legacy_summary(legacy_path)
    if legacy_summary is None:
        raise FileNotFoundError("Benchmark run was not found")

    migrated = create_run(
        working_dir,
        benchmark_id=legacy_summary["benchmark_id"],
        benchmark_name=legacy_summary["benchmark_name"],
        case_count=legacy_summary["case_count"],
        mode=legacy_summary["mode"],
        title=title or legacy_summary["title"],
        note=note,
    )
    metadata = _load_metadata(working_dir, migrated["id"])
    metadata["legacy_source"] = legacy_path.name
    metadata["created_at"] = legacy_summary["created_at"]
    metadata["started_at"] = legacy_summary["started_at"]
    _save_metadata(working_dir, metadata)
    complete_run(working_dir, migrated["id"], legacy_result)
    return _summary(_load_metadata(working_dir, migrated["id"]))


def _legacy_summary(path: Path) -> dict[str, Any] | None:
    try:
        result = _read_json(path)
    except Exception as exc:
        logger.warning("Skipping invalid legacy benchmark run %s: %s", path, exc)
        return None
    run = result.get("run") or {}
    benchmark = result.get("benchmark") or {}
    legacy_id = "legacy_" + hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:16]
    return {
        "id": legacy_id,
        "title": str(benchmark.get("name") or benchmark.get("id") or path.stem),
        "note": "",
        "status": "completed",
        "benchmark_id": str(benchmark.get("id") or path.stem),
        "benchmark_name": str(benchmark.get("name") or benchmark.get("id") or path.stem),
        "mode": str(run.get("mode") or "retrieval"),
        "created_at": str(run.get("generated_at") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()),
        "started_at": None,
        "completed_at": str(run.get("generated_at") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "error": None,
        "scores": result.get("scores") or {},
        "quality_gates_passed": (result.get("quality_gates") or {}).get("passed"),
        "failed_check_count": len(result.get("failed_checks") or []),
        "case_count": int((benchmark.get("case_count") or 0)),
        "legacy_source": path.name,
    }


def list_runs(
    working_dir: str | Path,
    *,
    benchmark_id: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    root = _runs_dir(working_dir)
    summaries: list[dict[str, Any]] = []
    migrated_legacy_sources: set[str] = set()
    for metadata_path in root.glob(f"*/{_METADATA_FILE}"):
        try:
            metadata = _read_json(metadata_path)
            if metadata.get("legacy_source"):
                migrated_legacy_sources.add(str(metadata["legacy_source"]))
            summaries.append(_summary(metadata))
        except Exception as exc:
            logger.warning("Skipping invalid benchmark run metadata %s: %s", metadata_path, exc)

    for legacy_path in root.glob("*.json"):
        if legacy_path.name in migrated_legacy_sources:
            continue
        legacy = _legacy_summary(legacy_path)
        if legacy:
            summaries.append(legacy)

    if benchmark_id:
        summaries = [run for run in summaries if run["benchmark_id"] == benchmark_id]
    summaries.sort(key=lambda run: str(run.get("created_at") or ""), reverse=True)
    total = len(summaries)
    return summaries[offset : offset + limit], total


def _legacy_path_for_id(root: Path, run_id: str) -> Path | None:
    for path in root.glob("*.json"):
        legacy = _legacy_summary(path)
        if legacy and legacy["id"] == run_id:
            return path
    return None


def get_run(working_dir: str | Path, run_id: str) -> dict[str, Any]:
    root = _runs_dir(working_dir)
    if run_id.startswith("legacy_"):
        legacy_path = _legacy_path_for_id(root, run_id)
        if legacy_path is None:
            raise FileNotFoundError("Benchmark run was not found")
        result = _read_json(legacy_path)
        summary = _legacy_summary(legacy_path)
        if summary is None:
            raise FileNotFoundError("Benchmark run was not found")
        result["run"] = {**dict(result.get("run") or {}), **summary}
        return {"run": summary, "result": result}

    metadata = _load_metadata(working_dir, run_id)
    result_path = _result_path(working_dir, run_id)
    if not result_path.exists():
        return {"run": _summary(metadata), "result": None}
    result = _read_json(result_path)
    result["run"] = {**dict(result.get("run") or {}), **_summary(metadata)}
    return {"run": _summary(metadata), "result": result}


def recover_interrupted_runs(working_dir: str | Path) -> int:
    """Mark runs left active by a container restart as interrupted."""
    root = _runs_dir(working_dir)
    recovered = 0
    for metadata_path in root.glob(f"*/{_METADATA_FILE}"):
        try:
            metadata = _read_json(metadata_path)
            if metadata.get("status") not in {"queued", "running"}:
                continue
            metadata["status"] = "interrupted"
            metadata["completed_at"] = _utc_now()
            metadata["error"] = "Benchmark worker stopped before the run completed."
            _save_metadata(working_dir, metadata)
            recovered += 1
        except Exception as exc:
            logger.warning("Failed to recover benchmark run %s: %s", metadata_path, exc)
    return recovered
