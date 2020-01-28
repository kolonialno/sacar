import pathlib

from starlette.config import Config
from starlette.datastructures import Secret

config = Config(".env")


DEBUG = config("SACAR_DEBUG", cast=bool, default=False)
HOSTNAME = config("SACAR_HOSTNAME")
ENVIRONMENT = config("SACAR_ENVIRONMENT")

VERSIONS_DIRECTORY = config("SACAR_VERSIONS_DIRECTORY", cast=pathlib.Path)
SLAVE_PREPARE_TIMEOUT = config("SACAR_SLAVE_PREPARE_TIMEOUT", cast=int)
PYTHON_37_PATH = config("SACAR_PYTHON37_PATH", default="python3.7")
SENTRY_DSN = config("SACAR_SENTRY_DSN")

GITHUB_APP_ID = config("SACAR_GITHUB_APP_ID", cast=int)
GITHUB_KEY_PATH = config("SACAR_GITHUB_KEY_PATH", cast=Secret)
GITHUB_WEBHOOK_SECRET = config("SACAR_GITHUB_WEBHOOK_SECRET", cast=Secret)
GITHUB_CHECK_RUN_NAME = config("SACAR_GITHUB_CHECK_RUN_NAME", default="Prepare hosts")

GCP_BUCKET = config("SACAR_GCP_BUCKET", cast=Secret)
GCP_KEY_PATH = config("SACAR_GCP_KEY_PATH", cast=pathlib.Path)

CONSUL_HTTP_TOKEN = config("CONSUL_HTTP_TOKEN", cast=Secret)
CONSUL_HOST = config("SACAR_CONSUL_HOST")
CONSUL_KEY_PREFIX = config("SACAR_CONSUL_KEY_PREFIX")
