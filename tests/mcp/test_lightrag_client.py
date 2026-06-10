import pytest

from lightrag_mcp.lightrag_client import (
    DEFAULT_CHUNK_TOP_K,
    DEFAULT_TOP_K,
    MAX_DOCUMENT_SEARCH_LIMIT,
    MAX_FETCH_CHUNKS,
    _normalize_document,
    _query_terms,
    _score_document,
    _validate_limit,
    build_citations,
    map_lightrag_response,
    normalize_mode,
)


def test_normalize_mode_defaults_to_mix():
    assert normalize_mode(None) == "mix"


def test_normalize_mode_rejects_invalid_mode():
    with pytest.raises(ValueError):
        normalize_mode("delete")


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
                "chunk_id": "chunk-1",
                "reference_id": "1",
                "page": None,
            },
        }
    ]
