import re
from hashlib import sha256
from json import dumps
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from career_agent_api.models.domain import CareerFact, ClaimEvidence, DocumentClaim, DocumentVersion
from career_agent_api.models.enums import (
    ClaimType,
    DocumentStatus,
    FactCategory,
    VerificationStatus,
)
from career_agent_api.schemas.api import DocumentCreate

CLAIM_FACT_CATEGORIES: dict[ClaimType, set[FactCategory]] = {
    ClaimType.IDENTITY: {FactCategory.IDENTITY},
    ClaimType.EXPERIENCE: {FactCategory.EXPERIENCE},
    ClaimType.EDUCATION: {FactCategory.EDUCATION},
    ClaimType.SKILL: {
        FactCategory.SKILL,
        FactCategory.EXPERIENCE,
        FactCategory.PROJECT,
        FactCategory.CERTIFICATION,
    },
    ClaimType.ACHIEVEMENT: {
        FactCategory.ACHIEVEMENT,
        FactCategory.EXPERIENCE,
        FactCategory.PROJECT,
    },
    ClaimType.PROJECT: {FactCategory.PROJECT},
    ClaimType.CERTIFICATION: {FactCategory.CERTIFICATION},
    ClaimType.LANGUAGE: {FactCategory.LANGUAGE},
    ClaimType.PREFERENCE: {FactCategory.PREFERENCE, FactCategory.ELIGIBILITY},
}

# These units are intentionally narrow. Non-factual copy is rendered only from an exact,
# server-owned allowlist so a caller cannot hide a career assertion behind a semantic label such
# as ``transition`` or ``intent``. Names, employers, role titles, and signatures remain factual
# claims and therefore require evidence.
NON_FACTUAL_TEMPLATES: dict[ClaimType, set[str]] = {
    ClaimType.SALUTATION: {
        "dear hiring team",
        "kind regards",
        "sincerely",
        "السادة فريق التوظيف",
        "مع التحية",
        "وتفضلوا بقبول التحية",
    },
    ClaimType.INTENT: {
        "i am applying for this role",
        "i would welcome the opportunity to discuss my application",
        "أتقدم لهذه الوظيفة",
        "يسعدني مناقشة طلبي",
    },
    ClaimType.TRANSITION: {
        "summary",
        "professional summary",
        "experience",
        "education",
        "skills",
        "projects",
        "certifications",
        "languages",
        "achievements",
        "الملخص",
        "الملخص المهني",
        "الخبرة",
        "التعليم",
        "المهارات",
        "المشاريع",
        "الشهادات",
        "اللغات",
        "الإنجازات",
    },
}

# Grammar-only words may be introduced while preserving meaning. Qualifiers, verbs, negation,
# seniority, quantities, and impact terms are deliberately not ignored.
GLUE_TOKENS = {
    "a",
    "an",
    "the",
}


def _normalized_template(value: str) -> str:
    return " ".join(
        token
        for raw_token in re.findall(r"[\w.+#-]+", value.casefold(), flags=re.UNICODE)
        if (token := raw_token.strip(".-"))
    )


def _material_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for raw_token in re.findall(r"[\w.+#-]+", value.casefold(), flags=re.UNICODE)
        if (token := raw_token.strip(".-"))
        if token not in GLUE_TOKENS
    )


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"[0-9\u0660-\u0669]+(?:[.,][0-9\u0660-\u0669]+)?%?", value))


def unsupported_reason(
    claim_type: ClaimType,
    claim_text: str,
    facts: list[CareerFact],
    profile_id: UUID,
) -> str | None:
    if not claim_type.is_factual:
        if facts:
            return "Non-factual template must not carry evidence links"
        if _normalized_template(claim_text) not in NON_FACTUAL_TEMPLATES[claim_type]:
            return "Non-factual text is not an approved server template"
        return None
    if not facts:
        return "Factual claim has no evidence"
    # Deliberately identical to the missing-fact message: a caller must not be able to
    # distinguish a nonexistent fact UUID from another profile's fact.
    if any(fact.profile_id != profile_id for fact in facts):
        return "Evidence not found"
    if any(fact.verification_status is not VerificationStatus.CONFIRMED for fact in facts):
        return "Evidence is not user-confirmed"
    allowed_categories = CLAIM_FACT_CATEGORIES[claim_type]
    if any(fact.category not in allowed_categories for fact in facts):
        return "Evidence category does not support this claim type"
    evidence_fragments: list[str] = []
    for fact in facts:
        evidence_fragments.extend(
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
        )
        # A correction preserves the source excerpt as immutable provenance, not as a current
        # assertion. Only the user-reviewed corrected fields may ground new output afterward.
        if fact.user_corrected_at is None and fact.source_excerpt:
            evidence_fragments.append(fact.source_excerpt)
    evidence_text = " ".join(evidence_fragments)
    unsupported_numbers = _numbers(claim_text) - _numbers(evidence_text)
    if unsupported_numbers:
        return (
            f"Claim contains numbers absent from evidence: {', '.join(sorted(unsupported_numbers))}"
        )
    claim_tokens = _material_tokens(claim_text)
    if not claim_tokens:
        return "Factual claim has no material content"
    # A single atomic fact must cover the complete claim. Combining words from unrelated facts can
    # otherwise manufacture a relationship (for example, attributing an outcome to a skill).
    if not any(_material_tokens(fragment) == claim_tokens for fragment in evidence_fragments):
        return (
            "Claim wording is not fully grounded: material tokens must be atomically equal "
            "to one confirmed evidence fragment"
        )
    return None


async def create_evidence_safe_document(
    session: AsyncSession, payload: DocumentCreate
) -> DocumentVersion:
    requested_fact_ids = {
        fact_id for claim in payload.claims for fact_id in claim.evidence_fact_ids
    }
    # Scope the lookup to the requesting profile so another profile's facts surface exactly
    # like nonexistent ones ("Evidence not found"), never as a distinguishable error.
    facts = (
        list(
            (
                await session.scalars(
                    select(CareerFact).where(
                        CareerFact.id.in_(requested_fact_ids),
                        CareerFact.profile_id == payload.profile_id,
                    )
                )
            ).all()
        )
        if requested_fact_ids
        else []
    )
    facts_by_id = {fact.id: fact for fact in facts}

    validation_errors: list[dict[str, object]] = []
    for position, claim in enumerate(payload.claims):
        claim_facts: list[CareerFact] = []
        missing_ids: list[UUID] = []
        for fact_id in claim.evidence_fact_ids:
            fact = facts_by_id.get(fact_id)
            if fact is None:
                missing_ids.append(fact_id)
            else:
                claim_facts.append(fact)
        if missing_ids:
            validation_errors.append(
                {
                    "position": position,
                    "fact_ids": [str(fact_id) for fact_id in missing_ids],
                    "reason": "Evidence not found",
                }
            )
            continue
        reason = unsupported_reason(claim.claim_type, claim.text, claim_facts, payload.profile_id)
        if reason:
            validation_errors.append({"position": position, "reason": reason})

    if validation_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "unsupported_claims", "claims": validation_errors},
        )

    # The server renders persisted content exclusively from audited claim units. This prevents a
    # caller from hiding an unannotated factual sentence in an arbitrary content field.
    rendered_content = "\n".join(claim.text.strip() for claim in payload.claims)
    document = DocumentVersion(
        profile_id=payload.profile_id,
        job_id=payload.job_id,
        base_version_id=payload.base_version_id,
        kind=payload.kind,
        language=payload.language,
        title=payload.title,
        # Status is server-owned. A client can request a later state for compatibility, but a new
        # version always starts as a draft and must pass the explicit review transition.
        status=DocumentStatus.DRAFT,
        content=rendered_content,
        diff_summary=payload.diff_summary,
    )
    session.add(document)
    await session.flush()
    for position, claim_input in enumerate(payload.claims):
        claim = DocumentClaim(
            document_id=document.id,
            claim_type=claim_input.claim_type,
            text=claim_input.text.strip(),
            position=position,
            supported=True,
        )
        session.add(claim)
        await session.flush()
        for fact_id in claim_input.evidence_fact_ids:
            session.add(ClaimEvidence(claim_id=claim.id, fact_id=fact_id))
    await session.flush()
    return await load_document(session, document.id)


async def load_document(session: AsyncSession, document_id: UUID) -> DocumentVersion | None:
    return await session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.id == document_id)
        .options(selectinload(DocumentVersion.claims).selectinload(DocumentClaim.evidence_links))
    )


async def validate_document(session: AsyncSession, document: DocumentVersion) -> list[UUID]:
    fact_ids = [link.fact_id for claim in document.claims for link in claim.evidence_links]
    facts_by_id = {}
    if fact_ids:
        facts = (await session.scalars(select(CareerFact).where(CareerFact.id.in_(fact_ids)))).all()
        facts_by_id = {fact.id: fact for fact in facts}

    unsupported: list[UUID] = []
    for claim in document.claims:
        linked_facts = [facts_by_id.get(link.fact_id) for link in claim.evidence_links]
        if any(fact is None for fact in linked_facts) or unsupported_reason(
            claim.claim_type,
            claim.text,
            [fact for fact in linked_facts if fact is not None],
            document.profile_id,
        ):
            unsupported.append(claim.id)
    return unsupported


def document_review_hash(document: DocumentVersion) -> str:
    """Hash the immutable review surface, including claim-to-evidence assignments."""

    payload = {
        "profile_id": str(document.profile_id),
        "job_id": str(document.job_id) if document.job_id else None,
        "base_version_id": str(document.base_version_id) if document.base_version_id else None,
        "kind": document.kind.value,
        "language": document.language.value,
        "title": document.title,
        "content": document.content,
        "claims": [
            {
                "position": claim.position,
                "type": claim.claim_type.value,
                "text": claim.text,
                "fact_ids": sorted(str(link.fact_id) for link in claim.evidence_links),
            }
            for claim in sorted(document.claims, key=lambda item: item.position)
        ],
    }
    canonical = dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def has_current_review(document: DocumentVersion) -> bool:
    return (
        document.status is DocumentStatus.EXPORT_READY
        and document.reviewed_at is not None
        and bool(document.reviewed_by_owner_id)
        and document.review_hash == document_review_hash(document)
    )
