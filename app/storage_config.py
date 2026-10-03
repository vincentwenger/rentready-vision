"""Storage settings kept separate from the frozen detector's configuration."""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    s3_video_retention_days: int = Field(default=30, ge=1)
    s3_noncurrent_video_retention_days: int = Field(default=30, ge=1)
    s3_abort_multipart_days: int = Field(default=7, ge=1)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_storage_settings() -> StorageSettings:
    return StorageSettings()
