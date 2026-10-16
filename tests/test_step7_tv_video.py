"""Offline security tests for approved Fire TV video grants.

FakeS3 performs no network or AWS requests.
"""

import pytest
from botocore.exceptions import ClientError

from app.tv_video import (
    APPROVED_CLIPS,
    BUCKET,
    INSPECTION_ID,
    VIDEO_TTL_SECONDS,
    create_tv_video_grant,
)


@pytest.fixture(autouse=True)
def use_original_v1_video_receipts(monkeypatch):
    monkeypatch.setattr(
        "app.tv_video.ACTIVE_VIDEO_VERSION", "v1"
    )

GARAGE_DAMAGE = "877eec22117f6f9508a087d46ed59e43"
GARAGE_STAIN = "c8ee6b7a97fca8b65ffba5192fd62ac8"
BEDROOM_WALL = "555f0443603ef3e57caaace06ea4bed5"

SOURCE = (
    f"rentready/inspections/{INSPECTION_ID}"
    "/original/walkthrough.mov"
)


class FakeS3:
    def __init__(self, finding_id=GARAGE_DAMAGE):
        self.finding_id = finding_id
        self.calls = []
        size, checksum = APPROVED_CLIPS[finding_id]

        self.head = {
            "ContentLength": size,
            "ContentType": "video/mp4",
            "ServerSideEncryption": "AES256",
            "Metadata": {
                "inspection-id": INSPECTION_ID,
                "finding-id": finding_id,
                "sha256": checksum,
                "purpose": "fire-tv-evidence",
            },
        }

        self.url = (
            f"https://{BUCKET}.s3.us-west-2.amazonaws.com/"
            "approved.mp4?X-Amz-Signature=test-signature"
        )
        self.error_code = None

    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs))

        if self.error_code:
            raise ClientError(
                {
                    "Error": {
                        "Code": self.error_code,
                        "Message": "Private provider diagnostics",
                    }
                },
                "HeadObject",
            )

        return self.head

    def generate_presigned_url(self, operation, **kwargs):
        self.calls.append(("sign", operation, kwargs))
        return self.url


def grant(s3, finding_id=GARAGE_DAMAGE, **overrides):
    args = {
        "inspection_id": INSPECTION_ID,
        "finding_id": finding_id,
        "authorized_finding_ids": {finding_id},
        "original_s3_key": SOURCE,
        "bucket": BUCKET,
        "signer": s3,
    }
    args.update(overrides)
    return create_tv_video_grant(**args)


@pytest.mark.parametrize(
    "finding_id",
    [GARAGE_DAMAGE, GARAGE_STAIN, BEDROOM_WALL],
)
def test_approved_clip_receives_bounded_get_grant(finding_id):
    s3 = FakeS3(finding_id)
    result = grant(s3, finding_id)

    assert result["expires_in_seconds"] == 120
    assert result["url"] == s3.url
    assert VIDEO_TTL_SECONDS == 120

    assert len(s3.calls) == 2

    _, head_args = s3.calls[0]

    assert head_args["Bucket"] == BUCKET
    assert head_args["Key"].endswith(
        f"/evidence/tv-clips/{finding_id}.mp4"
    )

    _, operation, signed = s3.calls[1]

    assert operation == "get_object"
    assert signed["ExpiresIn"] == 120
    assert signed["HttpMethod"] == "GET"
    assert signed["Params"]["Key"] == head_args["Key"]
    assert signed["Params"]["ResponseContentType"] == "video/mp4"


def test_unapproved_id_denied_before_s3_access():
    s3 = FakeS3()

    with pytest.raises(LookupError):
        grant(s3, "a" * 32)

    assert s3.calls == []


def test_malformed_finding_denied_before_s3_access():
    s3 = FakeS3()

    with pytest.raises(LookupError):
        grant(s3, "../original/walkthrough.mov")

    assert s3.calls == []


def test_wrong_inspection_denied_before_s3_access():
    s3 = FakeS3()

    with pytest.raises(LookupError):
        grant(
            s3,
            inspection_id="00000000-0000-4000-8000-000000000000",
        )

    assert s3.calls == []


def test_finding_must_be_in_authorized_projection():
    s3 = FakeS3()

    with pytest.raises(LookupError):
        grant(s3, authorized_finding_ids=set())

    assert s3.calls == []


@pytest.mark.parametrize(
    "source",
    [
        "original/walkthrough.mov",
        f"inspections/other/original/walkthrough.mov",
        f"rentready/inspections/{INSPECTION_ID}/"
        "original/../evidence/walkthrough.mov",
    ],
)
def test_untrusted_original_video_location_denied(source):
    s3 = FakeS3()

    with pytest.raises(ValueError):
        grant(s3, original_s3_key=source)

    assert s3.calls == []


def test_approved_alternate_inspection_prefix():
    s3 = FakeS3()

    alternate = (
        f"inspections/{INSPECTION_ID}/original/walkthrough.mov"
    )

    grant(s3, original_s3_key=alternate)

    assert s3.calls[0][1]["Key"].startswith(
        f"inspections/{INSPECTION_ID}/evidence/tv-clips/"
    )


def test_wrong_bucket_denied_before_s3_access():
    s3 = FakeS3()

    with pytest.raises(ValueError):
        grant(s3, bucket="other-bucket")

    assert s3.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("ContentLength", 1),
        ("ContentType", "application/octet-stream"),
        ("ServerSideEncryption", None),
    ],
)
def test_tampered_object_headers_block_signing(field, value):
    s3 = FakeS3()
    s3.head[field] = value

    with pytest.raises(ValueError):
        grant(s3)

    assert [call[0] for call in s3.calls] == ["head"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("inspection-id", "other-inspection"),
        ("finding-id", "f" * 32),
        ("sha256", "0" * 64),
        ("purpose", "unapproved"),
    ],
)
def test_tampered_object_metadata_blocks_signing(field, value):
    s3 = FakeS3()
    s3.head["Metadata"][field] = value

    with pytest.raises(ValueError):
        grant(s3)

    assert [call[0] for call in s3.calls] == ["head"]


def test_missing_s3_object_returns_unavailable():
    s3 = FakeS3()
    s3.error_code = "404"

    with pytest.raises(LookupError, match="unavailable"):
        grant(s3)

    assert len(s3.calls) == 1


def test_s3_access_error_does_not_reveal_provider_details():
    s3 = FakeS3()
    s3.error_code = "AccessDenied"

    with pytest.raises(RuntimeError) as exc:
        grant(s3)

    assert "Private provider diagnostics" not in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://s3.amazonaws.com/file.mp4?Signature=x",
        "https://evil.example/file.mp4?Signature=x",
        "https://s3.amazonaws.com/file.mp4",
        "https://s3.amazonaws.com/file.mp4?Signature=x#fragment",
    ],
)
def test_unsafe_or_unsigned_urls_rejected(url):
    s3 = FakeS3()
    s3.url = url

    with pytest.raises(ValueError):
        grant(s3)

    assert len(s3.calls) == 2


def test_no_full_walkthrough_or_s3_get_operation_is_requested():
    s3 = FakeS3()
    grant(s3)

    assert all(
        "original/walkthrough.mov" not in str(call)
        for call in s3.calls
    )
    assert all(call[0] in ("head", "sign") for call in s3.calls)
