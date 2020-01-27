import argparse
import asyncio
import logging
import signal
from typing import List

import sentry_sdk
from hypercorn.asyncio import serve
from hypercorn.config import Config

from . import server, settings

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sacar")


async def _main(*, bind: List[str], master: bool) -> None:
    """
    Run the server
    """

    loop = asyncio.get_running_loop()
    shutdown = asyncio.Event()

    def signal_handler() -> None:
        """Signal handler that schedules a shutdown"""

        shutdown.set()

    # Register a signal handler for the SIGINT (ctrl+c) signal
    loop.add_signal_handler(signal.SIGINT, signal_handler)

    config = Config()
    config.bind = bind

    await serve(server.get_app(master=master), config, shutdown_trigger=shutdown.wait)  # type: ignore


def main() -> None:

    sentry_sdk.init(dsn=settings.SENTRY_DSN)

    parser = argparse.ArgumentParser()

    parser.add_argument("--bind", action="append", required=True)

    subparsers = parser.add_subparsers(required=True, dest="mode")

    _ = subparsers.add_parser("master")
    _ = subparsers.add_parser("slave")

    args = parser.parse_args()

    asyncio.run(_main(bind=args.bind, master=args.mode == "master"))
