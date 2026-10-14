import pytest

from app import tv_video


INSPECTION_ID = tv_video.INSPECTION_ID
BUCKET = tv_video.BUCKET
REGION = tv_video.REGION

SOURCE = (
    f"rentready/inspections/{INSPECTION_ID}"
    "/original/walkthrough.mov"
)

FINDING_IDS = tuple(tv_video.APPROVED_CLIPS_V2)


class FakeS3:
    def __init__(self, finding_id, approval):
        self.calls = []

        size, checksum = approval

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

    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs))
        return self.head

    def generate_presigned_url(
        self, method, Params, ExpiresIn, HttpMethod
    ):
        self.calls.append((
            "sign",
            {
                "method": method,
                "params": Params,
                "expires": ExpiresIn,
                "http_method": HttpMethod,
            },
        ))

        return (
            f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"
            f"{Params['Key']}?X-Amz-Signature=test-signature"
        )


def issue_grant(signer, finding_id, inspection_id=INSPECTION_ID,
                authorized=None, bucket=BUCKET, source=SOURCE):

    if authorized is None:
        authorized = {finding_id}

    return tv_video.create_tv_video_grant(
        inspection_id=inspection_id,
        finding_id=finding_id,
        authorized_finding_ids=authorized,
        original_s3_key=source,
        bucket=bucket,
        signer=signer,
    )


def test_v1_remains_default():
    assert tv_video.ACTIVE_VIDEO_VERSION == "v1"
    assert tv_video.VIDEO_CLIP_VERSIONS["v1"][0] == "tv-clips"
    assert tv_video.VIDEO_CLIP_VERSIONS["v2"][0] == "tv-clips-v2"


@pytest.mark.parametrize("finding_id", FINDING_IDS)
def test_v2_uses_separate_approved_object(monkeypatch, finding_id):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    result = issue_grant(signer, finding_id)

    expected_key = (
        f"rentready/inspections/{INSPECTION_ID}"
        f"/evidence/tv-clips-v2/{finding_id}.mp4"
    )

    assert len(signer.calls) == 2

    head_call = signer.calls[0]
    sign_call = signer.calls[1]

    assert head_call[0] == "head"
    assert head_call[1]["Bucket"] == BUCKET
    assert head_call[1]["Key"] == expected_key

    assert sign_call[0] == "sign"
    assert sign_call[1]["method"] == "get_object"
    assert sign_call[1]["params"]["Key"] == expected_key
    assert sign_call[1]["expires"] == 120
    assert sign_call[1]["http_method"] == "GET"

    assert result["expires_in_seconds"] == 120
    assert result["url"].startswith("https://")


@pytest.mark.parametrize("finding_id", FINDING_IDS)
def test_v2_rejects_v1_object_receipts(monkeypatch, finding_id):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS[finding_id],
    )

    with pytest.raises(ValueError):
        issue_grant(signer, finding_id)

    assert len(signer.calls) == 1
    assert signer.calls[0][0] == "head"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ContentLength", 1),
        ("ContentType", "text/plain"),
        ("ServerSideEncryption", "aws:kms"),
    ],
)
def test_v2_rejects_invalid_object_headers(
    monkeypatch, field, value
):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    finding_id = FINDING_IDS[0]
    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    signer.head[field] = value

    with pytest.raises(ValueError):
        issue_grant(signer, finding_id)

    assert len(signer.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("inspection-id", "wrong-inspection"),
        ("finding-id", "wrong-finding"),
        ("sha256", "0" * 64),
        ("purpose", "unapproved"),
    ],
)
def test_v2_rejects_tampered_metadata(
    monkeypatch, field, value
):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    finding_id = FINDING_IDS[0]
    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    signer.head["Metadata"][field] = value

    with pytest.raises(ValueError):
        issue_grant(signer, finding_id)

    assert len(signer.calls) == 1


def test_v2_rejects_unauthorized_finding(monkeypatch):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    finding_id = FINDING_IDS[0]
    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    with pytest.raises(LookupError):
        issue_grant(
            signer,
            finding_id,
            authorized=set(),
        )

    assert signer.calls == []


def test_v2_rejects_wrong_inspection(monkeypatch):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    finding_id = FINDING_IDS[0]
    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    with pytest.raises(LookupError):
        issue_grant(
            signer,
            finding_id,
            inspection_id="wrong-inspection",
        )

    assert signer.calls == []


def test_v2_rejects_unapproved_finding_id(monkeypatch):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    finding_id = "a" * 32
    signer = FakeS3(
        finding_id,
        (100, "0" * 64),
    )

    with pytest.raises(LookupError):
        issue_grant(signer, finding_id)

    assert signer.calls == []


def test_unknown_version_fails_closed(monkeypatch):
    monkeypatch.setattr(
        tv_video,
        "ACTIVE_VIDEO_VERSION",
        "unapproved-version",
    )

    finding_id = FINDING_IDS[0]
    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    with pytest.raises(ValueError):
        issue_grant(signer, finding_id)

    assert signer.calls == []


def test_v2_rejects_wrong_bucket(monkeypatch):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    finding_id = FINDING_IDS[0]
    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    with pytest.raises(ValueError):
        issue_grant(
            signer,
            finding_id,
            bucket="unapproved-bucket",
        )

    assert signer.calls == []


def test_v2_rejects_invalid_storage_prefix(monkeypatch):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    finding_id = FINDING_IDS[0]
    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    with pytest.raises(ValueError):
        issue_grant(
            signer,
            finding_id,
            source="untrusted/location/video.mp4",
        )

    assert signer.calls == []


def test_v2_does_not_download_evidence(monkeypatch):
    monkeypatch.setattr(tv_video, "ACTIVE_VIDEO_VERSION", "v2")

    finding_id = FINDING_IDS[0]
    signer = FakeS3(
        finding_id,
        tv_video.APPROVED_CLIPS_V2[finding_id],
    )

    issue_grant(signer, finding_id)

    operations = [name for name, _ in signer.calls]

    assert operations == ["head", "sign"]
