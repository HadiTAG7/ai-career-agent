from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AI Career Agent API"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+aiosqlite:///./career_agent.db"
    auto_create_schema: bool = True
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    clerk_jwks_url: str | None = None
    clerk_issuer: str | None = None
    clerk_audience: str | None = None
    clerk_authorized_parties: Annotated[list[str], NoDecode] = Field(default_factory=list)

    ai_provider: Literal["deterministic", "openai", "mistral"] = "deterministic"
    openai_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None
    ai_model: str = Field(default="gpt-5.6-sol", min_length=1, max_length=120)
    ai_safety_salt: SecretStr | None = None
    ai_request_timeout_seconds: float = Field(default=25, ge=5, le=60)
    ai_max_output_tokens: int = Field(default=800, ge=200, le=1000)
    resume_ai_max_output_tokens: int = Field(default=4_000, ge=1_000, le=8_000)
    max_import_bytes: int = Field(default=10_000_000, ge=1_000_000, le=25_000_000)
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("clerk_authorized_parties", mode="before")
    @classmethod
    def parse_authorized_parties(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        # Render exposes a standard libpq URL. The application and Alembic both use SQLAlchemy's
        # async engine, so normalize it at the single configuration boundary.
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if isinstance(value, str) and value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @model_validator(mode="after")
    def secure_production(self) -> "Settings":
        if self.environment == "production":
            if not self.clerk_jwks_url:
                raise ValueError("CLERK_JWKS_URL is required in production")
            if not self.clerk_issuer:
                raise ValueError("CLERK_ISSUER is required in production")
            if not self.clerk_authorized_parties:
                raise ValueError("CLERK_AUTHORIZED_PARTIES is required in production")
            if not self.database_url.startswith(("postgresql+asyncpg://", "postgresql://")):
                raise ValueError("Production DATABASE_URL must use PostgreSQL")
            if self.auto_create_schema:
                raise ValueError("AUTO_CREATE_SCHEMA must be false in production; use Alembic")
            if self.ai_provider in {"openai", "mistral"}:
                provider_api_key = (
                    self.openai_api_key
                    if self.ai_provider == "openai"
                    else self.mistral_api_key
                )
                provider_key_name = (
                    "OPENAI_API_KEY"
                    if self.ai_provider == "openai"
                    else "MISTRAL_API_KEY"
                )
                if not provider_api_key:
                    raise ValueError(
                        f"{provider_key_name} is required when "
                        f"AI_PROVIDER={self.ai_provider} in production"
                    )
                if not self.ai_safety_salt:
                    raise ValueError(
                        "AI_SAFETY_SALT is required when an external AI provider is enabled "
                        "in production"
                    )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
