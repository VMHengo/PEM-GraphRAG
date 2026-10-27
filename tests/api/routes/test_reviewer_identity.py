"""Review authorship must come from the OAuth session, not request fields."""

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import lightrag.evaluation.reviewer_identity as reviewer_identity


@pytest.mark.parametrize(
    ("email", "name"),
    [
        ("m.konersmann@pem.rwth-aachen.de", "Matthias"),
        ("hoang.nguyen@rwth-aachen.de", "Hoang"),
        ("christoph.siebuerger@rwth-aachen.de", "Christoph"),
        ("nils.wolf@rwth-aachen.de", "Nils"),
    ],
)
def test_friendly_names(email, name):
    assert reviewer_identity.FRIENDLY_NAMES[email] == name


def test_verified_cookie_sets_friendly_name_and_ignores_forwarded_email(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"email": "Hoang.Nguyen@RWTH-Aachen.de"})

    transport = httpx.MockTransport(respond)
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        reviewer_identity.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=transport, **kwargs),
    )

    app = FastAPI()

    @app.get("/identity")
    async def identity(value=Depends(reviewer_identity.resolve_reviewer_identity)):
        return {"email": value.email, "name": value.default_name}

    with TestClient(app) as client:
        assert (
            client.get(
                "/identity", headers={"X-Forwarded-Email": "fake@example.org"}
            ).status_code
            == 401
        )
        response = client.get(
            "/identity",
            headers={
                "Cookie": "_oauth2_proxy=mock-session",
                "X-Forwarded-Email": "fake@example.org",
            },
        )
    assert response.json() == {"email": "hoang.nguyen@rwth-aachen.de", "name": "Hoang"}
    assert len(requests) == 1
    assert requests[0].headers["cookie"] == "_oauth2_proxy=mock-session"
    assert "X-Forwarded-Email" not in requests[0].headers


def test_missing_email_is_rejected(monkeypatch):
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"user": "Hoang"})
    )
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        reviewer_identity.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=transport, **kwargs),
    )
    app = FastAPI()

    @app.get("/identity")
    async def identity(value=Depends(reviewer_identity.resolve_reviewer_identity)):
        return value.email

    with TestClient(app) as client:
        assert (
            client.get(
                "/identity", headers={"Cookie": "_oauth2_proxy=mock"}
            ).status_code
            == 403
        )
