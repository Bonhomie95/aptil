"""MinIO / S3-compatible object storage for CVs and generated résumés."""

from __future__ import annotations

import os
import re
import threading
import unicodedata
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# boto3 client construction is expensive (~100ms) and the client is thread-safe,
# so build it once per process instead of per call.
_client_lock = threading.Lock()
_cached_client = None

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class StorageUnavailable(RuntimeError):
    """Object storage could not be reached or refused the operation.

    Distinct from a programming error so routes can answer 503 with something
    actionable instead of an opaque 500.
    """


def is_aws_endpoint() -> bool:
    """True when we're talking to real AWS S3 rather than MinIO/R2/B2."""
    ep = (settings.MINIO_ENDPOINT or "").strip().lower()
    return ep == "" or ep.endswith(".amazonaws.com")


def _client():
    global _cached_client
    if _cached_client is None:
        with _client_lock:
            if _cached_client is None:
                kwargs: dict = {
                    "aws_access_key_id": settings.MINIO_ROOT_USER,
                    "aws_secret_access_key": settings.MINIO_ROOT_PASSWORD,
                    # The region is part of the SigV4 signature. Hardcoding
                    # us-east-1 works for MinIO (which ignores it) but produces
                    # SignatureDoesNotMatch against a real S3 bucket in any
                    # other region.
                    "region_name": settings.MINIO_REGION or "us-east-1",
                }
                config: dict = {
                    "signature_version": "s3v4",
                    "retries": {"max_attempts": 3, "mode": "standard"},
                }

                endpoint = (settings.MINIO_ENDPOINT or "").strip()
                if endpoint:
                    scheme = "https" if settings.MINIO_SECURE else "http"
                    kwargs["endpoint_url"] = f"{scheme}://{endpoint}"
                # MinIO and most S3-compatibles want path-style addressing;
                # AWS prefers virtual-hosted. Left on "auto" for AWS.
                if not is_aws_endpoint():
                    config["s3"] = {"addressing_style": "path"}

                _cached_client = boto3.client("s3", config=Config(**config), **kwargs)
    return _cached_client


def reset_client() -> None:
    """Drop the cached client (used by tests)."""
    global _cached_client
    _cached_client = None


def safe_filename(name: str | None, fallback: str = "resume") -> str:
    """Reduce a user-supplied filename to a safe, flat basename.

    Strips directory components and anything outside ``[A-Za-z0-9._-]`` so a
    crafted name (``../../other-tenant/x.pdf``) cannot escape the tenant prefix
    of the object key.
    """
    raw = (name or "").strip()
    # Windows and POSIX separators both, then take the final component.
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    raw = _SAFE_NAME_RE.sub("-", raw).strip(".-")
    # Reject names that are only dots/dashes after cleaning.
    if not raw or set(raw) <= {".", "-"}:
        raw = fallback
    if len(raw) > 120:
        stem, ext = os.path.splitext(raw)
        raw = stem[: 120 - len(ext)] + ext
    return raw


def build_object_key(tenant_id, folder: str, filename: str | None) -> str:
    """Tenant-scoped, collision-free object key with a sanitized basename."""
    return f"{tenant_id}/{folder}/{uuid.uuid4()}-{safe_filename(filename)}"


def ensure_bucket() -> None:
    """Create the bucket if it does not exist. Safe to call on every boot."""
    client = _client()
    bucket = settings.MINIO_BUCKET
    region = settings.MINIO_REGION or "us-east-1"

    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code == "403":
            # The bucket exists and belongs to someone (usually us) but the
            # credentials cannot list it. Creating would fail; assume it's there.
            log.info("bucket_exists_no_head_permission", bucket=bucket)
            return
        if code not in ("404", "NoSuchBucket"):
            raise

    params: dict = {"Bucket": bucket}
    # S3 rejects a LocationConstraint of us-east-1 but requires it everywhere
    # else. MinIO accepts either.
    if region != "us-east-1":
        params["CreateBucketConfiguration"] = {"LocationConstraint": region}

    try:
        client.create_bucket(**params)
        log.info("bucket_created", bucket=bucket, region=region)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        # Someone (or another replica booting at the same time) got there first.
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            log.info("bucket_already_exists", bucket=bucket)
            return
        raise


def head_bucket() -> None:
    """Cheap reachability check for the readiness probe. Raises if unreachable."""
    _client().head_bucket(Bucket=settings.MINIO_BUCKET)


def upload_fileobj(fileobj, key: str, content_type: str) -> str:
    try:
        _client().upload_fileobj(
            fileobj,
            settings.MINIO_BUCKET,
            key,
            ExtraArgs={"ContentType": content_type},
        )
    except (ClientError, EndpointConnectionError, BotoCoreError) as exc:
        log.error("storage_upload_failed", key=key, error=str(exc)[:200])
        raise StorageUnavailable("Could not store the file") from exc
    return key


def upload_bytes(data: bytes, key: str, content_type: str) -> str:
    try:
        _client().put_object(
            Bucket=settings.MINIO_BUCKET, Key=key, Body=data, ContentType=content_type
        )
    except (ClientError, EndpointConnectionError, BotoCoreError) as exc:
        log.error("storage_upload_failed", key=key, error=str(exc)[:200])
        raise StorageUnavailable("Could not store the file") from exc
    return key


def download_bytes(key: str) -> bytes:
    try:
        obj = _client().get_object(Bucket=settings.MINIO_BUCKET, Key=key)
        return obj["Body"].read()
    except (ClientError, EndpointConnectionError, BotoCoreError) as exc:
        log.error("storage_download_failed", key=key, error=str(exc)[:200])
        raise StorageUnavailable("Could not read the file") from exc


def delete_object(key: str) -> None:
    """Best-effort delete; a missing object is not an error.

    Catches the same family as the upload helpers, not just ``ClientError``: an
    unreachable endpoint raises ``EndpointConnectionError``, which used to
    escape and take down whatever was tidying up — replacing a résumé would
    have failed outright because the *old* file could not be removed.
    """
    try:
        _client().delete_object(Bucket=settings.MINIO_BUCKET, Key=key)
    except (ClientError, EndpointConnectionError, BotoCoreError) as exc:
        log.warning("object_delete_failed", key=key, error=str(exc)[:200])


def presigned_get_url(key: str, expires: int = 3600, filename: str | None = None) -> str:
    params: dict = {"Bucket": settings.MINIO_BUCKET, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = (
            f'attachment; filename="{safe_filename(filename)}"'
        )
    return _client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires
    )
