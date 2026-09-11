import sys
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from lightrag.base import QueryParam

with patch.object(sys, "argv", [sys.argv[0]]):
    from lightrag.api.routers.query_routes import QueryRequest


@pytest.mark.offline
def test_query_request_defaults_preserve_normal_retrieval():
    request = QueryRequest(query="What causes electrode defects?")

    param = request.to_query_params(is_stream=False)

    assert param.mode == "mix"
    assert param.retrieval_strategy == "normal"
    assert param.edge_direction == "both"
    assert param.hop_depth == 2
    assert param.chain_top_k == 20
    assert param.chain_fanout == 20
    assert param.min_relation_importance == 0.45


@pytest.mark.offline
def test_query_request_maps_multihop_configuration_to_query_param():
    request = QueryRequest(
        query="Where can insufficient electrode thickness come from?",
        retrieval_strategy="combined",
        edge_direction="in",
        hop_depth=3,
        chain_top_k=12,
        chain_fanout=8,
        min_relation_importance=0.7,
    )

    param = request.to_query_params(is_stream=False)

    assert param.retrieval_strategy == "combined"
    assert param.edge_direction == "in"
    assert param.hop_depth == 3
    assert param.chain_top_k == 12
    assert param.chain_fanout == 8
    assert param.min_relation_importance == 0.7


@pytest.mark.offline
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("retrieval_strategy", "unsupported"),
        ("edge_direction", "sideways"),
        ("hop_depth", 4),
        ("chain_top_k", 0),
        ("chain_fanout", 51),
        ("min_relation_importance", 1.1),
    ],
)
def test_query_request_rejects_invalid_multihop_configuration(
    field_name: str, invalid_value: object
):
    with pytest.raises(ValidationError):
        QueryRequest(query="What causes electrode defects?", **{field_name: invalid_value})


@pytest.mark.offline
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("retrieval_strategy", "unsupported"),
        ("edge_direction", "sideways"),
        ("hop_depth", 0),
        ("chain_top_k", 101),
        ("chain_fanout", 0),
        ("min_relation_importance", -0.1),
    ],
)
def test_query_param_rejects_invalid_multihop_configuration(
    field_name: str, invalid_value: object
):
    with pytest.raises(ValueError):
        QueryParam(**{field_name: invalid_value})
