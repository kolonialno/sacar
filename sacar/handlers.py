import logging

from starlette.background import BackgroundTask
from starlette.responses import Response

from . import consul, decorators, github, settings, tasks, types, utils

logger = logging.getLogger("sacar")


###################
# GitHub webhooks #
###################


@decorators.decode_payload(data_class=types.CheckSuiteEvent)
async def check_suite_event(payload: types.CheckSuiteEvent) -> Response:
    """
    Handle an incomming check suite event.
    """

    if payload.action in (
        types.CheckSuiteAction.REQUESTED,
        types.CheckSuiteAction.REREQUESTED,
    ):

        logger.debug("Got check_suite webhook event: %s", payload)

        logger.debug(
            "Creating check run: %s %s",
            payload.check_suite.head_branch,
            payload.check_suite.head_sha,
        )

        run_id = await github.create_or_update_queued_check_run(
            repo_url=payload.repository.url,
            installation_id=payload.installation.id,
            payload={
                "name": settings.GITHUB_CHECK_RUN_NAME,
                "head_sha": payload.check_suite.head_sha,
                "status": types.CheckStatus.QUEUED,
                "external_id": "",
                "output": {
                    "title": settings.GITHUB_CHECK_RUN_NAME,
                    "summary": "Waiting for tarball",
                },
            },
        )

        logger.debug("Storing state in Consul")

        async with consul.Client() as client:
            await client.put(
                key=f"{payload.repository.full_name}/{payload.check_suite.head_sha}",
                value=types.VersionState(
                    run_id=run_id,
                    installation_id=payload.installation.id,
                    status="waiting-for-tarball",
                    tarball_path=None,
                    deployment_id=None,
                ),
            )

        logger.debug("Stored state in Consul")
    else:
        logger.debug('Ignoring check_suite event with action "%s"', payload.action)

    return Response(b"")


@decorators.decode_payload(data_class=types.DeploymentEvent)
async def deployment_event(payload: types.DeploymentEvent) -> Response:
    """
    Handle an incomming check suite event.
    """

    logger.debug("Got deployment webhook event: %s", payload)

    # Ignore deployment events for other environments
    if payload.environment != settings.ENVIRONMENT:
        logger.debug(
            "Wrong environment, not deploying (%s != %s)",
            payload.environment,
            settings.ENVIRONMENT,
        )
        return Response(b"")

    # Respond and start the deployment in the background
    return Response(
        b"",
        background=BackgroundTask(
            tasks.deploy,
            repo_url=payload.repository.url,
            repo_name=payload.repository.full_name,
            commit_sha=payload.sha,
            deployment_id=payload.deployment.id,
        ),
    )


##################
# Other webhooks #
##################


@decorators.decode_payload(data_class=types.TarballReadyEvent)
async def tarball_ready_event(payload: types.TarballReadyEvent) -> Response:
    """
    Handle callback when the tarball is ready. If it's on the master branch
    this will ask all slaves to prepare the tarball for deployment.
    """

    logger.debug("Got tarball ready callback: %s", payload)

    async with consul.Client() as client:
        _, state = await client.get(
            f"{payload.repo_name}/{payload.sha}", cls=types.VersionState
        )

    if payload.branch != settings.DEPLOY_BRANCH:

        logger.debug(
            "Not deploying commit on %s, only deploying commits on %s",
            payload.branch,
            settings.DEPLOY_BRANCH,
        )

        # If we're not on the master branch, don't prepare
        await github.create_or_update_completed_check_run(
            repo_url=f"https://api.github.com/repos/{payload.repo_name}",
            run_id=state.run_id,
            installation_id=state.installation_id,
            payload={
                "name": settings.GITHUB_CHECK_RUN_NAME,
                "head_sha": payload.sha,
                "status": types.CheckStatus.COMPLETED,
                "external_id": "",
                "completed_at": utils.now(),
                "conclusion": types.CheckConclusion.NEUTRAL,
                "output": {
                    "title": settings.GITHUB_CHECK_RUN_NAME,
                    "summary": "Preparing hosts",
                    "text": "Not preparing commit not on master",
                },
                "actions": [
                    {
                        "label": "Prepare this commit",
                        "description": "Prepare this version anyway",
                        "identifier": "prepare",
                    }
                ],
            },
        )
        return Response(b"")

    started_at = utils.now()

    logger.debug("Asking slaves to prepare hosts")

    try:
        num_slaves = await tasks.prepare_hosts(payload=payload, state=state)

        logger.debug("Asked slaves to prepare hosts")

        await github.create_or_update_in_progress_check_run(
            repo_url=f"https://api.github.com/repos/{payload.repo_name}",
            run_id=state.run_id,
            installation_id=state.installation_id,
            payload={
                "name": settings.GITHUB_CHECK_RUN_NAME,
                "head_sha": payload.sha,
                "status": types.CheckStatus.IN_PROGRESS,
                "external_id": "",
                "started_at": started_at,
                "output": {
                    "title": settings.GITHUB_CHECK_RUN_NAME,
                    "summary": "Preparing hosts",
                },
            },
        )

        logger.debug("Updated github check")

        # Respond that we have received the webhook and wait for the hosts to finish
        # in the background.
        return Response(
            b"",
            status_code=202,
            background=BackgroundTask(
                tasks.wait_for_hosts,
                num_slaves=num_slaves,
                payload=payload,
                check_run_id=state.run_id,
                installation_id=state.installation_id,
                started_at=started_at,
            ),
        )

    except Exception:

        await github.create_or_update_completed_check_run(
            repo_url=f"https://api.github.com/repos/{payload.repo_name}",
            run_id=state.run_id,
            installation_id=state.installation_id,
            payload={
                "name": settings.GITHUB_CHECK_RUN_NAME,
                "head_sha": payload.sha,
                "status": types.CheckStatus.COMPLETED,
                "external_id": "",
                "completed_at": utils.now(),
                "conclusion": types.CheckConclusion.FAILURE,
                "output": {
                    "title": settings.GITHUB_CHECK_RUN_NAME,
                    "summary": "Error while preparing version",
                },
            },
        )

        raise


@decorators.decode_payload(data_class=types.TarballReadyEvent)
async def prepare_host(payload: types.TarballReadyEvent) -> Response:
    """
    Callback from the master node to prepare a given version for deployment.
    """

    logger.debug("Received prepare host callback")

    return Response(
        b"",
        status_code=202,
        # Start preparing in the background
        background=BackgroundTask(tasks.prepare_host, payload=payload),
    )
