"""Route coverage for the persisted evaluation benchmark run history."""

from __future__ import annotations

import importlib
import json
import sys
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lightrag.evaluation.run_history import complete_run, create_run


_original_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
_evaluation_routes = importlib.import_module("lightrag.api.routers.evaluation_routes")
sys.argv = _original_argv

create_evaluation_routes = _evaluation_routes.create_evaluation_routes


_API_KEY = "test-key"
_HEADERS = {"X-API-Key": _API_KEY}


def _completed_run(tmp_path):
    run = create_run(
        tmp_path,
        benchmark_id="demo",
        benchmark_name="Demo benchmark",
        case_count=1,
        mode="graph",
        title="Initial title",
        note="Initial note",
    )
    complete_run(
        tmp_path,
        run["id"],
        {
            "benchmark": {"id": "demo", "name": "Demo benchmark", "case_count": 1},
            "run": {"mode": "graph", "generated_at": "2026-09-28T12:00:00+00:00"},
            "scores": {"overall": 80.0},
            "summary": {},
            "cases": {"graph": [], "query": []},
            "quality_gates": {"configured": False, "passed": True, "checks": []},
            "failed_checks": [],
        },
    )
    return run


def _client(tmp_path) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_evaluation_routes(SimpleNamespace(working_dir=str(tmp_path)), _API_KEY)
    )
    return TestClient(app)


class _Graph:
    async def get_all_nodes(self):
        return [{"entity_id": "Electrode Stacking"}]

    async def get_all_edges(self):
        return []


def test_evaluation_run_history_routes_list_load_and_update(tmp_path):
    run = _completed_run(tmp_path)
    client = _client(tmp_path)

    listing = client.get("/evaluation/runs?benchmark_id=demo", headers=_HEADERS)
    detail = client.get(f"/evaluation/runs/{run['id']}", headers=_HEADERS)
    updated = client.patch(
        f"/evaluation/runs/{run['id']}",
        headers=_HEADERS,
        json={"title": "Prompt version 2", "note": "Updated through the API"},
    )

    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert listing.json()["runs"][0]["scores"]["overall"] == 80.0
    assert detail.status_code == 200, detail.text
    assert detail.json()["result"]["scores"]["overall"] == 80.0
    assert updated.status_code == 200, updated.text
    assert updated.json()["run"]["title"] == "Prompt version 2"


def test_evaluation_run_route_starts_a_background_graph_benchmark(tmp_path, monkeypatch):
    benchmark_dir = tmp_path / "evaluation" / "benchmarks"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "demo.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo benchmark",
                "cases": [
                    {
                        "id": "electrode",
                        "question": "Is electrode stacking present?",
                        "expected_entities": ["Electrode Stacking"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVALUATION_BENCHMARK_DIR", str(benchmark_dir))

    rag = SimpleNamespace(
        working_dir=str(tmp_path / "rag_storage"),
        chunk_entity_relation_graph=_Graph(),
    )
    app = FastAPI()
    app.include_router(create_evaluation_routes(rag, _API_KEY))

    with TestClient(app) as client:
        started = client.post(
            "/evaluation/benchmarks/demo/runs",
            headers=_HEADERS,
            json={"mode": "graph", "title": "Async graph check", "note": "Route test"},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["id"]

        detail = None
        for _ in range(20):
            detail = client.get(f"/evaluation/runs/{run_id}", headers=_HEADERS)
            if detail.json()["run"]["status"] == "completed":
                break
            time.sleep(0.02)

    assert detail is not None
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "completed"
    assert detail.json()["result"]["scores"]["graph"] == 100.0
