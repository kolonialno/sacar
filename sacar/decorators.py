import enum
import functools
import json
from typing import Any, Awaitable, Callable, Coroutine, Type, TypeVar, Union

import dacite  # type: ignore
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import github

T = TypeVar("T", bound=Response)
R = TypeVar("R")


def require_github_webhook_signature(
    func: Callable[[Request], Coroutine[Any, Any, T]]
) -> Callable[[Request], Coroutine[Any, Any, Union[Response, T]]]:
    """
    Verify that the request has a valid x-hub-signature header. If it does not
    immediatly return an "401 Forbidden" response.
    """

    @functools.wraps(func)
    async def wrapper(request: Request) -> Union[T, Response]:
        if not github.verify_webhook_signature(
            request.headers.get("x-github-signature", ""), await request.body()
        ):
            return Response(b"", status_code=401)

        return await func(request)

    return wrapper


def decode_payload(
    *, data_class: Type[R]
) -> Callable[
    [Callable[[R], Awaitable[Union[JSONResponse, T]]]],
    Callable[[Request], Awaitable[Union[JSONResponse, T]]],
]:
    def inner(
        func: Callable[[R], Awaitable[Union[JSONResponse, T]]]
    ) -> Callable[[Request], Awaitable[Union[JSONResponse, T]]]:
        @functools.wraps(inner)
        async def wrapper(request: Request) -> Union[T, JSONResponse]:

            try:
                data = await request.json()
            except json.JSONDecodeError as e:
                return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)

            try:
                return await func(
                    dacite.from_dict(
                        data_class=data_class,
                        data=data,
                        config=dacite.Config(cast=[enum.Enum]),
                    )
                )
            except dacite.DaciteError as e:
                return JSONResponse({"error": f"Invalid payload: {e}"}, status_code=400)

        return wrapper

    return inner
