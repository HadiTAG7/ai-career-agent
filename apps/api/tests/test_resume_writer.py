from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError
from pypdf import PdfReader

import career_agent_api.services.resume_writer as resume_writer_module
from career_agent_api.api import resume_workspace as workspace_api
from career_agent_api.core.config import Settings
from career_agent_api.models.enums import FactCategory, PreferredLanguage, VerificationStatus
from career_agent_api.schemas.api import ResumeDraftContent, ResumeExportContact, ResumeQuestionRead
from career_agent_api.services.resume_export import render_resume_pdf
from career_agent_api.services.resume_writer import (
    RESUME_SECTION_ORDER,
    MistralResumeWriterProvider,
    ResumeEvidence,
    ResumeWriterError,
    ResumeWriterOutputError,
    ResumeWriterTransportError,
    _adaptive_answer_category,
    _GeneratedDraft,
    _redact_resume_text,
    _restore_open_ended_number_qualifiers,
    _sanitize_generated_draft,
    _StructuredResumeWriterProvider,
    _validate_gpa_policy,
    _validate_record,
    _validate_requested_draft_language,
    _validated_draft,
    build_resume_evidence,
    get_resume_writer_provider,
    resume_patch_uses_requested_language,
    validate_claim_grounding,
)


def evidence(*, category: str = "project") -> tuple[ResumeEvidence, ...]:
    return (
        ResumeEvidence(
            handle="fact_1",
            category=category,
            label="Inventory dashboard using Python and Power BI",
            detail="Built weekly inventory reports for the university project in Riyadh",
            verification_status="confirmed",
        ),
    )


def generated_draft(**item_overrides: object) -> _GeneratedDraft:
    item = {
        "id": "inventory_project",
        "title": "Inventory dashboard",
        "organization": "university project",
        "date_range": None,
        "location": "Riyadh",
        "bullets": ["Built inventory reports using Python and Power BI."],
        "evidence_handles": ["fact_1"],
        **item_overrides,
    }
    return _GeneratedDraft.model_validate(
        {
            "headline": "Data Analyst",
            "professional_summary": (
                "Data Analyst focused on practical inventory reporting with Python and Power BI."
            ),
            "summary_evidence_handles": ["fact_1"],
            "sections": [
                {
                    "key": "project",
                    "title": "Projects",
                    "items": [item],
                }
            ],
        }
    )


class CapturingResumeWriter(_StructuredResumeWriterProvider):
    provider_name = "capture"
    available = True

    def __init__(
        self,
        response: dict[str, Any] | list[dict[str, Any] | ResumeWriterError],
    ) -> None:
        super().__init__(
            api_key="secret",
            model="writer-model",
            interview_model="interview-model",
            timeout_seconds=5,
            max_tokens=4_000,
        )
        self.responses = response if isinstance(response, list) else [response]
        self.calls: list[dict[str, Any]] = []

    async def _structured_response(
        self,
        *,
        schema: type[BaseModel],
        schema_name: str,
        system_instructions: str,
        payload: dict[str, object],
        max_tokens: int,
        model_name: str,
    ) -> BaseModel:
        self.calls.append(
            {
                "schema": schema,
                "schema_name": schema_name,
                "system_instructions": system_instructions,
                "payload": payload,
                "max_tokens": max_tokens,
                "model_name": model_name,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, ResumeWriterError):
            raise response
        return schema.model_validate(response)


def supplemental_verification_response(
    *,
    handle: str,
    field: str,
    pairs: list[tuple[str, str]],
    verdict: str = "pass",
    issue_codes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "verifications": [
            {
                "pair_id": resume_writer_module._supplemental_translation_pair_id(
                    handle=handle,
                    field_name=field,
                    value_index=value_index,
                    source_value=source_value,
                    translated_value=translated_value,
                ),
                "verdict": verdict,
                "issue_codes": issue_codes or [],
            }
            for value_index, (source_value, translated_value) in enumerate(pairs)
        ]
    }


@pytest.mark.asyncio
async def test_generated_question_uses_required_section_order_and_conversation() -> None:
    provider = CapturingResumeWriter(
        {
            "questions": [
                {
                    "id": "petroleum_graduation_date",
                    "category": "education",
                    "question": "متى تخرجت من جامعة البترول، وما الدرجة التي حصلت عليها؟",
                    "why_it_matters": "يكمل تاريخ التعليم والدرجة من دون تكرار اسم الجامعة.",
                    "placeholder": "سنة التخرج والدرجة العلمية.",
                    "required": False,
                }
            ]
        }
    )

    questions = await provider.generate_questions(
        language=PreferredLanguage.AR,
        target_role=None,
        evidence=evidence(category="education"),
        conversation=[
            {"role": "user", "content": "درست في جامعة البترول تخصص مالية."}
        ],
        required_category="education",
        max_questions=1,
    )

    assert questions[0].question.startswith("متى تخرجت من جامعة البترول")
    payload = provider.calls[0]["payload"]
    assert payload["section_order"] == list(RESUME_SECTION_ORDER)
    assert payload["required_category"] == "education"
    assert payload["max_questions"] == 1
    assert payload["conversation"] == [
        {"role": "user", "content": "درست في جامعة البترول تخصص مالية."}
    ]


def test_grounded_draft_allows_professional_rewording_and_target_positioning() -> None:
    draft = _validated_draft(generated_draft(), evidence(), "Data Analyst")

    assert draft.headline == "Data Analyst"
    assert draft.sections[0].items[0].organization == "university project"


def test_generated_draft_must_follow_requested_language() -> None:
    draft = _validated_draft(generated_draft(), evidence(), "Data Analyst")

    _validate_requested_draft_language(draft, PreferredLanguage.EN)
    with pytest.raises(ResumeWriterError, match="requested Arabic"):
        _validate_requested_draft_language(draft, PreferredLanguage.AR)

    arabic_draft = draft.model_copy(
        update={
            "headline": "محلل بيانات",
            "professional_summary": (
                "محلل بيانات يركز على تقارير المخزون باستخدام Python وPower BI "
                "ضمن مشروع جامعي في Riyadh."
            ),
        }
    )
    _validate_requested_draft_language(arabic_draft, PreferredLanguage.AR)


def test_live_patch_language_check_rejects_clear_mismatch_but_allows_short_proper_nouns() -> None:
    arabic_patch = {
        "section_key": "experience",
        "title": "تحليل المبيعات",
        "bullet_candidates": ["أنشأت تقارير عربية أسبوعية للمبيعات."],
        "evidence_handles": ["fact_1"],
    }
    assert not resume_patch_uses_requested_language(arabic_patch, PreferredLanguage.EN)

    proper_noun_patch = {
        "section_key": "skill",
        "title": "Power BI",
        "bullet_candidates": [],
        "evidence_handles": ["fact_1"],
    }
    assert resume_patch_uses_requested_language(proper_noun_patch, PreferredLanguage.EN)


def test_rewrite_restores_a_dropped_open_ended_number_qualifier() -> None:
    assert _restore_open_ended_number_qualifiers(
        "مهني مالي لديه 7 سنوات من الخبرة.",
        "Finance professional with 7+ years of experience.",
    ) == "مهني مالي لديه أكثر من 7 سنوات من الخبرة."
    assert _restore_open_ended_number_qualifiers(
        "Finance professional with 7 years of experience.",
        "Finance professional with 7+ years of experience.",
    ) == "Finance professional with 7+ years of experience."
    assert _restore_open_ended_number_qualifiers(
        "مهني مالي لديه أكثر من أكثر من 7 سنوات من الخبرة.",
        "Finance professional with 7+ years of experience.",
    ) == "مهني مالي لديه أكثر من 7 سنوات من الخبرة."


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "title": "Senior Google Cloud Architect",
                "organization": "Google",
                "bullets": ["Directed Google Cloud architecture."],
            },
            "unsupported seniority or leadership",
        ),
        ({"organization": "Acme Corporation"}, "entity absent from evidence"),
        ({"location": "London"}, "entity absent from evidence"),
    ],
)
def test_grounding_rejects_invented_roles_organizations_and_locations(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ResumeWriterError, match=message):
        _validated_draft(generated_draft(**overrides), evidence(), "Data Analyst")


def test_grounding_rejects_section_supported_by_unrelated_evidence() -> None:
    with pytest.raises(ResumeWriterError, match="matching evidence"):
        _validated_draft(generated_draft(), evidence(category="education"), "Data Analyst")


def test_experience_and_project_schema_rejects_items_without_bullets() -> None:
    with pytest.raises(ValidationError, match="require at least one bullet"):
        generated_draft(bullets=[])


def test_grounding_rejects_number_in_headline_when_absent_from_evidence() -> None:
    generated = generated_draft()
    generated.headline = "Data Analyst with 5 years of experience"

    with pytest.raises(ResumeWriterError, match="numbers absent from evidence"):
        _validated_draft(generated, evidence(), "Data Analyst")


def test_resume_redaction_removes_international_contact_and_bank_details() -> None:
    value = (
        "Call +1 415 555 2671 or 020 7946 0958. "
        "IBAN GB82 WEST 1234 5698 7654 32. "
        "Address 123 Main Street, London. Keep graduation year 2025."
    )

    redacted = _redact_resume_text(value)

    assert "+1 415 555 2671" not in redacted
    assert "020 7946 0958" not in redacted
    assert "GB82 WEST 1234 5698 7654 32" not in redacted
    assert "123 Main Street" not in redacted
    assert "2025" in redacted


def test_grounding_rejects_unstated_scale_automation_and_business_impact() -> None:
    generated = generated_draft(
        bullets=[
            "Built scalable automated reporting pipelines and optimized stakeholder operations."
        ]
    )

    with pytest.raises(ResumeWriterError, match="unsupported scope or impact"):
        _validated_draft(generated, evidence(), "Data Analyst")


def test_grounding_rejects_decorative_section_and_invented_role_titles() -> None:
    decorative_section = generated_draft()
    decorative_section.sections[0].title = "Executive impact"
    with pytest.raises(ResumeWriterError, match="unsupported section title"):
        _validated_draft(decorative_section, evidence(), "Data Analyst")

    with pytest.raises(ResumeWriterError, match="title absent from evidence"):
        _validated_draft(
            generated_draft(title="Python developer"),
            evidence(),
            "Data Analyst",
        )


def test_gpa_policy_omits_low_or_unknown_scale_and_allows_strong_gpa() -> None:
    with pytest.raises(ResumeWriterError, match="below the display threshold"):
        _validate_gpa_policy("GPA 3.1/4")
    with pytest.raises(ResumeWriterError, match="without a known scale"):
        _validate_gpa_policy("GPA 3.8")

    _validate_gpa_policy("GPA 3.2/4")
    _validate_gpa_policy("GPA 3.8/4")
    _validate_gpa_policy("GPA 2.5/4 with honors")


def test_resume_evidence_requires_confirmation_and_uses_structured_source() -> None:
    source_handle = "segment_7"
    confirmed_record = SimpleNamespace(
        id=uuid4(),
        category=FactCategory.EXPERIENCE,
        label="Professional Experience",
        detail=None,
        structured_value={
            "schema_version": "resume_record.v1",
            "record_type": "experience",
            "source_handles": [source_handle],
            "title": "Data Analyst",
            "organization": "Acme",
            "responsibilities": ["Built weekly reports"],
            "private_email": "candidate@example.test",
        },
        source_excerpt="Data Analyst at Acme; built weekly reports",
        verification_status=VerificationStatus.CONFIRMED,
    )
    heading_only = SimpleNamespace(
        id=uuid4(),
        category=FactCategory.SKILL,
        label="Skills",
        detail=None,
        structured_value={},
        source_excerpt="Skills",
        verification_status=VerificationStatus.CONFIRMED,
    )
    unconfirmed = SimpleNamespace(
        id=uuid4(),
        category=FactCategory.SKILL,
        label="Python",
        detail=None,
        structured_value={},
        source_excerpt="Python",
        verification_status=VerificationStatus.UNCONFIRMED,
    )

    result = build_resume_evidence([confirmed_record, heading_only, unconfirmed])

    assert len(result) == 1
    assert result[0].label == "Data Analyst"
    assert result[0].source_handles == (source_handle,)
    assert result[0].source_excerpt == "Data Analyst at Acme; built weekly reports"
    assert "private_email" not in result[0].structured_value
    assert "candidate@example.test" not in result[0].text


def test_adaptive_record_cannot_invent_a_source_section() -> None:
    record = resume_writer_module.ResumeRecord(
        record_type="experience",
        source_handles=["fact_1"],
        source_section="Investment & Trading Experience",
        title="Inventory dashboard using Python and Power BI",
        responsibilities=["Built weekly inventory reports"],
    )

    validated = _validate_record(record, evidence(category="experience"))

    assert validated.source_section is None


def test_adaptive_record_cannot_invent_coursework() -> None:
    support = ResumeEvidence(
        handle="education_fact",
        category="education",
        label="Bachelor of Science in Finance",
        detail="Harbor University",
        verification_status="confirmed",
        source_excerpt="Bachelor of Science in Finance — Harbor University",
    )
    record = resume_writer_module.ResumeRecord(
        record_type="education",
        source_handles=[support.handle],
        title="Bachelor of Science in Finance",
        institution="Harbor University",
        coursework=["Nuclear Reactor Design"],
    )

    with pytest.raises(ResumeWriterError):
        _validate_record(record, (support,))


def test_completion_separates_multiple_experience_handles_instead_of_hiding_a_record() -> None:
    supports = (
        ResumeEvidence(
            handle="analyst_fact",
            category="experience",
            label="Finance Analyst",
            detail="Prepared monthly reports",
            verification_status="confirmed",
            structured_value={
                "source_section": "Professional Experience",
                "organization": "Northstar",
                "responsibilities": ["Prepared monthly reports"],
            },
            source_excerpt="Professional Experience\nFinance Analyst — Northstar",
        ),
        ResumeEvidence(
            handle="trainee_fact",
            category="experience",
            label="Finance Trainee",
            detail="Reconciled ledger accounts",
            verification_status="confirmed",
            structured_value={
                "source_section": "Professional Experience",
                "organization": "Meridian",
                "responsibilities": ["Reconciled ledger accounts"],
            },
            source_excerpt="Professional Experience\nFinance Trainee — Meridian",
        ),
    )
    combined = resume_writer_module.ResumeDraftContent.model_validate(
        {
            "headline": "Finance Analyst",
            "professional_summary": "Prepared monthly reports for Northstar.",
            "summary_evidence_handles": ["analyst_fact"],
            "sections": [
                {
                    "key": "experience",
                    "title": "Professional Experience",
                    "items": [
                        {
                            "id": "combined_experience",
                            "title": "Finance Analyst",
                            "organization": "Northstar",
                            "date_range": None,
                            "location": None,
                            "bullets": ["Prepared monthly reports"],
                            "evidence_handles": ["analyst_fact", "trainee_fact"],
                        }
                    ],
                }
            ],
        }
    )

    completed = resume_writer_module._complete_draft_from_evidence(
        combined,
        supports,
        PreferredLanguage.EN,
    )

    experience_items = next(
        section.items for section in completed.sections if section.key == "experience"
    )
    assert [item.title for item in experience_items] == [
        "Finance Analyst",
        "Finance Trainee",
    ]
    assert [item.evidence_handles for item in experience_items] == [
        ["analyst_fact"],
        ["trainee_fact"],
    ]


def test_completion_does_not_drop_confirmed_narrative_fact_without_bullets() -> None:
    support = ResumeEvidence(
        handle="incomplete_experience_fact",
        category="experience",
        label="Finance Intern",
        detail=None,
        verification_status="confirmed",
        structured_value={
            "source_section": "Professional Experience",
            "organization": "Northstar",
            "date_range": "2025",
            "responsibilities": [],
        },
        source_excerpt="Professional Experience\nFinance Intern — Northstar\n2025",
    )
    skill = ResumeEvidence(
        handle="financial_analysis_skill",
        category="skill",
        label="Financial Analysis",
        detail=None,
        verification_status="confirmed",
        source_excerpt="Skills\nFinancial Analysis",
    )
    draft = resume_writer_module.ResumeDraftContent.model_validate(
        {
            "headline": "Finance Intern",
            "professional_summary": "Finance intern with confirmed financial analysis skills.",
            "summary_evidence_handles": [skill.handle],
            "sections": [
                {
                    "key": "skill",
                    "title": "Skills",
                    "items": [
                        {
                            "id": "financial_analysis",
                            "title": "Financial Analysis",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [skill.handle],
                        }
                    ],
                }
            ],
        }
    )

    completed = resume_writer_module._complete_draft_from_evidence(
        draft,
        (skill, support),
        PreferredLanguage.EN,
    )

    experience = next(section for section in completed.sections if section.key == "experience")
    assert len(experience.items) == 1
    assert experience.items[0].title == "Finance Intern"
    assert experience.items[0].bullets == []
    assert experience.items[0].evidence_handles == [support.handle]


@pytest.mark.asyncio
async def test_generation_preserves_personal_portfolio_context_and_passes_review() -> None:
    responsibility = "Manage a personal investment portfolio and analyze opportunities."
    confirmed_context = (
        "This is my self-managed personal investment portfolio, not work performed for a company."
    )
    support = ResumeEvidence(
        handle="personal_portfolio_fact",
        category="experience",
        label="Investment & Trading Professional",
        detail=f"{responsibility}\n{confirmed_context}",
        verification_status="confirmed",
        structured_value={
            "source_section": "Trading Experience",
            "date_range": "2018 - Present",
            "responsibilities": [responsibility],
            "supplemental_details": {
                "organization_or_context": {
                    "value": confirmed_context,
                    "source": {
                        "kind": "resume_gap_interview",
                        "gap_key": "fact:portfolio:organization_or_context",
                    },
                }
            },
        },
        source_excerpt=(
            "Trading Experience\nInvestment & Trading Professional 2018 - Present\n"
            f"{responsibility}"
        ),
    )
    provider = CapturingResumeWriter(
        {
            "headline": "Investment & Trading Professional",
            "professional_summary": responsibility,
            "summary_evidence_handles": [support.handle],
            "sections": [
                {
                    "key": "trading_experience",
                    "title": "Trading Experience",
                    "items": [
                        {
                            "id": "personal_portfolio",
                            "title": support.label,
                            "organization": None,
                            "date_range": "2018 - Present",
                            "location": None,
                            # Deliberately omit the confirmed follow-up. Completion must restore it.
                            "bullets": [responsibility],
                            "evidence_handles": [support.handle],
                        }
                    ],
                }
            ],
        }
    )

    draft = await provider.generate_draft(
        language=PreferredLanguage.EN,
        target_role=None,
        evidence=(support,),
        answers=[],
    )

    assert len(provider.calls) == 1
    assert provider.calls[0]["schema_name"] == "professional_resume_draft"
    assert provider.calls[0]["payload"]["required_supplemental_evidence"] == [
        {
            "handle": support.handle,
            "field": "organization_or_context",
            "value": confirmed_context,
            "translated_value": confirmed_context,
        }
    ]
    trading = next(section for section in draft.sections if section.key == "trading_experience")
    assert len(trading.items) == 1
    assert responsibility in trading.items[0].bullets
    assert confirmed_context in trading.items[0].bullets
    validate_claim_grounding(
        confirmed_context,
        trading.items[0].evidence_handles,
        (support,),
    )
    review_workspace = SimpleNamespace(
        pending_understanding=None,
        pending_suggestion=None,
    )
    assert workspace_api._review_blockers(draft, review_workspace, (support,)) == []


@pytest.mark.asyncio
async def test_foreign_supplemental_requires_grounded_translation_instead_of_bullet_count() -> None:
    responsibilities = [
        "Manage a personal investment portfolio and analyze opportunities.",
        "Conduct technical and fundamental analysis of equity markets.",
        "Develop trading strategies and risk management plans.",
        "Review market trends and investment opportunities.",
        "Track portfolio performance and trading decisions.",
    ]
    arabic_context = (
        "\u0623\u0645\u0627\u0631\u0633 \u0627\u0644\u062a\u062f\u0627\u0648\u0644 "
        "\u0648\u0627\u0644\u0627\u0633\u062a\u062b\u0645\u0627\u0631 \u0628\u0634\u0643\u0644 "
        "\u0634\u062e\u0635\u064a \u0648\u0623\u062f\u064a\u0631 "
        "\u0645\u062d\u0641\u0638\u062a\u064a "
        "\u0627\u0644\u062e\u0627\u0635\u0629\u060c \u0648\u0644\u064a\u0633 "
        "\u0644\u0635\u0627\u0644\u062d \u0634\u0631\u0643\u0629."
    )
    translated_context = (
        "Personally manage trading and investments with a private portfolio, "
        "not for a company."
    )
    support = ResumeEvidence(
        handle="arabic_personal_portfolio_fact",
        category="experience",
        label="Investment & Trading Professional",
        detail=f"{' '.join(responsibilities)}\n{arabic_context}",
        verification_status="confirmed",
        structured_value={
            "source_section": "Trading Experience",
            "date_range": "2018 - Present",
            "responsibilities": responsibilities,
            "supplemental_details": {
                "organization_or_context": {
                    "value": arabic_context,
                    "source": {"kind": "resume_gap_interview"},
                }
            },
        },
        source_excerpt=(
            "Investment & Trading Professional\n2018 - Present\n"
            + "\n".join(responsibilities)
        ),
    )

    def provider_response(*, translate_context: bool) -> dict[str, object]:
        return {
            "headline": "Investment & Trading Professional",
            "professional_summary": responsibilities[0],
            "summary_evidence_handles": [support.handle],
            "sections": [
                {
                    "key": "trading_experience",
                    "title": "Trading Experience",
                    "items": [
                        {
                            "id": "personal_portfolio",
                            "title": support.label,
                            "organization": None,
                            "date_range": "2018 - Present",
                            "location": None,
                            # Actual failure: title, date, and five original English bullets were
                            # present, but the Arabic addendum was not.
                            "bullets": [
                                *responsibilities,
                                *([translated_context] if translate_context else []),
                            ],
                            "evidence_handles": [support.handle],
                        }
                    ],
                }
            ],
        }

    provider = CapturingResumeWriter(
        [
            {
                "translations": [
                    {
                        "handle": support.handle,
                        "field": "organization_or_context",
                        "value_index": 0,
                        "translated_value": translated_context,
                    }
                ]
            },
            supplemental_verification_response(
                handle=support.handle,
                field="organization_or_context",
                pairs=[(arabic_context, translated_context)],
            ),
            provider_response(translate_context=False),
            provider_response(translate_context=True),
        ]
    )

    draft = await provider.generate_draft(
        language=PreferredLanguage.EN,
        target_role=None,
        evidence=(support,),
        answers=[],
    )

    assert len(provider.calls) == 3
    translation_call = provider.calls[0]
    assert translation_call["schema_name"] == "resume_supplemental_translations"
    assert translation_call["payload"]["required_supplemental_evidence"] == [
        {
            "handle": support.handle,
            "field": "organization_or_context",
            "value_index": 0,
            "value": arabic_context,
        }
    ]
    verification_call = provider.calls[1]
    assert verification_call["schema_name"] == (
        "resume_supplemental_translation_verification"
    )
    assert verification_call["payload"]["translation_pairs"][0][
        "translated_value"
    ] == translated_context
    first_instructions = provider.calls[2]["system_instructions"]
    assert "required_supplemental_evidence" in first_instructions
    required_supplemental = provider.calls[2]["payload"][
        "required_supplemental_evidence"
    ]
    assert required_supplemental == [
        {
            "handle": support.handle,
            "field": "organization_or_context",
            "value": arabic_context,
            "translated_value": translated_context,
        }
    ]
    assert len(provider.responses) == 1
    trading = next(section for section in draft.sections if section.key == "trading_experience")
    assert translated_context in trading.items[0].bullets
    assert arabic_context not in " ".join(trading.items[0].bullets)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_value", "partial_translation", "complete_translation"),
    [
        (
            "\u0623\u062f\u064a\u0631 \u0645\u062d\u0641\u0638\u0629 "
            "\u0627\u0633\u062a\u062b\u0645\u0627\u0631\u064a\u0629 "
            "\u0648\u0623\u062f\u0631\u0651\u0628 \u0627\u0644\u0637\u0644\u0627\u0628",
            "Portfolio",
            "Manage an investment portfolio and train students",
        ),
        (
            "Aramco \u0645\u062d\u0641\u0638\u0629 "
            "\u0627\u0633\u062a\u062b\u0645\u0627\u0631\u064a\u0629 "
            "\u0634\u062e\u0635\u064a\u0629",
            "Personal investment portfolio",
            "Aramco personal investment portfolio",
        ),
        (
            "\u0645\u062d\u0641\u0638\u0629 \u0634\u062e\u0635\u064a\u0629 "
            "\u0648\u0644\u064a\u0633\u062a \u0644\u0635\u0627\u0644\u062d "
            "\u0634\u0631\u0643\u0629",
            "Not a personal portfolio for a company",
            "Personal portfolio, not for a company",
        ),
    ],
    ids=[
        "compound_atom",
        "mixed_script_entity",
        "negation_scope",
    ],
)
async def test_supplemental_translation_requires_complete_scoped_semantics(
    source_value: str,
    partial_translation: str,
    complete_translation: str,
) -> None:
    support = ResumeEvidence(
        handle="scoped_supplemental_translation",
        category="experience",
        label="Investment & Trading Professional",
        detail=source_value,
        verification_status="confirmed",
        structured_value={
            "source_section": "Trading Experience",
            "supplemental_details": {
                "organization_or_context": {"value": source_value},
            },
        },
    )

    def response(translated_value: str) -> dict[str, object]:
        return {
            "translations": [
                {
                    "handle": support.handle,
                    "field": "organization_or_context",
                    "value_index": 0,
                    "translated_value": translated_value,
                }
            ]
        }

    invalid_provider = CapturingResumeWriter(
        [response(partial_translation), response(partial_translation)]
    )
    with pytest.raises(
        ResumeWriterOutputError,
        match="no usable supplemental translations",
    ):
        await invalid_provider._translate_required_supplemental_evidence(
            language=PreferredLanguage.EN,
            evidence=(support,),
        )
    assert len(invalid_provider.calls) == 2

    valid_provider = CapturingResumeWriter(
        [
            response(complete_translation),
            supplemental_verification_response(
                handle=support.handle,
                field="organization_or_context",
                pairs=[(source_value, complete_translation)],
            ),
        ]
    )
    translated = await valid_provider._translate_required_supplemental_evidence(
        language=PreferredLanguage.EN,
        evidence=(support,),
    )
    assert len(valid_provider.calls) == 2
    assert translated == [
        {
            "handle": support.handle,
            "field": "organization_or_context",
            "value": source_value,
            "translated_value": complete_translation,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_value", "bad_translation", "issue_code"),
    [
        (
            "\u0623\u0643\u062a\u0628 \u0627\u0644\u0634\u0639\u0631",
            "Designed nuclear reactors",
            "addition",
        ),
        (
            "\u0645\u062d\u0641\u0638\u0629 \u0634\u062e\u0635\u064a\u0629 "
            "\u0648\u0623\u0643\u062a\u0628 \u0627\u0644\u0634\u0639\u0631",
            "Personal portfolio",
            "omission",
        ),
        (
            "\u062d\u0644\u0644\u062a \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a "
            "\u0627\u0644\u0645\u0627\u0644\u064a\u0629 \u0648\u062f\u0631\u0628\u062a "
            "\u0627\u0644\u0637\u0644\u0627\u0628",
            "Analyzed students and trained financial data",
            "relation_change",
        ),
    ],
    ids=["unknown_hallucination", "unknown_omission", "relation_swap"],
)
async def test_independent_translation_verifier_rejects_semantic_mismatch(
    source_value: str,
    bad_translation: str,
    issue_code: str,
) -> None:
    support = ResumeEvidence(
        handle="independent_translation_verification",
        category="experience",
        label="Creative Experience",
        detail=source_value,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "responsibility_or_scope": {"value": source_value},
            }
        },
    )
    translation_response = {
        "translations": [
            {
                "handle": support.handle,
                "field": "responsibility_or_scope",
                "value_index": 0,
                "translated_value": bad_translation,
            }
        ]
    }
    rejected_verification = supplemental_verification_response(
        handle=support.handle,
        field="responsibility_or_scope",
        pairs=[(source_value, bad_translation)],
        verdict="fail",
        issue_codes=[issue_code],
    )
    provider = CapturingResumeWriter(
        [
            translation_response,
            rejected_verification,
            translation_response,
            rejected_verification,
        ]
    )

    with pytest.raises(
        ResumeWriterOutputError,
        match="no usable supplemental translations",
    ):
        await provider._translate_required_supplemental_evidence(
            language=PreferredLanguage.EN,
            evidence=(support,),
        )

    assert [call["schema_name"] for call in provider.calls] == [
        "resume_supplemental_translations",
        "resume_supplemental_translation_verification",
        "resume_supplemental_translations",
        "resume_supplemental_translation_verification",
    ]
    verification_pair = provider.calls[1]["payload"]["translation_pairs"][0]
    assert verification_pair["source_value"] == source_value
    assert verification_pair["translated_value"] == bad_translation
    assert len(verification_pair["pair_id"]) == 64
    assert source_value not in provider.calls[2]["system_instructions"]


@pytest.mark.asyncio
async def test_verified_unknown_translation_survives_draft_grounding_end_to_end() -> None:
    source_value = "\u0623\u0643\u062a\u0628 \u0627\u0644\u0634\u0639\u0631"
    translated_value = "Write poetry"
    support = ResumeEvidence(
        handle="verified_poetry_translation",
        category="experience",
        label="Creative Writing",
        detail=source_value,
        verification_status="confirmed",
        structured_value={
            "source_section": "Professional Experience",
            "supplemental_details": {
                "responsibility_or_scope": {"value": source_value},
            },
        },
    )
    provider = CapturingResumeWriter(
        [
            {
                "translations": [
                    {
                        "handle": support.handle,
                        "field": "responsibility_or_scope",
                        "value_index": 0,
                        "translated_value": translated_value,
                    }
                ]
            },
            supplemental_verification_response(
                handle=support.handle,
                field="responsibility_or_scope",
                pairs=[(source_value, translated_value)],
            ),
            {
                "headline": "Creative Writing",
                "professional_summary": "Creative writing focused on poetry.",
                "summary_evidence_handles": [support.handle],
                "sections": [
                    {
                        "key": "experience",
                        "title": "Professional Experience",
                        "items": [
                            {
                                "id": "creative_writing",
                                "title": "Creative Writing",
                                "organization": None,
                                "date_range": None,
                                "location": None,
                                "bullets": [translated_value],
                                "evidence_handles": [support.handle],
                            }
                        ],
                    }
                ],
            },
        ]
    )

    draft = await provider.generate_draft(
        language=PreferredLanguage.EN,
        target_role=None,
        evidence=(support,),
        answers=[],
    )

    assert draft.sections[0].items[0].bullets == [translated_value]
    assert len(draft.verified_supplemental_translations) == 1
    proof = draft.verified_supplemental_translations[0]
    assert proof.handle == support.handle
    assert proof.field == "responsibility_or_scope"
    assert proof.verdict == "pass"
    assert "verified_supplemental_translations" not in draft.model_dump(mode="json")
    assert source_value in support.text
    assert translated_value not in support.text
    overlay = resume_writer_module._verified_supplemental_evidence_overlay(
        (support,),
        [
            {
                "handle": support.handle,
                "field": "responsibility_or_scope",
                "value": source_value,
                "translated_value": translated_value,
            }
        ],
    )
    validate_claim_grounding(translated_value, [support.handle], overlay)
    assert translated_value in overlay[0].text
    review_workspace = SimpleNamespace(
        pending_understanding=None,
        pending_suggestion=None,
    )
    assert workspace_api._review_blockers(draft, review_workspace, overlay) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_value", "translated_value"),
    [
        (
            "\u0639\u0645\u0644\u062a \u0641\u064a \u0627\u0644\u0628\u062d\u062b "
            "\u0648\u0627\u0644\u062a\u0637\u0648\u064a\u0631 \u062b\u0645 "
            "\u0643\u062a\u0628\u062a \u0627\u0644\u0634\u0639\u0631",
            "Worked in research and development, then wrote poetry",
        ),
        (
            "\u0637\u0648\u0631\u062a Microsoft Dynamics 365 "
            "\u0628\u0627\u0633\u062a\u062e\u062f\u0627\u0645 Python \u0648Power BI",
            "Developed Microsoft Dynamics 365 using Python and Power BI",
        ),
    ],
    ids=["research_development_then_poetry", "mixed_arabic_product_entities"],
)
async def test_full_value_translation_preserves_conjunctions_and_entities(
    source_value: str,
    translated_value: str,
) -> None:
    support = ResumeEvidence(
        handle="full_value_translation",
        category="project",
        label="Selected Project",
        detail=source_value,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "responsibility_or_scope": {"value": source_value},
            }
        },
    )
    provider = CapturingResumeWriter(
        [
            {
                "translations": [
                    {
                        "handle": support.handle,
                        "field": "responsibility_or_scope",
                        "value_index": 0,
                        "translated_value": translated_value,
                    }
                ]
            },
            supplemental_verification_response(
                handle=support.handle,
                field="responsibility_or_scope",
                pairs=[(source_value, translated_value)],
            ),
        ]
    )

    translated = await provider._translate_required_supplemental_evidence(
        language=PreferredLanguage.EN,
        evidence=(support,),
    )

    assert provider.calls[0]["payload"]["required_supplemental_evidence"] == [
        {
            "handle": support.handle,
            "field": "responsibility_or_scope",
            "value_index": 0,
            "value": source_value,
        }
    ]
    assert translated[0]["translated_value"] == translated_value
    overlay = resume_writer_module._verified_supplemental_evidence_overlay(
        (support,),
        translated,
    )
    assert translated_value in overlay[0].text
    if "Microsoft" in source_value:
        assert not resume_writer_module._requires_translation(
            source_value,
            PreferredLanguage.AR,
        )


@pytest.mark.asyncio
async def test_translation_verifier_transport_failure_is_not_retried() -> None:
    source_value = "\u0623\u0643\u062a\u0628 \u0627\u0644\u0634\u0639\u0631"
    translated_value = "Write poetry"
    support = ResumeEvidence(
        handle="verification_transport",
        category="experience",
        label="Creative Writing",
        detail=source_value,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "responsibility_or_scope": {"value": source_value},
            }
        },
    )
    provider = CapturingResumeWriter(
        [
            {
                "translations": [
                    {
                        "handle": support.handle,
                        "field": "responsibility_or_scope",
                        "value_index": 0,
                        "translated_value": translated_value,
                    }
                ]
            },
            ResumeWriterTransportError("verification timed out", transient=True),
            supplemental_verification_response(
                handle=support.handle,
                field="responsibility_or_scope",
                pairs=[(source_value, translated_value)],
            ),
        ]
    )

    with pytest.raises(ResumeWriterTransportError, match="verification timed out"):
        await provider._translate_required_supplemental_evidence(
            language=PreferredLanguage.EN,
            evidence=(support,),
        )

    assert len(provider.calls) == 2
    assert len(provider.responses) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_kind",
    ["omission", "wrong_handle", "missing_negation"],
)
async def test_invalid_foreign_supplemental_translation_fails_closed_after_one_retry(
    invalid_kind: str,
) -> None:
    arabic_context = (
        "\u0623\u062f\u064a\u0631 \u0645\u062d\u0641\u0638\u0629 "
        "\u0627\u0633\u062a\u062b\u0645\u0627\u0631\u064a\u0629 "
        "\u0634\u062e\u0635\u064a\u0629\u060c \u0648\u0644\u064a\u0633\u062a "
        "\u0644\u0635\u0627\u0644\u062d \u0634\u0631\u0643\u0629."
    )
    translated_context = (
        "Manage a personal investment portfolio, not for a company"
    )
    support = ResumeEvidence(
        handle="foreign_translation_validation",
        category="experience",
        label="Investment & Trading Professional",
        detail=arabic_context,
        verification_status="confirmed",
        structured_value={
            "source_section": "Trading Experience",
            "supplemental_details": {
                "organization_or_context": {"value": arabic_context},
            },
        },
    )
    translation = {
        "handle": support.handle,
        "field": "organization_or_context",
        "value_index": 0,
        "translated_value": translated_context,
    }
    if invalid_kind == "omission":
        invalid_response: dict[str, object] = {"translations": []}
    elif invalid_kind == "wrong_handle":
        invalid_response = {
            "translations": [{**translation, "handle": "wrong_handle"}],
        }
    else:
        invalid_response = {
            "translations": [
                {
                    **translation,
                    "translated_value": "Manage a personal investment portfolio",
                }
            ],
        }
    provider = CapturingResumeWriter([invalid_response, invalid_response])

    with pytest.raises(
        ResumeWriterOutputError,
        match="no usable supplemental translations",
    ):
        await provider.generate_draft(
            language=PreferredLanguage.EN,
            target_role=None,
            evidence=(support,),
            answers=[],
        )

    assert len(provider.calls) == 2
    assert {call["schema_name"] for call in provider.calls} == {
        "resume_supplemental_translations"
    }
    retry_instructions = provider.calls[1]["system_instructions"]
    assert "prior translations failed deterministic validation" in retry_instructions
    assert arabic_context not in retry_instructions


@pytest.mark.asyncio
async def test_supplemental_translation_redacts_private_data_and_does_not_retry_transport() -> None:
    private_context = (
        "\u0623\u062f\u064a\u0631 \u0645\u062d\u0641\u0638\u062a\u064a "
        "\u0627\u0644\u0627\u0633\u062a\u062b\u0645\u0627\u0631\u064a\u0629 "
        "\u0627\u0644\u0634\u062e\u0635\u064a\u0629 \u0628\u0646\u0641\u0633\u064a "
        "\u0648\u0644\u064a\u0633 \u0644\u0635\u0627\u0644\u062d \u0634\u0631\u0643\u0629; "
        "candidate@example.test; +966 50 123 4567"
    )
    support = ResumeEvidence(
        handle="private_foreign_supplemental",
        category="experience",
        label="Investment & Trading Professional",
        detail=private_context,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "organization_or_context": {"value": private_context},
            }
        },
    )
    provider = CapturingResumeWriter(
        ResumeWriterTransportError("provider request failed", transient=True)
    )

    with pytest.raises(ResumeWriterTransportError):
        await provider.generate_draft(
            language=PreferredLanguage.EN,
            target_role=None,
            evidence=(support,),
            answers=[],
        )

    assert len(provider.calls) == 1
    assert provider.calls[0]["schema_name"] == "resume_supplemental_translations"
    serialized_payload = str(provider.calls[0]["payload"])
    assert "candidate@example.test" not in serialized_payload
    assert "+966 50 123 4567" not in serialized_payload
    assert all(
        "@" not in entry["value"] and "+966" not in entry["value"]
        for entry in provider.calls[0]["payload"]["required_supplemental_evidence"]
    )


@pytest.mark.asyncio
async def test_translation_and_verifier_receive_only_redacted_private_values() -> None:
    private_context = (
        "\u0623\u062f\u064a\u0631 \u0645\u062d\u0641\u0638\u062a\u064a "
        "\u0627\u0644\u0627\u0633\u062a\u062b\u0645\u0627\u0631\u064a\u0629 "
        "\u0627\u0644\u0634\u062e\u0635\u064a\u0629\u060c \u0648\u0644\u064a\u0633 "
        "\u0644\u0635\u0627\u0644\u062d \u0634\u0631\u0643\u0629; "
        "candidate@example.test; +966 50 123 4567"
    )
    safe_context = _redact_resume_text(private_context)
    translated_value = (
        "Manage my personal investment portfolio, not for a company; "
        "[redacted]; [redacted]"
    )
    support = ResumeEvidence(
        handle="redacted_verified_translation",
        category="experience",
        label="Investment & Trading Professional",
        detail=private_context,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "organization_or_context": {"value": private_context},
            }
        },
    )
    provider = CapturingResumeWriter(
        [
            {
                "translations": [
                    {
                        "handle": support.handle,
                        "field": "organization_or_context",
                        "value_index": 0,
                        "translated_value": translated_value,
                    }
                ]
            },
            supplemental_verification_response(
                handle=support.handle,
                field="organization_or_context",
                pairs=[(safe_context, translated_value)],
            ),
        ]
    )

    translated = await provider._translate_required_supplemental_evidence(
        language=PreferredLanguage.EN,
        evidence=(support,),
    )

    serialized_calls = str(provider.calls)
    assert "candidate@example.test" not in serialized_calls
    assert "+966 50 123 4567" not in serialized_calls
    assert safe_context in str(provider.calls[0]["payload"])
    assert safe_context in str(provider.calls[1]["payload"])
    assert translated[0]["value"] == safe_context
    assert translated[0]["translated_value"] == translated_value


def test_required_supplemental_payload_redacts_contact_details() -> None:
    private_value = (
        "Personal investment portfolio; candidate@example.test; +966 50 123 4567"
    )
    support = ResumeEvidence(
        handle="private_supplemental_fact",
        category="experience",
        label="Investment & Trading Professional",
        detail=None,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "organization_or_context": {"value": private_value},
            }
        },
    )

    payload = resume_writer_module._required_supplemental_evidence((support,))
    serialized_payload = str(payload)

    assert "Personal investment portfolio" in serialized_payload
    assert "candidate@example.test" not in serialized_payload
    assert "+966 50 123 4567" not in serialized_payload


def test_every_foreign_supplemental_value_requires_its_own_grounded_translation() -> None:
    arabic_context = (
        "\u0645\u062d\u0641\u0638\u0629 \u0627\u0633\u062a\u062b\u0645\u0627\u0631\u064a\u0629 "
        "\u0634\u062e\u0635\u064a\u0629"
    )
    arabic_negation = (
        "\u0644\u064a\u0633\u062a \u0644\u0635\u0627\u0644\u062d \u0634\u0631\u0643\u0629"
    )
    full_answer = f"{arabic_context}. {arabic_negation}."
    provenance = {
        "kind": "resume_gap_interview",
        "gap_key": "experience:record:organization_or_context",
    }
    support = ResumeEvidence(
        handle="two_supplemental_values",
        category="experience",
        label="Investment & Trading Professional",
        detail=full_answer,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "organization_or_context": {
                    "value": [arabic_context, arabic_negation],
                    "source": provenance,
                },
            },
            "supplemental_addenda": [
                {
                    "text": full_answer,
                    "requested_fields": ["organization_or_context"],
                    "question": "portfolio context",
                    "source": provenance,
                }
            ],
        },
    )
    translated_context = "Personal investment portfolio"

    without_context = resume_writer_module._without_supplemental_value(
        support,
        arabic_context,
    )
    assert without_context.structured_value["supplemental_details"][
        "organization_or_context"
    ] == {
        "value": [arabic_negation],
        "source": provenance,
    }
    assert without_context.structured_value["supplemental_addenda"] == [
        {
            "text": arabic_negation,
            "requested_fields": ["organization_or_context"],
            "source": provenance,
        }
    ]
    assert arabic_context not in str(without_context.detail)
    assert arabic_context not in str(without_context.structured_value)

    assert not resume_writer_module._foreign_supplemental_has_grounded_translation(
        support,
        PreferredLanguage.EN,
        [translated_context],
    )
    assert resume_writer_module._foreign_supplemental_has_grounded_translation(
        support,
        PreferredLanguage.EN,
        [translated_context, "Not for a company"],
    )


def test_education_full_answer_addendum_is_scoped_per_translated_field() -> None:
    degree = "\u0628\u0643\u0627\u0644\u0648\u0631\u064a\u0648\u0633"
    field = "\u0645\u0627\u0644\u064a\u0629"
    institution = (
        "\u062c\u0627\u0645\u0639\u0629 \u0627\u0644\u0645\u0644\u0643 \u0641\u0647\u062f "
        "\u0644\u0644\u0628\u062a\u0631\u0648\u0644 "
        "\u0648\u0627\u0644\u0645\u0639\u0627\u062f\u0646"
    )
    full_answer = " ".join(
        (
            "\u062d\u0635\u0644\u062a \u0639\u0644\u0649",
            degree,
            "\u0641\u064a",
            field,
            "\u0645\u0646",
            institution,
            "\u0648\u062a\u062e\u0631\u062c\u062a \u0639\u0627\u0645 2025",
        )
    )
    provenance = {
        "kind": "resume_gap_interview",
        "gap_key": "education:record",
    }
    supplemental_values = {
        "degree": degree,
        "field": field,
        "institution": institution,
        "graduation_date": "2025",
    }
    support = ResumeEvidence(
        handle="arabic_education_gap_answer",
        category="education",
        label="Education",
        detail=full_answer,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                field_name: {"value": value, "source": provenance}
                for field_name, value in supplemental_values.items()
            },
            "supplemental_addenda": [
                {
                    "text": full_answer,
                    "requested_fields": list(supplemental_values),
                    "question": "education details",
                    "source": provenance,
                }
            ],
        },
    )
    translated_title = "Bachelor in Finance"
    translated_institution = "King Fahd University of Petroleum and Minerals"

    assert not resume_writer_module._foreign_supplemental_has_grounded_translation(
        support,
        PreferredLanguage.EN,
        [translated_institution, "2025"],
    )
    assert not resume_writer_module._foreign_supplemental_has_grounded_translation(
        support,
        PreferredLanguage.EN,
        [translated_title, "2025"],
    )
    assert resume_writer_module._foreign_supplemental_has_grounded_translation(
        support,
        PreferredLanguage.EN,
        [translated_title, translated_institution, "2025"],
    )

    provider_draft = ResumeDraftContent.model_validate(
        {
            "headline": translated_title,
            "professional_summary": "Finance graduate with confirmed education details.",
            "summary_evidence_handles": [support.handle],
            "sections": [
                {
                    "key": "education",
                    "title": "Education",
                    "items": [
                        {
                            "id": "finance_degree",
                            "title": translated_title,
                            "organization": translated_institution,
                            "date_range": "2025",
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [support.handle],
                        }
                    ],
                }
            ],
        }
    )

    completed = resume_writer_module._complete_draft_from_evidence(
        provider_draft,
        (support,),
        PreferredLanguage.EN,
    )

    education_item = completed.sections[0].items[0]
    assert education_item.title == translated_title
    assert education_item.organization == translated_institution
    assert education_item.date_range == "2025"


def test_foreign_narrative_requires_a_translation_for_every_distinct_atom() -> None:
    financial_analysis = (
        "\u062d\u0644\u0644\u062a \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a "
        "\u0627\u0644\u0645\u0627\u0644\u064a\u0629"
    )
    sales_reports = (
        "\u0623\u0639\u062f\u062f\u062a \u062a\u0642\u0627\u0631\u064a\u0631 "
        "\u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a"
    )
    excel = "\u0625\u0643\u0633\u0644"
    support = ResumeEvidence(
        handle="arabic_finance_narrative",
        category="experience",
        label="Finance Analyst",
        detail=f"{financial_analysis}. {sales_reports}. {excel}.",
        verification_status="confirmed",
        structured_value={
            "responsibilities": [financial_analysis],
            "outcomes": [sales_reports],
            "tools": [excel],
        },
        source_excerpt=f"Finance Analyst\n{financial_analysis}\n{sales_reports}\n{excel}",
    )
    first_analysis = "Analyzed financial data using Excel."
    duplicate_analysis = "Financial data analysis using Excel."
    translated_sales = "Produced sales reports."

    assert not resume_writer_module._foreign_narrative_has_grounded_translation(
        support,
        PreferredLanguage.EN,
        [first_analysis, duplicate_analysis],
    )
    assert not resume_writer_module._foreign_narrative_has_grounded_translation(
        support,
        PreferredLanguage.EN,
        ["Financial data analysis.", translated_sales],
    )
    assert resume_writer_module._foreign_narrative_has_grounded_translation(
        support,
        PreferredLanguage.EN,
        [first_analysis, translated_sales],
    )

    def provider_draft(bullets: list[str]) -> ResumeDraftContent:
        return ResumeDraftContent.model_validate(
            {
                "headline": "Finance Analyst",
                "professional_summary": "Finance analyst with financial reporting experience.",
                "summary_evidence_handles": [support.handle],
                "sections": [
                    {
                        "key": "experience",
                        "title": "Professional Experience",
                        "items": [
                            {
                                "id": "finance_analyst",
                                "title": "Finance Analyst",
                                "organization": None,
                                "date_range": None,
                                "location": None,
                                "bullets": bullets,
                                "evidence_handles": [support.handle],
                            }
                        ],
                    }
                ],
            }
        )

    with pytest.raises(ResumeWriterError, match="translated narrative detail"):
        resume_writer_module._complete_draft_from_evidence(
            provider_draft([first_analysis, duplicate_analysis]),
            (support,),
            PreferredLanguage.EN,
        )

    completed = resume_writer_module._complete_draft_from_evidence(
        provider_draft([first_analysis, translated_sales]),
        (support,),
        PreferredLanguage.EN,
    )
    completed_bullets = completed.sections[0].items[0].bullets
    assert completed_bullets == [first_analysis, translated_sales]
    assert not any(
        value in " ".join(completed_bullets)
        for value in (financial_analysis, sales_reports, excel)
    )


def test_hadi_english_narrative_completion_is_unchanged() -> None:
    responsibilities = [
        "Performed monthly variance analysis, cost control, and internal financial reviews",
        "Supported audit processes, compliance checks, and management reporting",
    ]
    support = ResumeEvidence(
        handle="hadi_cost_control",
        category="experience",
        label="Cost Control & Finance Analyst",
        detail=None,
        verification_status="confirmed",
        structured_value={
            "source_section": "Professional Experience",
            "organization": "Northstar Consumer Brands",
            "date_range": "2025 - Present",
            "responsibilities": responsibilities,
            "tools": ["Excel"],
        },
    )
    provider_draft = ResumeDraftContent.model_validate(
        {
            "headline": support.label,
            "professional_summary": responsibilities[0],
            "summary_evidence_handles": [support.handle],
            "sections": [
                {
                    "key": "experience",
                    "title": "Professional Experience",
                    "items": [
                        {
                            "id": "cost_control_finance_analyst",
                            "title": support.label,
                            "organization": "Northstar Consumer Brands",
                            "date_range": "2025 - Present",
                            "location": None,
                            "bullets": responsibilities,
                            "evidence_handles": [support.handle],
                        }
                    ],
                }
            ],
        }
    )

    completed = resume_writer_module._complete_draft_from_evidence(
        provider_draft,
        (support,),
        PreferredLanguage.EN,
    )

    assert completed.sections[0].items[0].bullets == responsibilities


def test_same_language_compact_organization_context_becomes_item_metadata() -> None:
    context = "Self-managed personal investment portfolio"
    responsibility = "Analyze investment opportunities for a personal portfolio."
    support = ResumeEvidence(
        handle="compact_personal_portfolio_context",
        category="experience",
        label="Investment & Trading Professional",
        detail=f"{responsibility}\n{context}",
        verification_status="confirmed",
        structured_value={
            "source_section": "Trading Experience",
            "responsibilities": [responsibility],
            "supplemental_details": {
                "organization_or_context": {"value": context},
            },
        },
    )
    provider_draft = ResumeDraftContent.model_validate(
        {
            "headline": support.label,
            "professional_summary": responsibility,
            "summary_evidence_handles": [support.handle],
            "sections": [
                {
                    "key": "trading_experience",
                    "title": "Trading Experience",
                    "items": [
                        {
                            "id": "personal_portfolio",
                            "title": support.label,
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [responsibility],
                            "evidence_handles": [support.handle],
                        }
                    ],
                }
            ],
        }
    )

    completed = resume_writer_module._complete_draft_from_evidence(
        provider_draft,
        (support,),
        PreferredLanguage.EN,
    )

    item = completed.sections[0].items[0]
    assert item.organization == context
    assert context not in item.bullets


@pytest.mark.asyncio
async def test_education_and_skills_only_keep_grounded_provider_summary() -> None:
    supports = (
        ResumeEvidence(
            handle="education_fact",
            category="education",
            label="Bachelor of Science in Finance",
            detail="Harbor University, completed 2023",
            verification_status="confirmed",
            structured_value={
                "institution": "Harbor University",
                "date_range": "2023",
            },
        ),
        ResumeEvidence(
            handle="skill_fact",
            category="skill",
            label="Financial Modeling",
            detail="Applied financial modeling to university budgeting case studies",
            verification_status="confirmed",
        ),
    )
    provider_summary = (
        "Applied financial modeling to university budgeting case studies."
    )
    provider = CapturingResumeWriter(
        {
            "headline": "Financial Modeling",
            "professional_summary": provider_summary,
            "summary_evidence_handles": ["skill_fact"],
            "sections": [
                {
                    "key": "education",
                    "title": "Education",
                    "items": [
                        {
                            "id": "finance_degree",
                            "title": "Bachelor of Science in Finance",
                            "organization": "Harbor University",
                            "date_range": "2023",
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["education_fact"],
                        }
                    ],
                },
                {
                    "key": "skill",
                    "title": "Skills",
                    "items": [
                        {
                            "id": "financial_modeling",
                            "title": "Financial Modeling",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["skill_fact"],
                        }
                    ],
                },
            ],
        }
    )

    draft = await provider.generate_draft(
        language=PreferredLanguage.EN,
        target_role=None,
        evidence=supports,
        answers=[],
    )

    assert draft.professional_summary == provider_summary
    assert draft.summary_evidence_handles == ["skill_fact"]


@pytest.mark.asyncio
async def test_completion_merges_exact_compact_fact_duplicates_and_keeps_richer_language() -> None:
    supports = (
        ResumeEvidence(
            handle="english_plain",
            category="language",
            label="English",
            detail=None,
            verification_status="confirmed",
        ),
        ResumeEvidence(
            handle="english_fluent",
            category="language",
            label="English",
            detail="Fluent",
            verification_status="confirmed",
            structured_value={"proficiency": "Fluent"},
        ),
        ResumeEvidence(
            handle="arabic_native",
            category="language",
            label="Arabic",
            detail="Native",
            verification_status="confirmed",
            structured_value={"proficiency": "Native"},
        ),
        ResumeEvidence(
            handle="skill_primary",
            category="skill",
            label="Financial Modeling",
            detail="Financial modeling supports practical scenario analysis",
            verification_status="confirmed",
        ),
        ResumeEvidence(
            handle="skill_duplicate",
            category="skill",
            label="Financial Modeling",
            detail="Financial modeling supports practical scenario analysis",
            verification_status="confirmed",
        ),
        ResumeEvidence(
            handle="cert_primary",
            category="certification",
            label="CME-1 Certification",
            detail="CME-1 Certification",
            verification_status="confirmed",
        ),
        ResumeEvidence(
            handle="cert_duplicate",
            category="certification",
            label="CME-1 Certification",
            detail="CME-1 Certification",
            verification_status="confirmed",
        ),
    )
    provider = CapturingResumeWriter(
        {
            "headline": "Financial Modeling",
            "professional_summary": (
                "Financial modeling supports practical scenario analysis."
            ),
            "summary_evidence_handles": ["skill_primary"],
            "sections": [
                {
                    "key": "certification",
                    "title": "Certifications",
                    "items": [
                        {
                            "id": "cme_1_primary",
                            "title": "CME-1 Certification",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["cert_primary"],
                        },
                        {
                            "id": "cme_1_duplicate",
                            "title": "CME-1 Certification",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["cert_duplicate"],
                        },
                    ],
                },
                {
                    "key": "skill",
                    "title": "Skills",
                    "items": [
                        {
                            "id": "financial_modeling_primary",
                            "title": "Financial Modeling",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["skill_primary"],
                        },
                        {
                            "id": "financial_modeling_duplicate",
                            "title": "Financial Modeling",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["skill_duplicate"],
                        },
                    ],
                },
                {
                    "key": "language",
                    "title": "Languages",
                    "items": [
                        {
                            "id": "english_plain",
                            "title": "English",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["english_plain"],
                        },
                        {
                            "id": "english_fluent",
                            "title": "English",
                            "organization": "Fluent",
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["english_fluent"],
                        },
                        {
                            "id": "arabic_native",
                            "title": "Arabic",
                            "organization": "Native",
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["arabic_native"],
                        },
                    ],
                },
            ],
        }
    )

    draft = await provider.generate_draft(
        language=PreferredLanguage.EN,
        target_role=None,
        evidence=supports,
        answers=[],
    )
    sections = {section.key: section for section in draft.sections}

    assert [
        (item.title, item.organization) for item in sections["language"].items
    ] == [("English", "Fluent"), ("Arabic", "Native")]
    assert set(sections["language"].items[0].evidence_handles) == {
        "english_plain",
        "english_fluent",
    }
    assert sections["language"].items[1].evidence_handles == ["arabic_native"]
    assert [item.title for item in sections["skill"].items] == ["Financial Modeling"]
    assert set(sections["skill"].items[0].evidence_handles) == {
        "skill_primary",
        "skill_duplicate",
    }
    assert [item.title for item in sections["certification"].items] == [
        "CME-1 Certification"
    ]
    assert set(sections["certification"].items[0].evidence_handles) == {
        "cert_primary",
        "cert_duplicate",
    }


def test_compact_duplicate_merge_refuses_to_truncate_thirteen_handles() -> None:
    handles = [f"skill_fact_{index}" for index in range(13)]
    items = [
        resume_writer_module.ResumeDraftItem(
            id="financial_modeling_a",
            title="Financial Modeling",
            evidence_handles=handles[:7],
        ),
        resume_writer_module.ResumeDraftItem(
            id="financial_modeling_b",
            title="Financial Modeling",
            evidence_handles=handles[7:],
        ),
    ]

    completed = resume_writer_module._merge_compatible_duplicate_items(items)

    assert len(completed) == 2
    assert [handle for item in completed for handle in item.evidence_handles] == handles


def test_compact_duplicate_merge_refuses_to_truncate_twenty_one_bullets() -> None:
    claims = [f"Grounded language claim {index:02d}" for index in range(21)]
    items = [
        resume_writer_module.ResumeDraftItem(
            id="english_a",
            title="English",
            organization="Fluent",
            bullets=claims[:11],
            evidence_handles=["english_fact_a"],
        ),
        resume_writer_module.ResumeDraftItem(
            id="english_b",
            title="English",
            organization="Fluent",
            bullets=claims[11:],
            evidence_handles=["english_fact_b"],
        ),
    ]

    completed = resume_writer_module._merge_compatible_duplicate_items(items)

    assert len(completed) == 2
    assert [claim for item in completed for claim in item.bullets] == claims


def test_compact_dedupe_preserves_symbolic_skills_and_merges_three_compatible_items() -> None:
    items = [
        resume_writer_module.ResumeDraftItem(
            id="skill_c",
            title="C",
            evidence_handles=["c_fact"],
        ),
        resume_writer_module.ResumeDraftItem(
            id="skill_c_sharp",
            title="C#",
            evidence_handles=["c_sharp_fact"],
        ),
        *[
            resume_writer_module.ResumeDraftItem(
                id=f"skill_sql_{index}",
                title="SQL",
                evidence_handles=[f"sql_fact_{index}"],
            )
            for index in range(3)
        ],
    ]

    completed = resume_writer_module._merge_compatible_duplicate_items(items)

    assert [item.title for item in completed] == ["C", "C#", "SQL"]
    assert completed[0].evidence_handles == ["c_fact"]
    assert completed[1].evidence_handles == ["c_sharp_fact"]
    assert set(completed[2].evidence_handles) == {
        "sql_fact_0",
        "sql_fact_1",
        "sql_fact_2",
    }


def test_completion_never_merges_same_title_experiences_from_different_roles() -> None:
    supports = (
        ResumeEvidence(
            handle="analyst_northstar",
            category="experience",
            label="Finance Analyst",
            detail="Prepared monthly cost reports",
            verification_status="confirmed",
            structured_value={
                "source_section": "Professional Experience",
                "organization": "Northstar",
                "date_range": "2025 - Present",
                "responsibilities": ["Prepared monthly cost reports"],
            },
        ),
        ResumeEvidence(
            handle="analyst_meridian",
            category="experience",
            label="Finance Analyst",
            detail="Reconciled treasury accounts",
            verification_status="confirmed",
            structured_value={
                "source_section": "Professional Experience",
                "organization": "Meridian",
                "date_range": "2024",
                "responsibilities": ["Reconciled treasury accounts"],
            },
        ),
    )
    provider_draft = resume_writer_module.ResumeDraftContent.model_validate(
        {
            "headline": "Finance Analyst",
            "professional_summary": (
                "Prepared monthly cost reports. Reconciled treasury accounts."
            ),
            "summary_evidence_handles": [
                "analyst_northstar",
                "analyst_meridian",
            ],
            "sections": [
                {
                    "key": "experience",
                    "title": "Professional Experience",
                    "items": [
                        {
                            "id": "finance_analyst_northstar",
                            "title": "Finance Analyst",
                            "organization": "Northstar",
                            "date_range": "2025 - Present",
                            "location": None,
                            "bullets": ["Prepared monthly cost reports"],
                            "evidence_handles": ["analyst_northstar"],
                        },
                        {
                            "id": "finance_analyst_meridian",
                            "title": "Finance Analyst",
                            "organization": "Meridian",
                            "date_range": "2024",
                            "location": None,
                            "bullets": ["Reconciled treasury accounts"],
                            "evidence_handles": ["analyst_meridian"],
                        },
                    ],
                }
            ],
        }
    )

    completed = resume_writer_module._complete_draft_from_evidence(
        provider_draft,
        supports,
        PreferredLanguage.EN,
    )
    items = next(
        section.items for section in completed.sections if section.key == "experience"
    )

    assert [
        (item.organization, item.date_range, item.evidence_handles) for item in items
    ] == [
        ("Northstar", "2025 - Present", ["analyst_northstar"]),
        ("Meridian", "2024", ["analyst_meridian"]),
    ]


def test_legacy_trading_role_without_source_section_keeps_its_own_section() -> None:
    support = ResumeEvidence(
        handle="legacy_trading_fact",
        category="experience",
        label="Investment & Trading Professional",
        detail="Active trader in regional equity markets",
        verification_status="confirmed",
    )

    assert resume_writer_module._evidence_section_key(support) == "trading_experience"


@pytest.mark.asyncio
async def test_fact_order_and_complete_responsibilities_survive_draft_and_pdf_preview() -> None:
    education_coursework = [
        "Applied Econometrics",
        "Financial Accounting",
        "Risk Management",
    ]
    professional_responsibilities = [
        "Prepared 12 monthly forecasts",
        "Reconciled 48 ledger accounts",
        "Reduced reporting cycle from 8 days to 5 days",
    ]
    trading_responsibilities = [
        "Reviewed 2,400 simulated trades",
        "Tested 6 strategies across 4 market regimes",
        "Kept maximum drawdown within 9%",
    ]

    def confirmed_fact(
        category: FactCategory,
        title: str,
        *,
        source_handle: str,
        source_excerpt: str,
        **structured_fields: object,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid4(),
            category=category,
            label=title,
            detail=None,
            structured_value={
                "schema_version": "resume_record.v1",
                "record_type": category.value,
                "source_handles": [source_handle],
                "title": title,
                **structured_fields,
            },
            source_excerpt=source_excerpt,
            verification_status=VerificationStatus.CONFIRMED,
        )

    facts = [
        confirmed_fact(
            FactCategory.EDUCATION,
            "Bachelor of Science in Applied Economics",
            source_handle="source_education",
            source_excerpt=(
                "Education\n"
                "Bachelor of Science in Applied Economics, Harbor University, completed 2023\n"
                "Relevant Courses: " + ", ".join(education_coursework)
            ),
            degree="Bachelor of Science in Applied Economics",
            institution="Harbor University",
            date_range="2023",
        ),
        confirmed_fact(
            FactCategory.EXPERIENCE,
            "Operations Analyst",
            source_handle="source_professional_experience",
            source_excerpt=(
                "Operations Analyst at Nimbus Labs from 2023 to Present. "
                + "; ".join(professional_responsibilities)
            ),
            organization="Nimbus Labs",
            date_range="2023 to Present",
            responsibilities=professional_responsibilities,
        ),
        confirmed_fact(
            FactCategory.EXPERIENCE,
            "Independent Trading Researcher",
            source_handle="source_trading_experience",
            source_excerpt=(
                "Investment & Trading Experience\n"
                "Independent Trading Researcher from 2020 to Present. "
                + "; ".join(trading_responsibilities)
            ),
            date_range="2020 to Present",
            responsibilities=trading_responsibilities,
        ),
        confirmed_fact(
            FactCategory.CERTIFICATION,
            "Aurora Financial Analysis Certificate",
            source_handle="source_certification",
            source_excerpt=(
                "Aurora Financial Analysis Certificate, Northstar Academy, awarded 2022"
            ),
            issuer="Northstar Academy",
            date_range="2022",
        ),
        confirmed_fact(
            FactCategory.SKILL,
            "Python",
            source_handle="source_skill",
            source_excerpt="Python",
        ),
        confirmed_fact(
            FactCategory.LANGUAGE,
            "English",
            source_handle="source_language",
            source_excerpt="English - Fluent",
            proficiency="Fluent",
        ),
    ]
    resume_evidence = build_resume_evidence(facts)
    evidence_by_label = {item.label: item for item in resume_evidence}
    professional_handle = evidence_by_label["Operations Analyst"].handle
    trading_handle = evidence_by_label["Independent Trading Researcher"].handle
    education_handle = evidence_by_label[
        "Bachelor of Science in Applied Economics"
    ].handle
    certification_handle = evidence_by_label[
        "Aurora Financial Analysis Certificate"
    ].handle
    skill_handle = evidence_by_label["Python"].handle
    language_handle = evidence_by_label["English"].handle

    assert [item.category for item in resume_evidence] == [
        "education",
        "experience",
        "experience",
        "certification",
        "skill",
        "language",
    ]
    assert evidence_by_label["Operations Analyst"].structured_value[
        "responsibilities"
    ] == professional_responsibilities
    assert evidence_by_label["Independent Trading Researcher"].structured_value[
        "responsibilities"
    ] == trading_responsibilities

    def generated_response(*, complete: bool) -> dict[str, object]:
        professional_bullets = (
            professional_responsibilities
            if complete
            else ["Prepared monthly forecasts"]
        )
        trading_bullets = (
            trading_responsibilities if complete else ["Reviewed simulated trades"]
        )
        return {
            "headline": "Education Experience",
            "professional_summary": "Prepared 12 monthly forecasts.",
            "summary_evidence_handles": [professional_handle, trading_handle],
            # Deliberately reverse the sections. The server owns the final draft/preview order and
            # must keep explicit investment/trading evidence out of Professional Experience.
            "sections": [
                {
                    "key": "language",
                    "title": "Languages",
                    "items": [
                        {
                            "id": "language_english",
                            "title": "English",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": ["Fluent"],
                            "evidence_handles": [language_handle],
                        }
                    ],
                },
                {
                    "key": "skill",
                    "title": "Skills",
                    "items": [
                        {
                            "id": "skill_python",
                            "title": "Python",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [skill_handle],
                        }
                    ],
                },
                {
                    "key": "certification",
                    "title": "Certifications",
                    "items": [
                        {
                            "id": "certification_aurora",
                            "title": "Aurora Financial Analysis Certificate",
                            "organization": "Northstar Academy",
                            "date_range": "2022",
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [certification_handle],
                        }
                    ],
                },
                {
                    "key": "trading_experience",
                    "title": "Investment & Trading Experience",
                    "items": [
                        {
                            "id": "trading_researcher",
                            "title": "Independent Trading Researcher",
                            "organization": None,
                            "date_range": "2020 to Present",
                            "location": None,
                            "bullets": trading_bullets,
                            "evidence_handles": [trading_handle],
                        }
                    ],
                },
                {
                    "key": "experience",
                    "title": "Professional Experience",
                    "items": [
                        {
                            "id": "operations_analyst",
                            "title": "Operations Analyst",
                            "organization": "Nimbus Labs",
                            "date_range": "2023 to Present",
                            "location": None,
                            "bullets": professional_bullets,
                            "evidence_handles": [professional_handle],
                        },
                    ],
                },
                {
                    "key": "education",
                    "title": "Education",
                    "items": [
                        {
                            "id": "education_applied_economics",
                            "title": "Bachelor of Science in Applied Economics",
                            "organization": "Harbor University",
                            "date_range": "2023",
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [education_handle],
                        }
                    ],
                },
            ],
        }

    provider = CapturingResumeWriter(
        [
            generated_response(complete=False),
            generated_response(complete=True),
        ]
    )
    draft = await provider.generate_draft(
        language=PreferredLanguage.EN,
        target_role=None,
        evidence=resume_evidence,
        answers=[],
    )

    expected_section_order = [
        "education",
        "experience",
        "trading_experience",
        "certification",
        "skill",
        "language",
    ]
    failures: list[str] = []
    actual_section_order = [section.key for section in draft.sections]
    if actual_section_order != expected_section_order:
        failures.append(
            f"draft section order was {actual_section_order}, expected {expected_section_order}"
        )

    if "Reconciled 48 ledger accounts" not in draft.professional_summary:
        failures.append("professional summary remained a single abbreviated sentence")
    if "Reviewed 2,400 simulated trades" not in draft.professional_summary:
        failures.append("professional summary omitted the separate trading background")
    if draft.headline != "Operations Analyst | Independent Trading Researcher":
        failures.append(f"draft kept a generic headline: {draft.headline!r}")

    education_section = next(
        section for section in draft.sections if section.key == "education"
    )
    expected_coursework = "Relevant Coursework: " + ", ".join(education_coursework)
    if expected_coursework not in education_section.items[0].bullets:
        failures.append("draft omitted relevant coursework from the education record")

    professional_section = next(
        section for section in draft.sections if section.key == "experience"
    )
    trading_section = next(
        section for section in draft.sections if section.key == "trading_experience"
    )
    actual_professional_items = [item.title for item in professional_section.items]
    if actual_professional_items != ["Operations Analyst"]:
        failures.append(
            "Professional Experience contained "
            f"{actual_professional_items}, expected only ['Operations Analyst']"
        )
    actual_trading_items = [item.title for item in trading_section.items]
    if actual_trading_items != ["Independent Trading Researcher"]:
        failures.append(
            "Investment & Trading Experience contained "
            f"{actual_trading_items}, expected only ['Independent Trading Researcher']"
        )
    experience_by_title = {
        item.title: item
        for section in (professional_section, trading_section)
        for item in section.items
    }
    expected_responsibilities = {
        "Operations Analyst": professional_responsibilities,
        "Independent Trading Researcher": trading_responsibilities,
    }
    for title, expected_bullets in expected_responsibilities.items():
        actual_bullets = [
            bullet.rstrip(".") for bullet in experience_by_title[title].bullets
        ]
        if actual_bullets != expected_bullets:
            failures.append(
                f"draft bullets for {title!r} were {actual_bullets}, "
                f"expected {expected_bullets}"
            )

    draft_text = " ".join(
        (
            draft.headline,
            draft.professional_summary,
            *(
                text
                for section in draft.sections
                for item in section.items
                for text in (
                    item.title,
                    item.organization or "",
                    item.date_range or "",
                    *item.bullets,
                )
            ),
        )
    )
    expected_numbers = ("12", "48", "8", "5", "2,400", "6", "4", "9%")
    missing_draft_numbers = [number for number in expected_numbers if number not in draft_text]
    if missing_draft_numbers:
        failures.append(f"draft omitted numbers {missing_draft_numbers}")

    preview = render_resume_pdf(
        profile_name="Synthetic Candidate",
        city=None,
        language=PreferredLanguage.EN,
        draft=draft,
        contact=ResumeExportContact(),
    )
    preview_text = " ".join(
        (page.extract_text() or "")
        for page in PdfReader(BytesIO(preview)).pages
    )
    preview_text = " ".join(preview_text.split())
    education_position = preview_text.find("Education")
    experience_position = preview_text.find("Professional Experience")
    professional_position = preview_text.find(
        "Operations Analyst", max(0, experience_position)
    )
    trading_section_position = preview_text.find("Investment & Trading Experience")
    trading_position = preview_text.find(
        "Independent Trading Researcher", max(0, trading_section_position)
    )
    certification_position = preview_text.find("Certifications")
    skill_position = preview_text.find("Skills")
    language_position = preview_text.find("Languages")
    preview_positions = [
        education_position,
        experience_position,
        professional_position,
        trading_section_position,
        trading_position,
        certification_position,
        skill_position,
        language_position,
    ]
    if -1 in preview_positions or preview_positions != sorted(preview_positions):
        failures.append(
            "PDF preview order was not Education, Professional Experience, Investment & "
            f"Trading Experience, Certifications, Skills, Languages: {preview_positions}"
        )
    for responsibility in (*professional_responsibilities, *trading_responsibilities):
        if responsibility not in preview_text:
            failures.append(f"PDF preview omitted responsibility {responsibility!r}")
    for course in education_coursework:
        if course not in preview_text:
            failures.append(f"PDF preview omitted relevant course {course!r}")
    missing_preview_numbers = [
        number for number in expected_numbers if number not in preview_text
    ]
    if missing_preview_numbers:
        failures.append(f"PDF preview omitted numbers {missing_preview_numbers}")

    assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_source_order_headline_and_summary_survive_reversed_provider_draft_and_pdf() -> None:
    training_sentence = (
        "Trained 1,200+ students in trading strategy execution, market analysis, and risk "
        "management."
    )
    training_program_sentence = (
        "Designed structured educational programs covering strategy logic, psychology, and "
        "discipline."
    )
    guest_lecturer_sentence = (
        "Guest lecturer on trading and risk management at GTU."
    )
    us_trading_sentence = (
        "Active trader in U.S. and regional equity markets since 2018."
    )

    def confirmed_experience(
        *,
        title: str,
        source_handle: str,
        date_range: str,
        organization: str | None,
        responsibilities: list[str],
        source_section: str = "Professional Experience",
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid4(),
            category=FactCategory.EXPERIENCE,
            label=title,
            detail=None,
            structured_value={
                "schema_version": "resume_record.v1",
                "record_type": "experience",
                "source_handles": [source_handle],
                "source_section": source_section,
                "title": title,
                "organization": organization,
                "date_range": date_range,
                "responsibilities": responsibilities,
            },
            source_excerpt=f"{source_section}\n{date_range}\n{title}",
            verification_status=VerificationStatus.CONFIRMED,
        )

    cost_control_responsibilities = [
        "Performed monthly variance analysis, cost control, and internal financial reviews",
        "Supported audit processes, compliance checks, and management reporting",
    ]
    trainee_responsibilities = [
        "Supported month-end and year-end financial closing, reconciliations, and journal posting",
        "Prepared reports on financial performance, liquidity, and variance analysis",
    ]
    instructor_responsibilities = [
        training_sentence.rstrip("."),
        training_program_sentence.rstrip("."),
        guest_lecturer_sentence.rstrip("."),
    ]
    trading_responsibilities = [
        us_trading_sentence.rstrip("."),
        "Built trading strategies validated using 4,000+ backtesting samples",
    ]
    # The intake response arrived in the wrong chronology. Segment handles still encode the
    # candidate's real top-to-bottom source order: Cost (4), Trainee (5), Instructor (6),
    # Trading (7).
    facts = [
        confirmed_experience(
            title="Financial Markets Instructor",
            source_handle="segment_6",
            date_range="2022 - 2025",
            organization="MarketLearn",
            responsibilities=instructor_responsibilities,
        ),
        confirmed_experience(
            title="Finance Trainee",
            source_handle="segment_5",
            date_range="2024/01 - 2024/08",
            organization="Meridian Petrochemical",
            responsibilities=trainee_responsibilities,
        ),
        confirmed_experience(
            title="Cost Control & Finance Analyst",
            source_handle="segment_4",
            date_range="2025 - Present",
            organization="Northstar Consumer Brands",
            responsibilities=cost_control_responsibilities,
        ),
        confirmed_experience(
            title="Investment & Trading Professional",
            source_handle="segment_7",
            date_range="2018 - Present",
            organization=None,
            responsibilities=trading_responsibilities,
            source_section="Investment & Trading Experience",
        ),
    ]
    resume_evidence = build_resume_evidence(facts)
    assert [item.source_handles for item in resume_evidence] == [
        ("segment_6",),
        ("segment_5",),
        ("segment_4",),
        ("segment_7",),
    ]
    assert [
        item.label
        for item in sorted(
            resume_evidence,
            key=lambda item: int(item.source_handles[0].removeprefix("segment_")),
        )
    ] == [
        "Cost Control & Finance Analyst",
        "Finance Trainee",
        "Financial Markets Instructor",
        "Investment & Trading Professional",
    ]
    handles = {item.label: item.handle for item in resume_evidence}

    def provider_item(
        *,
        item_id: str,
        title: str,
        organization: str | None,
        date_range: str,
        bullets: list[str],
    ) -> dict[str, object]:
        return {
            "id": item_id,
            "title": title,
            "organization": organization,
            "date_range": date_range,
            "location": None,
            "bullets": bullets,
            "evidence_handles": [handles[title]],
        }

    provider = CapturingResumeWriter(
        {
            "headline": "Instructor",
            "professional_summary": (
                f"{training_sentence} {training_program_sentence} "
                f"{guest_lecturer_sentence} {us_trading_sentence}"
            ),
            "summary_evidence_handles": [
                handles["Financial Markets Instructor"],
                handles["Investment & Trading Professional"],
            ],
            "sections": [
                {
                    "key": "trading_experience",
                    "title": "Investment & Trading Experience",
                    "items": [
                        provider_item(
                            item_id="investment_trading_professional",
                            title="Investment & Trading Professional",
                            organization=None,
                            date_range="2018 - Present",
                            bullets=trading_responsibilities,
                        )
                    ],
                },
                {
                    "key": "experience",
                    "title": "Professional Experience",
                    # The provider reverses the source chronology. Completion owns final order.
                    "items": [
                        provider_item(
                            item_id="financial_markets_instructor",
                            title="Financial Markets Instructor",
                            organization="MarketLearn",
                            date_range="2022 - 2025",
                            bullets=instructor_responsibilities,
                        ),
                        provider_item(
                            item_id="finance_trainee",
                            title="Finance Trainee",
                            organization="Meridian Petrochemical",
                            date_range="2024/01 - 2024/08",
                            bullets=trainee_responsibilities,
                        ),
                        provider_item(
                            item_id="cost_control_finance_analyst",
                            title="Cost Control & Finance Analyst",
                            organization="Northstar Consumer Brands",
                            date_range="2025 - Present",
                            bullets=cost_control_responsibilities,
                        ),
                    ],
                },
            ],
        }
    )

    draft = await provider.generate_draft(
        language=PreferredLanguage.EN,
        target_role=None,
        evidence=resume_evidence,
        answers=[],
    )
    professional_section = next(
        section for section in draft.sections if section.key == "experience"
    )
    expected_titles = [
        "Cost Control & Finance Analyst",
        "Finance Trainee",
        "Financial Markets Instructor",
    ]
    failures: list[str] = []
    actual_titles = [item.title for item in professional_section.items]
    if actual_titles != expected_titles:
        failures.append(
            f"draft professional order was {actual_titles}, expected {expected_titles}"
        )
    expected_headline = (
        "Cost Control & Finance Analyst | Investment & Trading Professional"
    )
    if draft.headline != expected_headline:
        failures.append(
            f"draft headline was {draft.headline!r}, expected {expected_headline!r}"
        )
    summary_units = resume_writer_module._claim_units(draft.professional_summary)
    normalized_units = [" ".join(unit.casefold().split()) for unit in summary_units]
    if len(normalized_units) != len(set(normalized_units)):
        failures.append(f"draft summary repeated a claim: {summary_units}")
    expected_summary_sentences = [
        f"{cost_control_responsibilities[0]}.",
        f"{trainee_responsibilities[0]}.",
        us_trading_sentence,
    ]
    for sentence in expected_summary_sentences:
        if sentence not in draft.professional_summary:
            failures.append(f"draft summary omitted source-priority claim {sentence!r}")
    expected_summary_handles = [
        handles["Cost Control & Finance Analyst"],
        handles["Finance Trainee"],
        handles["Investment & Trading Professional"],
    ]
    if draft.summary_evidence_handles != expected_summary_handles:
        failures.append(
            "draft summary handles were not limited to Cost, Trainee, and Trading: "
            f"{draft.summary_evidence_handles}"
        )
    instructor_handle = handles["Financial Markets Instructor"]
    instructor_summary_sentences = [
        training_sentence,
        training_program_sentence,
        guest_lecturer_sentence,
    ]
    if instructor_handle in draft.summary_evidence_handles or any(
        sentence in draft.professional_summary
        for sentence in instructor_summary_sentences
    ):
        failures.append("draft summary remained centered on the Instructor record")
    try:
        validate_claim_grounding(
            draft.professional_summary,
            draft.summary_evidence_handles,
            resume_evidence,
        )
    except ResumeWriterError as exc:
        failures.append(f"draft summary was not grounded: {exc}")

    preview = render_resume_pdf(
        profile_name="Synthetic Candidate",
        city=None,
        language=PreferredLanguage.EN,
        draft=draft,
        contact=ResumeExportContact(),
    )
    preview_text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in PdfReader(BytesIO(preview)).pages
    )
    experience_position = preview_text.find("Professional Experience")
    professional_positions = [
        preview_text.find(title, max(0, experience_position)) for title in expected_titles
    ]
    if (
        experience_position < 0
        or -1 in professional_positions
        or professional_positions != sorted(professional_positions)
    ):
        failures.append(
            "PDF professional order was not Cost Control, Trainee, Instructor: "
            f"{professional_positions}"
        )
    summary_preview = preview_text[: max(0, experience_position)]
    if expected_headline not in summary_preview:
        failures.append("PDF header did not contain the completed finance/trading headline")
    for sentence in expected_summary_sentences:
        if sentence not in summary_preview:
            failures.append(f"PDF summary omitted source-priority claim {sentence!r}")
    if any(sentence in summary_preview for sentence in instructor_summary_sentences):
        failures.append("PDF summary remained centered on the Instructor record")

    assert not failures, "\n".join(failures)


def test_metadata_duplicates_are_removed_from_compact_resume_sections() -> None:
    assert resume_writer_module._remove_redundant_metadata_bullets(
        "language",
        title="Arabic",
        organization="Native/Bilingual",
        date_range=None,
        location=None,
        bullets=["Native / Bilingual"],
    ) == []
    assert resume_writer_module._remove_redundant_metadata_bullets(
        "certification",
        title="ERP Implementation Experience (Internship-based)",
        organization="Internship-based",
        date_range=None,
        location=None,
        bullets=["Internship-based"],
    ) == []


def test_claim_units_do_not_split_an_initialism_mid_sentence() -> None:
    summary = (
        "Active trader in U.S. and regional equity markets since 2018. "
        "Trained students in risk management."
    )

    assert resume_writer_module._claim_units(summary) == [
        "Active trader in U.S. and regional equity markets since 2018.",
        "Trained students in risk management.",
    ]


def test_claim_grounding_allows_professional_prose_but_pins_entities_numbers_and_dates() -> None:
    validate_claim_grounding(
        "Produced clear weekly inventory reports using Python.",
        ["fact_1"],
        evidence(),
    )

    with pytest.raises(ResumeWriterError, match="numbers absent from evidence"):
        validate_claim_grounding(
            "Produced 12 weekly inventory reports using Python.",
            ["fact_1"],
            evidence(),
        )
    with pytest.raises(ResumeWriterError, match="named entity absent from evidence"):
        validate_claim_grounding(
            "Google received inventory reports produced with Python.",
            ["fact_1"],
            evidence(),
        )


def test_claim_grounding_rejects_new_semantic_substance_but_allows_close_rewording() -> None:
    excel_evidence = (
        ResumeEvidence(
            handle="fact_excel",
            category="skill",
            label="Excel",
            detail="Used Excel",
            verification_status="confirmed",
        ),
    )

    validate_claim_grounding(
        "Applied Excel professionally.",
        ["fact_excel"],
        excel_evidence,
    )
    validate_claim_grounding(
        "وظفت Excel بصورة مهنية.",
        ["fact_excel"],
        excel_evidence,
    )
    with pytest.raises(ResumeWriterError, match="unsupported semantic claims"):
        validate_claim_grounding(
            "Prepared executive reports using Excel.",
            ["fact_excel"],
            excel_evidence,
        )
    with pytest.raises(ResumeWriterError, match="unsupported semantic claims"):
        validate_claim_grounding(
            "أعددت تقارير تنفيذية باستخدام Excel.",
            ["fact_excel"],
            excel_evidence,
        )

    validate_claim_grounding(
        "Produced clear weekly inventory reporting using Python.",
        ["fact_1"],
        evidence(),
    )


def test_claim_grounding_accepts_direct_arabic_translation_of_english_evidence() -> None:
    finance_evidence = (
        ResumeEvidence(
            handle="fact_finance",
            category="experience",
            label="Finance and investment professional with 7+ years of equity trading experience",
            detail="Strategy development and risk management",
            verification_status="confirmed",
        ),
    )

    validate_claim_grounding(
        (
            "مهني في المالية والاستثمار مع خبرة 7+ سنوات في تداول الأسهم "
            "وتطوير الاستراتيجيات وإدارة المخاطر."
        ),
        ["fact_finance"],
        finance_evidence,
    )
    validate_claim_grounding(
        "محترف في سوق الأسهم.",
        ["fact_finance"],
        finance_evidence,
    )
    validate_claim_grounding(
        "محترف مالي، بخبرة تزيد عن 7 سنوات في تداول، وتطوير الاستراتيجيات.",
        ["fact_finance"],
        finance_evidence,
    )
    with pytest.raises(ResumeWriterError, match="open-ended numeric qualifier"):
        validate_claim_grounding(
            "محترف مالي لديه 7 سنوات من الخبرة.",
            ["fact_finance"],
            finance_evidence,
        )

    exact_years_evidence = (
        ResumeEvidence(
            handle="fact_exact_years",
            category="experience",
            label="Finance professional with 7 years of experience",
            detail=None,
            verification_status="confirmed",
        ),
    )
    with pytest.raises(ResumeWriterError, match="unsupported semantic claims"):
        validate_claim_grounding(
            "محترف مالي بخبرة تزيد عن 7 سنوات.",
            ["fact_exact_years"],
            exact_years_evidence,
        )

    with pytest.raises(ResumeWriterError, match="unsupported semantic claims"):
        validate_claim_grounding(
            "أعددت تقارير تنفيذية شهرية للإدارة باستخدام خبرتي في المالية.",
            ["fact_finance"],
            finance_evidence,
        )

    educator_evidence = (
        ResumeEvidence(
            handle="fact_educator",
            category="experience",
            label="Trading educator with 3,000+ students trained",
            detail=None,
            verification_status="confirmed",
        ),
    )
    validate_claim_grounding(
        "مدرب تداول درّب 3,000+ من المتداولين.",
        ["fact_educator"],
        educator_evidence,
    )


def test_claim_grounding_accepts_direct_english_translation_of_arabic_evidence() -> None:
    arabic_evidence = (
        ResumeEvidence(
            handle="fact_sales",
            category="project",
            label="حللت بيانات المبيعات باستخدام Excel",
            detail="أنشأت لوحة معلومات للمبيعات",
            verification_status="confirmed",
        ),
    )

    validate_claim_grounding(
        "Analyzed sales data using Excel.",
        ["fact_sales"],
        arabic_evidence,
    )

    english_evidence = (
        ResumeEvidence(
            handle="fact_sales_en",
            category="project",
            label="Analyzed sales data using Excel",
            detail=None,
            verification_status="confirmed",
        ),
    )
    validate_claim_grounding(
        "حللت بيانات المبيعات باستخدام إكسل.",
        ["fact_sales_en"],
        english_evidence,
    )

    erp_evidence = (
        ResumeEvidence(
            handle="fact_erp",
            category="experience",
            label="ERP implementation experience",
            detail=None,
            verification_status="confirmed",
        ),
    )
    validate_claim_grounding(
        "خبرة في تنفيذ أنظمة ERP.",
        ["fact_erp"],
        erp_evidence,
    )

    certification_evidence = (
        ResumeEvidence(
            handle="fact_cme",
            category="certification",
            label="CME-4 Certification (Both CME-4A & CME-4B)",
            detail=None,
            verification_status="confirmed",
        ),
    )
    validate_claim_grounding(
        "شهادة CME.",
        ["fact_cme"],
        certification_evidence,
    )


def test_claim_grounding_rejects_unsupported_qualifier_and_cross_fact_composition() -> None:
    separate_evidence = (
        ResumeEvidence(
            handle="fact_python",
            category="skill",
            label="Used Python in coursework",
            detail=None,
            verification_status="confirmed",
        ),
        ResumeEvidence(
            handle="fact_dashboard",
            category="project",
            label="Created a sales dashboard in Power BI",
            detail=None,
            verification_status="confirmed",
        ),
        ResumeEvidence(
            handle="fact_reports",
            category="experience",
            label="Prepared weekly Excel reports",
            detail=None,
            verification_status="confirmed",
        ),
    )

    with pytest.raises(ResumeWriterError, match="unsupported semantic claims"):
        validate_claim_grounding(
            "Prepared weekly financial Excel reports.",
            ["fact_reports"],
            separate_evidence,
        )
    with pytest.raises(ResumeWriterError, match="unsupported semantic claims"):
        validate_claim_grounding(
            "Created a sales dashboard using Python.",
            ["fact_python", "fact_dashboard"],
            separate_evidence,
        )


@pytest.mark.parametrize(
    ("claim", "support"),
    [
        ("Managed payroll", "Did not manage payroll"),
        ("Used Python", "No experience with Python"),
    ],
)
def test_claim_grounding_preserves_negation(claim: str, support: str) -> None:
    negative_evidence = (
        ResumeEvidence(
            handle="fact_negative",
            category="experience",
            label=support,
            detail=None,
            verification_status="confirmed",
        ),
    )

    with pytest.raises(ResumeWriterError, match="unsupported semantic claims"):
        validate_claim_grounding(claim, ["fact_negative"], negative_evidence)


def test_generated_draft_removes_unsupported_expert_word_without_changing_claims() -> None:
    finance_evidence = (
        ResumeEvidence(
            handle="fact_finance",
            category="experience",
            label="Finance professional with equity trading experience",
            detail="Strategy development and risk management",
            verification_status="confirmed",
        ),
    )
    generated = _GeneratedDraft.model_validate(
        {
            "headline": "أخصائي خبير في المالية وتداول الأسهم",
            "professional_summary": "أخصائي خبير مالي لديه خبرة في تداول الأسهم وإدارة المخاطر.",
            "summary_evidence_handles": ["fact_finance"],
            "sections": [
                {
                    "key": "experience",
                    "title": "الخبرة المهنية",
                    "items": [
                        {
                            "id": "finance_experience",
                        "title": "أخصائي خبير مالي",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [
                                "اكتسبت خبرة في تداول الأسهم الآلي وإدارة المخاطر.",
                                "طورت نماذج التداول.",
                            ],
                            "evidence_handles": ["fact_finance"],
                        }
                    ],
                }
            ],
        }
    )

    sanitized = _sanitize_generated_draft(generated, finance_evidence)

    assert "خبير" not in sanitized.headline
    assert "أخصائي" not in sanitized.headline
    assert "مهني" in sanitized.headline
    assert "خبير" not in sanitized.professional_summary
    assert "أخصائي" not in sanitized.professional_summary
    assert sanitized.professional_summary.startswith("مهني مالي")
    assert "خبير" not in sanitized.sections[0].items[0].title
    assert "أخصائي" not in sanitized.sections[0].items[0].title
    assert "الآلي" not in sanitized.sections[0].items[0].bullets[0]
    assert sanitized.sections[0].items[0].bullets[1] == "طورت استراتيجيات التداول."
    _validated_draft(sanitized, finance_evidence)


def test_generated_draft_sanitizer_fails_safely_when_required_text_becomes_empty() -> None:
    generated = generated_draft()
    generated.headline = "خبير"

    with pytest.raises(ResumeWriterError, match="unsupported resume wording"):
        _sanitize_generated_draft(generated, evidence())


def test_generated_draft_sanitizer_omits_unsupported_fragments() -> None:
    generated = generated_draft(
        organization="Google",
        location="London",
        bullets=[
            "Built inventory reports using Python and Power BI.",
            "Increased revenue by 50%.",
        ],
    )
    generated.professional_summary += " Managed payroll for Google."

    sanitized = _sanitize_generated_draft(generated, evidence(), "Data Analyst")

    item = sanitized.sections[0].items[0]
    assert "payroll" not in sanitized.professional_summary
    assert "Google" not in sanitized.professional_summary
    assert item.organization is None
    assert item.location is None
    assert item.bullets == ["Built inventory reports using Python and Power BI."]
    _validated_draft(sanitized, evidence(), "Data Analyst")


def test_sanitizer_drops_wrong_section_items_and_completion_restores_every_fact() -> None:
    responsibility = "Prepared monthly financial reports for cost control"
    supports = (
        ResumeEvidence(
            handle="wrong_section_experience",
            category="experience",
            label="Finance Analyst",
            detail=responsibility,
            verification_status="confirmed",
            structured_value={"responsibilities": [responsibility]},
        ),
        ResumeEvidence(
            handle="wrong_section_certification",
            category="certification",
            label="CFA Level I",
            detail="CFA Institute, 2025",
            verification_status="confirmed",
            structured_value={"issuer": "CFA Institute", "date_range": "2025"},
        ),
        ResumeEvidence(
            handle="correct_skill_anchor",
            category="skill",
            label="Excel",
            detail="Used Excel for financial reporting",
            verification_status="confirmed",
        ),
    )
    generated = _GeneratedDraft.model_validate(
        {
            "headline": "Finance Analyst",
            "professional_summary": f"{responsibility}.",
            "summary_evidence_handles": ["wrong_section_experience"],
            "sections": [
                {
                    "key": "certification",
                    "title": "Certifications",
                    "items": [
                        {
                            "id": "experience_in_certifications",
                            "title": "Finance Analyst",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [responsibility],
                            "evidence_handles": ["wrong_section_experience"],
                        }
                    ],
                },
                {
                    "key": "experience",
                    "title": "Professional Experience",
                    "items": [
                        {
                            "id": "certification_in_experience",
                            "title": "CFA Level I",
                            "organization": "CFA Institute",
                            "date_range": "2025",
                            "location": None,
                            "bullets": ["CFA Institute, 2025"],
                            "evidence_handles": ["wrong_section_certification"],
                        }
                    ],
                },
                {
                    "key": "skill",
                    "title": "Skills",
                    "items": [
                        {
                            "id": "excel",
                            "title": "Excel",
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": ["correct_skill_anchor"],
                        }
                    ],
                },
            ],
        }
    )

    sanitized = _sanitize_generated_draft(generated, supports)
    assert [section.key for section in sanitized.sections] == ["skill"]

    completed = resume_writer_module._complete_draft_from_evidence(
        _validated_draft(sanitized, supports),
        supports,
        PreferredLanguage.EN,
    )

    restored = {
        item.evidence_handles[0]: section.key
        for section in completed.sections
        for item in section.items
    }
    assert restored == {
        "wrong_section_experience": "experience",
        "wrong_section_certification": "certification",
        "correct_skill_anchor": "skill",
    }


def test_sanitizer_restricts_mixed_handles_before_marking_facts_covered() -> None:
    skill = ResumeEvidence(
        handle="financial_analysis_skill",
        category="skill",
        label="Financial Analysis",
        detail="Applied financial analysis in university coursework",
        verification_status="confirmed",
    )
    education = ResumeEvidence(
        handle="finance_education",
        category="education",
        label="Bachelor of Science in Finance",
        detail="Harbor University, 2025",
        verification_status="confirmed",
        structured_value={
            "institution": "Harbor University",
            "date_range": "2025",
        },
    )
    supports = (skill, education)
    generated = _GeneratedDraft.model_validate(
        {
            "headline": skill.label,
            "professional_summary": f"{skill.detail}.",
            "summary_evidence_handles": [skill.handle],
            "sections": [
                {
                    "key": "skill",
                    "title": "Skills",
                    "items": [
                        {
                            "id": "education_disguised_as_skill",
                            "title": education.label,
                            "organization": "Harbor University",
                            "date_range": "2025",
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [skill.handle, education.handle],
                        },
                        {
                            "id": "financial_analysis",
                            "title": skill.label,
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [skill.handle],
                        },
                    ],
                }
            ],
        }
    )

    sanitized = _sanitize_generated_draft(generated, supports)
    assert [item.id for item in sanitized.sections[0].items] == ["financial_analysis"]
    assert sanitized.sections[0].items[0].evidence_handles == [skill.handle]

    completed = resume_writer_module._complete_draft_from_evidence(
        _validated_draft(sanitized, supports),
        supports,
        PreferredLanguage.EN,
    )

    assert [section.key for section in completed.sections] == ["education", "skill"]
    completed_items = {
        item.evidence_handles[0]: (section.key, item.title)
        for section in completed.sections
        for item in section.items
    }
    assert completed_items == {
        education.handle: ("education", education.label),
        skill.handle: ("skill", skill.label),
    }


def test_achievement_claim_does_not_cover_its_source_experience_record() -> None:
    responsibility = "Prepared monthly financial reports"
    support = ResumeEvidence(
        handle="experience_supporting_achievement",
        category="experience",
        label="Finance Analyst",
        detail=responsibility,
        verification_status="confirmed",
        structured_value={
            "source_section": "Professional Experience",
            "responsibilities": [responsibility],
        },
    )
    generated = _GeneratedDraft.model_validate(
        {
            "headline": support.label,
            "professional_summary": f"{responsibility}.",
            "summary_evidence_handles": [support.handle],
            "sections": [
                {
                    "key": "achievement",
                    "title": "Achievements",
                    "items": [
                        {
                            "id": "monthly_reporting_achievement",
                            "title": responsibility,
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [support.handle],
                        }
                    ],
                }
            ],
        }
    )

    sanitized = _sanitize_generated_draft(generated, (support,))
    completed = resume_writer_module._complete_draft_from_evidence(
        _validated_draft(sanitized, (support,)),
        (support,),
        PreferredLanguage.EN,
    )

    assert [section.key for section in completed.sections] == [
        "experience",
        "achievement",
    ]
    experience = completed.sections[0].items[0]
    achievement = completed.sections[1].items[0]
    assert experience.title == support.label
    assert experience.evidence_handles == [support.handle]
    assert achievement.id == "monthly_reporting_achievement"
    assert achievement.evidence_handles == [support.handle]


def test_full_experience_record_is_not_duplicated_as_same_title_achievement() -> None:
    support = ResumeEvidence(
        handle="erp_implementation_experience",
        category="experience",
        label="ERP Implementation Experience",
        detail="ERP Implementation Experience (Internship-based)",
        verification_status="confirmed",
        structured_value={
            "source_section": "Certificates",
            "responsibilities": ["Internship-based"],
        },
    )
    generated = _GeneratedDraft.model_validate(
        {
            "headline": support.label,
            "professional_summary": "ERP Implementation Experience (Internship-based).",
            "summary_evidence_handles": [support.handle],
            "sections": [
                {
                    "key": "experience",
                    "title": "Professional Experience",
                    "items": [
                        {
                            "id": "erp_experience",
                            "title": support.label,
                            "organization": None,
                            "date_range": None,
                            "location": None,
                            "bullets": ["Internship-based"],
                            "evidence_handles": [support.handle],
                        }
                    ],
                },
                {
                    "key": "achievement",
                    "title": "Achievements",
                    "items": [
                        {
                            "id": "erp_achievement_duplicate",
                            "title": support.label,
                            "organization": "Internship-based",
                            "date_range": None,
                            "location": None,
                            "bullets": ["Internship-based"],
                            "evidence_handles": [support.handle],
                        }
                    ],
                },
            ],
        }
    )

    sanitized = _sanitize_generated_draft(generated, (support,))
    completed = resume_writer_module._complete_draft_from_evidence(
        _validated_draft(sanitized, (support,)),
        (support,),
        PreferredLanguage.EN,
    )

    assert [section.key for section in completed.sections] == ["experience"]
    represented = [
        item
        for section in completed.sections
        for item in section.items
        if support.handle in item.evidence_handles
    ]
    assert len(represented) == 1
    assert represented[0].title == support.label


def test_same_title_achievement_only_is_restored_once_in_canonical_section() -> None:
    support = ResumeEvidence(
        handle="erp_canonical_fallback",
        category="experience",
        label="ERP Implementation Experience",
        detail="ERP Implementation Experience (Internship-based)",
        verification_status="confirmed",
        structured_value={"responsibilities": ["Internship-based"]},
    )
    draft = ResumeDraftContent.model_validate(
        {
            "headline": support.label,
            "professional_summary": "ERP Implementation Experience (Internship-based).",
            "summary_evidence_handles": [support.handle],
            "sections": [
                {
                    "key": "achievement",
                    "title": "Achievements",
                    "items": [
                        {
                            "id": "erp_achievement_only",
                            "title": support.label,
                            "organization": "Internship-based",
                            "date_range": None,
                            "location": None,
                            "bullets": ["Internship-based"],
                            "evidence_handles": [support.handle],
                        }
                    ],
                }
            ],
        }
    )

    completed = resume_writer_module._complete_draft_from_evidence(
        draft,
        (support,),
        PreferredLanguage.EN,
    )

    assert [section.key for section in completed.sections] == ["experience"]
    assert completed.sections[0].items[0].title == support.label
    assert completed.sections[0].items[0].evidence_handles == [support.handle]


def test_compact_sections_follow_shared_source_segment_record_order() -> None:
    certification_order = [
        "CME-4 Certification",
        "Advanced Microsoft Excel",
        "CME-1 Certification",
    ]
    skill_order = [
        "Trading Strategy Development",
        "Backtesting & Optimization",
        "Risk & Money Management",
        "Portfolio Construction",
        "Market Analysis",
        "Options Strategies (Covered Calls)",
    ]
    language_order = ["English", "Arabic"]
    certification_excerpt = "Certificates:\n" + "\n".join(certification_order)
    skill_excerpt = "Financial Skills:\n" + ", ".join(skill_order)
    language_excerpt = "Languages:\n" + " ".join(language_order)

    def compact_support(
        *,
        category: str,
        label: str,
        handle: str,
        segment: str,
        source_excerpt: str,
        detail: str | None = None,
    ) -> ResumeEvidence:
        structured_value: dict[str, object] = {"source_handles": [segment]}
        if category == "language":
            structured_value["proficiency"] = (
                "Fluent" if label == "English" else "Native/Bilingual"
            )
        return ResumeEvidence(
            handle=handle,
            category=category,
            label=label,
            detail=detail,
            verification_status="confirmed",
            structured_value=structured_value,
            source_excerpt=source_excerpt,
            source_handles=(segment,),
            source_group="uploaded_resume",
        )

    certifications = {
        label: compact_support(
            category="certification",
            label=label,
            handle=f"cert_{index}",
            segment="segment_8",
            source_excerpt=certification_excerpt,
        )
        for index, label in enumerate(certification_order)
    }
    skills = {
        label: compact_support(
            category="skill",
            label=label,
            handle=f"skill_{index}",
            segment="segment_9",
            source_excerpt=skill_excerpt,
            detail=(
                "Trading Strategy Development supports disciplined execution"
                if label == "Trading Strategy Development"
                else None
            ),
        )
        for index, label in enumerate(skill_order)
    }
    languages = {
        label: compact_support(
            category="language",
            label=label,
            handle=f"language_{index}",
            segment="segment_12",
            source_excerpt=language_excerpt,
        )
        for index, label in enumerate(language_order)
    }
    provider_certification_order = [
        "CME-1 Certification",
        "Advanced Microsoft Excel",
        "CME-4 Certification",
    ]
    provider_skill_order = [
        "Market Analysis",
        "Risk & Money Management",
        "Portfolio Construction",
        "Options Strategies (Covered Calls)",
        "Trading Strategy Development",
        "Backtesting & Optimization",
    ]
    provider_language_order = ["Arabic", "English"]
    supports = tuple(
        [certifications[label] for label in provider_certification_order]
        + [skills[label] for label in provider_skill_order]
        + [languages[label] for label in provider_language_order]
    )

    def provider_items(
        ordered_labels: list[str],
        support_by_label: dict[str, ResumeEvidence],
        prefix: str,
    ) -> list[dict[str, object]]:
        return [
            {
                "id": f"{prefix}_{index}",
                "title": label,
                "organization": (
                    support_by_label[label].structured_value.get("proficiency")
                    if prefix == "language"
                    else None
                ),
                "date_range": None,
                "location": None,
                "bullets": [],
                "evidence_handles": [support_by_label[label].handle],
            }
            for index, label in enumerate(ordered_labels)
        ]

    generated = _GeneratedDraft.model_validate(
        {
            "headline": "Trading Strategy Development",
            "professional_summary": (
                "Trading Strategy Development supports disciplined execution."
            ),
            "summary_evidence_handles": [
                skills["Trading Strategy Development"].handle
            ],
            "sections": [
                {
                    "key": "certification",
                    "title": "Certifications",
                    "items": provider_items(
                        provider_certification_order,
                        certifications,
                        "certification",
                    ),
                },
                {
                    "key": "skill",
                    "title": "Skills",
                    "items": provider_items(
                        provider_skill_order,
                        skills,
                        "skill",
                    ),
                },
                {
                    "key": "language",
                    "title": "Languages",
                    "items": provider_items(
                        provider_language_order,
                        languages,
                        "language",
                    ),
                },
            ],
        }
    )
    completed = resume_writer_module._complete_draft_from_evidence(
        _validated_draft(_sanitize_generated_draft(generated, supports), supports),
        supports,
        PreferredLanguage.EN,
    )
    sections = {section.key: section for section in completed.sections}

    assert [item.title for item in sections["certification"].items] == (
        certification_order
    )
    assert [item.title for item in sections["skill"].items] == skill_order
    assert [item.title for item in sections["language"].items] == language_order


def test_source_order_uses_explicit_segment_record_suffix_before_input_order() -> None:
    supports = tuple(
        ResumeEvidence(
            handle=f"skill_{record_index}",
            category="skill",
            label=f"Skill {record_index}",
            detail=None,
            verification_status="confirmed",
            source_handles=(f"segment_9__{record_index}",),
            source_group="uploaded_resume",
        )
        for record_index in (3, 1, 2)
    )

    ordered = resume_writer_module._evidence_in_source_order(supports)

    assert [item.label for item in ordered] == ["Skill 1", "Skill 2", "Skill 3"]


def test_source_order_breaks_shared_segment_suffix_ties_by_excerpt_position() -> None:
    source_excerpt = "Skills: Skill 1, Skill 2, Skill 3"
    supports = tuple(
        ResumeEvidence(
            handle=f"shared_skill_{record_index}",
            category="skill",
            label=f"Skill {record_index}",
            detail=None,
            verification_status="confirmed",
            source_excerpt=source_excerpt,
            source_handles=("segment_9__1",),
            source_group="uploaded_resume",
        )
        for record_index in (3, 1, 2)
    )

    ordered = resume_writer_module._evidence_in_source_order(supports)

    assert [item.label for item in ordered] == ["Skill 1", "Skill 2", "Skill 3"]


def test_verified_overlay_replaces_overlapping_values_by_exact_atom_index() -> None:
    short_source = "\u0623\u0643\u062a\u0628 \u0627\u0644\u0634\u0639\u0631"
    long_source = (
        "\u0623\u0643\u062a\u0628 \u0627\u0644\u0634\u0639\u0631 "
        "\u0623\u062b\u0646\u0627\u0621 \u0627\u0644\u0639\u0632\u0641 "
        "\u0639\u0644\u0649 \u0627\u0644\u0639\u0648\u062f"
    )
    short_translation = "Write poetry"
    long_translation = "Write poetry while playing the oud"
    support = ResumeEvidence(
        handle="overlapping_supplemental_values",
        category="project",
        label="Creative Work",
        detail=f"{short_source}. {long_source}.",
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "responsibility_or_scope": {
                    "value": [short_source, long_source],
                }
            },
            "supplemental_addenda": [
                {
                    "text": f"{short_source}\n{long_source}",
                    "requested_fields": ["responsibility_or_scope"],
                }
            ],
        },
    )
    required = [
        {
            "handle": support.handle,
            "field": "responsibility_or_scope",
            "value": short_source,
            "translated_value": short_translation,
        },
        {
            "handle": support.handle,
            "field": "responsibility_or_scope",
            "value": long_source,
            "translated_value": long_translation,
        },
    ]

    immediate = resume_writer_module._verified_supplemental_evidence_overlay(
        (support,),
        required,
    )[0]
    proofs = [
        resume_writer_module.ResumeVerifiedSupplementalTranslation(
            handle=support.handle,
            field="responsibility_or_scope",
            value_index=value_index,
            source_hash=resume_writer_module.sha256(source.encode("utf-8")).hexdigest(),
            translated_value=translated,
            pair_id=resume_writer_module._supplemental_translation_pair_id(
                handle=support.handle,
                field_name="responsibility_or_scope",
                value_index=value_index,
                source_value=source,
                translated_value=translated,
            ),
            verdict="pass",
        )
        for value_index, (source, translated) in enumerate(
            (
                (short_source, short_translation),
                (long_source, long_translation),
            )
        )
    ]
    persisted = resume_writer_module.verified_supplemental_evidence_overlay(
        (support,),
        language=PreferredLanguage.EN,
        translations=proofs,
    )[0]

    for overlaid in (immediate, persisted):
        values = overlaid.structured_value["supplemental_details"][
            "responsibility_or_scope"
        ]["value"]
        assert values == [short_translation, long_translation]
        assert overlaid.detail == f"{short_translation}. {long_translation}."
        addendum = overlaid.structured_value["supplemental_addenda"][0]["text"]
        assert addendum == f"{short_translation}\n{long_translation}"
        assert short_source not in overlaid.text
        assert long_source not in overlaid.text


def test_sanitizer_repairs_summary_attribution_before_balanced_completion() -> None:
    cost_responsibility = (
        "Performed monthly variance analysis at Northstar Consumer Brands"
    )
    trainee_responsibility = "Reconciled accounts at Meridian Petrochemical"
    trading_responsibility = (
        "Active trader in U.S. and regional equity markets since 2018"
    )
    cost = ResumeEvidence(
        handle="cost_control_summary",
        category="experience",
        label="Finance Analyst",
        detail=cost_responsibility,
        verification_status="confirmed",
        structured_value={
            "source_section": "Professional Experience",
            "organization": "Northstar Consumer Brands",
            "responsibilities": [cost_responsibility],
        },
        source_handles=("segment_4",),
    )
    trainee = ResumeEvidence(
        handle="trainee_summary",
        category="experience",
        label="Finance Trainee",
        detail=trainee_responsibility,
        verification_status="confirmed",
        structured_value={
            "source_section": "Professional Experience",
            "organization": "Meridian Petrochemical",
            "responsibilities": [trainee_responsibility],
        },
        source_handles=("segment_5",),
    )
    trading = ResumeEvidence(
        handle="trading_summary",
        category="experience",
        label="Investment & Trading Professional",
        detail=trading_responsibility,
        verification_status="confirmed",
        structured_value={
            "source_section": "Investment & Trading Experience",
            "responsibilities": [trading_responsibility],
        },
        source_handles=("segment_7",),
    )
    education = ResumeEvidence(
        handle="education_summary",
        category="education",
        label="Bachelor of Science in Finance",
        detail="Harbor University, 2025",
        verification_status="confirmed",
        structured_value={
            "institution": "Harbor University",
            "date_range": "2025",
        },
        source_handles=("segment_1",),
    )
    supports = (education, cost, trainee, trading)
    combined_unsupported_unit = (
        f"{cost_responsibility} and {trainee_responsibility.casefold()}."
    )
    grounded_education_unit = (
        "Bachelor of Science in Finance from Harbor University."
    )
    generated = _GeneratedDraft.model_validate(
        {
            "headline": cost.label,
            "professional_summary": (
                f"{combined_unsupported_unit} {grounded_education_unit}"
            ),
            "summary_evidence_handles": [
                cost.handle,
                trainee.handle,
                trading.handle,
                education.handle,
            ],
            "sections": [
                {
                    "key": "education",
                    "title": "Education",
                    "items": [
                        {
                            "id": "finance_degree",
                            "title": education.label,
                            "organization": "Harbor University",
                            "date_range": "2025",
                            "location": None,
                            "bullets": [],
                            "evidence_handles": [education.handle],
                        }
                    ],
                }
            ],
        }
    )

    sanitized = _sanitize_generated_draft(generated, supports)
    assert sanitized.professional_summary == grounded_education_unit
    assert sanitized.summary_evidence_handles == [education.handle]

    completed = resume_writer_module._complete_draft_from_evidence(
        _validated_draft(sanitized, supports),
        supports,
        PreferredLanguage.EN,
    )

    assert completed.summary_evidence_handles == [
        cost.handle,
        trainee.handle,
        trading.handle,
    ]
    for responsibility in (
        cost_responsibility,
        trainee_responsibility,
        trading_responsibility,
    ):
        assert responsibility in completed.professional_summary


def test_generated_draft_sanitizer_separates_cross_fact_headline_roles() -> None:
    combined_evidence = (
        *evidence(),
        ResumeEvidence(
            handle="fact_educator",
            category="experience",
            label="Trading educator",
            detail="Trained students",
            verification_status="confirmed",
        ),
    )
    generated = generated_draft()
    generated.headline = "Inventory reporting and Trading educator"

    sanitized = _sanitize_generated_draft(generated, combined_evidence, "Data Analyst")

    assert sanitized.headline == "Inventory reporting | Trading educator"
    _validated_draft(sanitized, combined_evidence, "Data Analyst")


@pytest.mark.asyncio
async def test_generate_draft_retries_invalid_structured_output_once() -> None:
    provider = CapturingResumeWriter(
        [
            ResumeWriterError("Resume writer returned invalid structured output"),
            generated_draft().model_dump(mode="python"),
        ]
    )

    draft = await provider.generate_draft(
        language=PreferredLanguage.EN,
        target_role="Data Analyst",
        evidence=evidence(),
        answers=[],
    )

    assert draft.headline == "Data Analyst"
    assert len(provider.calls) == 2
    assert "prior draft was rejected" in provider.calls[1]["system_instructions"].lower()


@pytest.mark.asyncio
async def test_generate_draft_exhaustion_raises_distinct_output_error_after_two_calls() -> None:
    provider = CapturingResumeWriter(
        [
            ResumeWriterError("Resume writer returned invalid structured output"),
            ResumeWriterError("Resume writer returned unsupported semantic claims"),
        ]
    )

    with pytest.raises(ResumeWriterOutputError) as captured:
        await provider.generate_draft(
            language=PreferredLanguage.EN,
            target_role="Data Analyst",
            evidence=evidence(),
            answers=[],
        )

    assert len(provider.calls) == 2
    assert isinstance(captured.value.__cause__, ResumeWriterError)
    assert not isinstance(captured.value.__cause__, ResumeWriterTransportError)


@pytest.mark.asyncio
async def test_generate_draft_does_not_retry_transport_failure() -> None:
    provider = CapturingResumeWriter(
        [
            ResumeWriterTransportError("provider request failed", transient=True),
            generated_draft().model_dump(mode="python"),
        ]
    )

    with pytest.raises(ResumeWriterTransportError) as captured:
        await provider.generate_draft(
            language=PreferredLanguage.EN,
            target_role="Data Analyst",
            evidence=evidence(),
            answers=[],
        )

    assert captured.value.transient is True
    assert len(provider.calls) == 1
    assert len(provider.responses) == 1


@pytest.mark.asyncio
async def test_adaptive_turn_returns_understanding_record_question_and_patch_in_one_call() -> None:
    response = {
        "understanding": {
            "summary": "أنشأت لوحة Inventory باستخدام Python وأعددت تقارير أسبوعية.",
            "confidence": "high",
            "evidence_handles": ["answer_turn_7"],
            "confirmation_question": "هل فهمت إجابتك بشكل صحيح؟",
        },
        "proposed_records": [
            {
                "record_type": "project",
                "source_handles": ["answer_turn_7"],
                "title": "لوحة Inventory",
                "responsibilities": ["أعددت تقارير أسبوعية"],
                "tools": ["Python"],
            }
        ],
        "next_question": {
            "id": "inventory_outcome",
            "category": "project",
            "question": "ما النتيجة الملموسة التي حققتها اللوحة؟",
            "why_it_matters": "توضح النتيجة قيمة مساهمتك في المشروع.",
            "placeholder": "اذكر النتيجة، أو تجاوز السؤال إن لم تكن معروفة.",
            "required": False,
        },
        "draft_patch": {
            "section_key": "project",
            "title": "Inventory dashboard",
            "bullet_candidates": ["Built weekly reports using Python."],
            "evidence_handles": ["answer_turn_7"],
        },
        "ready_to_generate": False,
    }
    provider = CapturingResumeWriter(response)
    question = ResumeQuestionRead(
        id="inventory_scope",
        category=FactCategory.PROJECT,
        question="What did you build and which tools did you use?",
        why_it_matters="It supplies a grounded project example.",
        placeholder="Project, contribution, and tools.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.EN,
        target_role="Data Analyst",
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question={
            **question.model_dump(mode="json"),
            "fields_requested": ["action", "tools"],
            "quick_replies": ["skip"],
        },
        answer="أنشأت لوحة Inventory باستخدام Python وأعددت تقارير أسبوعية.",
        answer_handle="answer_turn_7",
    )

    assert result.proposed_records[0].record_type == "project"
    assert result.next_question is not None
    assert result.next_question.id == "inventory_outcome"
    assert result.draft_patch is not None
    assert result.draft_patch.bullet_candidates == ["Built weekly reports using Python."]
    assert len(provider.calls) == 1
    assert provider.calls[0]["model_name"] == "interview-model"
    assert provider.calls[0]["schema_name"] == "adaptive_resume_interview_turn"
    assert provider.calls[0]["max_tokens"] == 1_000
    assert provider.calls[0]["payload"]["conversation_language"] == "ar"
    assert provider.calls[0]["payload"]["output_language"] == "en"
    assert provider.calls[0]["payload"]["section_order"] == list(RESUME_SECTION_ORDER)
    assert provider.calls[0]["payload"]["active_section"] == "project"
    assert provider.calls[0]["payload"]["allowed_next_question_categories"] == [
        "project",
        "achievement",
    ]
    instructions = provider.calls[0]["system_instructions"]
    assert "conversation_language" in instructions
    assert "output_language" in instructions


@pytest.mark.asyncio
async def test_adaptive_turn_safely_handles_an_arabic_answer_that_changes_topic() -> None:
    answer = "خلينا نبدأ بالجامعة، أنا متخرج من جامعة البترول وتخصصي مالية"
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": (
                    "The user likely earned a Bachelor of Science in Finance from "
                    "Petroleum Institute."
                ),
                "confidence": "medium",
                "evidence_handles": ["answer_education"],
                "confirmation_question": "Did I understand your education correctly?",
            },
            "proposed_records": [
                {
                    "record_type": "education",
                    "source_handles": ["answer_education"],
                    "title": "Bachelor of Science in Finance",
                    "institution": "Petroleum Institute",
                }
            ],
            "next_question": {
                "id": "experience_details",
                "category": "experience",
                "question": "What company did you work for?",
                "why_it_matters": "It completes the experience record.",
                "placeholder": "Company name.",
                "required": True,
            },
            "draft_patch": None,
            "ready_to_generate": False,
        }
    )
    question = ResumeQuestionRead(
        id="experience_story",
        category=FactCategory.EXPERIENCE,
        question="احكي لي عن تجربة عمل أو مشروع تفتخر به.",
        why_it_matters="نحتاج مثالًا مهنيًا واضحًا.",
        placeholder="التجربة، دورك، والأثر.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.EN,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_education",
    )

    assert result.understanding.summary == answer
    assert result.understanding.evidence_handles == ["answer_education"]
    assert result.proposed_records[0].record_type == "education"
    assert result.proposed_records[0].title == answer
    assert result.next_question is not None
    assert result.next_question.category is FactCategory.EXPERIENCE
    assert result.draft_patch is None


@pytest.mark.asyncio
async def test_adaptive_turn_does_not_store_a_negative_answer_as_resume_content() -> None:
    answer = "لا، ما عندي خبرة للحين"
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_no_experience"],
                "confirmation_question": "هل فهمت إجابتك بشكل صحيح؟",
            },
            "proposed_records": [
                {
                    "record_type": "experience",
                    "source_handles": ["answer_no_experience"],
                    "title": answer,
                }
            ],
            "next_question": {
                "id": "project_story",
                "category": "project",
                "question": "هل لديك مشروع جامعي أو شخصي تود إضافته؟",
                "why_it_matters": "يمكن للمشروع أن يثبت مهاراتك حتى دون خبرة وظيفية.",
                "placeholder": "اذكر المشروع أو تخطّ السؤال.",
                "required": False,
            },
            "draft_patch": {
                "section_key": "experience",
                "title": answer,
                "bullet_candidates": [answer],
                "evidence_handles": ["answer_no_experience"],
            },
            "ready_to_generate": False,
        }
    )
    question = ResumeQuestionRead(
        id="experience_story",
        category=FactCategory.EXPERIENCE,
        question="احكي لي عن خبرتك العملية.",
        why_it_matters="نحتاج مثالًا مهنيًا واضحًا.",
        placeholder="المسمى، الشركة، والمسؤوليات.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.AR,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_no_experience",
    )

    assert result.understanding.summary == answer
    assert result.proposed_records == []
    assert result.draft_patch is None
    assert result.next_question is not None
    assert result.next_question.category is FactCategory.CERTIFICATION


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["لا أملك خبرة حتى الآن", "ما اشتغلت للحين"])
async def test_adaptive_turn_recognizes_common_arabic_negative_answers(answer: str) -> None:
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_no_experience"],
                "confirmation_question": "هل هذا يلخص ما تقصده بدقة؟",
            },
            "proposed_records": [
                {
                    "record_type": "experience",
                    "source_handles": ["answer_no_experience"],
                    "title": answer,
                }
            ],
            "next_question": {
                "id": "project_story",
                "category": "project",
                "question": "هل لديك مشروع تود إضافته؟",
                "why_it_matters": "المشروع يقدم دليلًا عمليًا.",
                "placeholder": "اذكر المشروع أو تخطّ السؤال.",
                "required": False,
            },
            "draft_patch": None,
            "ready_to_generate": False,
        }
    )
    question = ResumeQuestionRead(
        id="experience_story",
        category=FactCategory.EXPERIENCE,
        question="احكي لي عن خبرتك العملية.",
        why_it_matters="نحتاج مثالًا مهنيًا واضحًا.",
        placeholder="المسمى، الشركة، والمسؤوليات.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.EN,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_no_experience",
    )

    assert result.proposed_records == []
    assert result.draft_patch is None


@pytest.mark.asyncio
async def test_adaptive_turn_keeps_positive_project_after_negative_experience_clause() -> None:
    answer = "ما عندي خبرة عمل في شركة لكن سويت مشروع بايثون"
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_mixed"],
                "confirmation_question": "هل هذا يلخص ما تقصده بدقة؟",
            },
            "proposed_records": [
                {
                    "record_type": "project",
                    "source_handles": ["answer_mixed"],
                    "title": "سويت مشروع بايثون",
                    "tools": ["بايثون"],
                }
            ],
            "next_question": {
                "id": "project_outcome",
                "category": "project",
                "question": "ما هدف المشروع وما النتيجة؟",
                "why_it_matters": "الهدف والنتيجة يوضحان قيمة المشروع.",
                "placeholder": "اذكر الهدف والنتيجة.",
                "required": False,
            },
            "draft_patch": None,
            "ready_to_generate": False,
        }
    )
    question = ResumeQuestionRead(
        id="experience_story",
        category=FactCategory.EXPERIENCE,
        question="احكي لي عن خبرتك العملية.",
        why_it_matters="نحتاج مثالًا مهنيًا واضحًا.",
        placeholder="المسمى، الشركة، والمسؤوليات.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.EN,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_mixed",
    )

    assert len(result.proposed_records) == 1
    assert result.proposed_records[0].record_type == "project"
    assert result.proposed_records[0].tools == ["بايثون"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "positive_clause", "record_type"),
    [
        (
            "ما عندي خبرة رسمية لكن كنت أساعد والدي في المتجر",
            "كنت أساعد والدي في المتجر",
            "experience",
        ),
        (
            "ما عندي خبرة لكن حللت المبيعات وأعددت تقريرًا",
            "حللت المبيعات وأعددت تقريرًا",
            "project",
        ),
    ],
)
async def test_adaptive_turn_keeps_substantive_positive_clause_without_keywords(
    answer: str,
    positive_clause: str,
    record_type: str,
) -> None:
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_mixed"],
                "confirmation_question": "هل هذا يلخص ما تقصده بدقة؟",
            },
            "proposed_records": [
                {
                    "record_type": record_type,
                    "source_handles": ["answer_mixed"],
                    "title": positive_clause,
                }
            ],
            "next_question": {
                "id": f"{record_type}_details",
                "category": record_type,
                "question": "ما دورك بالتحديد وما النتيجة؟",
                "why_it_matters": "التفاصيل توضح قيمة مساهمتك.",
                "placeholder": "اذكر دورك والنتيجة.",
                "required": False,
            },
            "draft_patch": None,
            "ready_to_generate": False,
        }
    )
    question = ResumeQuestionRead(
        id="experience_story",
        category=FactCategory.EXPERIENCE,
        question="احكي لي عن خبرتك العملية.",
        why_it_matters="نحتاج مثالًا مهنيًا واضحًا.",
        placeholder="المسمى، الشركة، والمسؤوليات.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.EN,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_mixed",
    )

    assert len(result.proposed_records) == 1
    assert result.proposed_records[0].record_type == record_type
    assert result.proposed_records[0].title == positive_clause


@pytest.mark.asyncio
async def test_adaptive_turn_does_not_store_a_request_to_move_to_the_next_question() -> None:
    answer = "ما عندي خبرة لكن خلينا ننتقل للسؤال التالي"
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_move_on"],
                "confirmation_question": "هل هذا يلخص ما تقصده بدقة؟",
            },
            "proposed_records": [],
            "next_question": None,
            "draft_patch": {
                "section_key": "experience",
                "title": answer,
                "bullet_candidates": [answer],
                "evidence_handles": ["answer_move_on"],
            },
            "ready_to_generate": True,
        }
    )
    question = ResumeQuestionRead(
        id="experience_story",
        category=FactCategory.EXPERIENCE,
        question="احكي لي عن خبرتك العملية.",
        why_it_matters="نحتاج مثالًا مهنيًا واضحًا.",
        placeholder="المسمى، الشركة، والمسؤوليات.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.AR,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_move_on",
    )

    assert result.proposed_records == []
    assert result.draft_patch is None
    assert result.next_question is not None
    assert result.ready_to_generate is False


@pytest.mark.parametrize(
    ("answer", "current_category", "expected"),
    [
        ("سويت مشروع تخرج في الجامعة باستخدام بايثون", "experience", "project"),
        ("تدربت في جامعة الملك فهد", "education", "experience"),
        ("حصلت على شهادة PMP من جامعة الملك فهد", "education", "certification"),
    ],
)
def test_adaptive_answer_category_uses_context_not_the_institution_word(
    answer: str,
    current_category: str,
    expected: str,
) -> None:
    assert (
        _adaptive_answer_category(
            answer,
            current_category=current_category,  # type: ignore[arg-type]
            generated_records=[],
            answer_handle="answer_context",
        )
        == expected
    )


@pytest.mark.asyncio
async def test_adaptive_turn_treats_bachelor_certificate_as_education() -> None:
    answer = "عندي شهادة بكالوريوس في المالية"
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_degree"],
                "confirmation_question": "هل هذا يلخص ما تقصده بدقة؟",
            },
            "proposed_records": [
                {
                    "record_type": "certification",
                    "source_handles": ["answer_degree"],
                    "title": answer,
                }
            ],
            "next_question": {
                "id": "certification_issuer",
                "category": "certification",
                "question": "ما الجهة المانحة؟",
                "why_it_matters": "الجهة تكمل بيانات الشهادة.",
                "placeholder": "اسم الجهة.",
                "required": False,
            },
            "draft_patch": None,
            "ready_to_generate": False,
        }
    )
    question = ResumeQuestionRead(
        id="certification_story",
        category=FactCategory.CERTIFICATION,
        question="ما الشهادات التي حصلت عليها؟",
        why_it_matters="نحتاج تفاصيل مؤهلاتك.",
        placeholder="اسم الشهادة والجهة.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.EN,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_degree",
    )

    assert len(result.proposed_records) == 1
    assert result.proposed_records[0].record_type == "education"
    assert result.next_question is not None
    assert result.next_question.category is FactCategory.CERTIFICATION


@pytest.mark.asyncio
async def test_adaptive_turn_rejects_cross_category_achievement_for_current_answer() -> None:
    answer = "أنا متخرج من جامعة البترول تخصص مالية"
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_education"],
                "confirmation_question": "هل هذا يلخص ما تقصده بدقة؟",
            },
            "proposed_records": [
                {
                    "record_type": "achievement",
                    "source_handles": ["answer_education"],
                    "title": answer,
                }
            ],
            "next_question": None,
            "draft_patch": {
                "section_key": "achievement",
                "title": answer,
                "bullet_candidates": [answer],
                "evidence_handles": ["answer_education"],
            },
            "ready_to_generate": True,
        }
    )
    question = ResumeQuestionRead(
        id="experience_story",
        category=FactCategory.EXPERIENCE,
        question="احكي لي عن خبرتك العملية.",
        why_it_matters="نحتاج مثالًا مهنيًا واضحًا.",
        placeholder="المسمى، الشركة، والمسؤوليات.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.AR,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_education",
    )

    assert len(result.proposed_records) == 1
    assert result.proposed_records[0].record_type == "education"
    assert result.draft_patch is None
    assert result.next_question is not None
    assert result.next_question.category is FactCategory.EXPERIENCE
    assert result.ready_to_generate is False


@pytest.mark.asyncio
async def test_adaptive_turn_prefers_project_actions_over_a_tool_keyword() -> None:
    answer = "سويت لوحة ببايثون"
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_project"],
                "confirmation_question": "هل هذا يلخص ما تقصده بدقة؟",
            },
            "proposed_records": [
                {
                    "record_type": "skill",
                    "source_handles": ["answer_project"],
                    "title": answer,
                }
            ],
            "next_question": {
                "id": "skill_usage",
                "category": "skill",
                "question": "كم سنة استخدمت بايثون؟",
                "why_it_matters": "يوضح مستوى المهارة.",
                "placeholder": "عدد السنوات.",
                "required": False,
            },
            "draft_patch": {
                "section_key": "skill",
                "title": answer,
                "bullet_candidates": [answer],
                "evidence_handles": ["answer_project"],
            },
            "ready_to_generate": False,
        }
    )
    question = ResumeQuestionRead(
        id="project_story",
        category=FactCategory.PROJECT,
        question="احكي لي عن مشروع نفذته.",
        why_it_matters="نحتاج مثالًا عمليًا.",
        placeholder="المشروع، دورك، والأدوات.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.AR,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_project",
    )

    assert len(result.proposed_records) == 1
    assert result.proposed_records[0].record_type == "project"
    assert result.proposed_records[0].title == answer
    assert result.draft_patch is None
    assert result.next_question is not None
    assert result.next_question.category is FactCategory.PROJECT
    assert result.next_question.id.startswith("project_follow_up_")


@pytest.mark.asyncio
async def test_adaptive_turn_checks_each_conversation_field_language() -> None:
    answer = "عملت على تقارير مالية أسبوعية وراجعت النتائج مع الفريق"
    provider = CapturingResumeWriter(
        {
            "understanding": {
                "summary": answer,
                "confidence": "high",
                "evidence_handles": ["answer_experience"],
                "confirmation_question": "Correct?",
            },
            "proposed_records": [
                {
                    "record_type": "experience",
                    "source_handles": ["answer_experience"],
                    "title": answer,
                }
            ],
            "next_question": {
                "id": "experience_outcome",
                "category": "experience",
                "question": "ما النتيجة التي حققتها؟",
                "why_it_matters": "توضح النتيجة أثر عملك.",
                "placeholder": "Company?",
                "required": False,
            },
            "draft_patch": None,
            "ready_to_generate": False,
        }
    )
    question = ResumeQuestionRead(
        id="experience_story",
        category=FactCategory.EXPERIENCE,
        question="احكي لي عن تجربة عمل تفتخر بها.",
        why_it_matters="نحتاج مثالًا مهنيًا واضحًا.",
        placeholder="التجربة، دورك، والأثر.",
        required=False,
    )

    result = await provider.generate_adaptive_turn(
        conversation_language=PreferredLanguage.AR,
        output_language=PreferredLanguage.EN,
        target_role=None,
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question=question,
        answer=answer,
        answer_handle="answer_experience",
    )

    assert result.understanding.confirmation_question == "هل هذا يلخص ما تقصده بدقة؟"
    assert result.next_question is not None
    assert result.next_question.category is FactCategory.EXPERIENCE
    assert "مسماك" in result.next_question.question


@pytest.mark.asyncio
async def test_section_rewrite_is_a_grounded_candidate_and_uses_writer_model() -> None:
    provider = CapturingResumeWriter(
        {
            "section_key": "project",
            "item_id": "inventory_project",
            "original_text": "provider must not replace this value",
            "proposed_text": "Produced clear weekly inventory reports using Python.",
            "evidence_handles": ["fact_1"],
        }
    )

    result = await provider.rewrite_section(
        language=PreferredLanguage.EN,
        target_role="Data Analyst",
        evidence=evidence(),
        section_key="project",
        item_id="inventory_project",
        original_text="Built inventory reports using Python.",
        instruction="Make it stronger and concise",
        evidence_handles=["fact_1"],
    )

    assert result.original_text == "Built inventory reports using Python."
    assert result.proposed_text == "Produced clear weekly inventory reports using Python."
    assert result.evidence_handles == ["fact_1"]
    assert len(provider.calls) == 1
    assert provider.calls[0]["model_name"] == "writer-model"
    assert provider.calls[0]["max_tokens"] == 400


@pytest.mark.asyncio
async def test_section_rewrite_retries_an_unsupported_candidate() -> None:
    provider = CapturingResumeWriter(
        [
            {
                "section_key": "project",
                "item_id": "inventory_project",
                "original_text": "Built inventory reports using Python.",
                "proposed_text": "Increased revenue by 50% using Python.",
                "evidence_handles": ["fact_1"],
            },
            {
                "section_key": "project",
                "item_id": "inventory_project",
                "original_text": "Built inventory reports using Python.",
                "proposed_text": "Produced weekly inventory reports using Python.",
                "evidence_handles": ["fact_1"],
            },
        ]
    )

    result = await provider.rewrite_section(
        language=PreferredLanguage.EN,
        target_role="Data Analyst",
        evidence=evidence(),
        section_key="project",
        item_id="inventory_project",
        original_text="Built inventory reports using Python.",
        instruction="Shorten it",
        evidence_handles=["fact_1"],
    )

    assert result.proposed_text == "Produced weekly inventory reports using Python."
    assert len(provider.calls) == 2
    assert "prior candidate was rejected" in provider.calls[1]["system_instructions"].lower()


@pytest.mark.asyncio
async def test_section_rewrite_retries_a_repetitive_multi_sentence_bullet() -> None:
    rewrite_evidence = (
        ResumeEvidence(
            handle="fact_1",
            category="experience",
            label="Monthly variance analysis, cost control, and internal financial reviews",
            detail=(
                "Performed monthly variance analysis, cost control, and internal financial reviews."
            ),
            verification_status="confirmed",
        ),
    )
    provider = CapturingResumeWriter(
        [
            {
                "section_key": "experience",
                "item_id": "cost_analyst",
                "original_text": (
                    "Performed monthly variance analysis, cost control, and internal financial "
                    "reviews."
                ),
                "proposed_text": (
                    "Performed monthly variance analysis. "
                    "Performed cost control. "
                    "Performed internal financial reviews."
                ),
                "evidence_handles": ["fact_1"],
            },
            {
                "section_key": "experience",
                "item_id": "cost_analyst",
                "original_text": (
                    "Performed monthly variance analysis, cost control, and internal financial "
                    "reviews."
                ),
                "proposed_text": (
                    "Conducted monthly variance analysis, cost control, and internal financial "
                    "reviews."
                ),
                "evidence_handles": ["fact_1"],
            },
        ]
    )

    result = await provider.rewrite_section(
        language=PreferredLanguage.EN,
        target_role="Data Analyst",
        evidence=rewrite_evidence,
        section_key="experience",
        item_id="cost_analyst",
        original_text=(
            "Performed monthly variance analysis, cost control, and internal financial reviews."
        ),
        instruction="Make this bullet stronger",
        evidence_handles=["fact_1"],
    )

    assert result.proposed_text == (
        "Conducted monthly variance analysis, cost control, and internal financial reviews."
    )
    assert len(provider.calls) == 2
    assert "prior candidate was rejected" in provider.calls[1]["system_instructions"].lower()


@pytest.mark.parametrize(
    ("original_text", "proposed_text"),
    [
        ("Supported monthly financial reviews.", "Conducted monthly financial reviews."),
        ("Supported cost control measures.", "Implemented cost control measures."),
        (
            "Supported cost control measures.",
            "Supported and implemented cost control measures.",
        ),
        (
            "Supported cost control measures.",
            "Supported and responsible for cost control measures.",
        ),
        (
            "Supported cost control measures.",
            "Supported and leverage cost control measures.",
        ),
        (
            "\u062f\u0639\u0645\u062a \u0645\u0631\u0627\u062c\u0639\u0627\u062a "
            "\u0645\u0627\u0644\u064a\u0629 "
            "\u0634\u0647\u0631\u064a\u0629.",
            "\u062f\u0639\u0645\u062a\u060c \u0646\u0641\u0630\u062a "
            "\u0645\u0631\u0627\u062c\u0639\u0627\u062a "
            "\u0645\u0627\u0644\u064a\u0629 \u0634\u0647\u0631\u064a\u0629.",
        ),
        ("Implemented cost control measures.", "Cost control measures."),
    ],
)
def test_section_rewrite_rejects_unsupported_ownership_upgrade(
    original_text: str,
    proposed_text: str,
) -> None:
    rewrite_evidence = (
        ResumeEvidence(
            handle="fact_1",
            category="experience",
            label="Monthly financial reviews",
            detail=(
                "Performed variance analysis and supported monthly financial reviews and cost "
                "control measures. Implemented cost control measures."
            ),
            verification_status="confirmed",
        ),
    )

    with pytest.raises(ResumeWriterError):
        resume_writer_module._validated_rewrite_candidate(
            resume_writer_module.ResumeRewriteCandidate(
                section_key="experience",
                item_id="finance_role",
                original_text=original_text,
                proposed_text=proposed_text,
                evidence_handles=["fact_1"],
            ),
            section_key="experience",
            item_id="finance_role",
            original_text=original_text,
            evidence=rewrite_evidence,
            allowed_handles=["fact_1"],
        )


@pytest.mark.parametrize(
    "proposed_text",
    [
        "Performed monthly variance analysis.",
        (
            "Performed monthly variance analysis and performed cost control and performed "
            "internal financial reviews."
        ),
    ],
)
def test_section_rewrite_rejects_dropped_material_or_repeated_inline_action(
    proposed_text: str,
) -> None:
    original_text = (
        "Performed monthly variance analysis, cost control, and internal financial reviews."
    )
    rewrite_evidence = (
        ResumeEvidence(
            handle="fact_1",
            category="experience",
            label="Monthly finance responsibilities",
            detail=original_text,
            verification_status="confirmed",
        ),
    )

    with pytest.raises(ResumeWriterError):
        resume_writer_module._validated_rewrite_candidate(
            resume_writer_module.ResumeRewriteCandidate(
                section_key="experience",
                item_id="cost_analyst",
                original_text=original_text,
                proposed_text=proposed_text,
                evidence_handles=["fact_1"],
            ),
            section_key="experience",
            item_id="cost_analyst",
            original_text=original_text,
            evidence=rewrite_evidence,
            allowed_handles=["fact_1"],
        )


@pytest.mark.asyncio
async def test_summary_rewrite_keeps_a_larger_output_budget() -> None:
    provider = CapturingResumeWriter(
        {
            "section_key": "professional_summary",
            "item_id": None,
            "original_text": "provider must not replace this value",
            "proposed_text": "Produced weekly inventory reports using Python.",
            "evidence_handles": ["fact_1"],
        }
    )

    result = await provider.rewrite_section(
        language=PreferredLanguage.EN,
        target_role="Data Analyst",
        evidence=evidence(),
        section_key="professional_summary",
        item_id=None,
        original_text="Built weekly inventory reports using Python.",
        instruction="Make the summary more professional",
        evidence_handles=["fact_1"],
    )

    assert result.proposed_text == "Produced weekly inventory reports using Python."
    assert provider.calls[0]["max_tokens"] == 2_000


@pytest.mark.asyncio
async def test_section_rewrite_does_not_retry_a_transport_failure() -> None:
    provider = CapturingResumeWriter(
        [
            ResumeWriterTransportError("provider request timed out", transient=True),
            {
                "section_key": "project",
                "item_id": "inventory_project",
                "original_text": "Built inventory reports using Python.",
                "proposed_text": "Produced weekly inventory reports using Python.",
                "evidence_handles": ["fact_1"],
            },
        ]
    )

    with pytest.raises(ResumeWriterTransportError) as captured:
        await provider.rewrite_section(
            language=PreferredLanguage.EN,
            target_role="Data Analyst",
            evidence=evidence(),
            section_key="project",
            item_id="inventory_project",
            original_text="Built inventory reports using Python.",
            instruction="Make this bullet stronger",
            evidence_handles=["fact_1"],
        )

    assert captured.value.transient is True
    assert len(provider.calls) == 1
    assert len(provider.responses) == 1


@pytest.mark.asyncio
async def test_section_rewrite_has_one_total_wall_clock_budget() -> None:
    class SlowRewriteWriter(CapturingResumeWriter):
        async def _structured_response(self, **kwargs: Any) -> BaseModel:
            await asyncio.sleep(0.05)
            return await super()._structured_response(**kwargs)

    provider = SlowRewriteWriter(
        {
            "section_key": "project",
            "item_id": "inventory_project",
            "original_text": "Built inventory reports using Python.",
            "proposed_text": "Produced weekly inventory reports using Python.",
            "evidence_handles": ["fact_1"],
        }
    )
    provider._timeout_seconds = 0.01

    with pytest.raises(ResumeWriterTransportError) as captured:
        await provider.rewrite_section(
            language=PreferredLanguage.EN,
            target_role="Data Analyst",
            evidence=evidence(),
            section_key="project",
            item_id="inventory_project",
            original_text="Built inventory reports using Python.",
            instruction="Make this bullet stronger",
            evidence_handles=["fact_1"],
        )

    assert captured.value.transient is True
    assert len(provider.calls) == 0


@pytest.mark.asyncio
async def test_translation_verification_pipeline_has_one_total_wall_clock_budget() -> None:
    source_value = "\u0623\u0643\u062a\u0628 \u0627\u0644\u0634\u0639\u0631"
    translated_value = "Write poetry"
    support = ResumeEvidence(
        handle="translation_pipeline_deadline",
        category="project",
        label="Creative Writing",
        detail=source_value,
        verification_status="confirmed",
        structured_value={
            "supplemental_details": {
                "responsibility_or_scope": {"value": source_value},
            }
        },
    )

    class SlowTranslationWriter(CapturingResumeWriter):
        def __init__(self) -> None:
            super().__init__(
                [
                    {
                        "translations": [
                            {
                                "handle": support.handle,
                                "field": "responsibility_or_scope",
                                "value_index": 0,
                                "translated_value": translated_value,
                            }
                        ]
                    },
                    supplemental_verification_response(
                        handle=support.handle,
                        field="responsibility_or_scope",
                        pairs=[(source_value, translated_value)],
                    ),
                ]
            )
            self.started_schemas: list[str] = []

        async def _structured_response(self, **kwargs: Any) -> BaseModel:
            self.started_schemas.append(str(kwargs["schema_name"]))
            await asyncio.sleep(0.03)
            return await super()._structured_response(**kwargs)

    provider = SlowTranslationWriter()
    provider._timeout_seconds = 0.05

    with pytest.raises(ResumeWriterTransportError) as captured:
        await provider.generate_draft(
            language=PreferredLanguage.EN,
            target_role=None,
            evidence=(support,),
            answers=[],
        )

    assert captured.value.transient is True
    assert provider.started_schemas == [
        "resume_supplemental_translations",
        "resume_supplemental_translation_verification",
    ]
    assert [call["schema_name"] for call in provider.calls] == [
        "resume_supplemental_translations"
    ]
    assert len(provider.responses) == 1


@pytest.mark.asyncio
async def test_provider_uses_dedicated_interview_and_writer_models_with_one_key() -> None:
    provider = await get_resume_writer_provider(
        Settings(
            _env_file=None,
            environment="test",
            ai_provider="mistral",
            mistral_api_key=SecretStr("one-shared-key"),
            ai_model="fallback-model",
            resume_interview_model="interview-model",
            resume_writer_model="writer-model",
        )
    )

    assert provider.model == "writer-model"
    assert provider.interview_model == "interview-model"


@pytest.mark.asyncio
async def test_mistral_provider_wraps_failures_once_with_safe_transience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TinyResponse(BaseModel):
        value: str

    class ProviderStatusError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__(f"provider status {status_code}")
            self.status_code = status_code

    class FailingCompletions:
        def __init__(self, failure: Exception) -> None:
            self.failure = failure
            self.calls = 0

        async def create(self, **_kwargs: Any) -> SimpleNamespace:
            self.calls += 1
            raise self.failure

    class FailingClient:
        def __init__(self, failure: Exception) -> None:
            self.completions = FailingCompletions(failure)
            self.chat = SimpleNamespace(completions=self.completions)

        def with_options(self, **_kwargs: Any) -> FailingClient:
            return self

    failures = [
        (TypeError("client bug"), False),
        (ProviderStatusError(401), False),
        (TimeoutError("request timed out"), True),
        (httpx.ConnectError("network unavailable"), True),
    ]
    for failure, expected_transient in failures:
        provider = MistralResumeWriterProvider(
            api_key="test-key",
            model="writer-model",
            interview_model="interview-model",
            timeout_seconds=5,
            max_tokens=4_000,
        )
        client = FailingClient(failure)
        monkeypatch.setattr(provider, "_get_client", lambda client=client: client)

        with pytest.raises(ResumeWriterTransportError) as captured:
            await provider._structured_response(
                schema=TinyResponse,
                schema_name="professional_resume_draft",
                system_instructions="Return JSON",
                payload={"draft": 1},
                max_tokens=4_000,
                model_name="writer-model",
            )

        assert captured.value.transient is expected_transient
        assert client.completions.calls == 1


@pytest.mark.asyncio
async def test_mistral_wall_clock_timeout_bounds_nonadaptive_draft_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TinyResponse(BaseModel):
        value: str

    class SlowCompletions:
        def __init__(self) -> None:
            self.calls = 0

        async def create(self, **_kwargs: Any) -> SimpleNamespace:
            self.calls += 1
            await asyncio.sleep(1)
            raise AssertionError("wall-clock timeout did not cancel the provider request")

    class SlowClient:
        def __init__(self) -> None:
            self.completions = SlowCompletions()
            self.chat = SimpleNamespace(completions=self.completions)
            self.options: list[dict[str, Any]] = []

        def with_options(self, **kwargs: Any) -> SlowClient:
            self.options.append(kwargs)
            return self

    provider = MistralResumeWriterProvider(
        api_key="test-key",
        model="writer-model",
        interview_model="interview-model",
        timeout_seconds=0.01,
        max_tokens=4_000,
    )
    client = SlowClient()
    monkeypatch.setattr(provider, "_get_client", lambda: client)

    with pytest.raises(ResumeWriterTransportError) as captured:
        await provider._structured_response(
            schema=TinyResponse,
            schema_name="professional_resume_draft",
            system_instructions="Return JSON",
            payload={"draft": 1},
            max_tokens=4_000,
            model_name="writer-model",
        )

    assert captured.value.transient is True
    assert client.options == [{"timeout": 0.01, "max_retries": 0}]
    assert client.completions.calls == 1


@pytest.mark.asyncio
async def test_mistral_provider_reuses_client_and_bounds_interactive_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TinyResponse(BaseModel):
        value: str

    class FakeCompletions:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.delay = 0.0

        async def create(self, **kwargs: Any) -> SimpleNamespace:
            self.calls.append(kwargs)
            if self.delay:
                await asyncio.sleep(self.delay)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content='{"value":"ok"}'),
                    )
                ]
            )

    class FakeAsyncOpenAI:
        instances: list[FakeAsyncOpenAI] = []

        def __init__(self, **kwargs: Any) -> None:
            self.init_kwargs = kwargs
            self.options: list[dict[str, Any]] = []
            self.completions = FakeCompletions()
            self.chat = SimpleNamespace(completions=self.completions)
            self.closed = False
            self.instances.append(self)

        def with_options(self, **kwargs: Any) -> FakeAsyncOpenAI:
            self.options.append(kwargs)
            return self

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        "career_agent_api.services.resume_writer.AsyncOpenAI",
        FakeAsyncOpenAI,
    )
    provider = MistralResumeWriterProvider(
        api_key="test-key",
        model="writer-model",
        interview_model="interview-model",
        timeout_seconds=55,
        max_tokens=4_000,
    )

    adaptive = await provider._structured_response(
        schema=TinyResponse,
        schema_name="adaptive_resume_interview_turn",
        system_instructions="Return JSON",
        payload={"turn": 1},
        max_tokens=1_000,
        model_name="interview-model",
    )
    draft = await provider._structured_response(
        schema=TinyResponse,
        schema_name="professional_resume_draft",
        system_instructions="Return JSON",
        payload={"draft": 1},
        max_tokens=4_000,
        model_name="writer-model",
    )
    translation = await provider._structured_response(
        schema=TinyResponse,
        schema_name="resume_supplemental_translations",
        system_instructions="Return JSON",
        payload={"translation": 1},
        max_tokens=2_000,
        model_name="writer-model",
    )
    verification = await provider._structured_response(
        schema=TinyResponse,
        schema_name="resume_supplemental_translation_verification",
        system_instructions="Return JSON",
        payload={"verification": 1},
        max_tokens=2_000,
        model_name="writer-model",
    )
    rewrite = await provider._structured_response(
        schema=TinyResponse,
        schema_name="resume_section_rewrite_candidate",
        system_instructions="Return JSON",
        payload={"rewrite": 1},
        max_tokens=1_500,
        model_name="writer-model",
    )

    assert adaptive.value == "ok"
    assert draft.value == "ok"
    assert translation.value == "ok"
    assert verification.value == "ok"
    assert rewrite.value == "ok"
    assert len(FakeAsyncOpenAI.instances) == 1
    client = FakeAsyncOpenAI.instances[0]
    assert client.options == [
        {"timeout": 15.0, "max_retries": 0},
        {"timeout": 45.0, "max_retries": 0},
        {"timeout": 20.0, "max_retries": 0},
        {"timeout": 20.0, "max_retries": 0},
        {"timeout": 30.0, "max_retries": 0},
    ]
    assert len(client.completions.calls) == 5

    client.completions.delay = 0.05
    provider._timeout_seconds = 0.01
    with pytest.raises(ResumeWriterError, match="provider request failed"):
        await provider._structured_response(
            schema=TinyResponse,
            schema_name="adaptive_resume_interview_turn",
            system_instructions="Return JSON",
            payload={"turn": 2},
            max_tokens=1_000,
            model_name="interview-model",
        )
    assert client.options[-1] == {"timeout": 0.01, "max_retries": 0}

    await provider.aclose()
    assert client.closed is True


@pytest.mark.asyncio
async def test_provider_cache_reuses_by_value_and_closes_replaced_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProvider:
        provider_name = "fake"

        def __init__(self) -> None:
            self.close_count = 0

        async def aclose(self) -> None:
            self.close_count += 1

    await resume_writer_module.close_resume_writer_provider()
    created: list[FakeProvider] = []

    def build(_settings: Settings) -> FakeProvider:
        provider = FakeProvider()
        created.append(provider)
        return provider

    monkeypatch.setattr(resume_writer_module, "_build_resume_writer_provider", build)
    first_settings = Settings(_env_file=None, environment="test")
    equivalent_settings = Settings(_env_file=None, environment="test")
    changed_settings = Settings(
        _env_file=None, environment="test", ai_model="another-writer-model"
    )

    # Two concurrent cold requests must share one construction, not build two clients.
    first, concurrent = await asyncio.gather(
        resume_writer_module.get_resume_writer_provider(first_settings),
        resume_writer_module.get_resume_writer_provider(first_settings),
    )
    assert concurrent is first
    assert len(created) == 1
    assert await resume_writer_module.get_resume_writer_provider(first_settings) is first
    # Equivalent settings values reuse the warm provider even from a different instance.
    assert await resume_writer_module.get_resume_writer_provider(equivalent_settings) is first

    second = await resume_writer_module.get_resume_writer_provider(changed_settings)
    assert second is not first
    assert len(created) == 2
    # The replaced provider was closed when the cache key changed; the live one stays open.
    assert first.close_count == 1
    assert second.close_count == 0

    await resume_writer_module.close_resume_writer_provider()
    assert [provider.close_count for provider in created] == [1, 1]


def test_rewrite_may_drop_a_content_free_qualifier() -> None:
    """"Relevant" in "Relevant Coursework" qualifies nothing verifiable, so dropping it
    must not be treated as losing supported material."""

    original_text = (
        "Relevant Coursework: Auditing, Financial Accounting, Risk Management, Cost Control"
    )
    proposed_text = (
        "Coursework: Auditing, Financial Accounting, Risk Management, and Cost Control"
    )
    evidence = (
        ResumeEvidence(
            handle="fact_1",
            category="education",
            label="Bachelor degree in Finance",
            detail=original_text,
            verification_status="confirmed",
        ),
    )

    candidate = resume_writer_module._validated_rewrite_candidate(
        resume_writer_module.ResumeRewriteCandidate(
            section_key="education",
            item_id="degree_1",
            original_text=original_text,
            proposed_text=proposed_text,
            evidence_handles=["fact_1"],
        ),
        section_key="education",
        item_id="degree_1",
        original_text=original_text,
        evidence=evidence,
        allowed_handles=["fact_1"],
    )
    assert candidate.proposed_text == proposed_text


def test_rewrite_rejection_is_reported_as_an_output_error() -> None:
    """A rejected rewrite is a content verdict, not a provider outage; the API layer
    relies on the distinct type to avoid telling the user to retry pointlessly."""

    original_text = "Reconciled 48 monthly reports for the finance team."
    evidence = (
        ResumeEvidence(
            handle="fact_1",
            category="experience",
            label="Monthly reconciliations",
            detail=original_text,
            verification_status="confirmed",
        ),
    )

    with pytest.raises(resume_writer_module.ResumeWriterOutputError):
        resume_writer_module._validated_rewrite_candidate(
            resume_writer_module.ResumeRewriteCandidate(
                section_key="experience",
                item_id="finance_role",
                original_text=original_text,
                proposed_text="Reconciled reports for the team.",
                evidence_handles=["fact_1"],
            ),
            section_key="experience",
            item_id="finance_role",
            original_text=original_text,
            evidence=evidence,
            allowed_handles=["fact_1"],
        )


def test_rejected_rewrite_names_the_dropped_terms_in_the_users_wording() -> None:
    """A bare "it was rejected" is a dead end; the user needs to see what was lost."""

    original_text = (
        "Relevant Coursework: Auditing, Financial Accounting, Cost Control, "
        "Internal Control Systems"
    )
    evidence = (
        ResumeEvidence(
            handle="fact_1",
            category="education",
            label="Bachelor degree in Finance",
            detail=original_text,
            verification_status="confirmed",
        ),
    )

    with pytest.raises(resume_writer_module.ResumeWriterOutputError) as excinfo:
        resume_writer_module._validated_rewrite_candidate(
            resume_writer_module.ResumeRewriteCandidate(
                section_key="education",
                item_id="degree_1",
                original_text=original_text,
                proposed_text="Coursework: Auditing and Financial Accounting",
                evidence_handles=["fact_1"],
            ),
            section_key="education",
            item_id="degree_1",
            original_text=original_text,
            evidence=evidence,
            allowed_handles=["fact_1"],
        )

    dropped = excinfo.value.dropped_terms
    # Reported as the user wrote them, not as normalized tokens.
    assert "Cost" in dropped and "Control" in dropped and "Internal" in dropped
    assert all(term[0].isupper() for term in dropped)
