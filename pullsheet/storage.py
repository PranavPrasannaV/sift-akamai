"""Akamai Object Storage: the original of every export a run read.

A pull sheet is only as trustworthy as the file it was made from. Each delivery
(SFTP drop, email attachment, upload) is copied byte-for-byte into the bucket
under ``exports/run-<id>/<filename>`` the moment its run is decided, accepted or
rejected. The kitchen's server can be rebuilt; the evidence stays. Files leave
the bucket only through presigned links that expire after an hour, so the
bucket stays private.

Disabled (every function a no-op) when OBJ_BUCKET is not set, so tests and an
offline kitchen run unchanged.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)
LINK_SECONDS = 3600


def enabled() -> bool:
    return bool(os.environ.get("OBJ_BUCKET"))


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("OBJ_ENDPOINT"),
        aws_access_key_id=os.environ.get("OBJ_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("OBJ_SECRET_KEY"),
        # boto3 1.36+ adds checksums Akamai Object Storage does not accept.
        config=Config(signature_version="s3v4", request_checksum_calculation="when_required"),
    )


def _bucket() -> str:
    return os.environ["OBJ_BUCKET"]


def export_key(run_id: int, filename: str) -> str:
    return f"exports/run-{run_id}/{Path(filename).name}"


def archive_export(run_id: int, path: Path) -> str | None:
    """Copy one delivered file into the bucket. Never raises: a storage outage
    must not stop a pull sheet from being produced."""
    if not enabled():
        return None
    key = export_key(run_id, path.name)
    try:
        _client().put_object(Bucket=_bucket(), Key=key, Body=path.read_bytes(),
                             Metadata={"run-id": str(run_id)})
        return key
    except Exception:  # noqa: BLE001 -- logged, and the run still finalizes
        log.exception("could not archive %s to object storage", path.name)
        return None


def exports_for_run(run_id: int) -> list[dict]:
    """What the bucket holds for one run, each with a one-hour link."""
    if not enabled():
        return []
    try:
        listing = _client().list_objects_v2(Bucket=_bucket(), Prefix=f"exports/run-{run_id}/")
    except Exception:  # noqa: BLE001
        log.exception("could not list object storage for run %s", run_id)
        return []
    return [{
        "key": item["Key"],
        "name": item["Key"].rsplit("/", 1)[-1],
        "bytes": item["Size"],
        "url": link(item["Key"]),
    } for item in listing.get("Contents", [])]


def link(key: str) -> str:
    return _client().generate_presigned_url(
        "get_object", Params={"Bucket": _bucket(), "Key": key}, ExpiresIn=LINK_SECONDS)


def health() -> str:
    if not enabled():
        return "not set"
    try:
        _client().head_bucket(Bucket=_bucket())
        return "connected"
    except Exception as error:  # noqa: BLE001
        return f"error: {str(error).splitlines()[0][:120]}"
