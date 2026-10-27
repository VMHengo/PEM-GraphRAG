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
from lightrag.evaluation.reviewer_identity import ReviewerIdentity, resolve_reviewer_identity


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
                {"chunk_id": "chunk-1", "file_path": "a.pdf", "content": "Electrode Calendering changes Cathode Porosity. " + "Background. " * 120},
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
    app.dependency_overrides[resolve_reviewer_identity] = lambda: ReviewerIdentity(
        email="reviewer@example.org", default_name="Reviewer A"
    )
    with TestClient(app) as client:
        assert client.get("/evaluation/exploration/sessions").status_code in {401, 403}
        assert client.get("/evaluation/reviewer-identity", headers=HEADERS).json() == {
            "email": "reviewer@example.org", "default_name": "Reviewer A"
        }
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
        assert session["seed_diagnostics"][0]["start"] == "Electrode Calendering"
        assert session["seed_diagnostics"][0]["paths_examined"] == 1
        assert session["seed_diagnostics"][0]["eligible_paths"] == 1
        assert session["seed_diagnostics"][0]["excluded_paths"] == {}
        candidate = session["candidates"][0]
        assert candidate["path"][0]["sources"][0]["candidate_span"]["status"] == "candidate_mention_only"
        assert candidate["path"][0]["sources"][0]["document"] == "a.pdf"
        assert candidate["path"][1]["sources"][0]["document"] == "b.pdf"
        assert candidate["path"][0]["sources"][0]["url"] == "https://example.org/a"
        assert len(candidate["path"][0]["sources"][0]["chunk_excerpt"]) == 900
        assert len(candidate["path"][0]["sources"][0]["full_chunk_text"]) > 900
        assert candidate["path"][0]["sources"][0]["full_chunk_truncated"] is False
        assert candidate["inferred_connection"]["relation"] == "may_indirectly_affect"
        assert candidate["inferred_connection"]["polarity"] == "unknown"

        vote = {
            "candidate_id": candidate["id"], "reviewer": "Reviewer A",
            "reviewer_email": "spoofed@example.org",
            "interest": "interesting", "correctness": "partial",
            "hop_verdicts": ["supported", "unclear"],
            "conditions": "unclear", "inference_verdict": "conditional", "follow_up": True,
            "note": "Check the second paper.",
        }
        saved = client.post(
            f"/evaluation/exploration/sessions/{session_id}/reviews",
            headers=HEADERS, json=vote,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["review"]["extraction_revision"] == {"version": "1.0.1"}
        assert saved.json()["review"]["inference_verdict"] == "conditional"
        assert saved.json()["review"]["inference_rule_version"] == "1"
        assert saved.json()["review"]["reviewer_email"] == "reviewer@example.org"
        assert client.post(
            f"/evaluation/exploration/sessions/{session_id}/reviews",
            headers=HEADERS, json={**vote, "inference_verdict": "verified_fact"},
        ).status_code == 422
        vote["note"] = "Second reading"
        vote.pop("inference_verdict")
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
        assert "may indirectly affect" in sheet.text
        assert "a.pdf" in sheet.text
        listing = client.get("/evaluation/exploration/sessions", headers=HEADERS)
        assert listing.json()["sessions"][0]["candidate_count"] == 1
        assert listing.json()["sessions"][0].get("candidates") is None

    assert calls[0][1].retrieval_strategy == "directed"
    assert calls[0][1].edge_direction == "out"
    assert calls[0][1].ll_keywords == ["Electrode Calendering"]


def test_empty_review_session_preserves_seed_diagnostics(tmp_path):
    class Rag:
        working_dir = str(tmp_path)

        async def aquery_data(self, query, param):
            return {
                "data": {"entities": [], "chunks": []},
                "metadata": {"directed_paths": {
                    "status": "completed", "reason": "no_matching_paths", "paths": [],
                }},
            }

    app = FastAPI()
    app.include_router(create_evaluation_routes(Rag(), "test-key"))
    with TestClient(app) as client:
        response = client.post(
            "/evaluation/exploration/sessions", headers=HEADERS,
            json={"title": "Heat review", "starts": ["Heat Generation"], "hop_depth": 3, "limit": 20},
        )
        assert response.status_code == 202
        session_id = response.json()["session"]["id"]
        for _ in range(50):
            detail = client.get(f"/evaluation/exploration/sessions/{session_id}", headers=HEADERS)
            if detail.json()["session"]["status"] == "completed":
                break
            time.sleep(0.02)
        session = detail.json()["session"]
        assert session["candidates"] == []
        assert session["seed_diagnostics"] == [{
            "start": "Heat Generation",
            "retrieval_status": "completed",
            "retrieval_reason": "no_matching_paths",
            "paths_examined": 0,
            "eligible_paths": 0,
            "excluded_paths": {},
            "empty_reason": "No directed, source-resolved 2-4-hop path survived the filters.",
            "suggested_start_nodes": [],
        }]


def test_review_route_prefers_exact_start_graph_provider(tmp_path):
    class Graph:
        async def get_directed_neighbor_edges_batch(self, node_ids):
            edges = {
                "Battery Cell": [{
                    "src_id": "Battery Cell", "tgt_id": "Heat Generation",
                    "directionality": "directed", "relation_type": "causes",
                    "relation_importance": 0.9, "source_id": "c1",
                }],
                "Heat Generation": [{
                    "src_id": "Heat Generation", "tgt_id": "Thermal Runaway",
                    "directionality": "directed", "relation_type": "leads_to",
                    "relation_importance": 0.9, "source_id": "c2",
                }],
            }
            return {node: edges.get(node, []) for node in node_ids}

    class Chunks:
        async def get_by_ids(self, ids):
            return [{"content": "Battery Cell causes Heat Generation. Heat Generation leads to Thermal Runaway.", "file_path": "paper.pdf"} for _ in ids]

    class Rag:
        working_dir = str(tmp_path)
        chunk_entity_relation_graph = Graph()
        text_chunks = Chunks()

        async def aquery_data(self, query, param):
            raise AssertionError("General retrieval must not fill exact-start review slots")

    app = FastAPI()
    app.include_router(create_evaluation_routes(Rag(), "test-key"))
    with TestClient(app) as client:
        response = client.post(
            "/evaluation/exploration/sessions", headers=HEADERS,
            json={"title": "Battery review", "starts": ["Battery Cell"], "hop_depth": 4, "limit": 20},
        )
        assert response.status_code == 202
        session_id = response.json()["session"]["id"]
        for _ in range(50):
            detail = client.get(f"/evaluation/exploration/sessions/{session_id}", headers=HEADERS)
            if detail.json()["session"]["status"] == "completed":
                break
            time.sleep(0.02)
        session = detail.json()["session"]
        assert session["status"] == "completed"
        assert len(session["candidates"]) == 1
        assert session["candidates"][0]["from"] == "Battery Cell"
        assert session["seed_diagnostics"][0]["excluded_paths"] == {
            "unsupported_path_length": 1,
        }


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
