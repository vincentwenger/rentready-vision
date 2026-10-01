"""Measure Step 36 agentic verification before/after investigation.

Execution receives only candidates.json and the media.  labels.json is loaded
only after every candidate run has completed.  Development sets may be rerun
while tuning.  Challenge sets require a previously created freeze file and the
runner refuses any candidate, label, media, policy, or Step-36 code mismatch.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Callable

from scripts.step36_agentic_verification import (
    ABSENT,
    HUMAN_REVIEW,
    INVESTIGATE,
    POLICY,
    PRESENT,
    RESULT_SCHEMA_VERSION,
    policy_fingerprint,
    route_confidence,
    score_results,
    sha256_file,
    validate_candidates_document,
    validate_labels_document,
)

ROOT = Path(__file__).resolve().parents[1]
ASSESS_TOOL = "assess_step36_candidate"

SYSTEM = (
    "You are a conservative rental-inspection visual evidence reviewer. Judge only the visible condition "
    "described in the candidate. Do not infer hidden damage, mold, electrical safety, structural significance, "
    "repair cost, or code compliance. A high confidence score means the supplied images visibly support the "
    "specific candidate statement; a low score means they visibly contradict it or fail to show it."
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [{
            "toolSpec": {
                "name": ASSESS_TOOL,
                "description": "Return a conservative assessment of whether the visible evidence supports this exact candidate.",
                "inputSchema": {"json": {
                    "type": "object",
                    "properties": {
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "candidate_visible": {"type": "boolean"},
                        "evidence_summary": {"type": "string"},
                    },
                    "required": ["confidence", "candidate_visible", "evidence_summary"],
                }},
            }
        }],
        "toolChoice": {"tool": {"name": ASSESS_TOOL}},
    }


def _extract_assessment(response: dict[str, Any]) -> dict[str, Any]:
    matches = []
    for block in response.get("output", {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if tool_use and tool_use.get("name") == ASSESS_TOOL and isinstance(tool_use.get("input"), dict):
            matches.append(tool_use["input"])
    if len(matches) != 1:
        raise ValueError("Expected exactly one Step 36 assessment tool result")
    payload = matches[0]
    try:
        confidence = float(payload["confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Step 36 assessment confidence must be numeric") from exc
    if not 0 <= confidence <= 1:
        raise ValueError("Step 36 assessment confidence must be between 0 and 1")
    return {
        "confidence": round(confidence, 4),
        "candidate_visible": bool(payload.get("candidate_visible")),
        "evidence_summary": str(payload.get("evidence_summary") or "")[:1000],
        "outcome": route_confidence(confidence),
    }


def _image_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "jpeg"
    if suffix == ".png":
        return "png"
    raise ValueError(f"Unsupported assessment image format: {path}")


def _prompt(candidate: dict[str, Any], phase: str, image_count: int) -> str:
    return (
        f"PHASE={phase}. Review {image_count} image(s) for one fixed candidate. "
        "Do not search for unrelated defects. Candidate: "
        + json.dumps({
            "room": candidate.get("room"),
            "category": candidate.get("category"),
            "description": candidate.get("description"),
            "timestamp": candidate.get("timestamp"),
            "bbox": candidate.get("bbox"),
        }, sort_keys=True)
    )


def bedrock_assessor(client: Any, output_dir: Path) -> Callable[[list[Path], dict[str, Any], str], dict[str, Any]]:
    response_dir = output_dir / "responses"
    response_dir.mkdir(parents=True, exist_ok=True)
    call_index = 0

    def assess(images: list[Path], candidate: dict[str, Any], phase: str) -> dict[str, Any]:
        nonlocal call_index
        if not images:
            raise ValueError("assessment requires at least one image")
        content: list[dict[str, Any]] = [{"text": _prompt(candidate, phase, len(images))}]
        for path in images:
            content.append({"text": f"EVIDENCE_FILE={path.name}"})
            content.append({"image": {"format": _image_format(path), "source": {"bytes": path.read_bytes()}}})
        request = {
            "modelId": POLICY["model_id"],
            "system": [{"text": SYSTEM}],
            "messages": [{"role": "user", "content": content}],
            "inferenceConfig": POLICY["inference"],
            "toolConfig": _tool_config(),
        }
        last_error: Exception | None = None
        for attempt in range(1, int(POLICY["response_max_attempts"]) + 1):
            started = time.perf_counter()
            response = client.converse(**request)
            elapsed = time.perf_counter() - started
            response_path = response_dir / f"{call_index:04d}_{phase}_{attempt}.json"
            _write_json(response_path, response)
            usage = response.get("usage") or {}
            if any(not isinstance(usage.get(name), int) for name in ("inputTokens", "outputTokens")):
                raise ValueError("Bedrock token usage is required for Step 36 auditability")
            try:
                assessment = _extract_assessment(response)
            except ValueError as exc:
                last_error = exc
                if attempt == int(POLICY["response_max_attempts"]):
                    raise
                continue
            call_index += 1
            return {
                **assessment,
                "phase": phase,
                "model_id": POLICY["model_id"],
                "image_count": len(images),
                "image_sha256": [sha256_file(path) for path in images],
                "model_seconds": round(elapsed, 4),
                "usage": usage,
                "response_path": str(response_path.relative_to(output_dir)),
                "response_attempt": attempt,
            }
        raise last_error or RuntimeError("assessment failed")

    return assess


def _read_reference_frame(video: Path, timestamp: float, output: Path) -> Path:
    import cv2
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"OpenCV could not open video: {video}")
        capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000.0)
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"OpenCV could not read candidate timestamp {timestamp}: {video}")
        output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 94]):
            raise RuntimeError(f"OpenCV could not write reference frame: {output}")
        return output
    finally:
        capture.release()


def _distributed_paths(frames: list[dict[str, Any]], budget: int) -> list[Path]:
    if not frames:
        return []
    count = min(len(frames), int(budget))
    if count == 1:
        chosen = [frames[len(frames) // 2]]
    else:
        indices = [round(i * (len(frames) - 1) / (count - 1)) for i in range(count)]
        chosen = [frames[index] for index in indices]
    return [Path(row["local_path"]) for row in chosen]


def _stage(
    steps: list[dict[str, Any]],
    *,
    tool: str,
    confidence_before: float,
    assessment: dict[str, Any] | None,
    status: str = "ok",
    details: dict[str, Any] | None = None,
) -> str:
    if assessment is None:
        outcome = INVESTIGATE
        confidence_after = confidence_before
    else:
        outcome = assessment["outcome"]
        confidence_after = assessment["confidence"]
    steps.append({
        "tool": tool,
        "action": "re-evaluate" if status == "ok" and assessment is not None else "continue",
        "status": status,
        "confidence_before": round(float(confidence_before), 4),
        "confidence_after": round(float(confidence_after), 4),
        "outcome_after": outcome,
        "assessment": assessment,
        "details": details or {},
    })
    return outcome


def execute_candidate(
    candidate: dict[str, Any],
    video: Path,
    output_dir: Path,
    assessor: Callable[[list[Path], dict[str, Any], str], dict[str, Any]],
    *,
    inspect_interval_fn: Callable[..., dict[str, Any]] | None = None,
    crop_region_fn: Callable[..., dict[str, Any]] | None = None,
    other_angle_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one candidate without any access to its ground-truth label."""
    from app.vision.interval_inspector import inspect_interval as default_interval
    from app.vision.region_cropper import write_crop_region as default_crop
    from app.vision.other_angle_inspector import inspect_other_angle as default_other_angle

    inspect_interval_fn = inspect_interval_fn or default_interval
    crop_region_fn = crop_region_fn or default_crop
    other_angle_fn = other_angle_fn or default_other_angle
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    reference = _read_reference_frame(video, candidate["timestamp"], output_dir / "reference.jpg")
    evidence_images: list[Path] = [reference]
    # Step 36 starts from the frozen Step 35 assessment. Do not make a
    # fresh model call before deciding whether agent investigation is needed.
    confidence = float(candidate["source_confidence"])
    initial = {
        "confidence": round(confidence, 4),
        "candidate_visible": None,
        "evidence_summary": "Imported from the frozen Step 35 source finding.",
        "outcome": route_confidence(confidence),
        "phase": "step35_source",
        "model_id": candidate.get("source_model_id"),
        "source_stage": candidate.get("source_stage"),
    }
    steps: list[dict[str, Any]] = []
    outcome = initial["outcome"]

    if outcome == INVESTIGATE:
        # Tool 1: temporal evidence.
        interval_started = time.perf_counter()
        interval = inspect_interval_fn(
            video, output_dir / "inspect_interval",
            timestamp=candidate["timestamp"],
            seconds_before=POLICY["interval"]["seconds_before"],
            seconds_after=POLICY["interval"]["seconds_after"],
            sample_fps=POLICY["interval"]["sample_fps"],
        )
        interval_seconds = time.perf_counter() - interval_started
        interval_paths = _distributed_paths(interval.get("frames") or [], POLICY["interval"]["model_frame_budget"])
        evidence_images.extend(interval_paths)
        interval_assessment = assessor(interval_paths, candidate, "inspect_interval") if interval_paths else None
        outcome = _stage(
            steps, tool="inspect_interval", confidence_before=confidence,
            assessment=interval_assessment,
            details={"returned_frame_count": interval.get("returned_frame_count"),
                     "model_frame_count": len(interval_paths), "opencv_seconds": round(interval_seconds, 4)},
        )
        if interval_assessment is not None:
            confidence = interval_assessment["confidence"]

    if outcome == INVESTIGATE:
        # Tool 2: high-resolution ROI crop on the original evidence frame.
        crop_path = output_dir / "crop_region" / "candidate_crop.jpg"
        crop_started = time.perf_counter()
        crop = crop_region_fn(
            reference, crop_path,
            bounding_box=candidate["bbox"],
            padding=POLICY["crop_region"]["padding"],
            jpeg_quality=POLICY["crop_region"]["jpeg_quality"],
        )
        crop_seconds = time.perf_counter() - crop_started
        crop_path = Path(crop.get("local_path") or crop_path)
        evidence_images.append(crop_path)
        crop_assessment = assessor([crop_path], candidate, "crop_region")
        outcome = _stage(
            steps, tool="crop_region", confidence_before=confidence,
            assessment=crop_assessment,
            details={"opencv_seconds": round(crop_seconds, 4), "crop": crop},
        )
        confidence = crop_assessment["confidence"]

    if outcome == INVESTIGATE:
        # Tool 3: geometrically matched changed viewpoints.  Lack of reliable
        # features is an auditable unavailable result, not a benchmark crash.
        other_started = time.perf_counter()
        try:
            other = other_angle_fn(
                video, output_dir / "other_angle",
                timestamp=candidate["timestamp"],
                bounding_box=candidate["bbox"],
                **POLICY["other_angle"],
            )
        except RuntimeError as exc:
            other_seconds = time.perf_counter() - other_started
            outcome = _stage(
                steps, tool="other_angle_evidence", confidence_before=confidence,
                assessment=None, status="unavailable",
                details={"error": str(exc), "opencv_seconds": round(other_seconds, 4)},
            )
        else:
            other_seconds = time.perf_counter() - other_started
            other_paths = [Path(row["local_region_path"]) for row in other.get("frames") or []]
            evidence_images.extend(other_paths)
            if len(other_paths) >= 2:
                other_assessment = assessor(other_paths, candidate, "other_angle_evidence")
                outcome = _stage(
                    steps, tool="other_angle_evidence", confidence_before=confidence,
                    assessment=other_assessment,
                    details={"selected_frame_count": other.get("selected_frame_count"),
                             "opencv_seconds": round(other_seconds, 4)},
                )
                confidence = other_assessment["confidence"]
            else:
                outcome = _stage(
                    steps, tool="other_angle_evidence", confidence_before=confidence,
                    assessment=None, status="unavailable",
                    details={"selected_frame_count": len(other_paths),
                             "opencv_seconds": round(other_seconds, 4)},
                )

    if outcome == INVESTIGATE:
        # Tool 4: final conservative verification over a bounded, diverse set
        # of collected evidence. This is the last model call before escalation.
        unique: list[Path] = []
        seen = set()
        for path in evidence_images:
            identity = sha256_file(path)
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(path)
        budget = int(POLICY["final_verify_image_budget"])
        if len(unique) > budget:
            indices = [round(i * (len(unique) - 1) / (budget - 1)) for i in range(budget)] if budget > 1 else [0]
            unique = [unique[index] for index in indices]
        verify_assessment = assessor(unique, candidate, "verify")
        outcome = _stage(
            steps, tool="verify", confidence_before=confidence, assessment=verify_assessment,
            details={"evidence_image_count": len(unique)},
        )
        confidence = verify_assessment["confidence"]

    final_outcome = HUMAN_REVIEW if outcome == INVESTIGATE else outcome
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "candidate_id": candidate["candidate_id"],
        "video": candidate["video"],
        "candidate": candidate,
        "initial_assessment": initial,
        "steps": steps,
        "final_assessment": {
            "confidence": round(confidence, 4),
            "outcome": final_outcome,
            "classification": final_outcome if final_outcome in {PRESENT, ABSENT} else None,
        },
        "agent_tool_calls": sum(step.get("tool") in POLICY["tool_order"] for step in steps),
        "policy_re_evaluations": sum(step.get("action") == "re-evaluate" for step in steps),
        "processing_seconds": round(time.perf_counter() - started, 4),
        "policy_sha256": policy_fingerprint(),
    }
    _write_json(output_dir / "candidate_result.json", result)
    return result


def _emit_summary(output: Path, scored: dict[str, Any], *, purpose: str, set_id: str) -> None:
    metrics = scored["metrics"]
    lines = [
        "# Step 36 — Agentic verification measurement",
        "",
        f"Set: `{set_id}` ({purpose})",
        "",
        "| Metric | Result |",
        "|---|---:|",
    ]
    labels = [
        ("Accuracy before agent investigation", "accuracy_before_agent_investigation"),
        ("Accuracy after agent investigation", "accuracy_after_agent_investigation"),
        ("Accuracy delta", "accuracy_delta"),
        ("Ambiguous findings resolved", "ambiguous_findings_resolved_rate"),
        ("Average agent tool calls/candidate", "average_agent_tool_calls"),
        ("Average agent tool calls/investigated candidate", "average_agent_tool_calls_per_investigated_candidate"),
        ("Incorrect escalation rate", "incorrect_escalation_rate"),
        ("Unnecessary tool-call rate", "unnecessary_tool_call_rate"),
        ("Missed finding recovery rate", "missed_finding_recovery_rate"),
        ("Correct rejection rate after investigation", "correct_rejection_rate_after_investigation"),
        ("Policy outcome accuracy after", "policy_outcome_accuracy_after"),
    ]
    for label, key in labels:
        value = metrics.get(key)
        display = "N/A" if value is None else f"{value:.4f}"
        lines.append(f"| {label} | {display} |")
    lines.extend(["", "## Tool attribution", ""])
    for tool, count in scored["corrections_by_decisive_tool"].items():
        lines.append(f"- `{tool}`: {count} correction(s)")
    lines.extend([
        "",
        "Accuracy is candidate-level classification accuracy. An unresolved HUMAN_REVIEW is not counted as a correct "
        "PRESENT/ABSENT classification; `policy_outcome_accuracy_after` separately treats an owner-marked expected human review as correct.",
        "Ground-truth labels were loaded only after all candidate execution outputs existed.",
    ])
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def measure(
    dataset_root: Path,
    candidates_path: Path,
    labels_path: Path,
    output: Path,
    *,
    client: Any,
    freeze_path: Path | None = None,
    assessor_factory: Callable[[Any, Path], Callable] = bedrock_assessor,
) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    candidate_doc = validate_candidates_document(json.loads(candidates_path.read_text(encoding="utf-8-sig")))
    purpose = candidate_doc["purpose"]
    if purpose == "challenge":
        if freeze_path is None:
            raise ValueError("challenge measurement requires --freeze")
        from scripts.freeze_step36_challenge import verify_freeze
        verify_freeze(dataset_root, candidates_path, labels_path, freeze_path)
    elif freeze_path is not None:
        raise ValueError("--freeze is reserved for the challenge measurement")

    # Labels are intentionally not read here.  Candidate execution receives
    # only media + candidate metadata.  Existing completed results can resume.
    output.mkdir(parents=True, exist_ok=True)
    run_context = {
        "set_id": candidate_doc["set_id"],
        "purpose": purpose,
        "policy": POLICY,
        "policy_sha256": policy_fingerprint(),
        "candidates_sha256": sha256_file(candidates_path),
        "media_sha256": {row["video"]: sha256_file(dataset_root / row["video"])
                         for row in candidate_doc["candidates"]},
        "execution_code_sha256": {
            "scripts/step36_agentic_verification.py": sha256_file(ROOT / "scripts" / "step36_agentic_verification.py"),
            "scripts/measure_step36_agentic.py": sha256_file(ROOT / "scripts" / "measure_step36_agentic.py"),
        },
    }
    context_path = output / "run_context.json"
    if context_path.exists() and json.loads(context_path.read_text(encoding="utf-8")) != run_context:
        raise ValueError("Step 36 run context changed; use a new output directory")
    _write_json(context_path, run_context)

    results: list[dict[str, Any]] = []
    for candidate in candidate_doc["candidates"]:
        video = dataset_root / candidate["video"]
        if not video.is_file():
            raise FileNotFoundError(video)
        target = output / "candidates" / candidate["candidate_id"]
        saved = target / "candidate_result.json"
        if saved.is_file():
            result = json.loads(saved.read_text(encoding="utf-8"))
            if result.get("candidate") != candidate or result.get("policy_sha256") != policy_fingerprint():
                raise ValueError(f"saved Step 36 candidate identity changed: {candidate['candidate_id']}")
        else:
            assessor = assessor_factory(client, target)
            result = execute_candidate(candidate, video, target, assessor)
        results.append(result)

    # Only now, after every candidate execution is complete, read labels and score.
    label_doc = validate_labels_document(
        json.loads(labels_path.read_text(encoding="utf-8-sig")),
        set_id=candidate_doc["set_id"],
        candidate_ids=[row["candidate_id"] for row in candidate_doc["candidates"]],
    )
    scored = score_results(results, label_doc)
    final = {
        **scored,
        "set_id": candidate_doc["set_id"],
        "purpose": purpose,
        "policy": POLICY,
        "policy_sha256": policy_fingerprint(),
        "labels_sha256": sha256_file(labels_path),
    }
    _write_json(output / "measurement.json", final)
    _emit_summary(output, final, purpose=purpose, set_id=candidate_doc["set_id"])
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--region", default="us-west-2")
    args = parser.parse_args()
    import boto3
    from botocore.config import Config
    client = boto3.client("bedrock-runtime", region_name=args.region,
                          config=Config(retries={"total_max_attempts": 1}))
    result = measure(args.dataset_root, args.candidates, args.labels, args.output_dir,
                     client=client, freeze_path=args.freeze)
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
