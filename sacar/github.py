import datetime
import hmac
import json
import logging
import time
from typing import Any, Awaitable, Dict, Optional, Tuple, Union

import httpx
import jwt

from . import settings, types, utils

logger = logging.getLogger("sacar")

###################
# Webhook helpers #
###################

# Encode the webhook secret key from settings to a bytes object
WEBHOOK_SECRET = str(settings.GITHUB_WEBHOOK_SECRET).encode("ascii")


def verify_webhook_signature(signature_header: str, body: bytes) -> bool:
    """
    Check a signature from github against what we calculate.
    """

    try:
        method, signature = signature_header.split("=", 2)
    except ValueError:
        return False

    return hmac.compare_digest(
        signature, hmac.new(WEBHOOK_SECRET, msg=body, digestmod=method).hexdigest(),
    )


#################
# Check run API #
#################


def create_or_update_queued_check_run(
    *,
    repo_url: str,
    installation_id: int,
    run_id: Optional[int] = None,
    payload: types.QueuedCheck,
) -> Awaitable[int]:
    """
    Create or update a check run to the queued status.
    """

    return _create_or_update_check_run(
        repo_url=repo_url,
        installation_id=installation_id,
        run_id=run_id,
        payload=payload,
    )


def create_or_update_in_progress_check_run(
    *,
    repo_url: str,
    installation_id: int,
    run_id: Optional[int],
    payload: types.InProgressCheck,
) -> Awaitable[int]:
    """
    Create or update a check run with the in-progress status.
    """

    return _create_or_update_check_run(
        repo_url=repo_url,
        installation_id=installation_id,
        run_id=run_id,
        payload=payload,
    )


def create_or_update_completed_check_run(
    *,
    repo_url: str,
    installation_id: int,
    run_id: Optional[int],
    payload: types.CompletedCheck,
) -> Awaitable[int]:
    """
    Create or update a check run with the completed status.
    """

    return _create_or_update_check_run(
        repo_url=repo_url,
        installation_id=installation_id,
        run_id=run_id,
        payload=payload,
    )


async def _create_or_update_check_run(
    *,
    repo_url: str,
    installation_id: int,
    run_id: Optional[int],
    payload: Union[types.QueuedCheck, types.InProgressCheck, types.CompletedCheck],
) -> int:
    """
    Create or update a run's status. Returns the ID of the run
    """

    if run_id is not None:
        url = f"{repo_url}/check-runs/{run_id}"
        method = "PATCH"
    else:
        url = f"{repo_url}/check-runs"
        method = "POST"

    # Set up authorization
    token = await _get_auth_token(installation_id=installation_id)
    headers = {
        "Accept": "application/vnd.github.antiope-preview+json",
        "Authorization": f"token {token}",
    }

    encoded_payload = JSON_ENCODER.encode(payload)

    logger.debug(f"Sending {encoded_payload} to github")

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=method, url=url, data=encoded_payload, headers=headers
        )
        response.raise_for_status()
        result = response.json()

    if run_id is None:
        assert isinstance(result, dict)
        run_id = result["id"]
        assert isinstance(run_id, int)

    return run_id


###################
# Deployments API #
###################


async def create_deployment_status(
    *,
    repo_url: str,
    deployment_id: int,
    installation_id: int,
    payload: types.DeploymentStatus,
) -> int:
    """
    Create a new deployment status
    """

    # Set correct accept header depending on deployment state
    if payload["state"] in (
        types.DeploymentState.IN_PROGRESS,
        types.DeploymentState.QUEUED,
    ):
        accept = "application/vnd.github.flash-preview+json"
    elif payload["state"] == types.DeploymentState.INACTIVE:
        accept = "application/vnd.github.ant-man-preview+json"
    else:
        accept = "application/json"

    # Set up authorization
    token = await _get_auth_token(installation_id=installation_id)
    headers = {
        "Accept": accept,
        "Authorization": f"token {token}",
    }

    encoded_payload = JSON_ENCODER.encode(payload)

    print(f"Sending {encoded_payload} to github")

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method="POST",
            url=f"{repo_url}/deploymments/{deployment_id}/statuses",
            data=encoded_payload,
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()

    assert isinstance(result, dict)
    deployment_status_id = result["id"]
    assert isinstance(deployment_status_id, int)

    return deployment_status_id


####################
# Internal helpers #
####################


def _to_json(o: Any) -> Any:
    """
    Convert some known types to JSON as GitHub wants them.
    """

    if isinstance(o, (types.CheckStatus, types.CheckConclusion, types.AnnotationLevel)):
        return o.value

    if isinstance(o, datetime.datetime):
        assert o.tzinfo == datetime.timezone.utc
        return o.strftime("%Y-%m-%dT%H:%M:%SZ")

    raise TypeError


# Create a JSON encoder that we can reuse
JSON_ENCODER = json.JSONEncoder(default=_to_json)

# Cache of auth tokens
AUTH_TOKENS: Dict[int, Tuple[str, datetime.datetime]] = {}


async def _request_auth_token(*, installation_id: int) -> Tuple[str, datetime.datetime]:
    """
    Request a new auth token from Github
    """

    # Generate an JWT token that we can use to fetch an installation token
    now = int(time.time())
    message = {"iss": settings.GITHUB_APP_ID, "iat": now, "exp": now + 5 * 60}
    with open(str(settings.GITHUB_KEY_PATH), "r") as key_file:
        private_key = key_file.read()
    bearer_token = jwt.encode(message, private_key, algorithm="RS256").decode("ascii")

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Accept": "application/vnd.github.machine-man-preview+json",
    }
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

    logger.debug("Requesting GitHub auth token for installation: %s", installation_id)

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"Received invalid response from GitHub: {data}")

    return (
        data["token"],
        datetime.datetime.strptime(data["expires_at"], "%Y-%m-%dT%H:%M:%S%z"),
    )


async def _get_auth_token(*, installation_id: int) -> str:
    """
    Get (or request a new) authentication token for the specified installation.
    """

    token, expiry = AUTH_TOKENS.get(installation_id, (None, None))

    # If we have a token and it's still valid for at least 30 seconds, return that
    if token and expiry and expiry > utils.now() + datetime.timedelta(seconds=30):
        return token

    # The old token was still invalid, so request a new one
    token, expiry = await _request_auth_token(installation_id=installation_id)
    AUTH_TOKENS[installation_id] = (token, expiry)

    return token
