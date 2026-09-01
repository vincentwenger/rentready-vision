from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import Any

import boto3


EXPECTED = {
    "source_frame_count": 31576,
    "sampled_frame_count": 1053,
    "representative_frame_count": 73,
    "scene_count": 56,
}


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def matches(item: dict[str, Any]) -> bool:
    video = item.get("video") or {}
    processing = item.get("processing") or {}
    return (
        int(video.get("total_frames", -1)) == EXPECTED["source_frame_count"]
        and int(processing.get("sampled_frames", -1))
        == EXPECTED["sampled_frame_count"]
        and int(processing.get("selected_keyframes", -1))
        == EXPECTED["representative_frame_count"]
        and int(processing.get("scene_count", -1)) == EXPECTED["scene_count"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find the DynamoDB inspection that produced the Step-8 result."
    )
    parser.add_argument("--table", default="rentready-vision-dev")
    parser.add_argument("--region", default="us-west-2")
    args = parser.parse_args()

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    items = []
    scan_kwargs: dict[str, Any] = {}
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(json_safe(item) for item in response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    candidates = [
        {
            "inspection_id": item.get("inspection_id"),
            "original_s3_key": item.get("original_s3_key"),
            "manifest_s3_key": item.get("manifest_s3_key"),
            "updated_at": item.get("updated_at"),
            "video": item.get("video"),
            "processing": item.get("processing"),
        }
        for item in items
        if matches(item)
    ]
    print(json.dumps({"expected": EXPECTED, "candidates": candidates}, indent=2))
    return 0 if len(candidates) == 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
