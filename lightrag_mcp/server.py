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
from lightrag_mcp.lightrag_client import (
    LightRAGQueryError,
    fetch_document_context,
    query_lightrag,
    search_documents,
)

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


@mcp.tool()
async def search_pem_documents(
    query: Annotated[
        str,
        Field(
            min_length=3,
            max_length=500,
            description="Search processed PEM GraphRAG documents by title, path, and summary.",
        ),
    ],
    limit: Annotated[
        int,
        Field(
            default=10,
            ge=1,
            le=20,
            description="Maximum number of matching documents to return.",
        ),
    ] = 10,
) -> dict:
    """Search processed documents and return compact source metadata."""
    try:
        return await search_documents(
            base_url=config.lightrag_base_url,
            query=query,
            limit=limit,
            api_key=config.lightrag_api_key,
            timeout=config.lightrag_timeout,
        )
    except (LightRAGQueryError, ValueError) as exc:
        return {"error": str(exc), "query": query, "documents": []}


@mcp.tool()
async def fetch_pem_document_context(
    document_id: Annotated[
        str,
        Field(
            min_length=3,
            description="Document id returned by search_pem_documents.",
        ),
    ],
    query: Annotated[
        str | None,
        Field(
            default=None,
            max_length=500,
            description="Optional focus query used to retrieve relevant chunks from the document.",
        ),
    ] = None,
    max_chunks: Annotated[
        int,
        Field(
            default=5,
            ge=1,
            le=10,
            description="Maximum number of document chunks to return.",
        ),
    ] = 5,
) -> dict:
    """Fetch bounded, source-bearing chunks from one processed document."""
    try:
        return await fetch_document_context(
            base_url=config.lightrag_base_url,
            document_id=document_id,
            query=query,
            max_chunks=max_chunks,
            api_key=config.lightrag_api_key,
            timeout=config.lightrag_timeout,
        )
    except (LightRAGQueryError, ValueError) as exc:
        return {
            "error": str(exc),
            "document_id": document_id,
            "query": query,
            "chunks": [],
            "references": [],
        }


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
