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
    processing_min_sharpness: float = 45.0
    processing_min_brightness: float = 25.0
    processing_max_brightness: float = 235.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
