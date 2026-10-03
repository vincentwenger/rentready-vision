from __future__ import annotations

import io
import json
import os
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

from app.s3_lifecycle import lifecycle_rules, merge_lifecycle, read_lifecycle, retention_conflicts, write_lifecycle
from app.storage import VIDEO_TAG, VIDEO_TAGGING, artifact_key, inspection_prefix, keyframe_name, preserve_issue_evidence
from app.storage_config import StorageSettings
from scripts.configure_s3_lifecycle import original_video, tag_video_version, video_versions


def test_video_retention_never_matches_reports_frames_crops_or_evidence():
    rules = lifecycle_rules(video_days=45, noncurrent_days=15, multipart_days=3)
    for prefix in ("rentready/inspections/", "inspections/"):
        expiration = next(r for r in rules if r.get("Filter", {}).get("And", {}).get("Prefix") == prefix)
        assert expiration["Filter"]["And"]["Tags"] == [VIDEO_TAG]
        assert expiration["Expiration"] == {"Days": 45}
        assert expiration["NoncurrentVersionExpiration"] == {"NoncurrentDays": 15}
    # Abort/marker actions must be prefix-only (S3 does not permit tag filters).
    for rule in rules:
        if "And" not in rule["Filter"]:
            assert set(rule["Filter"]) == {"Prefix"}
            assert "Days" not in rule.get("Expiration", {})


def test_merge_preserves_unrelated_rules_and_disables_previous_broad_expiry():
    unrelated = {"ID": "keep-evaluation", "Status": "Enabled", "Filter": {"Prefix": "evaluation-datasets/"}, "Expiration": {"Days": 365}}
    broad = {"ID": "expire-prototype-video", "Status": "Enabled", "Filter": {"Prefix": "inspections/"}, "Expiration": {"Days": 30}}
    old = {"Rules": [unrelated, broad], "TransitionDefaultMinimumObjectSize": "all_storage_classes_128K"}
    merged = merge_lifecycle(old)
    assert old["Rules"][1]["Status"] == "Enabled"
    assert merged["Rules"][0] == unrelated
    assert merged["Rules"][1]["Status"] == "Disabled"
    assert merged["TransitionDefaultMinimumObjectSize"] == old["TransitionDefaultMinimumObjectSize"]
    assert merge_lifecycle(merged) == merged
    assert not retention_conflicts(merged)


def test_unknown_overlapping_expiration_is_rejected_before_writing():
    merged = merge_lifecycle({"Rules": [{"ID": "unknown-broad", "Status": "Enabled", "Filter": {"Prefix": ""}, "Expiration": {"Days": 1}}]})
    assert retention_conflicts(merged) == ["unknown-broad"]
    class NoWrites:
        def put_bucket_lifecycle_configuration(self, **kwargs):
            pytest.fail("Must not write overlapping expiry")
    with pytest.raises(RuntimeError, match="unknown-broad"):
        write_lifecycle(NoWrites(), "test-bucket", merged)


def test_s3_request_shapes_pass_botocore_validation_and_access_denied_is_not_swallowed():
    client = boto3.client("s3", region_name="us-west-2", aws_access_key_id="test", aws_secret_access_key="test")
    configuration = merge_lifecycle({"Rules": []})
    with Stubber(client) as stub:
        stub.add_client_error("get_bucket_lifecycle_configuration", "NoSuchLifecycleConfiguration", expected_params={"Bucket": "test-bucket"})
        assert read_lifecycle(client, "test-bucket") == {"Rules": []}
        stub.add_response("put_bucket_lifecycle_configuration", {}, {"Bucket": "test-bucket", "LifecycleConfiguration": configuration})
        write_lifecycle(client, "test-bucket", configuration)
        stub.add_client_error("get_bucket_lifecycle_configuration", "AccessDenied", expected_params={"Bucket": "test-bucket"})
        with pytest.raises(ClientError):
            read_lifecycle(client, "test-bucket")


@pytest.mark.parametrize("days", [0, -1, True, 1.2])
def test_invalid_retention_is_rejected(days):
    with pytest.raises(ValueError):
        lifecycle_rules(video_days=days)
    if days in (0, -1):
        with pytest.raises(ValueError):
            StorageSettings(s3_video_retention_days=days)


def test_namespace_isolation_and_legacy_paths():
    assert inspection_prefix("id") == "rentready/inspections/id"
    assert inspection_prefix("id", "inspections/id/frames/a.jpg") == "inspections/id"
    with pytest.raises(ValueError):
        inspection_prefix("id", "rentready/inspections/other/original/walkthrough.mp4")
    with pytest.raises(ValueError):
        inspection_prefix("../id")
    current = inspection_prefix("id")
    assert artifact_key(current, "agentic/job/crop/crop_1024.jpg", context={"issue_id": "issue-001"}) == "rentready/inspections/id/crops/issue-001/job/crop/crop_1024.jpg"
    assert artifact_key(current, "agentic/job/interval/frame.jpg", context={"issue_id": "issue-001"}) == "rentready/inspections/id/evidence/issue-001/job/interval/frame.jpg"
    assert artifact_key(current, "agentic/job/trace.json") == "rentready/inspections/id/reports/agentic/job/trace.json"
    assert artifact_key("inspections/id", "agentic/job/trace.json") == "inspections/id/agentic/job/trace.json"


def test_scene_names_are_unique_and_do_not_rename_local_files():
    counts = {}
    assert keyframe_name({"scene_index": 0}, counts) == "scene-001-frame-01.jpg"
    assert keyframe_name({"scene_index": 0}, counts) == "scene-001-frame-02.jpg"
    assert keyframe_name({"scene_index": 1}, counts) == "scene-002-frame-01.jpg"


def test_evidence_copies_preserve_associations_and_do_not_inherit_video_tags():
    copied = []
    class S3:
        def copy_object(self, **kwargs): copied.append(kwargs)
    prefix = inspection_prefix("id")
    source = prefix + "/frames/scene-001-frame-01.jpg"
    report = {"issues": [{"issue_id": "issue-001", "confidence": 0.8, "evidence": {"s3_key": source, "timestamp": 1}, "supporting_evidence": [{"s3_key": source}, {"s3_key": prefix + "/frames/scene-001-frame-02.jpg", "timestamp": 2}]}]}
    preserve_issue_evidence(S3(), "bucket", prefix, report)
    assert len(copied) == 2
    assert copied[0]["Key"] == prefix + "/evidence/issue-001/frame-01.jpg"
    assert copied[0]["TaggingDirective"] == "REPLACE"
    assert copied[0]["Tagging"] == "rentready-artifact=evidence"
    assert report["issues"][0]["evidence"]["s3_key"] == source
    assert report["issues"][0]["confidence"] == 0.8
    assert report["issues"][0]["preserved_evidence"][1]["timestamp"] == 2
    report["issues"][0]["evidence"]["s3_key"] = "inspections/other/frame.jpg"
    with pytest.raises(ValueError):
        preserve_issue_evidence(S3(), "bucket", prefix, report)


def test_existing_video_selection_excludes_datasets_reports_and_unknown_objects():
    assert original_video("rentready/inspections/id/original/walkthrough.mp4")
    assert original_video("inspections/id/original/walkthrough.mov")
    for key in ("evaluation-datasets/v2/walkthrough.mp4", "inspections/id/frames/video.mp4", "inspections/id/original/other.mp4", "inspections/id/original/nested/walkthrough.mp4"):
        assert not original_video(key)


def test_existing_versions_are_paginated_and_preserve_other_tags():
    calls = []
    class Paginator:
        def paginate(self, **kwargs):
            yield {"Versions": [{"Key": kwargs["Prefix"] + "id/original/walkthrough.mp4", "VersionId": "v1"}]}
            yield {"Versions": [{"Key": kwargs["Prefix"] + "id/frames/frame.jpg", "VersionId": "v2"}], "DeleteMarkers": [{"Key": "ignored"}]}
    class S3:
        def get_paginator(self, name): assert name == "list_object_versions"; return Paginator()
        def get_object_tagging(self, **kwargs): return {"TagSet": [{"Key": "owner", "Value": "user"}]}
        def put_object_tagging(self, **kwargs): calls.append(kwargs)
    versions = video_versions(S3(), "bucket")
    assert len(versions) == 2
    tag_video_version(S3(), "bucket", versions[0])
    assert calls[0]["VersionId"] == "v1"
    assert calls[0]["Tagging"]["TagSet"] == [{"Key": "owner", "Value": "user"}, VIDEO_TAG]


@pytest.mark.parametrize("legacy", [False, True])
def test_upload_signs_video_tag_and_upload_complete_tags_exact_version(monkeypatch, legacy):
    from app.models import CreateUploadUrlRequest, UploadCompleteRequest
    from app.routers import inspections as routes
    item = {"inspection_id": "id", "purpose": "rental_prep", "status": "CREATED", "created_at": "now", "updated_at": "now"}
    prefix = "inspections/id" if legacy else "rentready/inspections/id"
    if legacy:
        item["original_s3_key"] = prefix + "/original/walkthrough.mov"
    calls = []
    class S3:
        def generate_presigned_url(self, **kwargs): calls.append(kwargs); return "https://example.test/upload"
        def head_object(self, **kwargs): return {"ContentLength": 123, "ETag": '"abc"', "VersionId": "video-v1"}
        def get_object_tagging(self, **kwargs): assert kwargs["VersionId"] == "video-v1"; return {"TagSet": [{"Key": "owner", "Value": "user"}]}
        def put_object_tagging(self, **kwargs): calls.append(kwargs)
    monkeypatch.setattr(routes, "s3", S3())
    monkeypatch.setattr(routes, "_require_inspection", lambda _: item)
    def update(_, **changes): item.update(changes); return item
    monkeypatch.setattr(routes, "update_inspection", update)
    result = routes.create_upload_url("id", CreateUploadUrlRequest(filename="tour.mov", content_type="video/quicktime"))
    assert result.s3_key == prefix + "/original/walkthrough.mov"
    assert result.required_headers["x-amz-tagging"] == VIDEO_TAGGING
    assert calls[0]["Params"]["Tagging"] == VIDEO_TAGGING
    routes.upload_complete("id", UploadCompleteRequest(filename="tour.mov", content_type="video/quicktime"))
    assert calls[-1]["VersionId"] == "video-v1"
    assert calls[-1]["Tagging"]["TagSet"] == [{"Key": "owner", "Value": "user"}, VIDEO_TAG]


def test_expired_video_returns_410_while_report_is_still_readable(monkeypatch):
    from app.routers import inspections as routes
    from fastapi import HTTPException
    monkeypatch.setattr(routes, "_require_inspection", lambda _: {"original_s3_key": "rentready/inspections/id/original/walkthrough.mp4"})
    def gone(**kwargs): raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
    monkeypatch.setattr(routes.s3, "head_object", gone)
    with pytest.raises(HTTPException) as exc:
        routes.get_video_url("id")
    assert exc.value.status_code == 410


def test_new_report_is_persisted_with_evidence_but_legacy_cached_reports_stay_readable(monkeypatch):
    from app import services
    from app.vision.issue_detector import REPORT_SCHEMA_VERSION
    prefix = inspection_prefix("id")
    item = {"inspection_id": "id", "status": "COMPLETE", "original_s3_key": prefix + "/original/walkthrough.mp4", "manifest_s3_key": prefix + "/reports/manifest.json"}
    puts, copies = [], []
    report = {"schema_version": REPORT_SCHEMA_VERSION, "issues": [{"issue_id": "issue-001", "evidence": {"s3_key": prefix + "/frames/scene-001-frame-01.jpg"}}]}
    class S3:
        def copy_object(self, **kwargs): copies.append(kwargs)
        def put_object(self, **kwargs): puts.append(kwargs)
        def get_object(self, **kwargs): return {"Body": io.BytesIO(json.dumps(report).encode())}
    monkeypatch.setattr(services, "s3", S3())
    monkeypatch.setattr(services, "get_inspection", lambda _: item)
    monkeypatch.setattr(services, "load_manifest", lambda _: {"keyframes": []})
    monkeypatch.setattr(services, "detect_visible_issues", lambda **_: report)
    monkeypatch.setattr(services, "update_inspection", lambda _, **changes: item.update(changes))
    result = services.detect_issues_for_inspection("id")
    assert puts[0]["Key"] == prefix + "/reports/report.json"
    assert result["issues"][0]["preserved_evidence"][0]["s3_key"] == copies[0]["Key"]
    assert item["issue_report_s3_key"] == prefix + "/reports/report.json"
    assert services.load_issues_report("id")["report_s3_key"] == prefix + "/reports/report.json"


def test_new_processing_writes_scene_frames_and_manifest_in_reports(monkeypatch, tmp_path):
    from app import services
    files = []
    for index in range(3):
        path = tmp_path / f"local-{index}.jpg"
        path.write_bytes(b"fake-jpeg")
        files.append({"local_path": str(path), "index": index, "scene_index": index // 2})
    uploads, puts = [], []
    class S3:
        def head_object(self, **kwargs): return {"ETag": '"abc"'}
        def download_file(self, *args): Path(args[2]).write_bytes(b"video")
        def upload_file(self, *args, **kwargs): uploads.append(args[2])
        def put_object(self, **kwargs): puts.append(kwargs)
    monkeypatch.setattr(services, "s3", S3())
    monkeypatch.setattr(services, "_verify_runtime", lambda **_: {"runtime": "test"})
    monkeypatch.setattr(services, "process_video", lambda *args, **kwargs: {"processing": {}, "video": {"total_frames": 3}, "keyframes": files, "scenes": [], "frame_assessments": []})
    result = services.execute_processing_job(inspection_id="id", source_key=inspection_prefix("id") + "/original/walkthrough.mp4", supplied_parameters=None, job_id="job", require_cool=False)
    assert uploads == [inspection_prefix("id") + "/frames/" + name for name in ["scene-001-frame-01.jpg", "scene-001-frame-02.jpg", "scene-002-frame-01.jpg"]]
    assert result["manifest_s3_key"] == inspection_prefix("id") + "/reports/manifest.json"
    saved = json.loads(puts[0]["Body"])
    assert saved["keyframes"][0]["s3_key"] == uploads[0]
    assert "local_path" not in saved["keyframes"][0]
