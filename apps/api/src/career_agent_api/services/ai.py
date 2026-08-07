import re
from dataclasses import dataclass

from career_agent_api.models.enums import RequirementCategory, RequirementImportance


@dataclass(frozen=True, slots=True)
class ExtractedRequirement:
    category: RequirementCategory
    importance: RequirementImportance
    text: str
    normalized_value: str | None
    weight: int = 1
    needs_user_review: bool = False


class DeterministicCareerProvider:
    """Local-only parser. It never performs network I/O or invents missing requirements."""

    _mandatory_cues = (
        "required",
        "must",
        "minimum",
        "يشترط",
        "مطلوب",
        "يجب",
    )
    _preferred_cues = (
        "preferred",
        "nice to have",
        "plus",
        "optional",
        "يفضل",
        "اختياري",
        "ميزة إضافية",
    )
    _negative_requirement_cues = (
        "not required",
        "isn't required",
        "is not mandatory",
        "no requirement",
        "لا يشترط",
        "غير مطلوب",
        "غير مطلوبة",
        "ليس مطلوبا",
        "ليست مطلوبة",
    )
    _category_cues = {
        RequirementCategory.EXPERIENCE: ("experience", "years", "خبرة", "سنوات"),
        RequirementCategory.EDUCATION: ("degree", "bachelor", "diploma", "بكالوريوس", "دبلوم"),
        RequirementCategory.CERTIFICATION: (
            "certificate",
            "certification",
            "certified",
            "credential",
            "شهادة",
            "اعتماد",
            "معتمد",
        ),
        RequirementCategory.LANGUAGE: ("english", "arabic", "language", "الإنجليزية", "العربية"),
        RequirementCategory.ELIGIBILITY: (
            "work authorization",
            "saudi national",
            "eligible",
            "سعودي",
            "أهلية",
        ),
        RequirementCategory.LOCATION: ("riyadh", "jeddah", "remote", "الرياض", "جدة", "عن بعد"),
        RequirementCategory.SKILL: (
            "skill",
            "proficient",
            "knowledge",
            "python",
            "typescript",
            "react",
            "sql",
            "مهارة",
            "إتقان",
        ),
    }
    _atomic_terms: tuple[tuple[RequirementCategory, str, str], ...] = (
        (RequirementCategory.CERTIFICATION, "aws certification", "aws"),
        (RequirementCategory.CERTIFICATION, "aws certified", "aws"),
        (RequirementCategory.CERTIFICATION, "pmp", "pmp"),
        (RequirementCategory.CERTIFICATION, "cissp", "cissp"),
        (RequirementCategory.CERTIFICATION, "scrum master", "scrum master"),
        (RequirementCategory.CERTIFICATION, "شهادة aws", "aws"),
        (RequirementCategory.CERTIFICATION, "شهادة pmp", "pmp"),
        (RequirementCategory.CERTIFICATION, "اعتماد مهني", "اعتماد مهني"),
        (RequirementCategory.EDUCATION, "bachelor's", "bachelor"),
        (RequirementCategory.EDUCATION, "bachelor", "bachelor"),
        (RequirementCategory.EDUCATION, "بكالوريوس", "بكالوريوس"),
        (RequirementCategory.EDUCATION, "diploma", "diploma"),
        (RequirementCategory.EDUCATION, "دبلوم", "دبلوم"),
        (RequirementCategory.ELIGIBILITY, "saudi national", "saudi national"),
        (RequirementCategory.ELIGIBILITY, "سعودي", "سعودي"),
        (RequirementCategory.LOCATION, "riyadh", "riyadh"),
        (RequirementCategory.LOCATION, "الرياض", "الرياض"),
        (RequirementCategory.LOCATION, "jeddah", "jeddah"),
        (RequirementCategory.LOCATION, "جدة", "جدة"),
        (RequirementCategory.LOCATION, "remote", "remote"),
        (RequirementCategory.LOCATION, "عن بعد", "عن بعد"),
        (RequirementCategory.LANGUAGE, "english", "english"),
        (RequirementCategory.LANGUAGE, "الإنجليزية", "الإنجليزية"),
        (RequirementCategory.LANGUAGE, "arabic", "arabic"),
        (RequirementCategory.LANGUAGE, "العربية", "العربية"),
        (RequirementCategory.SKILL, "typescript", "typescript"),
        (RequirementCategory.SKILL, "javascript", "javascript"),
        (RequirementCategory.SKILL, "next.js", "next.js"),
        (RequirementCategory.SKILL, "python", "python"),
        (RequirementCategory.SKILL, "react", "react"),
        (RequirementCategory.SKILL, "figma", "figma"),
        (RequirementCategory.SKILL, "sql", "sql"),
    )

    def extract_requirements(self, description: str) -> list[ExtractedRequirement]:
        # Sentence boundaries are intentionally conservative; every returned string is a verbatim
        # segment of user-supplied content.
        initial_segments = [
            part.strip(" \t-*•") for part in re.split(r"[\r\n]+|(?<=[.!؟])\s+", description)
        ]
        segments: list[str] = []
        for initial in initial_segments:
            adversative_clauses = [
                part.strip()
                for part in re.split(
                    r"\s+(?:but|however|لكن|ولكن)\s+",
                    initial,
                    flags=re.IGNORECASE,
                )
                if part.strip()
            ]
            semicolon_clauses = [
                part.strip()
                for adversative in adversative_clauses
                for part in re.split(r"[;؛]", adversative)
                if part.strip()
            ]
            for clause in semicolon_clauses:
                comma_clauses = [part.strip() for part in re.split(r"[,،]", clause) if part.strip()]
                if len(comma_clauses) > 1 and all(
                    self._importance_for(part.casefold()) is not None for part in comma_clauses
                ):
                    segments.extend(comma_clauses)
                else:
                    conjunction_clauses = [
                        part.strip()
                        for part in re.split(r"\s+(?:and|و)\s+", clause, flags=re.IGNORECASE)
                        if part.strip()
                    ]
                    if len(conjunction_clauses) > 1 and all(
                        self._importance_for(part.casefold()) is not None
                        for part in conjunction_clauses
                    ):
                        segments.extend(conjunction_clauses)
                    else:
                        segments.append(clause)
        results: list[ExtractedRequirement] = []
        for segment in segments:
            if len(segment) < 3:
                continue
            lowered = segment.casefold()
            # Negated requirements are not requirements. Skipping the whole segment is the
            # conservative choice when a sentence mixes a negation with another clause.
            if any(cue in lowered for cue in self._negative_requirement_cues):
                continue
            importance = self._importance_for(lowered)
            atomic_hints = self._relational_hints(segment) or self._atomic_hints(segment)
            needs_user_review = importance is None
            if not atomic_hints:
                category = RequirementCategory.OTHER
                for candidate, cues in self._category_cues.items():
                    if any(cue in lowered for cue in cues):
                        category = candidate
                        break
                if importance is None and category is RequirementCategory.OTHER:
                    continue
                normalized = None if category is RequirementCategory.OTHER else segment[:500]
                atomic_hints = [(category, normalized)]
            if importance is None:
                # The text contains a concrete requirement-like term but does not state whether it
                # is mandatory or preferred. Preserve it, mark the placeholder importance for
                # review, and make the downstream decision fail closed until the user corrects it.
                importance = RequirementImportance.PREFERRED
            for category, normalized_value in atomic_hints:
                results.append(
                    ExtractedRequirement(
                        category=category,
                        importance=importance,
                        text=segment,
                        normalized_value=normalized_value,
                        needs_user_review=needs_user_review,
                    )
                )
        return results

    @classmethod
    def _relational_hints(cls, text: str) -> list[tuple[RequirementCategory, str]]:
        lowered = text.casefold()
        patterns = (
            (
                RequirementCategory.EXPERIENCE,
                r"\b\d+(?:[.,]\d+)?\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?"
                r"[\w.+#-]+\s+experience\b",
            ),
            (
                RequirementCategory.EXPERIENCE,
                r"\b\d+(?:[.,]\d+)?\s*\+?\s*(?:years?|yrs?)\s+experience\s+"
                r"(?:in|with)\s+[\w.+#-]+\b",
            ),
            (
                RequirementCategory.EDUCATION,
                r"\b(?:bachelor(?:'s)?(?:\s+degree)?|diploma|degree)\s+"
                r"(?:in|of)\s+[\w.+#-]+(?:\s+[\w.+#-]+){0,3}",
            ),
            (
                RequirementCategory.LANGUAGE,
                r"\b(?:fluent|proficient)\s+(?:in\s+)?(?:english|arabic)\b",
            ),
            (
                RequirementCategory.EXPERIENCE,
                r"[0-9٠-٩]+\s*سن(?:ة|وات)\s+خبرة\s+(?:في|باستخدام)\s+[\w.+#-]+",
            ),
            (
                RequirementCategory.LANGUAGE,
                r"(?:إتقان|طلاقة)\s+(?:في\s+)?(?:العربية|الإنجليزية)",
            ),
        )
        for category, pattern in patterns:
            if match := re.search(pattern, lowered, flags=re.IGNORECASE):
                return [(category, match.group(0))]
        return []

    @classmethod
    def _importance_for(cls, lowered: str) -> RequirementImportance | None:
        if any(cue in lowered for cue in cls._mandatory_cues):
            return RequirementImportance.MANDATORY
        if any(cue in lowered for cue in cls._preferred_cues):
            return RequirementImportance.PREFERRED
        return None

    @classmethod
    def _atomic_hints(cls, text: str) -> list[tuple[RequirementCategory, str]]:
        lowered = text.casefold()
        hints: list[tuple[RequirementCategory, str]] = []
        seen: set[tuple[RequirementCategory, str]] = set()
        for category, phrase, canonical in cls._atomic_terms:
            item = (category, canonical)
            if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered) and item not in seen:
                seen.add(item)
                hints.append(item)
        experience = re.search(
            r"\b\d+(?:[.,]\d+)?\s*(?:\+\s*)?(?:years?|yrs?)\b|[0-9٠-٩]+\s*سن(?:ة|وات)",
            lowered,
        )
        if experience:
            hints.append((RequirementCategory.EXPERIENCE, experience.group(0)))
        return hints


def get_ai_provider() -> DeterministicCareerProvider:
    return DeterministicCareerProvider()
