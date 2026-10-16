"""Explicitly approved, private Fire TV evidence video grants.

This module does not authenticate requests. The API route MUST
authenticate the caller, authorize the inspection, and confirm
finding membership in the completed TV projection first.

Never log signed URLs, operator tokens or S3 object keys.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qs, urlsplit

from botocore.exceptions import ClientError

INSPECTION_ID = "b2054cf1-2401-44df-b675-d01d28acffa9"
BUCKET = "rentready-vision-dev-081087819788"
REGION = "us-west-2"

VIDEO_TTL_SECONDS = 120

# Immutable approved upload receipt:
# finding ID -> (expected bytes, SHA-256 hex).
APPROVED_CLIPS = MappingProxyType({
    "877eec22117f6f9508a087d46ed59e43": (
        1680604,
        "e880c48059bcc316f1770d0a38798e9b2267d9081e9dbd0d589bca7de8dcc5ca",
    ),
    "c8ee6b7a97fca8b65ffba5192fd62ac8": (
        3201166,
        "cf218b89bff86b27e391d3818bc27a404f5df07ead8d5099d567077d5a0d9292",
    ),
    "555f0443603ef3e57caaace06ea4bed5": (
        1078098,
        "29c85d496ad2634805591391a00951e5d4e4f6c1d51c3653b471ff78753c9ac1",
    ),
})


# Step 7.18F.11B - Explicit versioned evidence approval.
# V2 is the verified production default; V1 is retained for rollback.
ACTIVE_VIDEO_VERSION = "v2"

APPROVED_CLIPS_V2 = MappingProxyType({
    "877eec22117f6f9508a087d46ed59e43": (
        1762755,
        "2b1d2260bd1fb65d504926f0bf601c3b816ee807cda2fa279b1e2c563959edba",
    ),
    "c8ee6b7a97fca8b65ffba5192fd62ac8": (
        987849,
        "8469a65f2bd5b9f9de99caea5b5230d45e09a19a3eef67e843adb1f4d25fbea5",
    ),
    "555f0443603ef3e57caaace06ea4bed5": (
        397496,
        "74783be1f9900ab27424359319c859c02dda42bd1e48cfa093cde96f201e3223",
    ),
})

VIDEO_CLIP_VERSIONS = MappingProxyType({
    "v1": ("tv-clips", APPROVED_CLIPS),
    "v2": ("tv-clips-v2", APPROVED_CLIPS_V2),
})

def _storage_root(inspection_id: str, source_key: str) -> str:
    """Derive the private inspection prefix from trusted metadata."""

    if (
        not isinstance(source_key, str)
        or len(source_key) > 1024
        or any(c in source_key for c in ("\\", "?", "#", "\r", "\n"))
        or any(p in ("", ".", "..") for p in source_key.split("/"))
    ):
        raise ValueError("Invalid original video reference")

    for root in (
        f"rentready/inspections/{inspection_id}",
        f"inspections/{inspection_id}",
    ):
        if source_key.startswith(root + "/original/"):
            return root

    raise ValueError("Invalid inspection storage prefix")


def _validate_signed_url(url: Any, bucket: str) -> None:
    """Accept only HTTPS signed Amazon S3 URLs."""

    if not isinstance(url, str):
        raise ValueError("Invalid signed video URL")

    try:
        parsed = urlsplit(url)

        allowed_hosts = {
            "s3.amazonaws.com",
            f"s3.{REGION}.amazonaws.com",
            f"{bucket}.s3.amazonaws.com",
            f"{bucket}.s3.{REGION}.amazonaws.com",
        }

        query = parse_qs(parsed.query)

        has_signature = bool(
            query.get("X-Amz-Signature")
            or query.get("Signature")
        )

        valid = (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() in allowed_hosts
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.fragment
            and has_signature
        )
    except ValueError:
        valid = False

    if not valid:
        raise ValueError("Unsafe or unsigned S3 video URL")


def create_tv_video_grant(
    *,
    inspection_id: str,
    finding_id: str,
    authorized_finding_ids: Collection[str],
    original_s3_key: str,
    bucket: str,
    signer: Any,
) -> dict[str, Any]:
    """Grant GET access to exactly one approved, verified MP4.

    The caller is responsible for authentication and inspection
    authorization BEFORE invoking this helper.

    This helper independently enforces the demo inspection,
    approved finding identity, storage path, object metadata,
    encryption and short signed-URL lifetime.
    """

    if inspection_id != INSPECTION_ID:
        raise LookupError("Finding video unavailable")

    if ACTIVE_VIDEO_VERSION not in VIDEO_CLIP_VERSIONS:
        raise ValueError("Unknown approved video version")

    clip_directory, active_clips = VIDEO_CLIP_VERSIONS[
        ACTIVE_VIDEO_VERSION
    ]

    if (
        not isinstance(finding_id, str)
        or not re.fullmatch(r"[0-9a-f]{32}", finding_id)
        or finding_id not in active_clips
    ):
        raise LookupError("Finding video unavailable")

    if (
        authorized_finding_ids is None
        or finding_id not in authorized_finding_ids
    ):
        raise LookupError("Finding video unavailable")

    if bucket != BUCKET:
        raise ValueError("Unexpected video storage bucket")

    root = _storage_root(inspection_id, original_s3_key)

    key = (
        f"{root}/evidence/{clip_directory}/{finding_id}.mp4"
    )

    expected_size, expected_sha256 = active_clips[finding_id]

    try:
        head = signer.head_object(
            Bucket=bucket,
            Key=key,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")

        if code in ("404", "NotFound", "NoSuchKey"):
            raise LookupError("Finding video unavailable") from None

        raise RuntimeError(
            "Video storage temporarily unavailable"
        ) from None
    except Exception:
        raise RuntimeError(
            "Video storage temporarily unavailable"
        ) from None

    metadata = head.get("Metadata")

    if not isinstance(metadata, dict):
        raise ValueError("Approved video metadata invalid")

    valid_object = (
        head.get("ContentLength") == expected_size
        and head.get("ContentType") == "video/mp4"
        and head.get("ServerSideEncryption") == "AES256"
        and metadata.get("inspection-id") == inspection_id
        and metadata.get("finding-id") == finding_id
        and metadata.get("sha256") == expected_sha256
        and metadata.get("purpose") == "fire-tv-evidence"
    )

    if not valid_object:
        raise ValueError("Approved video object verification failed")

    try:
        url = signer.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ResponseContentType": "video/mp4",
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=VIDEO_TTL_SECONDS,
            HttpMethod="GET",
        )
    except Exception:
        raise RuntimeError(
            "Video grant temporarily unavailable"
        ) from None

    _validate_signed_url(url, bucket)

    return {
        "url": url,
        "expires_in_seconds": VIDEO_TTL_SECONDS,
    }
