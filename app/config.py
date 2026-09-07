from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    aws_region: str = "us-west-2"
    s3_bucket: str
    ddb_table: str = "rentready-vision-dev"
    processing_queue_url: str | None = None
    processing_dlq_url: str | None = None
    queue_visibility_timeout_seconds: int = 1800
    queue_max_receive_count: int = 5
    queue_retry_base_seconds: int = 60
    processing_lease_seconds: int = 2100
    cool_required: bool = False
    cool_expected_cv2_prefix: str = "/opt/cool"
    cool_log_group: str | None = "/rentready-vision/cool-worker"
    cloudwatch_metrics_namespace: str = "RentReadyVision/Processing"
    presigned_url_ttl_seconds: int = 900
    max_upload_bytes: int = 1024 * 1024 * 1024
    cors_origins: str = "http://localhost:8000,http://localhost:5173"
    processing_sample_every_seconds: float = 1.0
    processing_scene_threshold: float = 0.75
    processing_scene_feature_threshold: float = 0.22
    processing_scene_combined_threshold: float = 0.55
    processing_scene_min_duration_seconds: float = 4.0
    processing_scene_max_duration_seconds: float = 30.0
    processing_scene_motion_support_percent_per_second: float = 12.0
    processing_scene_analysis_width: int = 480
    processing_scene_max_orb_features: int = 600
    processing_dedupe_threshold: float = 0.94
    processing_dedupe_feature_threshold: float = 0.55
    processing_min_sharpness: float = 45.0
    processing_blur_tile_grid_size: int = 3
    processing_min_sharp_tiles_percent: float = 50.0
    processing_motion_blur_min_motion_percent_per_second: float = 8.0
    processing_motion_blur_sharpness_multiplier: float = 1.5
    processing_min_brightness: float = 25.0
    processing_max_brightness: float = 235.0
    processing_dark_pixel_value: int = 16
    processing_bright_pixel_value: int = 240
    processing_max_dark_pixels_percent: float = 60.0
    processing_max_bright_pixels_percent: float = 35.0
    processing_max_motion_percent_per_second: float = 30.0
    processing_min_motion_features: int = 12
    processing_quality_analysis_width: int = 720
    processing_motion_analysis_width: int = 480
    processing_motion_interval_seconds: float = 0.1
    processing_motion_window_size: int = 3
    processing_min_motion_inliers: int = 12
    processing_min_motion_inlier_ratio: float = 0.25
    processing_min_keyframes_per_scene: int = 3
    processing_max_keyframes_per_scene: int = 8
    processing_min_keyframe_separation_seconds: float = 4.0
    processing_keyframe_marginal_score_threshold: float = 0.62
    processing_keyframe_weight_sharpness: float = 0.30
    processing_keyframe_weight_brightness: float = 0.15
    processing_keyframe_weight_stability: float = 0.20
    processing_keyframe_weight_distinctiveness: float = 0.25
    processing_keyframe_weight_temporal_distance: float = 0.10
    processing_max_output_keyframes: int = 120
    processing_min_output_keyframes: int = 3
    processing_fallback_spacing_seconds: float = 2.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
