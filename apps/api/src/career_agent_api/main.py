from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import career_agent_api.models  # noqa: F401
from career_agent_api.api.router import router
from career_agent_api.core.config import get_settings
from career_agent_api.db.base import Base
from career_agent_api.db.session import get_engine, get_session_factory
from career_agent_api.services.policies import seed_source_policies


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.auto_create_schema:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        await seed_source_policies(session)
        await session.commit()
    yield
    await get_engine().dispose()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Evidence-first bilingual career API. Match scores measure explicit requirement "
        "coverage and are not interview probabilities."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Id"],
    expose_headers=["Content-Disposition"],
)
app.include_router(router)


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, str]:
    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready"}
