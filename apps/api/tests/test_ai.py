from career_agent_api.services.ai import DeterministicCareerProvider


def test_composite_english_skill_requirement_is_split() -> None:
    requirements = DeterministicCareerProvider().extract_requirements("Must know Python and SQL.")
    assert {item.normalized_value for item in requirements} == {"python", "sql"}
    assert all(item.text == "Must know Python and SQL." for item in requirements)


def test_composite_arabic_skill_requirement_is_split() -> None:
    requirements = DeterministicCareerProvider().extract_requirements("مطلوب إتقان Python و SQL.")
    assert {item.normalized_value for item in requirements} == {"python", "sql"}


def test_cross_category_requirement_is_split_without_misclassification() -> None:
    requirements = DeterministicCareerProvider().extract_requirements(
        "Must have a bachelor's degree and Python."
    )
    assert {(item.category.value, item.normalized_value) for item in requirements} == {
        ("education", "bachelor"),
        ("skill", "python"),
    }


def test_certification_requirements_are_atomic_in_english_and_arabic() -> None:
    provider = DeterministicCareerProvider()
    english = provider.extract_requirements("AWS certification is required.")
    arabic = provider.extract_requirements("شهادة PMP مطلوبة.")

    assert {(item.category.value, item.normalized_value) for item in english} == {
        ("certification", "aws")
    }
    assert {(item.category.value, item.normalized_value) for item in arabic} == {
        ("certification", "pmp")
    }


def test_negated_requirement_is_not_extracted_as_mandatory() -> None:
    requirements = DeterministicCareerProvider().extract_requirements(
        "Python experience is not required."
    )
    assert requirements == []


def test_mixed_importance_clauses_are_classified_independently() -> None:
    requirements = DeterministicCareerProvider().extract_requirements(
        "Python preferred; SQL required."
    )
    by_value = {item.normalized_value: item.importance.value for item in requirements}
    assert by_value == {"python": "preferred", "sql": "mandatory"}

    conjunction = DeterministicCareerProvider().extract_requirements(
        "Python preferred and SQL required."
    )
    assert {item.normalized_value: item.importance.value for item in conjunction} == by_value


def test_unqualified_requirement_like_line_is_preserved_for_review() -> None:
    requirements = DeterministicCareerProvider().extract_requirements("5 years of experience.")
    assert len(requirements) == 1
    assert requirements[0].category.value == "experience"
    assert requirements[0].needs_user_review is True


def test_relational_experience_is_kept_as_one_requirement() -> None:
    requirements = DeterministicCareerProvider().extract_requirements(
        "3 years of Python experience required."
    )
    assert len(requirements) == 1
    assert requirements[0].category.value == "experience"
    assert requirements[0].normalized_value == "3 years of python experience"


def test_negative_and_positive_adversative_clauses_are_split() -> None:
    requirements = DeterministicCareerProvider().extract_requirements(
        "Python is not required but SQL is required. React required."
    )
    assert {item.normalized_value for item in requirements} == {"sql", "react"}
