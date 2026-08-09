import io
import zipfile
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from conftest import create_profile_and_source
from sqlalchemy import func, select

from career_agent_api.api import resume_workspace as workspace_api
from career_agent_api.models.domain import (
    CareerProfile,
    ResumeDraftVersion,
    ResumeMessage,
    ResumeWorkspace,
)
from career_agent_api.models.enums import (
    FactCategory,
    PreferredLanguage,
    ResumeDraftVersionReason,
    ResumeMessageKind,
    ResumeMessageRole,
    ResumeMessageStatus,
)
from career_agent_api.schemas.api import ResumeDraftContent, ResumeQuestionRead
from career_agent_api.services.resume_writer import (
    RESUME_SECTION_ORDER,
    ResumeEvidence,
    ResumeWriterOutputError,
    ResumeWriterProvider,
    ResumeWriterTransportError,
)


class StubWorkspaceProvider(ResumeWriterProvider):
    provider_name = "mistral"
    model = "test-resume-model"
    available = True

    def __init__(self) -> None:
        self.question_calls: list[dict[str, object]] = []
        self.draft_calls: list[dict[str, object]] = []
        self.adaptive_calls: list[dict[str, object]] = []

    async def generate_questions(self, **kwargs: object) -> list[ResumeQuestionRead]:
        self.question_calls.append(kwargs)
        category = str(kwargs.get("required_category") or "experience")
        language = kwargs.get("language")
        arabic_questions = {
            "experience": "ما نوع الخبرة العملية التي تريد إبرازها، وما أهم نتيجة حققتها فيها؟",
            "education": "بناءً على خبرتك، ما تخصصك وفي أي جامعة درست ومتى تخرجت؟",
            "project": "ما المشروع الذي يثبت مهاراتك، وما مساهمتك المحددة فيه؟",
            "skill": "أي مهارة استخدمتها فعليًا في هذه التجربة، وكيف استخدمتها؟",
            "certification": "هل لديك شهادة مهنية مرتبطة بمجالك، ومن أي جهة؟",
            "language": "ما اللغات التي تستخدمها، وما مستوى إجادتك الفعلي؟",
            "achievement": "ما الإنجاز الآخر الذي يستحق الظهور في سيرتك؟",
        }
        english_questions = {
            "experience": (
                "Tell me about the experience you want to highlight and its strongest outcome."
            ),
            "education": (
                "Based on your background, what did you study, where, and when did you graduate?"
            ),
            "project": "Which project best demonstrates your skills, and what did you contribute?",
            "skill": "Which skill did you use in that work, and how did you apply it?",
            "certification": (
                "Do you hold a relevant professional certification, and who issued it?"
            ),
            "language": "Which languages do you use, and what is your actual proficiency?",
            "achievement": "What other achievement deserves a place on your resume?",
        }
        question = (
            arabic_questions[category]
            if language is PreferredLanguage.AR
            else english_questions[category]
        )
        return [
            ResumeQuestionRead(
                id=f"ai_{category}_test",
                category=FactCategory(category),
                question=question,
                why_it_matters=(
                    "لجمع تفاصيل دقيقة ومفيدة للسيرة."
                    if language is PreferredLanguage.AR
                    else "It collects precise, useful resume evidence."
                ),
                placeholder=(
                    "اكتب التفاصيل بطريقتك."
                    if language is PreferredLanguage.AR
                    else "Answer in your own words."
                ),
                required=False,
            )
        ]

    async def generate_draft(self, **kwargs: object) -> ResumeDraftContent:
        self.draft_calls.append(kwargs)
        evidence = tuple(kwargs.get("evidence") or ())
        handle = evidence[0].handle if evidence else "missing_evidence"
        english = kwargs.get("language") is PreferredLanguage.EN
        return ResumeDraftContent.model_validate(
            {
                "headline": "Data Analyst" if english else "محلل بيانات",
                "professional_summary": (
                    "Analyzed sales using Power BI at an example company."
                    if english
                    else "حللت المبيعات باستخدام Power BI في شركة تجريبية."
                ),
                "summary_evidence_handles": [handle],
                "sections": [
                    {
                        "key": "experience",
                        "title": "Professional experience" if english else "الخبرة المهنية",
                        "items": [
                            {
                                "id": "experience_1",
                                "title": "Data Analyst" if english else "محلل بيانات",
                                "organization": (
                                    "Example Company" if english else "شركة تجريبية"
                                ),
                                "date_range": None,
                                "location": None,
                                "bullets": [
                                    "Analyzed sales using Power BI"
                                    if english
                                    else "حللت المبيعات باستخدام Power BI"
                                ],
                                "evidence_handles": [handle],
                            }
                        ],
                    }
                ],
            }
        )

    async def generate_adaptive_turn(self, **kwargs: object):
        self.adaptive_calls.append(kwargs)
        assert isinstance(kwargs["conversation_language"], PreferredLanguage)
        answer = str(kwargs["answer"])
        return SimpleNamespace(
            understanding=f"فهمت أنك {answer}",
            proposed_records=[
                {
                    "kind": "experience",
                    "title": "محلل بيانات",
                    "organization": "شركة تجريبية",
                    "responsibilities": [answer],
                    "tools": ["Power BI"],
                    "achievements": ["دعمت قرارات المبيعات"],
                }
            ],
            next_question={
                "id": "gap_education_test",
                "category": "education",
                "fields_requested": ["degree", "institution"],
                "question": "ما تخصصك وفي أي جامعة درست؟",
                "placeholder": "التخصص والجامعة",
                "why_it_matters": "لإكمال قسم التعليم",
                "quick_replies": ["skip"],
            },
            draft_patch={
                "section_key": "experience",
                "title": "محلل بيانات",
                "bullet_candidates": [answer],
                "evidence_handles": ["conversation_1"],
            },
            ready_to_generate=True,
        )

    async def rewrite_section(self, **kwargs: object):
        assert kwargs["instruction"] == "stronger"
        return SimpleNamespace(
            text="حللت المبيعات باستخدام Power BI.",
            evidence_handles=kwargs["evidence_handles"],
        )


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> StubWorkspaceProvider:
    provider = StubWorkspaceProvider()
    monkeypatch.setattr(workspace_api, "get_resume_writer_provider", lambda _settings: provider)
    return provider


async def add_confirmed_experience(client, profile: dict, source: dict, headers: dict) -> dict:
    fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "experience",
            "label": "محلل بيانات",
            "detail": "حللت المبيعات باستخدام Power BI في شركة تجريبية",
        },
    )
    assert fact.status_code == 201, fact.text
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


async def test_workspace_opens_with_an_ai_generated_question_in_resume_order(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    profile, _source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}

    response = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
        json={
            "language": "en",
            "conversation_language": "ar",
            "data_sharing_acknowledged": True,
        },
    )

    assert response.status_code == 201, response.text
    workspace = response.json()
    assert stub_provider.question_calls[0]["required_category"] == "education"
    assert stub_provider.question_calls[0]["max_questions"] == 1
    assert workspace["provider_metadata"]["current_question"]["generation_source"] == "ai"
    assert workspace["provider_metadata"]["current_question"]["category"] == "education"
    assert workspace["provider_metadata"]["section_order"] == list(RESUME_SECTION_ORDER)
    assert workspace["messages"][0]["content"] == (
        "بناءً على خبرتك، ما تخصصك وفي أي جامعة درست ومتى تخرجت؟"
    )


async def test_workspace_ai_question_starts_at_first_uncovered_resume_section(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    await add_confirmed_experience(client, profile, source, headers)

    response = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )

    assert response.status_code == 201, response.text
    assert stub_provider.question_calls[-1]["required_category"] == "education"
    assert response.json()["provider_metadata"]["current_question"]["category"] == "education"


async def create_generated_workspace(client) -> tuple[dict, str, dict, dict]:
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    await add_confirmed_experience(client, profile, source, headers)
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={
            "language": "ar",
            "contact": {"email": "reviewed@example.test"},
            "data_sharing_acknowledged": True,
        },
    )
    assert started.status_code == 201, started.text
    generated = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "أنشئ المسودة",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )
    assert generated.status_code == 200, generated.text
    return profile, base, headers, generated.json()


async def create_reviewed_workspace(client) -> tuple[dict, str, dict, dict]:
    profile, base, headers, workspace = await create_generated_workspace(client)
    reviewed = await client.post(
        f"{base}/review",
        headers=headers,
        json={
            "expected_draft_revision": workspace["draft_revision"],
            "review_acknowledged": True,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    return profile, base, headers, workspace


async def test_workspace_persists_adaptive_turn_draft_rewrite_and_review(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, _ = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"

    started = await client.post(
        base,
        headers=headers,
        json={
            "language": "ar",
            "contact": {"email": "user@example.test"},
            "data_sharing_acknowledged": True,
        },
    )
    assert started.status_code == 201, started.text
    workspace = started.json()
    assert workspace["revision"] == 0
    assert workspace["consent_required"] is False
    assert workspace["messages"][0]["kind"] == "question"

    client_turn_id = str(uuid4())
    answered = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "حللت المبيعات باستخدام Power BI",
            "client_turn_id": client_turn_id,
            "expected_revision": 0,
        },
    )
    assert answered.status_code == 200, answered.text
    workspace = answered.json()
    understanding = workspace["pending_understanding"]
    assert understanding["proposed_records"][0]["title"] == "محلل بيانات"
    assert workspace["current_draft"] is None

    duplicate = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "لن تتكرر",
            "client_turn_id": client_turn_id,
            "expected_revision": 0,
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["revision"] == workspace["revision"]

    confirmed = await client.post(
        f"{base}/understandings/{understanding['id']}/confirm",
        headers=headers,
        json={"expected_revision": workspace["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    workspace = confirmed.json()
    assert workspace["current_draft"]["sections"][0]["items"][0]["bullets"]
    item_handles = workspace["current_draft"]["sections"][0]["items"][0][
        "evidence_handles"
    ]
    assert item_handles[0].startswith("fact_")
    assert "conversation_1" not in item_handles
    assert workspace["draft_revision"] == 1
    assert workspace["versions"][0]["reason"] == "initial_generation"
    assert workspace["provider_metadata"]["current_question"]["category"] == "education"
    assert workspace["messages"][-1]["kind"] == "question"
    assert workspace["messages"][-1]["structured_payload"]["question"]["category"] == "education"

    rewrite = await client.post(
        f"{base}/draft/rewrite",
        headers=headers,
        json={
            "target_kind": "bullet",
            "section_key": "experience",
            "item_id": workspace["current_draft"]["sections"][0]["items"][0]["id"],
            "bullet_index": 0,
            "mode": "stronger",
            "expected_draft_revision": 1,
        },
    )
    assert rewrite.status_code == 200, rewrite.text
    suggestion = rewrite.json()
    assert suggestion["before_text"] != suggestion["after_text"]

    rewrite_reloaded = await client.get(base, headers=headers)
    assert rewrite_reloaded.status_code == 200
    assert rewrite_reloaded.json()["stage"] == "review"
    assert rewrite_reloaded.json()["pending_suggestion"]["suggestion_id"] == suggestion[
        "suggestion_id"
    ]

    accepted = await client.post(
        f"{base}/draft/suggestions/{suggestion['suggestion_id']}/accept",
        headers=headers,
        json={"expected_draft_revision": 1},
    )
    assert accepted.status_code == 200, accepted.text
    workspace = accepted.json()
    bullet = workspace["current_draft"]["sections"][0]["items"][0]["bullets"][0]
    assert bullet == suggestion["after_text"]
    assert workspace["draft_revision"] == 2

    reviewed = await client.post(
        f"{base}/review",
        headers=headers,
        json={"expected_draft_revision": 2, "review_acknowledged": True},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["export_allowed"] is True

    reloaded = await client.get(base, headers=headers)
    assert reloaded.status_code == 200
    assert reloaded.json()["current_draft"] == workspace["current_draft"]
    assert len(reloaded.json()["versions"]) == 3


async def test_draft_patch_and_restore_clear_pending_rewrite_suggestions(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    _profile, base, headers, workspace = await create_generated_workspace(client)
    initial_version_id = workspace["versions"][0]["id"]
    rewrite_payload = {
        "target_kind": "bullet",
        "section_key": "experience",
        "item_id": workspace["current_draft"]["sections"][0]["items"][0]["id"],
        "bullet_index": 0,
        "mode": "stronger",
    }

    suggested_before_patch = await client.post(
        f"{base}/draft/rewrite",
        headers=headers,
        json={**rewrite_payload, "expected_draft_revision": 1},
    )
    assert suggested_before_patch.status_code == 200, suggested_before_patch.text
    patched = await client.patch(
        f"{base}/draft",
        headers=headers,
        json={
            "draft": workspace["current_draft"],
            "expected_draft_revision": 1,
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["pending_suggestion"] is None
    assert patched.json()["stage"] == "writing"

    suggested_before_restore = await client.post(
        f"{base}/draft/rewrite",
        headers=headers,
        json={**rewrite_payload, "expected_draft_revision": 2},
    )
    assert suggested_before_restore.status_code == 200, suggested_before_restore.text
    restored = await client.post(
        f"{base}/versions/{initial_version_id}/restore",
        headers=headers,
        json={"expected_draft_revision": 2},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["pending_suggestion"] is None
    assert restored.json()["stage"] == "writing"


async def test_accept_rejects_a_suggestion_based_on_an_older_draft(
    client,
    session_factory,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, base, headers, workspace = await create_generated_workspace(client)
    rewrite = await client.post(
        f"{base}/draft/rewrite",
        headers=headers,
        json={
            "target_kind": "bullet",
            "section_key": "experience",
            "item_id": workspace["current_draft"]["sections"][0]["items"][0]["id"],
            "bullet_index": 0,
            "mode": "stronger",
            "expected_draft_revision": 1,
        },
    )
    assert rewrite.status_code == 200, rewrite.text

    # Simulate a legacy/concurrent mutation that advanced the draft but left an old
    # suggestion behind. The endpoint must defend itself even if invalidation was missed.
    async with session_factory() as session:
        stored = await session.scalar(
            select(ResumeWorkspace).where(
                ResumeWorkspace.profile_id == UUID(profile["id"])
            )
        )
        assert stored is not None
        stored.draft_revision += 1
        stored.revision += 1
        await session.commit()

    stale_accept = await client.post(
        f"{base}/draft/suggestions/{rewrite.json()['suggestion_id']}/accept",
        headers=headers,
        json={"expected_draft_revision": 2},
    )
    assert stale_accept.status_code == 409
    assert stale_accept.json()["detail"]["code"] == "resume_suggestion_stale"
    assert rewrite.json()["after_text"] not in stale_accept.text


async def test_autosave_retention_preserves_semantic_versions_and_old_restore(
    client,
    session_factory,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    _profile, base, headers, workspace = await create_generated_workspace(client)
    initial_version_id = workspace["versions"][0]["id"]
    rewrite = await client.post(
        f"{base}/draft/rewrite",
        headers=headers,
        json={
            "target_kind": "bullet",
            "section_key": "experience",
            "item_id": workspace["current_draft"]["sections"][0]["items"][0]["id"],
            "bullet_index": 0,
            "mode": "stronger",
            "expected_draft_revision": 1,
        },
    )
    assert rewrite.status_code == 200, rewrite.text
    accepted = await client.post(
        f"{base}/draft/suggestions/{rewrite.json()['suggestion_id']}/accept",
        headers=headers,
        json={"expected_draft_revision": 1},
    )
    assert accepted.status_code == 200, accepted.text
    accepted_version_id = accepted.json()["versions"][-1]["id"]
    reviewed = await client.post(
        f"{base}/review",
        headers=headers,
        json={"expected_draft_revision": 2, "review_acknowledged": True},
    )
    assert reviewed.status_code == 200, reviewed.text
    review_version_id = reviewed.json()["draft_version_id"]
    restored = await client.post(
        f"{base}/versions/{initial_version_id}/restore",
        headers=headers,
        json={"expected_draft_revision": 2},
    )
    assert restored.status_code == 200, restored.text
    restore_version_id = restored.json()["versions"][-1]["id"]
    workspace = restored.json()

    for _ in range(workspace_api.AUTOSAVE_SNAPSHOT_LIMIT + 5):
        patched = await client.patch(
            f"{base}/draft",
            headers=headers,
            json={
                "draft": workspace["current_draft"],
                "expected_draft_revision": workspace["draft_revision"],
            },
        )
        assert patched.status_code == 200, patched.text
        workspace = patched.json()

    async with session_factory() as session:
        stored_versions = list(
            (
                await session.scalars(
                    select(ResumeDraftVersion).where(
                        ResumeDraftVersion.workspace_id == UUID(workspace["id"])
                    )
                )
            ).all()
        )
    autosaves = [
        version
        for version in stored_versions
        if version.reason is ResumeDraftVersionReason.MANUAL_EDIT
    ]
    assert len(autosaves) == workspace_api.AUTOSAVE_SNAPSHOT_LIMIT
    stored_ids = {str(version.id) for version in stored_versions}
    assert {
        initial_version_id,
        accepted_version_id,
        review_version_id,
        restore_version_id,
    } <= stored_ids
    assert len(workspace["versions"]) == workspace_api.WORKSPACE_VERSION_RESPONSE_LIMIT
    assert initial_version_id not in {item["id"] for item in workspace["versions"]}

    history = await client.get(f"{base}/versions", headers=headers)
    assert history.status_code == 200, history.text
    assert len(history.json()) == workspace_api.VERSION_HISTORY_DEFAULT_LIMIT
    history_versions = [item["version"] for item in history.json()]
    assert history_versions == sorted(history_versions, reverse=True)
    short_history = await client.get(f"{base}/versions?limit=5", headers=headers)
    assert short_history.status_code == 200, short_history.text
    assert len(short_history.json()) == 5

    restored_old_version = await client.post(
        f"{base}/versions/{initial_version_id}/restore",
        headers=headers,
        json={"expected_draft_revision": workspace["draft_revision"]},
    )
    assert restored_old_version.status_code == 200, restored_old_version.text


async def test_workspace_returns_only_recent_messages_but_keeps_old_idempotency(
    client,
    session_factory,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, _source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    assert started.status_code == 201, started.text
    old_turn_id = uuid4()
    inserted_count = workspace_api.WORKSPACE_MESSAGE_RESPONSE_LIMIT + 10
    async with session_factory() as session:
        stored_workspace = await session.scalar(
            select(ResumeWorkspace).where(
                ResumeWorkspace.profile_id == UUID(profile["id"])
            )
        )
        assert stored_workspace is not None
        session.add_all(
            [
                ResumeMessage(
                    workspace_id=stored_workspace.id,
                    sequence=sequence,
                    role=ResumeMessageRole.USER,
                    kind=ResumeMessageKind.TEXT,
                    content=f"message-{sequence}",
                    structured_payload={},
                    status=ResumeMessageStatus.SENT,
                    client_turn_id=old_turn_id if sequence == 2 else None,
                )
                for sequence in range(2, inserted_count + 2)
            ]
        )
        await session.commit()

    reloaded = await client.get(base, headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    messages = reloaded.json()["messages"]
    assert len(messages) == workspace_api.WORKSPACE_MESSAGE_RESPONSE_LIMIT
    assert messages[0]["sequence"] == inserted_count + 2 - len(messages)
    assert messages[-1]["sequence"] == inserted_count + 1

    duplicate = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "must not be inserted again",
            "client_turn_id": str(old_turn_id),
            "expected_revision": started.json()["revision"],
        },
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["messages"][-1]["sequence"] == inserted_count + 1


async def test_workspace_rejects_stale_conversation_revision(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, _ = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    assert started.status_code == 201

    stale = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "إجابة",
            "client_turn_id": str(uuid4()),
            "expected_revision": 99,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "resume_workspace_revision_conflict"


async def test_workspace_separates_arabic_conversation_from_english_resume(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    profile, _source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"

    started_response = await client.post(
        base,
        headers=headers,
        json={
            "language": "en",
            "conversation_language": "ar",
            "data_sharing_acknowledged": True,
        },
    )
    assert started_response.status_code == 201, started_response.text
    started = started_response.json()
    assert started["language"] == "en"
    assert started["conversation_language"] == "ar"
    assert any("\u0621" <= character <= "\u064a" for character in started["messages"][0]["content"])

    answered_response = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "حللت المبيعات باستخدام Power BI في شركة تجريبية.",
            "client_turn_id": str(uuid4()),
            "expected_revision": started["revision"],
        },
    )
    assert answered_response.status_code == 200, answered_response.text
    answered = answered_response.json()
    adaptive_call = stub_provider.adaptive_calls[-1]
    assert adaptive_call["conversation_language"] is PreferredLanguage.AR
    assert adaptive_call["output_language"] is PreferredLanguage.EN

    confirmed_response = await client.post(
        f"{base}/understandings/{answered['pending_understanding']['id']}/confirm",
        headers=headers,
        json={"expected_revision": answered["revision"]},
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    confirmed = confirmed_response.json()
    assert confirmed["current_draft"]["headline"] == "Data Analyst"
    assert stub_provider.draft_calls[-1]["language"] is PreferredLanguage.EN


async def test_start_without_conversation_language_keeps_legacy_single_language_behavior(
    client,
    session_factory,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, _source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started_response = await client.post(
        base,
        headers=headers,
        json={"language": "en", "data_sharing_acknowledged": True},
    )
    assert started_response.status_code == 201, started_response.text
    started = started_response.json()
    assert started["conversation_language"] == "en"
    assert started["messages"][0]["content"].startswith("Based on your background")

    # Simulate a row created before conversation_language was persisted in provider metadata.
    async with session_factory() as session:
        stored = await session.scalar(
            select(ResumeWorkspace).where(ResumeWorkspace.id == UUID(started["id"]))
        )
        assert stored is not None
        stored.provider_metadata = {
            key: value
            for key, value in stored.provider_metadata.items()
            if key != "conversation_language"
        }
        await session.commit()

    reloaded_response = await client.get(base, headers=headers)
    assert reloaded_response.status_code == 200, reloaded_response.text
    assert reloaded_response.json()["conversation_language"] == "en"


async def test_conversation_language_can_change_before_answers_but_not_after(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, _source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = (
        await client.post(
            base,
            headers=headers,
            json={
                "language": "en",
                "conversation_language": "ar",
                "data_sharing_acknowledged": True,
            },
        )
    ).json()

    changed_response = await client.post(
        base,
        headers=headers,
        json={
            "language": "en",
            "conversation_language": "en",
            "data_sharing_acknowledged": True,
        },
    )
    assert changed_response.status_code == 201, changed_response.text
    changed = changed_response.json()
    assert changed["conversation_language"] == "en"
    assert changed["revision"] == started["revision"] + 1
    assert len(changed["messages"]) == 1
    assert changed["messages"][0]["content"].startswith("Based on your background")
    assert changed["provider_metadata"]["current_question"]["question"].startswith(
        "Based on your background"
    )

    answered_response = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "I analyzed sales using Power BI.",
            "client_turn_id": str(uuid4()),
            "expected_revision": changed["revision"],
        },
    )
    assert answered_response.status_code == 200, answered_response.text
    answered = answered_response.json()

    rejected = await client.post(
        base,
        headers=headers,
        json={
            "language": "en",
            "conversation_language": "ar",
            "data_sharing_acknowledged": True,
        },
    )
    assert rejected.status_code == 409
    assert (
        rejected.json()["detail"]["code"]
        == "resume_conversation_language_change_not_allowed"
    )
    current = (await client.get(base, headers=headers)).json()
    assert current["conversation_language"] == "en"
    assert current["revision"] == answered["revision"]
    assert current["pending_understanding"]["id"] == answered["pending_understanding"]["id"]


async def test_mismatched_adaptive_patch_does_not_mutate_existing_output_language_draft(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    profile, _source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = (
        await client.post(
            base,
            headers=headers,
            json={
                "language": "en",
                "conversation_language": "ar",
                "data_sharing_acknowledged": True,
            },
        )
    ).json()
    first_answer = (
        await client.post(
            f"{base}/messages",
            headers=headers,
            json={
                "content": "حللت المبيعات باستخدام Power BI في شركة تجريبية.",
                "client_turn_id": str(uuid4()),
                "expected_revision": started["revision"],
            },
        )
    ).json()
    first_confirmed = (
        await client.post(
            f"{base}/understandings/{first_answer['pending_understanding']['id']}/confirm",
            headers=headers,
            json={"expected_revision": first_answer["revision"]},
        )
    ).json()
    original_draft = deepcopy(first_confirmed["current_draft"])
    original_draft_revision = first_confirmed["draft_revision"]

    second_answer_response = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "أنشأت تقارير عربية أسبوعية للمبيعات.",
            "client_turn_id": str(uuid4()),
            "expected_revision": first_confirmed["revision"],
        },
    )
    assert second_answer_response.status_code == 200, second_answer_response.text
    second_answer = second_answer_response.json()
    assert stub_provider.adaptive_calls[-1]["output_language"] is PreferredLanguage.EN

    second_confirmed_response = await client.post(
        f"{base}/understandings/{second_answer['pending_understanding']['id']}/confirm",
        headers=headers,
        json={"expected_revision": second_answer["revision"]},
    )
    assert second_confirmed_response.status_code == 200, second_confirmed_response.text
    second_confirmed = second_confirmed_response.json()
    assert second_confirmed["current_draft"] == original_draft
    assert second_confirmed["draft_revision"] == original_draft_revision
    assert (
        second_confirmed["provider_metadata"]["generation_warning"]
        == "draft_patch_language_mismatch"
    )


async def test_reset_workspace_is_guarded_idempotent_and_preserves_confirmed_facts(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, _source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = (
        await client.post(
            base,
            headers=headers,
            json={
                "language": "en",
                "conversation_language": "ar",
                "data_sharing_acknowledged": True,
            },
        )
    ).json()
    answered = (
        await client.post(
            f"{base}/messages",
            headers=headers,
            json={
                "content": "حللت المبيعات باستخدام Power BI في شركة تجريبية.",
                "client_turn_id": str(uuid4()),
                "expected_revision": started["revision"],
            },
        )
    ).json()
    confirmed_response = await client.post(
        f"{base}/understandings/{answered['pending_understanding']['id']}/confirm",
        headers=headers,
        json={"expected_revision": answered["revision"]},
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    confirmed = confirmed_response.json()
    old_workspace_id = confirmed["id"]
    facts_before = (
        await client.get(f"/v1/profiles/{profile['id']}/facts", headers=headers)
    ).json()
    assert facts_before

    stale = await client.delete(
        base,
        headers=headers,
        params={"expected_revision": confirmed["revision"] - 1},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "resume_workspace_revision_conflict"

    reset = await client.delete(
        base,
        headers=headers,
        params={"expected_revision": confirmed["revision"]},
    )
    assert reset.status_code == 204, reset.text
    assert reset.content == b""
    assert (await client.get(base, headers=headers)).status_code == 404
    facts_after = (
        await client.get(f"/v1/profiles/{profile['id']}/facts", headers=headers)
    ).json()
    assert {fact["id"] for fact in facts_after} == {fact["id"] for fact in facts_before}

    repeated = await client.delete(
        base,
        headers=headers,
        params={"expected_revision": confirmed["revision"]},
    )
    assert repeated.status_code == 204

    restarted_response = await client.post(
        base,
        headers=headers,
        json={
            "language": "en",
            "conversation_language": "ar",
            "data_sharing_acknowledged": True,
        },
    )
    assert restarted_response.status_code == 201, restarted_response.text
    restarted = restarted_response.json()
    assert restarted["id"] != old_workspace_id
    assert restarted["revision"] == 0
    assert restarted["conversation_language"] == "ar"


async def test_reset_explicitly_removes_all_limited_messages_and_chained_versions(
    client,
    session_factory,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    _profile, base, headers, workspace = await create_generated_workspace(client)
    workspace_id = UUID(workspace["id"])
    draft = deepcopy(workspace["current_draft"])

    async with session_factory() as session:
        stored = await session.scalar(
            select(ResumeWorkspace).where(ResumeWorkspace.id == workspace_id)
        )
        assert stored is not None
        last_sequence = await session.scalar(
            select(func.max(ResumeMessage.sequence)).where(
                ResumeMessage.workspace_id == workspace_id
            )
        )
        for offset in range(60):
            session.add(
                ResumeMessage(
                    workspace_id=workspace_id,
                    sequence=int(last_sequence or 0) + offset + 1,
                    role=ResumeMessageRole.ASSISTANT,
                    kind=ResumeMessageKind.STATUS,
                    content=f"historical-message-{offset}",
                    structured_payload={},
                    status=ResumeMessageStatus.SENT,
                )
            )

        previous_version = await session.scalar(
            select(ResumeDraftVersion)
            .where(ResumeDraftVersion.workspace_id == workspace_id)
            .order_by(ResumeDraftVersion.version.desc())
            .limit(1)
        )
        assert previous_version is not None
        for version_number in range(previous_version.version + 1, 27):
            version = ResumeDraftVersion(
                workspace_id=workspace_id,
                version=version_number,
                base_version_id=previous_version.id,
                reason=ResumeDraftVersionReason.MANUAL_EDIT,
                content=draft,
                evidence_revision=stored.evidence_revision,
            )
            session.add(version)
            await session.flush()
            previous_version = version
        await session.commit()

        message_count = await session.scalar(
            select(func.count(ResumeMessage.id)).where(
                ResumeMessage.workspace_id == workspace_id
            )
        )
        version_count = await session.scalar(
            select(func.count(ResumeDraftVersion.id)).where(
                ResumeDraftVersion.workspace_id == workspace_id
            )
        )
        assert int(message_count or 0) > workspace_api.WORKSPACE_MESSAGE_RESPONSE_LIMIT
        assert int(version_count or 0) > workspace_api.WORKSPACE_VERSION_RESPONSE_LIMIT

    reset = await client.delete(
        base,
        headers=headers,
        params={"expected_revision": workspace["revision"]},
    )
    assert reset.status_code == 204, reset.text

    async with session_factory() as session:
        assert await session.get(ResumeWorkspace, workspace_id) is None
        assert not list(
            (
                await session.scalars(
                    select(ResumeMessage.id).where(
                        ResumeMessage.workspace_id == workspace_id
                    )
                )
            ).all()
        )
        assert not list(
            (
                await session.scalars(
                    select(ResumeDraftVersion.id).where(
                        ResumeDraftVersion.workspace_id == workspace_id
                    )
                )
            ).all()
        )


async def test_explicit_generation_uses_existing_evidence_without_saving_a_negative_answer(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"

    fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "experience",
            "label": "محلل بيانات",
            "detail": "حللت المبيعات باستخدام Power BI في شركة تجريبية",
        },
    )
    assert fact.status_code == 201, fact.text
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    facts_before = await client.get(f"/v1/profiles/{profile['id']}/facts", headers=headers)
    assert facts_before.status_code == 200

    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    assert started.status_code == 201

    answered = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "اكتب سيرتي من المعلومات المؤكدة.",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": 0,
        },
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["pending_understanding"] is None
    assert answered.json()["current_draft"]["professional_summary"]
    workspace = answered.json()
    for action in ("improve", "review"):
        command = await client.post(
            f"{base}/messages",
            headers=headers,
            json={
                "content": f"command:{action}",
                "quick_action": action,
                "client_turn_id": str(uuid4()),
                "expected_revision": workspace["revision"],
            },
        )
        assert command.status_code == 200, command.text
        workspace = command.json()
        assert workspace["pending_understanding"] is None

    facts = await client.get(f"/v1/profiles/{profile['id']}/facts", headers=headers)
    assert facts.status_code == 200
    assert len(facts.json()) == len(facts_before.json())


@pytest.mark.parametrize("provider_failure", ["request timed out", "401 unauthorized"])
async def test_workspace_maps_mistral_transport_failures_to_retryable_503(
    client,
    stub_provider: StubWorkspaceProvider,
    monkeypatch: pytest.MonkeyPatch,
    provider_failure: str,
) -> None:
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    await add_confirmed_experience(client, profile, source, headers)
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "en", "data_sharing_acknowledged": True},
    )
    assert started.status_code == 201, started.text

    async def fail_generation(**_kwargs: object) -> ResumeDraftContent:
        raise ResumeWriterTransportError(provider_failure, transient=True)

    monkeypatch.setattr(stub_provider, "generate_draft", fail_generation)
    failed = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "Generate my resume.",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )

    assert failed.status_code == 503, failed.text
    detail = failed.json()["detail"]
    assert detail["code"] == "resume_writer_unavailable"
    assert detail["message"] == (
        "The AI resume writer is temporarily unavailable; retry the command"
    )
    assert UUID(detail["request_id"])
    assert provider_failure not in failed.text


@pytest.mark.parametrize("failure_kind", ["transport", "output"])
async def test_failed_regeneration_preserves_current_draft_and_workspace_can_retry(
    client,
    stub_provider: StubWorkspaceProvider,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    _profile, base, headers, workspace = await create_generated_workspace(client)
    original_draft = deepcopy(workspace["current_draft"])
    original_revision = workspace["revision"]
    original_draft_revision = workspace["draft_revision"]
    working_generation = stub_provider.generate_draft

    async def fail_generation(**_kwargs: object) -> ResumeDraftContent:
        if failure_kind == "output":
            raise ResumeWriterOutputError("no usable grounded draft")
        raise ResumeWriterTransportError("request timed out", transient=True)

    monkeypatch.setattr(stub_provider, "generate_draft", fail_generation)
    failed = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "Retry generating my resume.",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": original_revision,
        },
    )

    assert failed.status_code == 200, failed.text
    fallback = failed.json()
    assert fallback["current_draft"] == original_draft
    assert fallback["revision"] == original_revision + 1
    assert fallback["draft_revision"] == original_draft_revision
    assert fallback["stage"] == "writing"
    assert fallback["provider_metadata"]["generation_warning"] == (
        "ai_unavailable_existing_draft_preserved"
    )
    reloaded = await client.get(base, headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    persisted = reloaded.json()
    assert persisted["current_draft"] == original_draft
    assert persisted["revision"] == fallback["revision"]
    assert persisted["draft_revision"] == original_draft_revision
    assert persisted["stage"] == "writing"

    monkeypatch.setattr(stub_provider, "generate_draft", working_generation)
    retried = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "Retry generating my resume.",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": persisted["revision"],
        },
    )

    assert retried.status_code == 200, retried.text
    assert retried.json()["current_draft"]
    assert retried.json()["draft_revision"] == original_draft_revision + 1


@pytest.mark.parametrize("failure_kind", ["transport", "output"])
async def test_initial_generate_uses_same_language_evidence_fallback_on_provider_failure(
    client,
    stub_provider: StubWorkspaceProvider,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    responsibility = "Prepared monthly cost reports using Excel."
    fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "experience",
            "label": "Cost Analyst",
            "detail": f"Cost Analyst at Harbor Company. {responsibility}",
            "structured_value": {
                "title": "Cost Analyst",
                "organization": "Harbor Company",
                "date_range": "2024 - Present",
                "responsibilities": [responsibility],
            },
            "source_excerpt": (
                "Cost Analyst | Harbor Company | 2024 - Present\n" + responsibility
            ),
        },
    )
    assert fact.status_code == 201, fact.text
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "en", "data_sharing_acknowledged": True},
    )
    assert started.status_code == 201, started.text

    async def fail_generation(**_kwargs: object) -> ResumeDraftContent:
        if failure_kind == "output":
            raise ResumeWriterOutputError("no usable grounded draft")
        raise ResumeWriterTransportError("request timed out", transient=True)

    monkeypatch.setattr(stub_provider, "generate_draft", fail_generation)
    generated = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "Generate my resume.",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )

    assert generated.status_code == 200, generated.text
    workspace = generated.json()
    draft = workspace["current_draft"]
    assert workspace["provider_metadata"]["generation_warning"] == (
        "ai_unavailable_evidence_fallback_created"
    )
    assert draft["headline"] == "Cost Analyst"
    assert draft["professional_summary"] == responsibility
    assert len(draft["summary_evidence_handles"]) == 1
    assert [section["key"] for section in draft["sections"]] == ["experience"]
    item = draft["sections"][0]["items"][0]
    assert item["title"] == "Cost Analyst"
    assert item["organization"] == "Harbor Company"
    assert item["date_range"] == "2024 - Present"
    assert item["bullets"] == [responsibility]
    assert item["evidence_handles"] == draft["summary_evidence_handles"]

    reviewed = await client.post(
        f"{base}/review",
        headers=headers,
        json={
            "expected_draft_revision": workspace["draft_revision"],
            "review_acknowledged": True,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "export_ready"
    assert reviewed.json()["export_allowed"] is True
    monkeypatch.setattr(workspace_api, "render_resume_pdf", lambda **_: b"%PDF-fallback")
    exported = await client.post(
        f"{base}/export.pdf",
        headers=headers,
        json={
            "expected_draft_revision": workspace["draft_revision"],
            "review_acknowledged": True,
        },
    )
    assert exported.status_code == 200, exported.text
    assert exported.content == b"%PDF-fallback"


@pytest.mark.parametrize(
    ("organization", "transient"),
    [
        pytest.param("شركة الميناء", True, id="mixed-language-transient"),
        pytest.param("Harbor Company", False, id="same-language-401"),
    ],
)
async def test_initial_transport_failure_does_not_create_an_unsafe_fallback(
    client,
    stub_provider: StubWorkspaceProvider,
    monkeypatch: pytest.MonkeyPatch,
    organization: str,
    transient: bool,
) -> None:
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    responsibility = "Prepared monthly cost reports using Excel."
    fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "experience",
            "label": "Cost Analyst",
            "detail": responsibility,
            "structured_value": {
                "title": "Cost Analyst",
                "organization": organization,
                "date_range": "2024 - Present",
                "responsibilities": [responsibility],
            },
            "source_excerpt": responsibility,
        },
    )
    assert fact.status_code == 201, fact.text
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "en", "data_sharing_acknowledged": True},
    )
    assert started.status_code == 201, started.text

    async def fail_generation(**_kwargs: object) -> ResumeDraftContent:
        message = "request timed out" if transient else "401 unauthorized"
        raise ResumeWriterTransportError(message, transient=transient)

    monkeypatch.setattr(stub_provider, "generate_draft", fail_generation)
    generated = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "Generate my resume.",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )

    assert generated.status_code == 503, generated.text
    assert generated.json()["detail"]["code"] == "resume_writer_unavailable"
    reloaded = await client.get(base, headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["current_draft"] is None
    assert reloaded.json()["draft_revision"] == 0


async def test_transport_fallback_preserves_exact_displayable_gpa_and_passes_review(
    client,
    stub_provider: StubWorkspaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "education",
            "label": "Bachelor of Science in Finance",
            "detail": (
                "Completed a Bachelor of Science in Finance at Harbor University in 2023."
            ),
            "structured_value": {
                "degree": "Bachelor of Science in Finance",
                "institution": "Harbor University",
                "date_range": "2023",
                "gpa_score": "3.6",
                "gpa_scale": "4",
                "gpa_display_recommended": True,
            },
            "source_excerpt": "Bachelor of Science in Finance, GPA: 3.6/4",
        },
    )
    assert fact.status_code == 201, fact.text
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "en", "data_sharing_acknowledged": True},
    )
    assert started.status_code == 201, started.text

    async def fail_generation(**_kwargs: object) -> ResumeDraftContent:
        raise ResumeWriterTransportError("request timed out", transient=True)

    monkeypatch.setattr(stub_provider, "generate_draft", fail_generation)
    generated = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "Generate my resume.",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )

    assert generated.status_code == 200, generated.text
    workspace = generated.json()
    education = next(
        section for section in workspace["current_draft"]["sections"]
        if section["key"] == "education"
    )
    assert education["items"][0]["bullets"] == ["GPA: 3.6/4"]
    reviewed = await client.post(
        f"{base}/review",
        headers=headers,
        json={
            "expected_draft_revision": workspace["draft_revision"],
            "review_acknowledged": True,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["export_allowed"] is True


async def test_correcting_understanding_invalidates_all_dependent_ai_output_and_source(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, onboarding_source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    answered = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "حللت المبيعات باستخدام Power BI",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )
    understanding_id = answered.json()["pending_understanding"]["id"]
    corrected = await client.post(
        f"{base}/understandings/{understanding_id}/correct",
        headers=headers,
        json={
            "expected_revision": answered.json()["revision"],
            "corrected_text": "نسّقت تقارير الفريق الأسبوعية",
        },
    )
    assert corrected.status_code == 200, corrected.text
    pending = corrected.json()["pending_understanding"]
    assert pending["draft_patch"] is None
    assert pending["next_question"] is None
    assert pending["ready_to_generate"] is False

    confirmed = await client.post(
        f"{base}/understandings/{understanding_id}/confirm",
        headers=headers,
        json={"expected_revision": corrected.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["current_draft"] is None

    facts = (await client.get(f"/v1/profiles/{profile['id']}/facts", headers=headers)).json()
    corrected_fact = next(fact for fact in facts if fact["label"] == "نسّقت تقارير الفريق الأسبوعية")
    assert corrected_fact["source_id"] != onboarding_source["id"]
    sources = (
        await client.get(f"/v1/profiles/{profile['id']}/sources", headers=headers)
    ).json()
    workspace_source = next(
        source
        for source in sources
        if source["source_metadata"].get("created_by") == "resume_workspace_v2"
    )
    assert corrected_fact["source_id"] == workspace_source["id"]


async def test_ephemeral_patch_without_persisted_fact_is_discarded(
    client,
    stub_provider: StubWorkspaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unsupported_patch(**_: object):
        return SimpleNamespace(
            understanding="لم أستخرج حقيقة مهنية مؤكدة.",
            proposed_records=[],
            next_question=None,
            draft_patch={
                "section_key": "experience",
                "title": "ادعاء غير مؤكد",
                "bullet_candidates": ["نص غير مؤكد"],
                "evidence_handles": ["answer_missing"],
            },
            ready_to_generate=False,
        )

    monkeypatch.setattr(stub_provider, "generate_adaptive_turn", unsupported_patch)
    profile, _ = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    answered = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "أمر لا يحتوي حقيقة",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )
    pending = answered.json()["pending_understanding"]
    confirmed = await client.post(
        f"{base}/understandings/{pending['id']}/confirm",
        headers=headers,
        json={"expected_revision": answered.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["current_draft"] is None


@pytest.mark.parametrize(
    "action",
    ["show_example", "no_exact_metric", "skip", "continue"],
)
async def test_guidance_quick_actions_never_create_facts_or_understandings(
    client,
    stub_provider: StubWorkspaceProvider,
    action: str,
) -> None:
    profile, _ = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    facts_before = (
        await client.get(f"/v1/profiles/{profile['id']}/facts", headers=headers)
    ).json()
    response = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": f"command:{action}",
            "quick_action": action,
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["pending_understanding"] is None
    if action in {"skip", "continue"}:
        assert stub_provider.question_calls[-1]["required_category"] == "experience"
        assert (
            response.json()["provider_metadata"]["current_question"]["category"]
            == "experience"
        )
    facts_after = (
        await client.get(f"/v1/profiles/{profile['id']}/facts", headers=headers)
    ).json()
    assert len(facts_after) == len(facts_before)


def _coursework_review_blockers(
    *,
    section_key: str,
    evidence: tuple[ResumeEvidence, ...],
    bullet: str,
    item_id: str,
    title: str,
    organization: str,
    date_range: str,
) -> list[str]:
    primary_evidence = evidence[0]
    draft = ResumeDraftContent.model_validate(
        {
            "headline": primary_evidence.label,
            "professional_summary": primary_evidence.detail or primary_evidence.label,
            "summary_evidence_handles": [primary_evidence.handle],
            "sections": [
                {
                    "key": section_key,
                    "title": section_key.replace("_", " ").title(),
                    "items": [
                        {
                            "id": item_id,
                            "title": title,
                            "organization": organization,
                            "date_range": date_range,
                            "location": None,
                            "bullets": [bullet],
                            "evidence_handles": [item.handle for item in evidence],
                        }
                    ],
                }
            ],
        }
    )
    workspace = SimpleNamespace(
        pending_understanding=None,
        pending_suggestion=None,
    )

    return workspace_api._review_blockers(draft, workspace, evidence)


def test_review_accepts_combined_coursework_bullet_from_structured_education_fact() -> None:
    coursework = [
        "Auditing",
        "Financial Accounting",
        "Risk Management",
        "Cost Control",
        "Internal Control Systems",
        "Financial Modelling",
    ]
    education = ResumeEvidence(
        handle="education_fact",
        category="education",
        label="Bachelor of Science in Finance",
        detail="Bachelor of Science in Finance at Harbor University, completed 2023",
        verification_status="confirmed",
        structured_value={
            "degree": "Bachelor of Science in Finance",
            "institution": "Harbor University",
            "date_range": "2023",
            "coursework": coursework,
        },
        source_excerpt=(
            "Education\nBachelor of Science in Finance\nHarbor University\n"
            f"Relevant Courses: {', '.join(coursework)}"
        ),
    )
    blockers = _coursework_review_blockers(
        section_key="education",
        evidence=(education,),
        bullet=f"Relevant Coursework: {', '.join(coursework)}",
        item_id="finance_degree",
        title="Bachelor of Science in Finance",
        organization="Harbor University",
        date_range="2023",
    )

    assert not [blocker for blocker in blockers if blocker.startswith("unsupported_claim:")]


def test_review_accepts_legacy_coursework_found_only_in_source_excerpt() -> None:
    coursework = [
        "Auditing",
        "Financial Accounting",
        "Risk Management",
        "Cost Control",
        "Internal Control Systems",
        "Financial Modelling",
    ]
    education = ResumeEvidence(
        handle="legacy_education_fact",
        category="education",
        label="Bachelor of Science in Finance",
        detail="Bachelor of Science in Finance at Harbor University, completed 2023",
        verification_status="confirmed",
        structured_value={
            "degree": "Bachelor of Science in Finance",
            "institution": "Harbor University",
            "date_range": "2023",
        },
        source_excerpt=(
            "Education\nBachelor of Science in Finance\nHarbor University\n"
            f"Relevant Courses: {', '.join(coursework)}"
        ),
    )
    blockers = _coursework_review_blockers(
        section_key="education",
        evidence=(education,),
        bullet=f"Relevant Coursework: {', '.join(coursework)}",
        item_id="legacy_finance_degree",
        title="Bachelor of Science in Finance",
        organization="Harbor University",
        date_range="2023",
    )

    assert not [blocker for blocker in blockers if blocker.startswith("unsupported_claim:")]


@pytest.mark.parametrize(
    ("gpa_bullet", "display_recommended"),
    [
        ("GPA: 3.7/4", True),
        ("GPA: 3.6/5", True),
        ("GPA: 3.60/4", True),
        ("GPA: 3.6/4 with honors", True),
        ("GPA: 3.6/4", False),
    ],
)
def test_review_rejects_gpa_that_is_not_exactly_displayable_education_evidence(
    gpa_bullet: str,
    display_recommended: bool,
) -> None:
    education = ResumeEvidence(
        handle="education_gpa_fact",
        category="education",
        label="Bachelor of Science in Finance",
        detail="Bachelor of Science in Finance at Harbor University, completed 2023",
        verification_status="confirmed",
        structured_value={
            "degree": "Bachelor of Science in Finance",
            "institution": "Harbor University",
            "date_range": "2023",
            "gpa_score": "3.6",
            "gpa_scale": "4",
            "gpa_display_recommended": display_recommended,
        },
        source_excerpt="Bachelor of Science in Finance, GPA: 3.6/4",
    )
    blockers = _coursework_review_blockers(
        section_key="education",
        evidence=(education,),
        bullet=gpa_bullet,
        item_id="finance_degree",
        title="Bachelor of Science in Finance",
        organization="Harbor University",
        date_range="2023",
    )

    assert "unsupported_claim:bullet:finance_degree:0" in blockers


def test_review_rejects_coursework_bullet_with_an_invented_course() -> None:
    coursework = [
        "Auditing",
        "Financial Accounting",
        "Risk Management",
        "Cost Control",
        "Internal Control Systems",
        "Financial Modelling",
    ]
    education = ResumeEvidence(
        handle="education_fact",
        category="education",
        label="Bachelor of Science in Finance",
        detail="Bachelor of Science in Finance at Harbor University, completed 2023",
        verification_status="confirmed",
        structured_value={
            "degree": "Bachelor of Science in Finance",
            "institution": "Harbor University",
            "date_range": "2023",
            "coursework": coursework,
        },
        source_excerpt=f"Relevant Courses: {', '.join(coursework)}",
    )
    blockers = _coursework_review_blockers(
        section_key="education",
        evidence=(education,),
        bullet=f"Relevant Coursework: {', '.join([*coursework, 'Quantum Finance'])}",
        item_id="finance_degree",
        title="Bachelor of Science in Finance",
        organization="Harbor University",
        date_range="2023",
    )

    assert "unsupported_claim:bullet:finance_degree:0" in blockers


@pytest.mark.parametrize("non_coursework_value", ["Harbor University", "Bachelor of Finance"])
def test_review_rejects_education_metadata_presented_as_coursework(
    non_coursework_value: str,
) -> None:
    coursework = [
        "Auditing",
        "Financial Accounting",
        "Risk Management",
        "Cost Control",
        "Internal Control Systems",
        "Financial Modelling",
    ]
    education = ResumeEvidence(
        handle="education_fact",
        category="education",
        label="Bachelor of Finance",
        detail="Bachelor of Finance at Harbor University, completed 2023",
        verification_status="confirmed",
        structured_value={
            "degree": "Bachelor of Finance",
            "institution": "Harbor University",
            "date_range": "2023",
            "coursework": coursework,
        },
        source_excerpt=f"Relevant Courses: {', '.join(coursework)}",
    )
    blockers = _coursework_review_blockers(
        section_key="education",
        evidence=(education,),
        bullet=f"Relevant Coursework: {non_coursework_value}",
        item_id="finance_degree",
        title="Bachelor of Finance",
        organization="Harbor University",
        date_range="2023",
    )

    assert "unsupported_claim:bullet:finance_degree:0" in blockers


def test_review_does_not_exempt_coursework_prefix_in_experience_section() -> None:
    coursework = ["Auditing", "Financial Accounting", "Risk Management"]
    experience = ResumeEvidence(
        handle="experience_fact",
        category="experience",
        label="Cost Analyst",
        detail="Cost Analyst at Harbor Company in 2024",
        verification_status="confirmed",
        structured_value={
            "title": "Cost Analyst",
            "organization": "Harbor Company",
            "date_range": "2024",
            "coursework": coursework,
        },
        source_excerpt=", ".join(coursework),
    )
    blockers = _coursework_review_blockers(
        section_key="experience",
        evidence=(experience,),
        bullet=f"Relevant Coursework: {', '.join(coursework)}",
        item_id="cost_analyst",
        title="Cost Analyst",
        organization="Harbor Company",
        date_range="2024",
    )

    assert "unsupported_claim:bullet:cost_analyst:0" in blockers


def test_review_accepts_arabic_coursework_prefix_for_arabic_structured_courses() -> None:
    coursework = [
        "المراجعة",
        "المحاسبة المالية",
        "إدارة المخاطر",
        "مراقبة التكاليف",
        "أنظمة الرقابة الداخلية",
        "النمذجة المالية",
    ]
    education = ResumeEvidence(
        handle="arabic_education_fact",
        category="education",
        label="بكالوريوس العلوم في المالية",
        detail="بكالوريوس العلوم في المالية من جامعة الميناء عام 2023",
        verification_status="confirmed",
        structured_value={
            "degree": "بكالوريوس العلوم في المالية",
            "institution": "جامعة الميناء",
            "date_range": "2023",
            "coursework": coursework,
        },
        source_excerpt=f"المقررات: {', '.join(coursework)}",
    )
    blockers = _coursework_review_blockers(
        section_key="education",
        evidence=(education,),
        bullet=f"المقررات ذات الصلة: {', '.join(coursework)}",
        item_id="arabic_finance_degree",
        title="بكالوريوس العلوم في المالية",
        organization="جامعة الميناء",
        date_range="2023",
    )

    assert not [blocker for blocker in blockers if blocker.startswith("unsupported_claim:")]


def test_review_rejects_coursework_list_composed_from_two_education_facts() -> None:
    first_courses = ["Auditing", "Risk Management", "Cost Control"]
    second_courses = [
        "Financial Accounting",
        "Internal Control Systems",
        "Financial Modelling",
    ]
    first_education = ResumeEvidence(
        handle="first_education_fact",
        category="education",
        label="Bachelor of Science in Finance",
        detail="Bachelor of Science in Finance at Harbor University, completed 2023",
        verification_status="confirmed",
        structured_value={
            "degree": "Bachelor of Science in Finance",
            "institution": "Harbor University",
            "date_range": "2023",
            "coursework": first_courses,
        },
        source_excerpt=f"Relevant Courses: {', '.join(first_courses)}",
    )
    second_education = ResumeEvidence(
        handle="second_education_fact",
        category="education",
        label="Diploma in Accounting",
        detail="Diploma in Accounting at Coast College, completed 2021",
        verification_status="confirmed",
        structured_value={
            "degree": "Diploma in Accounting",
            "institution": "Coast College",
            "date_range": "2021",
            "coursework": second_courses,
        },
        source_excerpt=f"Relevant Courses: {', '.join(second_courses)}",
    )
    combined_courses = [*first_courses, *second_courses]
    blockers = _coursework_review_blockers(
        section_key="education",
        evidence=(first_education, second_education),
        bullet=f"Relevant Coursework: {', '.join(combined_courses)}",
        item_id="combined_education",
        title="Bachelor of Science in Finance",
        organization="Harbor University",
        date_range="2023",
    )

    assert "unsupported_claim:bullet:combined_education:0" in blockers


async def test_review_rejects_unknown_evidence_handles(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    await add_confirmed_experience(client, profile, source, headers)
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    generated = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "أنشئ المسودة",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )
    draft = generated.json()["current_draft"]
    draft["summary_evidence_handles"] = ["fact_missing"]
    draft["sections"][0]["items"][0]["evidence_handles"] = ["fact_missing"]
    patched = await client.patch(
        f"{base}/draft",
        headers=headers,
        json={"draft": draft, "expected_draft_revision": 1},
    )
    assert patched.status_code == 200, patched.text
    reviewed = await client.post(
        f"{base}/review",
        headers=headers,
        json={"expected_draft_revision": 2, "review_acknowledged": True},
    )
    assert reviewed.status_code == 422
    assert reviewed.json()["detail"]["code"] == "resume_review_blocked"


@pytest.mark.parametrize(
    "changed_input",
    [
        "current_draft",
        "evidence_revision",
        "profile_full_name",
        "profile_city",
        "language",
        "contact",
    ],
)
async def test_every_pdf_input_change_invalidates_the_review_hash(
    client,
    session_factory,
    stub_provider: StubWorkspaceProvider,
    changed_input: str,
) -> None:
    del stub_provider
    profile, base, headers, workspace = await create_reviewed_workspace(client)

    async with session_factory() as session:
        stored_profile = await session.scalar(
            select(CareerProfile).where(CareerProfile.id == UUID(profile["id"]))
        )
        stored_workspace = await session.scalar(
            select(ResumeWorkspace).where(
                ResumeWorkspace.profile_id == UUID(profile["id"])
            )
        )
        assert stored_profile is not None
        assert stored_workspace is not None
        if changed_input == "current_draft":
            changed_draft = deepcopy(stored_workspace.current_draft)
            assert changed_draft is not None
            changed_draft["professional_summary"] += " "
            stored_workspace.current_draft = changed_draft
        elif changed_input == "evidence_revision":
            stored_profile.evidence_revision += 1
            stored_workspace.evidence_revision += 1
        elif changed_input == "profile_full_name":
            stored_profile.full_name = "اسم جديد"
        elif changed_input == "profile_city":
            stored_profile.city = "جدة"
        elif changed_input == "language":
            stored_workspace.language = PreferredLanguage.EN
        else:
            stored_workspace.contact = {"phone": "+966500000000"}
        await session.commit()

    exported = await client.post(
        f"{base}/export.pdf",
        headers=headers,
        json={
            "expected_draft_revision": workspace["draft_revision"],
            "review_acknowledged": True,
        },
    )
    assert exported.status_code == 409
    assert exported.json()["detail"]["code"] == "resume_review_stale"


async def test_contact_change_allows_export_only_after_a_fresh_review(
    client,
    stub_provider: StubWorkspaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del stub_provider
    _profile, base, headers, workspace = await create_reviewed_workspace(client)
    contact_changed = await client.post(
        base,
        headers=headers,
        json={
            "language": "ar",
            "contact": {"phone": "+966500000000"},
            "data_sharing_acknowledged": False,
        },
    )
    assert contact_changed.status_code == 201, contact_changed.text

    stale_export = await client.post(
        f"{base}/export.pdf",
        headers=headers,
        json={
            "expected_draft_revision": workspace["draft_revision"],
            "review_acknowledged": True,
        },
    )
    assert stale_export.status_code == 409
    assert stale_export.json()["detail"]["code"] == "resume_review_stale"

    reviewed_again = await client.post(
        f"{base}/review",
        headers=headers,
        json={
            "expected_draft_revision": workspace["draft_revision"],
            "review_acknowledged": True,
        },
    )
    assert reviewed_again.status_code == 200, reviewed_again.text
    monkeypatch.setattr(workspace_api, "render_resume_pdf", lambda **_: b"%PDF-reviewed")
    exported = await client.post(
        f"{base}/export.pdf",
        headers=headers,
        json={
            "expected_draft_revision": workspace["draft_revision"],
            "review_acknowledged": True,
        },
    )
    assert exported.status_code == 200, exported.text
    assert exported.content == b"%PDF-reviewed"


async def test_failed_pdf_render_does_not_mark_workspace_complete(
    client,
    stub_provider: StubWorkspaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del stub_provider
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    await add_confirmed_experience(client, profile, source, headers)
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    generated = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "أنشئ المسودة",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )
    assert generated.status_code == 200, generated.text
    reviewed = await client.post(
        f"{base}/review",
        headers=headers,
        json={"expected_draft_revision": 1, "review_acknowledged": True},
    )
    assert reviewed.status_code == 200, reviewed.text

    def fail_render(**_: object) -> bytes:
        raise RuntimeError("renderer failed")

    monkeypatch.setattr(workspace_api, "render_resume_pdf", fail_render)
    exported = await client.post(
        f"{base}/export.pdf",
        headers=headers,
        json={"expected_draft_revision": 1, "review_acknowledged": True},
    )
    assert exported.status_code == 500
    reloaded = await client.get(base, headers=headers)
    assert reloaded.status_code == 200
    assert reloaded.json()["stage"] == "review"


async def test_evidence_change_invalidates_review_and_blocks_export(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    fact = await add_confirmed_experience(client, profile, source, headers)
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    generated = await client.post(
        f"{base}/messages",
        headers=headers,
        json={
            "content": "أنشئ المسودة",
            "quick_action": "generate",
            "client_turn_id": str(uuid4()),
            "expected_revision": started.json()["revision"],
        },
    )
    assert generated.status_code == 200, generated.text
    reviewed = await client.post(
        f"{base}/review",
        headers=headers,
        json={"expected_draft_revision": 1, "review_acknowledged": True},
    )
    assert reviewed.status_code == 200, reviewed.text

    unconfirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{fact['id']}/unconfirm",
        headers=headers,
    )
    assert unconfirmed.status_code == 200, unconfirmed.text
    current_profile = await client.get("/v1/profiles", headers=headers)
    assert current_profile.status_code == 200
    exported = await client.post(
        f"{base}/export.pdf",
        headers=headers,
        json={"expected_draft_revision": 1, "review_acknowledged": True},
    )
    assert exported.status_code == 409
    assert exported.json()["detail"]["code"] == "resume_review_stale"
    reloaded = await client.get(base, headers=headers)
    assert reloaded.status_code == 200
    assert reloaded.json()["stage"] == "writing"
    assert reloaded.json()["evidence_revision"] == current_profile.json()[
        "evidence_revision"
    ]


async def test_removed_rewrite_target_is_rejected_by_schema(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    del stub_provider
    profile, _ = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    base = f"/v1/profiles/{profile['id']}/resume-workspace"
    started = await client.post(
        base,
        headers=headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    rejected = await client.post(
        f"{base}/draft/rewrite",
        headers=headers,
        json={
            "target_kind": "section",
            "section_key": "experience",
            "mode": "stronger",
            "expected_draft_revision": 0,
        },
    )
    assert started.status_code == 201
    assert rejected.status_code == 422


def import_draft_docx(
    text: str = "Skills: Python and SQL\nBachelor of Computer Science",
) -> bytes:
    stream = io.BytesIO()
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines()
    )
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>{paragraphs}</w:body>
    </w:document>"""
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", document_xml)
    return stream.getvalue()


async def create_from_import_workspace(client) -> tuple[dict, dict, dict, dict, dict]:
    profile, other_source = await create_profile_and_source(client)
    headers = {"X-User-Id": "demo-user"}
    imported = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        headers=headers,
        files={
            "file": (
                "existing-resume.docx",
                import_draft_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    import_source = imported.json()["source"]
    imported_fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": import_source["id"],
            "category": "experience",
            "label": "Cost Analyst",
            "detail": "Prepared monthly cost reports using Excel for Harbor Company.",
            "structured_value": {
                "title": "Cost Analyst",
                "organization": "Harbor Company",
                "date_range": "2024 - Present",
                "responsibilities": [
                    "Prepared monthly cost reports using Excel for Harbor Company."
                ],
            },
            "source_excerpt": (
                "Professional Experience\nCost Analyst | Harbor Company | 2024 - Present\n"
                "Prepared monthly cost reports using Excel for Harbor Company."
            ),
        },
    )
    assert imported_fact.status_code == 201, imported_fact.text
    confirmed_imported = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{imported_fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed_imported.status_code == 200, confirmed_imported.text

    other_fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": other_source["id"],
            "category": "experience",
            "label": "External Payroll Analyst",
            "detail": "Managed payroll reporting for External Company.",
            "structured_value": {
                "title": "External Payroll Analyst",
                "organization": "External Company",
                "responsibilities": ["Managed payroll reporting for External Company."],
            },
            "source_excerpt": "Managed payroll reporting for External Company.",
        },
    )
    assert other_fact.status_code == 201, other_fact.text
    confirmed_other = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{other_fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed_other.status_code == 200, confirmed_other.text

    started = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
        json={
            "language": "en",
            "conversation_language": "ar",
            "data_sharing_acknowledged": False,
        },
    )
    assert started.status_code == 201, started.text
    return (
        profile,
        import_source,
        confirmed_imported.json(),
        headers,
        started.json(),
    )


async def test_from_import_draft_uses_only_confirmed_source_facts_without_provider_call(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    profile, source, imported_fact, headers, started = await create_from_import_workspace(client)
    profile_state = await client.get("/v1/profiles", headers=headers)
    assert profile_state.status_code == 200, profile_state.text
    request_id = uuid4()
    payload = {
        "source_id": source["id"],
        "client_request_id": str(request_id),
        "expected_revision": started["revision"],
        "expected_evidence_revision": profile_state.json()["evidence_revision"],
    }

    generated = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace/draft/from-import",
        headers=headers,
        json=payload,
    )

    assert generated.status_code == 200, generated.text
    workspace = generated.json()
    assert stub_provider.draft_calls == []
    assert workspace["current_draft"]["headline"] == "Cost Analyst"
    serialized_draft = str(workspace["current_draft"])
    assert "Harbor Company" in serialized_draft
    assert "External Company" not in serialized_draft
    assert workspace["provider_metadata"]["generation_fact_ids"] == [imported_fact["id"]]
    assert workspace["draft_revision"] == 1
    assert len(workspace["versions"]) == 1
    assert workspace["versions"][0]["reason"] == "initial_generation"

    repeated = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace/draft/from-import",
        headers=headers,
        json=payload,
    )
    assert repeated.status_code == 200, repeated.text
    duplicate = repeated.json()
    assert duplicate["revision"] == workspace["revision"]
    assert duplicate["draft_revision"] == workspace["draft_revision"]
    assert duplicate["current_draft"] == workspace["current_draft"]
    assert len(duplicate["versions"]) == 1
    assert stub_provider.draft_calls == []

    replacement = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace/draft/from-import",
        headers=headers,
        json={**payload, "client_request_id": str(uuid4())},
    )
    assert replacement.status_code == 409, replacement.text
    assert replacement.json()["detail"]["code"] == "resume_import_draft_exists"
    preserved = await client.get(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
    )
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["current_draft"] == workspace["current_draft"]
    assert preserved.json()["draft_revision"] == workspace["draft_revision"]


async def test_from_import_scopes_cross_language_evidence_for_ai_without_blocking_chat(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    profile, source, imported_fact, headers, _started = await create_from_import_workspace(client)
    rejected_english = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{imported_fact['id']}/unconfirm",
        headers=headers,
    )
    assert rejected_english.status_code == 200, rejected_english.text
    arabic_fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "experience",
            "label": "محلل تكاليف",
            "detail": "أعددت تقارير التكاليف الشهرية باستخدام إكسل.",
            "structured_value": {
                "title": "محلل تكاليف",
                "organization": "شركة المرفأ",
                "responsibilities": ["أعددت تقارير التكاليف الشهرية باستخدام إكسل."],
            },
            "source_excerpt": "محلل تكاليف في شركة المرفأ",
        },
    )
    assert arabic_fact.status_code == 201, arabic_fact.text
    confirmed_arabic = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{arabic_fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed_arabic.status_code == 200, confirmed_arabic.text
    refreshed = await client.get(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
    )
    assert refreshed.status_code == 200, refreshed.text
    profile_state = await client.get("/v1/profiles", headers=headers)
    assert profile_state.status_code == 200, profile_state.text
    payload = {
        "source_id": source["id"],
        "client_request_id": str(uuid4()),
        "expected_revision": refreshed.json()["revision"],
        "expected_evidence_revision": profile_state.json()["evidence_revision"],
    }

    scoped = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace/draft/from-import",
        headers=headers,
        json=payload,
    )

    assert scoped.status_code == 200, scoped.text
    workspace = scoped.json()
    assert workspace["current_draft"] is None
    assert workspace["provider_metadata"]["draft_mode"] == "import_translation_required"
    assert workspace["provider_metadata"]["generation_fact_ids"] == [arabic_fact.json()["id"]]
    assert workspace["provider_metadata"]["pending_import_source_id"] is None
    assert "اكتب السيرة الآن" in workspace["messages"][-1]["content"]
    assert stub_provider.draft_calls == []

    repeated = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace/draft/from-import",
        headers=headers,
        json=payload,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["revision"] == workspace["revision"]
    assert repeated.json()["current_draft"] is None


async def test_from_import_draft_rejects_stale_workspace_revision(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    profile, source, _fact, headers, started = await create_from_import_workspace(client)
    profile_state = (await client.get("/v1/profiles", headers=headers)).json()
    changed = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
        json={
            "language": "en",
            "conversation_language": "en",
            "data_sharing_acknowledged": False,
        },
    )
    assert changed.status_code == 201, changed.text
    assert changed.json()["revision"] > started["revision"]

    rejected = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace/draft/from-import",
        headers=headers,
        json={
            "source_id": source["id"],
            "client_request_id": str(uuid4()),
            "expected_revision": started["revision"],
            "expected_evidence_revision": profile_state["evidence_revision"],
        },
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "resume_workspace_revision_conflict"
    assert stub_provider.draft_calls == []
    reloaded = await client.get(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
    )
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["current_draft"] is None


async def test_from_import_draft_rejects_stale_evidence_revision(
    client,
    stub_provider: StubWorkspaceProvider,
) -> None:
    profile, source, _fact, headers, started = await create_from_import_workspace(client)
    stale_evidence_revision = (await client.get("/v1/profiles", headers=headers)).json()[
        "evidence_revision"
    ]
    extra = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "skill",
            "label": "Power BI",
            "detail": "Built finance reporting dashboards with Power BI.",
            "source_excerpt": "Built finance reporting dashboards with Power BI.",
        },
    )
    assert extra.status_code == 201, extra.text
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{extra.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    refreshed = await client.get(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["revision"] > started["revision"]

    rejected = await client.post(
        f"/v1/profiles/{profile['id']}/resume-workspace/draft/from-import",
        headers=headers,
        json={
            "source_id": source["id"],
            "client_request_id": str(uuid4()),
            "expected_revision": refreshed.json()["revision"],
            "expected_evidence_revision": stale_evidence_revision,
        },
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "resume_evidence_revision_conflict"
    assert stub_provider.draft_calls == []
    reloaded = await client.get(
        f"/v1/profiles/{profile['id']}/resume-workspace",
        headers=headers,
    )
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["current_draft"] is None
