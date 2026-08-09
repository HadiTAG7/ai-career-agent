from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from career_agent_api.models.domain import CareerFact
from career_agent_api.models.enums import FactCategory, PreferredLanguage, VerificationStatus

ASSESSMENT_VERSION = "resume-assessment.v1"
PAGE_TARGET = 1
_SEGMENT_HANDLE_PATTERN = re.compile(r"(?:^|_)segment_(\d+)$", re.IGNORECASE)

AssessmentVerdict = Literal["needs_information", "ready_with_improvements", "ready"]
GapPriority = Literal["high", "medium", "low"]
ATSCheckStatus = Literal["pass", "warning", "not_assessed"]

SECTION_ORDER: tuple[FactCategory, ...] = (
    FactCategory.EDUCATION,
    FactCategory.EXPERIENCE,
    FactCategory.CERTIFICATION,
    FactCategory.SKILL,
    FactCategory.LANGUAGE,
    FactCategory.PROJECT,
    FactCategory.ACHIEVEMENT,
)


class ResumeAssessmentGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=3, max_length=180)
    category: FactCategory
    requested_fields: list[str] = Field(min_length=1, max_length=8)
    priority: GapPriority
    reason: str = Field(min_length=3, max_length=500)
    record_label: str | None = Field(default=None, max_length=500)
    evidence_handles: list[str] = Field(default_factory=list, max_length=12)


class ResumeATSCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=3, max_length=80)
    status: ATSCheckStatus
    detail: str = Field(min_length=3, max_length=600)
    evidence_handles: list[str] = Field(default_factory=list, max_length=30)


class ResumeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["resume-assessment.v1"] = ASSESSMENT_VERSION
    verdict: AssessmentVerdict
    fact_count: int = Field(ge=0, le=200)
    found_sections: list[FactCategory]
    section_counts: dict[str, int]
    missing_sections: list[FactCategory]
    gaps: list[ResumeAssessmentGap] = Field(max_length=20)
    ats_checks: list[ResumeATSCheck] = Field(max_length=12)
    page_target: Literal[1] = PAGE_TARGET
    disclaimer: str = Field(min_length=20, max_length=500)


def _structured(fact: CareerFact) -> dict[str, Any]:
    return fact.structured_value if isinstance(fact.structured_value, dict) else {}


def _has_text(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_text(item) for item in value)
    return value not in (None, {}, ())


def _first_present(record: Mapping[str, Any], *keys: str) -> bool:
    return any(_has_text(record.get(key)) for key in keys)


def _supplemental_present(record: Mapping[str, Any], field: str) -> bool:
    """Return whether a user-confirmed gap answer supplies one requested field.

    Supplemental details deliberately keep their provenance wrapper instead of pretending the
    uploaded file contained the answer. Older/scalar values are accepted for forward compatibility.
    """

    raw_details = record.get("supplemental_details")
    if not isinstance(raw_details, Mapping):
        return False
    raw_value = raw_details.get(field)
    if isinstance(raw_value, Mapping):
        return _has_text(raw_value.get("value"))
    return _has_text(raw_value)


def _field_present(
    record: Mapping[str, Any],
    requested_field: str,
    *native_keys: str,
) -> bool:
    return _first_present(record, *native_keys) or _supplemental_present(record, requested_field)


def _education_field_present(record: Mapping[str, Any]) -> bool:
    if _field_present(
        record,
        "field",
        "field",
        "field_of_study",
        "major",
        "specialization",
    ):
        return True
    # Some parsers preserve the qualification as one explicit phrase instead of splitting the
    # discipline into a second field (for example, "Bachelor degree in Finance"). Treat the
    # discipline as present only when the phrase itself carries an unambiguous study-field cue.
    for key in ("degree", "qualification", "title"):
        value = str(record.get(key) or "").strip()
        if re.search(r"\b(?:major(?:ed)?\s+in|in)\s+[\w&-]", value, re.IGNORECASE):
            return True
        if re.search(r"(?:^|\s)(?:في|تخصص)\s+[\w\u0600-\u06ff]", value):
            return True
    return False


def _fact_handle(fact: CareerFact, index: int) -> str:
    fact_id = getattr(fact, "id", None)
    return f"fact_{fact_id.hex}" if fact_id is not None else f"fact_{index + 1}"


def _fact_key(fact: CareerFact, index: int) -> str:
    fact_id = getattr(fact, "id", None)
    return fact_id.hex if fact_id is not None else str(index + 1)


def _source_position(fact: CareerFact, fallback_index: int) -> tuple[int, int]:
    """Keep record-specific questions in the order the records appeared in the uploaded CV."""

    record = _structured(fact)
    raw_handles = record.get("source_handles")
    handles = raw_handles if isinstance(raw_handles, list) else []
    positions = [
        int(match.group(1))
        for value in handles
        if (match := _SEGMENT_HANDLE_PATTERN.search(str(value).strip())) is not None
    ]
    return (min(positions), fallback_index) if positions else (1_000_000, fallback_index)


def _gap(
    *,
    key: str,
    category: FactCategory,
    fields: Sequence[str],
    priority: GapPriority,
    reason: str,
    record_label: str | None = None,
    handles: Sequence[str] = (),
) -> ResumeAssessmentGap:
    return ResumeAssessmentGap(
        key=key,
        category=category,
        requested_fields=list(dict.fromkeys(fields)),
        priority=priority,
        reason=reason,
        record_label=record_label,
        evidence_handles=list(dict.fromkeys(handles))[:12],
    )


def _record_gaps(facts: Sequence[CareerFact]) -> list[ResumeAssessmentGap]:
    gaps: list[ResumeAssessmentGap] = []
    weak_skill_handles: list[str] = []
    weak_language_handles: list[str] = []

    for index, fact in enumerate(facts):
        record = _structured(fact)
        handle = _fact_handle(fact, index)
        fact_key = _fact_key(fact, index)
        missing: list[str] = []
        priority: GapPriority = "medium"

        if fact.category is FactCategory.EDUCATION:
            if not _field_present(record, "degree", "degree", "qualification"):
                missing.append("degree")
            if not _education_field_present(record):
                missing.append("field")
            if not _field_present(record, "institution", "institution", "organization"):
                missing.append("institution")
            if not _field_present(
                record,
                "graduation_date",
                "date_range",
                "graduation_date",
                "year",
            ):
                missing.append("graduation_date")
            priority = "high"
        elif fact.category is FactCategory.EXPERIENCE:
            if not _field_present(
                record,
                "organization_or_context",
                "organization",
                "context",
            ):
                missing.append("organization_or_context")
            if not _field_present(record, "date_range", "date_range", "year"):
                missing.append("date_range")
            if not (
                _first_present(record, "responsibilities", "outcomes")
                or _has_text(fact.detail)
                or _supplemental_present(record, "responsibility_or_contribution")
            ):
                missing.append("responsibility_or_contribution")
            priority = "high" if "responsibility_or_contribution" in missing else "medium"
        elif fact.category is FactCategory.PROJECT:
            if not (
                _first_present(record, "responsibilities", "outcomes")
                or _has_text(fact.detail)
                or _supplemental_present(record, "contribution")
            ):
                missing.append("contribution")
            if not _field_present(record, "tools", "tools"):
                missing.append("tools")
            priority = "high" if "contribution" in missing else "medium"
        elif fact.category is FactCategory.CERTIFICATION:
            if not _field_present(record, "issuer", "issuer", "organization"):
                missing.append("issuer")
            if not _field_present(record, "year", "date_range", "year"):
                missing.append("year")
        elif fact.category is FactCategory.SKILL:
            if not (
                _has_text(fact.detail)
                or _first_present(record, "responsibilities", "outcomes", "usage_example")
                or _supplemental_present(record, "usage_context")
                or _supplemental_present(record, "example")
            ):
                weak_skill_handles.append(handle)
        elif fact.category is FactCategory.LANGUAGE:
            if not _field_present(record, "proficiency", "proficiency"):
                weak_language_handles.append(handle)

        if missing:
            gaps.append(
                _gap(
                    key=f"fact:{fact_key}:{'_'.join(missing)}",
                    category=fact.category,
                    fields=missing,
                    priority=priority,
                    reason=(
                        f"The confirmed {fact.category.value} record '{fact.label}' is missing "
                        f"{', '.join(missing)}."
                    ),
                    record_label=fact.label,
                    handles=[handle],
                )
            )

    if weak_skill_handles:
        gaps.append(
            _gap(
                key="section:skill:usage_evidence",
                category=FactCategory.SKILL,
                fields=["usage_context", "example"],
                priority="medium",
                reason="The listed skills need a truthful example of where they were used.",
                handles=weak_skill_handles,
            )
        )
    if weak_language_handles:
        gaps.append(
            _gap(
                key="section:language:proficiency",
                category=FactCategory.LANGUAGE,
                fields=["proficiency"],
                priority="medium",
                reason="The confirmed language records do not state proficiency.",
                handles=weak_language_handles,
            )
        )
    return gaps


def build_resume_assessment(
    facts: Sequence[CareerFact],
    source_metadata: Mapping[str, Any] | None = None,
) -> ResumeAssessment:
    """Build a transparent content-readiness assessment from confirmed source facts only."""

    confirmed_with_index = [
        (index, fact)
        for index, fact in enumerate(facts)
        if fact.verification_status is VerificationStatus.CONFIRMED
        and fact.category in SECTION_ORDER
    ]
    confirmed = [
        fact
        for index, fact in sorted(
            confirmed_with_index,
            key=lambda item: _source_position(item[1], item[0]),
        )
    ]
    counts = Counter(fact.category for fact in confirmed)
    found_sections = [category for category in SECTION_ORDER if counts[category]]
    # Optional sections are useful when the applicant actually has them, but their absence is not
    # an ATS defect. Report only structural gaps that the guided interview can meaningfully fill.
    missing_sections: list[FactCategory] = []
    if not counts[FactCategory.EDUCATION]:
        missing_sections.append(FactCategory.EDUCATION)
    if not counts[FactCategory.EXPERIENCE] and not counts[FactCategory.PROJECT]:
        missing_sections.append(FactCategory.EXPERIENCE)
    if not counts[FactCategory.SKILL]:
        missing_sections.append(FactCategory.SKILL)
    if not counts[FactCategory.LANGUAGE]:
        missing_sections.append(FactCategory.LANGUAGE)
    handles = [_fact_handle(fact, index) for index, fact in enumerate(confirmed)]

    gaps = _record_gaps(confirmed)
    if not counts[FactCategory.EDUCATION]:
        gaps.append(
            _gap(
                key="section:education:core",
                category=FactCategory.EDUCATION,
                fields=["degree", "field", "institution", "graduation_date"],
                priority="high",
                reason="No confirmed education record was found in the reviewed resume.",
            )
        )
    if not counts[FactCategory.EXPERIENCE] and not counts[FactCategory.PROJECT]:
        gaps.append(
            _gap(
                key="section:experience:core",
                category=FactCategory.EXPERIENCE,
                fields=["role_or_project", "context", "contribution", "outcome_or_scope"],
                priority="high",
                reason=(
                    "No confirmed experience or project record was found; beginners may use "
                    "coursework, volunteering, or personal projects."
                ),
            )
        )
    if not counts[FactCategory.SKILL]:
        gaps.append(
            _gap(
                key="section:skill:core",
                category=FactCategory.SKILL,
                fields=["skills", "usage_example"],
                priority="medium",
                reason="No confirmed skills were found in the reviewed resume.",
            )
        )
    if not counts[FactCategory.LANGUAGE]:
        gaps.append(
            _gap(
                key="section:language:core",
                category=FactCategory.LANGUAGE,
                fields=["language", "proficiency"],
                priority="low",
                reason="No confirmed language and proficiency record was found.",
            )
        )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    section_rank = {category: index for index, category in enumerate(SECTION_ORDER)}
    gaps = sorted(
        gaps,
        key=lambda item: (
            section_rank[item.category],
            priority_rank[item.priority],
        ),
    )[:20]

    metadata = dict(source_metadata or {})
    parser = str(metadata.get("parser") or "").strip()
    parseability_status: ATSCheckStatus = "pass" if parser else "not_assessed"
    parseability_detail = (
        f"Professional text was extracted with {parser}."
        if parser
        else "Document parseability was not measured for this source."
    )
    narrative = [
        fact
        for fact in confirmed
        if fact.category in {FactCategory.EXPERIENCE, FactCategory.PROJECT}
    ]
    narrative_with_detail = [
        fact
        for fact in narrative
        if _has_text(fact.detail)
        or _first_present(_structured(fact), "responsibilities", "outcomes")
    ]
    specificity_status: ATSCheckStatus = (
        "not_assessed"
        if not narrative
        else "pass"
        if len(narrative_with_detail) == len(narrative)
        else "warning"
    )
    specificity_detail = (
        "No confirmed experience or project content is available for a specificity check."
        if not narrative
        else (
            "Every confirmed experience or project has a responsibility, contribution, or outcome."
            if specificity_status == "pass"
            else "Some confirmed experience or project records need a clearer contribution."
        )
    )
    core_structure_complete = bool(counts[FactCategory.EDUCATION]) and bool(
        counts[FactCategory.EXPERIENCE] or counts[FactCategory.PROJECT]
    )
    ats_checks = [
        ResumeATSCheck(
            key="confirmed_source_evidence",
            status="pass" if confirmed else "warning",
            detail=(
                f"Assessment uses {len(confirmed)} owner-confirmed facts from this source."
                if confirmed
                else "No owner-confirmed professional facts are available."
            ),
            evidence_handles=handles[:30],
        ),
        ResumeATSCheck(
            key="text_parseability",
            status=parseability_status,
            detail=parseability_detail,
        ),
        ResumeATSCheck(
            key="core_section_structure",
            status="pass" if core_structure_complete else "warning",
            detail=(
                "Education plus experience or project evidence is present."
                if core_structure_complete
                else "Education and at least one experience or project record are recommended."
            ),
            evidence_handles=handles[:30],
        ),
        ResumeATSCheck(
            key="narrative_specificity",
            status=specificity_status,
            detail=specificity_detail,
            evidence_handles=[_fact_handle(fact, confirmed.index(fact)) for fact in narrative][:30],
        ),
        ResumeATSCheck(
            key="visual_formatting",
            status="not_assessed",
            detail=(
                "Columns, graphics, fonts, and final page count are not inferred from extracted "
                "text; the generated PDF must be checked separately."
            ),
        ),
    ]
    if any(gap.priority == "high" for gap in gaps):
        verdict: AssessmentVerdict = "needs_information"
    elif gaps or any(check.status == "warning" for check in ats_checks):
        verdict = "ready_with_improvements"
    else:
        verdict = "ready"

    return ResumeAssessment(
        verdict=verdict,
        fact_count=len(confirmed),
        found_sections=found_sections,
        section_counts={category.value: counts[category] for category in SECTION_ORDER},
        missing_sections=missing_sections,
        gaps=gaps,
        ats_checks=ats_checks,
        disclaimer=(
            "هذا تقييم لاكتمال بنية السيرة وقابلية استخراج النص، وليس احتمال قبول وظيفي "
            "أو ضمانًا لنتيجة أي نظام ATS."
        ),
    )


def deterministic_gap_question(
    gap: ResumeAssessmentGap | Mapping[str, Any],
    language: PreferredLanguage,
) -> dict[str, Any]:
    """Return a safe question when the remote writer cannot phrase the server-selected gap."""

    normalized = (
        gap if isinstance(gap, ResumeAssessmentGap) else ResumeAssessmentGap.model_validate(gap)
    )
    prompts = {
        PreferredLanguage.AR: {
            FactCategory.EDUCATION: (
                "أكمل لي بيانات التعليم الناقصة: ما الدرجة والتخصص والجامعة وتاريخ التخرج؟",
                "هذه التفاصيل تجعل قسم التعليم دقيقًا وقابلًا للقراءة.",
                "اذكر فقط التفاصيل الصحيحة التي تعرفها.",
            ),
            FactCategory.EXPERIENCE: (
                "أكمل هذه التجربة: ما دورك أو سياقها، وماذا أنجزت أو ساهمت فيه؟",
                "الدور والمساهمة الواضحة أقوى من عنوان عام.",
                "اذكر السياق، دورك، والأثر أو نطاق العمل من دون تخمين.",
            ),
            FactCategory.PROJECT: (
                "ما مساهمتك المحددة في المشروع، وما الأدوات أو النتيجة التي تعرفها؟",
                "المساهمة الموثقة تحول المشروع إلى دليل مهني مفيد.",
                "دورك، الأدوات، والنتيجة أو نطاق المشروع.",
            ),
            FactCategory.SKILL: (
                "أين استخدمت هذه المهارة فعليًا، وما المثال الذي يثبتها؟",
                "المهارة المدعومة بمثال أقوى من قائمة كلمات.",
                "المهارة، أين استخدمتها، وماذا فعلت بها.",
            ),
            FactCategory.CERTIFICATION: (
                "ما الجهة المانحة للشهادة ومتى حصلت عليها؟",
                "الجهة والتاريخ يكملان بيانات الشهادة.",
                "اسم الجهة والسنة إن كانا معروفين.",
            ),
            FactCategory.LANGUAGE: (
                "ما اللغة وما مستوى إجادتك الفعلي فيها؟",
                "مستوى واضح يجعل قسم اللغات أدق.",
                "اللغة والمستوى: أساسي، متوسط، متقدم، أو طليق.",
            ),
            FactCategory.ACHIEVEMENT: (
                "ما الإنجاز أو نطاق الأثر الذي تستطيع تأكيده من دون تخمين؟",
                "الوصف الصادق والمحدد أفضل من رقم غير موثوق.",
                "ماذا فعلت، ولمن، وما النتيجة أو النطاق؟",
            ),
        },
        PreferredLanguage.EN: {
            FactCategory.EDUCATION: (
                "Please complete the missing education details: degree, field, institution, "
                "and graduation date.",
                "These details make the education section accurate and readable.",
                "Share only the details you can confirm.",
            ),
            FactCategory.EXPERIENCE: (
                "Please complete this experience: what was your role or context, and what did "
                "you contribute?",
                "A clear role and contribution are stronger than a general heading.",
                "Share the context, your role, and the outcome or scope without guessing.",
            ),
            FactCategory.PROJECT: (
                "What did you contribute to the project, and which tools or outcome can you "
                "confirm?",
                "A supported contribution turns the project into useful professional evidence.",
                "Your role, tools, and the known outcome or scope.",
            ),
            FactCategory.SKILL: (
                "Where did you use this skill, and what example demonstrates it?",
                "A skill backed by an example is stronger than a keyword list.",
                "Skill, where you used it, and what you did with it.",
            ),
            FactCategory.CERTIFICATION: (
                "Who issued the certification, and when did you earn it?",
                "The issuer and date complete the certification record.",
                "Issuer and year, if known.",
            ),
            FactCategory.LANGUAGE: (
                "Which language is this, and what is your actual proficiency?",
                "A clear level makes the language section more accurate.",
                "Language and level: basic, intermediate, advanced, or fluent.",
            ),
            FactCategory.ACHIEVEMENT: (
                "What achievement or scope of impact can you confirm without guessing?",
                "A truthful, specific description is better than an unsupported number.",
                "What you did, for whom, and the outcome or scope.",
            ),
        },
    }
    question, why, placeholder = prompts[language][normalized.category]
    if normalized.record_label:
        question = (
            f"بالنسبة إلى «{normalized.record_label}»: {question}"
            if language is PreferredLanguage.AR
            else f'For "{normalized.record_label}": {question}'
        )
    safe_key = re.sub(r"[^a-z0-9_]+", "_", normalized.key.casefold()).strip("_")
    return {
        "id": f"gap_{safe_key}"[:80],
        "gap_key": normalized.key,
        "category": normalized.category.value,
        "fields_requested": normalized.requested_fields,
        "evidence_handles": normalized.evidence_handles,
        "question": question,
        "why_it_matters": why,
        "placeholder": placeholder,
        "required": normalized.priority == "high",
        "quick_replies": ["no_exact_metric", "show_example", "skip"],
        "generation_source": "deterministic_fallback",
    }
