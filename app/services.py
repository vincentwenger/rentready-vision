from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .aws import s3
from .config import get_settings
from .db import get_inspection, update_inspection
from .vision.video_processor import process_video

settings = get_settings()


def run_processing_job(inspection_id: str) -> None:
    inspection = get_inspection(inspection_id)
    if not inspection:
        return

    source_key = inspection.get("original_s3_key")
    if not source_key:
        update_inspection(inspection_id, status="FAILED", error="No uploaded video key")
        return

    update_inspection(inspection_id, status="PROCESSING", error=None)

    try:
        with tempfile.TemporaryDirectory(prefix=f"rentready-{inspection_id}-") as tmp:
            tmp_path = Path(tmp)
            suffix = Path(source_key).suffix or ".mp4"
            input_path = tmp_path / f"walkthrough{suffix}"
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            s3.download_file(settings.s3_bucket, source_key, str(input_path))

            manifest = process_video(
                input_path,
                output_dir,
                sample_every_seconds=settings.processing_sample_every_seconds,
                scene_threshold=settings.processing_scene_threshold,
                dedupe_threshold=settings.processing_dedupe_threshold,
                min_sharpness=settings.processing_min_sharpness,
                min_brightness=settings.processing_min_brightness,
                max_brightness=settings.processing_max_brightness,
            )

            prefix = f"inspections/{inspection_id}"
            public_keyframes = []

            for record in manifest["keyframes"]:
                local_path = Path(record["local_path"])
                s3_key = f"{prefix}/frames/{local_path.name}"
                s3.upload_file(
                    str(local_path), settings.s3_bucket, s3_key,
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
                public_keyframes.append({
                    "index": record["index"],
                    "timestamp_seconds": record["timestamp_seconds"],
                    "s3_key": s3_key,
                    "sharpness": record["sharpness"],
                    "brightness": record["brightness"],
                    "scene_index": record["scene_index"],
                })

            remote_manifest = {
                "video": manifest["video"],
                "processing": manifest["processing"],
                "scenes": manifest["scenes"],
                "keyframes": public_keyframes,
            }

            manifest_key = f"{prefix}/manifest.json"
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=manifest_key,
                Body=json.dumps(remote_manifest, indent=2).encode("utf-8"),
                ContentType="application/json",
            )

            update_inspection(
                inspection_id,
                status="COMPLETE",
                manifest_s3_key=manifest_key,
                video=manifest["video"],
                processing=manifest["processing"],
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
