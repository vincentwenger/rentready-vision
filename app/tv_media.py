"""Short-lived server-side image grants for approved TV findings.

The caller MUST authenticate and authorize the requested inspection
before calling this module. The returned URL is a temporary bearer
capability and must not be logged, cached, or made public.

No AWS requests are made by the selection logic. The supplied S3
signer is responsible for generating the temporary URL.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .tv_evidence import preserved_image_keys_by_finding


TV_IMAGE_TTL_SECONDS = 120

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def create_tv_image_grant(
    *,
    inspection_id: str,
    finding_id: str,
    report: dict[str, Any],
    bucket: str,
    signer: Any,
) -> dict[str, Any]:
    """Create a temporary grant for one verified preserved image.

    Authentication, inspection authorization and inspection completion
    checks belong to the API caller; this helper performs additional
    finding and preserved-object validation.

    Raises ValueError for invalid input and LookupError when no
    approved preserved image is associated with the finding.
    """

    if not isinstance(finding_id, str) or not re.fullmatch(
        r"[0-9a-f]{32}", finding_id
    ):
        raise ValueError("Invalid TV finding identifier")

    if not isinstance(bucket, str) or not bucket.strip():
        raise ValueError("S3 bucket configuration is missing")

    mapping = preserved_image_keys_by_finding(
        inspection_id,
        report,
    )

    key = mapping.get(finding_id)

    if key is None:
        raise LookupError("Preserved finding image unavailable")

    extension = "." + key.rsplit(".", 1)[-1].lower()
    content_type = CONTENT_TYPES.get(extension)

    if content_type is None:
        raise ValueError("Unsupported preserved image type")

    url = signer.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentType": content_type,
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=TV_IMAGE_TTL_SECONDS,
        HttpMethod="GET",
    )

    if not isinstance(url, str):
        raise ValueError("Invalid signed image URL")

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()

    is_s3_host = (
        host == "s3.amazonaws.com"
        or (
            host.endswith(".amazonaws.com")
            and (
                host.startswith("s3.")
                or ".s3." in host
                or host.endswith(".s3.amazonaws.com")
            )
        )
    )

    if (
        parsed.scheme != "https"
        or not is_s3_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or bool(parsed.fragment)
    ):
        raise ValueError("Invalid signed S3 HTTPS URL")

    return {
        "url": url,
        "expires_in_seconds": TV_IMAGE_TTL_SECONDS,
    }
