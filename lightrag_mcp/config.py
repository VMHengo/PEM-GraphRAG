from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MCPGatewayConfig:
    lightrag_base_url: str = os.getenv("LIGHTRAG_BASE_URL", "http://lightrag:9621")
    lightrag_api_key: str | None = os.getenv("LIGHTRAG_API_KEY") or None
    lightrag_timeout: float = float(os.getenv("LIGHTRAG_MCP_TIMEOUT", "120"))

    auth_required: bool = _env_bool("MCP_AUTH_REQUIRED", True)
    auth0_domain: str | None = os.getenv("AUTH0_DOMAIN") or None
    auth0_audience: str | None = os.getenv("AUTH0_AUDIENCE") or None
    auth0_algorithms: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("AUTH0_ALGORITHMS", "RS256").split(",")
        if item.strip()
    )

    def validate(self) -> None:
        if not self.lightrag_base_url:
            raise ValueError("LIGHTRAG_BASE_URL must not be empty")
        if self.auth_required:
            missing = [
                name
                for name, value in {
                    "AUTH0_DOMAIN": self.auth0_domain,
                    "AUTH0_AUDIENCE": self.auth0_audience,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    "Missing required MCP auth environment variables: "
                    + ", ".join(missing)
                )


def get_config() -> MCPGatewayConfig:
    config = MCPGatewayConfig()
    config.validate()
    return config

