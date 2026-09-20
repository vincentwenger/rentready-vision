from __future__ import annotations

import hashlib
import json
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .aws import bedrock_runtime, s3
from .config import get_settings
from .db import get_inspection, update_inspection
from .processing_jobs import normalize_processing_parameters, processing_parameters
from .runtime_evidence import collect_runtime_evidence
from .telemetry import CloudWatchTelemetry, PeakMemorySampler
from .action_log import ACTION_LOG_VERSION, action_log_document, agent_action
from .agentic_vision import (
    AGENTIC_TRACE_VERSION,
    action_from_confidence,
    reassess_interval_batches,
    reassess_other_angle_evidence,
    verify_candidate_image,
)
from .decision_policy import (
    CALL_CROP_REGION,
    CALL_INSPECT_INTERVAL,
    DECISION_POLICY_VERSION,
    RE_EVALUATE,
    VERIFY_EVIDENCE,
    evaluate_candidate,
    interval_evidence_from_result,
    next_investigation_step,
)
from .vision.issue_detector import REPORT_SCHEMA_VERSION, STRUCTURED_FINDING_VERSION, detect_visible_issues
from .vision.issue_consolidator import CONSOLIDATION_VERSION
from .vision.severity_classifier import (
    SEVERITY_CLASSIFICATION_VERSION,
    classification_summary,
    classify_issues,
)
from .vision.issue_taxonomy import TAXONOMY_VERSION, taxonomy_payload
from .vision.video_processor import process_video
from .vision.interval_inspector import inspect_interval
from .vision.region_cropper import CROP_TRACE_VERSION, write_crop_region
from .vision.region_enhancer import ENHANCE_TRACE_VERSION, write_enhanced_region
from .vision.other_angle_inspector import (
    OTHER_ANGLE_TRACE_VERSION,
    inspect_other_angle,
)

settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]


def _verify_runtime(
    *,
    input_s3_key: str,
    parameters: dict[str, Any],
    require_cool: bool,
) -> dict[str, Any]:
    evidence = collect_runtime_evidence(
        repo_root=ROOT,
        input_s3_key=input_s3_key,
        processing_parameters=parameters,
    )
    errors: list[str] = []
    if not str(evidence.get("opencv_version", "")).startswith("5."):
        errors.append(f"Expected OpenCV 5.x, got {evidence.get('opencv_version')!r}")
    if require_cool:
        if str(evidence.get("architecture", "")).lower() not in {"aarch64", "arm64"}:
            errors.append(f"Expected Graviton Arm64/aarch64, got {evidence.get('architecture')!r}")
        expected = settings.cool_expected_cv2_prefix.rstrip("/") + "/"
        if not str(evidence.get("cv2_path", "")).startswith(expected):
            errors.append(
                f"COOL cv2 must resolve under {settings.cool_expected_cv2_prefix!r}; "
                f"got {evidence.get('cv2_path')!r}"
            )
        if evidence.get("runtime") != "COOL":
            errors.append(f"Expected COOL runtime, got {evidence.get('runtime')!r}")
        for field in ("instance_type", "ami_id", "region"):
            if not evidence.get(field):
                errors.append(f"Missing COOL runtime identity field: {field}")
    evidence["verification"] = {"passed": not errors, "errors": errors}
    if errors:
        raise RuntimeError("COOL runtime verification failed: " + "; ".join(errors))
    return evidence


def execute_processing_job(
    *,
    inspection_id: str,
    source_key: str,
    supplied_parameters: dict[str, Any] | None,
    job_id: str,
    require_cool: bool,
    expected_source_etag: str | None = None,
    telemetry: CloudWatchTelemetry | None = None,
) -> dict[str, Any]:
    """Run one exact, immutable video-processing payload and persist its S3 evidence.

    This function deliberately does not decide retry/final failure state. The SQS
    worker owns that state machine so a transient worker exception cannot silently
    mark a durable job complete or terminally failed.
    """
    parameters = normalize_processing_parameters(supplied_parameters, settings)
    source_head = s3.head_object(Bucket=settings.s3_bucket, Key=source_key)
    observed_etag = str(source_head.get("ETag", "")).strip('"')
    if expected_source_etag and observed_etag != expected_source_etag:
        raise RuntimeError(
            "S3 input changed after enqueue: "
            f"expected ETag {expected_source_etag!r}, observed {observed_etag!r}"
        )
    runtime = _verify_runtime(
        input_s3_key=source_key,
        parameters=parameters,
        require_cool=require_cool,
    )
    if telemetry:
        telemetry.event(
            "COOL_RUNTIME_VERIFIED",
            inspection_id=inspection_id,
            job_id=job_id,
            runtime=runtime.get("runtime"),
            opencv_version=runtime.get("opencv_version"),
            cv2_path=runtime.get("cv2_path"),
            architecture=runtime.get("architecture"),
            instance_type=runtime.get("instance_type"),
            ami_id=runtime.get("ami_id"),
        )

    started = time.perf_counter()
    with PeakMemorySampler() as memory:
        with tempfile.TemporaryDirectory(prefix=f"rentready-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            suffix = Path(source_key).suffix or ".mp4"
            input_path = tmp_path / f"walkthrough{suffix}"
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            s3.download_file(settings.s3_bucket, source_key, str(input_path))
            if telemetry:
                telemetry.event(
                    "OPENCV_STARTED",
                    inspection_id=inspection_id,
                    job_id=job_id,
                    input_s3_key=source_key,
                    runtime=runtime.get("runtime"),
                )

            manifest = process_video(input_path, output_dir, **parameters)
            # Persist the preflight identity so the job proves what runtime was
            # verified before OpenCV execution, including the immutable S3 input.
            manifest["processing"]["runtime"] = runtime

            if telemetry:
                telemetry.event(
                    "KEYFRAMES_SELECTED",
                    inspection_id=inspection_id,
                    job_id=job_id,
                    selected_keyframes=len(manifest["keyframes"]),
                    scene_count=len(manifest["scenes"]),
                )

            prefix = f"inspections/{inspection_id}"
            public_keyframes = []
            for record in manifest["keyframes"]:
                local_path = Path(record["local_path"])
                s3_key = f"{prefix}/frames/{local_path.name}"
                s3.upload_file(
                    str(local_path),
                    settings.s3_bucket,
                    s3_key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
                public_record = {key: value for key, value in record.items() if key != "local_path"}
                public_record["s3_key"] = s3_key
                public_keyframes.append(public_record)

            remote_manifest = {
                "job": {
                    "job_id": job_id,
                    "operation": "analyze_video",
                },
                "video": manifest["video"],
                "processing": manifest["processing"],
                "scenes": manifest["scenes"],
                "keyframes": public_keyframes,
                "frame_assessments": manifest["frame_assessments"],
            }
            manifest_key = f"{prefix}/manifest.json"
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=manifest_key,
                Body=json.dumps(remote_manifest, indent=2).encode("utf-8"),
                ContentType="application/json",
            )

    processing_seconds = max(time.perf_counter() - started, 1e-9)
    total_frames = int(manifest["video"].get("total_frames") or 0)
    telemetry_values = {
        "processing_seconds": round(processing_seconds, 3),
        "frames_per_second": round(total_frames / processing_seconds, 3),
        "peak_memory_mb": round(memory.peak_memory_mb, 3),
    }
    return {
        "manifest_s3_key": manifest_key,
        "video": manifest["video"],
        "processing": manifest["processing"],
        "telemetry": telemetry_values,
    }


def execute_interval_inspection_job(
    *,
    inspection_id: str,
    source_key: str,
    parameters: dict[str, Any],
    agent_context: dict[str, Any],
    job_id: str,
    require_cool: bool,
    expected_source_etag: str | None = None,
    telemetry: CloudWatchTelemetry | None = None,
) -> dict[str, Any]:
    """Execute the Step-18 inspect_interval agent tool on the COOL worker."""
    source_head = s3.head_object(Bucket=settings.s3_bucket, Key=source_key)
    observed_etag = str(source_head.get("ETag", "")).strip('"')
    if expected_source_etag and observed_etag != expected_source_etag:
        raise RuntimeError(
            "S3 input changed after agent tool enqueue: "
            f"expected ETag {expected_source_etag!r}, observed {observed_etag!r}"
        )

    runtime = _verify_runtime(
        input_s3_key=source_key,
        parameters={"tool": "inspect_interval", **parameters},
        require_cool=require_cool,
    )
    confidence_before = float(agent_context.get("confidence_before"))
    if telemetry:
        telemetry.event(
            "AGENT_TOOL_STARTED",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="inspect_interval",
            runtime=runtime.get("runtime"),
            confidence_before=confidence_before,
            timestamp=parameters.get("timestamp"),
            sample_fps=parameters.get("sample_fps"),
        )

    started = time.perf_counter()
    with PeakMemorySampler() as memory:
        with tempfile.TemporaryDirectory(prefix=f"rentready-agent-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            suffix = Path(source_key).suffix or ".mp4"
            input_path = tmp_path / f"walkthrough{suffix}"
            frame_dir = tmp_path / "interval"
            frame_dir.mkdir()
            s3.download_file(settings.s3_bucket, source_key, str(input_path))

            interval = inspect_interval(
                input_path,
                frame_dir,
                timestamp=float(parameters["timestamp"]),
                seconds_before=float(parameters["seconds_before"]),
                seconds_after=float(parameters["seconds_after"]),
                sample_fps=float(parameters["sample_fps"]),
            )
            prefix = f"inspections/{inspection_id}/agentic/{job_id}/interval"
            public_frames: list[dict[str, Any]] = []
            for frame in interval["frames"]:
                local_path = Path(frame["local_path"])
                key = f"{prefix}/{local_path.name}"
                s3.upload_file(
                    str(local_path), settings.s3_bucket, key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
                public = {k: v for k, v in frame.items() if k != "local_path"}
                public["s3_key"] = key
                public_frames.append(public)
            interval["frames"] = public_frames

            if telemetry:
                telemetry.event(
                    "AGENT_TOOL_OPENCV_COMPLETE",
                    inspection_id=inspection_id,
                    job_id=job_id,
                    tool="inspect_interval",
                    runtime=runtime.get("runtime"),
                    returned_frame_count=len(public_frames),
                )

            reassessment = reassess_interval_batches(
                bedrock_client=bedrock_runtime,
                bucket=settings.s3_bucket,
                frames=public_frames,
                candidate=agent_context,
                model_id=settings.issue_detection_model_id,
                max_tokens=min(1000, settings.issue_detection_max_tokens),
                batch_size=15,
            )

    confidence_after = float(reassessment["confidence_after"])
    action = action_from_confidence(
        confidence_after,
        accept_threshold=settings.agentic_accept_threshold,
        dismiss_threshold=settings.agentic_dismiss_threshold,
    )
    elapsed = max(time.perf_counter() - started, 1e-9)
    result = {
        "schema_version": AGENTIC_TRACE_VERSION,
        "inspection_id": inspection_id,
        "job_id": job_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_decision": {
            "reason": "Need additional temporal evidence for an uncertain visual candidate.",
            "tool_call": {
                "name": "inspect_interval",
                "arguments": {k: parameters[k] for k in ("video_id", "timestamp", "seconds_before", "seconds_after", "sample_fps")},
            },
        },
        "candidate": agent_context,
        "runtime": runtime,
        "interval_result": interval,
        "confidence_before": round(confidence_before, 4),
        "confidence_after": round(confidence_after, 4),
        "confidence_delta": round(confidence_after - confidence_before, 4),
        "reassessment": reassessment,
        "action": action,
        "human_control": {
            "required": action == "REQUEST_HUMAN_APPROVAL",
            "reason": "Confidence remains in the configured uncertain band." if action == "REQUEST_HUMAN_APPROVAL" else None,
        },
        "telemetry": {
            "processing_seconds": round(elapsed, 3),
            "peak_memory_mb": round(memory.peak_memory_mb, 3),
            "returned_frame_count": len(public_frames),
        },
    }
    result_key = f"inspections/{inspection_id}/agentic/{job_id}/step18-agentic-trace.json"
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=result_key,
        Body=json.dumps(result, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    if telemetry:
        telemetry.event(
            "AGENT_ACTION_DECIDED",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="inspect_interval",
            runtime=runtime.get("runtime"),
            confidence_before=round(confidence_before, 4),
            confidence_after=round(confidence_after, 4),
            confidence_delta=round(confidence_after - confidence_before, 4),
            action=action,
            result_s3_key=result_key,
        )
    return {"result_s3_key": result_key, "result": result, "telemetry": result["telemetry"]}


def execute_decision_policy_job(
    *,
    inspection_id: str,
    source_key: str,
    parameters: dict[str, Any],
    agent_context: dict[str, Any],
    job_id: str,
    require_cool: bool,
    expected_source_etag: str | None = None,
    telemetry: CloudWatchTelemetry | None = None,
) -> dict[str, Any]:
    """Execute the bounded Step-22 evidence policy on the COOL worker."""
    source_head = s3.head_object(Bucket=settings.s3_bucket, Key=source_key)
    observed_etag = str(source_head.get("ETag", "")).strip('"')
    if expected_source_etag and observed_etag != expected_source_etag:
        raise RuntimeError(
            "S3 input changed after decision-policy enqueue: "
            f"expected ETag {expected_source_etag!r}, observed {observed_etag!r}"
        )
    frame_key = str(parameters["frame_s3_key"])
    frame_head = s3.head_object(Bucket=settings.s3_bucket, Key=frame_key)
    observed_frame_etag = str(frame_head.get("ETag", "")).strip('"')
    expected_frame_etag = str(parameters.get("frame_etag") or "")
    if expected_frame_etag and observed_frame_etag != expected_frame_etag:
        raise RuntimeError(
            "Step-17 frame changed after decision-policy enqueue: "
            f"expected ETag {expected_frame_etag!r}, observed {observed_frame_etag!r}"
        )

    runtime = _verify_runtime(
        input_s3_key=source_key,
        parameters={"tool": "run_decision_policy", **parameters},
        require_cool=require_cool,
    )
    candidate = dict(agent_context)
    confidence_before = float(candidate["confidence"])
    initial_evidence = candidate.get("initial_evidence") if isinstance(candidate.get("initial_evidence"), dict) else {}
    initial_policy = evaluate_candidate(
        candidate,
        evidence=initial_evidence,
        accept_threshold=float(parameters["accept_threshold"]),
        investigate_threshold=float(parameters["investigate_threshold"]),
    )
    if initial_policy["route"] != "INVESTIGATE_CANDIDATE":
        raise RuntimeError("Decision-policy worker received a candidate that does not require investigation")

    if telemetry:
        telemetry.event(
            "DECISION_POLICY_STARTED",
            inspection_id=inspection_id,
            job_id=job_id,
            policy_version=DECISION_POLICY_VERSION,
            confidence_before=confidence_before,
            safety_sensitive=initial_policy["safety_sensitive"],
            next_step=initial_policy["next_step"],
            runtime=runtime.get("runtime"),
        )

    started = time.perf_counter()
    steps: list[dict[str, Any]] = [
        {
            "sequence": 1,
            "stage": "INITIAL_ROUTE",
            "decision": initial_policy,
        }
    ]
    interval_public: dict[str, Any] | None = None
    interval_reassessment: dict[str, Any] | None = None
    crop_public: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    final_evidence = initial_evidence

    with PeakMemorySampler() as memory:
        with tempfile.TemporaryDirectory(prefix=f"rentready-policy-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            next_step = initial_policy["next_step"]
            if next_step == VERIFY_EVIDENCE:
                verification = verify_candidate_image(
                    bedrock_client=bedrock_runtime,
                    bucket=settings.s3_bucket,
                    image_s3_key=frame_key,
                    candidate=candidate,
                    model_id=settings.issue_detection_model_id,
                    evidence_label="Original Step-17 evidence",
                    max_tokens=min(1000, settings.issue_detection_max_tokens),
                )
                confidence_after = float(verification["confidence_after"])
                steps.append(
                    {
                        "sequence": 2,
                        "stage": VERIFY_EVIDENCE,
                        "tool": "verify_candidate_evidence",
                        "result": verification,
                    }
                )
            elif next_step == CALL_INSPECT_INTERVAL:
                suffix = Path(source_key).suffix or ".mp4"
                input_path = tmp_path / f"walkthrough{suffix}"
                interval_dir = tmp_path / "interval"
                interval_dir.mkdir()
                s3.download_file(settings.s3_bucket, source_key, str(input_path))
                interval = inspect_interval(
                    input_path,
                    interval_dir,
                    timestamp=float(parameters["timestamp"]),
                    seconds_before=float(parameters["seconds_before"]),
                    seconds_after=float(parameters["seconds_after"]),
                    sample_fps=float(parameters["sample_fps"]),
                )
                interval_prefix = f"inspections/{inspection_id}/agentic/{job_id}/policy/interval"
                public_frames: list[dict[str, Any]] = []
                for frame in interval["frames"]:
                    local_path = Path(frame["local_path"])
                    key = f"{interval_prefix}/{local_path.name}"
                    s3.upload_file(
                        str(local_path), settings.s3_bucket, key,
                        ExtraArgs={"ContentType": "image/jpeg"},
                    )
                    public = {k: v for k, v in frame.items() if k != "local_path"}
                    public["s3_key"] = key
                    public["sha256"] = hashlib.sha256(local_path.read_bytes()).hexdigest()
                    public_frames.append(public)
                interval["frames"] = public_frames
                interval_public = interval
                if telemetry:
                    telemetry.event(
                        "DECISION_POLICY_TOOL_COMPLETE",
                        inspection_id=inspection_id,
                        job_id=job_id,
                        tool="inspect_interval",
                        returned_frame_count=len(public_frames),
                        runtime=runtime.get("runtime"),
                    )
                interval_reassessment = reassess_interval_batches(
                    bedrock_client=bedrock_runtime,
                    bucket=settings.s3_bucket,
                    frames=public_frames,
                    candidate=candidate,
                    model_id=settings.issue_detection_model_id,
                    max_tokens=min(1000, settings.issue_detection_max_tokens),
                    batch_size=15,
                )
                final_evidence = interval_evidence_from_result(interval, interval_reassessment)
                interval_policy = evaluate_candidate(
                    {**candidate, "confidence": interval_reassessment["confidence_after"]},
                    evidence=final_evidence,
                    inspect_interval_completed=True,
                    accept_threshold=float(parameters["accept_threshold"]),
                    investigate_threshold=float(parameters["investigate_threshold"]),
                )
                # Once investigation has started, evidence sufficiency controls
                # the next tool. A high model score from an interval that did not
                # visibly corroborate the candidate cannot bypass crop_region.
                interval_next_step = next_investigation_step(
                    final_evidence,
                    inspect_interval_completed=True,
                )
                interval_policy["next_step"] = interval_next_step
                if interval_next_step == CALL_CROP_REGION:
                    interval_policy["route"] = "INVESTIGATE_CANDIDATE"
                steps.append(
                    {
                        "sequence": 2,
                        "stage": CALL_INSPECT_INTERVAL,
                        "tool": "inspect_interval",
                        "returned_frame_count": len(public_frames),
                        "reassessment": interval_reassessment,
                        "evidence_assessment": interval_policy["evidence_assessment"],
                        "next_step": interval_next_step,
                    }
                )
                if interval_next_step == CALL_CROP_REGION:
                    frame_path = tmp_path / ("source" + (Path(frame_key).suffix or ".jpg"))
                    crop_path = tmp_path / "policy_crop_1024.jpg"
                    s3.download_file(settings.s3_bucket, frame_key, str(frame_path))
                    crop = write_crop_region(
                        frame_path,
                        crop_path,
                        bounding_box=parameters["bounding_box"],
                        padding=float(parameters["crop_padding"]),
                    )
                    crop_key = f"inspections/{inspection_id}/agentic/{job_id}/policy/crop/crop_1024.jpg"
                    s3.upload_file(
                        str(crop_path), settings.s3_bucket, crop_key,
                        ExtraArgs={"ContentType": "image/jpeg"},
                    )
                    crop_public = {k: v for k, v in crop.items() if k != "local_path"}
                    crop_public["source_sha256"] = hashlib.sha256(frame_path.read_bytes()).hexdigest()
                    crop_public["crop_sha256"] = hashlib.sha256(crop_path.read_bytes()).hexdigest()
                    crop_public["source"]["s3_key"] = frame_key
                    crop_public["source"]["etag"] = observed_frame_etag or None
                    crop_public["output"]["s3_key"] = crop_key
                    verification = verify_candidate_image(
                        bedrock_client=bedrock_runtime,
                        bucket=settings.s3_bucket,
                        image_s3_key=crop_key,
                        candidate=candidate,
                        model_id=settings.issue_detection_model_id,
                        evidence_label="Step-22 cropped inspection view",
                        max_tokens=min(1000, settings.issue_detection_max_tokens),
                    )
                    confidence_after = float(verification["confidence_after"])
                    final_evidence = {
                        "source": "crop_region",
                        "observation_count": 1 if verification["candidate_visible"] else 0,
                        "independent_views": 1 if verification["candidate_visible"] else 0,
                        "quality_score": 1.0 if verification["candidate_visible"] else 0.4,
                        "candidate_visible": verification["candidate_visible"],
                        "multi_view_confirmed": False,
                    }
                    steps.append(
                        {
                            "sequence": 3,
                            "stage": CALL_CROP_REGION,
                            "tool": "crop_region",
                            "crop_result": crop_public,
                            "verification": verification,
                            "next_step": RE_EVALUATE,
                        }
                    )
                    if telemetry:
                        telemetry.event(
                            "DECISION_POLICY_TOOL_COMPLETE",
                            inspection_id=inspection_id,
                            job_id=job_id,
                            tool="crop_region",
                            crop_s3_key=crop_key,
                            runtime=runtime.get("runtime"),
                        )
                else:
                    confidence_after = float(interval_reassessment["confidence_after"])
            else:
                raise RuntimeError(f"Unsupported initial decision-policy step: {next_step!r}")

    final_policy = evaluate_candidate(
        {**candidate, "confidence": confidence_after},
        evidence=final_evidence,
        inspect_interval_completed=interval_public is not None,
        crop_region_completed=crop_public is not None,
        investigation_exhausted=True,
        accept_threshold=float(parameters["accept_threshold"]),
        investigate_threshold=float(parameters["investigate_threshold"]),
    )
    steps.append(
        {
            "sequence": len(steps) + 1,
            "stage": RE_EVALUATE,
            "confidence": round(confidence_after, 4),
            "decision": final_policy,
        }
    )
    elapsed = max(time.perf_counter() - started, 1e-9)
    candidate_id = str(
        candidate.get("policy_candidate_id")
        or candidate.get("issue_id")
        or f"candidate-{job_id}"
    )
    candidate_timestamp = float(parameters["timestamp"])
    actions: list[dict[str, Any]] = [
        agent_action(
            sequence=1,
            candidate_id=candidate_id,
            action="observe_candidate",
            reason=(
                "Initial visual finding entered the investigation band; "
                "additional evidence was required before a terminal decision."
            ),
            input_timestamp=candidate_timestamp,
            frames_returned=1,
            confidence_before=confidence_before,
            confidence_after=confidence_before,
            details={
                "description": candidate.get("description"),
                "category": candidate.get("category"),
                "initial_route": initial_policy["route"],
                "next_step": initial_policy["next_step"],
            },
        )
    ]
    if interval_public is not None and interval_reassessment is not None:
        interval_confidence = float(interval_reassessment["confidence_after"])
        actions.append(
            agent_action(
                sequence=len(actions) + 1,
                candidate_id=candidate_id,
                action="inspect_interval",
                reason=(
                    "Initial confidence was below the automatic acceptance threshold and "
                    "the available evidence did not yet establish temporal persistence."
                ),
                input_timestamp=candidate_timestamp,
                frames_returned=int(interval_public.get("returned_frame_count") or 0),
                confidence_before=confidence_before,
                confidence_after=interval_confidence,
                details={
                    "visible_in_multiple_frames": bool(
                        interval_reassessment.get("visible_in_multiple_frames")
                    ),
                    "requested_seconds_before": float(parameters["seconds_before"]),
                    "requested_seconds_after": float(parameters["seconds_after"]),
                    "sample_fps": float(parameters["sample_fps"]),
                    "next_step": (
                        steps[1].get("next_step") if len(steps) > 1 else None
                    ),
                },
            )
        )
    if crop_public is not None and verification is not None:
        prior_confidence = float(
            (interval_reassessment or {}).get("confidence_after", confidence_before)
        )
        actions.append(
            agent_action(
                sequence=len(actions) + 1,
                candidate_id=candidate_id,
                action="crop_region",
                reason=(
                    "Nearby frames were not sufficient to verify the candidate, so the agent "
                    "requested a close-up ROI while preserving the original evidence."
                ),
                input_timestamp=candidate_timestamp,
                frames_returned=1,
                confidence_before=prior_confidence,
                confidence_after=float(verification["confidence_after"]),
                details={
                    "crop_s3_key": (crop_public.get("output") or {}).get("s3_key"),
                    "candidate_visible": bool(verification.get("candidate_visible")),
                    "original_overwritten": False,
                },
            )
        )
    elif interval_public is None and verification is not None:
        actions.append(
            agent_action(
                sequence=len(actions) + 1,
                candidate_id=candidate_id,
                action="verify_evidence",
                reason="Existing evidence was sufficient for a direct conservative verification.",
                input_timestamp=candidate_timestamp,
                frames_returned=1,
                confidence_before=confidence_before,
                confidence_after=float(verification["confidence_after"]),
                details={"candidate_visible": bool(verification.get("candidate_visible"))},
            )
        )
    actions.append(
        agent_action(
            sequence=len(actions) + 1,
            candidate_id=candidate_id,
            action="final_decision",
            reason=(
                f"The bounded investigation completed and confidence mapped to "
                f"{final_policy['route']}."
            ),
            input_timestamp=candidate_timestamp,
            frames_returned=0,
            confidence_before=confidence_before,
            confidence_after=confidence_after,
            details={
                "result": final_policy["route"],
                "human_review_required": final_policy["route"] == "REQUEST_HUMAN_APPROVAL",
                "safety_override_applied": initial_policy["safety_override_applied"],
            },
        )
    )
    action_log = action_log_document(
        inspection_id=inspection_id,
        job_id=job_id,
        candidate_id=candidate_id,
        actions=actions,
    )
    action_log_key = f"inspections/{inspection_id}/agentic/{job_id}/step23-agent-action-log.json"
    result = {
        "schema_version": DECISION_POLICY_VERSION,
        "inspection_id": inspection_id,
        "job_id": job_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate": candidate,
        "runtime": runtime,
        "thresholds": final_policy["thresholds"],
        "initial_policy": initial_policy,
        "steps": steps,
        "interval_result": interval_public,
        "interval_reassessment": interval_reassessment,
        "crop_result": crop_public,
        "verification": verification,
        "confidence_before": round(confidence_before, 4),
        "confidence_after": round(confidence_after, 4),
        "confidence_delta": round(confidence_after - confidence_before, 4),
        "safety_sensitive": final_policy["safety_sensitive"],
        "safety_override_applied": initial_policy["safety_override_applied"],
        "action": final_policy["route"],
        "final_policy": final_policy,
        "action_log_version": ACTION_LOG_VERSION,
        "action_log_s3_key": action_log_key,
        "action_log": action_log,
        "human_control": {
            "required": final_policy["route"] == "REQUEST_HUMAN_APPROVAL",
            "reason": (
                "Safety-sensitive or unresolved evidence remains after the bounded investigation."
                if final_policy["route"] == "REQUEST_HUMAN_APPROVAL" else None
            ),
        },
        "evidence_preservation": {
            "source_video_s3_key": source_key,
            "source_video_etag": observed_etag or None,
            "source_frame_s3_key": frame_key,
            "source_frame_etag": observed_frame_etag or None,
            "original_overwritten": False,
        },
        "completion_event": "DECISION_POLICY_COMPLETE",
        "telemetry": {
            "processing_seconds": round(elapsed, 3),
            "peak_memory_mb": round(memory.peak_memory_mb, 3),
            "tools_executed": [step.get("tool") for step in steps if step.get("tool")],
        },
    }
    result_key = f"inspections/{inspection_id}/agentic/{job_id}/step22-decision-policy-trace.json"
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=action_log_key,
        Body=json.dumps(action_log, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=result_key,
        Body=json.dumps(result, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    if telemetry:
        telemetry.event(
            "DECISION_POLICY_COMPLETE",
            inspection_id=inspection_id,
            job_id=job_id,
            confidence_before=round(confidence_before, 4),
            confidence_after=round(confidence_after, 4),
            action=final_policy["route"],
            safety_override_applied=initial_policy["safety_override_applied"],
            tools_executed=result["telemetry"]["tools_executed"],
            action_count=action_log["action_count"],
            action_log_s3_key=action_log_key,
            result_s3_key=result_key,
        )
    return {"result_s3_key": result_key, "result": result, "telemetry": result["telemetry"]}


def execute_crop_region_job(
    *,
    inspection_id: str,
    source_key: str,
    parameters: dict[str, Any],
    agent_context: dict[str, Any],
    job_id: str,
    require_cool: bool,
    expected_source_etag: str | None = None,
    telemetry: CloudWatchTelemetry | None = None,
) -> dict[str, Any]:
    """Execute Step-19 Agent Tool 2: crop_region on the COOL/OpenCV worker."""
    frame_s3_key = str(parameters["frame_s3_key"])
    if source_key != frame_s3_key:
        raise RuntimeError("crop_region source key must match frame_s3_key")

    source_head = s3.head_object(Bucket=settings.s3_bucket, Key=frame_s3_key)
    observed_etag = str(source_head.get("ETag", "")).strip('"')
    if expected_source_etag and observed_etag != expected_source_etag:
        raise RuntimeError(
            "S3 frame changed after crop_region enqueue: "
            f"expected ETag {expected_source_etag!r}, observed {observed_etag!r}"
        )

    runtime = _verify_runtime(
        input_s3_key=frame_s3_key,
        parameters={"tool": "crop_region", **parameters},
        require_cool=require_cool,
    )
    if telemetry:
        telemetry.event(
            "AGENT_TOOL_STARTED",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="crop_region",
            runtime=runtime.get("runtime"),
            frame_s3_key=frame_s3_key,
            padding=parameters.get("padding"),
        )

    started = time.perf_counter()
    with PeakMemorySampler() as memory:
        with tempfile.TemporaryDirectory(prefix=f"rentready-crop-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            source_suffix = Path(frame_s3_key).suffix or ".jpg"
            source_path = tmp_path / f"source{source_suffix}"
            crop_path = tmp_path / "crop_1024.jpg"
            s3.download_file(settings.s3_bucket, frame_s3_key, str(source_path))

            crop = write_crop_region(
                source_path,
                crop_path,
                bounding_box=parameters["bounding_box"],
                padding=float(parameters["padding"]),
            )
            crop_key = f"inspections/{inspection_id}/agentic/{job_id}/crop/crop_1024.jpg"
            s3.upload_file(
                str(crop_path),
                settings.s3_bucket,
                crop_key,
                ExtraArgs={"ContentType": "image/jpeg"},
            )

    elapsed = max(time.perf_counter() - started, 1e-9)
    crop_public = {k: v for k, v in crop.items() if k != "local_path"}
    crop_public["source"]["s3_key"] = frame_s3_key
    crop_public["source"]["etag"] = observed_etag or None
    crop_public["output"]["s3_key"] = crop_key

    result = {
        "schema_version": CROP_TRACE_VERSION,
        "inspection_id": inspection_id,
        "job_id": job_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_decision": {
            "reason": "Need a larger, spatially focused view of the candidate region without altering the original frame evidence.",
            "tool_call": {
                "name": "crop_region",
                "arguments": {
                    "frame": frame_s3_key,
                    "bounding_box": parameters["bounding_box"],
                    "padding": float(parameters["padding"]),
                },
            },
        },
        "candidate": agent_context,
        "runtime": runtime,
        "crop_result": crop_public,
        "evidence_preservation": {
            "original_frame_s3_key": frame_s3_key,
            "original_frame_etag": observed_etag or None,
            "original_overwritten": False,
            "derived_crop_s3_key": crop_key,
        },
        "action": "CROP_READY",
        "completion_event": "AGENT_TOOL_COMPLETE",
        "telemetry": {
            "processing_seconds": round(elapsed, 3),
            "peak_memory_mb": round(memory.peak_memory_mb, 3),
            "output_width": crop_public["output"]["width"],
            "output_height": crop_public["output"]["height"],
        },
    }
    result_key = f"inspections/{inspection_id}/agentic/{job_id}/step19-crop-region-trace.json"
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=result_key,
        Body=json.dumps(result, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    if telemetry:
        telemetry.event(
            "AGENT_TOOL_OPENCV_COMPLETE",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="crop_region",
            runtime=runtime.get("runtime"),
            output_width=crop_public["output"]["width"],
            output_height=crop_public["output"]["height"],
            original_frame_s3_key=frame_s3_key,
            crop_s3_key=crop_key,
        )
        telemetry.event(
            "AGENT_TOOL_COMPLETE",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="crop_region",
            runtime=runtime.get("runtime"),
            result_s3_key=result_key,
            crop_s3_key=crop_key,
        )
    return {"result_s3_key": result_key, "result": result, "telemetry": result["telemetry"]}


def execute_enhance_region_job(
    *,
    inspection_id: str,
    source_key: str,
    parameters: dict[str, Any],
    agent_context: dict[str, Any],
    job_id: str,
    require_cool: bool,
    expected_source_etag: str | None = None,
    telemetry: CloudWatchTelemetry | None = None,
) -> dict[str, Any]:
    """Execute Step-20 Agent Tool 3 without replacing original evidence."""
    frame_s3_key = str(parameters["frame_s3_key"])
    if source_key != frame_s3_key:
        raise RuntimeError("enhance_region source key must match frame_s3_key")

    source_head = s3.head_object(Bucket=settings.s3_bucket, Key=frame_s3_key)
    observed_etag = str(source_head.get("ETag", "")).strip('"')
    if expected_source_etag and observed_etag != expected_source_etag:
        raise RuntimeError(
            "S3 frame changed after enhance_region enqueue: "
            f"expected ETag {expected_source_etag!r}, observed {observed_etag!r}"
        )

    runtime = _verify_runtime(
        input_s3_key=frame_s3_key,
        parameters={"tool": "enhance_region", **parameters},
        require_cool=require_cool,
    )
    if telemetry:
        telemetry.event(
            "AGENT_TOOL_STARTED",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="enhance_region",
            runtime=runtime.get("runtime"),
            frame_s3_key=frame_s3_key,
            contrast=parameters.get("contrast"),
            brightness_normalization=parameters.get("brightness_normalization"),
            sharpening=parameters.get("sharpening"),
        )

    started = time.perf_counter()
    with PeakMemorySampler() as memory:
        with tempfile.TemporaryDirectory(prefix=f"rentready-enhance-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            source_suffix = Path(frame_s3_key).suffix or ".jpg"
            source_path = tmp_path / f"original{source_suffix}"
            enhanced_path = tmp_path / "enhanced_inspection_view.jpg"
            s3.download_file(settings.s3_bucket, frame_s3_key, str(source_path))

            enhancement = write_enhanced_region(
                source_path,
                enhanced_path,
                bounding_box=parameters["bounding_box"],
                contrast=float(parameters["contrast"]),
                brightness_normalization=bool(parameters["brightness_normalization"]),
                sharpening=float(parameters["sharpening"]),
            )
            enhanced_key = (
                f"inspections/{inspection_id}/agentic/{job_id}/enhance/"
                "enhanced_inspection_view.jpg"
            )
            s3.upload_file(
                str(enhanced_path),
                settings.s3_bucket,
                enhanced_key,
                ExtraArgs={"ContentType": "image/jpeg"},
            )

    elapsed = max(time.perf_counter() - started, 1e-9)
    enhancement_public = {k: v for k, v in enhancement.items() if k != "local_path"}
    enhancement_public["source"]["s3_key"] = frame_s3_key
    enhancement_public["source"]["etag"] = observed_etag or None
    enhancement_public["output"]["s3_key"] = enhanced_key

    result = {
        "schema_version": ENHANCE_TRACE_VERSION,
        "inspection_id": inspection_id,
        "job_id": job_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_decision": {
            "reason": "Need a clearer inspection view while keeping the original evidence immutable.",
            "tool_call": {
                "name": "enhance_region",
                "arguments": {
                    "frame": frame_s3_key,
                    "bounding_box": parameters["bounding_box"],
                    "contrast": float(parameters["contrast"]),
                    "brightness_normalization": bool(parameters["brightness_normalization"]),
                    "sharpening": float(parameters["sharpening"]),
                },
            },
        },
        "candidate": agent_context,
        "runtime": runtime,
        "enhancement_result": enhancement_public,
        "evidence_preservation": {
            "original_frame_s3_key": frame_s3_key,
            "original_frame_etag": observed_etag or None,
            "original_sha256": enhancement_public["source_sha256"],
            "original_overwritten": False,
            "enhanced_view_s3_key": enhanced_key,
            "enhanced_sha256": enhancement_public["enhanced_sha256"],
            "display_labels": ["Original evidence", "Enhanced inspection view"],
        },
        "action": "ENHANCED_VIEW_READY",
        "completion_event": "AGENT_TOOL_COMPLETE",
        "telemetry": {
            "processing_seconds": round(elapsed, 3),
            "peak_memory_mb": round(memory.peak_memory_mb, 3),
            "output_width": enhancement_public["output"]["width"],
            "output_height": enhancement_public["output"]["height"],
        },
    }
    result_key = f"inspections/{inspection_id}/agentic/{job_id}/step20-enhance-region-trace.json"
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=result_key,
        Body=json.dumps(result, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    if telemetry:
        telemetry.event(
            "AGENT_TOOL_OPENCV_COMPLETE",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="enhance_region",
            runtime=runtime.get("runtime"),
            operations=enhancement_public["operations_applied"],
            original_frame_s3_key=frame_s3_key,
            enhanced_view_s3_key=enhanced_key,
            original_overwritten=False,
        )
        telemetry.event(
            "AGENT_TOOL_COMPLETE",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="enhance_region",
            runtime=runtime.get("runtime"),
            result_s3_key=result_key,
            enhanced_view_s3_key=enhanced_key,
        )
    return {"result_s3_key": result_key, "result": result, "telemetry": result["telemetry"]}


def execute_other_angle_job(
    *,
    inspection_id: str,
    source_key: str,
    parameters: dict[str, Any],
    agent_context: dict[str, Any],
    job_id: str,
    require_cool: bool,
    expected_source_etag: str | None = None,
    telemetry: CloudWatchTelemetry | None = None,
) -> dict[str, Any]:
    """Execute Step-21 Agent Tool 4 and persist auditable multi-view evidence."""
    source_head = s3.head_object(Bucket=settings.s3_bucket, Key=source_key)
    observed_etag = str(source_head.get("ETag", "")).strip('"')
    if expected_source_etag and observed_etag != expected_source_etag:
        raise RuntimeError(
            "S3 video changed after inspect_other_angle enqueue: "
            f"expected ETag {expected_source_etag!r}, observed {observed_etag!r}"
        )

    runtime = _verify_runtime(
        input_s3_key=source_key,
        parameters={"tool": "inspect_other_angle", **parameters},
        require_cool=require_cool,
    )
    confidence_before = float(agent_context.get("confidence_before"))
    if telemetry:
        telemetry.event(
            "AGENT_TOOL_STARTED",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="inspect_other_angle",
            runtime=runtime.get("runtime"),
            timestamp=parameters.get("timestamp"),
            confidence_before=confidence_before,
        )

    started = time.perf_counter()
    with PeakMemorySampler() as memory:
        with tempfile.TemporaryDirectory(prefix=f"rentready-other-angle-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            suffix = Path(source_key).suffix or ".mp4"
            input_path = tmp_path / f"walkthrough{suffix}"
            evidence_dir = tmp_path / "other_angle"
            s3.download_file(settings.s3_bucket, source_key, str(input_path))
            search = inspect_other_angle(
                input_path,
                evidence_dir,
                timestamp=float(parameters["timestamp"]),
                bounding_box=parameters["bounding_box"],
                search_seconds_before=float(parameters["search_seconds_before"]),
                search_seconds_after=float(parameters["search_seconds_after"]),
                sample_every_seconds=float(parameters["sample_every_seconds"]),
                max_results=int(parameters["max_results"]),
                min_viewpoint_change=float(parameters["min_viewpoint_change"]),
            )
            prefix = f"inspections/{inspection_id}/agentic/{job_id}/other-angle"
            public_frames: list[dict[str, Any]] = []
            for frame in search["frames"]:
                local_view = Path(frame["local_view_path"])
                local_region = Path(frame["local_region_path"])
                view_key = f"{prefix}/{local_view.name}"
                region_key = f"{prefix}/{local_region.name}"
                s3.upload_file(
                    str(local_view),
                    settings.s3_bucket,
                    view_key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
                s3.upload_file(
                    str(local_region),
                    settings.s3_bucket,
                    region_key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
                public = {
                    key: value
                    for key, value in frame.items()
                    if key not in {"local_view_path", "local_region_path"}
                }
                public["view_s3_key"] = view_key
                public["region_s3_key"] = region_key
                public_frames.append(public)
            search["frames"] = public_frames

            if telemetry:
                telemetry.event(
                    "AGENT_TOOL_OPENCV_COMPLETE",
                    inspection_id=inspection_id,
                    job_id=job_id,
                    tool="inspect_other_angle",
                    runtime=runtime.get("runtime"),
                    sampled_candidate_count=search["search"]["sampled_candidate_count"],
                    geometrically_matched_count=search["search"]["geometrically_matched_count"],
                    selected_frame_count=len(public_frames),
                )

            if len(public_frames) >= 2:
                assessment = reassess_other_angle_evidence(
                    bedrock_client=bedrock_runtime,
                    bucket=settings.s3_bucket,
                    frames=public_frames,
                    candidate=agent_context,
                    model_id=settings.issue_detection_model_id,
                    max_tokens=min(1000, settings.issue_detection_max_tokens),
                )
            else:
                assessment = {
                    "confidence_after": round(confidence_before, 4),
                    "same_region_or_object": False,
                    "visible_in_multiple_viewpoints": False,
                    "evidence_summary": (
                        "OpenCV did not find enough geometrically verified viewpoint alternatives; "
                        "the finding remains unresolved."
                    ),
                    "bedrock_request_id": None,
                    "usage": None,
                    "metrics": None,
                }

    confidence_after = float(assessment["confidence_after"])
    multi_view_confirmed = bool(
        assessment["same_region_or_object"]
        and assessment["visible_in_multiple_viewpoints"]
        and len(search["frames"]) >= 2
    )
    action = (
        action_from_confidence(
            confidence_after,
            accept_threshold=settings.agentic_accept_threshold,
            dismiss_threshold=settings.agentic_dismiss_threshold,
        )
        if multi_view_confirmed
        else "REQUEST_HUMAN_APPROVAL"
    )
    elapsed = max(time.perf_counter() - started, 1e-9)
    result = {
        "schema_version": OTHER_ANGLE_TRACE_VERSION,
        "inspection_id": inspection_id,
        "job_id": job_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_decision": {
            "reason": "Need nearby camera viewpoints to strengthen or challenge a single-frame finding.",
            "tool_call": {
                "name": "inspect_other_angle",
                "arguments": {
                    key: parameters[key]
                    for key in (
                        "video_id",
                        "timestamp",
                        "bounding_box",
                        "search_seconds_before",
                        "search_seconds_after",
                        "sample_every_seconds",
                        "max_results",
                        "min_viewpoint_change",
                    )
                },
            },
        },
        "candidate": agent_context,
        "runtime": runtime,
        "other_angle_result": search,
        "multi_view_assessment": assessment,
        "multi_view_confirmed": multi_view_confirmed,
        "confidence_before": round(confidence_before, 4),
        "confidence_after": round(confidence_after, 4),
        "confidence_delta": round(confidence_after - confidence_before, 4),
        "evidence_preservation": {
            "original_video_s3_key": source_key,
            "original_video_etag": observed_etag or None,
            "original_overwritten": False,
            "derived_view_s3_keys": [frame["view_s3_key"] for frame in search["frames"]],
            "derived_region_s3_keys": [frame["region_s3_key"] for frame in search["frames"]],
        },
        "action": action,
        "human_control": {
            "required": action == "REQUEST_HUMAN_APPROVAL",
            "reason": (
                "Multiple viewpoints did not conclusively verify the same visible issue."
                if action == "REQUEST_HUMAN_APPROVAL"
                else None
            ),
        },
        "completion_event": "AGENT_ACTION_DECIDED",
        "telemetry": {
            "processing_seconds": round(elapsed, 3),
            "peak_memory_mb": round(memory.peak_memory_mb, 3),
            "sampled_candidate_count": search["search"]["sampled_candidate_count"],
            "geometrically_matched_count": search["search"]["geometrically_matched_count"],
            "selected_frame_count": len(search["frames"]),
        },
    }
    result_key = f"inspections/{inspection_id}/agentic/{job_id}/step21-other-angle-trace.json"
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=result_key,
        Body=json.dumps(result, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    if telemetry:
        telemetry.event(
            "AGENT_ACTION_DECIDED",
            inspection_id=inspection_id,
            job_id=job_id,
            tool="inspect_other_angle",
            runtime=runtime.get("runtime"),
            multi_view_confirmed=multi_view_confirmed,
            confidence_before=round(confidence_before, 4),
            confidence_after=round(confidence_after, 4),
            action=action,
            result_s3_key=result_key,
        )
    return {"result_s3_key": result_key, "result": result, "telemetry": result["telemetry"]}


def run_processing_job(inspection_id: str) -> None:
    """Local developer fallback used when PROCESSING_QUEUE_URL is unset."""
    inspection = get_inspection(inspection_id)
    if not inspection:
        return
    source_key = inspection.get("original_s3_key")
    if not source_key:
        update_inspection(inspection_id, status="FAILED", error="No uploaded video key")
        return

    update_inspection(
        inspection_id,
        status="PROCESSING",
        error=None,
        processing_backend="local_fallback",
    )
    try:
        result = execute_processing_job(
            inspection_id=inspection_id,
            source_key=source_key,
            supplied_parameters=processing_parameters(settings),
            job_id=f"local-{inspection_id}",
            require_cool=False,
            expected_source_etag=inspection.get("s3_etag"),
            telemetry=None,
        )
        update_inspection(
            inspection_id,
            status="COMPLETE",
            manifest_s3_key=result["manifest_s3_key"],
            video=result["video"],
            processing=result["processing"],
            processing_telemetry=result["telemetry"],
        )
    except Exception as exc:
        update_inspection(inspection_id, status="FAILED", error=f"{type(exc).__name__}: {exc}")


def load_manifest(inspection_id: str) -> dict:
    inspection = get_inspection(inspection_id)
    if not inspection:
        raise KeyError(inspection_id)
    manifest_key = inspection.get("manifest_s3_key")
    if not manifest_key:
        raise FileNotFoundError("Manifest is not available yet")
    obj = s3.get_object(Bucket=settings.s3_bucket, Key=manifest_key)
    return json.loads(obj["Body"].read())


def detect_issues_for_inspection(inspection_id: str, *, force: bool = False) -> dict[str, Any]:
    """Run the Step-17 structured candidate detector and persist a judge-readable S3 report.

    This is intentionally a second stage after the frozen OpenCV evidence pipeline, so
    Bedrock latency and model behavior do not alter the Step-12/13 benchmark or the
    Step-14 COOL processing measurements.
    """
    if not settings.issue_detection_enabled:
        raise RuntimeError("Issue detection is disabled by ISSUE_DETECTION_ENABLED=false")

    inspection = get_inspection(inspection_id)
    if not inspection:
        raise KeyError(inspection_id)
    if inspection.get("status") != "COMPLETE":
        raise RuntimeError(
            f"Inspection must be COMPLETE before issue detection; got {inspection.get('status')!r}"
        )

    existing_key = inspection.get("issue_report_s3_key")
    if existing_key and not force:
        obj = s3.get_object(Bucket=settings.s3_bucket, Key=existing_key)
        existing_report = json.loads(obj["Body"].read())
        # Do not silently reuse the older Step-16 schema after Step 17 is deployed.
        if existing_report.get("schema_version") == REPORT_SCHEMA_VERSION:
            return existing_report

    update_inspection(
        inspection_id,
        issue_detection_status="PROCESSING",
        issue_detection_error=None,
        issue_detection_model_id=settings.issue_detection_model_id,
        issue_taxonomy_version=TAXONOMY_VERSION,
        structured_finding_version=STRUCTURED_FINDING_VERSION,
        issue_report_schema_version=REPORT_SCHEMA_VERSION,
    )
    try:
        manifest = load_manifest(inspection_id)
        report = detect_visible_issues(
            bedrock_client=bedrock_runtime,
            bucket=settings.s3_bucket,
            keyframes=manifest.get("keyframes", []),
            model_id=settings.issue_detection_model_id,
            confidence_threshold=settings.issue_detection_confidence_threshold,
            batch_size=settings.issue_detection_batch_size,
            max_keyframes=settings.issue_detection_max_keyframes,
            max_tokens=settings.issue_detection_max_tokens,
            image_loader=lambda key: s3.get_object(
                Bucket=settings.s3_bucket,
                Key=key,
            )["Body"].read(),
        )
        report["inspection_id"] = inspection_id
        report["source_manifest_s3_key"] = inspection.get("manifest_s3_key")
        report_key = f"inspections/{inspection_id}/issues/step25-severity-classified-issues.json"
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=report_key,
            Body=json.dumps(report, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        update_inspection(
            inspection_id,
            issue_detection_status="COMPLETE",
            issue_detection_error=None,
            issue_report_s3_key=report_key,
            issue_count=len(report.get("issues", [])),
            raw_issue_count=len(report.get("raw_issues", [])),
            candidate_finding_count=len(report.get("candidate_findings", [])),
            raw_candidate_finding_count=len(report.get("raw_candidate_findings", [])),
            issue_consolidation_version=CONSOLIDATION_VERSION,
            severity_classification_version=SEVERITY_CLASSIFICATION_VERSION,
            issue_detection_model_id=settings.issue_detection_model_id,
            issue_taxonomy_version=TAXONOMY_VERSION,
            structured_finding_version=STRUCTURED_FINDING_VERSION,
            issue_report_schema_version=REPORT_SCHEMA_VERSION,
            issue_detection_completed_at=report.get("generated_at"),
        )
        return report
    except Exception as exc:
        update_inspection(
            inspection_id,
            issue_detection_status="FAILED",
            issue_detection_error=f"{type(exc).__name__}: {exc}",
        )
        raise


def load_issues_report(inspection_id: str) -> dict[str, Any]:
    inspection = get_inspection(inspection_id)
    if not inspection:
        raise KeyError(inspection_id)
    report_key = inspection.get("issue_report_s3_key")
    if not report_key:
        return {
            "inspection_id": inspection_id,
            "status": inspection.get("issue_detection_status") or "NOT_RUN",
            "taxonomy_version": TAXONOMY_VERSION,
            "structured_finding_version": STRUCTURED_FINDING_VERSION,
            "taxonomy": taxonomy_payload(),
            "detector": None,
            "rooms": [],
            "candidate_findings": [],
            "raw_candidate_findings": [],
            "issues": [],
            "raw_issues": [],
            "severity_classification": classification_summary([]),
            "consolidation": None,
            "report_s3_key": None,
        }
    obj = s3.get_object(Bucket=settings.s3_bucket, Key=report_key)
    report = json.loads(obj["Body"].read())
    issues = report.get("issues", [])
    if any(not issue.get("severity") for issue in issues):
        # Older persisted Step-24 reports remain readable after deployment. The
        # next detector run writes a canonical Step-25 artifact, but GET can
        # classify the already-consolidated visible issues immediately.
        issues = classify_issues(issues)
    severity_classification = (
        report.get("severity_classification") or classification_summary(issues)
    )
    return {
        "inspection_id": inspection_id,
        "status": inspection.get("issue_detection_status") or "COMPLETE",
        "taxonomy_version": report.get("detector", {}).get("taxonomy_version", TAXONOMY_VERSION),
        "structured_finding_version": report.get("structured_finding_version", STRUCTURED_FINDING_VERSION),
        "taxonomy": report.get("taxonomy") or taxonomy_payload(),
        "detector": report.get("detector"),
        "rooms": report.get("rooms", []),
        "candidate_findings": report.get("candidate_findings", []),
        "raw_candidate_findings": report.get("raw_candidate_findings", []),
        "issues": issues,
        "raw_issues": report.get("raw_issues", []),
        "severity_classification": severity_classification,
        "consolidation": report.get("consolidation"),
        "report_s3_key": report_key,
    }
