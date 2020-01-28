import hmac
import json
from typing import Any

import pytest
from starlette.testclient import TestClient

from sacar import settings


def test_status_endpoint(master_client: TestClient) -> None:
    response = master_client.get("/status")
    assert response.status_code == 200


def test_webhook_auth_missing(master_client: TestClient) -> None:
    response = master_client.post("/github-webhook")
    assert response.status_code == 401


def test_webhook_auth_invalid(master_client: TestClient) -> None:
    response = master_client.post(
        "/github-webhook", headers={"x-hub-signature": "blabla"}
    )
    assert response.status_code == 401


def test_webhook_auth_valid(master_client: TestClient) -> None:

    signature = hmac.new(
        str(settings.GITHUB_WEBHOOK_SECRET).encode("ascii"), msg=b"", digestmod="SHA1",
    ).hexdigest()

    response = master_client.post(
        "/github-webhook",
        data=b"",
        headers={"x-hub-signature": f"sha1={signature}", "x-github-event": "push"},
    )
    assert response.status_code == 200


@pytest.mark.skip("Broken")  # type: ignore
def test_webhook_check_suite_requested(
    master_client: TestClient, mocker: Any, awaitable_mock: Any
) -> None:

    mocked_check_run = mocker.patch(
        "sacar.github._create_or_update_check_run", new=awaitable_mock()
    )

    data = json.dumps(
        {
            "action": "requested",
            "check_suite": {"head_branch": "master", "head_sha": "commithash"},
            "repository": {
                "full_name": "my/repo",
                "url": "https://api.github.com/repo/my/repo",
            },
            "installation": {"id": 1},
        }
    ).encode()

    signature = hmac.new(
        str(settings.GITHUB_WEBHOOK_SECRET).encode("ascii"), msg=data, digestmod="SHA1",
    ).hexdigest()

    response = master_client.post(
        "/github-webhook",
        data=data,
        headers={
            "x-hub-signature": f"sha1={signature}",
            "x-github-event": "check_suite",
        },
    )
    assert response.status_code == 200

    mocked_check_run.asseret_called_once()
