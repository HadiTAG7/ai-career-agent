from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from career_agent_api.api.router import router
from career_agent_api.core.config import Settings, get_settings
from career_agent_api.db.session import get_db
from career_agent_api.models.domain import CareerFact
from career_agent_api.models.enums import FactCategory, VerificationStatus
from career_agent_api.services.career_path import (
    CareerPathGeneratedReply,
    CareerPathProviderContext,
    get_career_path_provider,
)


@dataclass(slots=True)
class FakeCareerPathProvider:
    provider_name: str = "fake-career-path"
    model: str | None = "fake-career-model"
    available: bool = True
    reply_message: str = "خلنا نحدد أولًا نوع المشكلات التي تستمتع بحلها."
    contexts: list[CareerPathProviderContext] = field(default_factory=list)

    async def generate(self, context: CareerPathProviderContext) -> CareerPathGeneratedReply:
        if not self.available:
            raise AssertionError("An unavailable provider must not be called")
        self.contexts.append(context)
        return CareerPathGeneratedReply(message=self.reply_message, suggestions=[])


@pytest_asyncio.fixture
async def career_path_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeCareerPathProvider]]:
    provider = FakeCareerPathProvider()
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
            ai_safety_salt=SecretStr("test-only-safety-pepper"),
            max_import_bytes=1_000_000,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_career_path_provider] = lambda: provider
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, provider


async def create_path_profile(
    client: httpx.AsyncClient, user_id: str = "demo-user"
) -> tuple[dict, dict]:
    headers = {"X-User-Id": user_id}
    response = await client.post(
        "/v1/profiles",
        headers=headers,
        json={"full_name": f"Career Path User {user_id}", "preferred_language": "ar"},
    )
    assert response.status_code == 201, response.text
    profile = response.json()
    sources = await client.get(f"/v1/profiles/{profile['id']}/sources", headers=headers)
    assert sources.status_code == 200, sources.text
    return profile, sources.json()[0]


async def confirm_path_prerequisite(
    client: httpx.AsyncClient,
    profile: dict,
    source: dict,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "skill",
            "label": "Analytical problem solving",
            "detail": "User-confirmed prerequisite for path discovery",
        },
    )
    assert fact.status_code == 201, fact.text
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{fact.json()['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text


def turn_payload(
    content: str,
    *,
    expected_revision: int,
    client_turn_id: UUID | None = None,
    data_sharing_acknowledged: bool = True,
) -> dict[str, object]:
    return {
        "content": content,
        "client_turn_id": str(client_turn_id or uuid4()),
        "expected_revision": expected_revision,
        "data_sharing_acknowledged": data_sharing_acknowledged,
    }


async def test_workspace_reports_provider_profile_and_consent_state(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, provider = career_path_client
    profile, _source = await create_path_profile(client)

    response = await client.get("/v1/career-path")

    assert response.status_code == 200, response.text
    workspace = response.json()
    assert workspace == {
        "provider_ready": True,
        "provider": provider.provider_name,
        "model": provider.model,
        "profile_id": profile["id"],
        "confirmed_fact_count": 0,
        "consent_required": True,
        "conversation": None,
    }


async def test_missing_provider_configuration_is_atomic(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, provider = career_path_client
    await create_path_profile(client)
    provider.available = False

    before = (await client.get("/v1/career-path")).json()
    assert before["provider_ready"] is False
    assert before["conversation"] is None

    response = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("أحتاج مساعدة في اختيار مساري.", expected_revision=0),
    )

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "ai_provider_not_configured"
    assert detail["message"]
    assert provider.contexts == []
    after = (await client.get("/v1/career-path")).json()
    assert after["conversation"] is None


async def test_path_discovery_requires_a_confirmed_resume_fact(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, provider = career_path_client
    await create_path_profile(client)

    response = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("Help me choose a path", expected_revision=0),
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "career_profile_evidence_required"
    assert provider.contexts == []
    workspace = (await client.get("/v1/career-path")).json()
    assert workspace["conversation"] is None
    assert workspace["confirmed_fact_count"] == 0


async def test_successful_turn_persists_an_atomic_user_assistant_pair(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, provider = career_path_client
    profile, source = await create_path_profile(client)
    fact = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={
                "source_id": source["id"],
                "category": "skill",
                "label": "Python",
                "detail": "Built production APIs",
            },
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")

    content = "أحب بناء الخدمات، ما المسار الأقرب لي؟"
    response = await client.post(
        "/v1/career-path/messages",
        json=turn_payload(content, expected_revision=0),
    )

    assert response.status_code == 200, response.text
    workspace = response.json()
    assert workspace["confirmed_fact_count"] == 1
    assert workspace["consent_required"] is False
    conversation = workspace["conversation"]
    assert conversation["revision"] == 1
    assert [message["role"] for message in conversation["messages"]] == [
        "user",
        "assistant",
    ]
    assert conversation["messages"][0]["content"] == content
    assert conversation["messages"][0]["suggestions"] == []
    assert conversation["messages"][1]["content"] == provider.reply_message
    assert conversation["messages"][1]["model"] == provider.model
    assert conversation["messages"][1]["suggestions"] == []
    assert len(provider.contexts) == 1

    loaded = await client.get("/v1/career-path")
    assert loaded.status_code == 200
    assert loaded.json()["conversation"] == conversation


async def test_provider_context_contains_only_confirmed_non_identity_minimal_facts(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, provider = career_path_client
    profile, source = await create_path_profile(client)
    confirmed = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={
                "source_id": source["id"],
                "category": "skill",
                "label": "Python",
                "detail": "Built production APIs",
                "structured_value": {"private_email": "secret@example.com"},
                "source_excerpt": "Contact secret@example.com for a reference",
            },
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{confirmed['id']}/confirm")
    unconfirmed = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={
                "source_id": source["id"],
                "category": "experience",
                "label": "Unconfirmed leadership role",
            },
        )
    ).json()
    async with session_factory() as session:
        session.add(
            CareerFact(
                profile_id=UUID(profile["id"]),
                source_id=UUID(source["id"]),
                category=FactCategory.PROJECT,
                label="Extracted secret project",
                detail="Never reviewed by the user",
                structured_value={},
                verification_status=VerificationStatus.EXTRACTED,
            )
        )
        await session.commit()

    response = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("وش المسارات المناسبة؟", expected_revision=0),
    )

    assert response.status_code == 200, response.text
    assert response.json()["confirmed_fact_count"] == 1
    context = provider.contexts[-1]
    assert context.locale == "ar"
    assert len(context.confirmed_facts) == 1
    shared = context.confirmed_facts[0]
    assert shared.category == "skill"
    assert shared.label == "Python"
    assert shared.detail == "Built production APIs"
    assert shared.handle
    assert context.safety_identifier
    assert context.safety_identifier != "demo-user"
    assert not hasattr(context, "owner_id")

    shared_text = repr(context.confirmed_facts)
    assert profile["full_name"] not in shared_text
    assert "secret@example.com" not in shared_text
    assert unconfirmed["label"] not in shared_text
    assert "Extracted secret project" not in shared_text


async def test_turn_idempotency_and_optimistic_revision_conflict(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, provider = career_path_client
    profile, source = await create_path_profile(client)
    await confirm_path_prerequisite(client, profile, source)
    turn_id = uuid4()
    first_payload = turn_payload(
        "أفكر في تحليل البيانات.",
        expected_revision=0,
        client_turn_id=turn_id,
    )

    first = await client.post("/v1/career-path/messages", json=first_payload)
    retry = await client.post("/v1/career-path/messages", json=first_payload)

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json()["conversation"] == first.json()["conversation"]
    assert retry.json()["conversation"]["revision"] == 1
    assert len(retry.json()["conversation"]["messages"]) == 2
    assert len(provider.contexts) == 1

    stale = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("والأمن السيبراني؟", expected_revision=0),
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "career_path_revision_conflict"
    assert len(provider.contexts) == 1
    unchanged = (await client.get("/v1/career-path")).json()["conversation"]
    assert unchanged["revision"] == 1
    assert len(unchanged["messages"]) == 2

    second = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("والأمن السيبراني؟", expected_revision=1),
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation"]["revision"] == 2
    assert len(second.json()["conversation"]["messages"]) == 4
    assert len(provider.contexts) == 2


async def test_changing_provider_requires_fresh_data_sharing_acknowledgement(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, provider = career_path_client
    profile, source = await create_path_profile(client)
    await confirm_path_prerequisite(client, profile, source)
    first = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("First provider turn", expected_revision=0),
    )
    assert first.status_code == 200, first.text
    assert first.json()["consent_required"] is False
    assert len(provider.contexts) == 1

    provider.provider_name = "second-provider"
    switched = await client.get("/v1/career-path")
    assert switched.status_code == 200, switched.text
    assert switched.json()["consent_required"] is True

    rejected = await client.post(
        "/v1/career-path/messages",
        json=turn_payload(
            "Do not share this without fresh consent",
            expected_revision=1,
            data_sharing_acknowledged=False,
        ),
    )
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["detail"]["code"] == "data_sharing_acknowledgement_required"
    assert len(provider.contexts) == 1

    accepted = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("Share after consent", expected_revision=1),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["consent_required"] is False
    assert accepted.json()["conversation"]["revision"] == 2
    assert len(provider.contexts) == 2


async def test_each_owner_only_sees_their_own_conversation(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, _provider = career_path_client
    profile_a, source_a = await create_path_profile(client, user_id="owner-a")
    profile_b, source_b = await create_path_profile(client, user_id="owner-b")
    headers_a = {"X-User-Id": "owner-a"}
    headers_b = {"X-User-Id": "owner-b"}
    await confirm_path_prerequisite(client, profile_a, source_a, headers=headers_a)
    await confirm_path_prerequisite(client, profile_b, source_b, headers=headers_b)

    turn_a = await client.post(
        "/v1/career-path/messages",
        headers=headers_a,
        json=turn_payload("رسالة المالك ألف", expected_revision=0),
    )
    turn_b = await client.post(
        "/v1/career-path/messages",
        headers=headers_b,
        json=turn_payload("رسالة المالك باء", expected_revision=0),
    )
    assert turn_a.status_code == 200, turn_a.text
    assert turn_b.status_code == 200, turn_b.text

    workspace_a = (await client.get("/v1/career-path", headers=headers_a)).json()
    workspace_b = (await client.get("/v1/career-path", headers=headers_b)).json()
    text_a = " ".join(message["content"] for message in workspace_a["conversation"]["messages"])
    text_b = " ".join(message["content"] for message in workspace_b["conversation"]["messages"])
    assert "رسالة المالك ألف" in text_a
    assert "رسالة المالك باء" not in text_a
    assert "رسالة المالك باء" in text_b
    assert "رسالة المالك ألف" not in text_b
    assert workspace_a["conversation"]["id"] != workspace_b["conversation"]["id"]


async def test_career_path_data_is_exported_and_removed_with_account_data(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, provider = career_path_client
    profile, source = await create_path_profile(client)
    await confirm_path_prerequisite(client, profile, source)
    user_content = "أريد استكشاف إدارة المنتجات."
    sent = await client.post(
        "/v1/career-path/messages",
        json=turn_payload(user_content, expected_revision=0),
    )
    assert sent.status_code == 200, sent.text

    exported = await client.get("/v1/me/export")
    assert exported.status_code == 200, exported.text
    export_payload = exported.json()
    assert export_payload["career_path_conversation"]["revision"] == 1
    assert [item["content"] for item in export_payload["career_path_messages"]] == [
        user_content,
        provider.reply_message,
    ]

    deleted = await client.delete("/v1/me/data")
    assert deleted.status_code == 200, deleted.text
    counts = deleted.json()["deleted_counts"]
    assert counts["career_path_conversations"] == 1
    assert counts["career_path_messages"] == 2
    assert user_content not in deleted.text
    assert (await client.get("/v1/career-path")).status_code == 404


async def test_reset_deletes_only_the_current_conversation_and_starts_revision_zero(
    career_path_client: tuple[httpx.AsyncClient, FakeCareerPathProvider],
) -> None:
    client, _provider = career_path_client
    profile, source = await create_path_profile(client)
    await confirm_path_prerequisite(client, profile, source)
    first = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("المحادثة الأولى", expected_revision=0),
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["conversation"]["id"]

    reset = await client.delete("/v1/career-path/conversation")

    assert reset.status_code == 204, reset.text
    assert reset.content == b""
    empty = (await client.get("/v1/career-path")).json()
    assert empty["conversation"] is None
    assert empty["consent_required"] is True

    restarted = await client.post(
        "/v1/career-path/messages",
        json=turn_payload("محادثة جديدة", expected_revision=0),
    )
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["conversation"]["revision"] == 1
    assert restarted.json()["conversation"]["id"] != first_id
