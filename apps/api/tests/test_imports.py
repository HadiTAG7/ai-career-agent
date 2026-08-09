import io
import zipfile
from uuid import UUID, uuid4

import httpx
import pytest
from conftest import create_profile_and_source
from fastapi import HTTPException

import career_agent_api.api.router as router_module
from career_agent_api.models.domain import CareerFact, EvidenceSource
from career_agent_api.models.enums import FactCategory
from career_agent_api.services import imports
from career_agent_api.services.imports import FactCandidate, _facts_from_cv_text
from career_agent_api.services.resume_intake import (
    ResumeIntakeProviderContext,
    ResumeIntakeProviderError,
)


class StubResumeProvider:
    available = True
    provider_name = "mistral"
    model = "resume-test-model"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.contexts: list[object] = []

    async def generate(self, context: ResumeIntakeProviderContext) -> list[FactCandidate]:
        self.contexts.append(context)
        if self.fail:
            raise ResumeIntakeProviderError("safe test failure")
        segments = context.segments
        return [
            FactCandidate(
                category=FactCategory.SKILL,
                label="Python",
                detail="Backend development",
                structured_value={},
                source_excerpt=segments[0].text,
                confidence=0.7,
            )
        ]


class UpgradeResumeProvider(StubResumeProvider):
    async def generate(self, context: ResumeIntakeProviderContext) -> list[FactCandidate]:
        self.contexts.append(context)
        return [
            FactCandidate(
                category=FactCategory.SKILL,
                label="Python",
                detail="AI-enriched Python detail",
                structured_value={"level": "advanced"},
                source_excerpt=context.segments[0].text,
                confidence=0.91,
            ),
            FactCandidate(
                category=FactCategory.SKILL,
                label="SQL",
                detail="AI-enriched SQL detail",
                structured_value={
                    "title": "SQL",
                    "level": "advanced",
                    "tool_family": "database",
                },
                source_excerpt=context.segments[0].text,
                confidence=0.9,
            ),
            FactCandidate(
                category=FactCategory.EDUCATION,
                label="Bachelor of Computer Science",
                detail="AI-enriched education detail",
                structured_value={"degree": "bachelor"},
                source_excerpt=context.segments[1].text,
                confidence=0.89,
            ),
            FactCandidate(
                category=FactCategory.PROJECT,
                label="Portfolio project",
                detail="AI-discovered project",
                structured_value={},
                source_excerpt=context.segments[1].text,
                confidence=0.8,
            ),
        ]


class ThinExperienceUpgradeProvider(UpgradeResumeProvider):
    async def generate(self, context: ResumeIntakeProviderContext) -> list[FactCandidate]:
        candidates = await super().generate(context)
        return [
            *candidates,
            FactCandidate(
                category=FactCategory.EXPERIENCE,
                label="Operations Analyst",
                detail="Operations reporting detail",
                structured_value={
                    "title": "Operations Analyst",
                    "organization": "Northstar Logistics",
                    "date_range": "2022 - 2025",
                    "responsibilities": [
                        "Reduced monthly reporting time by 35% through SQL automation.",
                        "Built Power BI dashboards tracking 12 regional sites.",
                    ],
                },
                source_excerpt="Professional Experience\nOperations Analyst",
                confidence=0.93,
            ),
        ]


def test_resume_upgrade_prefers_current_label_over_an_original_label_match() -> None:
    profile_id = uuid4()
    source_id = uuid4()
    shared_excerpt = "Skills: SQL"
    corrected = CareerFact(
        id=uuid4(),
        profile_id=profile_id,
        source_id=source_id,
        category=FactCategory.SKILL,
        label="Advanced SQL",
        structured_value={},
        source_excerpt=shared_excerpt,
        original_extraction={"label": "SQL"},
    )
    current = CareerFact(
        id=uuid4(),
        profile_id=profile_id,
        source_id=source_id,
        category=FactCategory.SKILL,
        label="SQL",
        structured_value={},
        source_excerpt=shared_excerpt,
    )
    candidate = FactCandidate(
        category=FactCategory.SKILL,
        label="SQL",
        detail=None,
        structured_value={},
        source_excerpt=shared_excerpt,
        confidence=0.9,
    )

    matched = router_module._matching_source_fact(candidate, [corrected, current], set())

    assert matched is current


def minimal_docx(text: str = "Skills: Python and SQL\nBachelor of Computer Science") -> bytes:
    stream = io.BytesIO()
    paragraphs = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines())
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>{paragraphs}</w:body>
    </w:document>"""
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", document_xml)
    return stream.getvalue()


async def test_docx_import_creates_only_review_required_extracted_facts(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    response = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={
            "file": (
                "resume.docx",
                minimal_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["requires_user_review"] is True
    assert result["source"]["kind"] == "cv_upload"
    assert result["source"]["source_metadata"]["raw_file_retained"] is False
    assert result["facts"]
    assert {fact["verification_status"] for fact in result["facts"]} == {"extracted"}
    assert any(fact["label"] == "python" for fact in result["facts"])


async def test_ai_docx_import_requires_separate_consent_and_configuration(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    files = {
        "file": (
            "resume.docx",
            minimal_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }

    missing_consent = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files=files,
        data={"use_ai": "true"},
    )
    assert missing_consent.status_code == 400
    assert missing_consent.json()["detail"]["code"] == "resume_ai_consent_required"

    not_configured = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files=files,
        data={"use_ai": "true", "data_sharing_acknowledged": "true"},
    )
    assert not_configured.status_code == 503
    assert not_configured.json()["detail"]["code"] == "resume_ai_not_configured"


async def test_ai_docx_import_uses_provider_and_returns_existing_ai_analysis_on_repeat(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, _source = await create_profile_and_source(client)
    provider = StubResumeProvider()
    monkeypatch.setattr(
        router_module,
        "get_resume_intake_provider",
        lambda _settings: provider,
    )
    files = {
        "file": (
            "resume.docx",
            minimal_docx("Senior Python backend developer"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    form = {"use_ai": "true", "data_sharing_acknowledged": "true"}

    first = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files=files,
        data=form,
    )

    assert first.status_code == 201, first.text
    result = first.json()
    assert len(provider.contexts) == 1
    assert provider.contexts[0].mode == "upload"
    assert provider.contexts[0].locale == "ar"
    metadata = result["source"]["source_metadata"]
    assert metadata["ai_enhanced"] is True
    assert metadata["ai_provider"] == "mistral"
    assert metadata["ai_model"] == "resume-test-model"
    assert metadata["extractor_version"] == "resume-records-v6"
    assert metadata["consent_version"] == "2026-08-07-v1:mistral"
    assert "Senior Python backend developer" not in str(metadata)
    assert {fact["verification_status"] for fact in result["facts"]} == {"extracted"}
    assert [fact["label"] for fact in result["facts"]] == ["Python"]

    duplicate = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files=files,
        data=form,
    )
    assert duplicate.status_code == 201, duplicate.text
    duplicate_result = duplicate.json()
    assert duplicate_result["analysis_status"] == "already_ai_analyzed"
    assert duplicate_result["source"]["id"] == result["source"]["id"]
    assert [fact["label"] for fact in duplicate_result["facts"]] == ["Python"]
    assert len(provider.contexts) == 1


async def test_local_import_ai_upgrade_stages_enrichment_for_review(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, _source = await create_profile_and_source(client)
    upload = {
        "file": (
            "resume.docx",
            minimal_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    first = await client.post(f"/v1/profiles/{profile['id']}/imports", files=upload)
    assert first.status_code == 201, first.text
    first_result = first.json()
    source_id = first_result["source"]["id"]
    facts_by_label = {fact["label"].casefold(): fact for fact in first_result["facts"]}

    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{facts_by_label['python']['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    unconfirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{facts_by_label['sql']['id']}/unconfirm"
    )
    assert unconfirmed.status_code == 200, unconfirmed.text
    source_count = len((await client.get(f"/v1/profiles/{profile['id']}/sources")).json())

    provider = UpgradeResumeProvider()
    monkeypatch.setattr(
        router_module,
        "get_resume_intake_provider",
        lambda _settings: provider,
    )
    form = {"use_ai": "true", "data_sharing_acknowledged": "true"}
    upgraded = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files=upload,
        data=form,
    )

    assert upgraded.status_code == 201, upgraded.text
    result = upgraded.json()
    assert result["analysis_status"] == "ai_upgraded"
    assert result["source"]["id"] == source_id
    assert len(provider.contexts) == 1
    metadata = result["source"]["source_metadata"]
    assert metadata["ai_enhanced"] is True
    assert metadata["ai_provider"] == "mistral"
    assert metadata["ai_model"] == "resume-test-model"
    assert metadata["extractor_version"] == "resume-records-v6"
    assert metadata["consent_version"] == "2026-08-07-v1:mistral"
    assert metadata["candidate_fact_count"] == 4
    assert {fact["label"] for fact in result["facts"]} == {
        "Python",
        "Bachelor of Computer Science",
        "Portfolio project",
    }

    all_facts = (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
    saved_by_label = {fact["label"].casefold(): fact for fact in all_facts}
    assert saved_by_label["python"]["id"] == facts_by_label["python"]["id"]
    assert saved_by_label["python"]["verification_status"] == "extracted"
    assert saved_by_label["python"]["detail"] == "AI-enriched Python detail"
    assert saved_by_label["python"]["structured_value"]["level"] == "advanced"
    assert saved_by_label["sql"]["id"] == facts_by_label["sql"]["id"]
    assert saved_by_label["sql"]["verification_status"] == "unconfirmed"
    assert saved_by_label["sql"]["detail"] is None
    assert "level" not in saved_by_label["sql"]["structured_value"]
    assert saved_by_label["bachelor of computer science"]["verification_status"] == "extracted"
    assert (
        saved_by_label["bachelor of computer science"]["detail"] == "AI-enriched education detail"
    )
    assert saved_by_label["portfolio project"]["verification_status"] == "extracted"
    assert len((await client.get(f"/v1/profiles/{profile['id']}/sources")).json()) == source_count

    reconfirmed_python = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{facts_by_label['python']['id']}/confirm"
    )
    assert reconfirmed_python.status_code == 200, reconfirmed_python.text
    assert reconfirmed_python.json()["id"] == facts_by_label["python"]["id"]
    assert reconfirmed_python.json()["verification_status"] == "confirmed"
    assert reconfirmed_python.json()["structured_value"]["level"] == "advanced"

    repeated = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files=upload,
        data=form,
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["analysis_status"] == "already_ai_analyzed"
    assert repeated.json()["source"]["id"] == source_id
    assert {fact["label"].casefold() for fact in repeated.json()["facts"]} == {
        "python",
        "sql",
        "bachelor of computer science",
        "portfolio project",
    }
    assert len(provider.contexts) == 1


async def test_v5_ai_import_is_reanalyzed_once_by_v6_and_enriches_reviewed_facts(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    profile, _source = await create_profile_and_source(client)
    document = minimal_docx("Skills: Python and SQL and Docker\nBachelor of Computer Science")
    upload = {
        "file": (
            "resume.docx",
            document,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }

    imported = await client.post(f"/v1/profiles/{profile['id']}/imports", files=upload)
    assert imported.status_code == 201, imported.text
    imported_result = imported.json()
    source_id = imported_result["source"]["id"]
    facts_by_label = {fact["label"].casefold(): fact for fact in imported_result["facts"]}

    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{facts_by_label['python']['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    document_response = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "kind": "cv",
            "language": "en",
            "title": "Python CV",
            "claims": [
                {
                    "claim_type": "skill",
                    "text": "Python",
                    "evidence_fact_ids": [facts_by_label["python"]["id"]],
                }
            ],
        },
    )
    assert document_response.status_code == 201, document_response.text
    reviewed_document = await client.post(
        f"/v1/documents/{document_response.json()['id']}/review"
    )
    assert reviewed_document.status_code == 200, reviewed_document.text
    assert reviewed_document.json()["status"] == "export_ready"
    corrected_sql = await client.patch(
        f"/v1/profiles/{profile['id']}/facts/{facts_by_label['sql']['id']}",
        json={
            "label": "Advanced SQL",
            "detail": "User-reviewed SQL detail",
            "structured_value": {"level": "expert"},
            "correction_reason": "Keep my reviewed SQL proficiency",
        },
    )
    assert corrected_sql.status_code == 200, corrected_sql.text
    reconfirmed_sql = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{facts_by_label['sql']['id']}/confirm"
    )
    assert reconfirmed_sql.status_code == 200, reconfirmed_sql.text
    thin_experience = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={
            "source_id": source_id,
            "category": "experience",
            "label": "Operations Analyst",
            "detail": "Operations reporting detail",
            "structured_value": {
                "title": "Operations Analyst",
                "organization": "Northstar Logistics",
                "date_range": "2022 - 2025",
                "responsibilities": [],
            },
            "source_excerpt": "Professional Experience\nOperations Analyst",
        },
    )
    assert thin_experience.status_code == 201, thin_experience.text
    thin_experience_id = thin_experience.json()["id"]
    confirmed_experience = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{thin_experience_id}/confirm"
    )
    assert confirmed_experience.status_code == 200, confirmed_experience.text
    stale_extracted_id = facts_by_label["docker"]["id"]

    async with session_factory() as session:
        source = await session.get(EvidenceSource, UUID(source_id))
        assert source is not None
        source.source_metadata = {
            **source.source_metadata,
            "ai_enhanced": True,
            "extractor_version": "resume-records-v5",
            "ai_provider": "mistral",
            "ai_model": "legacy-resume-model",
        }
        await session.commit()

    provider = ThinExperienceUpgradeProvider()
    monkeypatch.setattr(
        router_module,
        "get_resume_intake_provider",
        lambda _settings: provider,
    )
    form = {"use_ai": "true", "data_sharing_acknowledged": "true"}

    upgraded = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files=upload,
        data=form,
    )
    assert upgraded.status_code == 201, upgraded.text
    upgraded_result = upgraded.json()
    assert upgraded_result["analysis_status"] == "ai_upgraded"
    assert upgraded_result["source"]["id"] == source_id
    assert upgraded_result["source"]["source_metadata"]["extractor_version"] == (
        "resume-records-v6"
    )
    assert upgraded_result["source"]["source_metadata"]["candidate_fact_count"] == 5
    assert len(provider.contexts) == 1

    current_facts = (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
    current_by_id = {fact["id"]: fact for fact in current_facts}
    assert stale_extracted_id not in current_by_id
    assert current_by_id[facts_by_label["python"]["id"]]["verification_status"] == ("extracted")
    assert (
        current_by_id[facts_by_label["python"]["id"]]["detail"]
        == "AI-enriched Python detail"
    )
    assert current_by_id[facts_by_label["python"]["id"]]["structured_value"]["level"] == (
        "advanced"
    )
    reviewed_sql = current_by_id[facts_by_label["sql"]["id"]]
    assert reviewed_sql["verification_status"] == "extracted"
    assert reviewed_sql["label"] == "Advanced SQL"
    assert reviewed_sql["detail"] == "User-reviewed SQL detail"
    assert reviewed_sql["structured_value"] == {
        "title": "Advanced SQL",
        "level": "expert",
        "tool_family": "database",
    }
    enriched_experience = current_by_id[thin_experience_id]
    assert enriched_experience["id"] == thin_experience_id
    assert enriched_experience["label"] == "Operations Analyst"
    assert enriched_experience["detail"] == "Operations reporting detail"
    assert enriched_experience["verification_status"] == "extracted"
    assert enriched_experience["structured_value"]["responsibilities"] == [
        "Reduced monthly reporting time by 35% through SQL automation.",
        "Built Power BI dashboards tracking 12 regional sites.",
    ]
    assert enriched_experience["original_extraction"]["structured_value"][
        "responsibilities"
    ] == []
    invalidated_document = await client.get(
        f"/v1/documents/{document_response.json()['id']}"
    )
    assert invalidated_document.status_code == 200, invalidated_document.text
    assert invalidated_document.json()["status"] == "draft"
    assert invalidated_document.json()["review_hash"] is None
    assert invalidated_document.json()["reviewed_at"] is None
    assert "Portfolio project" in {fact["label"] for fact in current_facts}

    for reviewed_fact_id in (
        facts_by_label["python"]["id"],
        facts_by_label["sql"]["id"],
        thin_experience_id,
    ):
        reconfirmed = await client.post(
            f"/v1/profiles/{profile['id']}/facts/{reviewed_fact_id}/confirm"
        )
        assert reconfirmed.status_code == 200, reconfirmed.text
        assert reconfirmed.json()["id"] == reviewed_fact_id
        assert reconfirmed.json()["verification_status"] == "confirmed"
        if reviewed_fact_id == thin_experience_id:
            assert reconfirmed.json()["structured_value"]["responsibilities"] == [
                "Reduced monthly reporting time by 35% through SQL automation.",
                "Built Power BI dashboards tracking 12 regional sites.",
            ]

    repeated = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files=upload,
        data=form,
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["analysis_status"] == "already_ai_analyzed"
    assert repeated.json()["source"]["id"] == source_id
    assert len(provider.contexts) == 1


async def test_ai_docx_import_fails_closed_when_no_readable_segments(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, _source = await create_profile_and_source(client)
    provider = StubResumeProvider()
    monkeypatch.setattr(
        router_module,
        "get_resume_intake_provider",
        lambda _settings: provider,
    )

    response = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={
            "file": (
                "resume.docx",
                minimal_docx("Email: user@example.com"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"use_ai": "true", "data_sharing_acknowledged": "true"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "resume_text_unreadable"
    assert provider.contexts == []


async def test_resume_draft_creates_ai_extracted_facts_without_raw_metadata(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, _source = await create_profile_and_source(client)
    provider = StubResumeProvider()
    monkeypatch.setattr(
        router_module,
        "get_resume_intake_provider",
        lambda _settings: provider,
    )
    content = "I build Python APIs and maintain production backend services."

    response = await client.post(
        f"/v1/profiles/{profile['id']}/resume-drafts",
        json={"content": content, "data_sharing_acknowledged": True},
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert len(provider.contexts) == 1
    assert provider.contexts[0].mode == "builder"
    assert result["source"]["kind"] == "manual"
    assert result["source"]["label"] == "AI-assisted resume draft"
    metadata = result["source"]["source_metadata"]
    assert metadata["char_count"] == len(content)
    assert metadata["raw_narrative_retained"] is False
    assert content not in str(metadata)
    assert {fact["verification_status"] for fact in result["facts"]} == {"extracted"}

    duplicate = await client.post(
        f"/v1/profiles/{profile['id']}/resume-drafts",
        json={"content": content, "data_sharing_acknowledged": True},
    )
    assert duplicate.status_code == 409
    assert len(provider.contexts) == 1


async def test_resume_draft_returns_structured_ai_errors(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, _source = await create_profile_and_source(client)
    content = "I build Python APIs and maintain backend services."

    missing_consent = await client.post(
        f"/v1/profiles/{profile['id']}/resume-drafts",
        json={"content": content, "data_sharing_acknowledged": False},
    )
    assert missing_consent.status_code == 400
    assert missing_consent.json()["detail"]["code"] == "resume_ai_consent_required"

    not_configured = await client.post(
        f"/v1/profiles/{profile['id']}/resume-drafts",
        json={"content": content, "data_sharing_acknowledged": True},
    )
    assert not_configured.status_code == 503
    assert not_configured.json()["detail"]["code"] == "resume_ai_not_configured"

    provider = StubResumeProvider(fail=True)
    monkeypatch.setattr(
        router_module,
        "get_resume_intake_provider",
        lambda _settings: provider,
    )
    unavailable = await client.post(
        f"/v1/profiles/{profile['id']}/resume-drafts",
        json={"content": content, "data_sharing_acknowledged": True},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "resume_ai_unavailable"


async def test_import_rejects_unsupported_type_and_oversized_file(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    unsupported = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={"file": ("resume.exe", b"MZ-danger", "application/octet-stream")},
    )
    assert unsupported.status_code == 422

    oversized = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={"file": ("resume.pdf", b"%PDF-" + b"x" * 1_000_000, "application/pdf")},
    )
    assert oversized.status_code == 413


async def test_linkedin_zip_ignores_unrelated_files(client: httpx.AsyncClient) -> None:
    profile, _source = await create_profile_and_source(client)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Skills.csv", "Name\nPython\n")
        archive.writestr(
            "Connections.csv", "First Name,Last Name,Email\nOther,Person,x@example.com\n"
        )
    response = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={"file": ("linkedin-export.zip", stream.getvalue(), "application/zip")},
        data={"use_ai": "true"},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["source"]["kind"] == "linkedin_export"
    assert [fact["label"] for fact in result["facts"]] == ["Python"]
    serialized = str(result)
    assert "x@example.com" not in serialized
    assert "Other" not in serialized


async def test_import_without_supported_facts_is_rejected_without_mutation(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    sources_before = (await client.get(f"/v1/profiles/{profile['id']}/sources")).json()

    response = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={
            "file": (
                "empty-resume.docx",
                minimal_docx("Contact details only"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 422
    assert "No supported professional facts" in response.json()["detail"]
    assert (await client.get(f"/v1/profiles/{profile['id']}/sources")).json() == sources_before
    assert (await client.get("/v1/profiles")).json()["evidence_revision"] == 0


async def test_duplicate_import_is_rejected_without_duplicate_sources_or_revision(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    upload = {
        "file": (
            "resume.docx",
            minimal_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }

    first = await client.post(f"/v1/profiles/{profile['id']}/imports", files=upload)
    assert first.status_code == 201
    revision_after_first = (await client.get("/v1/profiles")).json()["evidence_revision"]
    source_count_after_first = len(
        (await client.get(f"/v1/profiles/{profile['id']}/sources")).json()
    )

    second = await client.post(f"/v1/profiles/{profile['id']}/imports", files=upload)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "resume_content_duplicate"
    assert second.json()["detail"]["message"] == "This file has already been imported"
    assert (await client.get("/v1/profiles")).json()["evidence_revision"] == revision_after_first
    duplicate_source_count = len((await client.get(f"/v1/profiles/{profile['id']}/sources")).json())
    assert duplicate_source_count == source_count_after_first


async def test_batch_confirm_is_atomic_idempotent_and_advances_revision_once(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    imported = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={
            "file": (
                "batch-resume.docx",
                minimal_docx("Skills: Python and SQL\nBachelor of Computer Science"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    fact_ids = [fact["id"] for fact in result["facts"][:2]]
    assert len(fact_ids) == 2
    before = (await client.get("/v1/profiles")).json()["evidence_revision"]
    payload = {
        "source_id": result["source"]["id"],
        "client_request_id": str(uuid4()),
        "fact_ids": fact_ids,
        "expected_evidence_revision": before,
    }

    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/confirm-batch",
        json=payload,
    )

    assert confirmed.status_code == 200, confirmed.text
    batch = confirmed.json()
    assert {fact["id"] for fact in batch["facts"]} == set(fact_ids)
    assert {fact["verification_status"] for fact in batch["facts"]} == {"confirmed"}
    assert batch["evidence_revision"] == before + 1
    assert (await client.get("/v1/profiles")).json()["evidence_revision"] == before + 1

    repeated = await client.post(
        f"/v1/profiles/{profile['id']}/facts/confirm-batch",
        json=payload,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["evidence_revision"] == batch["evidence_revision"]
    assert (await client.get("/v1/profiles")).json()["evidence_revision"] == before + 1

    changed_after_commit = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{fact_ids[0]}/unconfirm"
    )
    assert changed_after_commit.status_code == 200, changed_after_commit.text
    stale_replay = await client.post(
        f"/v1/profiles/{profile['id']}/facts/confirm-batch",
        json=payload,
    )
    assert stale_replay.status_code == 409, stale_replay.text
    assert stale_replay.json()["detail"]["code"] == "resume_evidence_revision_conflict"
    assert changed_after_commit.json()["verification_status"] == "unconfirmed"


async def test_batch_confirm_rejects_unconfirmed_fact_without_partial_mutation(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    imported = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={
            "file": (
                "review-resume.docx",
                minimal_docx("Skills: Python and SQL\nBachelor of Computer Science"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    extracted_fact, rejected_fact = result["facts"][:2]
    rejected = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{rejected_fact['id']}/unconfirm"
    )
    assert rejected.status_code == 200, rejected.text
    before = (await client.get("/v1/profiles")).json()["evidence_revision"]

    response = await client.post(
        f"/v1/profiles/{profile['id']}/facts/confirm-batch",
        json={
            "source_id": result["source"]["id"],
            "client_request_id": str(uuid4()),
            "fact_ids": [extracted_fact["id"], rejected_fact["id"]],
            "expected_evidence_revision": before,
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "resume_import_fact_rejected"
    assert (await client.get("/v1/profiles")).json()["evidence_revision"] == before
    facts = {
        fact["id"]: fact
        for fact in (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
    }
    assert facts[extracted_fact["id"]]["verification_status"] == "extracted"
    assert facts[rejected_fact["id"]]["verification_status"] == "unconfirmed"


async def test_batch_confirm_rejects_cross_source_ids_without_partial_mutation(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    first = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={
            "file": (
                "first-resume.docx",
                minimal_docx("Skills: Python and SQL"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    second = await client.post(
        f"/v1/profiles/{profile['id']}/imports",
        files={
            "file": (
                "second-resume.docx",
                minimal_docx("Skills: Python and Docker"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_result = first.json()
    second_result = second.json()
    first_fact = first_result["facts"][0]
    second_fact = second_result["facts"][0]
    before = (await client.get("/v1/profiles")).json()["evidence_revision"]

    response = await client.post(
        f"/v1/profiles/{profile['id']}/facts/confirm-batch",
        json={
            "source_id": first_result["source"]["id"],
            "client_request_id": str(uuid4()),
            "fact_ids": [first_fact["id"], second_fact["id"]],
            "expected_evidence_revision": before,
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "resume_import_fact_mismatch"
    assert (await client.get("/v1/profiles")).json()["evidence_revision"] == before
    facts = {
        fact["id"]: fact
        for fact in (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
    }
    assert facts[first_fact["id"]]["verification_status"] == "extracted"
    assert facts[second_fact["id"]]["verification_status"] == "extracted"


def test_negated_or_third_party_skill_lines_do_not_create_positive_facts() -> None:
    assert _facts_from_cv_text("No Python experience") == []
    assert _facts_from_cv_text("I didn't use Python") == []
    assert _facts_from_cv_text("I don't know SQL") == []
    assert _facts_from_cv_text("لم أستخدم Python") == []
    assert _facts_from_cv_text("My colleague uses Python") == []
    assert not any(fact.label == "git" for fact in _facts_from_cv_text("Digital marketing"))
    assert not any(fact.label == "react" for fact in _facts_from_cv_text("Interactive design"))


def test_arabic_resume_section_headings_are_recognized() -> None:
    candidates = _facts_from_cv_text(
        "المشاريع: لوحة بيانات أسبوعية\nاللغات: العربية والإنجليزية\nالتعليم: بكالوريوس نظم معلومات"
    )

    assert {candidate.category for candidate in candidates} >= {
        FactCategory.PROJECT,
        FactCategory.LANGUAGE,
        FactCategory.EDUCATION,
    }


def test_cv_fact_excerpts_redact_contact_and_government_identifiers() -> None:
    candidates = _facts_from_cv_text(
        "Python developer | user@example.com | +966501234567 | 1234567890 | "
        "SA1234567890123456789012"
    )

    assert candidates
    serialized = repr(candidates)
    assert "user@example.com" not in serialized
    assert "+966501234567" not in serialized
    assert "1234567890" not in serialized
    assert "SA1234567890123456789012" not in serialized
    assert "[redacted]" in serialized


def test_pdf_text_limit_is_enforced_incrementally(monkeypatch: pytest.MonkeyPatch) -> None:
    class Page:
        def extract_text(self) -> str:
            return "x" * (imports.MAX_EXTRACTED_TEXT_CHARS // 2 + 1)

    class Reader:
        is_encrypted = False
        pages = [Page(), Page()]

    monkeypatch.setattr(imports, "PdfReader", lambda *_args, **_kwargs: Reader())
    with pytest.raises(HTTPException, match="Extracted document text is too large") as exc_info:
        imports._parse_pdf(b"%PDF-fake")
    assert exc_info.value.status_code == 422
