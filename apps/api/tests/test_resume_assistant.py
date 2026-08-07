from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from conftest import create_profile_and_source

import career_agent_api.api.resume as resume_api
from career_agent_api.models.enums import FactCategory, PreferredLanguage
from career_agent_api.schemas.api import (
    ResumeDraftContent,
    ResumeDraftItem,
    ResumeDraftSection,
    ResumeInterviewAnswerCreate,
    ResumeQuestionRead,
)
from career_agent_api.services.resume_writer import ResumeEvidence


def _draft() -> ResumeDraftContent:
    return ResumeDraftContent(
        headline="مطوّر برمجيات Python",
        professional_summary=(
            "مطوّر برمجيات يبني واجهات برمجية موثوقة باستخدام Python "
            "ويحرص على وضوح الحلول وقابليتها للصيانة."
        ),
        summary_evidence_handles=["fact_2"],
        sections=[
            ResumeDraftSection(
                key="skill",
                title="المهارات",
                items=[
                    ResumeDraftItem(
                        id="python_api_skill",
                        title="Python وتطوير واجهات API",
                        organization=None,
                        date_range=None,
                        location=None,
                        bullets=["بناء واجهات برمجية قابلة للصيانة باستخدام Python."],
                        evidence_handles=["fact_2"],
                    )
                ],
            )
        ],
    )


def _export_payload(*, reviewed: bool) -> dict[str, object]:
    return {
        "language": "ar",
        "draft": _draft().model_dump(mode="json"),
        "contact": {
            "email": "noura@example.test",
            "phone": "+966500000000",
            "linkedin": "linkedin.com/in/noura",
        },
        "review_acknowledged": reviewed,
    }


@dataclass
class StubResumeWriter:
    provider_name: str = "stub-writer"
    model: str = "stub-resume-model"
    available: bool = True
    question_calls: list[dict[str, Any]] = field(default_factory=list)
    draft_calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate_questions(
        self,
        *,
        language: PreferredLanguage,
        target_role: str | None,
        evidence: tuple[ResumeEvidence, ...],
    ) -> list[ResumeQuestionRead]:
        self.question_calls.append(
            {
                "language": language,
                "target_role": target_role,
                "evidence": evidence,
            }
        )
        return [
            ResumeQuestionRead(
                id="python_project_impact",
                category=FactCategory.PROJECT,
                question="ما المشروع الذي طبقت فيه Python، وما النتيجة التي حققها؟",
                why_it_matters="يربط المهارة بدليل عملي واضح.",
                placeholder="اذكر المشروع، دورك، والأثر إن كان معروفًا.",
                required=False,
            )
        ]

    async def generate_draft(
        self,
        *,
        language: PreferredLanguage,
        target_role: str | None,
        evidence: tuple[ResumeEvidence, ...],
        answers: list[ResumeInterviewAnswerCreate],
    ) -> ResumeDraftContent:
        self.draft_calls.append(
            {
                "language": language,
                "target_role": target_role,
                "evidence": evidence,
                "answers": answers,
            }
        )
        return _draft()


async def _add_skill_fact(
    client: httpx.AsyncClient,
    profile: dict[str, Any],
    source: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        headers=headers,
        json={
            "source_id": source["id"],
            "category": "skill",
            "label": "Python API development",
            "detail": "Built maintainable APIs; contact user@example.test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_resume_questions_require_consent_then_use_redacted_profile_evidence(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    profile, source = await create_profile_and_source(client)
    skill_fact = await _add_skill_fact(client, profile, source)
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{skill_fact['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    provider = StubResumeWriter()
    monkeypatch.setattr(resume_api, "get_resume_writer_provider", lambda _settings: provider)
    path = f"/v1/profiles/{profile['id']}/resume-assistant/questions"

    missing_consent = await client.post(
        path,
        json={
            "language": "ar",
            "target_role": "مهندس برمجيات خلفية",
            "data_sharing_acknowledged": False,
        },
    )

    assert missing_consent.status_code == 400
    assert missing_consent.json()["detail"]["code"] == "resume_writer_consent_required"
    assert provider.question_calls == []

    response = await client.post(
        path,
        json={
            "language": "ar",
            "target_role": "مهندس برمجيات خلفية",
            "data_sharing_acknowledged": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "stub-writer"
    assert payload["model"] == "stub-resume-model"
    assert payload["covered_categories"] == ["skill"]
    assert payload["questions"][0]["id"] == "python_project_impact"
    assert len(provider.question_calls) == 1
    call = provider.question_calls[0]
    assert call["language"] is PreferredLanguage.AR
    assert call["target_role"] == "مهندس برمجيات خلفية"
    evidence_text = " ".join(item.text for item in call["evidence"])
    assert "user@example.test" not in evidence_text
    assert "[redacted]" in evidence_text


async def test_resume_generate_forwards_interview_answers_and_returns_editable_draft(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    profile, source = await create_profile_and_source(client)
    skill_fact = await _add_skill_fact(client, profile, source)
    confirmed = await client.post(
        f"/v1/profiles/{profile['id']}/facts/{skill_fact['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    provider = StubResumeWriter()
    monkeypatch.setattr(resume_api, "get_resume_writer_provider", lambda _settings: provider)

    response = await client.post(
        f"/v1/profiles/{profile['id']}/resume-assistant/generate",
        json={
            "language": "ar",
            "target_role": "مهندس برمجيات خلفية",
            "answers": [
                {
                    "question_id": "python_project_impact",
                    "category": "project",
                    "question": "ما المشروع الذي طبقت فيه Python؟",
                    "answer": "بنيت API لمشروع جامعي باستخدام Python.",
                    "skipped": False,
                }
            ],
            "data_sharing_acknowledged": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "stub-writer"
    assert payload["model"] == "stub-resume-model"
    assert payload["fact_count"] == 2
    assert payload["headline"] == "مطوّر برمجيات Python"
    assert payload["sections"][0]["items"][0]["evidence_handles"] == ["fact_2"]
    assert len(provider.draft_calls) == 1
    call = provider.draft_calls[0]
    assert call["language"] is PreferredLanguage.AR
    assert call["target_role"] == "مهندس برمجيات خلفية"
    assert call["answers"][0].answer == "بنيت API لمشروع جامعي باستخدام Python."


async def test_resume_generate_requires_consent_without_calling_provider(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    profile, _source = await create_profile_and_source(client)
    provider = StubResumeWriter()
    monkeypatch.setattr(resume_api, "get_resume_writer_provider", lambda _settings: provider)

    response = await client.post(
        f"/v1/profiles/{profile['id']}/resume-assistant/generate",
        json={
            "language": "ar",
            "answers": [],
            "data_sharing_acknowledged": False,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "resume_writer_consent_required"
    assert provider.draft_calls == []


async def test_resume_export_requires_review_and_returns_private_pdf_download(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    path = f"/v1/profiles/{profile['id']}/resume-assistant/export"

    missing_review = await client.post(path, json=_export_payload(reviewed=False))
    assert missing_review.status_code == 400
    assert missing_review.json()["detail"]["code"] == "resume_review_required"

    response = await client.post(path, json=_export_payload(reviewed=True))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "filename=resume.pdf" in disposition
    assert "filename*=UTF-8''" in disposition
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 1_000


async def test_resume_assistant_endpoints_are_owner_scoped_before_provider_or_export(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    other_headers = {"X-User-Id": "owner-b"}
    profile, _source = await create_profile_and_source(client, user_id="owner-a")
    provider = StubResumeWriter()
    export_calls: list[dict[str, object]] = []

    def unexpected_export(**kwargs: object) -> bytes:
        export_calls.append(kwargs)
        return b"%PDF-never-returned"

    monkeypatch.setattr(resume_api, "get_resume_writer_provider", lambda _settings: provider)
    monkeypatch.setattr(resume_api, "render_resume_pdf", unexpected_export)
    base = f"/v1/profiles/{profile['id']}/resume-assistant"

    questions = await client.post(
        f"{base}/questions",
        headers=other_headers,
        json={"language": "ar", "data_sharing_acknowledged": True},
    )
    generated = await client.post(
        f"{base}/generate",
        headers=other_headers,
        json={"language": "ar", "answers": [], "data_sharing_acknowledged": True},
    )
    exported = await client.post(
        f"{base}/export",
        headers=other_headers,
        json=_export_payload(reviewed=True),
    )

    assert {questions.status_code, generated.status_code, exported.status_code} == {404}
    assert questions.json()["detail"] == "Profile not found"
    assert generated.json()["detail"] == "Profile not found"
    assert exported.json()["detail"] == "Profile not found"
    assert provider.question_calls == []
    assert provider.draft_calls == []
    assert export_calls == []
