from __future__ import annotations

from typing import Any, Literal

import httpx

QueryMode = Literal["mix", "local", "global", "hybrid", "naive"]
ALLOWED_QUERY_MODES: set[str] = {"mix", "local", "global", "hybrid", "naive"}


class LightRAGQueryError(Exception):
    """Raised when the MCP gateway cannot query LightRAG successfully."""


def normalize_mode(mode: str | None) -> QueryMode:
    normalized = (mode or "mix").strip().lower()
    if normalized not in ALLOWED_QUERY_MODES:
        raise ValueError(
            "mode must be one of: " + ", ".join(sorted(ALLOWED_QUERY_MODES))
        )
    return normalized  # type: ignore[return-value]


def map_lightrag_response(payload: dict[str, Any], mode: QueryMode) -> dict[str, Any]:
    return {
        "answer": payload.get("response", ""),
        "references": payload.get("references") or [],
        "mode": mode,
    }


async def query_lightrag(
    *,
    base_url: str,
    question: str,
    mode: str | None,
    api_key: str | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    query_mode = normalize_mode(mode)
    payload = {
        "query": question,
        "mode": query_mode,
        "include_references": True,
        "stream": False,
        "response_type": "Multiple Paragraphs",
    }
    headers = {"X-API-Key": api_key} if api_key else {}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/query",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LightRAGQueryError(
            f"LightRAG query failed with HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise LightRAGQueryError("LightRAG query service is unavailable") from exc

    return map_lightrag_response(response.json(), query_mode)

