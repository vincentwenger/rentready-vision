from pathlib import Path
import cv2
import numpy as np
import json

DATASET = Path(
    r"C:\Users\vince\Software\RentReady_Vision\evaluation\v3"
)

OUTPUT = Path(
    r"C:\Users\vince\Software\RentReady_Vision\evaluation"
    r"\step42b5_transient_motion_diagnostic"
)

OUTPUT.mkdir(
    parents=True,
    exist_ok=True,
)

CASES = [
    "defect_09_quimby_water_drip",
    "clean_16_compass_bedroom_entry",
    "clean_17_compass_bedroom_windows",
    "clean_18_compass_stairway",
    "clean_23_compass_upstairs_bedroom",
]


def find_video(stem):
    matches = []

    for suffix in (
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
    ):
        matches.extend(
            DATASET.rglob(
                stem + suffix
            )
        )

    if not matches:
        raise FileNotFoundError(stem)

    return matches[0]


def align(reference, moving):
    ref_gray = cv2.cvtColor(
        reference,
        cv2.COLOR_BGR2GRAY,
    )

    mov_gray = cv2.cvtColor(
        moving,
        cv2.COLOR_BGR2GRAY,
    )

    warp = np.eye(
        2,
        3,
        dtype=np.float32,
    )

    criteria = (
        cv2.TERM_CRITERIA_EPS
        | cv2.TERM_CRITERIA_COUNT,
        60,
        1e-5,
    )

    try:
        cv2.findTransformECC(
            ref_gray,
            mov_gray,
            warp,
            cv2.MOTION_AFFINE,
            criteria,
        )

        return cv2.warpAffine(
            moving,
            warp,
            (
                reference.shape[1],
                reference.shape[0],
            ),
            flags=(
                cv2.INTER_LINEAR
                | cv2.WARP_INVERSE_MAP
            ),
            borderMode=cv2.BORDER_REPLICATE,
        )

    except cv2.error:
        return moving


def analyze_video(path):
    cap = cv2.VideoCapture(
        str(path)
    )

    if not cap.isOpened():
        raise RuntimeError(path)

    fps = float(
        cap.get(cv2.CAP_PROP_FPS)
    )

    total_frames = int(
        cap.get(
            cv2.CAP_PROP_FRAME_COUNT
        )
    )

    duration = (
        total_frames / fps
        if fps > 0
        else 0
    )

    # 10 Hz OpenCV-only temporal scan.
    times = np.arange(
        0.0,
        max(
            0.0,
            duration - 0.1,
        ),
        0.1,
    )

    frames = []

    for t in times:
        cap.set(
            cv2.CAP_PROP_POS_MSEC,
            float(t * 1000.0),
        )

        ok, frame = cap.read()

        if not ok or frame is None:
            frames.append(None)
            continue

        h, w = frame.shape[:2]

        # Ignore outermost border where alignment
        # commonly creates residual artifacts.
        margin_x = int(
            w * 0.05
        )

        margin_y = int(
            h * 0.05
        )

        frames.append(
            frame[
                margin_y:h-margin_y,
                margin_x:w-margin_x,
            ].copy()
        )

    cap.release()

    events = []

    for i in range(
        1,
        len(frames),
    ):
        previous = frames[i - 1]
        current = frames[i]

        if (
            previous is None
            or current is None
        ):
            continue

        current_aligned = align(
            previous,
            current,
        )

        a = cv2.cvtColor(
            previous,
            cv2.COLOR_BGR2GRAY,
        )

        b = cv2.cvtColor(
            current_aligned,
            cv2.COLOR_BGR2GRAY,
        )

        diff = cv2.absdiff(
            a,
            b,
        )

        diff = cv2.GaussianBlur(
            diff,
            (3, 3),
            0,
        )

        _, mask = cv2.threshold(
            diff,
            24,
            255,
            cv2.THRESH_BINARY,
        )

        # Remove isolated single-pixel noise.
        kernel = np.ones(
            (2, 2),
            np.uint8,
        )

        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            kernel,
        )

        count, labels, stats, _ = (
            cv2.connectedComponentsWithStats(
                mask,
                connectivity=8,
            )
        )

        candidates = []

        for label in range(
            1,
            count,
        ):
            x, y, w, h, area = (
                stats[label]
            )

            if area < 8:
                continue

            if area > 450:
                continue

            long_side = max(
                w,
                h,
            )

            short_side = max(
                1,
                min(
                    w,
                    h,
                ),
            )

            elongation = (
                long_side
                / short_side
            )

            # Looking for compact or streak-like
            # transient objects, not huge shifted edges.
            if long_side > 90:
                continue

            candidates.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "width": int(w),
                    "height": int(h),
                    "area": int(area),
                    "elongation": round(
                        float(elongation),
                        3,
                    ),
                }
            )

        if candidates:
            strongest = sorted(
                candidates,
                key=lambda item: (
                    item["elongation"],
                    item["area"],
                ),
                reverse=True,
            )[:5]

            events.append(
                {
                    "from_seconds": round(
                        float(
                            times[i - 1]
                        ),
                        3,
                    ),
                    "to_seconds": round(
                        float(
                            times[i]
                        ),
                        3,
                    ),
                    "candidate_count": len(
                        candidates
                    ),
                    "strongest": strongest,
                }
            )

    return {
        "fps": fps,
        "duration_seconds": round(
            duration,
            3,
        ),
        "scan_interval_seconds": 0.1,
        "events": events,
    }


results = {}

for stem in CASES:
    print(
        f"ANALYZE {stem}"
    )

    video = find_video(stem)

    result = analyze_video(
        video
    )

    results[stem] = result

    print(
        "  events:",
        len(
            result["events"]
        ),
    )

    # Show only strongest events by maximum
    # component elongation.
    ranked = sorted(
        result["events"],
        key=lambda event: max(
            (
                item["elongation"]
                for item
                in event["strongest"]
            ),
            default=0,
        ),
        reverse=True,
    )

    for event in ranked[:10]:
        best = (
            event["strongest"][0]
            if event["strongest"]
            else {}
        )

        print(
            f"  {event['from_seconds']:.1f}"
            f"->{event['to_seconds']:.1f}s",
            "count=",
            event["candidate_count"],
            "best=",
            best,
        )


output_path = (
    OUTPUT
    / "transient_motion_diagnostic.json"
)

output_path.write_text(
    json.dumps(
        results,
        indent=2,
    ),
    encoding="utf-8",
)

print()
print(output_path)
