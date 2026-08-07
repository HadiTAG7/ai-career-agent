from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from career_agent_api.core.config import Settings
from career_agent_api.models.enums import FactCategory, PreferredLanguage, VerificationStatus
from career_agent_api.schemas.api import ResumeQuestionRead
from career_agent_api.services.resume_writer import (
    ResumeEvidence,
    ResumeWriterError,
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
            "summary": "You built an inventory dashboard with Python and weekly reports.",
            "confidence": "high",
            "evidence_handles": ["answer_turn_7"],
            "confirmation_question": "هل فهمت إجابتك بشكل صحيح؟",
        },
        "proposed_records": [
            {
                "record_type": "project",
                "source_handles": ["answer_turn_7"],
                "title": "Inventory dashboard",
                "responsibilities": ["Built weekly reports"],
                "tools": ["Python"],
            }
        ],
        "next_question": {
            "id": "inventory_outcome",
            "category": "project",
            "question": "What concrete outcome did the dashboard produce?",
            "why_it_matters": "It makes the project contribution clearer.",
            "placeholder": "Describe the outcome or skip if unknown.",
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
        language=PreferredLanguage.EN,
        target_role="Data Analyst",
        evidence=(),
        conversation=[{"role": "assistant", "content": question.question}],
        current_question={
            **question.model_dump(mode="json"),
            "fields_requested": ["action", "tools"],
            "quick_replies": ["skip"],
        },
        answer="I built an Inventory dashboard with Python and produced weekly reports.",
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
