from __future__ import annotations

import pytest

from career_agent_api.services.resume_writer import (
    ResumeEvidence,
    ResumeWriterError,
    _GeneratedDraft,
    _redact_resume_text,
    _validate_gpa_policy,
    _validated_draft,
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


def test_grounded_draft_allows_professional_rewording_and_target_positioning() -> None:
    draft = _validated_draft(generated_draft(), evidence(), "Data Analyst")

    assert draft.headline == "Data Analyst"
    assert draft.sections[0].items[0].organization == "university project"


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
        _validate_gpa_policy("GPA 2.5/4")
    with pytest.raises(ResumeWriterError, match="without a known scale"):
        _validate_gpa_policy("GPA 3.8")

    _validate_gpa_policy("GPA 3.8/4")
