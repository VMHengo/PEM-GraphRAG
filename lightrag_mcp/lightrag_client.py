from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

import httpx

QueryMode = Literal["mix", "local", "global", "hybrid", "naive"]
ALLOWED_QUERY_MODES: set[str] = {"mix", "local", "global", "hybrid", "naive"}
DEFAULT_TOP_K = 80
DEFAULT_CHUNK_TOP_K = 20
MAX_DOCUMENT_SEARCH_LIMIT = 20
MAX_DOCUMENT_QUERY_LENGTH = 500
MAX_FETCH_CHUNKS = 10
MAX_CHARS_PER_CHUNK = 2000
MAX_TOTAL_CONTEXT_CHARS = 12000
DOCUMENT_PAGE_SIZE = 200


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
        "citations": build_citations(payload.get("references") or []),
        "mode": mode,
        "retrieval": {
            "top_k": DEFAULT_TOP_K,
            "chunk_top_k": DEFAULT_CHUNK_TOP_K,
            "include_chunk_content": True,
        },
    }


def _headers(api_key: str | None) -> dict[str, str]:
    return {"X-API-Key": api_key} if api_key else {}


def _validate_query(query: str) -> str:
    normalized = query.strip()
    if len(normalized) < 3:
        raise ValueError("query must be at least 3 characters long")
    if len(normalized) > MAX_DOCUMENT_QUERY_LENGTH:
        raise ValueError(
            f"query must be at most {MAX_DOCUMENT_QUERY_LENGTH} characters long"
        )
    return normalized


def _validate_limit(limit: int, *, maximum: int, name: str) -> int:
    if limit < 1:
        raise ValueError(f"{name} must be at least 1")
    return min(limit, maximum)


def _normalize_status(status: Any) -> str:
    return str(status or "").split(".")[-1].lower()


def _basename(path: str | None) -> str:
    if not path:
        return ""
    normalized = str(path).replace("\\", "/")
    return PurePosixPath(normalized).name or PureWindowsPath(str(path)).name


def _document_title(document: dict[str, Any]) -> str:
    file_path = str(document.get("file_path") or "")
    if file_path:
        return _basename(file_path)
    return str(document.get("id") or "Untitled document")


def _normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": document.get("id"),
        "title": _document_title(document),
        "file_path": document.get("file_path"),
        "status": _normalize_status(document.get("status")),
        "content_summary": document.get("content_summary") or "",
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
        "track_id": document.get("track_id"),
        "chunks_count": document.get("chunks_count"),
        "content_length": document.get("content_length"),
    }


def _score_document(document: dict[str, Any], query_terms: set[str]) -> float:
    if not query_terms:
        return 0.0

    title = str(document.get("title") or "").lower()
    file_path = str(document.get("file_path") or "").lower()
    summary = str(document.get("content_summary") or "").lower()
    haystacks = [(title, 3.0), (file_path, 2.0), (summary, 1.0)]
    score = 0.0
    for term in query_terms:
        for text, weight in haystacks:
            if term in text:
                score += weight
    return score


def _query_terms(query: str) -> set[str]:
    return {part.lower() for part in query.replace("_", " ").split() if len(part) > 2}


def _same_document_path(reference_path: str | None, document_path: str | None) -> bool:
    if not reference_path or not document_path:
        return False
    ref = str(reference_path).replace("\\", "/").strip().lower()
    doc = str(document_path).replace("\\", "/").strip().lower()
    return ref == doc or _basename(ref).lower() == _basename(doc).lower()


def _trim_content(content: Any, remaining_chars: int) -> str:
    if isinstance(content, list):
        text = "\n\n".join(str(item) for item in content)
    else:
        text = str(content or "")
    text = text.strip()
    if remaining_chars <= 0:
        return ""
    return text[: min(MAX_CHARS_PER_CHUNK, remaining_chars)]


def _citation_url(_source: dict[str, Any]) -> str | None:
    # Future hook: return a stable HTTPS URL for a source document or chunk here,
    # e.g. https://lightrag.example.edu/sources/{document_id}?chunk={chunk_id}

    # document_id = source.get("document_id")
    # chunk_id = source.get("chunk_id")
    # if not document_id:
    #     return None
    # url = f"https://lightrag.vmhnguyen.dev/sources/{document_id}"
    # if chunk_id:
    #     url += f"?chunk={chunk_id}"
    # return url
    
    return None


def _excerpt(content: Any, max_chars: int = 500) -> str:
    if isinstance(content, list):
        text = "\n\n".join(str(item) for item in content)
    else:
        text = str(content or "")
    return text.strip()[:max_chars]


def build_citations(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        file_path = source.get("file_path")
        title = (
            source.get("title")
            or source.get("document_title")
            or _basename(str(file_path or ""))
            or source.get("document_id")
            or f"Source {index}"
        )
        citation_source = {
            "document_id": source.get("document_id"),
            "file_path": file_path,
            "chunk_id": source.get("chunk_id"),
            "reference_id": source.get("reference_id"),
            "page": source.get("page"),
        }
        citations.append(
            {
                "label": f"[{index}]",
                "title": title,
                "kind": "document_chunk" if source.get("chunk_id") else "document",
                "url": source.get("url") or _citation_url(citation_source),
                "excerpt": _excerpt(source.get("content")),
                "source": citation_source,
            }
        )
    return citations


async def _post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    payload: dict[str, Any],
    api_key: str | None,
) -> dict[str, Any]:
    response = await client.post(url, json=payload, headers=_headers(api_key))
    response.raise_for_status()
    return response.json()


async def _get_documents_page(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str | None,
    page: int = 1,
) -> dict[str, Any]:
    return await _post_json(
        client,
        f"{base_url.rstrip('/')}/documents/paginated",
        payload={
            "status_filters": ["PROCESSED"],
            "page": page,
            "page_size": DOCUMENT_PAGE_SIZE,
            "sort_field": "updated_at",
            "sort_direction": "desc",
        },
        api_key=api_key,
    )


async def _list_processed_documents(
    *,
    base_url: str,
    api_key: str | None,
    timeout: float,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for page in range(1, max_pages + 1):
            payload = await _get_documents_page(
                client, base_url=base_url, api_key=api_key, page=page
            )
            documents.extend(payload.get("documents") or [])
            pagination = payload.get("pagination") or {}
            if not pagination.get("has_next"):
                break
    return documents


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
        "top_k": DEFAULT_TOP_K,
        "chunk_top_k": DEFAULT_CHUNK_TOP_K,
        "include_references": True,
        "include_chunk_content": True,
        "stream": False,
        "response_type": "Multiple Paragraphs",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/query",
                json=payload,
                headers=_headers(api_key),
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LightRAGQueryError(
            f"LightRAG query failed with HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise LightRAGQueryError("LightRAG query service is unavailable") from exc

    return map_lightrag_response(response.json(), query_mode)


async def search_documents(
    *,
    base_url: str,
    query: str,
    limit: int = 10,
    api_key: str | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    normalized_query = _validate_query(query)
    capped_limit = _validate_limit(
        limit, maximum=MAX_DOCUMENT_SEARCH_LIMIT, name="limit"
    )

    try:
        documents = await _list_processed_documents(
            base_url=base_url, api_key=api_key, timeout=timeout
        )
    except httpx.HTTPStatusError as exc:
        raise LightRAGQueryError(
            f"LightRAG document search failed with HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise LightRAGQueryError("LightRAG document service is unavailable") from exc

    terms = _query_terms(normalized_query)
    scored_documents: list[tuple[float, dict[str, Any]]] = []
    for raw_document in documents:
        document = _normalize_document(raw_document)
        score = _score_document(document, terms)
        if score > 0:
            scored_documents.append((score, document))

    scored_documents.sort(
        key=lambda item: (item[0], str(item[1].get("updated_at") or "")),
        reverse=True,
    )

    return {
        "query": normalized_query,
        "limit": capped_limit,
        "documents": [
            {**document, "score_hint": score}
            for score, document in scored_documents[:capped_limit]
        ],
        "citations": build_citations(
            [
                {
                    **document,
                    "document_id": document.get("document_id"),
                    "title": document.get("title"),
                    "content": document.get("content_summary"),
                }
                for _, document in scored_documents[:capped_limit]
            ]
        ),
    }


async def fetch_document_context(
    *,
    base_url: str,
    document_id: str,
    query: str | None = None,
    max_chunks: int = 5,
    api_key: str | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    normalized_document_id = document_id.strip()
    if not normalized_document_id:
        raise ValueError("document_id is required")
    capped_max_chunks = _validate_limit(
        max_chunks, maximum=MAX_FETCH_CHUNKS, name="max_chunks"
    )

    try:
        documents = await _list_processed_documents(
            base_url=base_url, api_key=api_key, timeout=timeout
        )
    except httpx.HTTPStatusError as exc:
        raise LightRAGQueryError(
            f"LightRAG document lookup failed with HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise LightRAGQueryError("LightRAG document service is unavailable") from exc

    document = next(
        (
            _normalize_document(raw_document)
            for raw_document in documents
            if str(raw_document.get("id") or "") == normalized_document_id
        ),
        None,
    )
    if not document:
        raise ValueError(f"document_id not found: {normalized_document_id}")

    retrieval_query = (query or "").strip()
    if retrieval_query:
        retrieval_query = _validate_query(retrieval_query)
    else:
        retrieval_query = (
            f"Find the abstract, title, introduction, and key claims in "
            f"the document {_document_title(document)}."
        )
    document_hint = " ".join(
        part
        for part in [
            str(document.get("title") or ""),
            str(document.get("file_path") or ""),
        ]
        if part
    )
    retrieval_query_for_lightrag = (
        f"{retrieval_query}\n\nFocus on this document source: {document_hint}"
        if document_hint
        else retrieval_query
    )

    data_payload = {
        "query": retrieval_query_for_lightrag,
        "mode": "naive",
        "top_k": DEFAULT_TOP_K,
        "chunk_top_k": max(DEFAULT_CHUNK_TOP_K, capped_max_chunks * 2),
        "include_references": True,
        "include_chunk_content": True,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            payload = await _post_json(
                client,
                f"{base_url.rstrip('/')}/query/data",
                payload=data_payload,
                api_key=api_key,
            )
    except httpx.HTTPStatusError as exc:
        raise LightRAGQueryError(
            f"LightRAG document context fetch failed with HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise LightRAGQueryError("LightRAG query data service is unavailable") from exc

    data = payload.get("data") or {}
    document_path = str(document.get("file_path") or "")
    chunks: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    total_chars = 0

    for raw_chunk in data.get("chunks") or []:
        if not _same_document_path(raw_chunk.get("file_path"), document_path):
            continue
        content = _trim_content(
            raw_chunk.get("content"), MAX_TOTAL_CONTEXT_CHARS - total_chars
        )
        if not content:
            continue
        total_chars += len(content)
        chunk = {
            "chunk_id": raw_chunk.get("chunk_id"),
            "content": content,
            "source": {
                "document_id": normalized_document_id,
                "file_path": document.get("file_path"),
                "chunk_id": raw_chunk.get("chunk_id"),
                "reference_id": raw_chunk.get("reference_id"),
                "page": raw_chunk.get("page"),
            },
        }
        chunks.append(chunk)
        references.append(
            {
                **chunk["source"],
                "title": document.get("title"),
                "content": content,
            }
        )
        if len(chunks) >= capped_max_chunks or total_chars >= MAX_TOTAL_CONTEXT_CHARS:
            break

    return {
        "document": document,
        "query": retrieval_query,
        "chunks": chunks,
        "references": references,
        "citations": build_citations(references),
        "limits": {
            "max_chunks": capped_max_chunks,
            "max_chars_per_chunk": MAX_CHARS_PER_CHUNK,
            "max_total_chars": MAX_TOTAL_CONTEXT_CHARS,
        },
    }
