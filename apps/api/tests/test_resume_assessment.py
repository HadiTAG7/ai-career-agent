from uuid import uuid4

from career_agent_api.models.domain import CareerFact
from career_agent_api.models.enums import FactCategory, PreferredLanguage, VerificationStatus
from career_agent_api.services.resume_assessment import (
    SECTION_ORDER,
    build_resume_assessment,
    deterministic_gap_question,
)
from career_agent_api.services.resume_writer import RESUME_SECTION_ORDER


def _fact(
    category: FactCategory,
    label: str,
    *,
    detail: str | None = None,
    structured_value: dict | None = None,
) -> CareerFact:
    return CareerFact(
        id=uuid4(),
        profile_id=uuid4(),
        source_id=uuid4(),
        category=category,
        label=label,
        detail=detail,
        structured_value=structured_value or {},
        source_excerpt=detail or label,
        verification_status=VerificationStatus.CONFIRMED,
    )


def test_assessment_is_deterministic_grounded_and_has_no_acceptance_score() -> None:
    education = _fact(
        FactCategory.EDUCATION,
        "Bachelor of Finance",
        structured_value={"degree": "Bachelor of Finance", "institution": "Harbor University"},
    )
    experience = _fact(
        FactCategory.EXPERIENCE,
        "Finance Intern",
        detail="Prepared monthly cost reports using Excel.",
        structured_value={
            "title": "Finance Intern",
            "organization": "Harbor Company",
            "responsibilities": ["Prepared monthly cost reports using Excel."],
        },
    )

    first = build_resume_assessment([education, experience], {"parser": "pdf-v1"})
    second = build_resume_assessment([education, experience], {"parser": "pdf-v1"})
    dumped = first.model_dump(mode="json")

    assert dumped == second.model_dump(mode="json")
    assert "score" not in dumped
    assert dumped["found_sections"] == ["education", "experience"]
    assert dumped["missing_sections"] == ["skill", "language"]
    assert dumped["section_counts"]["education"] == 1
    assert dumped["page_target"] == 1
    assert "ليس احتمال قبول وظيفي" in dumped["disclaimer"]
    assert all(gap["key"] and gap["requested_fields"] for gap in dumped["gaps"])
    assert any(
        gap["key"].startswith(f"fact:{education.id.hex}:")
        and gap["record_label"] == "Bachelor of Finance"
        and gap["evidence_handles"] == [f"fact_{education.id.hex}"]
        for gap in dumped["gaps"]
    )
    assert (
        next(check for check in dumped["ats_checks"] if check["key"] == "visual_formatting")[
            "status"
        ]
        == "not_assessed"
    )


def test_gap_question_keeps_the_server_selected_key_and_fields() -> None:
    assessment = build_resume_assessment([], {})
    gap = assessment.gaps[0]

    question = deterministic_gap_question(gap, PreferredLanguage.AR)

    assert question["gap_key"] == gap.key
    assert question["category"] == gap.category.value
    assert question["fields_requested"] == gap.requested_fields
    assert question["evidence_handles"] == gap.evidence_handles
    assert question["generation_source"] == "deterministic_fallback"


def test_education_record_requires_degree_field_institution_and_date() -> None:
    education = _fact(
        FactCategory.EDUCATION,
        "Harbor University",
        structured_value={
            "institution": "Harbor University",
            "graduation_date": "2025",
        },
    )

    gap = next(
        gap
        for gap in build_resume_assessment([education]).gaps
        if gap.key.startswith(f"fact:{education.id.hex}:")
    )

    assert gap.requested_fields == ["degree", "field"]


def test_degree_phrase_with_explicit_finance_field_does_not_repeat_the_question() -> None:
    education = _fact(
        FactCategory.EDUCATION,
        "Bachelor degree in Finance",
        structured_value={
            "title": "Bachelor degree in Finance",
            "degree": "Bachelor degree in Finance",
            "institution": "King Fahd University of Petroleum and Minerals",
            "date_range": "Dec 2024",
        },
    )

    assessment = build_resume_assessment([education])

    assert all(not gap.key.startswith(f"fact:{education.id.hex}:") for gap in assessment.gaps)


def test_confirmed_supplemental_details_satisfy_only_the_named_gap_fields() -> None:
    experience = _fact(
        FactCategory.EXPERIENCE,
        "Investment & Trading Professional",
        detail="Manage a personal investment portfolio.",
        structured_value={
            "title": "Investment & Trading Professional",
            "date_range": "2018 - Present",
            "responsibilities": ["Manage a personal investment portfolio."],
            "supplemental_details": {
                "organization_or_context": {
                    "value": "Self-managed personal investment portfolio",
                    "source": {"kind": "resume_gap_interview"},
                }
            },
        },
    )

    assessment = build_resume_assessment([experience])

    assert all(not gap.key.startswith(f"fact:{experience.id.hex}:") for gap in assessment.gaps)


def test_assessment_gap_queue_follows_resume_section_order_before_priority() -> None:
    education = _fact(FactCategory.EDUCATION, "Harbor University")
    experience = _fact(
        FactCategory.EXPERIENCE,
        "Finance Analyst",
        detail="Prepared monthly reports for finance stakeholders.",
        structured_value={"organization": "Harbor Company"},
    )
    project = _fact(FactCategory.PROJECT, "Forecasting Project")
    certification = _fact(FactCategory.CERTIFICATION, "Finance Certificate")
    skill = _fact(FactCategory.SKILL, "Excel")
    language = _fact(FactCategory.LANGUAGE, "English")

    assessment = build_resume_assessment(
        [language, skill, certification, project, experience, education]
    )

    assert [gap.category for gap in assessment.gaps] == [
        FactCategory.EDUCATION,
        FactCategory.EXPERIENCE,
        FactCategory.CERTIFICATION,
        FactCategory.SKILL,
        FactCategory.LANGUAGE,
        FactCategory.PROJECT,
    ]
    experience_gap = next(
        gap for gap in assessment.gaps if gap.category is FactCategory.EXPERIENCE
    )
    project_gap = next(gap for gap in assessment.gaps if gap.category is FactCategory.PROJECT)
    assert experience_gap.priority == "medium"
    assert project_gap.priority == "high"


def test_assessment_and_writer_share_the_same_resume_section_order() -> None:
    assert [category.value for category in SECTION_ORDER] == list(RESUME_SECTION_ORDER)


def test_record_gap_questions_follow_uploaded_resume_source_order() -> None:
    first_in_file = _fact(
        FactCategory.EXPERIENCE,
        "Cost Control & Finance Analyst",
        detail="Prepared monthly variance analysis.",
        structured_value={
            "source_handles": ["segment_4"],
            "date_range": "2025 - Present",
            "responsibilities": ["Prepared monthly variance analysis."],
        },
    )
    later_in_file = _fact(
        FactCategory.EXPERIENCE,
        "Financial Markets Instructor",
        detail="Delivered financial markets training.",
        structured_value={
            "source_handles": ["segment_6"],
            "date_range": "2022 - Present",
            "responsibilities": ["Delivered financial markets training."],
        },
    )

    assessment = build_resume_assessment([later_in_file, first_in_file])
    experience_labels = [
        gap.record_label
        for gap in assessment.gaps
        if gap.category is FactCategory.EXPERIENCE
    ]

    assert experience_labels == [
        "Cost Control & Finance Analyst",
        "Financial Markets Instructor",
    ]
