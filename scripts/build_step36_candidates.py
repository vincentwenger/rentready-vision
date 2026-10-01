"""Build Step 36 ambiguous-candidate review files and finalized candidate sets.

Two-stage workflow:
1. extract: scan a completed Step 35 arm for raw findings in confidence 0.50-0.85
   and emit an owner-review CSV with blank truth fields.
2. finalize: after manual review, split that CSV into an execution manifest and
   a separate label file.  The executor never receives the label file.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.step36_agentic_verification import (
    ABSENT,
    LABEL_SCHEMA_VERSION,
    PRESENT,
    SCHEMA_VERSION,
    validate_candidates_document,
    validate_labels_document,
)

FIELDS = [
    "candidate_id", "video", "timestamp", "x", "y", "width", "height",
    "room", "category", "description", "source_confidence", "source_arm",
    "source_model_id", "source_stage", "ground_truth", "human_review_expected",
    "review_notes",
]


def _candidate_id(video: str, finding: dict[str, Any], ordinal: int) -> str:
    payload = json.dumps(
        {
            "video": video,
            "timestamp": finding.get("timestamp"),
            "bbox": finding.get("bbox"),
            "category": finding.get("category"),
            "description": finding.get("description"),
            "ordinal": ordinal,
        },
        sort_keys=True,
    ).encode("utf-8")
    return "s36-" + hashlib.sha256(payload).hexdigest()[:16]


def extract(step35_run: Path, output_csv: Path, *, arm: str = "B") -> list[dict[str, str]]:
    root = step35_run / arm
    if not root.is_dir():
        raise FileNotFoundError(f"Step 35 arm directory not found: {root}")
    rows: list[dict[str, str]] = []
    for report_path in sorted(root.glob("*/detector_report.json")):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        video = report_path.parent.name + ".mp4"
        # Prefer the original video name from run.json when available.
        run_path = report_path.parent / "run.json"
        if run_path.is_file():
            video = str(json.loads(run_path.read_text(encoding="utf-8")).get("video") or video)
        findings = report.get("candidate_findings") or []
        for ordinal, finding in enumerate(findings):
            try:
                confidence = float(finding.get("confidence"))
            except (TypeError, ValueError):
                continue
            if not 0.50 <= confidence <= 0.85:
                continue
            bbox = finding.get("bbox") or {}
            if not all(name in bbox for name in ("x", "y", "width", "height")):
                continue
            rows.append({
                "candidate_id": _candidate_id(video, finding, ordinal),
                "video": video,
                "timestamp": str(finding.get("timestamp")),
                "x": str(bbox["x"]), "y": str(bbox["y"]),
                "width": str(bbox["width"]), "height": str(bbox["height"]),
                "room": str(finding.get("room") or "unknown"),
                "category": str(finding.get("category") or ""),
                "description": str(finding.get("description") or ""),
                "source_confidence": str(confidence),
                "source_arm": arm,
                "source_model_id": str(finding.get("model_id") or ""),
                "source_stage": str(finding.get("stage") or "initial"),
                "ground_truth": "",
                "human_review_expected": "",
                "review_notes": "",
            })
    if not rows:
        raise ValueError("No ambiguous Step 35 findings found in the selected arm")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _parse_bool(value: str, *, field: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"{field} must be true/false or yes/no")


def finalize(review_csv: Path, candidates_path: Path, labels_path: Path, *, set_id: str, purpose: str) -> tuple[dict, dict]:
    with review_csv.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("review CSV is empty")
    candidates, labels = [], []
    for row in rows:
        truth = str(row.get("ground_truth") or "").strip().upper()
        if truth not in {PRESENT, ABSENT}:
            raise ValueError(f"ground_truth for {row.get('candidate_id')} must be PRESENT or ABSENT")
        source_confidence = float(row["source_confidence"])
        if not 0.50 <= source_confidence <= 0.85:
            raise ValueError("every finalized candidate must originate in the ambiguous 0.50-0.85 band")
        candidates.append({
            "candidate_id": row["candidate_id"],
            "video": row["video"],
            "timestamp": float(row["timestamp"]),
            "bbox": {name: float(row[name]) for name in ("x", "y", "width", "height")},
            "room": row.get("room") or "unknown",
            "category": row["category"],
            "description": row["description"],
            "source_confidence": source_confidence,
            "source_arm": row.get("source_arm") or None,
            "source_model_id": row.get("source_model_id") or None,
            "source_stage": row.get("source_stage") or None,
        })
        labels.append({
            "candidate_id": row["candidate_id"],
            "ground_truth": truth,
            "human_review_expected": _parse_bool(row.get("human_review_expected") or "", field="human_review_expected"),
            "review_notes": row.get("review_notes") or "",
        })
    candidate_doc = validate_candidates_document({
        "schema_version": SCHEMA_VERSION,
        "set_id": set_id,
        "purpose": purpose,
        "candidates": candidates,
    })
    label_doc = validate_labels_document({
        "schema_version": LABEL_SCHEMA_VERSION,
        "set_id": set_id,
        "labels": labels,
    }, set_id=set_id, candidate_ids=[row["candidate_id"] for row in candidate_doc["candidates"]])
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(json.dumps(candidate_doc, indent=2) + "\n", encoding="utf-8")
    labels_path.write_text(json.dumps(label_doc, indent=2) + "\n", encoding="utf-8")
    return candidate_doc, label_doc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    extract_parser = sub.add_parser("extract")
    extract_parser.add_argument("step35_run", type=Path)
    extract_parser.add_argument("--output-csv", type=Path, required=True)
    extract_parser.add_argument("--arm", default="B", choices=["A", "B", "C"])
    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("review_csv", type=Path)
    finalize_parser.add_argument("--candidates", type=Path, required=True)
    finalize_parser.add_argument("--labels", type=Path, required=True)
    finalize_parser.add_argument("--set-id", required=True)
    finalize_parser.add_argument("--purpose", choices=["development", "challenge"], required=True)
    args = parser.parse_args()
    if args.command == "extract":
        rows = extract(args.step35_run, args.output_csv, arm=args.arm)
        print(json.dumps({"ambiguous_candidates": len(rows), "review_csv": str(args.output_csv)}, indent=2))
    else:
        candidates, labels = finalize(args.review_csv, args.candidates, args.labels,
                                      set_id=args.set_id, purpose=args.purpose)
        print(json.dumps({"candidate_count": len(candidates["candidates"]),
                          "candidates": str(args.candidates), "labels": str(args.labels)}, indent=2))


if __name__ == "__main__":
    main()
