import pytest
from jwt import PyJWKClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from lightrag_mcp.auth import Auth0JWTValidator, AuthError, BearerAuthMiddleware
from lightrag_mcp.config import MCPGatewayConfig


def test_auth0_validator_normalizes_domain_to_issuer():
    validator = Auth0JWTValidator(
        domain="example.eu.auth0.com",
        audience="https://mcp.example.edu",
    )

    assert validator.issuer == "https://example.eu.auth0.com/"


def test_auth0_validator_wraps_jwt_errors(monkeypatch):
    def fail_get_key(self, token):
        raise RuntimeError("bad token")

    monkeypatch.setattr(PyJWKClient, "get_signing_key_from_jwt", fail_get_key)
    validator = Auth0JWTValidator(
        domain="example.eu.auth0.com",
        audience="https://mcp.example.edu",
    )

    with pytest.raises(AuthError):
        validator.validate("not-a-token")


def test_diagnostic_permission_is_required_for_every_protected_route(monkeypatch):
    claims = {"permissions": []}
    monkeypatch.setattr(Auth0JWTValidator, "validate", lambda self, token: claims)
    config = MCPGatewayConfig(
        auth_required=True,
        auth0_domain="example.eu.auth0.com",
        auth0_audience="https://mcp-debug.example.edu",
    )
    app = Starlette(
        routes=[
            Route("/healthz", lambda request: JSONResponse({"ok": True})),
            Route("/mcp/", lambda request: JSONResponse({"private": True})),
        ],
        middleware=[
            Middleware(
                BearerAuthMiddleware,
                config=config,
                required_permission="read:graph-diagnostics",
            )
        ],
    )
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/mcp/").status_code == 401
        headers = {"Authorization": "Bearer valid-token"}
        assert client.get("/mcp/", headers=headers).status_code == 403
        claims["permissions"] = ["read:graph-diagnostics"]
        assert client.get("/mcp/", headers=headers).status_code == 200


def test_diagnostic_permission_cannot_run_with_auth_disabled():
    with pytest.raises(ValueError, match="require authentication"):
        BearerAuthMiddleware(
            object(),
            MCPGatewayConfig(auth_required=False),
            required_permission="read:graph-diagnostics",
        )
