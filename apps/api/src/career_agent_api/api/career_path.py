from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from career_agent_api.core.auth import CurrentUser
from career_agent_api.core.config import Settings, get_settings
from career_agent_api.db.session import get_db
from career_agent_api.models.domain import (
    CareerFact,
    CareerPathConversation,
    CareerPathMessage,
    CareerProfile,
)
from career_agent_api.models.enums import CareerPathMessageRole, VerificationStatus
from career_agent_api.schemas.api import (
    CareerPathConversationRead,
    CareerPathMessageCreate,
    CareerPathWorkspaceRead,
)
from career_agent_api.services.career_path import (
    CONSENT_VERSION,
    CareerPathContextMessage,
    CareerPathProvider,
    CareerPathProviderContext,
    CareerPathProviderError,
    build_confirmed_fact_context,
    build_safety_identifier,
    get_career_path_provider,
    redact_for_ai,
)

router = APIRouter(prefix="/career-path", tags=["career path"])
DAILY_MESSAGE_LIMIT = 30


def _api_error(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "request_id": str(uuid4())},
        headers=headers,
    )


def _provider_consent_version(provider: CareerPathProvider) -> str:
    return f"{CONSENT_VERSION}:{provider.provider_name}"


def _has_current_provider_consent(
    conversation: CareerPathConversation | None,
    provider: CareerPathProvider,
) -> bool:
    return bool(
        conversation
        and conversation.consent_version == _provider_consent_version(provider)
    )


async def _current_profile(session: AsyncSession, owner_id: str) -> CareerProfile:
    profile = await session.scalar(
        select(CareerProfile).where(CareerProfile.owner_id == owner_id)
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


async def _conversation(
    session: AsyncSession, profile_id: object
) -> CareerPathConversation | None:
    return await session.scalar(
        select(CareerPathConversation)
        .where(CareerPathConversation.profile_id == profile_id)
        .options(selectinload(CareerPathConversation.messages))
        .execution_options(populate_existing=True)
    )


async def _confirmed_facts(
    session: AsyncSession, profile_id: object
) -> tuple:
    facts = list(
        (
            await session.scalars(
                select(CareerFact)
                .where(
                    CareerFact.profile_id == profile_id,
                    CareerFact.verification_status == VerificationStatus.CONFIRMED,
                )
                .order_by(CareerFact.created_at, CareerFact.id)
            )
        ).all()
    )
    return build_confirmed_fact_context(facts)


def _workspace(
    *,
    profile: CareerProfile,
    provider: CareerPathProvider,
    confirmed_facts: tuple,
    conversation: CareerPathConversation | None,
) -> CareerPathWorkspaceRead:
    return CareerPathWorkspaceRead(
        provider_ready=provider.available,
        provider=provider.provider_name,
        model=provider.model if provider.available else None,
        profile_id=profile.id,
        confirmed_fact_count=len(confirmed_facts),
        consent_required=not _has_current_provider_consent(conversation, provider),
        conversation=(
            CareerPathConversationRead.model_validate(conversation) if conversation else None
        ),
    )


@router.get("", response_model=CareerPathWorkspaceRead)
async def get_career_path_workspace(
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    provider: CareerPathProvider = Depends(get_career_path_provider),
) -> CareerPathWorkspaceRead:
    profile = await _current_profile(session, user.id)
    conversation = await _conversation(session, profile.id)
    confirmed_facts = await _confirmed_facts(session, profile.id)
    return _workspace(
        profile=profile,
        provider=provider,
        confirmed_facts=confirmed_facts,
        conversation=conversation,
    )


@router.post("/messages", response_model=CareerPathWorkspaceRead)
async def send_career_path_message(
    payload: CareerPathMessageCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    provider: CareerPathProvider = Depends(get_career_path_provider),
) -> CareerPathWorkspaceRead:
    profile = await _current_profile(session, user.id)
    if profile.deletion_started_at is not None:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "profile_deletion_in_progress",
            "Profile deletion is in progress",
        )

    conversation = await _conversation(session, profile.id)
    expected_consent_version = _provider_consent_version(provider)
    has_current_provider_consent = _has_current_provider_consent(conversation, provider)
    if conversation:
        duplicate = next(
            (
                message
                for message in conversation.messages
                if message.client_turn_id == payload.client_turn_id
            ),
            None,
        )
        if duplicate:
            confirmed_facts = await _confirmed_facts(session, profile.id)
            return _workspace(
                profile=profile,
                provider=provider,
                confirmed_facts=confirmed_facts,
                conversation=conversation,
            )

    current_revision = conversation.revision if conversation else 0
    if payload.expected_revision != current_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "career_path_revision_conflict",
            "The conversation changed; reload it before sending another message",
        )
    if not provider.available:
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ai_provider_not_configured",
            "The career path assistant is not configured on the server",
        )
    if not has_current_provider_consent and not payload.data_sharing_acknowledged:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            "data_sharing_acknowledgement_required",
            "Acknowledge the data-sharing notice before starting the conversation",
        )

    confirmed_facts = await _confirmed_facts(session, profile.id)
    if not confirmed_facts:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "career_profile_evidence_required",
            "Prepare your resume and confirm at least one career fact before starting",
        )

    if conversation:
        now = datetime.now(UTC)
        window_start = now - timedelta(days=1)
        recent_user_messages = 0
        for message in conversation.messages:
            created_at = message.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if message.role is CareerPathMessageRole.USER and created_at >= window_start:
                recent_user_messages += 1
        if recent_user_messages >= DAILY_MESSAGE_LIMIT:
            raise _api_error(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "career_path_rate_limited",
                "The daily conversation limit has been reached",
                headers={"Retry-After": "3600"},
            )

    prior_messages = list(conversation.messages) if conversation else []
    if conversation and conversation.last_evidence_revision != profile.evidence_revision:
        # Keep the user's own statements, but do not compound advice produced from stale evidence.
        prior_messages = [
            message
            for message in prior_messages
            if message.role is CareerPathMessageRole.USER
        ]
    context_messages = [
        CareerPathContextMessage(
            role=message.role.value,
            content=redact_for_ai(message.content),
        )
        for message in prior_messages
    ]
    context_messages.append(
        CareerPathContextMessage(role="user", content=redact_for_ai(payload.content))
    )
    context = CareerPathProviderContext(
        locale=profile.preferred_language.value,
        confirmed_facts=confirmed_facts,
        messages=tuple(context_messages),
        safety_identifier=build_safety_identifier(user.id, settings),
    )

    try:
        reply = await provider.generate(context)
    except CareerPathProviderError as exc:
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ai_provider_unavailable",
            "The career path assistant is temporarily unavailable",
        ) from exc

    evidence_revision = profile.evidence_revision
    profile_guard = await session.execute(
        update(CareerProfile)
        .where(
            CareerProfile.id == profile.id,
            CareerProfile.owner_id == user.id,
            CareerProfile.evidence_revision == evidence_revision,
            CareerProfile.deletion_started_at.is_(None),
        )
        .values(evidence_revision=CareerProfile.evidence_revision)
    )
    if profile_guard.rowcount != 1:
        await session.rollback()
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "career_path_context_changed",
            "The verified profile changed while the response was being created",
        )

    if conversation:
        conversation_values: dict[str, object] = {
            "revision": current_revision + 1,
            "last_evidence_revision": evidence_revision,
        }
        if not has_current_provider_consent:
            conversation_values.update(
                consent_version=expected_consent_version,
                consented_at=datetime.now(UTC),
            )
        conversation_guard = await session.execute(
            update(CareerPathConversation)
            .where(
                CareerPathConversation.id == conversation.id,
                CareerPathConversation.profile_id == profile.id,
                CareerPathConversation.revision == current_revision,
            )
            .values(**conversation_values)
        )
        if conversation_guard.rowcount != 1:
            await session.rollback()
            raise _api_error(
                status.HTTP_409_CONFLICT,
                "career_path_revision_conflict",
                "The conversation changed while the response was being created",
            )
        conversation_id = conversation.id
    else:
        conversation = CareerPathConversation(
            profile_id=profile.id,
            revision=1,
            last_evidence_revision=evidence_revision,
            consent_version=expected_consent_version,
            consented_at=datetime.now(UTC),
        )
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id

    first_sequence = current_revision * 2
    session.add_all(
        [
            CareerPathMessage(
                conversation_id=conversation_id,
                sequence=first_sequence,
                role=CareerPathMessageRole.USER,
                content=payload.content,
                suggestions=[],
                evidence_revision=evidence_revision,
                client_turn_id=payload.client_turn_id,
            ),
            CareerPathMessage(
                conversation_id=conversation_id,
                sequence=first_sequence + 1,
                role=CareerPathMessageRole.ASSISTANT,
                content=reply.message,
                suggestions=[
                    suggestion.model_dump(mode="json") for suggestion in reply.suggestions
                ],
                model=provider.model,
                evidence_revision=evidence_revision,
            ),
        ]
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "career_path_revision_conflict",
            "The conversation changed while the response was being saved",
        ) from exc

    refreshed = await _conversation(session, profile.id)
    if not refreshed:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "career_path_save_conflict",
            "The conversation could not be reloaded",
        )
    return _workspace(
        profile=profile,
        provider=provider,
        confirmed_facts=confirmed_facts,
        conversation=refreshed,
    )


@router.delete("/conversation", status_code=status.HTTP_204_NO_CONTENT)
async def reset_career_path_conversation(
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _current_profile(session, user.id)
    conversation = await _conversation(session, profile.id)
    if conversation:
        await session.delete(conversation)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
