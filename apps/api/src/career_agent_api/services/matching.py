import re
from collections import defaultdict

from career_agent_api.models.domain import CareerFact, JobRequirement
from career_agent_api.models.enums import (
    ApplyDecision,
    ConfidenceBand,
    FactCategory,
    ReadinessBand,
    RequirementCategory,
    RequirementImportance,
    RequirementMatchStatus,
)

CATEGORY_FACTS: dict[RequirementCategory, set[FactCategory]] = {
    RequirementCategory.SKILL: {
        FactCategory.SKILL,
        FactCategory.EXPERIENCE,
        FactCategory.PROJECT,
        FactCategory.CERTIFICATION,
    },
    RequirementCategory.EXPERIENCE: {FactCategory.EXPERIENCE},
    RequirementCategory.EDUCATION: {FactCategory.EDUCATION},
    RequirementCategory.CERTIFICATION: {FactCategory.CERTIFICATION},
    RequirementCategory.LANGUAGE: {FactCategory.LANGUAGE},
    RequirementCategory.LOCATION: {FactCategory.PREFERENCE},
    RequirementCategory.ELIGIBILITY: {FactCategory.ELIGIBILITY},
    RequirementCategory.OTHER: set(FactCategory),
}

REQUIREMENT_COMPLETENESS_CATEGORY: dict[RequirementCategory, FactCategory | None] = {
    RequirementCategory.SKILL: FactCategory.SKILL,
    RequirementCategory.EXPERIENCE: FactCategory.EXPERIENCE,
    RequirementCategory.EDUCATION: FactCategory.EDUCATION,
    RequirementCategory.CERTIFICATION: FactCategory.CERTIFICATION,
    RequirementCategory.LANGUAGE: FactCategory.LANGUAGE,
    RequirementCategory.LOCATION: FactCategory.PREFERENCE,
    RequirementCategory.ELIGIBILITY: FactCategory.ELIGIBILITY,
    RequirementCategory.OTHER: None,
}


def normalize(value: str) -> str:
    folded = value.casefold()
    folded = re.sub(
        r"\b(?:did|do|does|is|was|were|have|has|could|would|should)n['’]?t\b|"
        r"\bcan['’]?t\b|\bcannot\b",
        " not ",
        folded,
    )
    folded = folded.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    tokens = re.findall(r"[\w.+#-]+", folded, flags=re.UNICODE)
    single_aliases: dict[str, tuple[str, ...]] = {
        "الرياض": ("riyadh",),
        "جدة": ("jeddah",),
        "بكالوريوس": ("bachelor",),
        "دبلوم": ("diploma",),
        "الإنجليزية": ("english",),
        "الانجليزية": ("english",),
        "إنجليزية": ("english",),
        "انجليزية": ("english",),
        "العربية": ("arabic",),
        "عربية": ("arabic",),
        "سعودي": ("saudi",),
        "سعودية": ("saudi",),
    }
    expanded = [alias for token in tokens for alias in single_aliases.get(token, (token,))]
    phrase_aliases: dict[tuple[str, ...], tuple[str, ...]] = {
        ("عن", "بعد"): ("remote",),
        ("saudi", "national"): ("saudi",),
        ("saudi", "citizen"): ("saudi",),
    }
    normalized: list[str] = []
    index = 0
    while index < len(expanded):
        matched = False
        for phrase, replacement in phrase_aliases.items():
            if tuple(expanded[index : index + len(phrase)]) == phrase:
                normalized.extend(replacement)
                index += len(phrase)
                matched = True
                break
        if not matched:
            normalized.append(expanded[index])
            index += 1
    return " ".join(normalized)


def fact_text(fact: CareerFact) -> str:
    values = " ".join(
        str(value)
        for key, value in fact.structured_value.items()
        if key != "profile_field" and not key.startswith("_") and value is not None
    )
    return normalize(" ".join(filter(None, (fact.label, fact.detail, values))))


def _sequence_positions(haystack: list[str], needle: list[str]) -> list[int]:
    if not needle or len(needle) > len(haystack):
        return []
    return [
        index
        for index in range(len(haystack) - len(needle) + 1)
        if haystack[index : index + len(needle)] == needle
    ]


def _unsafe_attribution(tokens: list[str], start: int, length: int) -> bool:
    window = set(tokens[max(0, start - 6) : start + length + 3])
    negations = {
        "no",
        "not",
        "never",
        "without",
        "lack",
        "lacks",
        "lacking",
        "لا",
        "ليس",
        "لست",
        "بدون",
        "دون",
        "غير",
        "لم",
        "لن",
    }
    third_parties = {
        "he",
        "she",
        "they",
        "colleague",
        "coworker",
        "manager",
        "team",
        "client",
        "زميلي",
        "زميلتي",
        "مديري",
        "فريقي",
        "الفريق",
        "العميل",
    }
    return bool(window & (negations | third_parties))


def _year_value(value: str) -> float | None:
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*\+?\s*(?:years?|yrs?)\b|"
        r"([0-9٠-٩]+(?:[.,][0-9٠-٩]+)?)\s*سن(?:ة|وات)",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    raw = next(group for group in match.groups() if group is not None)
    translation = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return float(raw.translate(translation).replace(",", "."))


def _experience_relationship_supported(fact: CareerFact, relationship_qualifiers: set[str]) -> bool:
    fragments = [
        fragment
        for fragment in (
            fact.label,
            fact.detail,
            *(
                str(value)
                for key, value in fact.structured_value.items()
                if key != "profile_field" and not key.startswith("_") and value is not None
            ),
        )
        if fragment
    ]
    year_tokens = {"year", "years", "yrs", "سنة", "سنوات"}
    experience_tokens = {"experience", "خبرة"}
    relation_connectors = {"with", "in", "using", "في", "باستخدام"}
    for fragment in fragments:
        tokens = normalize(fragment).split()
        year_positions = [
            index
            for index, token in enumerate(tokens)
            if token in year_tokens
            and index > 0
            and re.fullmatch(r"\d+(?:[.,]\d+)?\+?", tokens[index - 1])
        ]
        experience_positions = [
            index for index, token in enumerate(tokens) if token in experience_tokens
        ]
        qualifier_positions = {
            qualifier: [index for index, token in enumerate(tokens) if token == qualifier]
            for qualifier in relationship_qualifiers
        }
        if not all(qualifier_positions.values()):
            continue
        for year_position in year_positions:
            for experience_position in experience_positions:
                positions = [items[0] for items in qualifier_positions.values()]
                if year_position < min(positions) <= max(positions) < experience_position:
                    if experience_position - year_position <= len(positions) + 4:
                        return True
                if year_position < experience_position < min(positions):
                    between = tokens[experience_position + 1 : min(positions)]
                    if relation_connectors & set(between):
                        return True
    return False


def _matches(requirement: JobRequirement, fact: CareerFact) -> bool:
    needle = normalize(requirement.normalized_value or requirement.text)
    haystack = fact_text(fact)
    if not needle:
        return False
    needle_tokens = needle.split()
    haystack_tokens = haystack.split()
    requirement_numbers = set(re.findall(r"[0-9٠-٩]+(?:[.,][0-9٠-٩]+)?", needle))
    fact_numbers = set(re.findall(r"[0-9٠-٩]+(?:[.,][0-9٠-٩]+)?", haystack))
    if requirement_numbers:
        if requirement.category is RequirementCategory.EXPERIENCE:
            required_years = _year_value(needle)
            fact_years = _year_value(haystack)
            if required_years is None or fact_years is None or fact_years < required_years:
                return False
            generic_experience_tokens = {
                "year",
                "years",
                "yrs",
                "experience",
                "required",
                "minimum",
                "must",
                "سنة",
                "سنوات",
                "خبرة",
                "مطلوب",
                "يشترط",
                "with",
                "using",
                "باستخدام",
            }
            relationship_qualifiers = {
                token
                for token in needle_tokens
                if len(token) >= 3
                and not token[0].isdigit()
                and token not in generic_experience_tokens
            }
            if relationship_qualifiers - set(haystack_tokens):
                return False
            if relationship_qualifiers and not _experience_relationship_supported(
                fact, relationship_qualifiers
            ):
                return False
        elif requirement_numbers != fact_numbers:
            return False

    positions = _sequence_positions(haystack_tokens, needle_tokens)
    if positions:
        return any(
            not _unsafe_attribution(haystack_tokens, position, len(needle_tokens))
            for position in positions
        )

    tokens = [token for token in needle_tokens if len(token) >= 3 and not token[0].isdigit()]
    # Multiword descriptions require meaningful overlap; explicit normalized values usually match
    # exactly above.
    overlap = set(tokens) & set(haystack_tokens)
    if any(
        _unsafe_attribution(haystack_tokens, position, 1)
        for token in overlap
        for position in _sequence_positions(haystack_tokens, [token])
    ):
        return False
    return bool(tokens) and len(overlap) / len(set(tokens)) >= 0.6


def calculate_match(
    requirements: list[JobRequirement],
    confirmed_facts: list[CareerFact],
    complete_categories: set[FactCategory] | None = None,
    requirements_reviewed: bool = True,
) -> dict[str, object]:
    complete_categories = complete_categories or set()
    facts_by_category: dict[FactCategory, list[CareerFact]] = defaultdict(list)
    for fact in confirmed_facts:
        facts_by_category[fact.category].append(fact)

    matches: list[dict[str, object]] = []
    total_weight = earned_weight = 0
    mandatory_total = mandatory_earned = 0
    known_count = mandatory_missing = 0

    for requirement in requirements:
        effective_weight = requirement.weight * (
            2 if requirement.importance is RequirementImportance.MANDATORY else 1
        )
        total_weight += effective_weight
        if requirement.importance is RequirementImportance.MANDATORY:
            mandatory_total += effective_weight

        category_facts = [
            fact
            for category in CATEGORY_FACTS[requirement.category]
            for fact in facts_by_category.get(category, [])
        ]
        evidence = next((fact for fact in category_facts if _matches(requirement, fact)), None)
        if evidence:
            match_status = RequirementMatchStatus.MATCHED
            reason = f"Covered by confirmed fact: {evidence.label}"
            earned = effective_weight
            known_count += 1
            earned_weight += earned
            if requirement.importance is RequirementImportance.MANDATORY:
                mandatory_earned += earned
        elif REQUIREMENT_COMPLETENESS_CATEGORY[requirement.category] in complete_categories:
            match_status = RequirementMatchStatus.MISSING
            reason = (
                "The user marked this profile category complete and it does not cover "
                "the requirement"
            )
            earned = 0
            known_count += 1
            if requirement.importance is RequirementImportance.MANDATORY:
                mandatory_missing += 1
        else:
            match_status = RequirementMatchStatus.UNKNOWN
            reason = (
                "The verified profile has insufficient information, or this category has not "
                "been marked complete"
            )
            earned = 0
        matches.append(
            {
                "requirement": requirement,
                "evidence": evidence,
                "status": match_status,
                "reason": reason,
                "earned_weight": earned,
            }
        )

    requirement_count = len(requirements)
    coverage = round(100 * earned_weight / total_weight) if total_weight else 0
    mandatory_coverage = round(100 * mandatory_earned / mandatory_total) if mandatory_total else 100
    known_ratio = known_count / requirement_count if requirement_count else 0
    unknown_count = requirement_count - known_count
    review_required_count = sum(bool(requirement.needs_user_review) for requirement in requirements)

    if known_ratio >= 0.8:
        confidence = ConfidenceBand.HIGH
    elif known_ratio >= 0.5:
        confidence = ConfidenceBand.MEDIUM
    else:
        confidence = ConfidenceBand.LOW

    if coverage >= 80 and mandatory_coverage >= 80 and mandatory_missing == 0:
        readiness = ReadinessBand.HIGH
    elif coverage >= 55 and mandatory_coverage >= 50:
        readiness = ReadinessBand.MEDIUM
    else:
        readiness = ReadinessBand.LOW

    if (
        requirement_count == 0
        or unknown_count > 0
        or review_required_count
        or not requirements_reviewed
    ):
        decision = ApplyDecision.NEED_INFORMATION
    elif mandatory_missing and mandatory_coverage < 50:
        decision = ApplyDecision.LOW_RETURN
    elif coverage >= 75 and mandatory_coverage >= 80 and mandatory_missing == 0:
        decision = ApplyDecision.APPLY_NOW
    elif coverage >= 40 or mandatory_coverage >= 50:
        decision = ApplyDecision.IMPROVE_THEN_APPLY
    else:
        decision = ApplyDecision.LOW_RETURN

    return {
        "matches": matches,
        "coverage_score": coverage,
        "mandatory_coverage_score": mandatory_coverage,
        "readiness_band": readiness,
        "confidence_band": confidence,
        "decision": decision,
        "explanation": {
            "definition": (
                "Weighted coverage of explicit job requirements, not interview probability"
            ),
            "weighting": "Mandatory requirements count twice; preferred requirements count once",
            "requirement_count": requirement_count,
            "matched_count": sum(
                item["status"] is RequirementMatchStatus.MATCHED for item in matches
            ),
            "missing_count": sum(
                item["status"] is RequirementMatchStatus.MISSING for item in matches
            ),
            "unknown_count": unknown_count,
            "mandatory_missing_count": mandatory_missing,
            "review_required_count": review_required_count,
            "requirements_reviewed": requirements_reviewed,
            "decision_preliminary": not requirements_reviewed,
            "capabilities": {
                "can_edit_requirement": True,
                "can_add_requirement": True,
                "can_retire_requirement": True,
                "can_correct_fact": True,
                "can_override_match": False,
            },
        },
    }
