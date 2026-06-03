from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from lightrag_mcp.auth import BearerAuthMiddleware
from lightrag_mcp.config import get_config
from lightrag_mcp.lightrag_client import LightRAGQueryError, query_lightrag

config = get_config()

mcp = FastMCP(
    "PEM GraphRAG",
    host="0.0.0.0",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
async def query_pem_graphrag(
    question: Annotated[
        str,
        Field(
            min_length=3,
            description="Question to answer from the PEM GraphRAG knowledge base.",
        ),
    ],
    mode: Literal["mix", "local", "global", "hybrid", "naive"] = "mix",
) -> dict:
    """Query the read-only PEM GraphRAG knowledge base and return references."""
    try:
        return await query_lightrag(
            base_url=config.lightrag_base_url,
            question=question,
            mode=mode,
            api_key=config.lightrag_api_key,
            timeout=config.lightrag_timeout,
        )
    except (LightRAGQueryError, ValueError) as exc:
        return {"error": str(exc), "mode": mode}


async def healthz(_request):
    return JSONResponse({"status": "ok", "service": "pem-graphrag-mcp"})


mcp_app = mcp.streamable_http_app()

app = Starlette(
    routes=[
        Route("/healthz", healthz, methods=["GET"]),
        Mount("/mcp", app=mcp_app),
    ],
    middleware=[Middleware(BearerAuthMiddleware, config=config)],
    lifespan=mcp_app.router.lifespan_context,
)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
