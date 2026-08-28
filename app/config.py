from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    aws_region: str = "us-west-2"
    s3_bucket: str
    ddb_table: str = "rentready-vision-dev"
    presigned_url_ttl_seconds: int = 900
    max_upload_bytes: int = 1024 * 1024 * 1024
    cors_origins: str = "http://localhost:8000,http://localhost:5173"
    processing_sample_every_seconds: float = 1.0
    processing_scene_threshold: float = 0.75
    processing_dedupe_threshold: float = 0.96
    processing_min_sharpness: float = 30.0
    processing_min_brightness: float = 25.0
    processing_max_brightness: float = 235.0
    processing_dark_pixel_value: int = 16
    processing_bright_pixel_value: int = 240
    processing_max_dark_pixels_percent: float = 60.0
    processing_max_bright_pixels_percent: float = 35.0
    processing_max_motion_percent_per_second: float = 8.0
    processing_min_motion_features: int = 12
    processing_quality_analysis_width: int = 720
    processing_motion_analysis_width: int = 480
    processing_motion_interval_seconds: float = 0.1
    processing_motion_window_size: int = 3
    processing_min_motion_inliers: int = 12
    processing_min_motion_inlier_ratio: float = 0.25
    processing_min_output_keyframes: int = 3
    processing_fallback_spacing_seconds: float = 2.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
