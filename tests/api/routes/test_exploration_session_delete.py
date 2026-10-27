"""Review-session progress counts and deletion remain scoped to one session."""

import importlib
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lightrag.evaluation.human_review import (
    add_review,
    create_session,
    delete_session,
    list_sessions,
    update_session,
)


_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
create_evaluation_routes = importlib.import_module(
    "lightrag.api.routers.evaluation_routes"
).create_evaluation_routes
sys.argv = _argv


def _session(tmp_path, title):
    session = create_session(
        tmp_path,
        title=title,
        starts=["Mixing Heat"],
        hop_depth=2,
        limit=20,
        extraction_revision=None,
    )
    update_session(
        tmp_path,
        session["id"],
        status="completed",
        candidates=[{"id": "case-1", "path": [{}]}, {"id": "case-2", "path": [{}]}],
    )
    return session


def test_review_count_is_distinct_cases_and_delete_is_scoped(tmp_path):
    first = _session(tmp_path, "First")
    second = _session(tmp_path, "Second")
    for reviewer in ("Hoang", "Other"):
        add_review(
            tmp_path,
            first["id"],
            candidate_id="case-1",
            reviewer=reviewer,
            interest="interesting",
            correctness="supported",
            hop_verdicts=["supported"],
            conditions="compatible",
            follow_up=False,
            note="",
        )
    summary = next(
        item for item in list_sessions(tmp_path) if item["id"] == first["id"]
    )
    assert summary["review_count"] == 1
    assert summary["candidate_count"] == 2

    app = FastAPI()
    app.include_router(
        create_evaluation_routes(SimpleNamespace(working_dir=str(tmp_path)), "test-key")
    )
    with TestClient(app) as client:
        url = f"/evaluation/exploration/sessions/{first['id']}"
        assert client.delete(url).status_code in (401, 403)
        assert client.delete(url, headers={"X-API-Key": "test-key"}).status_code == 204
        assert client.delete(url, headers={"X-API-Key": "test-key"}).status_code == 404
    assert [item["id"] for item in list_sessions(tmp_path)] == [second["id"]]


def test_running_session_cannot_be_deleted(tmp_path):
    session = create_session(
        tmp_path,
        title="Running",
        starts=["Mixing Heat"],
        hop_depth=2,
        limit=20,
        extraction_revision=None,
    )
    with pytest.raises(ValueError, match="running"):
        delete_session(tmp_path, session["id"])
    with pytest.raises(FileNotFoundError):
        delete_session(tmp_path, "../outside")
