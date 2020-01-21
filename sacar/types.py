import dataclasses
import datetime
import enum
from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict

####################
# GitHub API types #
####################


class AnnotationLevel(enum.Enum):
    NOTICE = "notice"
    WARNING = "warning"
    FAILURE = "failure"


class CheckStatus(enum.Enum):
    QUEUED = "queued"
    IN_PROGESS = "in_progress"
    COMPLETED = "completed"


class CheckConclusion(enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"


class _AnnotationBase(TypedDict):
    path: str
    start_line: int
    end_line: int
    annotation_level: AnnotationLevel
    message: str


class Annotation(_AnnotationBase, total=False):
    start_column: int
    end_column: int
    title: str
    raw_details: str


class Action(TypedDict):
    label: str
    description: str
    identifier: str


class _OutputBase(TypedDict):
    title: str
    summary: str


class Output(_OutputBase, total=False):
    text: str
    annotations: List[Annotation]


class _BaseStatus(TypedDict):
    name: str
    head_sha: str
    external_id: str
    status: CheckStatus
    output: Output


class _OptionalStatusFields(TypedDict, total=False):
    actions: List[Action]


class QueuedCheck(_BaseStatus, _OptionalStatusFields):
    pass


class InProgressCheck(_BaseStatus, _OptionalStatusFields):
    started_at: datetime.datetime


class CompletedCheck(_BaseStatus, _OptionalStatusFields):
    conclusion: CheckConclusion
    completed_at: datetime.datetime


###########################
# Github webhook payloads #
###########################


class CheckSuiteAction(enum.Enum):
    REQUESTED = "requested"
    REREQUESTED = "rerequested"
    COMPLETED = "completed"


@dataclasses.dataclass(frozen=True)
class CheckSuite:
    head_branch: str
    head_sha: str


@dataclasses.dataclass(frozen=True)
class Repository:
    full_name: str
    url: str


@dataclasses.dataclass(frozen=True)
class GithubUser:
    login: str


@dataclasses.dataclass(frozen=True)
class DeploymentEvent:
    url: str
    sha: str
    ref: Optional[str]
    task: str
    payload: Dict[str, Any]
    original_environment: str
    environment: str
    creator: GithubUser


@dataclasses.dataclass(frozen=True)
class Installation:
    id: int


@dataclasses.dataclass(frozen=True)
class CheckSuiteEvent:
    """The payload we receive from GitHub for the check_suite event."""

    action: CheckSuiteAction
    check_suite: CheckSuite
    repository: Repository
    installation: Installation


##################
# Other payloads #
##################


@dataclasses.dataclass(frozen=True)
class TarballReadyEvent:

    repo_name: str
    sha: str
    branch: str
    tarball_path: str


@dataclasses.dataclass
class VersionState:

    run_id: int
    installation_id: int
    status: str
    tarball_path: Optional[str]


@dataclasses.dataclass
class SlaveVersionState:

    done: bool
    success: Optional[bool] = None
    message: Optional[str] = None


class GCPServiceAccountKey(TypedDict):
    type: str
    project_id: str
    private_key_id: str
    private_key: str
    client_email: str
    client_id: str
    auth_uri: str
    token_uri: str
    auth_provider_x509_cert_url: str
    client_x509_cert_url: str
