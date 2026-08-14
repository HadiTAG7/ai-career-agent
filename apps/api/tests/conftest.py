from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import career_agent_api.models  # noqa: F401
from career_agent_api.api.router import router
from career_agent_api.core.config import Settings, get_settings
from career_agent_api.db.base import Base
from career_agent_api.db.session import get_db
from career_agent_api.services.policies import seed_source_policies


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed_source_policies(session)
        await session.commit()
    yield factory
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(router)

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def override_settings() -> Settings:
        return Settings(
            _env_file=None,
            environment="test",
            dev_auth_bypass=True,
            database_url="sqlite+aiosqlite://",
            auto_create_schema=True,
            ai_provider="deterministic",
            max_import_bytes=1_000_000,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


async def create_profile_and_source(
    client: httpx.AsyncClient, user_id: str = "demo-user"
) -> tuple[dict, dict]:
    headers = {"X-User-Id": user_id}
    response = await client.post(
        "/v1/profiles",
        headers=headers,
        json={"full_name": "نورة المطيري", "preferred_language": "ar", "city": "الرياض"},
    )
    assert response.status_code == 201, response.text
    profile = response.json()
    sources_response = await client.get(f"/v1/profiles/{profile['id']}/sources", headers=headers)
    assert sources_response.status_code == 200
    return profile, sources_response.json()[0]
