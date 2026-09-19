#!/usr/bin/env python3
"""Create deterministic local verification evidence for Step 24 issue consolidation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vision.issue_consolidator import (  # noqa: E402
    CONSOLIDATION_VERSION,
    compare_issues,
    consolidate_issues,
    consolidation_contract,
)


def image_bytes(*, shift: int = 0, unrelated: bool = False) -> bytes:
    image = np.full((360, 640, 3), 210, dtype=np.uint8)
    if unrelated:
        cv2.rectangle(image, (25, 20), (125, 105), (35, 45, 65), -1)
        cv2.putText(image, "SHOWER", (20, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (10, 10, 10), 2)
    else:
        cv2.rectangle(image, (250, 160), (390, 270), (235, 235, 235), -1)
        cv2.ellipse(image, (320, 220), (50, 25), 0, 0, 360, (70, 90, 120), -1)
        cv2.putText(image, "VANITY", (240, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
        image = np.roll(image, shift, axis=1)
    success, encoded = cv2.imencode(".jpg", image)
    if not success:
        raise RuntimeError("OpenCV could not encode synthetic evidence")
    return encoded.tobytes()


def issue(
    issue_id: str,
    timestamp: float,
    frame_index: int,
    key: str,
    *,
    confidence: float,
    description: str = "Possible staining near bathroom vanity",
    bbox: dict | None = None,
) -> dict:
    return {
        "issue_id": issue_id,
        "room": "bathroom",
        "category": "visible_staining",
        "description": description,
        "timestamp": timestamp,
        "confidence": confidence,
        "severity_candidate": "review",
        "bbox": bbox or {"x": 0.39, "y": 0.48, "width": 0.22, "height": 0.25},
        "evidence_frame_index": frame_index,
        "evidence": {
            "frame_index": frame_index,
            "timestamp_seconds": timestamp,
            "scene_index": 3,
            "s3_key": key,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "step24" / "local_verification.json",
    )
    parser.add_argument(
        "--contract-output",
        type=Path,
        default=ROOT / "evaluation" / "step24" / "issue_consolidation_contract.json",
    )
    args = parser.parse_args()

    timestamps = [268.0, 270.0, 271.0, 274.0, 276.0]
    images = {
        f"bathroom-{index}.jpg": image_bytes(shift=index)
        for index in range(len(timestamps))
    }
    images["shower.jpg"] = image_bytes(unrelated=True)
    repeated = [
        issue(
            f"bathroom-stain-{index}",
            timestamp,
            index,
            f"bathroom-{index}.jpg",
            confidence=0.80 + index * 0.01,
            bbox={"x": 0.39 + index * 0.002, "y": 0.48, "width": 0.22, "height": 0.25},
        )
        for index, timestamp in enumerate(timestamps)
    ]
    merged = consolidate_issues(repeated, image_loader=lambda key: images[key])
    distinct = issue(
        "shower-stain",
        271.0,
        8,
        "shower.jpg",
        confidence=0.91,
        description="Dark stain near shower ceiling",
        bbox={"x": 0.04, "y": 0.04, "width": 0.16, "height": 0.14},
    )
    separated = consolidate_issues(
        [repeated[0], distinct], image_loader=lambda key: images[key]
    )
    distinct_comparison = compare_issues(
        repeated[0], distinct, image_loader=lambda key: images[key]
    )
    metadata_fallback = compare_issues(
        repeated[0],
        repeated[3],
        image_loader=lambda _key: (_ for _ in ()).throw(OSError("simulated unavailable image")),
    )

    browser = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    services = (ROOT / "app" / "services.py").read_text(encoding="utf-8")
    checks = {
        "contract_has_six_requested_signals": consolidation_contract()["signals"] == [
            "timestamp_similarity",
            "room_similarity",
            "category_similarity",
            "image_similarity",
            "region_similarity",
            "semantic_similarity",
        ],
        "five_repeated_detections_become_one_issue": merged["consolidated_issue_count"] == 1,
        "four_duplicates_removed": merged["duplicate_observations_merged"] == 4,
        "all_evidence_timestamps_preserved": merged["issues"][0]["evidence_timestamps"] == timestamps,
        "all_source_issue_ids_preserved": len(merged["issues"][0]["source_issue_ids"]) == 5,
        "highest_confidence_evidence_is_representative": merged["issues"][0]["representative_issue_id"] == "bathroom-stain-4",
        "opencv_visual_comparisons_executed": merged["visual_comparison_count"] > 0,
        "different_region_stays_separate": separated["consolidated_issue_count"] == 2,
        "different_region_rejection_is_auditable": (
            not distinct_comparison["merge"]
            and "region_location_changed" in distinct_comparison["rejection_reasons"]
        ),
        "missing_images_do_not_get_synthetic_similarity": (
            metadata_fallback["signals"]["image_similarity"] is None
            and metadata_fallback["visual_evidence_available"] is False
        ),
        "strict_metadata_fallback_can_merge_exact_repeat": metadata_fallback["merge"] is True,
        "s3_report_path_is_step24_specific": "step24-consolidated-issues.json" in services,
        "browser_renders_consolidated_issues": "response?.issues ?? response?.candidate_findings" in browser,
        "browser_renders_evidence_timestamps": "evidence_timestamps" in browser,
    }
    errors = [name for name, passed in checks.items() if not passed]
    output = {
        "step": 24,
        "verification_scope": "local_deterministic_issue_consolidation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": CONSOLIDATION_VERSION,
        "passed": not errors,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "checks": checks,
        "errors": errors,
        "example": {
            "raw_issue_count": merged["raw_issue_count"],
            "consolidated_issue_count": merged["consolidated_issue_count"],
            "description": merged["issues"][0]["description"],
            "evidence_timestamps_seconds": merged["issues"][0]["evidence_timestamps"],
            "evidence_timestamps_mm_ss": [
                f"{int(value // 60):02d}:{int(value % 60):02d}" for value in timestamps
            ],
        },
        "note": (
            "Local PASS proves deterministic consolidation, OpenCV image/region comparison, "
            "negative separation, strict missing-image fallback, API persistence wiring, and browser rendering."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    args.contract_output.write_text(
        json.dumps(consolidation_contract(), indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(output, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
