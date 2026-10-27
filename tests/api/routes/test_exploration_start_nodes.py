"""Read-only, authenticated and cached review start-node recommendations."""

import importlib
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient


_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
create_evaluation_routes = importlib.import_module(
    "lightrag.api.routers.evaluation_routes"
).create_evaluation_routes
sys.argv = _argv


def test_start_nodes_are_authenticated_validated_and_cached(tmp_path):
    calls = []

    class Graph:
        async def get_review_start_recommendations(self, depth):
            calls.append(depth)
            return [{"name": "Mixing Heat", "path_count": 3}]

    app = FastAPI()
    app.include_router(
        create_evaluation_routes(
            SimpleNamespace(
                working_dir=str(tmp_path), chunk_entity_relation_graph=Graph()
            ),
            "test-key",
        )
    )
    with TestClient(app) as client:
        endpoint = "/evaluation/exploration/start-nodes"
        assert client.get(endpoint).status_code in (401, 403)
        headers = {"X-API-Key": "test-key"}
        assert (
            client.get(endpoint, params={"hop_depth": 5}, headers=headers).status_code
            == 422
        )
        response = client.get(endpoint, params={"hop_depth": 3}, headers=headers)
        assert response.status_code == 200
        assert response.json()["items"][0]["name"] == "Mixing Heat"
        assert response.json()["bounded"] is True
        assert (
            client.get(endpoint, params={"hop_depth": 3}, headers=headers).status_code
            == 200
        )
        assert calls == [3]
        assert (
            client.get(
                endpoint, params={"hop_depth": 3, "refresh": True}, headers=headers
            ).status_code
            == 200
        )
        assert calls == [3, 3]


def test_start_nodes_unavailable_without_graph_provider(tmp_path):
    app = FastAPI()
    app.include_router(
        create_evaluation_routes(SimpleNamespace(working_dir=str(tmp_path)), "test-key")
    )
    with TestClient(app) as client:
        response = client.get(
            "/evaluation/exploration/start-nodes", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 503
