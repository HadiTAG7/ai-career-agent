from __future__ import annotations

import logging
from functools import partial
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from career_agent_api.core.auth import CurrentUser
from career_agent_api.core.config import Settings, get_settings
from career_agent_api.db.session import get_db
from career_agent_api.models.domain import CareerFact, CareerProfile
from career_agent_api.schemas.api import (
    ResumeDraftExportCreate,
    ResumeDraftGenerateCreate,
    ResumeDraftRead,
    ResumeQuestionCreate,
    ResumeQuestionsRead,
)
from career_agent_api.services.resume_export import render_resume_pdf
from career_agent_api.services.resume_writer import (
    ResumeWriterError,
    ResumeWriterProvider,
    build_resume_evidence,
    get_resume_writer_provider,
)

router = APIRouter(
    prefix="/profiles/{profile_id}/resume-assistant",
    tags=["resume assistant"],
)

logger = logging.getLogger(__name__)


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "request_id": str(uuid4())},
    )


async def _owned_profile(
    session: AsyncSession,
    profile_id: UUID,
    owner_id: str,
) -> CareerProfile:
    profile = await session.scalar(
        select(CareerProfile).where(
            CareerProfile.id == profile_id,
            CareerProfile.owner_id == owner_id,
        )
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


async def _profile_facts(session: AsyncSession, profile_id: UUID) -> list[CareerFact]:
    return list(
        (
            await session.scalars(
                select(CareerFact)
                .where(CareerFact.profile_id == profile_id)
                .order_by(CareerFact.created_at)
            )
        ).all()
    )


def _resume_writer_provider(
    settings: Settings,
    *,
    data_sharing_acknowledged: bool,
) -> ResumeWriterProvider:
    if not data_sharing_acknowledged:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            "resume_writer_consent_required",
            "Acknowledge sending professional evidence to the AI provider before continuing",
        )
    provider = get_resume_writer_provider(settings)
    if not provider.available:
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_not_configured",
            "The AI resume writer is not configured on the server",
        )
    return provider


@router.post("/questions", response_model=ResumeQuestionsRead)
async def create_resume_questions(
    profile_id: UUID,
    payload: ResumeQuestionCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeQuestionsRead:
    await _owned_profile(session, profile_id, user.id)
    provider = _resume_writer_provider(
        settings,
        data_sharing_acknowledged=payload.data_sharing_acknowledged,
    )
    evidence = build_resume_evidence(await _profile_facts(session, profile_id))
    if not evidence:
        raise _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_writer_evidence_required",
            (
                "Analyze a resume or complete the guided interview before requesting "
                "follow-up questions"
            ),
        )
    try:
        questions = await provider.generate_questions(
            language=payload.language,
            target_role=payload.target_role,
            evidence=evidence,
        )
    except ResumeWriterError as exc:
        logger.warning("Resume follow-up question generation failed: %s", exc)
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_unavailable",
            "The AI resume writer is temporarily unavailable",
        ) from exc
    covered_categories = sorted(
        {item.category for item in evidence if item.category != "identity"}
    )
    return ResumeQuestionsRead(
        provider=provider.provider_name,
        model=provider.model,
        questions=questions,
        covered_categories=covered_categories,
    )


@router.post("/generate", response_model=ResumeDraftRead)
async def generate_resume_draft(
    profile_id: UUID,
    payload: ResumeDraftGenerateCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeDraftRead:
    await _owned_profile(session, profile_id, user.id)
    provider = _resume_writer_provider(
        settings,
        data_sharing_acknowledged=payload.data_sharing_acknowledged,
    )
    evidence = build_resume_evidence(await _profile_facts(session, profile_id))
    if not evidence and not any(not answer.skipped for answer in payload.answers):
        raise _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_writer_evidence_required",
            "Professional evidence is required before generating a resume",
        )
    try:
        draft = await provider.generate_draft(
            language=payload.language,
            target_role=payload.target_role,
            evidence=evidence,
            answers=payload.answers,
        )
    except ResumeWriterError as exc:
        logger.warning("Resume draft generation failed: %s", exc)
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_unavailable",
            "The AI resume writer is temporarily unavailable",
        ) from exc
    return ResumeDraftRead(
        **draft.model_dump(),
        provider=provider.provider_name,
        model=provider.model,
        fact_count=len(evidence)
        + sum(bool(answer.answer.strip()) and not answer.skipped for answer in payload.answers),
    )


@router.post(
    "/export",
    response_class=Response,
    responses={
        200: {
            "description": "Reviewed resume PDF",
            "content": {"application/pdf": {}},
        }
    },
)
async def export_resume_pdf(
    profile_id: UUID,
    payload: ResumeDraftExportCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _owned_profile(session, profile_id, user.id)
    if not payload.review_acknowledged:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            "resume_review_required",
            "Review the generated resume before exporting it",
        )
    try:
        pdf_bytes = await run_in_threadpool(
            partial(
                render_resume_pdf,
                profile_name=profile.full_name,
                city=profile.city,
                language=payload.language,
                draft=payload.draft,
                contact=payload.contact,
            )
        )
    except Exception as exc:
        raise _api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "resume_export_failed",
            "The resume PDF could not be generated",
        ) from exc

    display_name = f"{profile.full_name.strip() or 'resume'}-resume.pdf"
    encoded_name = quote(display_name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=resume.pdf; filename*=UTF-8''{encoded_name}"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
