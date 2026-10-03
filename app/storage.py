"""Inspection storage paths, independent of AWS clients and local filenames."""
from __future__ import annotations

import hashlib
import re
from typing import Any

VIDEO_TAG = {"Key": "rentready-artifact", "Value": "original-video"}
VIDEO_TAGGING = "rentready-artifact=original-video"


def segment(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(value)):
        raise ValueError("Storage path identifiers must be single safe segments")
    return str(value)


def inspection_prefix(inspection_id: str, *stored_keys: str | None) -> str:
    """Continue writing legacy inspections in place; new ones use rentready/."""
    identity = segment(inspection_id)
    for key in stored_keys:
        if key:
            for base in ("rentready/inspections", "inspections"):
                prefix = f"{base}/{identity}"
                if key.startswith(prefix + "/"):
                    return prefix
            raise ValueError("Stored S3 key does not belong to this inspection")
    return f"rentready/inspections/{identity}"


def prefix_for_record(inspection_id: str, record: dict[str, Any]) -> str:
    return inspection_prefix(
        inspection_id, record.get("original_s3_key"), record.get("manifest_s3_key"),
        record.get("issue_report_s3_key"),
    )


def issue_segment(context: dict[str, Any], job_id: str) -> str:
    value = str(context.get("policy_candidate_id") or context.get("issue_id") or f"candidate-{job_id}")
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return "issue-" + hashlib.sha256(value.encode()).hexdigest()[:24]


def artifact_key(prefix: str, relative: str, *, context: dict[str, Any] | None = None) -> str:
    """Map new agent artifacts into evidence/crops/reports; keep legacy paths."""
    if prefix.startswith("inspections/") or not relative.startswith("agentic/"):
        return f"{prefix}/{relative}"
    _, job_id, tail = relative.split("/", 2)
    segment(job_id)
    issue = issue_segment(context or {}, job_id)
    if tail.endswith(".json"):
        return f"{prefix}/reports/agentic/{job_id}/{tail}"
    if "/crop/" in f"/{tail}" or tail.startswith("crop/"):
        return f"{prefix}/crops/{issue}/{job_id}/{tail}"
    return f"{prefix}/evidence/{issue}/{job_id}/{tail}"


def report_key(prefix: str) -> str:
    if prefix.startswith("inspections/"):
        return f"{prefix}/issues/step25-severity-classified-issues.json"
    return f"{prefix}/reports/report.json"


def keyframe_name(record: dict[str, Any], per_scene: dict[int, int]) -> str:
    scene = int(record["scene_index"])
    per_scene[scene] = per_scene.get(scene, 0) + 1
    return f"scene-{scene + 1:03d}-frame-{per_scene[scene]:02d}.jpg"


def preserve_issue_evidence(client: Any, bucket: str, prefix: str, report: dict[str, Any]) -> None:
    """Snapshot supporting frames so reports remain useful after video expiry."""
    for issue in report.get("issues", []):
        issue_id = issue_segment(issue, "unknown")
        entries = list(issue.get("supporting_evidence") or [])
        if isinstance(issue.get("evidence"), dict):
            entries.insert(0, issue["evidence"])
        preserved, seen = [], set()
        for entry in entries:
            source = entry.get("s3_key")
            if not source or source in seen:
                continue
            if not source.startswith(prefix + "/"):
                raise ValueError("Issue evidence must belong to its inspection")
            seen.add(source)
            destination = f"{prefix}/evidence/{issue_id}/frame-{len(preserved) + 1:02d}.jpg"
            client.copy_object(
                Bucket=bucket, Key=destination,
                CopySource={"Bucket": bucket, "Key": source},
                TaggingDirective="REPLACE", Tagging="rentready-artifact=evidence",
                MetadataDirective="COPY",
            )
            preserved.append({**entry, "source_s3_key": source, "s3_key": destination})
        issue["preserved_evidence"] = preserved
