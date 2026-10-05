"""Step 42B-2 temporal verification of saved 42B-1 raw candidates.

This experiment does NOT rerun candidate generation and does NOT read
ground-truth annotations. Each saved candidate is independently verified
against up to five nearby OpenCV-selected keyframes from the same clip.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PROFILE = "detector_v3_temporal_verification_v1/1.0"
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
TOOL_NAME = "verify_temporal_candidate"

AUTO_ACCEPT_CONFIDENCE = 0.80
AUTO_REJECT_CONFIDENCE = 0.45
MAX_EVIDENCE_FRAMES = 5


SYSTEM = """You are a conservative rental-condition visual evidence verifier.

Review only the supplied candidate and images.

Verify the EXACT described physical condition, not merely a related condition
in the same area.

Reject unsupported interpretations of normal material variation, wood grain,
knots, shadows, glare, reflections, clean seams, texture, normal fasteners,
and ordinary wear that is not visibly the claimed condition.

For motion-dependent claims such as a falling droplet, dripping faucet, or
active leak, require visible evidence of that claimed motion or condition.

For static physical damage such as a crack, hole, unfinished patch, chipped
finish, or missing mounting point, one clearly supporting frame may be enough.
Persistence across multiple frames is supporting evidence but is not required.

Do not use detector confidence as proof. Judge only the supplied visual
evidence."""


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": (
                        "Verify whether the supplied temporal visual evidence "
                        "supports the exact rental-condition candidate."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "exact_condition_supported": {
                                    "type": "boolean"
                                },
                                "visible_in_multiple_frames": {
                                    "type": "boolean"
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1
                                },
                                "evidence_summary": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "exact_condition_supported",
                                "visible_in_multiple_frames",
                                "confidence",
                                "evidence_summary"
                            ]
                        }
                    }
                }
            }
        ],
        "toolChoice": {
            "tool": {
                "name": TOOL_NAME
            }
        }
    }


def _extract_tool_result(response: dict[str, Any]) -> dict[str, Any]:
    for block in response.get("output", {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if tool_use and tool_use.get("name") == TOOL_NAME:
            payload = tool_use.get("input")
            if isinstance(payload, dict):
                return payload

    raise RuntimeError(
        f"Bedrock response did not contain {TOOL_NAME!r}"
    )


def _candidate_fingerprint(
    video: str,
    candidate: dict[str, Any],
) -> str:
    payload = {
        "video": video,
        "timestamp": candidate.get("timestamp"),
        "room": candidate.get("room"),
        "category": candidate.get("category"),
        "description": candidate.get("description"),
        "confidence": candidate.get("confidence"),
        "bbox": candidate.get("bbox"),
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def _decision(
    *,
    exact_condition_supported: bool,
    confidence: float,
) -> str:
    if not exact_condition_supported:
        return "REJECT"

    if confidence >= AUTO_ACCEPT_CONFIDENCE:
        return "ACCEPT"

    if confidence < AUTO_REJECT_CONFIDENCE:
        return "REJECT"

    return "HUMAN_REVIEW"


def _evidence_frames(
    manifest: dict[str, Any],
    candidate_timestamp: float,
) -> list[dict[str, Any]]:
    frames = list(manifest.get("keyframes") or [])

    frames.sort(
        key=lambda frame: (
            abs(
                float(frame["timestamp_seconds"])
                - candidate_timestamp
            ),
            float(frame["timestamp_seconds"]),
        )
    )

    chosen = frames[:MAX_EVIDENCE_FRAMES]

    return sorted(
        chosen,
        key=lambda frame: float(frame["timestamp_seconds"]),
    )


def _verify_candidate(
    *,
    client: Any,
    video_name: str,
    candidate: dict[str, Any],
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    if not frames:
        raise ValueError("No evidence frames available")

    candidate_summary = {
        "video": video_name,
        "timestamp": candidate.get("timestamp"),
        "room": candidate.get("room"),
        "category": candidate.get("category"),
        "description": candidate.get("description"),
        "detector_confidence": candidate.get("confidence"),
        "bbox": candidate.get("bbox"),
    }

    content: list[dict[str, Any]] = [
        {
            "text": (
                "Independently verify this candidate against the supplied "
                "temporal evidence. Candidate:\n"
                + json.dumps(
                    candidate_summary,
                    sort_keys=True,
                )
            )
        }
    ]

    evidence_manifest = []

    for index, frame in enumerate(frames, start=1):
        local_path = Path(frame["local_path"])

        if not local_path.is_file():
            raise FileNotFoundError(local_path)

        timestamp = float(frame["timestamp_seconds"])

        content.append(
            {
                "text": (
                    f"EVIDENCE_FRAME={index}; "
                    f"TIMESTAMP_SECONDS={timestamp:.3f}; "
                    f"SELECTION_REASON={frame.get('selection_reason')}; "
                    f"EVIDENCE_QUALITY={frame.get('evidence_quality_score')}"
                )
            }
        )

        content.append(
            {
                "image": {
                    "format": "jpeg",
                    "source": {
                        "bytes": local_path.read_bytes()
                    }
                }
            }
        )

        evidence_manifest.append(
            {
                "index": index,
                "timestamp_seconds": timestamp,
                "local_path": str(local_path),
                "selection_reason": frame.get("selection_reason"),
                "evidence_quality_score": frame.get(
                    "evidence_quality_score"
                ),
            }
        )

    response = client.converse(
        modelId=MODEL_ID,
        system=[
            {
                "text": SYSTEM
            }
        ],
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
        inferenceConfig={
            "maxTokens": 800,
            "temperature": 0,
        },
        toolConfig=_tool_config(),
    )

    payload = _extract_tool_result(response)

    confidence = max(
        0.0,
        min(
            1.0,
            float(payload.get("confidence", 0.0)),
        ),
    )

    supported = bool(
        payload.get("exact_condition_supported")
    )

    decision = _decision(
        exact_condition_supported=supported,
        confidence=confidence,
    )

    return {
        "candidate": candidate_summary,
        "candidate_fingerprint": _candidate_fingerprint(
            video_name,
            candidate,
        ),
        "evidence_frames": evidence_manifest,
        "verification": {
            "exact_condition_supported": supported,
            "visible_in_multiple_frames": bool(
                payload.get("visible_in_multiple_frames")
            ),
            "confidence": round(confidence, 4),
            "evidence_summary": str(
                payload.get("evidence_summary") or ""
            )[:1200],
            "decision": decision,
        },
        "model": {
            "model_id": MODEL_ID,
            "usage": response.get("usage") or {},
            "metrics": response.get("metrics") or {},
            "request_id": (
                response.get("ResponseMetadata") or {}
            ).get("RequestId"),
        },
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    source_root = args.source_root.resolve()
    manifest_root = args.manifest_root.resolve()
    output = args.output_dir.resolve()

    if not source_root.is_dir():
        raise FileNotFoundError(source_root)

    if not manifest_root.is_dir():
        raise FileNotFoundError(manifest_root)

    output.mkdir(parents=True, exist_ok=True)

    candidates: list[dict[str, Any]] = []

    for clip_dir in sorted(source_root.iterdir()):
        if not clip_dir.is_dir():
            continue

        report_path = clip_dir / "detector_report.json"

        if not report_path.is_file():
            continue

        report = json.loads(
            report_path.read_text(encoding="utf-8")
        )

        for issue_index, issue in enumerate(
            report.get("issues") or [],
            start=1,
        ):
            candidates.append(
                {
                    "video": report.get(
                        "detector",
                        {},
                    ).get("video")
                    or f"{clip_dir.name}.mp4",
                    "stem": clip_dir.name,
                    "issue_index": issue_index,
                    "issue": issue,
                }
            )

    if len(candidates) != 6:
        raise ValueError(
            f"Expected exactly 6 saved 42B-1 raw observations, "
            f"found {len(candidates)}"
        )

    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
    )

    results = []

    for index, item in enumerate(candidates, start=1):
        issue = item["issue"]
        stem = item["stem"]

        manifest_path = (
            manifest_root
            / stem
            / "manifest.local.json"
        )

        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)

        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        timestamp = float(
            issue.get("timestamp") or 0.0
        )

        frames = _evidence_frames(
            manifest,
            timestamp,
        )

        fingerprint = _candidate_fingerprint(
            item["video"],
            issue,
        )

        result_path = output / (
            f"{index:02d}_{stem}_{fingerprint[:10]}.json"
        )

        if result_path.is_file():
            saved = json.loads(
                result_path.read_text(encoding="utf-8")
            )

            if saved.get("candidate_fingerprint") != fingerprint:
                raise ValueError(
                    f"Incompatible saved verification: {result_path}"
                )

            result = saved

            print(
                f"[{index}/6] RESUME {stem} "
                f"t={timestamp:.3f} "
                f"decision={result['verification']['decision']}",
                flush=True,
            )

        else:
            print(
                f"[{index}/6] VERIFY {stem} "
                f"t={timestamp:.3f} "
                f"{issue.get('category')} "
                f"conf={issue.get('confidence')}",
                flush=True,
            )

            result = _verify_candidate(
                client=client,
                video_name=item["video"],
                candidate=issue,
                frames=frames,
            )

            result_path.write_text(
                json.dumps(result, indent=2),
                encoding="utf-8",
            )

            print(
                f"[{index}/6] RESULT "
                f"{result['verification']['decision']} "
                f"supported="
                f"{result['verification']['exact_condition_supported']} "
                f"confidence="
                f"{result['verification']['confidence']}",
                flush=True,
            )

        results.append(result)

    summary = {
        "schema_version": "rentready-step42b2-verification-run/1.0",
        "profile": PROFILE,
        "source_candidate": "42B-1 detector_v3_multikeyframe_v1",
        "annotations_opened": False,
        "candidate_count": len(results),
        "accept_count": sum(
            result["verification"]["decision"] == "ACCEPT"
            for result in results
        ),
        "reject_count": sum(
            result["verification"]["decision"] == "REJECT"
            for result in results
        ),
        "human_review_count": sum(
            result["verification"]["decision"] == "HUMAN_REVIEW"
            for result in results
        ),
        "model_requests": len(results),
        "input_tokens": sum(
            int(
                result["model"]["usage"].get("inputTokens")
                or 0
            )
            for result in results
        ),
        "output_tokens": sum(
            int(
                result["model"]["usage"].get("outputTokens")
                or 0
            )
            for result in results
        ),
        "results": results,
    }

    (output / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "candidate_count",
                    "accept_count",
                    "reject_count",
                    "human_review_count",
                    "model_requests",
                    "input_tokens",
                    "output_tokens",
                )
            },
            indent=2,
        )
    )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--manifest-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--region",
        default="us-west-2",
    )

    args = parser.parse_args()

    evaluate(args)


if __name__ == "__main__":
    main()
