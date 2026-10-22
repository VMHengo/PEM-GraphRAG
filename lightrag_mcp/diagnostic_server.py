"""Developer-only, bounded graph diagnostics for the staging MCP endpoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from neo4j import AsyncGraphDatabase
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from lightrag_mcp.auth import BearerAuthMiddleware
from lightrag_mcp.config import get_config
from lightrag_mcp.graph_diagnostics import (
    inspect_chain as find_chain,
    inspect_entity as find_entity,
    inspect_relationships as find_relationships,
)

_PERMISSION = "read:graph-diagnostics"
config = get_config()
if not config.auth_required:
    raise ValueError("Diagnostic MCP requires MCP_AUTH_REQUIRED=true")

uri = os.environ.get("NEO4J_URI", "").strip()
username = os.environ.get("NEO4J_USERNAME", "").strip()
password = os.environ.get("NEO4J_PASSWORD", "")
database = os.environ.get("NEO4J_DATABASE", "neo4j").strip()
if not uri or not username or not password or not database:
    raise ValueError("Diagnostic MCP requires Neo4j URI, user, password and database")

driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
mcp = FastMCP(
    "PEM GraphRAG Staging Diagnostics",
    host="0.0.0.0",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
async def inspect_entity(
    name: Annotated[str, Field(min_length=2, max_length=160)],
    limit: Annotated[int, Field(ge=1, le=20)] = 10,
) -> dict:
    """Inspect one named graph entity and bounded immediate relationships."""
    return await find_entity(driver, database, name, limit)


@mcp.tool()
async def inspect_relationships(
    entity: Annotated[str, Field(min_length=2, max_length=160)],
    document: Annotated[str | None, Field(max_length=200)] = None,
    limit: Annotated[int, Field(ge=1, le=30)] = 20,
) -> dict:
    """Inspect source-bearing semantic relationships around an entity."""
    return await find_relationships(driver, database, entity, document, limit)


@mcp.tool()
async def inspect_chain(
    start: Annotated[str, Field(min_length=2, max_length=160)],
    end: Annotated[str, Field(min_length=2, max_length=160)],
    max_hops: Annotated[int, Field(ge=1, le=3)] = 2,
    limit: Annotated[int, Field(ge=1, le=10)] = 10,
) -> dict:
    """Inspect bounded paths and semantic directions between named entities."""
    return await find_chain(driver, database, start, end, max_hops, limit)


async def healthz(_request):
    return JSONResponse({"status": "ok", "service": "pem-graphrag-diagnostics"})


def _issuer() -> str:
    domain = (config.auth0_domain or "").strip()
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    return domain.rstrip("/")


async def protected_resource_metadata(_request):
    return JSONResponse(
        {
            "resource": config.auth0_audience,
            "authorization_servers": [_issuer()],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [_PERMISSION],
            "resource_name": "PEM GraphRAG Staging Diagnostics",
        }
    )


async def authorization_server_metadata(_request):
    issuer = _issuer()
    return JSONResponse(
        {
            "issuer": issuer + "/",
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "jwks_uri": f"{issuer}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "scopes_supported": ["openid", "profile", "email", _PERMISSION],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
                "none",
            ],
            "code_challenge_methods_supported": ["S256"],
        }
    )


mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp_app.router.lifespan_context(app):
        try:
            yield
        finally:
            await driver.close()


app = Starlette(
    routes=[
        Route("/healthz", healthz, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", protected_resource_metadata),
        Route("/.well-known/oauth-authorization-server", authorization_server_metadata),
        Route("/.well-known/openid-configuration", authorization_server_metadata),
        Route("/mcp/.well-known/oauth-protected-resource", protected_resource_metadata),
        Route(
            "/mcp/.well-known/oauth-authorization-server", authorization_server_metadata
        ),
        Route("/mcp/.well-known/openid-configuration", authorization_server_metadata),
        Mount("/mcp", app=mcp_app),
    ],
    middleware=[
        Middleware(
            BearerAuthMiddleware,
            config=config,
            required_permission=_PERMISSION,
        )
    ],
    lifespan=lifespan,
)
