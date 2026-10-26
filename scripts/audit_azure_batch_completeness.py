"""Audit historic Azure Batch extraction completeness from local artifacts only."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable


_INCOMPLETE_STATUSES = {"incomplete", "failed", "cancelled"}
_BUDGET_KEYS = ("max_output_tokens", "max_completion_tokens", "max_tokens")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return value


def _evidence(path: Path, line_number: int | None = None) -> str:
    resolved = str(path.resolve())
    return f"{resolved}:{line_number}" if line_number is not None else resolved


def _request_artifact(
    path: Path | None,
) -> tuple[Counter[int], set[str], list[str]]:
    budgets: Counter[int] = Counter()
    chunk_ids: set[str] = set()
    evidence: list[str] = []
    if path is None:
        return budgets, chunk_ids, evidence

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Cannot read request artifact {path}: {exc}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid request JSONL at {_evidence(path, line_number)}: {exc.msg}"
            ) from exc
        body = payload.get("body") if isinstance(payload, dict) else None
        chunk_id = payload.get("custom_id") if isinstance(payload, dict) else None
        if isinstance(chunk_id, str) and chunk_id:
            chunk_ids.add(chunk_id)
        if not isinstance(body, dict):
            continue
        for key in _BUDGET_KEYS:
            value = body.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                budgets[value] += 1
                evidence.append(_evidence(path, line_number))
                break
    return budgets, chunk_ids, list(dict.fromkeys(evidence))


def _finish_reason(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        reason = choices[0].get("finish_reason")
        if isinstance(reason, str) and reason:
            return reason

    details = body.get("incomplete_details")
    if isinstance(details, dict):
        reason = details.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    status = body.get("status")
    return status if isinstance(status, str) and status else "unknown"


def _response_is_incomplete(response: Any, body: Any, finish_reason: str) -> bool:
    if not isinstance(response, dict) or response.get("status_code") != 200:
        return True
    if not isinstance(body, dict):
        return True
    if body.get("status") in _INCOMPLETE_STATUSES or body.get("incomplete_details"):
        return True
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        return finish_reason != "stop"
    return finish_reason not in {"completed", "unknown"}


def _audit_output(path: Path | None, expected_chunk_ids: set[str]) -> dict[str, Any]:
    if path is None:
        return {
            "output_count": 0,
            "incomplete_count": 0,
            "missing_output_count": len(expected_chunk_ids),
            "duplicate_output_count": 0,
            "unexpected_output_count": 0,
            "invalid_output_count": 0,
            "finish_reasons": {},
            "incomplete_evidence": [],
            "seen_chunk_ids": set(),
        }

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Cannot read output artifact {path}: {exc}") from exc

    output_count = 0
    incomplete_count = 0
    invalid_output_count = 0
    duplicate_output_count = 0
    unexpected_output_count = 0
    finish_reasons: Counter[str] = Counter()
    incomplete_evidence: list[str] = []
    seen_chunk_ids: set[str] = set()
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        output_count += 1
        evidence = _evidence(path, line_number)
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            invalid_output_count += 1
            incomplete_evidence.append(evidence)
            continue
        if not isinstance(payload, dict):
            invalid_output_count += 1
            incomplete_evidence.append(evidence)
            continue

        chunk_id = payload.get("custom_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            invalid_output_count += 1
            incomplete_evidence.append(evidence)
        elif chunk_id in seen_chunk_ids:
            duplicate_output_count += 1
            incomplete_evidence.append(evidence)
        else:
            seen_chunk_ids.add(chunk_id)
            if expected_chunk_ids and chunk_id not in expected_chunk_ids:
                unexpected_output_count += 1
                incomplete_evidence.append(evidence)

        response = payload.get("response")
        body = response.get("body") if isinstance(response, dict) else None
        reason = _finish_reason(body) if isinstance(body, dict) else "invalid_response"
        finish_reasons[reason] += 1
        if _response_is_incomplete(response, body, reason):
            incomplete_count += 1
            incomplete_evidence.append(evidence)

    return {
        "output_count": output_count,
        "incomplete_count": incomplete_count,
        "missing_output_count": len(expected_chunk_ids - seen_chunk_ids),
        "duplicate_output_count": duplicate_output_count,
        "unexpected_output_count": unexpected_output_count,
        "invalid_output_count": invalid_output_count,
        "finish_reasons": dict(sorted(finish_reasons.items())),
        "incomplete_evidence": list(dict.fromkeys(incomplete_evidence)),
        "seen_chunk_ids": seen_chunk_ids,
    }


def _find_output(
    output_files: Iterable[Path], output_file_id: str | None
) -> Path | None:
    if not output_file_id:
        return None
    matches = [
        path
        for path in output_files
        if path.name == output_file_id or path.stem == output_file_id
    ]
    if not matches:
        return None
    exact = [path for path in matches if path.name == output_file_id]
    selected = exact or matches
    if len(selected) != 1:
        paths = ", ".join(str(path) for path in selected)
        raise ValueError(f"Ambiguous output artifact for {output_file_id}: {paths}")
    return selected[0]


def audit_batch_artifacts(jobs_dir: Path, outputs_dir: Path) -> dict[str, Any]:
    """Return a repair report without changing artifacts or using runtime services."""

    jobs_dir = jobs_dir.resolve()
    outputs_dir = outputs_dir.resolve()
    if not jobs_dir.is_dir():
        raise ValueError(f"Jobs directory does not exist: {jobs_dir}")
    if not outputs_dir.is_dir():
        raise ValueError(f"Outputs directory does not exist: {outputs_dir}")

    job_paths = sorted(jobs_dir.glob("*.json"))
    output_files = [path for path in outputs_dir.rglob("*") if path.is_file()]
    documents: list[dict[str, Any]] = []
    for job_path in job_paths:
        job = _read_json(job_path)
        doc_id = job.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id:
            raise ValueError(f"Batch job is missing doc_id: {job_path}")

        manifest = job.get("submission_manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        request_path = jobs_dir / f"{doc_id}.jsonl"
        if not request_path.is_file():
            request_path = None
        request_budgets, request_chunk_ids, budget_evidence = _request_artifact(
            request_path
        )
        expected_values = manifest.get("expected_chunk_ids")
        expected_chunk_ids = {
            value for value in expected_values or [] if isinstance(value, str)
        }
        if not expected_chunk_ids:
            expected_chunk_ids = request_chunk_ids
        output_file_id = job.get("output_file_id")
        output_path = _find_output(
            output_files, output_file_id if isinstance(output_file_id, str) else None
        )
        output = _audit_output(output_path, expected_chunk_ids)

        manifest_budget = manifest.get("max_output_tokens")
        if not isinstance(manifest_budget, int) or isinstance(manifest_budget, bool):
            manifest_budget = None
        output_available = output_path is not None
        incomplete_total = (
            len(output["incomplete_evidence"]) + output["missing_output_count"]
            if output_available
            else None
        )
        evidence_paths = {
            "job": _evidence(job_path),
            "request": _evidence(request_path) if request_path else None,
            "output": _evidence(output_path) if output_path else None,
            "budget_lines": budget_evidence,
            "incomplete_lines": output["incomplete_evidence"],
        }
        documents.append(
            {
                "doc_id": doc_id,
                "document": job.get("document_name") or job.get("file_path"),
                "batch_id": job.get("batch_id"),
                "output_file_id": output_file_id,
                "extraction_revision": manifest.get("extraction_revision")
                or job.get("extraction_revision"),
                "output_budgets": {
                    "manifest": manifest_budget,
                    "request_lines": {
                        str(value): count
                        for value, count in sorted(request_budgets.items())
                    },
                },
                "expected_chunk_count": len(expected_chunk_ids),
                "output_count": output["output_count"],
                "finish_reasons": output["finish_reasons"],
                "incomplete_response_count": output["incomplete_count"],
                "missing_output_count": output["missing_output_count"],
                "invalid_output_count": output["invalid_output_count"],
                "duplicate_output_count": output["duplicate_output_count"],
                "unexpected_output_count": output["unexpected_output_count"],
                "incomplete_count": incomplete_total,
                "repair_required": incomplete_total > 0 if output_available else None,
                "audit_status": "assessed"
                if output_available
                else "output_artifact_missing",
                "evidence_paths": evidence_paths,
            }
        )

    return {
        "schema_version": 1,
        "audit_mode": "offline_read_only",
        "document_count": len(documents),
        "repair_document_count": sum(
            1 for document in documents if document["repair_required"] is True
        ),
        "unassessed_document_count": sum(
            1 for document in documents if document["repair_required"] is None
        ),
        "documents": documents,
    }


def _print_text(report: dict[str, Any]) -> None:
    print(
        f"Audited {report['document_count']} documents; "
        f"{report['repair_document_count']} require repair; "
        f"{report['unassessed_document_count']} lack output artifacts."
    )
    for document in report["documents"]:
        revision = document["extraction_revision"] or {}
        revision_label = revision.get("version") or "unknown"
        fingerprint = revision.get("fingerprint")
        if fingerprint:
            revision_label = f"{revision_label}/{fingerprint}"
        budgets = document["output_budgets"]
        print(
            f"{document['doc_id']}: repair={str(document['repair_required']).lower()} "
            f"incomplete={document['incomplete_count']} "
            f"responses={document['output_count']}/{document['expected_chunk_count']} "
            f"revision={revision_label} budgets={json.dumps(budgets, sort_keys=True)} "
            f"finish_reasons={json.dumps(document['finish_reasons'], sort_keys=True)}"
        )
        for label in ("job", "request", "output"):
            value = document["evidence_paths"][label]
            if value:
                print(f"  evidence {label}: {value}")
        for value in document["evidence_paths"]["incomplete_lines"]:
            print(f"  incomplete: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "jobs_dir", type=Path, help="Directory containing saved batch job JSON files"
    )
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        help="Directory containing downloaded output files (defaults to jobs_dir)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    args = parser.parse_args()
    try:
        report = audit_batch_artifacts(args.jobs_dir, args.outputs_dir or args.jobs_dir)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
    else:
        _print_text(report)


if __name__ == "__main__":
    main()
