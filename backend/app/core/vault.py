"""
HashiCorp Vault integration for Minerva.

Used exclusively for storing and retrieving Ansible SSH credentials
(SSH private keys, passwords, etc.). The `credentials` table in
PostgreSQL holds only metadata (name, type, vault_path); the actual
secret material lives in Vault under the configured KV v2 mount.

Usage example:
    cred = await get_credential("ansible/node-prod-01")
    # cred = {"private_key": "-----BEGIN OPENSSH PRIVATE KEY-----..."}
    #    or  {"password": "s3cr3t"}
"""

import logging
from functools import lru_cache
from typing import Any

import hvac

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _vault_client() -> hvac.Client:
    """Return a cached (module-level singleton) Vault client."""
    client = hvac.Client(url=settings.VAULT_URL, token=settings.VAULT_TOKEN)
    if not client.is_authenticated():
        raise RuntimeError(
            f"Vault client is not authenticated. Check VAULT_URL and VAULT_TOKEN. "
            f"(url={settings.VAULT_URL})"
        )
    return client


async def get_credential(vault_path: str) -> dict[str, Any]:
    """
    Retrieve secret data from Vault KV v2 at `vault_path`.

    Args:
        vault_path: Path within the KV mount, e.g. "ansible/node-prod-01"

    Returns:
        dict with secret key-value pairs, e.g.:
            {"private_key": "..."} for SSH key credentials
            {"password": "..."}   for password credentials

    Raises:
        ValueError: if the secret does not exist at the given path.
        RuntimeError: if Vault is unavailable or unauthenticated.
    """
    try:
        client = _vault_client()
        response = client.secrets.kv.v2.read_secret_version(
            path=vault_path,
            mount_point=settings.VAULT_MOUNT_PATH,
        )
        data: dict[str, Any] = response["data"]["data"]
        logger.debug("vault: read credential path=%s keys=%s", vault_path, list(data.keys()))
        return data
    except hvac.exceptions.InvalidPath:
        raise ValueError(f"Credential not found in Vault at path: {vault_path!r}")
    except Exception as exc:
        logger.error("vault: failed to read path=%s: %s", vault_path, exc)
        raise


async def write_credential(vault_path: str, data: dict[str, Any]) -> None:
    """
    Write (or update) secret data in Vault KV v2 at `vault_path`.

    Args:
        vault_path: Path within the KV mount.
        data: Secret key-value pairs to store.
    """
    try:
        client = _vault_client()
        client.secrets.kv.v2.create_or_update_secret(
            path=vault_path,
            secret=data,
            mount_point=settings.VAULT_MOUNT_PATH,
        )
        logger.info("vault: wrote credential path=%s", vault_path)
    except Exception as exc:
        logger.error("vault: failed to write path=%s: %s", vault_path, exc)
        raise


async def delete_credential(vault_path: str) -> None:
    """Delete all versions of a secret in Vault KV v2."""
    try:
        client = _vault_client()
        client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=vault_path,
            mount_point=settings.VAULT_MOUNT_PATH,
        )
        logger.info("vault: deleted credential path=%s", vault_path)
    except Exception as exc:
        logger.error("vault: failed to delete path=%s: %s", vault_path, exc)
        raise
