from pathlib import Path
import cv2
import numpy as np
from app.vision.video_processor import (
    blur_metrics,
    brightness_metrics,
    duration_aware_minimum_keyframes,
    estimate_camera_motion,
    feature_similarity,
    frame_sharpness,
    near_duplicate_metrics,
    process_video,
    visual_signature,
)


def _make_test_video(path: Path) -> None:
    width, height, fps = 320, 240, 10
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    assert writer.isOpened()
    for scene in range(3):
        for i in range(20):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:] = (30 + scene * 70, 60 + scene * 40, 90 + scene * 20)
            cv2.rectangle(frame, (20 + i, 20), (150 + i, 120), (255, 255, 255), 3)
            cv2.putText(frame, f"scene-{scene}-{i}", (25, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            writer.write(frame)
    writer.release()


def _make_duplicate_view_video(path: Path) -> None:
    """Four seconds of one view with progressively sharper focus."""
    width, height, fps = 320, 240, 10
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    assert writer.isOpened()
    rng = np.random.default_rng(7)
    cabinet = np.full((height, width, 3), 110, dtype=np.uint8)
    cv2.rectangle(cabinet, (30, 20), (290, 220), (80, 120, 170), -1)
    for x, y in rng.integers([40, 30], [280, 210], size=(150, 2)):
        cv2.circle(cabinet, (int(x), int(y)), 2, (240, 240, 240), -1)
    cv2.putText(cabinet, "CABINET", (70, 125), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 3)

    for frame_index in range(40):
        kernel = 7 if frame_index < 10 else 5 if frame_index < 20 else 3 if frame_index < 30 else 1
        frame = cv2.GaussianBlur(cabinet, (kernel, kernel), 0) if kernel > 1 else cabinet.copy()
        writer.write(frame)
    writer.release()


def test_process_video(tmp_path: Path) -> None:
    video = tmp_path / "sample.avi"
    out = tmp_path / "out"
    _make_test_video(video)
    manifest = process_video(video, out, sample_every_seconds=0.5, min_sharpness=1.0, scene_threshold=0.80, dedupe_threshold=0.995)
    assert manifest["video"]["total_frames"] > 0
    assert manifest["processing"]["sampled_frames"] > 0
    assert manifest["processing"]["selected_keyframes"] > 0
    assert manifest["processing"]["opencv_version"].startswith("5.")
    assert "pyramidal_lucas_kanade_optical_flow" in manifest["processing"]["opencv_operations"]
    assert len(manifest["frame_assessments"]) == manifest["processing"]["sampled_frames"]
    assert all("evidence_quality_score" in item for item in manifest["frame_assessments"])
    assert all("motion" in item for item in manifest["frame_assessments"])
    assert all("blur_classification" in item for item in manifest["keyframes"])
    reduction = manifest["processing"]["reduction_metrics"]
    assert reduction["original_video_frames"] == manifest["video"]["total_frames"]
    assert reduction["frames_initially_sampled"] == manifest["processing"]["sampled_frames"]
    assert reduction["near_duplicates_removed"] == manifest["processing"]["rejected_duplicate"]
    assert reduction["representative_frames"] == manifest["processing"]["selected_keyframes"]
    assert len(manifest["scenes"]) >= 1
    assert (out / "manifest.local.json").exists()


def test_variance_of_laplacian_separates_sharp_and_blurry_frames() -> None:
    checker = np.indices((240, 320)).sum(axis=0) % 2
    sharp = (checker * 255).astype(np.uint8)
    blurry = cv2.GaussianBlur(sharp, (21, 21), 0)

    assert frame_sharpness(sharp) > frame_sharpness(blurry) * 20


def test_motion_supported_blur_rejects_borderline_panning_frame() -> None:
    rng = np.random.default_rng(91)
    frame = rng.integers(0, 256, size=(240, 320), dtype=np.uint8)
    sharpness = frame_sharpness(frame, analysis_width=320)
    threshold = sharpness / 1.2

    stable = blur_metrics(
        frame,
        min_sharpness=threshold,
        analysis_width=320,
        motion_percent_per_second=0.0,
    )
    panning = blur_metrics(
        frame,
        min_sharpness=threshold,
        analysis_width=320,
        motion_percent_per_second=10.0,
    )

    assert stable["classification"] == "usable"
    assert panning["classification"] == "blurry"
    assert panning["motion_blur_suspected"] is True
    assert "motion_supported_blur" in panning["reasons"]


def test_tiled_blur_rejects_localized_detail_false_positive() -> None:
    frame = np.full((240, 320), 128, dtype=np.uint8)
    checker = (np.indices((80, 106)).sum(axis=0) % 2 * 255).astype(np.uint8)
    frame[:80, :106] = checker
    global_sharpness = frame_sharpness(frame, analysis_width=320)

    result = blur_metrics(
        frame,
        min_sharpness=global_sharpness / 1.2,
        analysis_width=320,
        motion_percent_per_second=None,
    )

    assert result["classification"] == "blurry"
    assert result["sharp_tiles_percent"] < 50.0
    assert "insufficient_sharp_tiles" in result["reasons"]


def test_duration_aware_minimum_keyframes_scales_with_scene_length() -> None:
    assert duration_aware_minimum_keyframes(4.0, 3) == 1
    assert duration_aware_minimum_keyframes(12.0, 3) == 2
    assert duration_aware_minimum_keyframes(30.0, 3) == 3
    assert duration_aware_minimum_keyframes(30.0, 0) == 0


def test_brightness_classifies_dark_usable_and_overexposed() -> None:
    kwargs = {
        "min_brightness": 25.0,
        "max_brightness": 235.0,
        "dark_pixel_value": 16,
        "bright_pixel_value": 240,
        "max_dark_pixels_percent": 60.0,
        "max_bright_pixels_percent": 35.0,
    }
    dark = brightness_metrics(np.full((100, 100), 5, dtype=np.uint8), **kwargs)
    usable = brightness_metrics(np.full((100, 100), 128, dtype=np.uint8), **kwargs)
    bright = brightness_metrics(np.full((100, 100), 250, dtype=np.uint8), **kwargs)

    assert dark["classification"] == "too_dark"
    assert usable["classification"] == "usable"
    assert bright["classification"] == "overexposed"


def test_optical_flow_detects_fast_camera_translation() -> None:
    rng = np.random.default_rng(2026)
    base = np.zeros((240, 320), dtype=np.uint8)
    for x, y in rng.integers([15, 15], [305, 225], size=(180, 2)):
        cv2.circle(base, (int(x), int(y)), 2, 255, -1)

    stable = cv2.warpAffine(base, np.float32([[1, 0, 1], [0, 1, 0]]), (320, 240))
    fast = cv2.warpAffine(base, np.float32([[1, 0, 5], [0, 1, 0]]), (320, 240))
    stable_motion = estimate_camera_motion(base, stable, elapsed_seconds=0.1)
    fast_motion = estimate_camera_motion(base, fast, elapsed_seconds=0.1)

    assert stable_motion["method"] == "sparse_lk_flow_ransac_affine"
    assert stable_motion["percent_per_second"] < 3.0
    assert fast_motion["percent_per_second"] > 8.0
    assert fast_motion["percent_per_second"] > stable_motion["percent_per_second"] * 4


def test_unreliable_large_gap_motion_is_marked_unknown() -> None:
    rng = np.random.default_rng(2026)
    base = rng.integers(0, 256, size=(240, 320), dtype=np.uint8)
    unrelated = rng.integers(0, 256, size=(240, 320), dtype=np.uint8)

    motion = estimate_camera_motion(base, unrelated, elapsed_seconds=1.0)

    assert motion["percent_per_second"] is None
    assert motion["method"] in {"unreliable_ransac_fit", "unavailable"}


def test_orb_feature_similarity_separates_same_view_from_unrelated_view() -> None:
    rng = np.random.default_rng(2026)
    base = np.zeros((240, 320, 3), dtype=np.uint8)
    unrelated = np.zeros_like(base)
    for x, y in rng.integers([10, 10], [310, 230], size=(120, 2)):
        cv2.circle(base, (int(x), int(y)), 3, (255, 255, 255), -1)
    for x, y in rng.integers([10, 10], [310, 230], size=(120, 2)):
        cv2.rectangle(unrelated, (int(x), int(y)), (int(x) + 5, int(y) + 5), (255, 255, 255), -1)
    shifted = cv2.warpAffine(base, np.float32([[1, 0, 4], [0, 1, 2]]), (320, 240))

    similar = feature_similarity(visual_signature(base), visual_signature(shifted))
    different = feature_similarity(visual_signature(base), visual_signature(unrelated))

    assert similar["method"] == "orb_knn_ratio_test_ransac_affine"
    assert similar["similarity"] > 0.65
    assert different["similarity"] < 0.35


def test_geometric_orb_can_dedupe_a_shifted_view_when_histogram_changes() -> None:
    rng = np.random.default_rng(2027)
    base = np.zeros((240, 320, 3), dtype=np.uint8)
    for x, y in rng.integers([10, 10], [310, 230], size=(180, 2)):
        cv2.circle(base, (int(x), int(y)), 3, (255, 255, 255), -1)
    shifted = cv2.warpAffine(base, np.float32([[1, 0, 35], [0, 1, 4]]), (320, 240))

    duplicate = near_duplicate_metrics(
        visual_signature(base),
        visual_signature(shifted),
        histogram_threshold=0.96,
        feature_threshold=0.55,
    )

    assert duplicate["is_near_duplicate"] is True
    assert duplicate["method"] in {"geometric_orb", "hsv_and_geometric_orb"}
    assert duplicate["feature_good_matches"] >= 12


def test_multisignal_scene_detection_creates_timed_segments(tmp_path: Path) -> None:
    video = tmp_path / "scenes.avi"
    out = tmp_path / "scene-output"
    _make_test_video(video)

    manifest = process_video(
        video,
        out,
        sample_every_seconds=0.5,
        min_sharpness=1.0,
        max_motion_percent_per_second=100.0,
        scene_threshold=0.80,
        scene_feature_threshold=0.30,
        scene_combined_threshold=0.60,
        scene_min_duration_seconds=0.5,
        scene_max_duration_seconds=100.0,
        max_keyframes_per_scene=2,
    )

    assert len(manifest["scenes"]) == 3
    assert [scene["start_seconds"] for scene in manifest["scenes"]] == [0.0, 2.0, 4.0]
    assert [scene["end_seconds"] for scene in manifest["scenes"]] == [2.0, 4.0, 6.0]
    assert manifest["scenes"][0]["end_reason"] in {
        "hsv_and_feature_drop",
        "scene_reference_divergence",
        "stable_view_differs_from_scene_reference",
    }
    boundary = manifest["scenes"][0]["boundary_evidence"]
    assert boundary["hsv_similarity_previous"] is not None
    assert boundary["feature_similarity_previous"] is not None
    assert all("scene_change" in assessment for assessment in manifest["frame_assessments"])


def test_maximum_scene_duration_is_enforced_even_on_rejected_frames(tmp_path: Path) -> None:
    video = tmp_path / "all-rejected.avi"
    out = tmp_path / "all-rejected-output"
    _make_test_video(video)

    manifest = process_video(
        video,
        out,
        sample_every_seconds=0.5,
        min_sharpness=1_000_000.0,
        scene_min_duration_seconds=0.5,
        scene_max_duration_seconds=1.0,
    )

    assert len(manifest["scenes"]) >= 5
    assert all(
        scene["duration_seconds"] <= 1.5
        for scene in manifest["scenes"][:-1]
    )
    assert any(
        scene["end_reason"] == "maximum_scene_duration"
        for scene in manifest["scenes"]
    )


def test_short_final_scene_is_merged_instead_of_rendered_as_zero_length(tmp_path: Path) -> None:
    video = tmp_path / "short-tail.avi"
    out = tmp_path / "short-tail-output"
    _make_test_video(video)

    manifest = process_video(
        video,
        out,
        sample_every_seconds=0.5,
        min_sharpness=1.0,
        max_motion_percent_per_second=100.0,
        scene_threshold=0.0,
        scene_feature_threshold=0.0,
        scene_combined_threshold=0.0,
        scene_min_duration_seconds=1.0,
        scene_max_duration_seconds=5.5,
        dedupe_threshold=1.1,
    )

    assert len(manifest["scenes"]) == 1
    assert manifest["scenes"][0]["duration_seconds"] == 6.0
    assert "merged_short_final_scene" in manifest["scenes"][0]


def test_scene_selection_honors_global_ai_frame_cap(tmp_path: Path) -> None:
    video = tmp_path / "capped.avi"
    out = tmp_path / "capped-output"
    _make_test_video(video)

    manifest = process_video(
        video,
        out,
        sample_every_seconds=0.5,
        min_sharpness=1.0,
        max_motion_percent_per_second=100.0,
        scene_threshold=0.80,
        scene_feature_threshold=0.30,
        scene_combined_threshold=0.60,
        scene_min_duration_seconds=0.5,
        scene_max_duration_seconds=100.0,
        dedupe_threshold=1.1,
        max_keyframes_per_scene=2,
        min_keyframe_separation_seconds=0.1,
        max_output_keyframes=4,
        keyframe_marginal_score_threshold=0.0,
    )

    assert manifest["processing"]["selected_keyframes"] == 4
    assert manifest["processing"]["rejected_output_limit"] == 2
    assert len({frame["scene_index"] for frame in manifest["keyframes"]}) == 3


def test_adaptive_keyframe_count_changes_with_marginal_value_threshold(tmp_path: Path) -> None:
    video = tmp_path / "adaptive.avi"
    _make_test_video(video)
    common = {
        "sample_every_seconds": 0.5,
        "min_sharpness": 1.0,
        "max_motion_percent_per_second": 100.0,
        "scene_threshold": 0.0,
        "scene_feature_threshold": 0.0,
        "scene_combined_threshold": 0.0,
        "scene_max_duration_seconds": 100.0,
        "dedupe_threshold": 1.1,
        "min_keyframes_per_scene": 3,
        "max_keyframes_per_scene": 8,
        "min_keyframe_separation_seconds": 2.0,
    }

    conservative = process_video(
        video,
        tmp_path / "adaptive-conservative",
        keyframe_marginal_score_threshold=1.1,
        **common,
    )
    permissive = process_video(
        video,
        tmp_path / "adaptive-permissive",
        keyframe_marginal_score_threshold=0.0,
        **common,
    )

    assert conservative["processing"]["strict_selected_keyframes"] == 1
    assert conservative["processing"]["selected_keyframes"] == 3
    assert permissive["processing"]["selected_keyframes"] == 8
    assert conservative["processing"]["rejected_adaptive_selection"] > 0
    assert permissive["processing"]["rejected_scene_limit"] > 0
    assert all(
        0.0 <= frame["keyframe_selection_score"] <= 1.0
        for frame in permissive["keyframes"]
    )
    assert all(
        set(frame["keyframe_selection_components"]) == {
            "sharpness",
            "brightness",
            "camera_stability",
            "distinctiveness",
            "temporal_distance",
        }
        for frame in permissive["keyframes"]
    )


def test_near_duplicates_collapse_to_sharpest_representative(tmp_path: Path) -> None:
    video = tmp_path / "cabinet.avi"
    out = tmp_path / "cabinet-output"
    _make_duplicate_view_video(video)

    manifest = process_video(
        video,
        out,
        sample_every_seconds=0.5,
        min_sharpness=0.1,
        max_motion_percent_per_second=100.0,
        scene_max_duration_seconds=100.0,
        max_keyframes_per_scene=10,
        min_keyframe_separation_seconds=0.0,
        dedupe_threshold=0.94,
        dedupe_feature_threshold=0.45,
        min_output_keyframes=1,
    )

    assessments = manifest["frame_assessments"]
    selected = manifest["keyframes"]
    reduction = manifest["processing"]["reduction_metrics"]
    maximum_candidate_sharpness = max(
        assessment["blur"]["variance_of_laplacian"] for assessment in assessments
    )

    assert len(selected) == 1
    assert selected[0]["sharpness"] == maximum_candidate_sharpness
    assert reduction["frames_initially_sampled"] == 8
    assert reduction["near_duplicates_removed"] == 7
    assert reduction["representative_frames"] == 1
    assert all(
        assessment["decision"] in {"selected_keyframe", "rejected_duplicate"}
        for assessment in assessments
    )


def test_best_available_fallback_prevents_empty_frame_output(tmp_path: Path) -> None:
    video = tmp_path / "fallback.avi"
    out = tmp_path / "fallback-out"
    _make_test_video(video)

    manifest = process_video(
        video,
        out,
        sample_every_seconds=0.5,
        min_sharpness=1_000_000.0,
        min_output_keyframes=3,
        fallback_spacing_seconds=0.5,
    )

    assert manifest["processing"]["strict_selected_keyframes"] == 0
    assert manifest["processing"]["fallback_selected_keyframes"] == 3
    assert manifest["processing"]["scene_fallback_selected_keyframes"] == 1
    assert manifest["processing"]["global_fallback_selected_keyframes"] == 2
    assert manifest["processing"]["selected_keyframes"] == 3
    assert len(list((out / "frames").glob("*_fallback.jpg"))) == 3
    assert {frame["selection_reason"] for frame in manifest["keyframes"]} == {
        "best_available_scene_fallback",
        "best_available_fallback",
    }


def test_every_scene_gets_a_labeled_best_available_frame(tmp_path: Path) -> None:
    video = tmp_path / "scene-fallbacks.avi"
    out = tmp_path / "scene-fallbacks-output"
    _make_test_video(video)

    manifest = process_video(
        video,
        out,
        sample_every_seconds=0.5,
        min_sharpness=1_000_000.0,
        scene_min_duration_seconds=0.5,
        scene_max_duration_seconds=1.0,
        min_output_keyframes=1,
    )

    assert manifest["processing"]["strict_selected_keyframes"] == 0
    assert manifest["processing"]["scenes_without_selected_frames"] == 0
    assert manifest["processing"]["scene_coverage_percent"] == 100.0
    assert manifest["processing"]["scene_fallback_selected_keyframes"] == len(
        manifest["scenes"]
    )
    assert all(scene["selected_keyframe_count"] == 1 for scene in manifest["scenes"])
    assert all(
        frame["selection_reason"] == "best_available_scene_fallback"
        for frame in manifest["keyframes"]
    )
