import asyncio

import pytest

from lightrag_mcp.lightrag_client import (
    DEFAULT_CHUNK_TOP_K,
    DEFAULT_TOP_K,
    MAX_DOCUMENT_SEARCH_LIMIT,
    MAX_FETCH_CHUNKS,
    _build_query_payload,
    _normalize_document,
    _query_terms,
    _score_document,
    _validate_limit,
    build_citations,
    map_lightrag_response,
    normalize_edge_direction,
    normalize_mode,
    normalize_retrieval_strategy,
    query_lightrag,
)


def test_normalize_mode_defaults_to_mix():
    assert normalize_mode(None) == "mix"


def test_normalize_mode_rejects_invalid_mode():
    with pytest.raises(ValueError):
        normalize_mode("delete")


def test_normalize_retrieval_strategy_defaults_to_normal_and_rejects_invalid():
    assert normalize_retrieval_strategy(None) == "normal"
    assert normalize_retrieval_strategy("AUTO") == "auto"
    with pytest.raises(ValueError):
        normalize_retrieval_strategy("replace")


def test_normalize_edge_direction_defaults_to_both_and_rejects_invalid():
    assert normalize_edge_direction(None) == "both"
    assert normalize_edge_direction("OUT") == "out"
    with pytest.raises(ValueError):
        normalize_edge_direction("sideways")


def test_query_payload_keeps_directed_controls_bounded_and_opted_in():
    payload, strategy, direction = _build_query_payload(
        question="Where can coating defects come from?",
        mode="mix",
        retrieval_strategy="combined",
        edge_direction="in",
        directed_hop_depth=2,
        directed_chain_top_k=12,
        directed_min_importance=0.7,
    )

    assert strategy == "combined"
    assert direction == "in"
    assert payload["retrieval_strategy"] == "combined"
    assert payload["edge_direction"] == "in"
    assert payload["hop_depth"] == 2
    assert payload["chain_top_k"] == 12
    assert payload["min_relation_importance"] == 0.7
    assert payload["include_retrieval_metadata"] is True


@pytest.mark.parametrize(
    ("hop_depth", "chain_top_k", "importance"),
    [(0, 20, 0.45), (4, 20, 0.45), (2, 0, 0.45), (2, 101, 0.45), (2, 20, 1.1)],
)
def test_query_payload_rejects_unbounded_directed_controls(
    hop_depth, chain_top_k, importance
):
    with pytest.raises(ValueError):
        _build_query_payload(
            question="Trace a chain",
            mode="mix",
            retrieval_strategy="combined",
            edge_direction="out",
            directed_hop_depth=hop_depth,
            directed_chain_top_k=chain_top_k,
            directed_min_importance=importance,
        )


def test_query_lightrag_sends_explicit_chain_direction(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": "Residual solvent can cause coating defects.",
                "references": [{"reference_id": "1", "file_path": "coating.pdf"}],
                "metadata": {
                    "retrieval_route": {"effective_strategy": "combined"},
                    "directed_paths": {"status": "completed", "path_count": 1},
                },
            }

    class FakeClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, json, headers):
            captured["url"] = url
            captured["payload"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("lightrag_mcp.lightrag_client.httpx.AsyncClient", FakeClient)

    result = asyncio.run(
        query_lightrag(
            base_url="http://lightrag:9621",
            question="Where can coating defects come from?",
            mode="mix",
            api_key="test-key",
            retrieval_strategy="combined",
            edge_direction="in",
            directed_hop_depth=2,
            directed_chain_top_k=12,
            directed_min_importance=0.7,
        )
    )

    assert captured["url"] == "http://lightrag:9621/query"
    assert captured["headers"] == {"X-API-Key": "test-key"}
    assert captured["payload"] == {
        "query": "Where can coating defects come from?",
        "mode": "mix",
        "top_k": DEFAULT_TOP_K,
        "chunk_top_k": DEFAULT_CHUNK_TOP_K,
        "include_references": True,
        "include_chunk_content": True,
        "stream": False,
        "response_type": "Multiple Paragraphs",
        "retrieval_strategy": "combined",
        "edge_direction": "in",
        "hop_depth": 2,
        "chain_top_k": 12,
        "min_relation_importance": 0.7,
        "include_retrieval_metadata": True,
    }
    assert result["retrieval"]["edge_direction"] == "in"
    assert result["retrieval_diagnostics"]["directed_paths"]["path_count"] == 1


def test_map_lightrag_response_returns_answer_references_and_mode():
    result = map_lightrag_response(
        {
            "response": "PEM electrolysis is connected to energy systems.",
            "references": [{"reference_id": "1", "file_path": "paper.pdf"}],
        },
        "mix",
    )

    assert result == {
        "answer": "PEM electrolysis is connected to energy systems.",
        "references": [{"reference_id": "1", "file_path": "paper.pdf"}],
        "citations": [
            {
                "label": "[1]",
                "title": "paper.pdf",
                "kind": "document",
                "url": None,
                "excerpt": "",
                "source": {
                    "document_id": None,
                    "file_path": "paper.pdf",
                    "source_url": None,
                    "download_url": None,
                    "chunk_id": None,
                    "reference_id": "1",
                    "page": None,
                },
            }
        ],
        "mode": "mix",
        "retrieval": {
            "top_k": DEFAULT_TOP_K,
            "chunk_top_k": DEFAULT_CHUNK_TOP_K,
            "include_chunk_content": True,
        },
    }


def test_map_lightrag_response_exposes_opt_in_retrieval_diagnostics():
    result = map_lightrag_response(
        {
            "response": "A causes B.",
            "metadata": {
                "retrieval_route": {"effective_strategy": "combined"},
                "directed_paths": {"status": "completed", "path_count": 1},
                "ignored": "not exposed",
            },
        },
        "mix",
    )

    assert result["retrieval_diagnostics"] == {
        "retrieval_route": {"effective_strategy": "combined"},
        "directed_paths": {"status": "completed", "path_count": 1},
    }


def test_normalize_document_maps_light_rag_status_and_title():
    result = _normalize_document(
        {
            "id": "doc-123",
            "file_path": "/inputs/Cross-Domain Insights.pdf",
            "status": "DocStatus.PROCESSED",
            "content_summary": "CNN and VVP methods are compared.",
            "chunks_count": 3,
        }
    )

    assert result["document_id"] == "doc-123"
    assert result["title"] == "Cross-Domain Insights.pdf"
    assert result["status"] == "processed"
    assert result["chunks_count"] == 3


def test_score_document_prioritizes_title_and_path_matches():
    document = _normalize_document(
        {
            "id": "doc-123",
            "file_path": "/inputs/Cross-Domain Insights.pdf",
            "status": "PROCESSED",
            "content_summary": "A document about machine learning.",
        }
    )

    score = _score_document(document, _query_terms("Cross Domain"))

    assert score > 0


def test_validate_limit_caps_document_and_chunk_limits():
    assert _validate_limit(999, maximum=MAX_DOCUMENT_SEARCH_LIMIT, name="limit") == 20
    assert _validate_limit(999, maximum=MAX_FETCH_CHUNKS, name="max_chunks") == 10


def test_validate_limit_rejects_zero():
    with pytest.raises(ValueError):
        _validate_limit(0, maximum=MAX_FETCH_CHUNKS, name="max_chunks")


def test_build_citations_includes_title_excerpt_and_source_metadata():
    citations = build_citations(
        [
            {
                "document_id": "doc-123",
                "title": "Cross-Domain Insights",
                "file_path": "Cross-Domain Insights.pdf",
                "chunk_id": "chunk-1",
                "reference_id": "1",
                "content": "CNNs are compared with the ventral visual pathway.",
            }
        ]
    )

    assert citations == [
        {
            "label": "[1]",
            "title": "Cross-Domain Insights",
            "kind": "document_chunk",
            "url": None,
            "excerpt": "CNNs are compared with the ventral visual pathway.",
            "source": {
                "document_id": "doc-123",
                "file_path": "Cross-Domain Insights.pdf",
                "source_url": None,
                "download_url": None,
                "chunk_id": "chunk-1",
                "reference_id": "1",
                "page": None,
            },
        }
    ]
