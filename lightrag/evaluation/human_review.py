"""Immutable, source-visible review sessions for exploratory path candidates."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lightrag.evaluation.path_inference import infer_indirect_connection


_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root(working_dir: str | Path) -> Path:
    return Path(working_dir).expanduser().resolve() / "exploration_reviews"


def _session_dir(working_dir: str | Path, session_id: str) -> Path:
    if not _ID.fullmatch(session_id):
        raise FileNotFoundError("Review session was not found")
    return _root(working_dir) / session_id


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError("Review session was not found")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Review session data must be an object")
    return value


def create_session(
    working_dir: str | Path,
    *,
    title: str,
    starts: list[str],
    hop_depth: int,
    limit: int,
    extraction_revision: dict[str, Any] | None,
) -> dict[str, Any]:
    session_id = f"review_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    now = _now()
    session = {
        "schema_version": 1,
        "id": session_id,
        "title": title,
        "starts": starts,
        "hop_depth": hop_depth,
        "limit": limit,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "extraction_revision": extraction_revision,
        "completed_starts": 0,
        "seed_errors": [],
        "seed_diagnostics": [],
        "candidates": [],
        "error": None,
    }
    _atomic_json(_session_dir(working_dir, session_id) / "session.json", session)
    return session


def load_session(working_dir: str | Path, session_id: str) -> dict[str, Any]:
    session_dir = _session_dir(working_dir, session_id)
    session = _load_json(session_dir / "session.json")
    reviews_dir = session_dir / "reviews"
    session["reviews"] = sorted(
        (_load_json(path) for path in reviews_dir.glob("*.json")),
        key=lambda item: (item.get("created_at") or "", item.get("id") or ""),
    ) if reviews_dir.is_dir() else []
    return session


def list_sessions(working_dir: str | Path, *, limit: int = 25) -> list[dict[str, Any]]:
    root = _root(working_dir)
    if not root.is_dir():
        return []
    sessions = []
    for path in sorted(root.glob("review_*/session.json"), reverse=True):
        session = _load_json(path)
        summary = {key: value for key, value in session.items() if key != "candidates"}
        summary["candidate_count"] = len(session.get("candidates") or [])
        reviews_dir = path.parent / "reviews"
        summary["review_count"] = len({
            _load_json(review_path).get("candidate_id")
            for review_path in reviews_dir.glob("*.json")
        }) if reviews_dir.is_dir() else 0
        sessions.append(summary)
        if len(sessions) >= limit:
            break
    return sessions


def delete_session(working_dir: str | Path, session_id: str) -> None:
    session_dir = _session_dir(working_dir, session_id)
    session = _load_json(session_dir / "session.json")
    if session["status"] in {"queued", "running"}:
        raise ValueError("A running review session cannot be deleted")
    root = _root(working_dir)
    if session_dir.is_symlink() or session_dir.parent != root:
        raise ValueError("Invalid review session directory")
    shutil.rmtree(session_dir)


def update_session(working_dir: str | Path, session_id: str, **changes: Any) -> dict[str, Any]:
    path = _session_dir(working_dir, session_id) / "session.json"
    session = _load_json(path)
    allowed = {"status", "completed_starts", "seed_errors", "seed_diagnostics", "candidates", "error"}
    if set(changes) - allowed:
        raise ValueError("Unsupported review session update")
    session.update(changes)
    session["updated_at"] = _now()
    _atomic_json(path, session)
    return session


def add_review(
    working_dir: str | Path,
    session_id: str,
    *,
    candidate_id: str,
    reviewer: str,
    interest: str,
    correctness: str,
    hop_verdicts: list[str],
    conditions: str,
    inference_verdict: str | None = None,
    follow_up: bool,
    note: str,
) -> dict[str, Any]:
    session = load_session(working_dir, session_id)
    if session["status"] != "completed":
        raise ValueError("Only completed sessions can be reviewed")
    candidate = next(
        (item for item in session["candidates"] if item["id"] == candidate_id), None
    )
    if candidate is None:
        raise ValueError("Candidate was not found in this session")
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    if len(hop_verdicts) != len(candidate["path"]):
        raise ValueError("Provide one verdict for each hop")
    if inference_verdict not in {None, "plausible", "conditional", "contradicted", "not_derivable"}:
        raise ValueError("Invalid inferred-connection verdict")
    event = {
        "id": f"vote_{uuid.uuid4().hex}",
        "candidate_id": candidate_id,
        "reviewer": reviewer,
        "interest": interest,
        "correctness": correctness,
        "hop_verdicts": hop_verdicts,
        "conditions": conditions,
        "inference_verdict": inference_verdict,
        "inference_rule_version": (candidate.get("inferred_connection") or {}).get("rule_version"),
        "follow_up": follow_up,
        "note": note,
        "created_at": _now(),
        "extraction_revision": session.get("extraction_revision"),
    }
    _atomic_json(_session_dir(working_dir, session_id) / "reviews" / f"{event['id']}.json", event)
    return event


def recover_interrupted_sessions(working_dir: str | Path) -> int:
    count = 0
    for summary in list_sessions(working_dir, limit=1000):
        if summary["status"] in {"queued", "running"}:
            update_session(
                working_dir, summary["id"],
                status="interrupted", error="Server restarted before discovery completed",
            )
            count += 1
    return count


def select_review_candidates(
    discoveries: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    """Review distant subject bridges first while retaining signed alternatives."""

    def priority_key(candidate: dict[str, Any]) -> tuple[bool, float]:
        distance = candidate.get("domain_distance")
        return distance is None, -float(distance or 0)

    queues = [list(item.get("connections") or []) for item in discoveries]
    ordered: list[dict[str, Any]] = []
    seen_paths: set[tuple] = set()
    while any(queues):
        for queue in queues:
            if not queue:
                continue
            candidate = queue.pop(0)
            signature = (
                str(candidate.get("from") or "").casefold(),
                str(candidate.get("to") or "").casefold(),
                tuple(
                    (
                        str(hop.get("source") or "").casefold(),
                        str(hop.get("relation") or "").casefold(),
                        str(hop.get("target") or "").casefold(),
                    )
                    for hop in candidate.get("path") or []
                ),
            )
            if signature in seen_paths:
                continue
            seen_paths.add(signature)
            ordered.append({
                **candidate, "inferred_connection": infer_indirect_connection(candidate)
            })
    ordered.sort(key=priority_key)

    primary: list[dict[str, Any]] = []
    conflicting: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in ordered:
        pair = (str(candidate["from"]).casefold(), str(candidate["to"]).casefold())
        groups.setdefault(pair, []).append(candidate)
    for group in groups.values():
        signed = [
            candidate for candidate in group
            if candidate["inferred_connection"]["polarity"] in {"positive", "negative"}
        ]
        has_opposition = {item["inferred_connection"]["polarity"] for item in signed} == {
            "positive", "negative"
        }
        first = signed[0] if has_opposition else group[0]
        primary.append(first)
        opposite = next(
            (
                item for item in signed
                if item["inferred_connection"]["polarity"]
                != first["inferred_connection"]["polarity"]
            ), None,
        ) if has_opposition else None
        if opposite is not None:
            conflicting.append(opposite)
        alternatives.extend(
            candidate for candidate in group
            if candidate is not first and candidate is not opposite
        )

    conflict_slots = min(len(conflicting), max(1, limit // 5) if limit > 1 else 0)
    selected = primary[:limit - conflict_slots] + conflicting[:conflict_slots]
    for candidate in primary[limit - conflict_slots:] + conflicting[conflict_slots:] + alternatives:
        if len(selected) >= limit:
            break
        selected.append(candidate)
    selected.sort(key=priority_key)
    return [
        {"id": f"candidate-{index:03d}", **candidate}
        for index, candidate in enumerate(selected, start=1)
    ]


def render_review_sheet(session: dict[str, Any]) -> str:
    """Produce a compact offline sheet without promoting proposals to facts."""

    lines = [
        f"# {session['title']}",
        "",
        f"Session: `{session['id']}` | Status: {session['status']}",
        f"Candidates: {len(session.get('candidates') or [])} | Extraction revision: "
        f"`{json.dumps(session.get('extraction_revision'), ensure_ascii=False)}`",
        "",
        "Each path is an unreviewed hypothesis. A candidate text span only locates "
        "mentions; inspect the complete source before judging support.",
    ]
    for index, candidate in enumerate(session.get("candidates") or [], start=1):
        lines.extend([
            "",
            f"## {index}. {candidate['from']} -> {candidate['to']}",
            f"ID: `{candidate['id']}` | Hops: {candidate['hops']} | "
            f"Areas: {', '.join(candidate.get('start_domains') or [])} -> "
            f"{', '.join(candidate.get('target_domains') or [])} | "
            f"Map: {candidate.get('taxonomy_version') or 'legacy'} | "
            f"Distance: {candidate.get('domain_distance')}",
        ])
        inferred = candidate.get("inferred_connection") or {}
        if inferred:
            lines.append(
                f"Indirect hypothesis: {candidate['from']} --[{inferred.get('label')}]--> "
                f"{candidate['to']} (rule: {inferred.get('rule')}; "
                f"status: {inferred.get('status')})"
            )
            for caveat in inferred.get("caveats") or []:
                lines.append(f"- Limitation: {caveat}")
        for hop_index, hop in enumerate(candidate["path"], start=1):
            lines.append(
                f"{hop_index}. **{hop['source']} --{hop['relation']}--> {hop['target']}**"
            )
            for source in hop.get("sources") or []:
                lines.append(
                    f"   - Document: {source.get('document') or 'unknown'}; "
                    f"chunk: `{source.get('chunk_id') or ''}`; "
                    f"URL: {source.get('url') or 'none'}"
                )
                span = source.get("candidate_span") or {}
                span_text = span.get("text") if isinstance(span, dict) else str(span)
                lines.append(
                    f"   - Candidate passage: {span_text or source.get('chunk_excerpt') or ''}"
                )
                if source.get("full_chunk_text"):
                    lines.append("   - Extracted PDF text (retained chunk):")
                    for text_line in str(source["full_chunk_text"]).splitlines():
                        lines.append(f"     > {text_line}")
                    if source.get("full_chunk_truncated"):
                        lines.append("     > [Text truncated; inspect the original document]")
            lines.append("   - Hop support: supported / partial / contradicted / unclear")
        lines.extend([
            "- Overall correctness: supported / partial / contradicted / unclear",
            "- Indirect hypothesis: plausible / conditional / contradicted / not derivable",
            "- Interest: interesting / neutral / not interesting / unclear",
            "- Conditions compatible: yes / no / unclear",
            "- Worth follow-up: yes / no",
            "- Notes:",
        ])
    return "\n".join(lines) + "\n"
