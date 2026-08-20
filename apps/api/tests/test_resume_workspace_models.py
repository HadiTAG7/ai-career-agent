from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from career_agent_api.models.domain import (
    CareerProfile,
    ResumeDraftVersion,
    ResumeMessage,
    ResumeWorkspace,
)
from career_agent_api.models.enums import (
    PreferredLanguage,
    ResumeDraftStatus,
    ResumeDraftVersionReason,
    ResumeMessageKind,
    ResumeMessageRole,
    ResumeMessageStatus,
    ResumeWorkspaceStage,
)
from career_agent_api.schemas.api import (
    ResumeDraftPatchCreate,
    ResumeDraftRevisionCreate,
    ResumeMessageCreate,
    ResumeRewriteCreate,
    ResumeRewriteSuggestionRead,
    ResumeRewriteTurnRead,
    ResumeWorkspaceRead,
    ResumeWorkspaceStartCreate,
)


def _draft() -> dict:
    return {
        "headline": "مهندس برمجيات",
        "professional_summary": "مهندس برمجيات بخبرة عملية في بناء تطبيقات موثوقة.",
        "summary_evidence_handles": ["fact:summary"],
        "sections": [
            {
                "key": "experience",
                "title": "الخبرة العملية",
                "items": [
                    {
                        "id": "experience_1",
                        "title": "مهندس برمجيات",
                        "organization": "شركة مثال",
                        "date_range": "2024 - 2026",
                        "location": "الرياض",
                        "bullets": ["طوّر خدمات خلفية موثوقة."],
                        "evidence_handles": ["fact:experience"],
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_resume_workspace_persists_ordered_messages_versions_and_cascades(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client_turn_id = uuid4()
    async with session_factory() as session:
        profile = CareerProfile(
            owner_id="resume-workspace-owner",
            full_name="Resume Workspace Owner",
            preferred_language=PreferredLanguage.AR,
        )
        workspace = ResumeWorkspace(
            profile=profile,
            language=PreferredLanguage.AR,
            stage=ResumeWorkspaceStage.WRITING,
            evidence_revision=3,
            readiness_score=72,
            section_coverage={"experience": True, "education": False},
            current_draft=_draft(),
            draft_revision=1,
            contact={"email": "owner@example.com"},
            consent_version="2026-08-08-v2:mistral",
            provider="mistral",
            model="mistral-small-latest",
            provider_metadata={"region": "eu"},
        )
        workspace.messages.extend(
            [
                ResumeMessage(
                    sequence=2,
                    role=ResumeMessageRole.ASSISTANT,
                    kind=ResumeMessageKind.QUESTION,
                    content="ما أبرز أثر حققته؟",
                    structured_payload={"category": "experience"},
                    status=ResumeMessageStatus.SENT,
                ),
                ResumeMessage(
                    sequence=1,
                    role=ResumeMessageRole.USER,
                    kind=ResumeMessageKind.TEXT,
                    content="أريد بناء سيرتي.",
                    structured_payload={},
                    status=ResumeMessageStatus.SENT,
                    client_turn_id=client_turn_id,
                ),
            ]
        )
        workspace.versions.append(
            ResumeDraftVersion(
                version=1,
                reason=ResumeDraftVersionReason.INITIAL_GENERATION,
                status=ResumeDraftStatus.DRAFT,
                content=_draft(),
                diff={"sections_added": ["experience"]},
                evidence_revision=3,
            )
        )
        session.add(profile)
        await session.commit()
        workspace_id = workspace.id
        profile_id = profile.id

        session.expunge_all()
        result = await session.execute(
            select(ResumeWorkspace)
            .where(ResumeWorkspace.id == workspace_id)
            .options(
                selectinload(ResumeWorkspace.messages),
                selectinload(ResumeWorkspace.versions),
            )
        )
        stored = result.scalar_one()
        assert [message.sequence for message in stored.messages] == [1, 2]
        assert stored.messages[0].client_turn_id == client_turn_id
        assert stored.versions[0].content["headline"] == "مهندس برمجيات"
        assert stored.profile_id == profile_id
        serialized = ResumeWorkspaceRead.model_validate(stored)
        assert [message.sequence for message in serialized.messages] == [1, 2]
        assert serialized.versions[0].reason is ResumeDraftVersionReason.INITIAL_GENERATION

        await session.delete(await session.get(CareerProfile, profile_id))
        await session.commit()
        assert await session.get(ResumeWorkspace, workspace_id) is None
        assert await session.get(ResumeMessage, stored.messages[0].id) is None
        assert await session.get(ResumeDraftVersion, stored.versions[0].id) is None


@pytest.mark.asyncio
async def test_resume_message_client_turn_is_idempotent_per_workspace(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client_turn_id = uuid4()
    async with session_factory() as session:
        workspace = ResumeWorkspace(
            profile=CareerProfile(owner_id="resume-idempotency-owner", full_name="Owner"),
            language=PreferredLanguage.EN,
        )
        workspace.messages.extend(
            [
                ResumeMessage(
                    sequence=1,
                    role=ResumeMessageRole.USER,
                    content="First",
                    client_turn_id=client_turn_id,
                ),
                ResumeMessage(
                    sequence=2,
                    role=ResumeMessageRole.USER,
                    content="Duplicate retry",
                    client_turn_id=client_turn_id,
                ),
            ]
        )
        session.add(workspace)
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_profile_can_have_only_one_resume_workspace(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        profile = CareerProfile(owner_id="single-resume-workspace-owner", full_name="Owner")
        first = ResumeWorkspace(profile=profile)
        session.add(first)
        await session.commit()

        session.add(ResumeWorkspace(profile_id=profile.id))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_resume_draft_versions_are_immutable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace = ResumeWorkspace(
            profile=CareerProfile(owner_id="resume-version-owner", full_name="Owner"),
            language=PreferredLanguage.EN,
        )
        version = ResumeDraftVersion(
            version=1,
            reason=ResumeDraftVersionReason.INITIAL_GENERATION,
            content=_draft(),
            evidence_revision=0,
        )
        workspace.versions.append(version)
        session.add(workspace)
        await session.commit()

        version.diff = {"illegal": "mutation"}
        with pytest.raises(ValueError, match="immutable"):
            await session.commit()


def test_resume_workspace_request_schemas_enforce_revisions_and_rewrite_targets() -> None:
    start = ResumeWorkspaceStartCreate(language="en", conversation_language="ar")
    assert start.language is PreferredLanguage.EN
    assert start.conversation_language is PreferredLanguage.AR

    with pytest.raises(ValidationError):
        ResumeMessageCreate(
            content="   ",
            client_turn_id=uuid4(),
            expected_revision=0,
        )

    action = ResumeMessageCreate(
        client_turn_id=uuid4(),
        expected_revision=2,
        quick_action="generate",
    )
    assert action.content == ""

    with pytest.raises(ValidationError):
        ResumeRewriteCreate(
            target_kind="bullet",
            section_key="experience",
            item_id="experience_1",
            mode="stronger",
            expected_draft_revision=1,
        )

    rewrite = ResumeRewriteCreate(
        target_kind="bullet",
        section_key="experience",
        item_id="experience_1",
        bullet_index=0,
        mode="custom",
        instruction="  ركّز على الأثر  ",
        expected_draft_revision=1,
    )
    assert rewrite.instruction == "ركّز على الأثر"

    patch = ResumeDraftPatchCreate(draft=_draft(), expected_draft_revision=4)
    assert patch.draft.sections[0].key == "experience"
    assert ResumeDraftRevisionCreate(expected_draft_revision=4).expected_draft_revision == 4


def _rewrite_request(conversation: list[dict[str, str]]) -> ResumeRewriteCreate:
    return ResumeRewriteCreate(
        target_kind="bullet",
        section_key="experience",
        item_id="experience_1",
        bullet_index=0,
        mode="custom",
        instruction="غيّر المواد إلى مواد استثمارية",
        expected_draft_revision=1,
        conversation=conversation,
    )


def test_rewrite_conversation_must_be_an_alternating_capped_exchange() -> None:
    exchange = _rewrite_request(
        [
            {"role": "assistant", "content": "أي مواد استثمارية تقصد تحديدًا؟"},
            {"role": "user", "content": "  المحاسبة المالية والاقتصاد الكلي  "},
        ]
    )
    assert exchange.conversation[0].role == "assistant"
    assert exchange.conversation[1].content == "المحاسبة المالية والاقتصاد الكلي"

    question = {"role": "assistant", "content": "سؤال؟"}
    answer = {"role": "user", "content": "جواب"}
    invalid_conversations = [
        [answer],  # must start with the editor's question
        [question, answer, answer],  # roles must alternate
        [question],  # must end with the user's answer
        [question, answer] * 3 + [question, answer],  # over both cap and length
        [question, answer, question, answer, question, answer],  # a third question
        [question, {"role": "user", "content": "   "}],  # blank answer
        [question, {"role": "user", "content": "a" * 1_001}],  # oversized answer
    ]
    for conversation in invalid_conversations:
        with pytest.raises(ValidationError):
            _rewrite_request(conversation)


def test_rewrite_turn_read_carries_exactly_one_outcome() -> None:
    suggestion = ResumeRewriteSuggestionRead(
        suggestion_id=uuid4(),
        target_kind="bullet",
        section_key="experience",
        item_id="experience_1",
        bullet_index=0,
        mode="stronger",
        before_text="قبل",
        after_text="بعد",
        base_draft_revision=1,
        evidence_handles=["fact_1"],
    )

    suggestion_turn = ResumeRewriteTurnRead(kind="suggestion", suggestion=suggestion)
    assert suggestion_turn.question is None
    question_turn = ResumeRewriteTurnRead(kind="question", question="أي مواد تقصد؟")
    assert question_turn.suggestion is None

    with pytest.raises(ValidationError):
        ResumeRewriteTurnRead(kind="suggestion", suggestion=None)
    with pytest.raises(ValidationError):
        ResumeRewriteTurnRead(kind="suggestion", suggestion=suggestion, question="سؤال؟")
    with pytest.raises(ValidationError):
        ResumeRewriteTurnRead(kind="question", question="   ")
    with pytest.raises(ValidationError):
        ResumeRewriteTurnRead(kind="question", question="سؤال؟", suggestion=suggestion)


@pytest.mark.asyncio
async def test_resume_workspace_read_serializes_persisted_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace = ResumeWorkspace(
            profile=CareerProfile(owner_id="resume-read-owner", full_name="Owner"),
            language=PreferredLanguage.AR,
            current_draft=_draft(),
            section_coverage={"experience": True},
            contact={"email": "owner@example.com"},
            provider="mistral",
            provider_metadata={},
        )
        session.add(workspace)
        await session.commit()

        payload = ResumeWorkspaceRead.model_validate(
            {
                **workspace.__dict__,
                "provider_ready": True,
                "consent_required": True,
                "messages": [],
                "versions": [],
            }
        )
        assert payload.stage is ResumeWorkspaceStage.UNDERSTANDING
        assert payload.current_draft is not None
        assert payload.current_draft.headline == "مهندس برمجيات"
        assert payload.contact.email == "owner@example.com"
        assert payload.conversation_language is PreferredLanguage.AR
