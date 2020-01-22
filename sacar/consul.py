import base64
import dataclasses
import json
from types import TracebackType
from typing import Any, AsyncIterable, Dict, List, Optional, Tuple, Type, TypeVar

import dacite  # type: ignore
import httpx

from . import settings

E = TypeVar("E", bound=BaseException)
T = TypeVar("T")


class Client:
    """
    A simple wrapper around the Consul HTTP API.
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self.client = client or httpx.AsyncClient()

    ###################
    # Context manager #
    ###################

    async def __aenter__(self) -> "Client":
        await self.client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[E]],
        exc: Optional[E],
        traceback: Optional[TracebackType],
    ) -> None:
        await self.client.__aexit__(exc_type, exc, traceback)  # type: ignore

    ##############
    # Public API #
    ##############

    async def get_service_nodes(
        self, *, service_name: str, tag: str
    ) -> List[Tuple[str, int]]:
        """
        Get the address and port for all registered node for a service.
        """

        resp = await self.client.get(
            f"http://{settings.CONSUL_HOST}/v1/catalog/service/{service_name}",
            params={"tag": tag},
            headers={"X-Consul-Token": str(settings.CONSUL_HTTP_TOKEN)},
        )
        resp.raise_for_status()
        services = resp.json()

        if not isinstance(services, list):
            raise RuntimeError(f"Expected dict, got {type(services)}")

        return [
            (service["ServiceAddress"] or service["Address"], service["ServicePort"])
            for service in services
        ]

    async def put(self, *, key: str, value: Any) -> None:
        """
        Save a value to the given key
        """

        if dataclasses.is_dataclass(value):
            value = dataclasses.asdict(value)
        await self.client.put(
            f"http://{settings.CONSUL_HOST}/v1/kv/{settings.CONSUL_KEY_PREFIX}/{key}",
            json=value,
            headers={"X-Consul-Token": str(settings.CONSUL_HTTP_TOKEN)},
        )

    async def get(
        self, key: str, *, cls: Type[T], wait: int = 0, index: int = 0,
    ) -> Tuple[int, T]:
        """
        Get a single entry
        """

        headers, entries = await self._get(
            key=key, params=self._params(wait=wait, index=index), timeout=wait + 10
        )

        return (
            int(headers["X-Consul-Index"]),
            self._decode(entry=entries[0], cls=cls),
        )

    async def get_recursive(
        self, key: str, *, cls: Type[T], wait: int = 0, index: int = 0,
    ) -> Tuple[int, List[T]]:
        """
        Get entries, recursively
        """

        headers, entries = await self._get(
            key=key,
            params=self._params(wait=wait, index=index, recurse=True),
            timeout=wait + 10,
        )

        return (
            int(headers["X-Consul-Index"]),
            [self._decode(entry=entry, cls=cls) for entry in entries],
        )

    async def wait(self, *, key: str, cls: Type[T], wait: int = 10) -> AsyncIterable[T]:
        """
        Watch for changes
        """

        index = 1
        while True:
            try:
                index, value = await self.get(key=key, cls=cls, index=index, wait=wait)
                yield value
            except httpx.HTTPError as e:
                if e.response.status_code == 404:
                    index = int(e.response.headers["X-Consul-Index"])
                    continue
                raise

    async def wait_recursive(
        self, *, key: str, cls: Type[T], wait: int = 10
    ) -> AsyncIterable[List[T]]:
        """
        Watch for changes recursively
        """

        index = 1
        while True:
            try:
                index, values = await self.get_recursive(
                    key=key, cls=cls, index=index, wait=wait
                )
                yield values
            except httpx.HTTPError as e:
                if e.response.status_code == 404:
                    index = int(e.response.headers["X-Consul-Index"])
                    continue
                raise

    ####################
    # Internal helpers #
    ####################

    async def _get(
        self, *, key: str, params: Dict[str, str], timeout: Optional[int] = None
    ) -> Tuple[httpx.Headers, Any]:
        resp = await self.client.get(
            f"http://{settings.CONSUL_HOST}/v1/kv/{settings.CONSUL_KEY_PREFIX}/{key}",
            params=params,
            timeout=timeout,
            headers={"X-Consul-Token": str(settings.CONSUL_HTTP_TOKEN)},
        )
        resp.raise_for_status()
        data = resp.json()

        return resp.headers, data

    def _decode(self, *, entry: Dict[str, str], cls: Type[T]) -> T:
        return dacite.from_dict(  # type: ignore
            data_class=cls, data=json.loads(base64.b64decode(entry["Value"]))
        )

    def _params(
        self,
        *,
        recurse: Optional[bool] = None,
        wait: Optional[int] = None,
        index: Optional[int] = None,
    ) -> Dict[str, str]:

        params = {}
        if index:
            params["index"] = str(index)
        if wait:
            params["wait"] = f"{wait}s"
        if recurse:
            params["recurse"] = "True"
        return params
