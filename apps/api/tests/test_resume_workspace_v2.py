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
    PreferredLanguage,
    ResumeDraftVersionReason,
    ResumeMessageKind,
    ResumeMessageRole,
    ResumeMessageStatus,
)
from career_agent_api.schemas.api import ResumeDraftContent
from career_agent_api.services.resume_writer import ResumeWriterProvider


class StubWorkspaceProvider(ResumeWriterProvider):
    provider_name = "mistral"
    model = "test-resume-model"
    available = True

    def __init__(self) -> None:
        self.draft_calls: list[dict[str, object]] = []
        self.adaptive_calls: list[dict[str, object]] = []

    async def generate_questions(self, **_: object) -> list:
        return []

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
    assert started["messages"][0]["content"].startswith("Tell")

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
    assert changed["messages"][0]["content"].startswith("Tell")
    assert changed["provider_metadata"]["current_question"]["question"].startswith("Tell")

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
    del stub_provider
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
    facts_after = (
        await client.get(f"/v1/profiles/{profile['id']}/facts", headers=headers)
    ).json()
    assert len(facts_after) == len(facts_before)


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
