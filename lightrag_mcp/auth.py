from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anyio
import jwt
from jwt import PyJWKClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lightrag_mcp.config import MCPGatewayConfig


class AuthError(Exception):
    """Authentication or authorization failure for the MCP gateway."""


@dataclass
class Auth0JWTValidator:
    domain: str
    audience: str
    algorithms: tuple[str, ...] = ("RS256",)

    def __post_init__(self) -> None:
        issuer = self.domain.strip()
        if not issuer.startswith(("http://", "https://")):
            issuer = f"https://{issuer}"
        self.issuer = issuer.rstrip("/") + "/"
        self._jwks_client = PyJWKClient(f"{self.issuer}.well-known/jwks.json")

    def validate(self, token: str) -> dict[str, Any]:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
            )
        except Exception as exc:  # noqa: BLE001 - collapse JWT details for clients
            raise AuthError("Invalid bearer token") from exc


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: MCPGatewayConfig):
        super().__init__(app)
        self.config = config
        self.validator = (
            Auth0JWTValidator(
                domain=config.auth0_domain or "",
                audience=config.auth0_audience or "",
                algorithms=config.auth0_algorithms,
            )
            if config.auth_required
            else None
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/healthz" or not self.config.auth_required:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                {"error": "Missing bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            claims = await anyio.to_thread.run_sync(self.validator.validate, token)
        except AuthError:
            return JSONResponse(
                {"error": "Invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        request.state.auth_claims = claims
        return await call_next(request)

