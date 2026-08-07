from uuid import uuid4

from career_agent_api.models.domain import CareerFact, JobRequirement
from career_agent_api.models.enums import (
    ApplyDecision,
    FactCategory,
    ReadinessBand,
    RequirementCategory,
    RequirementImportance,
    RequirementMatchStatus,
)
from career_agent_api.services.matching import calculate_match


def requirement(
    category: RequirementCategory,
    importance: RequirementImportance,
    normalized: str,
) -> JobRequirement:
    return JobRequirement(
        id=uuid4(),
        category=category,
        importance=importance,
        text=f"Requirement: {normalized}",
        normalized_value=normalized,
        weight=1,
    )


def fact(category: FactCategory, label: str) -> CareerFact:
    return CareerFact(
        id=uuid4(),
        profile_id=uuid4(),
        source_id=uuid4(),
        category=category,
        label=label,
        detail=None,
        structured_value={},
    )


def test_weighted_score_exposes_mandatory_gap() -> None:
    requirements = [
        requirement(RequirementCategory.SKILL, RequirementImportance.MANDATORY, "python"),
        requirement(RequirementCategory.EDUCATION, RequirementImportance.MANDATORY, "bachelor"),
        requirement(RequirementCategory.SKILL, RequirementImportance.PREFERRED, "figma"),
    ]
    result = calculate_match(
        requirements,
        [fact(FactCategory.SKILL, "Python"), fact(FactCategory.EDUCATION, "Diploma")],
        complete_categories={FactCategory.SKILL, FactCategory.EDUCATION},
    )

    assert result["coverage_score"] == 40
    assert result["mandatory_coverage_score"] == 50
    assert result["readiness_band"] is ReadinessBand.LOW
    assert result["decision"] is ApplyDecision.IMPROVE_THEN_APPLY
    education_match = result["matches"][1]
    assert education_match["status"] is RequirementMatchStatus.MISSING
    assert result["explanation"]["mandatory_missing_count"] == 1


def test_missing_profile_category_returns_need_information() -> None:
    requirements = [
        requirement(
            RequirementCategory.ELIGIBILITY,
            RequirementImportance.MANDATORY,
            "saudi national",
        )
    ]
    result = calculate_match(requirements, [fact(FactCategory.SKILL, "Python")])
    assert result["matches"][0]["status"] is RequirementMatchStatus.UNKNOWN
    assert result["decision"] is ApplyDecision.NEED_INFORMATION


def test_any_unknown_requirement_keeps_the_decision_open() -> None:
    requirements = [
        requirement(RequirementCategory.SKILL, RequirementImportance.PREFERRED, "python"),
        requirement(
            RequirementCategory.ELIGIBILITY,
            RequirementImportance.MANDATORY,
            "saudi national",
        ),
    ]
    result = calculate_match(requirements, [fact(FactCategory.SKILL, "Python")])

    assert result["matches"][0]["status"] is RequirementMatchStatus.MATCHED
    assert result["matches"][1]["status"] is RequirementMatchStatus.UNKNOWN
    assert result["decision"] is ApplyDecision.NEED_INFORMATION


def test_unmatched_skill_is_unknown_until_user_marks_category_complete() -> None:
    requirements = [requirement(RequirementCategory.SKILL, RequirementImportance.MANDATORY, "sql")]
    result = calculate_match(requirements, [fact(FactCategory.SKILL, "Python")])
    assert result["matches"][0]["status"] is RequirementMatchStatus.UNKNOWN
    assert result["explanation"]["missing_count"] == 0
    assert result["explanation"]["unknown_count"] == 1


def test_mandatory_certification_is_missing_when_category_is_complete() -> None:
    requirements = [
        requirement(
            RequirementCategory.CERTIFICATION,
            RequirementImportance.MANDATORY,
            "aws",
        )
    ]
    result = calculate_match(
        requirements,
        [fact(FactCategory.SKILL, "AWS")],
        complete_categories={FactCategory.CERTIFICATION},
    )
    assert result["matches"][0]["status"] is RequirementMatchStatus.MISSING
    assert result["mandatory_coverage_score"] == 0
    assert result["decision"] is ApplyDecision.LOW_RETURN


def test_matching_uses_atomic_token_boundaries_and_rejects_negation() -> None:
    git_requirement = requirement(RequirementCategory.SKILL, RequirementImportance.MANDATORY, "git")
    sql_requirement = requirement(RequirementCategory.SKILL, RequirementImportance.MANDATORY, "sql")
    python_requirement = requirement(
        RequirementCategory.SKILL, RequirementImportance.MANDATORY, "python"
    )
    assert (
        calculate_match([git_requirement], [fact(FactCategory.SKILL, "Digital marketing")])[
            "matches"
        ][0]["status"]
        is not RequirementMatchStatus.MATCHED
    )
    assert (
        calculate_match([sql_requirement], [fact(FactCategory.SKILL, "NoSQL")])["matches"][0][
            "status"
        ]
        is not RequirementMatchStatus.MATCHED
    )
    assert (
        calculate_match([python_requirement], [fact(FactCategory.SKILL, "No Python experience")])[
            "matches"
        ][0]["status"]
        is not RequirementMatchStatus.MATCHED
    )
    assert (
        calculate_match([python_requirement], [fact(FactCategory.SKILL, "I didn't use Python")])[
            "matches"
        ][0]["status"]
        is not RequirementMatchStatus.MATCHED
    )
    assert (
        calculate_match([python_requirement], [fact(FactCategory.SKILL, "لم أستخدم Python")])[
            "matches"
        ][0]["status"]
        is not RequirementMatchStatus.MATCHED
    )


def test_experience_years_require_minimum_numeric_evidence() -> None:
    requirement_3_years = requirement(
        RequirementCategory.EXPERIENCE,
        RequirementImportance.MANDATORY,
        "3 years experience",
    )
    too_little = calculate_match(
        [requirement_3_years], [fact(FactCategory.EXPERIENCE, "1 year experience")]
    )
    enough = calculate_match(
        [requirement_3_years], [fact(FactCategory.EXPERIENCE, "5 years experience")]
    )
    assert too_little["matches"][0]["status"] is not RequirementMatchStatus.MATCHED
    assert enough["matches"][0]["status"] is RequirementMatchStatus.MATCHED

    numbered_skill = requirement(
        RequirementCategory.SKILL,
        RequirementImportance.MANDATORY,
        "iso 27001",
    )
    wrong_numeric_scope = calculate_match(
        [numbered_skill], [fact(FactCategory.SKILL, "ISO 27001 and ISO 9001")]
    )
    assert wrong_numeric_scope["matches"][0]["status"] is not RequirementMatchStatus.MATCHED


def test_relational_experience_requires_years_and_skill_in_one_fact() -> None:
    relational = requirement(
        RequirementCategory.EXPERIENCE,
        RequirementImportance.MANDATORY,
        "3 years of python experience",
    )
    separate = calculate_match(
        [relational],
        [
            fact(FactCategory.EXPERIENCE, "5 years experience"),
            fact(FactCategory.SKILL, "Python"),
        ],
    )
    combined = calculate_match(
        [relational],
        [fact(FactCategory.EXPERIENCE, "5 years of Python experience")],
    )
    unrelated_same_fact = calculate_match(
        [relational],
        [fact(FactCategory.EXPERIENCE, "5 years experience. Recently learned Python")],
    )
    assert separate["matches"][0]["status"] is not RequirementMatchStatus.MATCHED
    assert combined["matches"][0]["status"] is RequirementMatchStatus.MATCHED
    assert unrelated_same_fact["matches"][0]["status"] is not RequirementMatchStatus.MATCHED


def test_supported_saudi_ontology_aliases_match_across_languages() -> None:
    cases = [
        (RequirementCategory.LOCATION, "riyadh", FactCategory.PREFERENCE, "الرياض"),
        (RequirementCategory.LOCATION, "jeddah", FactCategory.PREFERENCE, "جدة"),
        (RequirementCategory.EDUCATION, "bachelor", FactCategory.EDUCATION, "بكالوريوس"),
        (RequirementCategory.LANGUAGE, "english", FactCategory.LANGUAGE, "لغة إنجليزية"),
        (RequirementCategory.ELIGIBILITY, "saudi national", FactCategory.ELIGIBILITY, "سعودية"),
    ]
    for requirement_category, normalized, fact_category, label in cases:
        result = calculate_match(
            [requirement(requirement_category, RequirementImportance.MANDATORY, normalized)],
            [fact(fact_category, label)],
        )
        assert result["matches"][0]["status"] is RequirementMatchStatus.MATCHED
