import asyncio
import dataclasses
import datetime
import logging
import os
import pathlib
import subprocess
import tempfile
from typing import Optional, Tuple

import httpx

from . import consul, gcp, github, settings, types, utils

logger = logging.getLogger("sacar")

################
# Master tasks #
################


async def prepare_hosts(
    *, payload: types.TarballReadyEvent, state: types.VersionState
) -> int:
    """
    Prepare all hosts
    """

    async with httpx.AsyncClient() as client:

        consul_client = consul.Client(client=client)

        # Find all slaves, through Consul services
        slaves = await consul_client.get_service_nodes(
            service_name="sacar", tag="slave"
        )

        async def _notify_slave(*, host: str, port: int) -> None:
            """Helper to notify a slave to start preparing a version"""

            logger.debug(f"Notifying {host}:{port}")

            resp = await client.put(
                f"http://{host}:{port}/prepare-host", json=dataclasses.asdict(payload)
            )
            resp.raise_for_status()

        # Notify all slaves concurrently
        await asyncio.gather(
            *[_notify_slave(host=host, port=port) for host, port in slaves],
        )

        # Update state and store in Consul
        state.status = "preparing"
        await consul_client.put(
            key=f"{payload.repo_name}/{payload.sha}", value=state,
        )

    return len(slaves)


async def wait_for_hosts(
    *,
    payload: types.TarballReadyEvent,
    num_slaves: int,
    check_run_id: int,
    installation_id: int,
    started_at: datetime.datetime,
    timeout: int = 5 * 60,
) -> None:
    """
    Wait for all slaves to finish, up to a configurable timeout.
    """

    timed_out = False
    num_ready = 0

    async with consul.Client() as client:
        async for slave_states in client.wait_recursive(
            key=f"{payload.repo_name}/{payload.sha}/", cls=types.SlaveVersionState
        ):
            # Count how many nodes have set their status to success
            num_ready = sum(1 for slave_state in slave_states if slave_state.done)

            await github.create_or_update_in_progress_check_run(
                repo_url=f"https://api.github.com/repos/{payload.repo_name}",
                run_id=check_run_id,
                installation_id=installation_id,
                payload={
                    "name": settings.GITHUB_CHECK_RUN_NAME,
                    "head_sha": payload.sha,
                    "status": types.CheckStatus.IN_PROGRESS,
                    "external_id": "",
                    "started_at": started_at,
                    "output": {
                        "title": settings.GITHUB_CHECK_RUN_NAME,
                        "summary": f"Preparing hosts ({num_ready} of {num_slaves} ready)",
                    },
                },
            )

            if num_ready >= num_slaves:
                break

            if datetime.datetime.now() - started_at > datetime.timedelta(
                seconds=timeout
            ):
                timed_out = True
                break

    # If we're not on the master branch, don't prepare
    await github.create_or_update_completed_check_run(
        repo_url=f"https://api.github.com/repos/{payload.repo_name}",
        run_id=check_run_id,
        installation_id=installation_id,
        payload={
            "name": settings.GITHUB_CHECK_RUN_NAME,
            "head_sha": payload.sha,
            "status": types.CheckStatus.COMPLETED,
            "external_id": "",
            "completed_at": datetime.datetime.now(),
            "conclusion": (
                types.CheckConclusion.FAILURE
                if timed_out
                else types.CheckConclusion.SUCCESS
            ),
            "output": {
                "title": settings.GITHUB_CHECK_RUN_NAME,
                "summary": (
                    "Timed out while preparing hosts"
                    if timed_out
                    else "All hosts ready"
                ),
                "text": (
                    f"Timed out after {timeout} seconds, "
                    f"{num_ready} of {num_slaves} hosts ready"
                    if timed_out
                    else "Finished preparing all {num_slaves} hosts"
                ),
            },
            # TODO: Add deploy action?
        },
    )


async def deploy(
    *, repo_url: str, repo_name: str, commit_sha: str, deployment_id: int
) -> Tuple[bool, str]:
    """
    Deploy a version. This verifies that the version is prepared and then calls
    the deploy script from the tarball.
    """

    logger.debug("Deploying %s", commit_sha)

    # Update state with the deployment id
    async with consul.Client() as client:
        _, state = await client.get(f"{repo_name}/{commit_sha}", cls=types.VersionState)
        state.deployment_id = deployment_id
        await client.put(key=f"{repo_name}/{commit_sha}", value=state)

    target_path = settings.VERSIONS_DIRECTORY / commit_sha

    if not target_path.exists():
        return False, "Version does not exist"

    if not (target_path / "prepare.done").exists():
        return False, "Version is not prepared"

    if not await _run_script(
        name="deploy", target_path=target_path, commit_sha=commit_sha
    ):
        return False, "Failed to run deploy script"

    return True, "Finished deploy"


###############
# Slave tasks #
###############


async def prepare_host(*, payload: types.TarballReadyEvent) -> None:
    """
    Download a tarball and prepare it for deployment.
    """

    logger.debug("Preparing host: %s", payload)

    async with consul.Client() as client:
        await client.put(
            key=f"{payload.repo_name}/{payload.sha}/{settings.HOSTNAME}",
            value=types.SlaveVersionState(done=False),
        )

    try:
        success, message = await _prepare(
            tarball_path=payload.tarball_path,
            target_path=settings.VERSIONS_DIRECTORY / payload.sha,
            commit_sha=payload.sha,
        )
        logger.exception("Finished preparing host")
    except Exception as e:
        logger.exception("Failed to prepare host")
        success = False
        message = str(e)

    async with consul.Client() as client:
        await client.put(
            key=f"{payload.repo_name}/{payload.sha}/{settings.HOSTNAME}",
            value=types.SlaveVersionState(done=True, success=success, message=message),
        )


async def _prepare(
    *, tarball_path: str, target_path: pathlib.Path, commit_sha: str
) -> Tuple[bool, str]:
    """
    Prepare a version for running. Once this command has succeeded, the version
    is ready for running.
    """

    # Create the target path if it does not exist
    target_path.mkdir(parents=True, exist_ok=True)
    logger.debug("Created dir")

    # Create a lock file to ensure that we don't concurrently attempt to prepare
    # the same version.
    if not utils.create_lock_file(
        target_path / "prepare.pid", content=str(os.getpid())
    ):
        logger.debug("Failed to create lock file")
        return False, f'Someone is already preparing "{str(target_path)}"'

    logger.debug("Created lock file")

    # If the path is already prepared, clear the lock file and return
    if (target_path / "prepare.done").exists():
        (target_path / "prepare.pid").unlink()
        logger.debug("Already perpared")
        return True, f'"{str(target_path)}" is already prepared'

    with tempfile.NamedTemporaryFile() as tar_file:
        if not await _download_tarball(
            path=tarball_path, to=pathlib.Path(tar_file.name)
        ):
            # Unlock so we can try again. We have not touched the directory so
            # this should not cause any problems later.
            (target_path / "prepare.pid").unlink()
            logger.debug("Faiiled to download")
            return False, "Failed to download tar"

        logger.debug("Downloaded tar")

        if not await _extract_tar(
            tar_path=pathlib.Path(tar_file.name), target_path=target_path
        ):
            logger.debug("Failed to extract")
            return False, "Failed to extract tar"

        logger.debug("Extracted")

    if not (target_path / "python-version").exists():
        logger.debug("Missing python-versrion")
        return False, "Missing python-version from tarball"

    logger.debug("Finding python")

    python = _get_python_path(target_path=target_path)
    if not python:
        logger.debug("Unable to find correct python version")
        return False, "Unsupported python version"

    logger.debug("Found python")

    if not await _create_venv(target_path=target_path, python=python):
        logger.debug("Failed to create venv")
        return False, "Failed to create venv"

    logger.debug("Created venv")

    if not await _install_dependencies(target_path=target_path):
        logger.debug("Failed to install deps")
        return False, "Failed to install dependencies"

    logger.debug("Installed deps")

    if (target_path / "bin" / "prepare").exists():
        if not await _run_script(
            name="prepare", target_path=target_path, commit_sha=commit_sha
        ):
            logger.debug("Failed to run prepare script")
            return False, "Failed to run bootstrap script"

    logger.debug("Prepared")

    # Create the prepare.done file, to indicate that this version is ready to
    # be deployed.
    with open(target_path / "prepare.done", "w") as _:
        pass

    logger.debug("Done")

    # Remove the lockfile
    (target_path / "prepare.pid").unlink()

    return True, "Prepared and ready for deployment"


async def _download_tarball(*, path: str, to: pathlib.Path) -> bool:
    """
    Download the tarball from the given URL to the given path.
    """

    try:
        url = (
            "https://storage.googleapis.com/storage/v1/b/"
            f"{settings.GCP_BUCKET}/o/{path}?alt=media"
        )
        token = await gcp.get_auth_token(
            scope="https://www.googleapis.com/auth/devstorage.read_only"
        )
    except Exception:
        logger.exception("Failed to download tarball")
        return False

    try:
        # Download the tarball to the temporary file
        await utils.run(
            "curl", "-o", str(to), "-f", "-H", f"Authorization: Bearer {token}", url
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(
            "Failed to download %s to %s",
            url,
            to,
            extra={
                "rerturncode": e.returncode,
                "stdout": e.stdout,
                "stderr": e.stderr,
            },
        )
        return False


async def _extract_tar(*, tar_path: pathlib.Path, target_path: pathlib.Path) -> bool:
    """
    Extract the tar to the given path.
    """

    try:
        await utils.run("tar", "xf", str(tar_path), "-C", str(target_path))
        return True
    except subprocess.CalledProcessError as e:
        logger.error(
            "Failed to extract %s to %s",
            tar_path,
            target_path,
            extra={
                "rerturncode": e.returncode,
                "stdout": e.stdout,
                "stderr": e.stderr,
            },
        )
        return False


def _get_python_path(*, target_path: pathlib.Path) -> Optional[str]:
    """
    Find the correct python version to use based on the python-version file in
    the tarball.
    """

    with open(target_path / "python-version", "r") as _f:
        version_string = _f.read().strip()

    if version_string == "3.7":
        return str(settings.PYTHON_37_PATH)

    # Unsupported version
    return None


async def _create_venv(*, target_path: pathlib.Path, python: str) -> bool:
    """
    Create a virtualenv in the given path. The venv is created at .venv within
    the given directory, using the specified python executable.
    """

    try:
        await utils.run(python, "-m", "venv", str(target_path / ".venv"))
        return True
    except subprocess.CalledProcessError as e:
        logger.error(
            "Failed to create venv at %s using %s",
            target_path / ".venv",
            python,
            extra={
                "rerturncode": e.returncode,
                "stdout": e.stdout,
                "stderr": e.stderr,
            },
        )
        return False


async def _install_dependencies(*, target_path: pathlib.Path) -> bool:
    """
    Install all dependencies specified in <target_path>/requirements.txt into
    the venv, using only wheels from the <target_path>/wheels/ directory.
    """

    logger.debug("Installing dependencies")

    try:
        stdout = await utils.run(
            str(target_path / ".venv" / "bin" / "pip"),
            "install",
            "--isolated",
            "--no-index",
            "--find-links",
            str(target_path / "wheels"),
            "-r",
            str(target_path / "requirements.txt"),
            env={
                **os.environ,
                "VIRTUAL_ENV": str(target_path / ".venv"),
                "PATH": f'{target_path/".venv"/"bin"}:{os.environ.get("PATH", "")}',
                "PYTHONPATH": "",  # This is set for sacar, so unset it
            },
        )
        logger.debug(stdout)
        return True
    except subprocess.CalledProcessError as e:
        logger.exception("Failed to install dependencies")
        logger.debug(e.stderr)
        logger.debug(e.stdout)
        return False


async def _run_script(*, name: str, target_path: pathlib.Path, commit_sha: str) -> bool:
    """
    Run a script in the project directory.
    """

    venv_bin = target_path / ".venv" / "bin"

    try:
        logger.debug("Running script: %s", name)
        await utils.run(
            str(target_path / "bin" / name),
            cwd=target_path,
            env={
                **os.environ,
                "PATH": f'{venv_bin}:{os.environ.get("PATH", "")}',
                "COMMIT_SHA": commit_sha,
                "PYTHONPATH": "",  # This is set for sacar, so unset it
            },
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.debug(e.stderr)
        logger.debug(e.stdout)
        return False
