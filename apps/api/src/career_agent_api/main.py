import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import career_agent_api.models  # noqa: F401
from career_agent_api.api.router import router
from career_agent_api.core.config import get_settings
from career_agent_api.db.base import Base
from career_agent_api.db.session import get_engine, get_session_factory
from career_agent_api.services.policies import seed_source_policies
from career_agent_api.services.resume_writer import close_resume_writer_provider

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.auto_create_schema:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        try:
            await seed_source_policies(session)
            await session.commit()
        except IntegrityError:
            # Another worker seeded concurrently; the policies exist, which is all we need.
            await session.rollback()
    try:
        yield
    finally:
        try:
            await close_resume_writer_provider()
        finally:
            await get_engine().dispose()


settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    request_id = str(uuid4())
    logger.exception("Unhandled error (request_id=%s): %s", request_id, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                "message": "The request could not be completed",
                "request_id": request_id,
            }
        },
    )


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, str]:
    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready"}
