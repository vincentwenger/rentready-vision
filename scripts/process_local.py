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
    parser.add_argument("--min-sharpness", type=float, default=45.0)
    parser.add_argument("--blur-tile-grid-size", type=int, default=3)
    parser.add_argument("--min-sharp-tiles-percent", type=float, default=50.0)
    parser.add_argument("--motion-blur-min-motion-percent-per-second", type=float, default=8.0)
    parser.add_argument("--motion-blur-sharpness-multiplier", type=float, default=1.5)
    parser.add_argument("--min-brightness", type=float, default=25.0)
    parser.add_argument("--max-brightness", type=float, default=235.0)
    parser.add_argument("--max-motion-percent-per-second", type=float, default=30.0)
    parser.add_argument("--scene-histogram-threshold", type=float, default=0.75)
    parser.add_argument("--scene-feature-threshold", type=float, default=0.22)
    parser.add_argument("--scene-combined-threshold", type=float, default=0.55)
    parser.add_argument("--scene-min-duration-seconds", type=float, default=4.0)
    parser.add_argument("--scene-max-duration-seconds", type=float, default=30.0)
    parser.add_argument("--min-keyframes-per-scene", type=int, default=3)
    parser.add_argument("--max-keyframes-per-scene", type=int, default=8)
    parser.add_argument("--keyframe-marginal-score-threshold", type=float, default=0.62)
    parser.add_argument("--max-output-keyframes", type=int, default=120)
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
        scene_threshold=args.scene_histogram_threshold,
        scene_feature_threshold=args.scene_feature_threshold,
        scene_combined_threshold=args.scene_combined_threshold,
        scene_min_duration_seconds=args.scene_min_duration_seconds,
        scene_max_duration_seconds=args.scene_max_duration_seconds,
        min_sharpness=args.min_sharpness,
        blur_tile_grid_size=args.blur_tile_grid_size,
        min_sharp_tiles_percent=args.min_sharp_tiles_percent,
        motion_blur_min_motion_percent_per_second=(
            args.motion_blur_min_motion_percent_per_second
        ),
        motion_blur_sharpness_multiplier=args.motion_blur_sharpness_multiplier,
        min_brightness=args.min_brightness,
        max_brightness=args.max_brightness,
        max_motion_percent_per_second=args.max_motion_percent_per_second,
        quality_analysis_width=args.quality_analysis_width,
        motion_analysis_width=args.motion_analysis_width,
        motion_interval_seconds=args.motion_interval_seconds,
        min_motion_inlier_ratio=args.min_motion_inlier_ratio,
        min_keyframes_per_scene=args.min_keyframes_per_scene,
        max_keyframes_per_scene=args.max_keyframes_per_scene,
        keyframe_marginal_score_threshold=args.keyframe_marginal_score_threshold,
        max_output_keyframes=args.max_output_keyframes,
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
