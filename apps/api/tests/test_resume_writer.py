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
from career_agent_api.core.config import Settings
from career_agent_api.models.enums import FactCategory, PreferredLanguage, VerificationStatus
from career_agent_api.schemas.api import ResumeExportContact, ResumeQuestionRead
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


def test_provider_uses_dedicated_interview_and_writer_models_with_one_key() -> None:
    provider = get_resume_writer_provider(
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

    assert adaptive.value == "ok"
    assert draft.value == "ok"
    assert len(FakeAsyncOpenAI.instances) == 1
    client = FakeAsyncOpenAI.instances[0]
    assert client.options == [
        {"timeout": 15.0, "max_retries": 0},
        {"timeout": 45.0, "max_retries": 0},
    ]
    assert len(client.completions.calls) == 2

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
async def test_provider_cache_closes_every_settings_scoped_provider(
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
    second_settings = Settings(_env_file=None, environment="test")

    first = resume_writer_module.get_resume_writer_provider(first_settings)
    assert resume_writer_module.get_resume_writer_provider(first_settings) is first
    second = resume_writer_module.get_resume_writer_provider(second_settings)
    assert second is not first
    assert len(created) == 2

    await resume_writer_module.close_resume_writer_provider()
    assert [provider.close_count for provider in created] == [1, 1]
