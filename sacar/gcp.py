import json
import time
from typing import Dict, Tuple

import httpx
import jwt

from . import settings, types

with open(settings.GCP_KEY_PATH, "r") as _f:
    GCP_KEY: types.GCPServiceAccountKey = json.loads(_f.read())


# Cache of auth tokens, mapping from token to key and expiry
AUTH_TOKENS: Dict[str, Tuple[str, int]] = {}


async def _request_auth_token(*, scope: str) -> Tuple[str, int]:
    iat = time.time()
    exp = iat + 3600
    payload = {
        "iss": GCP_KEY["client_id"],
        "scope": scope,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": iat,
        "exp": exp,
    }
    additional_headers = {"kid": GCP_KEY["private_key_id"]}
    token = jwt.encode(
        payload, GCP_KEY["private_key"], headers=additional_headers, algorithm="RS256"
    ).decode("ascii")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": token,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"Received invalid response from GCP: {data}")

    return (
        data["access_token"],
        time.time() + data["expires_in"],
    )


async def get_auth_token(*, scope: str) -> str:

    token, expires_at = AUTH_TOKENS.get(scope, (None, None))

    if token and expires_at and expires_at > time.time() + 30:
        return token

    token, expires_at = await _request_auth_token(scope=scope)
    AUTH_TOKENS[scope] = (token, expires_at)

    return token
