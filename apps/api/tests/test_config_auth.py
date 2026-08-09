import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from career_agent_api.core import auth
from career_agent_api.core.auth import get_current_user
from career_agent_api.core.config import Settings


def test_render_postgres_url_is_normalized_for_async_engine() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider="deterministic",
        database_url="postgresql://user:pass@db.example/career",
    )
    assert settings.database_url == "postgresql+asyncpg://user:pass@db.example/career"


def test_production_requires_clerk_jwks() -> None:
    with pytest.raises(ValidationError, match="CLERK_JWKS_URL"):
        Settings(
            _env_file=None,
            ai_provider="deterministic",
            environment="production",
            database_url="postgresql://user:pass@db.example/career",
            auto_create_schema=False,
        )


@pytest.mark.asyncio
async def test_dev_header_bypass_is_rejected_in_production() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider="deterministic",
        environment="production",
        database_url="postgresql://user:pass@db.example/career",
        auto_create_schema=False,
        clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
        clerk_issuer="https://clerk.example",
        clerk_authorized_parties=["https://career.example"],
    )
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=None, settings=settings, x_user_id="attacker")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_configured_clerk_requires_bearer_even_in_development() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider="deterministic",
        environment="development",
        clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
        clerk_issuer="https://clerk.example",
    )
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=None, settings=settings, x_user_id="dev-bypass")
    assert exc_info.value.status_code == 401


def test_production_requires_authorized_parties() -> None:
    with pytest.raises(ValidationError, match="CLERK_AUTHORIZED_PARTIES"):
        Settings(
            _env_file=None,
            ai_provider="deterministic",
            environment="production",
            database_url="postgresql://user:pass@db.example/career",
            auto_create_schema=False,
            clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
            clerk_issuer="https://clerk.example",
            clerk_authorized_parties=[],
        )


def test_clerk_token_rejects_unknown_authorized_party(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeKey:
        key = "public-key"

    class FakeJwkClient:
        def get_signing_key_from_jwt(self, _token: str) -> FakeKey:
            return FakeKey()

    monkeypatch.setattr(auth, "_jwk_client", lambda _url: FakeJwkClient())
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "user_123",
            "azp": "https://attacker.example",
        },
    )
    settings = Settings(
        _env_file=None,
        ai_provider="deterministic",
        clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
        clerk_issuer="https://clerk.example",
        clerk_authorized_parties=["https://career.example"],
    )

    with pytest.raises(HTTPException) as exc_info:
        auth._validate_clerk_token("token", settings)
    assert exc_info.value.status_code == 401


def test_clerk_token_requires_azp_when_allowlist_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeKey:
        key = "public-key"

    class FakeJwkClient:
        def get_signing_key_from_jwt(self, _token: str) -> FakeKey:
            return FakeKey()

    monkeypatch.setattr(auth, "_jwk_client", lambda _url: FakeJwkClient())
    monkeypatch.setattr(auth.jwt, "decode", lambda *_args, **_kwargs: {"sub": "user_123"})
    settings = Settings(
        _env_file=None,
        ai_provider="deterministic",
        clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
        clerk_issuer="https://clerk.example",
        clerk_authorized_parties=["https://career.example"],
    )

    with pytest.raises(HTTPException) as exc_info:
        auth._validate_clerk_token("token", settings)
    assert exc_info.value.status_code == 401


def test_clerk_jwks_connection_failure_is_not_reported_as_an_expired_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableJwkClient:
        def get_signing_key_from_jwt(self, _token: str) -> object:
            raise auth.PyJWKClientConnectionError("JWKS temporarily unavailable")

    monkeypatch.setattr(auth, "_jwk_client", lambda _url: UnavailableJwkClient())
    settings = Settings(
        _env_file=None,
        ai_provider="deterministic",
        clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
        clerk_issuer="https://clerk.example",
    )

    with pytest.raises(HTTPException) as exc_info:
        auth._validate_clerk_token("token", settings)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Authentication keys are temporarily unavailable"


def _external_provider_production_settings(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "production",
        "database_url": "postgresql://user:pass@db.example/career",
        "auto_create_schema": False,
        "clerk_jwks_url": "https://clerk.example/.well-known/jwks.json",
        "clerk_issuer": "https://clerk.example",
        "clerk_authorized_parties": ["https://career.example"],
        "ai_provider": "mistral",
    }
    values.update(overrides)
    return values


def test_production_mistral_requires_its_provider_specific_key() -> None:
    with pytest.raises(ValidationError, match="MISTRAL_API_KEY"):
        Settings(
            **_external_provider_production_settings(
                openai_api_key=SecretStr("wrong-provider-key"),
                ai_safety_salt=SecretStr("test-safety-salt"),
            )
        )


def test_production_mistral_requires_dedicated_safety_salt() -> None:
    with pytest.raises(ValidationError, match="AI_SAFETY_SALT"):
        Settings(
            **_external_provider_production_settings(
                mistral_api_key=SecretStr("mistral-key"),
            )
        )


def test_production_accepts_complete_mistral_configuration() -> None:
    settings = Settings(
        **_external_provider_production_settings(
            mistral_api_key=SecretStr("mistral-key"),
            ai_safety_salt=SecretStr("test-safety-salt"),
            ai_model="mistral-small-2603",
        )
    )

    assert settings.ai_provider == "mistral"
    assert settings.ai_model == "mistral-small-2603"
