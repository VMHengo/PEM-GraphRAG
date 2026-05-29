import pytest

from lightrag_mcp.lightrag_client import (
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
        "mode": "mix",
    }

