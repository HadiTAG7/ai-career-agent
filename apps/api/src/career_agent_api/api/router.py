from datetime import UTC, datetime
from hashlib import sha256
from json import dumps
from typing import Any
from unicodedata import normalize
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from career_agent_api.api.career_path import router as career_path_router
from career_agent_api.core.auth import CurrentUser
from career_agent_api.core.config import Settings, get_settings
from career_agent_api.db.session import get_db
from career_agent_api.models.domain import (
    Application,
    CareerFact,
    CareerPathConversation,
    CareerPathMessage,
    CareerProfile,
    ClaimEvidence,
    DeletionReceipt,
    DocumentClaim,
    DocumentVersion,
    EvidenceSource,
    Job,
    JobRequirement,
    MatchAnalysis,
    Outcome,
    RequirementMatch,
    SourcePolicy,
)
from career_agent_api.models.enums import (
    ApplicationStatus,
    DocumentKind,
    DocumentStatus,
    FactCategory,
    IntakeMethod,
    OutcomeKind,
    SourceKind,
    VerificationStatus,
)
from career_agent_api.schemas.api import (
    AnalyzeJobRequest,
    ApplicationCreate,
    ApplicationRead,
    ApplicationUpdate,
    CareerFactCreate,
    CareerFactRead,
    CareerFactUpdate,
    CareerPathConversationRead,
    CareerPathMessageRead,
    CareerProfileCreate,
    CareerProfileRead,
    CareerProfileSummaryRead,
    CareerProfileUpdate,
    DashboardRead,
    DeletionReceiptRead,
    DocumentCreate,
    DocumentRead,
    DocumentValidationRead,
    EvidenceSourceCreate,
    EvidenceSourceRead,
    ImportResultRead,
    JobRead,
    JobRequirementRead,
    JobRequirementRetire,
    JobRequirementUpdate,
    JobRequirementUserCreate,
    ManualJobCreate,
    MatchAnalysisRead,
    OutcomeCreate,
    OutcomeRead,
    ResumeNarrativeCreate,
    SourcePolicyRead,
)
from career_agent_api.services.ai import get_ai_provider
from career_agent_api.services.documents import (
    create_evidence_safe_document,
    document_review_hash,
    has_current_review,
    validate_document,
)
from career_agent_api.services.imports import (
    FactCandidate,
    metadata_for_import,
    parse_import,
    read_limited_upload,
)
from career_agent_api.services.matching import calculate_match
from career_agent_api.services.policies import (
    get_or_create_deny_by_default_policy,
    source_key_for_url,
)
from career_agent_api.services.resume_intake import (
    ResumeIntakeProvider,
    ResumeIntakeProviderContext,
    ResumeIntakeProviderError,
    build_resume_segments,
    get_resume_intake_provider,
)

router = APIRouter(prefix="/v1")
router.include_router(career_path_router)

POST_SUBMISSION_STATUSES = {
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.REJECTED,
    ApplicationStatus.OFFER,
}
POST_SUBMISSION_OUTCOMES = {
    OutcomeKind.SCREENING,
    OutcomeKind.INTERVIEW,
    OutcomeKind.REJECTION,
    OutcomeKind.OFFER,
}
PROFILE_QUALITY_CATEGORIES = frozenset(
    {
        FactCategory.EDUCATION,
        FactCategory.EXPERIENCE,
        FactCategory.SKILL,
        FactCategory.PROJECT,
        FactCategory.LANGUAGE,
        FactCategory.CERTIFICATION,
    }
)
RESUME_AI_CONSENT_VERSION = "2026-08-07-v1"


def _resume_ai_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "request_id": str(uuid4())},
    )


def _resume_ai_provider(
    settings: Settings, *, data_sharing_acknowledged: bool
) -> ResumeIntakeProvider:
    if not data_sharing_acknowledged:
        raise _resume_ai_error(
            status.HTTP_400_BAD_REQUEST,
            "resume_ai_consent_required",
            "Acknowledge sending the resume content to the AI provider before continuing",
        )
    provider = get_resume_intake_provider(settings)
    if not provider.available:
        raise _resume_ai_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_ai_not_configured",
            "The AI resume assistant is not configured on the server",
        )
    return provider


def _resume_ai_consent_version(provider: ResumeIntakeProvider) -> str:
    return f"{RESUME_AI_CONSENT_VERSION}:{provider.provider_name}"


async def _evidence_source_for_content(
    session: AsyncSession,
    profile_id: UUID,
    content_sha256: str,
) -> EvidenceSource | None:
    sources = list(
        (
            await session.scalars(
                select(EvidenceSource)
                .where(EvidenceSource.profile_id == profile_id)
                .order_by(EvidenceSource.created_at)
            )
        ).all()
    )
    return next(
        (
            source
            for source in sources
            if source.source_metadata.get("content_sha256") == content_sha256
        ),
        None,
    )


async def _ensure_unique_evidence_content(
    session: AsyncSession,
    profile_id: UUID,
    content_sha256: str,
    *,
    detail: str,
) -> None:
    if await _evidence_source_for_content(session, profile_id, content_sha256):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _normalized_resume_fact_match(value: str | None) -> str:
    return " ".join(normalize("NFKC", value or "").casefold().split())


def _matching_source_fact(
    candidate: FactCandidate,
    facts: list[CareerFact],
    matched_fact_ids: set[UUID],
) -> CareerFact | None:
    category_matches = [
        fact
        for fact in facts
        if fact.id not in matched_fact_ids and fact.category == candidate.category
    ]
    candidate_excerpt = _normalized_resume_fact_match(candidate.source_excerpt)
    excerpt_matches = [
        fact
        for fact in category_matches
        if candidate_excerpt
        and _normalized_resume_fact_match(fact.source_excerpt) == candidate_excerpt
    ]
    candidate_label = _normalized_resume_fact_match(candidate.label)
    for fact in excerpt_matches:
        if _normalized_resume_fact_match(fact.label) == candidate_label:
            return fact
    if len(excerpt_matches) == 1:
        return excerpt_matches[0]
    return next(
        (
            fact
            for fact in category_matches
            if candidate_label and _normalized_resume_fact_match(fact.label) == candidate_label
        ),
        None,
    )


async def _guard_resume_ai_snapshot(
    session: AsyncSession,
    profile: CareerProfile,
    owner_id: str,
    evidence_revision: int,
) -> None:
    guard = await session.execute(
        update(CareerProfile)
        .where(
            CareerProfile.id == profile.id,
            CareerProfile.owner_id == owner_id,
            CareerProfile.evidence_revision == evidence_revision,
            CareerProfile.deletion_started_at.is_(None),
        )
        .values(evidence_revision=CareerProfile.evidence_revision)
    )
    if guard.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile evidence changed while the resume was being analyzed; retry",
        )


def _career_profile_summary(
    profile_id: UUID, facts: list[CareerFact]
) -> CareerProfileSummaryRead:
    confirmed = [
        fact for fact in facts if fact.verification_status is VerificationStatus.CONFIRMED
    ]
    covered_categories = sorted(
        {fact.category for fact in confirmed} & PROFILE_QUALITY_CATEGORIES,
        key=lambda category: category.value,
    )
    return CareerProfileSummaryRead(
        profile_id=profile_id,
        profile_quality_percent=round(
            100 * len(covered_categories) / len(PROFILE_QUALITY_CATEGORIES)
        ),
        confirmed_facts=len(confirmed),
        total_facts=len(facts),
        extracted_facts=sum(
            fact.verification_status is VerificationStatus.EXTRACTED for fact in facts
        ),
        unconfirmed_facts=sum(
            fact.verification_status is VerificationStatus.UNCONFIRMED for fact in facts
        ),
        covered_quality_categories=covered_categories,
        total_quality_categories=len(PROFILE_QUALITY_CATEGORIES),
    )


async def _owned_profile(session: AsyncSession, profile_id: UUID, owner_id: str) -> CareerProfile:
    profile = await session.scalar(
        select(CareerProfile).where(
            CareerProfile.id == profile_id, CareerProfile.owner_id == owner_id
        )
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


async def _current_profile(session: AsyncSession, owner_id: str) -> CareerProfile:
    profile = await session.scalar(select(CareerProfile).where(CareerProfile.owner_id == owner_id))
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


async def _maybe_current_profile(session: AsyncSession, owner_id: str) -> CareerProfile | None:
    return await session.scalar(select(CareerProfile).where(CareerProfile.owner_id == owner_id))


async def _owned_job(session: AsyncSession, job_id: UUID, owner_id: str) -> Job:
    job = await session.scalar(
        select(Job)
        .where(Job.id == job_id, Job.owner_id == owner_id)
        .options(selectinload(Job.source_policy), selectinload(Job.requirements))
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


async def _owned_requirement(
    session: AsyncSession, job_id: UUID, requirement_id: UUID, owner_id: str
) -> JobRequirement:
    await _owned_job(session, job_id, owner_id)
    requirement = await session.scalar(
        select(JobRequirement).where(
            JobRequirement.id == requirement_id, JobRequirement.job_id == job_id
        )
    )
    if not requirement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
    return requirement


async def _invalidate_profile_analyses(
    session: AsyncSession, profile_id: UUID, reason: str
) -> None:
    revision_update = await session.execute(
        update(CareerProfile)
        .where(
            CareerProfile.id == profile_id,
            CareerProfile.deletion_started_at.is_(None),
        )
        .values(evidence_revision=CareerProfile.evidence_revision + 1)
    )
    if revision_update.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile evidence changed or deletion is in progress",
        )
    await session.execute(
        update(MatchAnalysis)
        .where(
            MatchAnalysis.profile_id == profile_id,
            MatchAnalysis.invalidated_at.is_(None),
        )
        .values(invalidated_at=datetime.now(UTC), invalidation_reason=reason[:500])
    )


async def _invalidate_job_analyses(session: AsyncSession, job_id: UUID, reason: str) -> None:
    revision_update = await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(requirements_revision=Job.requirements_revision + 1)
    )
    if revision_update.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job requirements changed concurrently",
        )
    await session.execute(
        update(MatchAnalysis)
        .where(MatchAnalysis.job_id == job_id, MatchAnalysis.invalidated_at.is_(None))
        .values(invalidated_at=datetime.now(UTC), invalidation_reason=reason[:500])
    )


async def _guard_profile_mutation(session: AsyncSession, profile_id: UUID, owner_id: str) -> None:
    guard = await session.execute(
        update(CareerProfile)
        .where(
            CareerProfile.id == profile_id,
            CareerProfile.owner_id == owner_id,
            CareerProfile.deletion_started_at.is_(None),
        )
        .values(evidence_revision=CareerProfile.evidence_revision)
    )
    if guard.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile mutation rejected because deletion is in progress",
        )


async def _guard_current_profile_mutation(session: AsyncSession, owner_id: str) -> CareerProfile:
    profile = await _current_profile(session, owner_id)
    await _guard_profile_mutation(session, profile.id, owner_id)
    return profile


async def _guard_analysis_snapshot(
    session: AsyncSession,
    profile: CareerProfile,
    job: Job,
    evidence_revision: int,
    requirements_revision: int,
) -> None:
    profile_guard = await session.execute(
        update(CareerProfile)
        .where(
            CareerProfile.id == profile.id,
            CareerProfile.owner_id == profile.owner_id,
            CareerProfile.evidence_revision == evidence_revision,
            CareerProfile.deletion_started_at.is_(None),
        )
        .values(evidence_revision=CareerProfile.evidence_revision)
    )
    if profile_guard.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence changed while the analysis was being created; retry",
        )
    job_guard = await session.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.owner_id == job.owner_id,
            Job.requirements_revision == requirements_revision,
        )
        .values(requirements_revision=Job.requirements_revision)
    )
    if job_guard.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Requirements changed while the analysis was being created; retry",
        )


async def _guard_document_review_snapshot(
    session: AsyncSession,
    document: DocumentVersion,
    profile: CareerProfile,
    evidence_revision: int,
) -> None:
    # All mutations lock the profile first, then their child rows. This shared order avoids a
    # deletion/retraction/review deadlock and makes the final writer's state deterministic.
    profile_guard = await session.execute(
        update(CareerProfile)
        .where(
            CareerProfile.id == profile.id,
            CareerProfile.owner_id == profile.owner_id,
            CareerProfile.evidence_revision == evidence_revision,
            CareerProfile.deletion_started_at.is_(None),
        )
        .values(evidence_revision=CareerProfile.evidence_revision)
    )
    if profile_guard.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence changed while the document was being reviewed; retry",
        )
    document_guard = await session.execute(
        update(DocumentVersion)
        .where(
            DocumentVersion.id == document.id,
            DocumentVersion.status == DocumentStatus.DRAFT,
        )
        .values(status=DocumentStatus.DRAFT)
    )
    if document_guard.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document state changed while it was being reviewed; retry",
        )


def _requirements_review_hash(requirements: list[JobRequirement]) -> str:
    payload = [
        {
            "id": str(requirement.id),
            "category": requirement.category.value,
            "importance": requirement.importance.value,
            "text": requirement.text,
            "normalized_value": requirement.normalized_value,
            "weight": requirement.weight,
        }
        for requirement in sorted(requirements, key=lambda item: str(item.id))
        if requirement.is_active
    ]
    return sha256(
        dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _requirements_review_is_current(job: Job) -> bool:
    return (
        job.requirements_reviewed_at is not None
        and bool(job.requirements_reviewed_by_owner_id)
        and job.requirements_review_hash == _requirements_review_hash(list(job.requirements))
    )


def _clear_requirements_review(job: Job) -> None:
    job.requirements_reviewed_at = None
    job.requirements_reviewed_by_owner_id = None
    job.requirements_review_hash = None


async def _owned_document(
    session: AsyncSession, document_id: UUID, owner_id: str
) -> DocumentVersion:
    document = await session.scalar(
        select(DocumentVersion)
        .join(CareerProfile, CareerProfile.id == DocumentVersion.profile_id)
        .where(DocumentVersion.id == document_id, CareerProfile.owner_id == owner_id)
        .options(selectinload(DocumentVersion.claims).selectinload(DocumentClaim.evidence_links))
    )
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


async def _owned_application(
    session: AsyncSession, application_id: UUID, owner_id: str
) -> Application:
    application = await session.scalar(
        select(Application)
        .join(CareerProfile, CareerProfile.id == Application.profile_id)
        .where(Application.id == application_id, CareerProfile.owner_id == owner_id)
        .options(selectinload(Application.outcomes))
    )
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@router.post("/profiles", response_model=CareerProfileRead, status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: CareerProfileCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> CareerProfile:
    if await session.scalar(select(CareerProfile.id).where(CareerProfile.owner_id == user.id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists")
    profile = CareerProfile(owner_id=user.id, **payload.model_dump())
    session.add(profile)
    await session.flush()
    source = EvidenceSource(
        profile_id=profile.id,
        kind=SourceKind.MANUAL,
        label="User-confirmed manual entries",
        source_metadata={"created_by": "profile_onboarding"},
    )
    session.add(source)
    await session.flush()
    session.add(
        CareerFact(
            profile_id=profile.id,
            source_id=source.id,
            category=FactCategory.IDENTITY,
            label=payload.full_name,
            structured_value={
                "profile_field": "full_name",
                "full_name": payload.full_name,
            },
            source_excerpt=payload.full_name,
            verification_status=VerificationStatus.CONFIRMED,
            extraction_confidence=1.0,
            confirmed_at=datetime.now(UTC),
        )
    )
    if payload.city:
        session.add(
            CareerFact(
                profile_id=profile.id,
                source_id=source.id,
                category=FactCategory.PREFERENCE,
                label=payload.city,
                structured_value={"profile_field": "city", "city": payload.city},
                source_excerpt=payload.city,
                verification_status=VerificationStatus.CONFIRMED,
                extraction_confidence=1.0,
                confirmed_at=datetime.now(UTC),
            )
        )
    if payload.years_experience is not None:
        years_label = f"{payload.years_experience:g} years experience"
        session.add(
            CareerFact(
                profile_id=profile.id,
                source_id=source.id,
                category=FactCategory.EXPERIENCE,
                label=years_label,
                structured_value={
                    "profile_field": "years_experience",
                    "years_experience": payload.years_experience,
                },
                source_excerpt=years_label,
                verification_status=VerificationStatus.CONFIRMED,
                extraction_confidence=1.0,
                confirmed_at=datetime.now(UTC),
            )
        )
    await session.commit()
    await session.refresh(profile)
    return profile


@router.get("/profiles", response_model=CareerProfileRead)
async def get_profile(user: CurrentUser, session: AsyncSession = Depends(get_db)) -> CareerProfile:
    return await _current_profile(session, user.id)


@router.get(
    "/profiles/{profile_id}/summary",
    response_model=CareerProfileSummaryRead,
)
async def get_profile_summary(
    profile_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> CareerProfileSummaryRead:
    await _owned_profile(session, profile_id, user.id)
    facts = list(
        (
            await session.scalars(
                select(CareerFact).where(CareerFact.profile_id == profile_id)
            )
        ).all()
    )
    return _career_profile_summary(profile_id, facts)


@router.patch("/profiles", response_model=CareerProfileRead)
async def update_profile(
    payload: CareerProfileUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> CareerProfile:
    profile = await _current_profile(session, user.id)
    requested_changes = payload.model_dump(exclude_unset=True)
    changes = {
        key: value
        for key, value in requested_changes.items()
        if getattr(profile, key) != value
    }
    if not changes:
        return profile
    await _guard_profile_mutation(session, profile.id, user.id)
    for key, value in changes.items():
        setattr(profile, key, value)
    profile_fact_fields = {"full_name", "city", "years_experience"} & changes.keys()
    if profile_fact_fields:
        manual_source = await session.scalar(
            select(EvidenceSource).where(
                EvidenceSource.profile_id == profile.id,
                EvidenceSource.kind == SourceKind.MANUAL,
                EvidenceSource.label == "User-confirmed manual entries",
            )
        )
        if not manual_source:
            raise HTTPException(status_code=500, detail="Onboarding evidence source is missing")
        onboarding_facts = list(
            (
                await session.scalars(
                    select(CareerFact).where(
                        CareerFact.profile_id == profile.id,
                        CareerFact.source_id == manual_source.id,
                    )
                )
            ).all()
        )
        facts_by_field = {
            fact.structured_value.get("profile_field"): fact
            for fact in onboarding_facts
            if fact.structured_value.get("profile_field")
        }
        fact_specs = {
            "full_name": (
                FactCategory.IDENTITY,
                str(changes.get("full_name") or "Name not specified"),
                {"full_name": changes.get("full_name")},
            ),
            "city": (
                FactCategory.PREFERENCE,
                str(changes.get("city") or "City not specified"),
                {"city": changes.get("city")},
            ),
            "years_experience": (
                FactCategory.EXPERIENCE,
                (
                    f"{changes['years_experience']:g} years experience"
                    if changes.get("years_experience") is not None
                    else "Experience years not specified"
                ),
                {"years_experience": changes.get("years_experience")},
            ),
        }
        for field_name in profile_fact_fields:
            category, label, structured = fact_specs[field_name]
            fact = facts_by_field.get(field_name)
            if fact:
                if fact.original_extraction is None:
                    fact.original_extraction = {
                        "category": fact.category.value,
                        "label": fact.label,
                        "detail": fact.detail,
                        "structured_value": fact.structured_value,
                        "source_excerpt": fact.source_excerpt,
                        "source_id": str(fact.source_id),
                    }
                await _invalidate_fact_documents(session, fact.id)
            else:
                fact = CareerFact(profile_id=profile.id, source_id=manual_source.id)
                session.add(fact)
            fact.category = category
            fact.label = label
            fact.structured_value = {"profile_field": field_name, **structured}
            fact.source_excerpt = label
            fact.verification_status = VerificationStatus.UNCONFIRMED
            fact.confirmed_at = None
            fact.extraction_confidence = 1.0
            fact.user_correction_reason = f"Profile {field_name} changed by user"
            fact.user_corrected_at = datetime.now(UTC)
    invalidation_reasons: list[str] = []
    if "completed_fact_categories" in changes:
        invalidation_reasons.append("Profile completeness categories changed")
    if profile_fact_fields:
        invalidation_reasons.append("Profile evidence fields changed")
    if invalidation_reasons:
        await _invalidate_profile_analyses(session, profile.id, "; ".join(invalidation_reasons))
    await session.commit()
    await session.refresh(profile)
    return profile


@router.post(
    "/profiles/{profile_id}/sources",
    response_model=EvidenceSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_evidence_source(
    profile_id: UUID,
    payload: EvidenceSourceCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> EvidenceSource:
    await _owned_profile(session, profile_id, user.id)
    await _guard_profile_mutation(session, profile_id, user.id)
    if payload.kind is not SourceKind.MANUAL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only manual evidence sources can be created by users",
        )
    source = EvidenceSource(profile_id=profile_id, **payload.model_dump())
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@router.get("/profiles/{profile_id}/sources", response_model=list[EvidenceSourceRead])
async def list_evidence_sources(
    profile_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> list[EvidenceSource]:
    await _owned_profile(session, profile_id, user.id)
    return list(
        (
            await session.scalars(
                select(EvidenceSource)
                .where(EvidenceSource.profile_id == profile_id)
                .order_by(EvidenceSource.created_at)
            )
        ).all()
    )


@router.post(
    "/profiles/{profile_id}/imports",
    response_model=ImportResultRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_professional_file(
    profile_id: UUID,
    user: CurrentUser,
    file: UploadFile = File(...),
    use_ai: bool = Form(False),
    data_sharing_acknowledged: bool = Form(False),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ImportResultRead:
    profile = await _owned_profile(session, profile_id, user.id)
    evidence_revision = profile.evidence_revision
    if not file.filename:
        raise HTTPException(status_code=422, detail="Import filename is required")
    try:
        data = await read_limited_upload(file, settings.max_import_bytes)
    finally:
        await file.close()
    parsed = parse_import(file.filename, file.content_type, data)
    import_metadata = metadata_for_import(data, parsed)
    content_sha256 = str(import_metadata["content_sha256"])
    ai_enhanced = use_ai and parsed.source_kind is SourceKind.CV_UPLOAD
    existing_source = await _evidence_source_for_content(session, profile_id, content_sha256)
    if existing_source and not ai_enhanced:
        raise _resume_ai_error(
            status.HTTP_409_CONFLICT,
            "resume_content_duplicate",
            "This file has already been imported",
        )
    if existing_source and existing_source.source_metadata.get("ai_enhanced") is True:
        return ImportResultRead(
            source=existing_source,
            facts=[],
            requires_user_review=True,
            analysis_status="already_ai_analyzed",
        )

    candidates = parsed.candidates
    provider: ResumeIntakeProvider | None = None
    if ai_enhanced:
        segments = build_resume_segments(parsed.extracted_text or "")
        if not segments:
            raise _resume_ai_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "resume_text_unreadable",
                "No readable resume text was found; use a text-based PDF or DOCX",
            )
        provider = _resume_ai_provider(
            settings,
            data_sharing_acknowledged=data_sharing_acknowledged,
        )
        try:
            candidates = await provider.generate(
                ResumeIntakeProviderContext(
                    locale=profile.preferred_language.value,
                    mode="upload",
                    segments=segments,
                )
            )
        except ResumeIntakeProviderError as exc:
            raise _resume_ai_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "resume_ai_unavailable",
                "The AI resume assistant is temporarily unavailable",
            ) from exc

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "No supported professional facts were found. Use a text-based PDF or DOCX, "
                "a LinkedIn export, or add facts manually."
            ),
        )
    if ai_enhanced:
        await _guard_resume_ai_snapshot(
            session,
            profile,
            user.id,
            evidence_revision,
        )
    else:
        await _guard_profile_mutation(session, profile_id, user.id)

    if existing_source:
        await session.refresh(existing_source)
        if existing_source.source_metadata.get("ai_enhanced") is True:
            return ImportResultRead(
                source=existing_source,
                facts=[],
                requires_user_review=True,
                analysis_status="already_ai_analyzed",
            )
        existing_facts = list(
            (
                await session.scalars(
                    select(CareerFact)
                    .where(CareerFact.source_id == existing_source.id)
                    .order_by(CareerFact.created_at)
                )
            ).all()
        )
        matched_fact_ids: set[UUID] = set()
        changed_facts: list[CareerFact] = []
        for candidate in candidates:
            fact = _matching_source_fact(candidate, existing_facts, matched_fact_ids)
            if fact:
                matched_fact_ids.add(fact.id)
                if fact.verification_status is not VerificationStatus.EXTRACTED:
                    continue
                fact.label = candidate.label
                fact.detail = candidate.detail
                fact.structured_value = candidate.structured_value
                fact.source_excerpt = candidate.source_excerpt
                fact.extraction_confidence = candidate.confidence
            else:
                fact = CareerFact(
                    profile_id=profile_id,
                    source_id=existing_source.id,
                    category=candidate.category,
                    label=candidate.label,
                    detail=candidate.detail,
                    structured_value=candidate.structured_value,
                    source_excerpt=candidate.source_excerpt,
                    verification_status=VerificationStatus.EXTRACTED,
                    extraction_confidence=candidate.confidence,
                )
                session.add(fact)
            changed_facts.append(fact)
        if not provider:
            raise HTTPException(status_code=500, detail="AI resume provider was not initialized")
        existing_source.source_metadata = {
            **existing_source.source_metadata,
            "candidate_fact_count": len(candidates),
            "ai_enhanced": True,
            "ai_provider": provider.provider_name,
            "ai_model": provider.model,
            "consent_version": _resume_ai_consent_version(provider),
        }
        if changed_facts:
            await _invalidate_profile_analyses(
                session,
                profile_id,
                "Existing professional evidence AI-upgraded",
            )
        await session.commit()
        await session.refresh(existing_source)
        for fact in changed_facts:
            await session.refresh(fact)
        return ImportResultRead(
            source=existing_source,
            facts=changed_facts,
            requires_user_review=True,
            analysis_status="ai_upgraded",
        )

    duplicate_source = await _evidence_source_for_content(session, profile_id, content_sha256)
    if duplicate_source:
        raise _resume_ai_error(
            status.HTTP_409_CONFLICT,
            "resume_content_duplicate",
            "This file has already been imported",
        )
    if provider:
        import_metadata.update(
            {
                "candidate_fact_count": len(candidates),
                "ai_enhanced": True,
                "ai_provider": provider.provider_name,
                "ai_model": provider.model,
                "consent_version": _resume_ai_consent_version(provider),
            }
        )
    safe_filename = file.filename.replace("\\", "/").rsplit("/", 1)[-1][:500]
    source = EvidenceSource(
        profile_id=profile_id,
        kind=parsed.source_kind,
        label=f"Imported {safe_filename}"[:255],
        original_filename=safe_filename,
        source_locator=None,
        source_metadata=import_metadata,
    )
    session.add(source)
    await session.flush()
    facts: list[CareerFact] = []
    for candidate in candidates:
        fact = CareerFact(
            profile_id=profile_id,
            source_id=source.id,
            category=candidate.category,
            label=candidate.label,
            detail=candidate.detail,
            structured_value=candidate.structured_value,
            source_excerpt=candidate.source_excerpt,
            verification_status=VerificationStatus.EXTRACTED,
            extraction_confidence=candidate.confidence,
        )
        session.add(fact)
        facts.append(fact)
    await _invalidate_profile_analyses(session, profile_id, "New professional evidence imported")
    await session.commit()
    await session.refresh(source)
    for fact in facts:
        await session.refresh(fact)
    return ImportResultRead(
        source=source,
        facts=facts,
        requires_user_review=True,
        analysis_status="created",
    )


@router.post(
    "/profiles/{profile_id}/resume-drafts",
    response_model=ImportResultRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_ai_resume_draft(
    profile_id: UUID,
    payload: ResumeNarrativeCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ImportResultRead:
    profile = await _owned_profile(session, profile_id, user.id)
    provider = _resume_ai_provider(
        settings,
        data_sharing_acknowledged=payload.data_sharing_acknowledged,
    )
    narrative = payload.content.strip()
    segments = build_resume_segments(narrative)
    if not segments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No supported professional information was found in the resume draft",
        )
    content_sha256 = sha256(narrative.encode("utf-8")).hexdigest()
    await _ensure_unique_evidence_content(
        session,
        profile_id,
        content_sha256,
        detail="This resume draft has already been analyzed",
    )
    evidence_revision = profile.evidence_revision
    try:
        candidates = await provider.generate(
            ResumeIntakeProviderContext(
                locale=profile.preferred_language.value,
                mode="builder",
                segments=segments,
            )
        )
    except ResumeIntakeProviderError as exc:
        raise _resume_ai_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_ai_unavailable",
            "The AI resume assistant is temporarily unavailable",
        ) from exc
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No supported professional facts were found in the resume draft",
        )

    await _guard_resume_ai_snapshot(
        session,
        profile,
        user.id,
        evidence_revision,
    )
    await _ensure_unique_evidence_content(
        session,
        profile_id,
        content_sha256,
        detail="This resume draft has already been analyzed",
    )
    source = EvidenceSource(
        profile_id=profile_id,
        kind=SourceKind.MANUAL,
        label="AI-assisted resume draft",
        original_filename=None,
        source_locator=None,
        source_metadata={
            "content_sha256": content_sha256,
            "char_count": len(narrative),
            "candidate_fact_count": len(candidates),
            "raw_narrative_retained": False,
            "professional_data_only": True,
            "ai_enhanced": True,
            "ai_provider": provider.provider_name,
            "ai_model": provider.model,
            "consent_version": _resume_ai_consent_version(provider),
        },
    )
    session.add(source)
    await session.flush()
    facts: list[CareerFact] = []
    for candidate in candidates:
        fact = CareerFact(
            profile_id=profile_id,
            source_id=source.id,
            category=candidate.category,
            label=candidate.label,
            detail=candidate.detail,
            structured_value=candidate.structured_value,
            source_excerpt=candidate.source_excerpt,
            verification_status=VerificationStatus.EXTRACTED,
            extraction_confidence=candidate.confidence,
        )
        session.add(fact)
        facts.append(fact)
    await _invalidate_profile_analyses(
        session,
        profile_id,
        "AI-assisted resume evidence created",
    )
    await session.commit()
    await session.refresh(source)
    for fact in facts:
        await session.refresh(fact)
    return ImportResultRead(source=source, facts=facts, requires_user_review=True)


@router.post(
    "/profiles/{profile_id}/facts",
    response_model=CareerFactRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_fact(
    profile_id: UUID,
    payload: CareerFactCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> CareerFact:
    await _owned_profile(session, profile_id, user.id)
    await _guard_profile_mutation(session, profile_id, user.id)
    source = await session.scalar(
        select(EvidenceSource).where(
            EvidenceSource.id == payload.source_id, EvidenceSource.profile_id == profile_id
        )
    )
    if not source:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid source"
        )
    initial_status = (
        VerificationStatus.EXTRACTED
        if source.kind in {SourceKind.CV_UPLOAD, SourceKind.LINKEDIN_EXPORT}
        else VerificationStatus.UNCONFIRMED
    )
    fact = CareerFact(
        profile_id=profile_id,
        verification_status=initial_status,
        **payload.model_dump(),
    )
    session.add(fact)
    await _invalidate_profile_analyses(session, profile_id, "Professional fact created")
    await session.commit()
    await session.refresh(fact)
    return fact


@router.get("/profiles/{profile_id}/facts", response_model=list[CareerFactRead])
async def list_facts(
    profile_id: UUID,
    user: CurrentUser,
    verification_status: VerificationStatus | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[CareerFact]:
    await _owned_profile(session, profile_id, user.id)
    statement = select(CareerFact).where(CareerFact.profile_id == profile_id)
    if verification_status:
        statement = statement.where(CareerFact.verification_status == verification_status)
    return list((await session.scalars(statement.order_by(CareerFact.created_at))).all())


async def _owned_fact(
    session: AsyncSession, profile_id: UUID, fact_id: UUID, owner_id: str
) -> CareerFact:
    await _owned_profile(session, profile_id, owner_id)
    fact = await session.scalar(
        select(CareerFact).where(CareerFact.id == fact_id, CareerFact.profile_id == profile_id)
    )
    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")
    return fact


async def _invalidate_fact_documents(session: AsyncSession, fact_id: UUID) -> None:
    document_ids = list(
        (
            await session.scalars(
                select(DocumentVersion.id)
                .join(DocumentClaim, DocumentClaim.document_id == DocumentVersion.id)
                .join(ClaimEvidence, ClaimEvidence.claim_id == DocumentClaim.id)
                .where(ClaimEvidence.fact_id == fact_id)
                .distinct()
            )
        ).all()
    )
    if document_ids:
        await session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id.in_(document_ids))
            .values(
                status=DocumentStatus.DRAFT,
                reviewed_at=None,
                reviewed_by_owner_id=None,
                review_hash=None,
                evidence_revision_at_review=None,
            )
        )


@router.patch(
    "/profiles/{profile_id}/facts/{fact_id}",
    response_model=CareerFactRead,
)
async def update_fact(
    profile_id: UUID,
    fact_id: UUID,
    payload: CareerFactUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> CareerFact:
    fact = await _owned_fact(session, profile_id, fact_id, user.id)
    await _guard_profile_mutation(session, profile_id, user.id)
    if fact.structured_value.get("profile_field"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile-managed facts must be edited through PATCH /v1/profiles",
        )
    if fact.original_extraction is None:
        fact.original_extraction = {
            "category": fact.category.value,
            "label": fact.label,
            "detail": fact.detail,
            "structured_value": fact.structured_value,
            "source_excerpt": fact.source_excerpt,
            "source_id": str(fact.source_id),
        }
    changes = payload.model_dump(exclude_unset=True, exclude={"correction_reason"})
    for key, value in changes.items():
        setattr(fact, key, value)
    fact.user_correction_reason = payload.correction_reason
    fact.user_corrected_at = datetime.now(UTC)
    fact.verification_status = VerificationStatus.UNCONFIRMED
    fact.confirmed_at = None
    await _invalidate_fact_documents(session, fact.id)
    await _invalidate_profile_analyses(session, profile_id, "Professional fact edited")
    await session.commit()
    await session.refresh(fact)
    return fact


@router.post("/profiles/{profile_id}/facts/{fact_id}/confirm", response_model=CareerFactRead)
async def confirm_fact(
    profile_id: UUID,
    fact_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> CareerFact:
    fact = await _owned_fact(session, profile_id, fact_id, user.id)
    await _guard_profile_mutation(session, profile_id, user.id)
    if fact.verification_status is VerificationStatus.CONFIRMED:
        return fact
    fact.verification_status = VerificationStatus.CONFIRMED
    fact.confirmed_at = datetime.now(UTC)
    await _invalidate_profile_analyses(session, profile_id, "Professional fact confirmed")
    await session.commit()
    await session.refresh(fact)
    return fact


@router.post(
    "/profiles/{profile_id}/facts/{fact_id}/unconfirm",
    response_model=CareerFactRead,
)
async def unconfirm_fact(
    profile_id: UUID,
    fact_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> CareerFact:
    fact = await _owned_fact(session, profile_id, fact_id, user.id)
    await _guard_profile_mutation(session, profile_id, user.id)
    if fact.verification_status is VerificationStatus.UNCONFIRMED:
        return fact
    fact.verification_status = VerificationStatus.UNCONFIRMED
    fact.confirmed_at = None
    await _invalidate_fact_documents(session, fact.id)
    await _invalidate_profile_analyses(session, profile_id, "Professional fact unconfirmed")
    await session.commit()
    await session.refresh(fact)
    return fact


@router.get("/source-policies", response_model=list[SourcePolicyRead])
async def list_source_policies(
    _user: CurrentUser, session: AsyncSession = Depends(get_db)
) -> list[SourcePolicy]:
    return list(
        (await session.scalars(select(SourcePolicy).order_by(SourcePolicy.source_key))).all()
    )


@router.post("/jobs/manual", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_manual_job(
    payload: ManualJobCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Job:
    # Keep the career profile as the ownership root used by analysis, export, and deletion. A
    # failed analysis must not leave behind a job that the user cannot manage from onboarding.
    await _guard_current_profile_mutation(session, user.id)
    source_key = source_key_for_url(payload.source_url, payload.source_key)
    policy = await get_or_create_deny_by_default_policy(session, source_key)
    digest_input = "\n".join(
        (
            payload.title.strip().casefold(),
            payload.company.strip().casefold(),
            payload.description.strip(),
        )
    )
    job = Job(
        owner_id=user.id,
        source_policy_id=policy.id,
        source_url=payload.source_url,
        intake_method=IntakeMethod.MANUAL,
        title=payload.title,
        company=payload.company,
        description=payload.description,
        location=payload.location,
        posted_at=payload.posted_at,
        expires_at=payload.expires_at,
        fetched_at=None,
        content_hash=sha256(digest_input.encode()).hexdigest(),
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Duplicate job for this user"
        ) from exc
    requirements = payload.requirements
    if not requirements:
        extracted = get_ai_provider().extract_requirements(payload.description)
        for item in extracted:
            session.add(
                JobRequirement(
                    job_id=job.id,
                    category=item.category,
                    importance=item.importance,
                    text=item.text,
                    normalized_value=item.normalized_value,
                    weight=item.weight,
                    needs_user_review=item.needs_user_review,
                )
            )
    else:
        for item in requirements:
            session.add(JobRequirement(job_id=job.id, **item.model_dump()))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Duplicate job for this user"
        ) from exc
    return await _owned_job(session, job.id, user.id)


@router.get("/jobs", response_model=list[JobRead])
async def list_jobs(user: CurrentUser, session: AsyncSession = Depends(get_db)) -> list[Job]:
    return list(
        (
            await session.scalars(
                select(Job)
                .where(Job.owner_id == user.id)
                .options(selectinload(Job.source_policy), selectinload(Job.requirements))
                .order_by(Job.created_at.desc())
            )
        ).all()
    )


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: UUID, user: CurrentUser, session: AsyncSession = Depends(get_db)) -> Job:
    return await _owned_job(session, job_id, user.id)


@router.post(
    "/jobs/{job_id}/requirements",
    response_model=JobRequirementRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_job_requirement(
    job_id: UUID,
    payload: JobRequirementUserCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> JobRequirement:
    job = await _owned_job(session, job_id, user.id)
    await _guard_current_profile_mutation(session, user.id)
    requirement = JobRequirement(
        job_id=job.id,
        category=payload.category,
        importance=payload.importance,
        text=payload.text,
        normalized_value=payload.normalized_value,
        weight=payload.weight,
        needs_user_review=False,
        is_active=True,
        user_added=True,
        user_correction_reason=payload.correction_reason,
        user_corrected_at=datetime.now(UTC),
        original_extraction={"user_added": True},
    )
    session.add(requirement)
    _clear_requirements_review(job)
    await _invalidate_job_analyses(session, job.id, "Job requirement added by user")
    await session.commit()
    await session.refresh(requirement)
    return requirement


@router.post(
    "/jobs/{job_id}/requirements/{requirement_id}/retire",
    response_model=JobRequirementRead,
)
async def retire_job_requirement(
    job_id: UUID,
    requirement_id: UUID,
    payload: JobRequirementRetire,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> JobRequirement:
    job = await _owned_job(session, job_id, user.id)
    await _guard_current_profile_mutation(session, user.id)
    requirement = await _owned_requirement(session, job_id, requirement_id, user.id)
    if requirement.original_extraction is None:
        requirement.original_extraction = {
            "category": requirement.category.value,
            "importance": requirement.importance.value,
            "text": requirement.text,
            "normalized_value": requirement.normalized_value,
            "weight": requirement.weight,
            "needs_user_review": requirement.needs_user_review,
        }
    requirement.is_active = False
    requirement.user_correction_reason = payload.correction_reason
    requirement.user_corrected_at = datetime.now(UTC)
    _clear_requirements_review(job)
    await _invalidate_job_analyses(session, job.id, "Job requirement retired by user")
    await session.commit()
    await session.refresh(requirement)
    return requirement


@router.post("/jobs/{job_id}/requirements/review", response_model=JobRead)
async def review_job_requirements(
    job_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Job:
    job = await _owned_job(session, job_id, user.id)
    await _guard_current_profile_mutation(session, user.id)
    if _requirements_review_is_current(job) and not any(
        requirement.is_active and requirement.needs_user_review
        for requirement in job.requirements
    ):
        return job
    for requirement in job.requirements:
        if requirement.is_active:
            requirement.needs_user_review = False
    job.requirements_reviewed_at = datetime.now(UTC)
    job.requirements_reviewed_by_owner_id = user.id
    job.requirements_review_hash = _requirements_review_hash(list(job.requirements))
    await _invalidate_job_analyses(session, job.id, "Job requirements attested by user")
    await session.commit()
    return await _owned_job(session, job.id, user.id)


@router.patch(
    "/jobs/{job_id}/requirements/{requirement_id}",
    response_model=JobRequirementRead,
)
async def update_job_requirement(
    job_id: UUID,
    requirement_id: UUID,
    payload: JobRequirementUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> JobRequirement:
    job = await _owned_job(session, job_id, user.id)
    await _guard_current_profile_mutation(session, user.id)
    requirement = await _owned_requirement(session, job_id, requirement_id, user.id)
    if requirement.original_extraction is None:
        requirement.original_extraction = {
            "category": requirement.category.value,
            "importance": requirement.importance.value,
            "text": requirement.text,
            "normalized_value": requirement.normalized_value,
            "weight": requirement.weight,
            "needs_user_review": requirement.needs_user_review,
        }
    changes = payload.model_dump(exclude_unset=True, exclude={"correction_reason"})
    needs_user_review = False
    if "text" in changes and "normalized_value" not in changes:
        extracted = get_ai_provider().extract_requirements(changes["text"])
        if len(extracted) == 1:
            candidate = extracted[0]
            changes["normalized_value"] = candidate.normalized_value
            if "category" not in changes:
                changes["category"] = candidate.category
            if "importance" not in changes:
                changes["importance"] = candidate.importance
            needs_user_review = candidate.needs_user_review
        else:
            changes["normalized_value"] = None
            needs_user_review = True
    for key, value in changes.items():
        setattr(requirement, key, value)
    requirement.user_correction_reason = payload.correction_reason
    requirement.user_corrected_at = datetime.now(UTC)
    requirement.needs_user_review = needs_user_review
    _clear_requirements_review(job)
    await _invalidate_job_analyses(session, job_id, "Job requirement corrected by user")
    await session.commit()
    await session.refresh(requirement)
    return requirement


async def _load_analysis(session: AsyncSession, analysis_id: UUID) -> MatchAnalysis:
    return await session.scalar(
        select(MatchAnalysis)
        .where(MatchAnalysis.id == analysis_id)
        .options(
            selectinload(MatchAnalysis.requirement_matches).selectinload(
                RequirementMatch.requirement
            )
        )
    )


@router.get("/jobs/{job_id}/analyses/latest", response_model=MatchAnalysisRead)
async def get_latest_job_analysis(
    job_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> MatchAnalysis:
    await _owned_job(session, job_id, user.id)
    analysis = await session.scalar(
        select(MatchAnalysis)
        .join(CareerProfile, CareerProfile.id == MatchAnalysis.profile_id)
        .join(Job, Job.id == MatchAnalysis.job_id)
        .where(
            MatchAnalysis.job_id == job_id,
            MatchAnalysis.invalidated_at.is_(None),
            MatchAnalysis.evidence_revision == CareerProfile.evidence_revision,
            MatchAnalysis.requirements_revision == Job.requirements_revision,
        )
        .options(
            selectinload(MatchAnalysis.requirement_matches).selectinload(
                RequirementMatch.requirement
            )
        )
        .order_by(MatchAnalysis.created_at.desc())
    )
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current analysis found",
        )
    return analysis


@router.post("/jobs/{job_id}/analyze", response_model=MatchAnalysisRead)
async def analyze_job(
    job_id: UUID,
    payload: AnalyzeJobRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> MatchAnalysis:
    job = await _owned_job(session, job_id, user.id)
    profile = await _owned_profile(session, payload.profile_id, user.id)
    evidence_revision = profile.evidence_revision
    requirements_revision = job.requirements_revision
    confirmed_facts = list(
        (
            await session.scalars(
                select(CareerFact).where(
                    CareerFact.profile_id == payload.profile_id,
                    CareerFact.verification_status == VerificationStatus.CONFIRMED,
                )
            )
        ).all()
    )
    complete_categories = {FactCategory(value) for value in profile.completed_fact_categories}
    result = calculate_match(
        [requirement for requirement in job.requirements if requirement.is_active],
        confirmed_facts,
        complete_categories=complete_categories,
        requirements_reviewed=_requirements_review_is_current(job),
    )
    await _guard_analysis_snapshot(
        session,
        profile,
        job,
        evidence_revision,
        requirements_revision,
    )
    analysis = MatchAnalysis(
        profile_id=payload.profile_id,
        job_id=job.id,
        coverage_score=result["coverage_score"],
        mandatory_coverage_score=result["mandatory_coverage_score"],
        readiness_band=result["readiness_band"],
        confidence_band=result["confidence_band"],
        decision=result["decision"],
        explanation=result["explanation"],
        evidence_revision=evidence_revision,
        requirements_revision=requirements_revision,
    )
    session.add(analysis)
    await session.flush()
    for match in result["matches"]:
        session.add(
            RequirementMatch(
                analysis_id=analysis.id,
                requirement_id=match["requirement"].id,
                evidence_fact_id=match["evidence"].id if match["evidence"] else None,
                status=match["status"],
                reason=match["reason"],
                earned_weight=match["earned_weight"],
            )
        )
    await session.commit()
    return await _load_analysis(session, analysis.id)


@router.post("/documents", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> DocumentVersion:
    await _owned_profile(session, payload.profile_id, user.id)
    await _guard_profile_mutation(session, payload.profile_id, user.id)
    if payload.job_id:
        await _owned_job(session, payload.job_id, user.id)
    if payload.base_version_id:
        await _owned_document(session, payload.base_version_id, user.id)
    document = await create_evidence_safe_document(session, payload)
    await session.commit()
    return document


@router.get("/documents", response_model=list[DocumentRead])
async def list_documents(
    user: CurrentUser,
    profile_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[DocumentVersion]:
    statement = (
        select(DocumentVersion)
        .join(CareerProfile, CareerProfile.id == DocumentVersion.profile_id)
        .where(CareerProfile.owner_id == user.id)
        .options(selectinload(DocumentVersion.claims).selectinload(DocumentClaim.evidence_links))
        .order_by(DocumentVersion.created_at.desc())
    )
    if profile_id:
        statement = statement.where(DocumentVersion.profile_id == profile_id)
    return list((await session.scalars(statement)).all())


@router.get("/documents/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: UUID, user: CurrentUser, session: AsyncSession = Depends(get_db)
) -> DocumentVersion:
    return await _owned_document(session, document_id, user.id)


@router.post("/documents/{document_id}/validate", response_model=DocumentValidationRead)
async def check_document(
    document_id: UUID, user: CurrentUser, session: AsyncSession = Depends(get_db)
) -> DocumentValidationRead:
    document = await _owned_document(session, document_id, user.id)
    unsupported = await validate_document(session, document)
    return DocumentValidationRead(
        document_id=document.id,
        valid=not unsupported,
        unsupported_claim_ids=unsupported,
        export_allowed=not unsupported and has_current_review(document),
    )


@router.post("/documents/{document_id}/review", response_model=DocumentRead)
async def review_document(
    document_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> DocumentVersion:
    document = await _owned_document(session, document_id, user.id)
    profile = await _owned_profile(session, document.profile_id, user.id)
    evidence_revision = profile.evidence_revision
    unsupported = await validate_document(session, document)
    if unsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "unsupported_claims",
                "claim_ids": [str(claim_id) for claim_id in unsupported],
            },
        )
    await _guard_document_review_snapshot(
        session,
        document,
        profile,
        evidence_revision,
    )
    document.reviewed_at = datetime.now(UTC)
    document.reviewed_by_owner_id = user.id
    document.review_hash = document_review_hash(document)
    document.evidence_revision_at_review = evidence_revision
    document.status = DocumentStatus.EXPORT_READY
    await session.commit()
    return await _owned_document(session, document.id, user.id)


async def _validate_application_documents(
    session: AsyncSession, application: Application, owner_id: str
) -> None:
    gated_statuses = {ApplicationStatus.READY, *POST_SUBMISSION_STATUSES}
    if application.status in gated_statuses and not application.cv_document_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A reviewed export-ready CV is required before the application is ready",
        )
    document_slots = (
        (application.cv_document_id, DocumentKind.CV),
        (application.cover_letter_document_id, DocumentKind.COVER_LETTER),
    )
    for document_id, expected_kind in document_slots:
        if not document_id:
            continue
        document = await _owned_document(session, document_id, owner_id)
        if document.profile_id != application.profile_id or (
            document.job_id and document.job_id != application.job_id
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Document does not belong to this application",
            )
        if document.kind is not expected_kind:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Document in {expected_kind.value} slot has the wrong kind",
            )
        if await validate_document(session, document):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Application contains a document with unsupported claims",
            )
        if application.status in gated_statuses and not has_current_review(document):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Application documents must be reviewed and export-ready",
            )


async def _validate_application_analysis(
    session: AsyncSession, application: Application, owner_id: str
) -> None:
    if not application.analysis_id:
        return
    analysis = await session.scalar(
        select(MatchAnalysis)
        .join(CareerProfile, CareerProfile.id == MatchAnalysis.profile_id)
        .join(Job, Job.id == MatchAnalysis.job_id)
        .where(
            MatchAnalysis.id == application.analysis_id,
            CareerProfile.owner_id == owner_id,
            Job.owner_id == owner_id,
            MatchAnalysis.evidence_revision == CareerProfile.evidence_revision,
            MatchAnalysis.requirements_revision == Job.requirements_revision,
        )
    )
    if (
        not analysis
        or analysis.profile_id != application.profile_id
        or analysis.job_id != application.job_id
        or analysis.invalidated_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Analysis does not belong to this application",
        )


@router.post("/applications", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Application:
    await _owned_profile(session, payload.profile_id, user.id)
    await _guard_profile_mutation(session, payload.profile_id, user.id)
    await _owned_job(session, payload.job_id, user.id)
    application = Application(**payload.model_dump())
    if payload.status in POST_SUBMISSION_STATUSES:
        application.submitted_at = datetime.now(UTC)
    session.add(application)
    try:
        await session.flush()
        await _validate_application_analysis(session, application, user.id)
        await _validate_application_documents(session, application, user.id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Application already exists") from exc
    return await _owned_application(session, application.id, user.id)


@router.get("/applications", response_model=list[ApplicationRead])
async def list_applications(
    user: CurrentUser, session: AsyncSession = Depends(get_db)
) -> list[Application]:
    return list(
        (
            await session.scalars(
                select(Application)
                .join(CareerProfile, CareerProfile.id == Application.profile_id)
                .where(CareerProfile.owner_id == user.id)
                .options(selectinload(Application.outcomes))
                .order_by(Application.updated_at.desc())
            )
        ).all()
    )


@router.patch("/applications/{application_id}", response_model=ApplicationRead)
async def update_application(
    application_id: UUID,
    payload: ApplicationUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Application:
    application = await _owned_application(session, application_id, user.id)
    await _guard_profile_mutation(session, application.profile_id, user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(application, key, value)
    if application.status in POST_SUBMISSION_STATUSES and not application.submitted_at:
        application.submitted_at = datetime.now(UTC)
    if "analysis_id" in payload.model_fields_set:
        await _validate_application_analysis(session, application, user.id)
    await _validate_application_documents(session, application, user.id)
    await session.commit()
    return await _owned_application(session, application.id, user.id)


@router.post(
    "/applications/{application_id}/outcomes",
    response_model=OutcomeRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_outcome(
    application_id: UUID,
    payload: OutcomeCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Outcome:
    application = await _owned_application(session, application_id, user.id)
    await _guard_profile_mutation(session, application.profile_id, user.id)
    if (
        payload.confirmed_by_user
        and payload.kind in POST_SUBMISSION_OUTCOMES
        and application.submitted_at is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Confirm that the application was submitted before recording this outcome",
        )
    outcome = Outcome(application_id=application.id, **payload.model_dump())
    session.add(outcome)
    if payload.confirmed_by_user:
        status_map = {
            OutcomeKind.INTERVIEW: ApplicationStatus.INTERVIEW,
            OutcomeKind.REJECTION: ApplicationStatus.REJECTED,
            OutcomeKind.OFFER: ApplicationStatus.OFFER,
            OutcomeKind.WITHDRAWAL: ApplicationStatus.WITHDRAWN,
        }
        if payload.kind in status_map:
            application.status = status_map[payload.kind]
    await session.commit()
    await session.refresh(outcome)
    return outcome


@router.get("/dashboard", response_model=DashboardRead)
async def get_dashboard(
    user: CurrentUser, session: AsyncSession = Depends(get_db)
) -> DashboardRead:
    profile = await _current_profile(session, user.id)
    facts = list(
        (await session.scalars(select(CareerFact).where(CareerFact.profile_id == profile.id))).all()
    )
    profile_summary = _career_profile_summary(profile.id, facts)

    applications = list(
        (
            await session.scalars(
                select(Application)
                .where(Application.profile_id == profile.id)
                .options(selectinload(Application.outcomes))
            )
        ).all()
    )
    pipeline = {application_status: 0 for application_status in ApplicationStatus}
    for application in applications:
        pipeline[application.status] += 1
    submitted = sum(application.submitted_at is not None for application in applications)
    qualified_interviews = sum(
        outcome.confirmed_by_user and outcome.qualified_human_interview
        for application in applications
        for outcome in application.outcomes
    )
    now = datetime.now(UTC)
    terminal_statuses = {
        ApplicationStatus.REJECTED,
        ApplicationStatus.OFFER,
        ApplicationStatus.WITHDRAWN,
    }
    actions_due = 0
    for application in applications:
        due_at = application.next_action_at
        if due_at and due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=UTC)
        if due_at and due_at <= now and application.status not in terminal_statuses:
            actions_due += 1
    top_analyses = list(
        (
            await session.scalars(
                select(MatchAnalysis)
                .join(Job, Job.id == MatchAnalysis.job_id)
                .where(
                    MatchAnalysis.profile_id == profile.id,
                    Job.owner_id == user.id,
                    MatchAnalysis.invalidated_at.is_(None),
                    MatchAnalysis.evidence_revision == profile.evidence_revision,
                    MatchAnalysis.requirements_revision == Job.requirements_revision,
                )
                .options(
                    selectinload(MatchAnalysis.requirement_matches).selectinload(
                        RequirementMatch.requirement
                    )
                )
                .order_by(MatchAnalysis.coverage_score.desc(), MatchAnalysis.created_at.desc())
                .limit(5)
            )
        ).all()
    )
    return DashboardRead(
        profile_id=profile.id,
        profile_quality_percent=profile_summary.profile_quality_percent,
        confirmed_facts=profile_summary.confirmed_facts,
        total_facts=profile_summary.total_facts,
        application_pipeline=pipeline,
        submitted_applications=submitted,
        qualified_interviews=qualified_interviews,
        qualified_interviews_per_completed_application=(
            round(qualified_interviews / submitted, 3) if submitted else None
        ),
        actions_due=actions_due,
        top_opportunities=top_analyses,
    )


def _dump(schema: type, value: object) -> Any:
    return schema.model_validate(value).model_dump(mode="json")


@router.get("/me/export", response_class=JSONResponse)
async def export_my_data(
    user: CurrentUser, session: AsyncSession = Depends(get_db)
) -> JSONResponse:
    profile = await _maybe_current_profile(session, user.id)
    profile_id = profile.id if profile else None
    sources = list(
        (
            await session.scalars(
                select(EvidenceSource)
                .where(EvidenceSource.profile_id == profile_id)
                .order_by(EvidenceSource.created_at)
            )
        ).all()
    )
    facts = list(
        (
            await session.scalars(
                select(CareerFact)
                .where(CareerFact.profile_id == profile_id)
                .order_by(CareerFact.created_at)
            )
        ).all()
    )
    jobs = list(
        (
            await session.scalars(
                select(Job)
                .where(Job.owner_id == user.id)
                .options(selectinload(Job.source_policy), selectinload(Job.requirements))
                .order_by(Job.created_at)
            )
        ).all()
    )
    analyses = list(
        (
            await session.scalars(
                select(MatchAnalysis)
                .where(MatchAnalysis.profile_id == profile_id)
                .options(
                    selectinload(MatchAnalysis.requirement_matches).selectinload(
                        RequirementMatch.requirement
                    )
                )
                .order_by(MatchAnalysis.created_at)
            )
        ).all()
    )
    documents = list(
        (
            await session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.profile_id == profile_id)
                .options(
                    selectinload(DocumentVersion.claims).selectinload(DocumentClaim.evidence_links)
                )
                .order_by(DocumentVersion.created_at)
            )
        ).all()
    )
    applications = list(
        (
            await session.scalars(
                select(Application)
                .where(Application.profile_id == profile_id)
                .options(selectinload(Application.outcomes))
                .order_by(Application.created_at)
            )
        ).all()
    )
    career_path_conversation = await session.scalar(
        select(CareerPathConversation)
        .where(CareerPathConversation.profile_id == profile_id)
        .options(selectinload(CareerPathConversation.messages))
    )
    payload = {
        "schema_version": "2026-08-07",
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": _dump(CareerProfileRead, profile) if profile else None,
        "evidence_sources": [_dump(EvidenceSourceRead, item) for item in sources],
        "career_facts": [_dump(CareerFactRead, item) for item in facts],
        "jobs": [_dump(JobRead, item) for item in jobs],
        "match_analyses": [_dump(MatchAnalysisRead, item) for item in analyses],
        "documents": [_dump(DocumentRead, item) for item in documents],
        "applications": [_dump(ApplicationRead, item) for item in applications],
        "career_path_conversation": (
            _dump(CareerPathConversationRead, career_path_conversation)
            if career_path_conversation
            else None
        ),
        "career_path_messages": (
            [
                _dump(CareerPathMessageRead, item)
                for item in career_path_conversation.messages
            ]
            if career_path_conversation
            else []
        ),
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="career-agent-export.json"'},
    )


@router.delete("/me/data", response_model=DeletionReceiptRead)
async def delete_my_data(
    user: CurrentUser, session: AsyncSession = Depends(get_db)
) -> DeletionReceipt:
    profile = await _maybe_current_profile(session, user.id)
    if profile:
        deletion_guard = await session.execute(
            update(CareerProfile)
            .where(
                CareerProfile.id == profile.id,
                CareerProfile.owner_id == user.id,
                CareerProfile.deletion_started_at.is_(None),
            )
            .values(deletion_started_at=datetime.now(UTC))
        )
        if deletion_guard.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Profile deletion is already in progress",
            )
    profile_id = profile.id if profile else None
    job_ids = list((await session.scalars(select(Job.id).where(Job.owner_id == user.id))).all())
    analysis_ids = list(
        (
            await session.scalars(
                select(MatchAnalysis.id).where(MatchAnalysis.profile_id == profile_id)
            )
        ).all()
    )
    document_ids = list(
        (
            await session.scalars(
                select(DocumentVersion.id).where(DocumentVersion.profile_id == profile_id)
            )
        ).all()
    )
    application_ids = list(
        (
            await session.scalars(
                select(Application.id).where(Application.profile_id == profile_id)
            )
        ).all()
    )
    source_ids = list(
        (
            await session.scalars(
                select(EvidenceSource.id).where(EvidenceSource.profile_id == profile_id)
            )
        ).all()
    )
    fact_ids = list(
        (
            await session.scalars(select(CareerFact.id).where(CareerFact.profile_id == profile_id))
        ).all()
    )
    requirement_ids = list(
        (
            await session.scalars(
                select(JobRequirement.id).where(JobRequirement.job_id.in_(job_ids))
            )
        ).all()
    )
    requirement_match_ids = list(
        (
            await session.scalars(
                select(RequirementMatch.id).where(RequirementMatch.analysis_id.in_(analysis_ids))
            )
        ).all()
    )
    claim_ids = list(
        (
            await session.scalars(
                select(DocumentClaim.id).where(DocumentClaim.document_id.in_(document_ids))
            )
        ).all()
    )
    outcome_ids = list(
        (
            await session.scalars(
                select(Outcome.id).where(Outcome.application_id.in_(application_ids))
            )
        ).all()
    )
    career_path_conversation_ids = list(
        (
            await session.scalars(
                select(CareerPathConversation.id).where(
                    CareerPathConversation.profile_id == profile_id
                )
            )
        ).all()
    )
    career_path_message_ids = list(
        (
            await session.scalars(
                select(CareerPathMessage.id).where(
                    CareerPathMessage.conversation_id.in_(career_path_conversation_ids)
                )
            )
        ).all()
    )

    # Explicit ordering covers owner-keyed jobs as well as profile-keyed records; no shared source
    # policy is removed. The receipt deliberately contains no user identifier.
    await session.execute(delete(Outcome).where(Outcome.id.in_(outcome_ids)))
    await session.execute(delete(Application).where(Application.id.in_(application_ids)))
    await session.execute(delete(ClaimEvidence).where(ClaimEvidence.claim_id.in_(claim_ids)))
    await session.execute(delete(DocumentClaim).where(DocumentClaim.id.in_(claim_ids)))
    await session.execute(
        update(DocumentVersion)
        .where(DocumentVersion.id.in_(document_ids))
        .values(base_version_id=None)
    )
    await session.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(document_ids)))
    await session.execute(
        delete(RequirementMatch).where(RequirementMatch.id.in_(requirement_match_ids))
    )
    await session.execute(delete(MatchAnalysis).where(MatchAnalysis.id.in_(analysis_ids)))
    await session.execute(delete(JobRequirement).where(JobRequirement.id.in_(requirement_ids)))
    await session.execute(delete(Job).where(Job.id.in_(job_ids)))
    await session.execute(
        delete(CareerPathMessage).where(CareerPathMessage.id.in_(career_path_message_ids))
    )
    await session.execute(
        delete(CareerPathConversation).where(
            CareerPathConversation.id.in_(career_path_conversation_ids)
        )
    )
    await session.execute(delete(CareerFact).where(CareerFact.id.in_(fact_ids)))
    await session.execute(delete(EvidenceSource).where(EvidenceSource.id.in_(source_ids)))
    if profile:
        await session.execute(delete(CareerProfile).where(CareerProfile.id == profile.id))

    receipt = DeletionReceipt(
        completed_at=datetime.now(UTC),
        deleted_counts={
            "profiles": int(profile is not None),
            "evidence_sources": len(source_ids),
            "career_facts": len(fact_ids),
            "jobs": len(job_ids),
            "job_requirements": len(requirement_ids),
            "match_analyses": len(analysis_ids),
            "requirement_matches": len(requirement_match_ids),
            "documents": len(document_ids),
            "claims": len(claim_ids),
            "applications": len(application_ids),
            "outcomes": len(outcome_ids),
            "career_path_conversations": len(career_path_conversation_ids),
            "career_path_messages": len(career_path_message_ids),
        },
    )
    session.add(receipt)
    await session.commit()
    await session.refresh(receipt)
    return receipt
