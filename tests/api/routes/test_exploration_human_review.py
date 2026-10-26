"""Read-only exploratory discovery and persisted human review route checks."""

from __future__ import annotations

import importlib
import sys
import time

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lightrag.evaluation.human_review import (
    add_review,
    create_session,
    load_session,
    select_review_candidates,
    update_session,
)


_original_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
create_evaluation_routes = importlib.import_module(
    "lightrag.api.routers.evaluation_routes"
).create_evaluation_routes
sys.argv = _original_argv

HEADERS = {"X-API-Key": "test-key"}


def _payload():
    return {
        "status": "success",
        "data": {
            "chunks": [
                {"chunk_id": "chunk-1", "file_path": "a.pdf", "content": "Electrode Calendering changes Cathode Porosity."},
                {"chunk_id": "chunk-2", "file_path": "b.pdf", "content": "Cathode Porosity can influence Lithium Plating."},
            ],
            "references": [{"file_path": "a.pdf", "source_url": "https://example.org/a"}],
        },
        "metadata": {
            "directed_paths": {
                "status": "completed",
                "paths": [{
                    "nodes": ["Electrode Calendering", "Cathode Porosity", "Lithium Plating"],
                    "edges": [
                        {"source": "Electrode Calendering", "target": "Cathode Porosity", "relation_type": "causes", "directionality": "directed", "source_ids": ["chunk-1"]},
                        {"source": "Cathode Porosity", "target": "Lithium Plating", "relation_type": "influences", "directionality": "directed", "source_ids": ["chunk-2"]},
                    ],
                }],
            }
        },
    }


def test_review_session_routes_persist_hop_verdicts_and_sheet(tmp_path):
    calls = []

    class Rag:
        working_dir = str(tmp_path)

        def get_extraction_revision(self):
            return {"version": "1.0.1"}

        async def aquery_data(self, query, param):
            calls.append((query, param))
            return _payload()

    app = FastAPI()
    app.include_router(create_evaluation_routes(Rag(), "test-key"))
    with TestClient(app) as client:
        assert client.get("/evaluation/exploration/sessions").status_code in {401, 403}
        assert client.post(
            "/evaluation/exploration/sessions", headers=HEADERS,
            json={"title": "Too deep", "starts": ["Electrode Calendering"], "hop_depth": 5, "limit": 20},
        ).status_code == 422
        assert client.post(
            "/evaluation/exploration/sessions", headers=HEADERS,
            json={"title": "Too many", "starts": ["Electrode Calendering"], "hop_depth": 3, "limit": 21},
        ).status_code == 422
        started = client.post(
            "/evaluation/exploration/sessions", headers=HEADERS,
            json={"title": "Electrode review", "starts": ["Electrode Calendering"], "hop_depth": 3, "limit": 20},
        )
        assert started.status_code == 202, started.text
        session_id = started.json()["session"]["id"]
        for _ in range(50):
            detail = client.get(f"/evaluation/exploration/sessions/{session_id}", headers=HEADERS)
            if detail.json()["session"]["status"] == "completed":
                break
            time.sleep(0.02)
        session = detail.json()["session"]
        assert session["status"] == "completed", session
        assert session["extraction_revision"] == {"version": "1.0.1"}
        assert session["completed_starts"] == 1
        assert len(session["candidates"]) == 1
        candidate = session["candidates"][0]
        assert candidate["path"][0]["sources"][0]["candidate_span"]["status"] == "candidate_mention_only"
        assert candidate["path"][0]["sources"][0]["document"] == "a.pdf"
        assert candidate["path"][1]["sources"][0]["document"] == "b.pdf"
        assert candidate["path"][0]["sources"][0]["url"] == "https://example.org/a"

        vote = {
            "candidate_id": candidate["id"], "reviewer": "Reviewer A",
            "interest": "interesting", "correctness": "partial",
            "hop_verdicts": ["supported", "unclear"],
            "conditions": "unclear", "follow_up": True,
            "note": "Check the second paper.",
        }
        saved = client.post(
            f"/evaluation/exploration/sessions/{session_id}/reviews",
            headers=HEADERS, json=vote,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["review"]["extraction_revision"] == {"version": "1.0.1"}
        vote["note"] = "Second reading"
        assert client.post(
            f"/evaluation/exploration/sessions/{session_id}/reviews",
            headers=HEADERS, json=vote,
        ).status_code == 200
        reloaded = client.get(f"/evaluation/exploration/sessions/{session_id}", headers=HEADERS)
        assert len(reloaded.json()["session"]["reviews"]) == 2
        sheet = client.get(
            f"/evaluation/exploration/sessions/{session_id}/review-sheet", headers=HEADERS
        )
        assert sheet.status_code == 200
        assert "Electrode Calendering --causes--> Cathode Porosity" in sheet.text
        assert "a.pdf" in sheet.text
        listing = client.get("/evaluation/exploration/sessions", headers=HEADERS)
        assert listing.json()["sessions"][0]["candidate_count"] == 1
        assert listing.json()["sessions"][0].get("candidates") is None

    assert calls[0][1].retrieval_strategy == "directed"
    assert calls[0][1].edge_direction == "out"
    assert calls[0][1].ll_keywords == ["Electrode Calendering"]


def test_hop_count_and_unknown_candidate_cannot_be_reviewed(tmp_path):
    session = create_session(
        tmp_path, title="Case", starts=["Electrode Calendering"],
        hop_depth=2, limit=20, extraction_revision=None,
    )
    update_session(
        tmp_path, session["id"], status="completed",
        candidates=[{"id": "candidate-001", "path": [{}, {}]}],
    )
    base = dict(
        candidate_id="candidate-001", reviewer="Reviewer A",
        interest="interesting", correctness="supported", conditions="compatible",
        follow_up=True, note="",
    )
    with pytest.raises(ValueError, match="each hop"):
        add_review(tmp_path, session["id"], hop_verdicts=["supported"], **base)
    with pytest.raises(ValueError, match="not found"):
        add_review(
            tmp_path, session["id"], hop_verdicts=["supported", "supported"],
            **{**base, "candidate_id": "candidate-999"},
        )
    with pytest.raises(ValueError, match="Reviewer is required"):
        add_review(
            tmp_path, session["id"], hop_verdicts=["supported", "supported"],
            **{**base, "reviewer": " "},
        )
    assert load_session(tmp_path, session["id"])["reviews"] == []


def test_candidate_selection_round_robins_seeds_and_deduplicates_pairs():
    def item(start, target):
        return {"from": start, "to": target, "hops": 2, "path": [{}, {}]}

    selected = select_review_candidates([
        {"connections": [item("A", "B"), item("A", "C")]},
        {"connections": [item("X", "Y"), item("A", "B")]},
    ], limit=20)
    assert [(case["from"], case["to"]) for case in selected] == [
        ("A", "B"), ("X", "Y"), ("A", "C")
    ]
