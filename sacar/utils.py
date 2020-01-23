import asyncio
import os
import pathlib
import subprocess
from typing import Dict, Optional


async def run(
    *args: str,
    stdin: Optional[str] = None,
    cwd: Optional[pathlib.Path] = None,
    env: Optional[Dict[str, str]] = None
) -> str:
    """
    Start a subprocess, wait for it to exit, and return stdout if it returned
    successfully. If the subprocess did not return successfully an
    subprocess.CalledProcessError exception is raised.
    """

    process = await asyncio.create_subprocess_exec(
        args[0],
        *args[1:],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env or os.environ,
    )
    stdout, stderr = await process.communicate(stdin.encode("utf-8") if stdin else None)

    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode,
            cmd=args,
            output=stdout.decode("utf-8"),
            stderr=stderr.decode("utf-8"),
        )

    return stdout.decode("utf-8")


def create_lock_file(path: pathlib.Path, *, content: str) -> bool:
    """
    Atomically create a file with the given content.
    """

    try:
        with open(path, "x") as _f:
            _f.write(content)
        return True
    except FileExistsError:
        return False
