import io
import zipfile
from uuid import UUID

import httpx
import pytest
from conftest import create_profile_and_source
from fastapi import HTTPException

import career_agent_api.api.router as router_module
from career_agent_api.models.domain import EvidenceSource
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
                detail="AI must not replace confirmed evidence",
                structured_value={"level": "advanced"},
                source_excerpt=context.segments[0].text,
                confidence=0.91,
            ),
            FactCandidate(
                category=FactCategory.SKILL,
                label="SQL",
                detail="AI must not replace unconfirmed evidence",
                structured_value={"level": "advanced"},
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
    assert metadata["extractor_version"] == "resume-records-v5"
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


async def test_local_import_can_be_ai_upgraded_without_replacing_reviewed_facts(
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
    assert metadata["extractor_version"] == "resume-records-v5"
    assert metadata["consent_version"] == "2026-08-07-v1:mistral"
    assert metadata["candidate_fact_count"] == 4
    assert {fact["label"] for fact in result["facts"]} == {
        "Bachelor of Computer Science",
        "Portfolio project",
    }

    all_facts = (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
    saved_by_label = {fact["label"].casefold(): fact for fact in all_facts}
    assert saved_by_label["python"]["verification_status"] == "confirmed"
    assert saved_by_label["python"]["detail"] is None
    assert saved_by_label["sql"]["verification_status"] == "unconfirmed"
    assert saved_by_label["sql"]["detail"] is None
    assert saved_by_label["bachelor of computer science"]["verification_status"] == "extracted"
    assert (
        saved_by_label["bachelor of computer science"]["detail"] == "AI-enriched education detail"
    )
    assert saved_by_label["portfolio project"]["verification_status"] == "extracted"
    assert len((await client.get(f"/v1/profiles/{profile['id']}/sources")).json()) == source_count

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


async def test_v4_ai_import_is_reanalyzed_once_by_v5_without_replacing_reviewed_facts(
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
    unconfirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{facts_by_label['sql']['id']}/unconfirm"
    )
    assert unconfirmed.status_code == 200, unconfirmed.text
    stale_extracted_id = facts_by_label["docker"]["id"]

    async with session_factory() as session:
        source = await session.get(EvidenceSource, UUID(source_id))
        assert source is not None
        source.source_metadata = {
            **source.source_metadata,
            "ai_enhanced": True,
            "extractor_version": "resume-records-v4",
            "ai_provider": "mistral",
            "ai_model": "legacy-resume-model",
        }
        await session.commit()

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
    upgraded_result = upgraded.json()
    assert upgraded_result["analysis_status"] == "ai_upgraded"
    assert upgraded_result["source"]["id"] == source_id
    assert upgraded_result["source"]["source_metadata"]["extractor_version"] == (
        "resume-records-v5"
    )
    assert len(provider.contexts) == 1

    current_facts = (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
    current_by_id = {fact["id"]: fact for fact in current_facts}
    assert stale_extracted_id not in current_by_id
    assert current_by_id[facts_by_label["python"]["id"]]["verification_status"] == ("confirmed")
    assert current_by_id[facts_by_label["python"]["id"]]["detail"] is None
    assert current_by_id[facts_by_label["sql"]["id"]]["verification_status"] == ("unconfirmed")
    assert current_by_id[facts_by_label["sql"]["id"]]["detail"] is None
    assert "Portfolio project" in {fact["label"] for fact in current_facts}

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
