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
    assert param.chain_top_k_per_prompt == 2
    assert param.min_relation_importance == 0.45
    assert param.path_ranking_mode == "mean"
    assert param.allow_evidence_predicates is False
    assert request.include_retrieval_metadata is False


@pytest.mark.offline
def test_query_request_can_opt_in_to_retrieval_metadata():
    request = QueryRequest(
        query="What causes electrode defects?", include_retrieval_metadata=True
    )

    assert request.include_retrieval_metadata is True
    assert request.to_query_params(is_stream=False).retrieval_strategy == "normal"


@pytest.mark.offline
def test_query_request_maps_multihop_configuration_to_query_param():
    request = QueryRequest(
        query="Where can insufficient electrode thickness come from?",
        retrieval_strategy="combined",
        edge_direction="in",
        hop_depth=3,
        chain_top_k=12,
        chain_fanout=8,
        chain_top_k_per_prompt=4,
        min_relation_importance=0.7,
        path_ranking_mode="weakest_link",
        allow_evidence_predicates=True,
    )

    param = request.to_query_params(is_stream=False)

    assert param.retrieval_strategy == "combined"
    assert param.edge_direction == "in"
    assert param.hop_depth == 3
    assert param.chain_top_k == 12
    assert param.chain_fanout == 8
    assert param.chain_top_k_per_prompt == 4
    assert param.min_relation_importance == 0.7
    assert param.path_ranking_mode == "weakest_link"
    assert param.allow_evidence_predicates is True


@pytest.mark.offline
def test_query_request_accepts_bounded_five_hop_paths():
    request = QueryRequest(query="Trace a five-step failure chain", hop_depth=5)
    assert request.to_query_params(is_stream=False).hop_depth == 5


@pytest.mark.offline
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("retrieval_strategy", "unsupported"),
        ("edge_direction", "sideways"),
        ("hop_depth", 6),
        ("chain_top_k", 0),
        ("chain_fanout", 51),
        ("chain_top_k_per_prompt", 11),
        ("min_relation_importance", 1.1),
        ("path_ranking_mode", "random"),
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
        ("chain_top_k_per_prompt", 0),
        ("min_relation_importance", -0.1),
        ("path_ranking_mode", "random"),
        ("allow_evidence_predicates", "yes"),
    ],
)
def test_query_param_rejects_invalid_multihop_configuration(
    field_name: str, invalid_value: object
):
    with pytest.raises(ValueError):
        QueryParam(**{field_name: invalid_value})
