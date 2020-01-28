import pytest  # type: ignore
from starlette.testclient import TestClient

from sacar.server import get_app


@pytest.fixture  # type: ignore
def master_client() -> TestClient:
    return TestClient(get_app(master=True, sentry=False))  # type: ignore


@pytest.fixture
def awaitable_mock(mocker):  # type: ignore
    """
    Simple fixtures that provides a coroutine mock factory.
    """

    async def coro(*args, **kwargs):  # type: ignore
        pass

    def _coro_mock():  # type: ignore
        return mocker.Mock(wraps=coro)

    return _coro_mock
