from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from . import handlers
from .decorators import require_github_webhook_signature


@require_github_webhook_signature
async def github_webhook(request: Request) -> Response:
    """
    Endpoint for incomming webhooks from GitHub.
    """

    event = request.headers.get("x-github-event", None)
    if event == "check_suite":
        return await handlers.check_suite_event(request)
    return Response(b"")


# TODO: Verify request
async def tarball_ready(request: Request) -> Response:
    return await handlers.tarball_ready_event(request)


# TODO: Verify request
async def prepare_host(request: Request) -> Response:
    return await handlers.prepare_host(request)


async def status(request: Request) -> Response:
    return Response(b"")


def get_app(*, master: bool) -> Starlette:
    return Starlette(
        debug=True,
        routes=(
            [
                Route("/github-webhook", github_webhook, methods=["POST"]),
                Route("/tarball-ready", tarball_ready, methods=["POST"]),
                Route("/status", status, methods=["GET"]),
            ]
            if master
            else [
                Route("/prepare-host", prepare_host, methods=["PUT"]),
                Route("/status", status, methods=["GET"]),
            ]
        ),
    )
