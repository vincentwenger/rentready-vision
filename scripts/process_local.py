import argparse
import json
from app.vision.video_processor import process_video


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run and tune the RentReady Vision OpenCV pipeline without AWS."
    )
    parser.add_argument("video")
    parser.add_argument("--out", default="./local-output")
    parser.add_argument("--sample-every-seconds", type=float, default=1.0)
    parser.add_argument("--min-sharpness", type=float, default=30.0)
    parser.add_argument("--min-brightness", type=float, default=25.0)
    parser.add_argument("--max-brightness", type=float, default=235.0)
    parser.add_argument("--max-motion-percent-per-second", type=float, default=8.0)
    parser.add_argument("--quality-analysis-width", type=int, default=720)
    parser.add_argument("--motion-analysis-width", type=int, default=480)
    parser.add_argument("--motion-interval-seconds", type=float, default=0.1)
    parser.add_argument("--min-motion-inlier-ratio", type=float, default=0.25)
    parser.add_argument("--min-output-keyframes", type=int, default=3)
    args = parser.parse_args()
    manifest = process_video(
        args.video,
        args.out,
        sample_every_seconds=args.sample_every_seconds,
        min_sharpness=args.min_sharpness,
        min_brightness=args.min_brightness,
        max_brightness=args.max_brightness,
        max_motion_percent_per_second=args.max_motion_percent_per_second,
        quality_analysis_width=args.quality_analysis_width,
        motion_analysis_width=args.motion_analysis_width,
        motion_interval_seconds=args.motion_interval_seconds,
        min_motion_inlier_ratio=args.min_motion_inlier_ratio,
        min_output_keyframes=args.min_output_keyframes,
    )
    print(
        json.dumps(
            {
                "video": manifest["video"],
                "processing": manifest["processing"],
                "scenes": manifest["scenes"],
                "manifest": f"{args.out}/manifest.local.json",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
