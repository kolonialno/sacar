import pathlib

from starlette.config import Config
from starlette.datastructures import Secret

config = Config(".env")


DEBUG = config("SACAR_DEBUG", cast=bool, default=False)
PRIVATE_KEY_PATH = config("SACAR_PRIVATE_KEY_PATH", cast=Secret)
WEBHOOK_SECRET_KEY = config("SACAR_WEBHOOK_SECRET_KEY", cast=Secret)
VERSIONS_DIRECTORY = config("SACAR_VERSIONS_DIRECTORY", cast=pathlib.Path)
ENVIRONMENT = config("SACAR_ENVIRONMENT")
SLAVE_PREPARE_TIMEOUT = config("SACAR_SLAVE_PREPARE_TIMEOUT", cast=int)
HOSTNAME = config("SACAR_HOSTNAME")
CONSUL_HOST = config("SACAR_CONSUL_HOST")
CHECK_RUN_NAME = config("SACAR_CHECK_RUN_NAME", default="Prepare hosts")
GCP_BUCKET = config("SACAR_GCP_BUCKET", cast=Secret)
GCP_KEY_PATH = config("SACAR_GCP_KEY_PATH", cast=pathlib.Path)
