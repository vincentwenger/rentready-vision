"""Step 49 operational settings, separate from frozen detector configuration."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerLifecycleSettings(BaseSettings):
    cool_worker_instance_id: str | None = None
    worker_lifecycle_function_name: str | None = None
    worker_lifecycle_enabled: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_lifecycle_settings():
    settings = WorkerLifecycleSettings()
    if settings.worker_lifecycle_enabled and not settings.cool_worker_instance_id:
        raise ValueError("COOL_WORKER_INSTANCE_ID is required when Step 49 is enabled")
    return settings
