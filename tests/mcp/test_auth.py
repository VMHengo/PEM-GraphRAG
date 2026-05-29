import pytest
from jwt import PyJWKClient

from lightrag_mcp.auth import Auth0JWTValidator, AuthError


def test_auth0_validator_normalizes_domain_to_issuer():
    validator = Auth0JWTValidator(
        domain="example.eu.auth0.com",
        audience="https://mcp.example.edu",
    )

    assert validator.issuer == "https://example.eu.auth0.com/"


def test_auth0_validator_wraps_jwt_errors(monkeypatch):
    def fail_get_key(self, token):
        raise RuntimeError("bad token")

    monkeypatch.setattr(PyJWKClient, "get_signing_key_from_jwt", fail_get_key)
    validator = Auth0JWTValidator(
        domain="example.eu.auth0.com",
        audience="https://mcp.example.edu",
    )

    with pytest.raises(AuthError):
        validator.validate("not-a-token")
