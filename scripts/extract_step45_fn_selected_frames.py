from pathlib import Path
import json
import shutil

root = Path("evaluation/step44_one_shot_run")
out = Path("evaluation/step45_fn_selected_frames")

cases = [
    "case_003",
    "case_005",
    "case_011",
    "case_012",
    "case_013",
]

out.mkdir(parents=True, exist_ok=True)

for case_id in cases:
    report_path = root / case_id / "detector_v3_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))

    case_out = out / case_id
    case_out.mkdir(parents=True, exist_ok=True)

    frames = report["multi_keyframe"]["keyframes"]

    print(f"\n{case_id}: {len(frames)} selected keyframes")

    for index, item in enumerate(frames, start=1):
        frame = item["frame"]

        # The OpenCV manifest path is preserved in the corresponding
        # per-case opencv_1hz output. Match by frame number/timestamp.
        frame_number = int(frame["frame_number"])
        timestamp = float(frame["timestamp_seconds"])

        candidates = sorted(
            (root / case_id / "opencv_1hz").rglob("*.jpg")
        )

        match = None

        marker = f"{frame_number:05d}_"

        for candidate in candidates:
            if marker in candidate.name:
                match = candidate
                break

        if match is None:
            print(
                f"  [MISSING] frame={frame_number} "
                f"t={timestamp:.3f}"
            )
            continue

        destination = (
            case_out
            / f"{index:02d}_t{timestamp:.3f}_frame{frame_number}.jpg"
        )

        shutil.copyfile(match, destination)

        print(
            f"  [PASS] t={timestamp:.3f} "
            f"frame={frame_number} -> {destination}"
        )
