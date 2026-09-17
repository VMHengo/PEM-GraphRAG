import pytest

from lightrag_mcp.config import MCPGatewayConfig


def test_mcp_config_accepts_bounded_directed_defaults_without_auth():
    config = MCPGatewayConfig(
        auth_required=False,
        retrieval_strategy="normal",
        directed_edge_direction="both",
        directed_hop_depth=2,
        directed_chain_top_k=20,
        directed_min_importance=0.45,
    )

    config.validate()


@pytest.mark.parametrize("direction", ["sideways", "", "upstream"])
def test_mcp_config_rejects_invalid_directed_default_direction(direction: str):
    config = MCPGatewayConfig(
        auth_required=False,
        directed_edge_direction=direction,
    )

    with pytest.raises(ValueError, match="MCP_DIRECTED_EDGE_DIRECTION"):
        config.validate()
