"""Resolve a human reviewer's identity from the OAuth2 Proxy session."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, Request


FRIENDLY_NAMES = {
    "m.konersmann@pem.rwth-aachen.de": "Matthias",
    "hoang.nguyen@rwth-aachen.de": "Hoang",
    "christoph.siebuerger@rwth-aachen.de": "Christoph",
    "nils.wolf@rwth-aachen.de": "Nils",
}


@dataclass(frozen=True)
class ReviewerIdentity:
    email: str
    default_name: str


async def resolve_reviewer_identity(request: Request) -> ReviewerIdentity:
    cookie = request.headers.get("cookie")
    if not cookie:
        raise HTTPException(
            status_code=401, detail="OAuth login is required for reviews"
        )

    proxy_url = os.getenv("REVIEW_OAUTH2_PROXY_URL", "http://oauth2-proxy:4180")
    try:
        async with httpx.AsyncClient(
            timeout=5, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.get(
                f"{proxy_url.rstrip('/')}/oauth2/userinfo",
                headers={"Cookie": cookie},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail="Reviewer identity is unavailable"
        ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=401, detail="OAuth login is required for reviews"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=503, detail="Reviewer identity is unavailable"
        ) from exc
    email = str(data.get("email") or "").strip().casefold()
    if not email or "@" not in email or len(email) > 254:
        raise HTTPException(
            status_code=403, detail="OAuth account has no email address"
        )
    return ReviewerIdentity(email=email, default_name=FRIENDLY_NAMES.get(email, email))
