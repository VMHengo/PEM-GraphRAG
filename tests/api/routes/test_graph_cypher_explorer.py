"""Offline route tests for the developer-facing read-only Cypher endpoint."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


_original_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
_graph_routes = importlib.import_module("lightrag.api.routers.graph_routes")
sys.argv = _original_argv

create_graph_routes = _graph_routes.create_graph_routes

_API_KEY = "test-key"
_HEADERS = {"X-API-Key": _API_KEY}


def _client(execute_result=None, execute_error=None) -> tuple[TestClient, AsyncMock]:
    execute = AsyncMock(return_value=execute_result)
    if execute_error is not None:
        execute.side_effect = execute_error
    rag = SimpleNamespace(
        chunk_entity_relation_graph=SimpleNamespace(execute_readonly_cypher=execute)
    )
    app = FastAPI()
    app.include_router(create_graph_routes(rag, api_key=_API_KEY))
    return TestClient(app), execute


def test_readonly_cypher_route_forwards_bounded_request():
    expected = {
        "columns": ["source", "edge", "target"],
        "rows": [],
        "nodes": [],
        "edges": [],
        "truncated": False,
        "execution_time_ms": 3,
    }
    client, execute = _client(execute_result=expected)

    response = client.post(
        "/graph/cypher/read",
        headers=_HEADERS,
        json={
            "query": "MATCH (source)-[edge:DIRECTED]-(target) RETURN source, edge, target",
            "parameters": {"relation_types": ["causes"]},
            "max_records": 50,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == expected
    execute.assert_awaited_once_with(
        query="MATCH (source)-[edge:DIRECTED]-(target) RETURN source, edge, target",
        parameters={"relation_types": ["causes"]},
        max_records=50,
    )


def test_readonly_cypher_route_maps_validation_errors_to_400():
    client, _ = _client(execute_error=ValueError("'DELETE' is not allowed"))

    response = client.post(
        "/graph/cypher/read",
        headers=_HEADERS,
        json={"query": "MATCH (n) DELETE n RETURN n"},
    )

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_readonly_cypher_route_maps_unsupported_storage_to_501():
    client, _ = _client(execute_error=NotImplementedError())

    response = client.post(
        "/graph/cypher/read",
        headers=_HEADERS,
        json={"query": "MATCH (n) RETURN n"},
    )

    assert response.status_code == 501


def test_readonly_cypher_route_honors_optional_developer_allowlist(monkeypatch):
    monkeypatch.setenv("GRAPH_CYPHER_EXPLORER_ALLOWED_EMAILS", "dev@example.test")
    client, execute = _client(
        execute_result={
            "columns": [],
            "rows": [],
            "nodes": [],
            "edges": [],
            "truncated": False,
            "execution_time_ms": 1,
        }
    )

    denied = client.post(
        "/graph/cypher/read",
        headers={**_HEADERS, "X-Auth-Request-Email": "other@example.test"},
        json={"query": "MATCH (n) RETURN n"},
    )
    allowed = client.post(
        "/graph/cypher/read",
        headers={**_HEADERS, "X-Auth-Request-Email": "dev@example.test"},
        json={"query": "MATCH (n) RETURN n"},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    execute.assert_awaited_once()
