"""API-only settings, separate from the frozen detector and worker settings."""
from functools import lru_cache
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecuritySettings(BaseSettings):
    app_env: str = "dev"
    aws_region: str = "us-west-2"
    api_auth_token: SecretStr | None = None
    api_auth_secret_id: str | None = None
    api_auth_ssm_parameter: str | None = None
    require_https: bool = False
    public_mode_supported: bool = False
    allowed_hosts: str = "localhost,127.0.0.1,[::1],testserver"
    cors_origins: str = "http://localhost:8000,http://localhost:5173"
    presigned_url_ttl_seconds: int = Field(default=900, ge=60, le=900)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    @property
    def cloud_mode(self) -> bool:
        return self.app_env.lower() not in {"dev", "local", "test"}

    @model_validator(mode="after")
    def validate_security(self):
        sources = [self.api_auth_token, self.api_auth_secret_id, self.api_auth_ssm_parameter]
        if sum(bool(source) for source in sources) > 1:
            raise ValueError("Choose one API auth secret source")
        if self.cloud_mode:
            if not any(sources) or not self.require_https:
                raise ValueError("Cloud API requires an auth secret source and REQUIRE_HTTPS=true")
            origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
            if not origins or any(not origin.startswith("https://") or "*" in origin for origin in origins):
                raise ValueError("Cloud CORS origins must be explicit HTTPS origins")
            if not self.allowed_hosts.strip() or "*" in self.allowed_hosts or "testserver" in self.allowed_hosts:
                raise ValueError("Cloud API requires explicit ALLOWED_HOSTS")
        return self


@lru_cache
def get_security_settings() -> SecuritySettings:
    return SecuritySettings()
