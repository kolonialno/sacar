from hypercorn.typing import ASGIFramework
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from . import handlers, settings
from .decorators import require_github_webhook_signature


@require_github_webhook_signature
async def github_webhook(request: Request) -> Response:
    """
    Endpoint for incomming webhooks from GitHub.
    """

    event = request.headers.get("x-github-event", None)
    if event == "check_suite":
        return await handlers.check_suite_event(request)
    if event == "deployment":
        return await handlers.deployment_event(request)
    return Response(b"")


# TODO: Verify request
async def tarball_ready(request: Request) -> Response:
    return await handlers.tarball_ready_event(request)


# TODO: Verify request
async def prepare_host(request: Request) -> Response:
    return await handlers.prepare_host(request)


# TODO: Verify request
async def deploy_host(request: Request) -> Response:
    return await handlers.deploy_host(request)


async def status(request: Request) -> Response:
    return Response(b"")


async def error(request: Request) -> Response:
    raise RuntimeError("Testing exception")


def get_app(*, master: bool, sentry: bool = True) -> ASGIFramework:
    asgi_app = Starlette(
        debug=True,
        routes=(
            [
                Route("/github-webhook", github_webhook, methods=["POST"]),
                Route("/tarball-ready", tarball_ready, methods=["POST"]),
                Route("/status", status, methods=["GET"]),
                Route("/error", error, methods=["GET"]),
            ]
            if master
            else [
                Route("/prepare-host", prepare_host, methods=["PUT"]),
                Route("/deploy-host", deploy_host, methods=["PUT"]),
                Route("/status", status, methods=["GET"]),
            ]
        ),
    )

    if sentry and not settings.SENTRY_DSN:
        raise RuntimeError(
            "Cannot enable Sentry integration without SACAR_SENTRY_DSN being set"
        )

    return SentryAsgiMiddleware(asgi_app) if sentry else asgi_app
