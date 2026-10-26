"""Immutable, source-visible review sessions for exploratory path candidates."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
        sessions.append(summary)
        if len(sessions) >= limit:
            break
    return sessions


def update_session(working_dir: str | Path, session_id: str, **changes: Any) -> dict[str, Any]:
    path = _session_dir(working_dir, session_id) / "session.json"
    session = _load_json(path)
    allowed = {"status", "completed_starts", "seed_errors", "candidates", "error"}
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
    event = {
        "id": f"vote_{uuid.uuid4().hex}",
        "candidate_id": candidate_id,
        "reviewer": reviewer,
        "interest": interest,
        "correctness": correctness,
        "hop_verdicts": hop_verdicts,
        "conditions": conditions,
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
    """Round-robin seed results and keep distinct endpoint pairs."""

    queues = [list(item.get("connections") or []) for item in discoveries]
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    while len(selected) < limit and any(queues):
        for queue in queues:
            if not queue or len(selected) >= limit:
                continue
            candidate = queue.pop(0)
            key = (str(candidate["from"]).casefold(), str(candidate["to"]).casefold())
            if key in seen:
                continue
            seen.add(key)
            selected.append({"id": f"candidate-{len(selected) + 1:03d}", **candidate})
    return selected


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
            f"{', '.join(candidate.get('target_domains') or [])}",
        ])
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
                lines.append(
                    f"   - Candidate passage: {span.get('text') or source.get('chunk_excerpt') or ''}"
                )
            lines.append("   - Hop support: supported / partial / contradicted / unclear")
        lines.extend([
            "- Overall correctness: supported / partial / contradicted / unclear",
            "- Interest: interesting / neutral / not interesting / unclear",
            "- Conditions compatible: yes / no / unclear",
            "- Worth follow-up: yes / no",
            "- Notes:",
        ])
    return "\n".join(lines) + "\n"
