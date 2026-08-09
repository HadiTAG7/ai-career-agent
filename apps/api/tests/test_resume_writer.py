from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, SecretStr, ValidationError

import career_agent_api.services.resume_writer as resume_writer_module
from career_agent_api.core.config import Settings
from career_agent_api.models.enums import FactCategory, PreferredLanguage, VerificationStatus
from career_agent_api.schemas.api import ResumeQuestionRead
from career_agent_api.services.resume_writer import (
    RESUME_SECTION_ORDER,
    MistralResumeWriterProvider,
    ResumeEvidence,
    ResumeWriterError,
    _adaptive_answer_category,
    _GeneratedDraft,
    _redact_resume_text,
    _restore_open_ended_number_qualifiers,
    _sanitize_generated_draft,
    _StructuredResumeWriterProvider,
    _validate_gpa_policy,
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
        "skill",
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
    assert result.next_question.category is FactCategory.EDUCATION
    assert "الدرجة" in result.next_question.question
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
    assert result.next_question.category is FactCategory.EDUCATION


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
    assert result.next_question.category is FactCategory.EDUCATION
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
    assert result.next_question.category is FactCategory.SKILL
    assert result.next_question.id == "skill_usage"


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
    assert client.options == [{"timeout": 15.0, "max_retries": 0}]
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
