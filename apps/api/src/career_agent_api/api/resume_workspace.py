from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from career_agent_api.core.auth import CurrentUser
from career_agent_api.core.config import Settings, get_settings
from career_agent_api.db.session import get_db
from career_agent_api.models.domain import (
    CareerFact,
    CareerProfile,
    ClaimEvidence,
    DocumentClaim,
    DocumentVersion,
    EvidenceSource,
    MatchAnalysis,
    ResumeDraftVersion,
    ResumeMessage,
    ResumeWorkspace,
)
from career_agent_api.models.enums import (
    DocumentStatus,
    FactCategory,
    PreferredLanguage,
    ResumeDraftStatus,
    ResumeDraftVersionReason,
    ResumeMessageKind,
    ResumeMessageRole,
    ResumeMessageStatus,
    ResumeWorkspaceStage,
    SourceKind,
    VerificationStatus,
)
from career_agent_api.schemas.api import (
    ResumeDraftContent,
    ResumeDraftPatchCreate,
    ResumeDraftRevisionCreate,
    ResumeDraftVersionRead,
    ResumeExportContact,
    ResumeImportDraftCreate,
    ResumeMessageCreate,
    ResumeReviewCreate,
    ResumeReviewRead,
    ResumeRewriteCreate,
    ResumeRewriteSuggestionRead,
    ResumeUnderstandingActionCreate,
    ResumeVerifiedSupplementalTranslation,
    ResumeWorkspaceRead,
    ResumeWorkspaceStartCreate,
    sanitize_structured_evidence,
)
from career_agent_api.services.resume_assessment import (
    ResumeAssessmentGap,
    build_resume_assessment,
    deterministic_gap_question,
)
from career_agent_api.services.resume_export import render_resume_pdf
from career_agent_api.services.resume_writer import (
    RESUME_SECTION_ORDER,
    ResumeWriterCategory,
    ResumeWriterError,
    ResumeWriterOutputError,
    ResumeWriterProvider,
    ResumeWriterTransportError,
    build_evidence_fallback_draft,
    build_resume_evidence,
    get_resume_writer_provider,
    resume_evidence_coursework,
    resume_patch_uses_requested_language,
    validate_claim_grounding,
    verified_supplemental_evidence_overlay,
)

router = APIRouter(
    prefix="/profiles/{profile_id}/resume-workspace",
    tags=["resume workspace"],
)

logger = logging.getLogger(__name__)

CONSENT_VERSION = "2026-08-08-v2"
AUTOSAVE_SNAPSHOT_LIMIT = 30
WORKSPACE_MESSAGE_RESPONSE_LIMIT = 50
WORKSPACE_VERSION_RESPONSE_LIMIT = 20
VERIFIED_SUPPLEMENTAL_TRANSLATIONS_KEY = "verified_supplemental_translations"
VERIFIED_SUPPLEMENTAL_TRANSLATIONS_SCHEMA = "resume_verified_supplemental.v1"
VERSION_HISTORY_DEFAULT_LIMIT = 30
VERSION_HISTORY_MAX_LIMIT = 50
PROFESSIONAL_CATEGORIES = {
    FactCategory.EDUCATION,
    FactCategory.EXPERIENCE,
    FactCategory.CERTIFICATION,
    FactCategory.SKILL,
    FactCategory.PROJECT,
    FactCategory.LANGUAGE,
    FactCategory.ACHIEVEMENT,
}
SECTION_SUPPORT_CATEGORIES: dict[str, set[str]] = {
    "education": {"education", "achievement"},
    "experience": {"experience", "achievement"},
    "trading_experience": {"experience", "achievement"},
    "project": {"project", "achievement"},
    "skill": {"skill"},
    "certification": {"certification", "achievement"},
    "language": {"language"},
    "achievement": {
        "achievement",
        "education",
        "experience",
        "project",
        "certification",
    },
}


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "request_id": str(uuid4())},
    )


async def _owned_profile(
    session: AsyncSession,
    profile_id: UUID,
    owner_id: str,
    *,
    for_update: bool = False,
) -> CareerProfile:
    statement = select(CareerProfile).where(
        CareerProfile.id == profile_id,
        CareerProfile.owner_id == owner_id,
    )
    if for_update:
        statement = statement.with_for_update()
    profile = await session.scalar(statement)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    if profile.deletion_started_at is not None:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "profile_deletion_in_progress",
            "Profile deletion is in progress",
        )
    return profile


async def _load_workspace(
    session: AsyncSession,
    profile_id: UUID,
    *,
    for_update: bool = False,
    include_messages: bool = True,
    include_versions: bool = True,
) -> ResumeWorkspace | None:
    statement = (
        select(ResumeWorkspace)
        .where(ResumeWorkspace.profile_id == profile_id)
        .execution_options(populate_existing=True)
    )
    relationship_options = []
    if include_messages:
        latest_message_ids = (
            select(ResumeMessage.id)
            .join(
                ResumeWorkspace,
                ResumeWorkspace.id == ResumeMessage.workspace_id,
            )
            .where(ResumeWorkspace.profile_id == profile_id)
            .order_by(ResumeMessage.sequence.desc())
            .limit(WORKSPACE_MESSAGE_RESPONSE_LIMIT)
        )
        relationship_options.append(
            selectinload(ResumeWorkspace.messages.and_(ResumeMessage.id.in_(latest_message_ids)))
        )
    if include_versions:
        latest_version_ids = (
            select(ResumeDraftVersion.id)
            .join(
                ResumeWorkspace,
                ResumeWorkspace.id == ResumeDraftVersion.workspace_id,
            )
            .where(ResumeWorkspace.profile_id == profile_id)
            .order_by(ResumeDraftVersion.version.desc())
            .limit(WORKSPACE_VERSION_RESPONSE_LIMIT)
        )
        relationship_options.append(
            selectinload(
                ResumeWorkspace.versions.and_(ResumeDraftVersion.id.in_(latest_version_ids))
            )
        )
    if relationship_options:
        statement = statement.options(*relationship_options)
    if for_update:
        # PostgreSQL serializes all workspace mutations on this row. SQLite safely ignores
        # SELECT FOR UPDATE, preserving local/test compatibility.
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def _profile_facts(session: AsyncSession, profile_id: UUID) -> list[CareerFact]:
    return list(
        (
            await session.scalars(
                select(CareerFact)
                .where(
                    CareerFact.profile_id == profile_id,
                    CareerFact.category.in_(PROFESSIONAL_CATEGORIES),
                )
                .order_by(CareerFact.created_at, CareerFact.id)
            )
        ).all()
    )


def _facts_selected_by_metadata(
    facts: list[CareerFact],
    metadata: dict[str, Any],
) -> list[CareerFact]:
    raw_ids = metadata.get("generation_fact_ids")
    if not isinstance(raw_ids, list):
        return facts
    selected_ids = {str(value) for value in raw_ids if str(value).strip()}
    return [fact for fact in facts if str(fact.id) in selected_ids]


async def _workspace_facts(
    session: AsyncSession,
    workspace: ResumeWorkspace,
) -> list[CareerFact]:
    """Return the evidence explicitly selected for this resume, if it has a source scope."""

    facts = await _profile_facts(session, workspace.profile_id)
    metadata = workspace.provider_metadata if isinstance(workspace.provider_metadata, dict) else {}
    return _facts_selected_by_metadata(facts, metadata)


def _provider_consent_version(provider: ResumeWriterProvider) -> str:
    return f"{CONSENT_VERSION}:{provider.provider_name}"


def _has_current_consent(
    workspace: ResumeWorkspace,
    provider: ResumeWriterProvider,
) -> bool:
    return workspace.consent_version == _provider_consent_version(provider)


def _conversation_language(workspace: ResumeWorkspace) -> PreferredLanguage:
    """Return the persisted interview language without changing the database schema.

    Workspaces created before the bilingual contract have no metadata value, so they retain the
    former behavior where the workspace language controlled both interview and resume output.
    """

    metadata = workspace.provider_metadata if isinstance(workspace.provider_metadata, dict) else {}
    raw_language = metadata.get("conversation_language")
    try:
        return PreferredLanguage(str(raw_language))
    except ValueError:
        return workspace.language


def _coverage(
    facts: list[CareerFact],
    draft: ResumeDraftContent | None,
) -> tuple[dict[str, bool], int]:
    confirmed = [fact for fact in facts if fact.verification_status is VerificationStatus.CONFIRMED]
    categories = {fact.category.value for fact in confirmed}
    draft_section_keys = {section.key for section in draft.sections} if draft else set()
    coverage = {
        "education": "education" in categories,
        "experience": "experience" in categories,
        "trading_experience": "trading_experience" in draft_section_keys,
        "certification": "certification" in categories,
        "skill": "skill" in categories,
        "language": "language" in categories,
        "project": "project" in categories,
        "achievement": "achievement" in categories,
    }
    score = 0
    score += 40 if coverage["experience"] else 0
    score += 15 if coverage["education"] else 0
    score += 15 if coverage["skill"] else 0
    score += 10 if coverage["language"] or coverage["certification"] else 0
    score += 10 if draft and draft.professional_summary.strip() else 0
    score += 10 if confirmed and len(confirmed) == len(facts) else 0
    return coverage, min(score, 100)


def _first_question(
    language: PreferredLanguage,
    facts: list[CareerFact],
) -> dict[str, Any]:
    categories = {
        fact.category.value
        for fact in facts
        if fact.verification_status is VerificationStatus.CONFIRMED
    }
    next_category = next(
        (category for category in RESUME_SECTION_ORDER if category not in categories),
        RESUME_SECTION_ORDER[-1],
    )
    if next_category == "experience":
        if language is PreferredLanguage.AR:
            question = (
                "احكِ لي عن تجربة عمل أو مشروع واحد تفخر به: ماذا فعلت، وبأي أداة، وما النتيجة؟"
            )
            placeholder = "مثال: حللت بيانات المبيعات باستخدام Power BI وساعدت الفريق على..."
            why = "نبني منها أول قصة مهنية قوية بدل وصف عام."
        else:
            question = (
                "Tell me about one job or project you are proud of: what did you do, "
                "which tools did you use, and what changed?"
            )
            placeholder = "Example: I analyzed sales data in Power BI and helped the team..."
            why = "This gives the resume one concrete professional story."
        category = "experience"
        fields = ["context", "action", "tools", "outcome"]
    elif next_category == "education":
        if language is PreferredLanguage.AR:
            question = "ما تخصصك، وفي أي جامعة درست، ومتى تخرجت؟ اذكر المعدل ومقياسه إن رغبت."
            placeholder = "التخصص، الجامعة، سنة التخرج، والمعدل من 4 أو 5."
            why = "حتى يظهر التعليم كاملًا ونعرض المعدل فقط عندما يقوي السيرة."
        else:
            question = (
                "What did you study, at which institution, and when did you graduate? "
                "Include your GPA and scale if you want it assessed."
            )
            placeholder = "Degree, field, institution, graduation year, and GPA scale."
            why = "This completes education and only shows a GPA when it strengthens the resume."
        category = "education"
        fields = ["degree", "field", "institution", "graduation_date", "gpa"]
    elif next_category == "project":
        if language is PreferredLanguage.AR:
            question = (
                "حدثني عن مشروع أكاديمي أو شخصي مناسب للسيرة: ما هدفه، وما دورك، "
                "وما الأدوات التي استخدمتها؟"
            )
            placeholder = "اسم المشروع أو فكرته، مساهمتك، الأدوات، والنتيجة إن وجدت."
            why = "المشروع يثبت قدرتك العملية خصوصًا إذا كانت خبرتك الوظيفية محدودة."
        else:
            question = (
                "Tell me about a relevant academic or personal project: what was its goal, "
                "what did you contribute, and which tools did you use?"
            )
            placeholder = "Project idea, your contribution, tools, and outcome if known."
            why = (
                "A project demonstrates practical ability, especially with limited work experience."
            )
        category = "project"
        fields = ["goal", "contribution", "tools", "outcome"]
    elif next_category == "skill":
        if language is PreferredLanguage.AR:
            question = (
                "ما الأدوات أو المهارات التي استخدمتها فعليًا في الدراسة أو العمل؟ "
                "أعطني مثالًا بسيطًا لكل مهارة مهمة."
            )
            placeholder = "Excel لإعداد التقارير، Python لتحليل البيانات..."
            why = "المهارة المدعومة بمثال أقوى من قائمة كلمات."
        else:
            question = (
                "Which tools or skills have you actually used in work or study? "
                "Give a short example for each important skill."
            )
            placeholder = "Excel for reporting, Python for data analysis..."
            why = "Skills backed by examples are stronger than a keyword list."
        category = "skill"
        fields = ["skills", "evidence"]
    elif next_category == "certification":
        if language is PreferredLanguage.AR:
            question = "هل لديك شهادة مهنية؟ اذكر اسمها، الجهة المانحة، وسنة الحصول عليها."
            placeholder = "اسم الشهادة، الجهة المانحة، والسنة؛ أو تخطَّ إن لم توجد."
            why = "نضيف فقط الشهادات المهنية الدقيقة والقابلة للعرض."
        else:
            question = (
                "Do you have a professional certification? Share its name, issuer, and year earned."
            )
            placeholder = "Certification, issuer, and year; or skip if none."
            why = "Only accurate, resume-ready certifications should be included."
        category = "certification"
        fields = ["name", "issuer", "year"]
    elif next_category == "language":
        if language is PreferredLanguage.AR:
            question = "ما اللغات التي تستخدمها، وما مستواك الفعلي في كل لغة؟"
            placeholder = "اللغة ومستواك: أساسي، متوسط، متقدم، أو طليق."
            why = "مستوى واضح يجعل قسم اللغات دقيقًا ومفيدًا."
        else:
            question = "Which languages do you use, and what is your actual proficiency in each?"
            placeholder = "Language and level: basic, intermediate, advanced, or fluent."
            why = "Clear proficiency makes the language section accurate and useful."
        category = "language"
        fields = ["language", "proficiency"]
    else:
        if language is PreferredLanguage.AR:
            question = (
                "ما أهم مسؤولية أو إنجاز ما زال ناقصًا من سيرتك؟ وإذا ما عندك رقم دقيق، "
                "صف نطاق العمل أو من استفاد منه."
            )
            placeholder = "صف المهمة، دورك، الأداة، والأثر أو نطاق العمل."
            why = "نقوّي السيرة من دون اختراع أرقام."
        else:
            question = (
                "What important responsibility or achievement is still missing? "
                "If you do not have an exact number, describe the scope or who benefited."
            )
            placeholder = "Describe the task, your role, the tool, and the outcome or scope."
            why = "This improves specificity without inventing metrics."
        category = "achievement"
        fields = ["context", "action", "scope_or_outcome"]
    return {
        "id": f"gap_{category}_{uuid4().hex[:8]}",
        "category": category,
        "fields_requested": fields,
        "question": question,
        "placeholder": placeholder,
        "why_it_matters": why,
        "quick_replies": ["no_exact_metric", "show_example", "skip"],
    }


def _workspace_read(
    workspace: ResumeWorkspace,
    provider: ResumeWriterProvider,
) -> ResumeWorkspaceRead:
    return ResumeWorkspaceRead.model_validate(workspace).model_copy(
        update={
            "conversation_language": _conversation_language(workspace),
            "provider_ready": provider.available,
            "provider": provider.provider_name,
            "model": provider.model if provider.available else None,
            "consent_required": not _has_current_consent(workspace, provider),
        }
    )


def _resume_review_hash(
    *,
    profile: CareerProfile,
    workspace: ResumeWorkspace,
) -> str:
    """Fingerprint every persisted input that can change the rendered PDF."""

    metadata = workspace.provider_metadata if isinstance(workspace.provider_metadata, dict) else {}
    snapshot = {
        "schema_version": "resume_pdf_review.v3",
        "current_draft": workspace.current_draft,
        "evidence_revision": workspace.evidence_revision,
        "profile_full_name": profile.full_name,
        "profile_city": profile.city,
        "language": workspace.language.value,
        "contact": ResumeExportContact.model_validate(workspace.contact).model_dump(mode="json"),
        VERIFIED_SUPPLEMENTAL_TRANSLATIONS_KEY: metadata.get(
            VERIFIED_SUPPLEMENTAL_TRANSLATIONS_KEY
        ),
    }
    return sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


async def _refresh_workspace(
    session: AsyncSession,
    workspace: ResumeWorkspace,
) -> None:
    profile = await session.scalar(
        select(CareerProfile).where(CareerProfile.id == workspace.profile_id)
    )
    if profile and workspace.evidence_revision != profile.evidence_revision:
        workspace.evidence_revision = profile.evidence_revision
        workspace.pending_suggestion = None
        if workspace.current_draft and workspace.stage in {
            ResumeWorkspaceStage.REVIEW,
            ResumeWorkspaceStage.COMPLETE,
        }:
            workspace.stage = ResumeWorkspaceStage.WRITING
        workspace.revision += 1
        workspace.provider_metadata = {
            **workspace.provider_metadata,
            "review_invalidated_reason": "professional_evidence_changed",
        }
    facts = await _workspace_facts(session, workspace)
    draft = (
        ResumeDraftContent.model_validate(workspace.current_draft)
        if workspace.current_draft
        else None
    )
    coverage, score = _coverage(facts, draft)
    workspace.section_coverage = coverage
    workspace.readiness_score = score


def _next_sequence(workspace: ResumeWorkspace) -> int:
    return max((message.sequence for message in workspace.messages), default=0) + 1


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_dump(item) for item in value]
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in value.items()}
    return value


def _evidence_fingerprint(evidence: tuple[Any, ...]) -> str:
    snapshot = [
        {
            "handle": item.handle,
            "category": item.category,
            "label": item.label,
            "detail": item.detail,
            "structured_value": item.structured_value,
            "source_excerpt": item.source_excerpt,
        }
        for item in evidence
    ]
    return sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _store_verified_supplemental_translations(
    workspace: ResumeWorkspace,
    *,
    draft: ResumeDraftContent,
    evidence: tuple[Any, ...],
) -> None:
    """Persist only server-generated verifier proofs, never source evidence or contact PII."""

    metadata = dict(workspace.provider_metadata)
    metadata.pop(VERIFIED_SUPPLEMENTAL_TRANSLATIONS_KEY, None)
    proofs = list(draft.verified_supplemental_translations)
    if proofs:
        # Revalidate the in-memory proof at the persistence boundary.  The source itself remains
        # in CareerFact; metadata receives only its redacted hash and the verified translation.
        verified_supplemental_evidence_overlay(
            evidence,
            language=workspace.language,
            translations=proofs,
        )
        metadata[VERIFIED_SUPPLEMENTAL_TRANSLATIONS_KEY] = {
            "schema_version": VERIFIED_SUPPLEMENTAL_TRANSLATIONS_SCHEMA,
            "language": workspace.language.value,
            "evidence_fingerprint": _evidence_fingerprint(evidence),
            "entries": [proof.model_dump(mode="json") for proof in proofs],
        }
    workspace.provider_metadata = metadata


def _workspace_evidence_with_verified_translations(
    workspace: ResumeWorkspace,
    evidence: tuple[Any, ...],
    *,
    metadata_override: dict[str, Any] | None = None,
) -> tuple[Any, ...]:
    """Rebuild the translation overlay only when every persisted binding is current."""

    metadata = (
        metadata_override
        if metadata_override is not None
        else workspace.provider_metadata
        if isinstance(workspace.provider_metadata, dict)
        else {}
    )
    raw_bundle = metadata.get(VERIFIED_SUPPLEMENTAL_TRANSLATIONS_KEY)
    try:
        if raw_bundle is None:
            proofs: list[ResumeVerifiedSupplementalTranslation] = []
        else:
            if not isinstance(raw_bundle, dict) or set(raw_bundle) != {
                "schema_version",
                "language",
                "evidence_fingerprint",
                "entries",
            }:
                raise ResumeWriterError("Verified supplemental evidence metadata is invalid")
            if (
                raw_bundle.get("schema_version")
                != VERIFIED_SUPPLEMENTAL_TRANSLATIONS_SCHEMA
                or raw_bundle.get("language") != workspace.language.value
                or raw_bundle.get("evidence_fingerprint") != _evidence_fingerprint(evidence)
            ):
                raise ResumeWriterError("Verified supplemental evidence metadata is stale")
            raw_entries = raw_bundle.get("entries")
            if not isinstance(raw_entries, list):
                raise ResumeWriterError("Verified supplemental evidence metadata is invalid")
            proofs = [
                ResumeVerifiedSupplementalTranslation.model_validate(entry)
                for entry in raw_entries
            ]
        return verified_supplemental_evidence_overlay(
            evidence,
            language=workspace.language,
            translations=proofs,
        )
    except (ResumeWriterError, ValueError) as exc:
        raise _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_verified_translation_invalid",
            "Confirmed translated evidence changed or is incomplete; regenerate the resume",
        ) from exc


def _first_interview_section(facts: list[CareerFact]) -> ResumeWriterCategory:
    confirmed_categories = {
        fact.category.value
        for fact in facts
        if fact.verification_status is VerificationStatus.CONFIRMED
    }
    return next(
        (category for category in RESUME_SECTION_ORDER if category not in confirmed_categories),
        RESUME_SECTION_ORDER[-1],
    )


def _next_interview_section(category: str) -> ResumeWriterCategory | None:
    try:
        index = RESUME_SECTION_ORDER.index(cast(ResumeWriterCategory, category))
    except ValueError:
        return RESUME_SECTION_ORDER[0]
    if index + 1 >= len(RESUME_SECTION_ORDER):
        return None
    return RESUME_SECTION_ORDER[index + 1]


def _workspace_conversation(workspace: ResumeWorkspace) -> list[dict[str, str]]:
    return [
        {"role": message.role.value, "content": message.content}
        for message in workspace.messages[-12:]
        if message.role in {ResumeMessageRole.USER, ResumeMessageRole.ASSISTANT}
        and message.content.strip()
    ]


async def _generate_ordered_question(
    provider: ResumeWriterProvider,
    *,
    language: PreferredLanguage,
    evidence: tuple[Any, ...],
    category: ResumeWriterCategory,
    conversation: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    questions = await provider.generate_questions(
        language=language,
        target_role=None,
        evidence=evidence,
        conversation=conversation or [],
        required_category=category,
        max_questions=1,
    )
    if not questions:
        raise ResumeWriterError("Resume writer returned no interview question")
    question = _dump(questions[0])
    if not isinstance(question, dict) or question.get("category") != category:
        raise ResumeWriterError("Resume writer returned an out-of-order interview question")
    question["quick_replies"] = ["no_exact_metric", "show_example", "skip"]
    question["generation_source"] = "ai"
    return question


def _import_flow(workspace: ResumeWorkspace) -> dict[str, Any] | None:
    metadata = workspace.provider_metadata if isinstance(workspace.provider_metadata, dict) else {}
    raw_flow = metadata.get("import_flow")
    return dict(raw_flow) if isinstance(raw_flow, dict) else None


def _additional_information_question(
    language: PreferredLanguage,
    source_id: str,
) -> dict[str, Any]:
    if language is PreferredLanguage.AR:
        question = "ما المعلومات المهمة التي تريد إضافتها ولم تكن موجودة في الملف؟"
        why = "سأحفظ فقط ما تؤكده ثم أعود إلى النواقص المحددة في التحليل."
        placeholder = "مثال: مشروع، تدريب، تطوع، شهادة، أو مسؤولية لم تُذكر في الملف."
    else:
        question = "What important information would you like to add that was not in the file?"
        why = "I will save only what you confirm, then return to the assessed gaps."
        placeholder = (
            "For example, a project, internship, volunteer role, certification, or responsibility."
        )
    return {
        "id": f"additional_information_{source_id.replace('-', '')[-12:]}",
        "category": "achievement",
        "fields_requested": ["additional_information"],
        "question": question,
        "why_it_matters": why,
        "placeholder": placeholder,
        "required": False,
        "quick_replies": ["skip"],
        "generation_source": "server",
    }


async def _question_for_assessment_gap(
    provider: ResumeWriterProvider,
    *,
    workspace: ResumeWorkspace,
    evidence: tuple[Any, ...],
    gap: ResumeAssessmentGap,
) -> dict[str, Any]:
    language = _conversation_language(workspace)
    question_metadata = deterministic_gap_question(gap, language)
    if not provider.available or not _has_current_consent(workspace, provider):
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_unavailable",
            "The AI resume writer is unavailable; retry this gap question",
        )
    try:
        questions = await provider.generate_questions(
            language=language,
            target_role=None,
            evidence=evidence,
            conversation=_workspace_conversation(workspace),
            required_category=cast(ResumeWriterCategory, gap.category.value),
            max_questions=1,
            gap=gap.model_dump(mode="json"),
        )
        if not questions or questions[0].category is not gap.category:
            raise ResumeWriterError(
                "Resume writer returned a question for the wrong assessment gap"
            )
    except ResumeWriterError as exc:
        logger.warning("Assessment gap question generation failed: %s", exc)
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_unavailable",
            "The AI resume writer could not generate the next gap question; retry",
        ) from exc
    generated = questions[0]
    return {
        **question_metadata,
        "question": generated.question,
        "why_it_matters": generated.why_it_matters,
        "placeholder": generated.placeholder,
        "generation_source": "ai",
    }


async def _advance_import_gap(
    *,
    workspace: ResumeWorkspace,
    provider: ResumeWriterProvider,
    evidence: tuple[Any, ...],
) -> dict[str, Any] | None:
    flow = _import_flow(workspace)
    if flow is None:
        return None
    raw_queue = flow.get("gap_queue")
    queue = list(raw_queue) if isinstance(raw_queue, list) else []
    if not queue:
        flow.update(
            {
                "phase": "ready_to_generate",
                "can_generate": True,
                "active_gap_key": None,
                "gap_queue": [],
            }
        )
        workspace.provider_metadata = {
            **workspace.provider_metadata,
            "import_flow": flow,
            "current_question": None,
            "pending_question": None,
        }
        return None
    raw_gap = queue.pop(0)
    try:
        gap = ResumeAssessmentGap.model_validate(raw_gap)
    except ValueError as exc:
        raise ResumeWriterError("Stored resume assessment gap is invalid") from exc
    question = await _question_for_assessment_gap(
        provider,
        workspace=workspace,
        evidence=evidence,
        gap=gap,
    )
    flow.update(
        {
            "phase": "gap_interview",
            "can_generate": False,
            "active_gap_key": gap.key,
            "gap_queue": queue,
        }
    )
    workspace.provider_metadata = {
        **workspace.provider_metadata,
        "import_flow": flow,
        "current_question": question,
        "pending_question": None,
    }
    return question


def _record_import_gap_outcome(
    workspace: ResumeWorkspace,
    outcome_key: str,
) -> None:
    flow = _import_flow(workspace)
    if flow is None:
        return
    active_gap_key = str(flow.get("active_gap_key") or "").strip()
    if not active_gap_key:
        return
    recorded = [str(value) for value in flow.get(outcome_key, []) if str(value).strip()]
    flow[outcome_key] = list(dict.fromkeys([*recorded, active_gap_key]))
    flow["active_gap_key"] = None
    workspace.provider_metadata = {
        **workspace.provider_metadata,
        "import_flow": flow,
    }


def _refresh_import_gap_queue(
    workspace: ResumeWorkspace,
    facts: list[CareerFact],
    *,
    complete_active_gap: bool,
) -> None:
    """Reassess gaps while preserving the user's completed and skipped progress."""

    flow = _import_flow(workspace)
    if flow is None:
        return
    assessment = build_resume_assessment(facts)
    reassessed_keys = {gap.key for gap in assessment.gaps}
    active_gap_key = str(flow.get("active_gap_key") or "").strip()
    if complete_active_gap and active_gap_key and active_gap_key not in reassessed_keys:
        _record_import_gap_outcome(workspace, "completed_gap_keys")
        flow = _import_flow(workspace) or flow
    completed = {str(value) for value in flow.get("completed_gap_keys", []) if str(value).strip()}
    skipped = {str(value) for value in flow.get("skipped_gap_keys", []) if str(value).strip()}
    excluded = completed | skipped
    flow["assessment"] = assessment.model_dump(mode="json")
    flow["gap_queue"] = [
        gap.model_dump(mode="json") for gap in assessment.gaps if gap.key not in excluded
    ]
    flow["active_gap_key"] = None
    workspace.provider_metadata = {
        **workspace.provider_metadata,
        "import_flow": flow,
    }


def _fact_handle(fact: CareerFact) -> str:
    return f"fact_{fact.id.hex}"


def _active_fact_gap_target(
    workspace: ResumeWorkspace,
    facts: list[CareerFact],
) -> tuple[CareerFact, str, list[str], dict[str, Any]] | None:
    """Resolve a fact-specific guided gap without trusting client-authored identifiers."""

    flow = _import_flow(workspace)
    if flow is None or flow.get("phase") != "gap_interview":
        return None
    metadata = workspace.provider_metadata if isinstance(workspace.provider_metadata, dict) else {}
    raw_question = metadata.get("current_question")
    question = dict(raw_question) if isinstance(raw_question, dict) else {}
    gap_key = str(question.get("gap_key") or flow.get("active_gap_key") or "").strip()
    if not gap_key.startswith("fact:"):
        return None

    raw_handles = question.get("evidence_handles")
    raw_fields = question.get("fields_requested")
    if not isinstance(raw_handles, list) or not isinstance(raw_fields, list):
        assessment = flow.get("assessment")
        gaps = assessment.get("gaps") if isinstance(assessment, dict) else None
        matching_gap = next(
            (
                gap
                for gap in gaps or []
                if isinstance(gap, dict) and str(gap.get("key") or "") == gap_key
            ),
            None,
        )
        if isinstance(matching_gap, dict):
            raw_handles = matching_gap.get("evidence_handles")
            raw_fields = matching_gap.get("requested_fields")
    handles = [str(value).strip() for value in raw_handles or [] if str(value).strip()]
    fields = [str(value).strip() for value in raw_fields or [] if str(value).strip()]
    if len(handles) != 1 or not fields or not handles[0].startswith("fact_"):
        return None

    fact_key = gap_key.split(":", 2)[1].replace("-", "").casefold()
    handle_key = handles[0].removeprefix("fact_").replace("-", "").casefold()
    if not fact_key or handle_key != fact_key:
        return None
    target = next(
        (
            fact
            for fact in facts
            if _fact_handle(fact) == handles[0]
            and fact.verification_status is VerificationStatus.CONFIRMED
        ),
        None,
    )
    if target is None:
        return None
    return target, gap_key, list(dict.fromkeys(fields))[:8], question


_GAP_NON_ANSWERS = {
    "n/a",
    "no",
    "none",
    "not sure",
    "i do not know",
    "i don't know",
    "skip",
    "تخطي",
    "لا أعرف",
    "لا اعرف",
    "لا أدري",
    "لا ادري",
    "ما أعرف",
    "ما اعرف",
    "غير متأكد",
}


def _is_gap_non_answer(value: str) -> bool:
    normalized = re.sub(r"[^\w\s']", " ", value.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized in {item.casefold() for item in _GAP_NON_ANSWERS}:
        return True
    return any(
        normalized.startswith(prefix)
        for prefix in (
            "i do not know ",
            "i don't know ",
            "لا أعرف ",
            "لا اعرف ",
            "لا أدري ",
            "لا ادري ",
            "ما أعرف ",
            "ما اعرف ",
        )
    )


def _identity_tokens(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()
    tokens: set[str] = set()
    for raw_token in re.findall(r"\w+", value.casefold(), flags=re.UNICODE):
        if raw_token in {
            "a",
            "an",
            "and",
            "at",
            "of",
            "professional",
            "the",
            "خبرة",
            "شخصية",
            "في",
            "من",
        }:
            continue
        if (
            raw_token.startswith(("invest", "trad", "portfolio"))
            or "استثمار" in raw_token
            or "تداول" in raw_token
            or "محفظ" in raw_token
        ):
            tokens.add("investment_portfolio")
        else:
            tokens.add(raw_token)
    return tokens


def _answer_explicitly_describes_another_record(answer: str) -> bool:
    normalized = re.sub(r"\s+", " ", answer.casefold()).strip()
    return any(
        marker in normalized
        for marker in (
            "also worked",
            "another experience",
            "another job",
            "another role",
            "separate experience",
            "خبرة أخرى",
            "خبرة اخرى",
            "وظيفة أخرى",
            "وظيفة اخرى",
            "عمل آخر",
            "عمل اخر",
            "عملت أيضاً",
            "عملت أيضا",
            "اشتغلت أيضاً",
            "اشتغلت أيضا",
        )
    )


def _record_targets_gap_fact(
    record: dict[str, Any],
    fact: CareerFact,
    *,
    answer: str,
) -> bool:
    """Conservatively distinguish a supplement from a separate same-category record."""

    target_handle = _fact_handle(fact)
    raw_handles = record.get("source_handles")
    handles = {
        str(value).strip()
        for value in (raw_handles if isinstance(raw_handles, list) else [])
        if str(value).strip()
    }
    if target_handle in handles:
        return True
    if _answer_explicitly_describes_another_record(answer):
        return False

    structured = fact.structured_value if isinstance(fact.structured_value, dict) else {}
    target_identity = set()
    for value in (
        fact.label,
        structured.get("title"),
        structured.get("degree"),
        structured.get("name"),
    ):
        target_identity.update(_identity_tokens(value))
    record_identity = set()
    for value in (record.get("title"), record.get("degree"), record.get("name")):
        record_identity.update(_identity_tokens(value))
    if target_identity and record_identity and target_identity & record_identity:
        return True

    anchors = [
        str(record.get(key) or "").strip()
        for key in ("organization", "institution", "issuer")
        if str(record.get(key) or "").strip()
    ]
    title = str(record.get("title") or "").strip()
    # A new role/qualification with its own organization is a separate fact. A bare employer
    # answer (title == employer) remains a valid response to an organization-only gap.
    if anchors and title and all(title.casefold() != anchor.casefold() for anchor in anchors):
        return False
    if anchors and title and any(title.casefold() == anchor.casefold() for anchor in anchors):
        return True
    # A field-of-study answer such as "Finance" has no dedicated canonical property, so the
    # provider must place it in title. Keep this narrow education-only allowance. For every other
    # category, a new non-matching title is a separate record, even when no organization was given.
    if fact.category is FactCategory.EDUCATION and record_identity and not anchors:
        return True
    return not record_identity


def _first_record_field(records: list[dict[str, Any]], *keys: str) -> Any | None:
    for record in records:
        for key in keys:
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
                if cleaned:
                    return cleaned
    return None


def _mapped_gap_field_values(
    requested_fields: list[str],
    records: list[dict[str, Any]],
    *,
    answer: str,
) -> dict[str, Any]:
    aliases: dict[str, tuple[str, ...]] = {
        "degree": ("degree",),
        "field": ("field", "field_of_study", "major", "specialization"),
        "institution": ("institution",),
        "graduation_date": ("graduation_date", "date_range", "year"),
        "organization_or_context": ("organization", "context"),
        "date_range": ("date_range", "year"),
        "responsibility_or_contribution": (
            "responsibilities",
            "outcomes",
            "contribution",
        ),
        "contribution": ("contribution", "responsibilities", "outcomes"),
        "tools": ("tools",),
        "issuer": ("issuer",),
        "year": ("year", "date_range"),
        "proficiency": ("proficiency",),
        "usage_context": ("usage_context", "responsibilities", "outcomes"),
        "example": ("example", "usage_example", "responsibilities", "outcomes"),
    }
    values: dict[str, Any] = {}
    for field in requested_fields:
        value = _first_record_field(records, *aliases.get(field, (field,)))
        if value is None and field == "field":
            # The canonical record schema has no dedicated field-of-study property. A title that
            # is not a degree is the provider's only structured representation of "Finance".
            candidate = _first_record_field(records, "title")
            degree = _first_record_field(records, "degree")
            if candidate is not None and candidate != degree:
                value = candidate
        if value is not None:
            values[field] = value
    if len(requested_fields) == 1:
        # The full answer is the evidence for a direct one-field question. Keep it verbatim even
        # when the provider also returns a shorter normalized value (for example, "personal
        # portfolio"), otherwise qualifications such as "not work for a company" disappear.
        # Never apply this rule to a multi-field gap, where one sentence could falsely complete
        # several unrelated fields.
        values[requested_fields[0]] = answer.strip()[:4_000]
    return values


def _enrich_fact_from_confirmed_gap(
    fact: CareerFact,
    *,
    gap_key: str,
    field_values: dict[str, Any],
    question: dict[str, Any],
    confirmed_text: str,
    source_message_id: str | None,
    confirmed_at: datetime,
) -> None:
    """Attach a confirmed answer to its source fact while keeping explicit provenance."""

    answer = confirmed_text.strip()[:10_000]
    if fact.original_extraction is None:
        fact.original_extraction = {
            "category": fact.category.value,
            "label": fact.label,
            "detail": fact.detail,
            "structured_value": deepcopy(fact.structured_value),
            "source_excerpt": fact.source_excerpt,
            "source_id": str(fact.source_id),
        }
    structured = deepcopy(fact.structured_value) if isinstance(fact.structured_value, dict) else {}
    raw_details = structured.get("supplemental_details")
    supplemental_details = dict(raw_details) if isinstance(raw_details, dict) else {}
    provenance = {
        "kind": "resume_gap_interview",
        "gap_key": gap_key,
        "message_id": source_message_id,
        "confirmed_at": confirmed_at.isoformat(),
    }
    for field, value in field_values.items():
        supplemental_details[field] = {
            "value": value,
            "source": provenance,
        }
    structured["supplemental_details"] = supplemental_details

    raw_addenda = structured.get("supplemental_addenda")
    addenda = list(raw_addenda) if isinstance(raw_addenda, list) else []
    addendum = {
        "text": answer,
        "requested_fields": list(field_values),
        "question": str(question.get("question") or "")[:2_000],
        "source": provenance,
    }
    addenda = [
        value
        for value in addenda
        if not (
            isinstance(value, dict)
            and str(value.get("text") or "").strip().casefold() == answer.casefold()
            and value.get("requested_fields") == list(field_values)
        )
    ]
    structured["supplemental_addenda"] = [*addenda[-19:], addendum]
    fact.structured_value = structured
    if answer and answer.casefold() not in str(fact.detail or "").casefold():
        fact.detail = f"{fact.detail.strip()}\n{answer}" if fact.detail else answer
    fact.user_correction_reason = "User-confirmed guided resume gap answer"
    fact.user_corrected_at = confirmed_at


async def _invalidate_profile_match_analyses(
    session: AsyncSession, *, profile_id: UUID, changed_at: datetime, reason: str
) -> None:
    await session.execute(
        update(MatchAnalysis)
        .where(
            MatchAnalysis.profile_id == profile_id,
            MatchAnalysis.invalidated_at.is_(None),
        )
        .values(invalidated_at=changed_at, invalidation_reason=reason)
    )


async def _invalidate_enriched_fact_dependents(
    session: AsyncSession,
    *,
    workspace: ResumeWorkspace,
    fact_id: UUID,
    changed_at: datetime,
) -> None:
    """Invalidate outputs whose reviewed claims depended on the enriched evidence."""

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
    await _invalidate_profile_match_analyses(
        session,
        profile_id=workspace.profile_id,
        changed_at=changed_at,
        reason="Confirmed resume gap enriched professional evidence",
    )
    workspace.pending_suggestion = None
    if workspace.current_draft and workspace.stage in {
        ResumeWorkspaceStage.REVIEW,
        ResumeWorkspaceStage.COMPLETE,
    }:
        workspace.stage = ResumeWorkspaceStage.WRITING
    workspace.provider_metadata = {
        **workspace.provider_metadata,
        "review_invalidated_reason": "professional_evidence_changed",
    }


def _remap_patch_evidence_handles(
    patch: Any,
    *,
    source_handle_map: dict[str, list[str]],
    created_handles: list[str],
    available_handles: set[str],
) -> Any:
    """Replace ephemeral answer handles with persisted CareerFact handles.

    Adaptive interview responses cite the current answer (``answer_*``), but subsequent writer
    calls only expose persisted facts (``fact_<uuid>``). The draft must never retain the former.
    """

    dumped = _dump(patch)

    def remap_handles(raw_handles: object) -> list[str]:
        if not isinstance(raw_handles, list):
            raw_handles = []
        remapped: list[str] = []
        for raw_handle in raw_handles:
            handle = str(raw_handle).strip()
            if not handle:
                continue
            replacements = source_handle_map.get(handle)
            if replacements:
                remapped.extend(replacements)
            elif handle in available_handles:
                remapped.append(handle)
            elif created_handles:
                # Unknown handles in this one-turn patch can only refer to the current answer.
                remapped.extend(created_handles)
        if not remapped and created_handles:
            remapped.extend(created_handles)
        return list(dict.fromkeys(remapped))[:12]

    def walk(value: Any) -> Any:
        if isinstance(value, list):
            return [walk(item) for item in value]
        if not isinstance(value, dict):
            return value
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"evidence_handles", "summary_evidence_handles"}:
                result[key] = remap_handles(item)
            else:
                result[key] = walk(item)
        return result

    return walk(dumped)


async def _manual_source(
    session: AsyncSession,
    profile_id: UUID,
) -> EvidenceSource:
    manual_sources = list(
        (
            await session.scalars(
                select(EvidenceSource)
                .where(
                    EvidenceSource.profile_id == profile_id,
                    EvidenceSource.kind == SourceKind.MANUAL,
                )
                .order_by(EvidenceSource.created_at)
            )
        ).all()
    )
    for source in manual_sources:
        metadata = source.source_metadata if isinstance(source.source_metadata, dict) else {}
        if (
            metadata.get("created_by") == "resume_workspace_v2"
            or source.label == "Resume workspace conversation"
        ):
            return source
    source = EvidenceSource(
        profile_id=profile_id,
        kind=SourceKind.MANUAL,
        label="Resume workspace conversation",
        source_metadata={
            "created_by": "resume_workspace_v2",
            "professional_data_only": True,
            "raw_narrative_retained": False,
        },
    )
    session.add(source)
    await session.flush()
    return source


def _record_category(record: dict[str, Any], fallback: str) -> FactCategory:
    raw = str(
        record.get("record_type") or record.get("category") or record.get("kind") or fallback
    ).casefold()
    aliases = {"skills": "skill", "projects": "project", "languages": "language"}
    raw = aliases.get(raw, raw)
    try:
        category = FactCategory(raw)
    except ValueError:
        category = FactCategory.ACHIEVEMENT
    return category if category in PROFESSIONAL_CATEGORIES else FactCategory.ACHIEVEMENT


def _record_text_grounded(record: dict[str, Any], *confirmed_texts: str) -> bool:
    """True when every substantive text field of a model-proposed record appears verbatim
    in text the user actually wrote or confirmed."""
    haystack = " ".join(confirmed_texts).casefold()
    values = [
        value.strip()
        for key, value in record.items()
        if key not in {"source", "category", "record_type", "kind"}
        and isinstance(value, str)
        and value.strip()
    ]
    if not values:
        return False
    return all(value.casefold() in haystack for value in values)


def _record_label(record: dict[str, Any], fallback: str) -> str:
    for key in ("title", "name", "degree", "field", "summary", "label"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return fallback.strip()[:500] or "Professional evidence"


def _record_detail(record: dict[str, Any], fallback: str) -> str:
    pieces: list[str] = []
    for key in (
        "organization",
        "institution",
        "issuer",
        "location",
        "date_range",
        "proficiency",
        "honors",
        "detail",
    ):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value.strip())
    for key in (
        "responsibilities",
        "achievements",
        "outcomes",
        "tools",
        "metrics",
        "bullets",
    ):
        value = record.get(key)
        if isinstance(value, list):
            pieces.extend(str(item).strip() for item in value if str(item).strip())
    return " · ".join(dict.fromkeys(pieces))[:20_000] or fallback.strip()[:20_000]


def _draft_from_patch(
    current: dict[str, Any] | None,
    patch: Any,
    *,
    fallback_summary: str,
    language: PreferredLanguage,
) -> ResumeDraftContent | None:
    dumped = _dump(patch)
    if not isinstance(dumped, dict):
        return None
    candidate = dumped.get("draft") if isinstance(dumped.get("draft"), dict) else dumped
    if {"headline", "professional_summary", "summary_evidence_handles", "sections"} <= set(
        candidate
    ):
        try:
            return ResumeDraftContent.model_validate(candidate)
        except ValueError:
            return None
    section_key = str(candidate.get("section_key") or "").casefold()
    if section_key not in {item.value for item in PROFESSIONAL_CATEGORIES}:
        return None
    title = str(candidate.get("title") or fallback_summary).strip()[:500]
    bullets = [
        str(item).strip()[:1_000]
        for item in candidate.get("bullet_candidates", [])
        if str(item).strip()
    ]
    if section_key in {"experience", "trading_experience", "project"} and not bullets:
        bullets = [fallback_summary.strip()[:1_000]] if fallback_summary.strip() else []
    handles = [str(item) for item in candidate.get("evidence_handles", []) if str(item)]
    if not handles:
        return None
    item = {
        "id": f"{section_key}_{uuid4().hex[:12]}",
        "title": title,
        "organization": None,
        "date_range": None,
        "location": None,
        "bullets": bullets,
        "evidence_handles": handles[:12],
    }
    section_titles = {
        "ar": {
            "education": "التعليم",
            "experience": "الخبرة المهنية",
            "certification": "الشهادات",
            "skill": "المهارات",
            "project": "المشاريع",
            "language": "اللغات",
            "achievement": "الإنجازات",
        },
        "en": {
            "education": "Education",
            "experience": "Professional experience",
            "certification": "Certifications",
            "skill": "Skills",
            "project": "Projects",
            "language": "Languages",
            "achievement": "Achievements",
        },
    }
    if not current:
        summary = fallback_summary.strip()
        if len(summary) < 20:
            return None
        merged = {
            "headline": title,
            "professional_summary": summary[:2_500],
            "summary_evidence_handles": handles[:15],
            "sections": [
                {
                    "key": section_key,
                    "title": section_titles[language.value][section_key],
                    "items": [item],
                }
            ],
        }
    else:
        merged = deepcopy(current)
        section = next(
            (row for row in merged["sections"] if row["key"] == section_key),
            None,
        )
        if section:
            section["items"].append(item)
        else:
            merged["sections"].append(
                {
                    "key": section_key,
                    "title": section_titles[language.value][section_key],
                    "items": [item],
                }
            )
    try:
        return ResumeDraftContent.model_validate(merged)
    except ValueError:
        return None


async def _create_version(
    session: AsyncSession,
    workspace: ResumeWorkspace,
    *,
    reason: ResumeDraftVersionReason,
    status_value: ResumeDraftStatus = ResumeDraftStatus.DRAFT,
    diff: dict[str, Any] | None = None,
    base_version_id: UUID | None = None,
    reviewed_by: str | None = None,
    review_hash: str | None = None,
) -> ResumeDraftVersion:
    if not workspace.current_draft:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_draft_required",
            "Create a resume draft before saving a version",
        )
    latest = await session.scalar(
        select(func.max(ResumeDraftVersion.version)).where(
            ResumeDraftVersion.workspace_id == workspace.id
        )
    )
    metadata = workspace.provider_metadata if isinstance(workspace.provider_metadata, dict) else {}
    scope_diff = {
        key: metadata[key]
        for key in (
            "active_import_source_id",
            "generation_fact_ids",
            "generation_evidence_fingerprint",
            VERIFIED_SUPPLEMENTAL_TRANSLATIONS_KEY,
        )
        if key in metadata
    }
    version = ResumeDraftVersion(
        workspace_id=workspace.id,
        version=int(latest or 0) + 1,
        base_version_id=base_version_id,
        reason=reason,
        status=status_value,
        content=workspace.current_draft,
        # Server-owned evidence scope always wins over caller-supplied version annotations.
        diff={**(diff or {}), **scope_diff},
        evidence_revision=workspace.evidence_revision,
        reviewed_at=datetime.now(UTC) if reviewed_by else None,
        reviewed_by_owner_id=reviewed_by,
        review_hash=review_hash,
    )
    session.add(version)
    await session.flush()
    if reason is ResumeDraftVersionReason.MANUAL_EDIT:
        keep_autosave_ids = (
            select(ResumeDraftVersion.id)
            .where(
                ResumeDraftVersion.workspace_id == workspace.id,
                ResumeDraftVersion.reason == ResumeDraftVersionReason.MANUAL_EDIT,
            )
            .order_by(ResumeDraftVersion.version.desc())
            .limit(AUTOSAVE_SNAPSHOT_LIMIT)
        )
        await session.execute(
            delete(ResumeDraftVersion).where(
                ResumeDraftVersion.workspace_id == workspace.id,
                ResumeDraftVersion.reason == ResumeDraftVersionReason.MANUAL_EDIT,
                ResumeDraftVersion.id.not_in(keep_autosave_ids),
            )
        )
    return version


def _quick_action_example(language: PreferredLanguage, category: str) -> str:
    examples = {
        "ar": {
            "education": (
                "مثال: بكالوريوس نظم معلومات من جامعة كذا، تخرجت عام 2024، ومعدلي 4.2 من 5."
            ),
            "experience": (
                "مثال: أنشأت تقارير أسبوعية باستخدام Power BI وساعدت الفريق على متابعة المبيعات."
            ),
            "project": (
                "مثال: بنيت مشروعًا لتحليل البيانات باستخدام Python، وكان دوري "
                "تنظيف البيانات وعرض النتائج."
            ),
            "skill": "مثال: استخدمت Excel لإعداد التقارير وPython لتنظيف البيانات في مشروع جامعي.",
            "achievement": (
                "مثال: نظمت عمل الفريق وسلّمنا المشروع في موعده؛ لا تحتاج إلى اختراع رقم غير معروف."
            ),
        },
        "en": {
            "education": (
                "Example: BSc in Information Systems from Example University, "
                "graduated in 2024 with a 4.2/5 GPA."
            ),
            "experience": (
                "Example: Built weekly Power BI reports that helped the team track sales."
            ),
            "project": (
                "Example: Built a Python data-analysis project; I cleaned the data "
                "and presented the findings."
            ),
            "skill": (
                "Example: Used Excel for reporting and Python for data cleaning "
                "in a university project."
            ),
            "achievement": (
                "Example: Coordinated the team and delivered the project on time; "
                "no invented metric is needed."
            ),
        },
    }
    language_examples = examples[language.value]
    return language_examples.get(category, language_examples["achievement"])


async def _handle_resume_quick_action(
    *,
    session: AsyncSession,
    workspace: ResumeWorkspace,
    provider: ResumeWriterProvider,
    action: str,
    evidence: tuple[Any, ...],
    current_question: dict[str, Any],
    user_message: ResumeMessage,
) -> None:
    """Execute UI commands without ever turning command copy into career evidence."""

    sequence = user_message.sequence + 1
    category = str(current_question.get("category") or "achievement")
    conversation_language = _conversation_language(workspace)
    import_flow = _import_flow(workspace)
    assistant_kind = ResumeMessageKind.STATUS
    structured_payload: dict[str, Any] = {"quick_action": action}

    if action in {"additions_yes", "additions_no"}:
        if import_flow is None or import_flow.get("phase") != "additions_choice":
            raise _api_error(
                status.HTTP_409_CONFLICT,
                "resume_import_phase_conflict",
                "Reload the resume import before choosing whether to add information",
            )
        if action == "additions_yes":
            next_question = _additional_information_question(
                conversation_language,
                str(import_flow.get("source_id") or "resume"),
            )
            import_flow.update(
                {
                    "phase": "additions_interview",
                    "can_generate": False,
                    "active_gap_key": None,
                }
            )
            workspace.provider_metadata = {
                **workspace.provider_metadata,
                "import_flow": import_flow,
                "current_question": next_question,
                "pending_question": None,
            }
            assistant_content = str(next_question["question"])
            assistant_kind = ResumeMessageKind.QUESTION
            structured_payload = {"question": next_question, "quick_action": action}
        else:
            next_question = await _advance_import_gap(
                workspace=workspace,
                provider=provider,
                evidence=evidence,
            )
            if next_question is None:
                assistant_content = (
                    "لم يتبقَّ نقص ذو أولوية. يمكنك الآن كتابة السيرة ومراجعتها."
                    if conversation_language is PreferredLanguage.AR
                    else "No priority gaps remain. You can now write and review the resume."
                )
                structured_payload = {
                    "quick_action": action,
                    "import_flow_phase": "ready_to_generate",
                    "can_generate": True,
                }
            else:
                assistant_content = str(next_question["question"])
                assistant_kind = ResumeMessageKind.QUESTION
                structured_payload = {"question": next_question, "quick_action": action}
    elif action == "show_example":
        assistant_content = _quick_action_example(conversation_language, category)
    elif action == "no_exact_metric":
        if conversation_language is PreferredLanguage.AR:
            assistant_content = (
                "ما يحتاج تخمّن رقمًا. صف نطاق العمل: ماذا أنجزت، من استفاد، "
                "وما الأداة أو المسؤولية التي كانت عليك؟"
            )
            placeholder = "صف المهمة ودورك والأداة ومن استفاد منها، من دون رقم مخمّن."
            why = "النطاق الحقيقي أقوى من رقم غير موثوق."
        else:
            assistant_content = (
                "You do not need to guess a number. Describe the scope: what you did, "
                "who benefited, and which tool or responsibility was yours."
            )
            placeholder = (
                "Describe the task, your role, the tool, and who benefited—without guessing."
            )
            why = "Truthful scope is stronger than an unsupported metric."
        next_question = {
            "id": f"scope_{category}_{uuid4().hex[:8]}",
            "category": (
                category
                if category in {item.value for item in PROFESSIONAL_CATEGORIES}
                else "achievement"
            ),
            "question": assistant_content,
            "placeholder": placeholder,
            "why_it_matters": why,
            "required": False,
        }
        workspace.provider_metadata = {
            **workspace.provider_metadata,
            "current_question": next_question,
            "pending_question": None,
        }
        assistant_kind = ResumeMessageKind.QUESTION
        structured_payload = {"question": next_question, "quick_action": action}
    elif (
        action in {"skip", "continue"}
        and import_flow is not None
        and import_flow.get("phase") in {"additions_interview", "gap_interview"}
    ):
        workspace.pending_understanding = None
        skipped_gap_key = (
            str(import_flow.get("active_gap_key") or "").strip()
            if import_flow.get("phase") == "gap_interview"
            else ""
        )
        next_question = await _advance_import_gap(
            workspace=workspace,
            provider=provider,
            evidence=evidence,
        )
        # Do not record a skip until the next AI question has been generated. A failed provider
        # call therefore leaves the active gap untouched and safe to retry.
        if skipped_gap_key:
            refreshed_flow = _import_flow(workspace)
            if refreshed_flow is not None:
                skipped = [
                    str(value)
                    for value in refreshed_flow.get("skipped_gap_keys", [])
                    if str(value).strip()
                ]
                refreshed_flow["skipped_gap_keys"] = list(
                    dict.fromkeys([*skipped, skipped_gap_key])
                )
                workspace.provider_metadata = {
                    **workspace.provider_metadata,
                    "import_flow": refreshed_flow,
                }
        if next_question is None:
            assistant_content = (
                "اكتملت أسئلة النواقص. يمكنك الآن كتابة السيرة ومراجعتها."
                if conversation_language is PreferredLanguage.AR
                else "The gap questions are complete. You can now write and review the resume."
            )
            structured_payload = {
                "quick_action": action,
                "import_flow_phase": "ready_to_generate",
                "can_generate": True,
            }
        else:
            assistant_content = str(next_question["question"])
            assistant_kind = ResumeMessageKind.QUESTION
            structured_payload = {"question": next_question, "quick_action": action}
    elif action in {"skip", "continue"}:
        workspace.pending_understanding = None
        next_category = _next_interview_section(category)
        if next_category is None:
            assistant_content = (
                "اكتملت أقسام المقابلة الأساسية. يمكنك الآن كتابة السيرة ومراجعتها."
                if conversation_language is PreferredLanguage.AR
                else (
                    "The core interview sections are complete. "
                    "You can now write and review the resume."
                )
            )
            workspace.provider_metadata = {
                **workspace.provider_metadata,
                "current_question": None,
                "pending_question": None,
                "interview_complete": True,
            }
            structured_payload = {"quick_action": action, "interview_complete": True}
        else:
            next_question = await _generate_ordered_question(
                provider,
                language=conversation_language,
                evidence=evidence,
                category=next_category,
                conversation=_workspace_conversation(workspace),
            )
            assistant_content = str(next_question["question"])
            workspace.provider_metadata = {
                **workspace.provider_metadata,
                "current_question": next_question,
                "pending_question": None,
                "interview_complete": False,
            }
            assistant_kind = ResumeMessageKind.QUESTION
            structured_payload = {"question": next_question, "quick_action": action}
    elif action == "improve" and workspace.current_draft is not None:
        workspace.pending_understanding = None
        workspace.pending_suggestion = None
        workspace.stage = ResumeWorkspaceStage.WRITING
        assistant_content = (
            "مسودتك محفوظة. حدّد الملخص أو أي نقطة داخل السيرة، ثم اختر «صياغة أقوى» "
            "أو «احترافية أكثر» لتراجع التحسين قبل اعتماده."
            if conversation_language is PreferredLanguage.AR
            else (
                "Your draft is preserved. Select the summary or any bullet, then choose "
                "a stronger or more professional rewrite to review it before accepting."
            )
        )
        structured_payload = {
            "quick_action": action,
            "draft_preserved": True,
            "improvement_mode": "reviewed_selection",
        }
    elif action in {"generate", "improve", "review"}:
        if (
            import_flow is not None
            and not bool(import_flow.get("can_generate"))
            and (action == "generate" or workspace.current_draft is None)
        ):
            raise _api_error(
                status.HTTP_409_CONFLICT,
                "resume_import_questions_incomplete",
                "Complete or skip the remaining resume gap questions before generating",
            )
        if not evidence:
            raise _api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "resume_writer_evidence_required",
                "Confirm at least one professional fact before generating a resume",
            )
        should_generate = action != "review" or workspace.current_draft is None
        generation_warning: str | None = None
        if should_generate:
            had_draft = workspace.current_draft is not None
            draft: ResumeDraftContent | None = None
            dispatch_revision = workspace.revision
            output_language = workspace.language
            # Release the row lock during the writer round trip; the pending user message
            # is already persisted and results are applied only after re-locking.
            await session.commit()
            try:
                draft = await provider.generate_draft(
                    language=output_language,
                    target_role=None,
                    evidence=evidence,
                    answers=[],
                )
            except ResumeWriterTransportError as exc:
                if not exc.transient:
                    raise
                if had_draft:
                    generation_warning = "ai_unavailable_existing_draft_preserved"
                elif import_flow is not None:
                    raise
                else:
                    draft = build_evidence_fallback_draft(
                        language=output_language,
                        evidence=evidence,
                    )
                    generation_warning = "ai_unavailable_evidence_fallback_created"
            except ResumeWriterOutputError:
                if had_draft:
                    generation_warning = "ai_unavailable_existing_draft_preserved"
                elif import_flow is not None:
                    raise
                else:
                    draft = build_evidence_fallback_draft(
                        language=output_language,
                        evidence=evidence,
                    )
                    generation_warning = "ai_unavailable_evidence_fallback_created"
            workspace = await _relock_workspace_for_dispatch(
                session,
                workspace.profile_id,
                dispatch_revision=dispatch_revision,
                user_message=user_message,
            )
            if draft is not None:
                _store_verified_supplemental_translations(
                    workspace,
                    draft=draft,
                    evidence=evidence,
                )
                workspace.current_draft = draft.model_dump(mode="json")
                workspace.draft_revision += 1
                await _create_version(
                    session,
                    workspace,
                    reason=(
                        ResumeDraftVersionReason.AI_REWRITE
                        if had_draft
                        else ResumeDraftVersionReason.INITIAL_GENERATION
                    ),
                    diff={
                        "quick_action": action,
                        "draft_mode": ("evidence_fallback" if generation_warning else "ai"),
                    },
                )
                current_flow = _import_flow(workspace)
                if current_flow is not None:
                    current_flow.update(
                        {
                            "phase": "draft_review",
                            "can_generate": False,
                            "active_gap_key": None,
                            "gap_queue": [],
                        }
                    )
                    workspace.provider_metadata = {
                        **workspace.provider_metadata,
                        "import_flow": current_flow,
                    }
            workspace.provider_metadata = {
                **workspace.provider_metadata,
                "generation_warning": generation_warning,
            }
        workspace.pending_understanding = None
        workspace.pending_suggestion = None
        workspace.stage = (
            ResumeWorkspaceStage.REVIEW if action == "review" else ResumeWorkspaceStage.WRITING
        )
        if (
            generation_warning == "ai_unavailable_existing_draft_preserved"
            and conversation_language is PreferredLanguage.AR
        ):
            assistant_content = (
                "تعذر الوصول إلى كاتب الذكاء الاصطناعي مؤقتًا، "
                "فأبقيت مسودتك الحالية محفوظة دون تغيير."
            )
        elif generation_warning == "ai_unavailable_existing_draft_preserved":
            assistant_content = (
                "The AI writer is temporarily unavailable, so I kept your current "
                "draft saved without changes."
            )
        elif (
            generation_warning == "ai_unavailable_evidence_fallback_created"
            and conversation_language is PreferredLanguage.AR
        ):
            assistant_content = (
                "تعذر الوصول إلى كاتب الذكاء الاصطناعي مؤقتًا، فأنشأت مسودة "
                "موثقة مباشرة من معلوماتك المؤكدة. يمكنك إعادة المحاولة لاحقًا "
                "لتحسين الصياغة."
            )
        elif generation_warning == "ai_unavailable_evidence_fallback_created":
            assistant_content = (
                "The AI writer is temporarily unavailable, so I created a literal draft "
                "from your confirmed evidence. You can retry later to improve the wording."
            )
        elif conversation_language is PreferredLanguage.AR:
            assistant_content = "جهزت المسودة من الحقائق التي أكّدتها. راجعها وعدّلها قبل التنزيل."
        else:
            assistant_content = (
                "I prepared the draft from your confirmed facts. "
                "Review and edit it before download."
            )
        structured_payload = {
            **structured_payload,
            "generation_warning": generation_warning,
        }
        await _refresh_workspace(session, workspace)
    else:  # Schema validation should make this unreachable.
        raise _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_quick_action_invalid",
            "Unsupported resume command",
        )

    user_message.status = ResumeMessageStatus.SENT
    session.add(
        ResumeMessage(
            workspace_id=workspace.id,
            sequence=sequence,
            role=ResumeMessageRole.ASSISTANT,
            kind=assistant_kind,
            content=assistant_content,
            structured_payload=structured_payload,
            status=ResumeMessageStatus.SENT,
        )
    )
    workspace.revision += 1


@router.post("", response_model=ResumeWorkspaceRead, status_code=status.HTTP_201_CREATED)
async def start_resume_workspace(
    profile_id: UUID,
    payload: ResumeWorkspaceStartCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    if not settings.resume_workspace_v2:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # Locking the parent row also serializes the first workspace creation, when no workspace row
    # exists yet to lock. This prevents duplicate POSTs from surfacing a unique-constraint 500.
    profile = await _owned_profile(session, profile_id, user.id, for_update=True)
    provider = get_resume_writer_provider(settings)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_messages=False,
        include_versions=False,
    )
    if workspace:
        current_conversation_language = _conversation_language(workspace)
        conversation_language = payload.conversation_language or current_conversation_language
        if workspace.current_draft and workspace.language is not payload.language:
            raise _api_error(
                status.HTTP_409_CONFLICT,
                "resume_language_change_requires_new_version",
                "Restore or finish the current draft before changing its language",
            )
        if conversation_language is not current_conversation_language:
            user_message_count = await session.scalar(
                select(func.count(ResumeMessage.id)).where(
                    ResumeMessage.workspace_id == workspace.id,
                    ResumeMessage.role == ResumeMessageRole.USER,
                )
            )
            if user_message_count or workspace.pending_understanding:
                raise _api_error(
                    status.HTTP_409_CONFLICT,
                    "resume_conversation_language_change_not_allowed",
                    "Start a new resume workspace to change the conversation language",
                )
            facts = await _workspace_facts(session, workspace)
            evidence = build_resume_evidence(facts)
            if provider.available and (
                payload.data_sharing_acknowledged or _has_current_consent(workspace, provider)
            ):
                try:
                    question = await _generate_ordered_question(
                        provider,
                        language=conversation_language,
                        evidence=evidence,
                        category=_first_interview_section(facts),
                    )
                except ResumeWriterError as exc:
                    logger.warning("Initial AI resume question failed: %s", exc)
                    raise _api_error(
                        status.HTTP_503_SERVICE_UNAVAILABLE,
                        "resume_writer_unavailable",
                        (
                            "The AI resume writer is temporarily unavailable; "
                            "retry starting the interview"
                        ),
                    ) from exc
            else:
                question = _first_question(conversation_language, facts)
            assistant_question = await session.scalar(
                select(ResumeMessage)
                .where(
                    ResumeMessage.workspace_id == workspace.id,
                    ResumeMessage.role == ResumeMessageRole.ASSISTANT,
                    ResumeMessage.kind == ResumeMessageKind.QUESTION,
                )
                .order_by(ResumeMessage.sequence.desc())
                .limit(1)
            )
            if assistant_question:
                assistant_question.content = question["question"]
                assistant_question.structured_payload = {"question": question}
                assistant_question.status = ResumeMessageStatus.SENT
            else:
                last_sequence = await session.scalar(
                    select(func.max(ResumeMessage.sequence)).where(
                        ResumeMessage.workspace_id == workspace.id
                    )
                )
                session.add(
                    ResumeMessage(
                        workspace_id=workspace.id,
                        sequence=int(last_sequence or 0) + 1,
                        role=ResumeMessageRole.ASSISTANT,
                        kind=ResumeMessageKind.QUESTION,
                        content=question["question"],
                        structured_payload={"question": question},
                        status=ResumeMessageStatus.SENT,
                    )
                )
            workspace.pending_understanding = None
            workspace.revision += 1
            workspace.provider_metadata = {
                **workspace.provider_metadata,
                "current_question": question,
                "pending_question": None,
            }
        elif (
            provider.available
            and payload.data_sharing_acknowledged
            and not workspace.pending_understanding
            and (workspace.provider_metadata.get("current_question") or {}).get("generation_source")
            != "ai"
        ):
            user_message_count = await session.scalar(
                select(func.count(ResumeMessage.id)).where(
                    ResumeMessage.workspace_id == workspace.id,
                    ResumeMessage.role == ResumeMessageRole.USER,
                )
            )
            if not user_message_count:
                facts = await _workspace_facts(session, workspace)
                try:
                    question = await _generate_ordered_question(
                        provider,
                        language=conversation_language,
                        evidence=build_resume_evidence(facts),
                        category=_first_interview_section(facts),
                    )
                except ResumeWriterError as exc:
                    logger.warning("Initial AI resume question refresh failed: %s", exc)
                    raise _api_error(
                        status.HTTP_503_SERVICE_UNAVAILABLE,
                        "resume_writer_unavailable",
                        (
                            "The AI resume writer is temporarily unavailable; "
                            "retry starting the interview"
                        ),
                    ) from exc
                assistant_question = await session.scalar(
                    select(ResumeMessage)
                    .where(
                        ResumeMessage.workspace_id == workspace.id,
                        ResumeMessage.role == ResumeMessageRole.ASSISTANT,
                        ResumeMessage.kind == ResumeMessageKind.QUESTION,
                    )
                    .order_by(ResumeMessage.sequence.desc())
                    .limit(1)
                )
                if assistant_question:
                    assistant_question.content = str(question["question"])
                    assistant_question.structured_payload = {"question": question}
                    assistant_question.status = ResumeMessageStatus.SENT
                workspace.revision += 1
                workspace.provider_metadata = {
                    **workspace.provider_metadata,
                    "current_question": question,
                    "pending_question": None,
                }
        workspace.language = payload.language
        workspace.provider_metadata = {
            **workspace.provider_metadata,
            "conversation_language": conversation_language.value,
            "section_order": list(RESUME_SECTION_ORDER),
        }
        workspace.contact = payload.contact.model_dump(mode="json", exclude_none=True)
        workspace.provider = provider.provider_name
        workspace.model = provider.model if provider.available else None
        if payload.data_sharing_acknowledged:
            workspace.consent_version = _provider_consent_version(provider)
            workspace.consented_at = datetime.now(UTC)
        await _refresh_workspace(session, workspace)
        await session.commit()
        workspace = await _load_workspace(session, profile_id)
        assert workspace is not None
        return _workspace_read(workspace, provider)

    facts = await _profile_facts(session, profile_id)
    conversation_language = payload.conversation_language or payload.language
    evidence = build_resume_evidence(facts)
    if provider.available and payload.data_sharing_acknowledged:
        try:
            question = await _generate_ordered_question(
                provider,
                language=conversation_language,
                evidence=evidence,
                category=_first_interview_section(facts),
            )
        except ResumeWriterError as exc:
            logger.warning("Initial AI resume question failed: %s", exc)
            raise _api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "resume_writer_unavailable",
                "The AI resume writer is temporarily unavailable; retry starting the interview",
            ) from exc
    else:
        question = _first_question(conversation_language, facts)
    workspace = ResumeWorkspace(
        profile_id=profile_id,
        language=payload.language,
        stage=ResumeWorkspaceStage.UNDERSTANDING,
        evidence_revision=profile.evidence_revision,
        contact=payload.contact.model_dump(mode="json", exclude_none=True),
        provider=provider.provider_name,
        model=provider.model if provider.available else None,
        provider_metadata={
            "current_question": question,
            "prompt_version": CONSENT_VERSION,
            "conversation_language": conversation_language.value,
            "section_order": list(RESUME_SECTION_ORDER),
        },
        consent_version=(
            _provider_consent_version(provider) if payload.data_sharing_acknowledged else None
        ),
        consented_at=datetime.now(UTC) if payload.data_sharing_acknowledged else None,
    )
    session.add(workspace)
    await session.flush()
    session.add(
        ResumeMessage(
            workspace_id=workspace.id,
            sequence=1,
            role=ResumeMessageRole.ASSISTANT,
            kind=ResumeMessageKind.QUESTION,
            content=question["question"],
            structured_payload={"question": question},
            status=ResumeMessageStatus.SENT,
        )
    )
    await _refresh_workspace(session, workspace)
    await session.commit()
    workspace = await _load_workspace(session, profile_id)
    assert workspace is not None
    return _workspace_read(workspace, provider)


@router.get("", response_model=ResumeWorkspaceRead)
async def get_resume_workspace(
    profile_id: UUID,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    profile = await _owned_profile(session, profile_id, user.id)
    provider = get_resume_writer_provider(settings)
    workspace = await _load_workspace(session, profile_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
        )
    if workspace.evidence_revision != profile.evidence_revision:
        # Evidence drifted since the last mutation: persist the invalidation once,
        # under a row lock, exactly as the mutation paths do.
        locked = await _load_workspace(
            session,
            profile_id,
            for_update=True,
            include_messages=False,
            include_versions=False,
        )
        if not locked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
            )
        await _refresh_workspace(session, locked)
        locked.provider = provider.provider_name
        locked.model = provider.model if provider.available else None
        await session.commit()
        workspace = await _load_workspace(session, profile_id)
        assert workspace is not None
        return _workspace_read(workspace, provider)
    # Common case: a plain read. Compute coverage in memory so a GET never takes a row
    # lock, bumps the revision, or commits — concurrent tabs must not 409 because of reads.
    facts = await _workspace_facts(session, workspace)
    draft = (
        ResumeDraftContent.model_validate(workspace.current_draft)
        if workspace.current_draft
        else None
    )
    coverage, score = _coverage(facts, draft)
    return _workspace_read(workspace, provider).model_copy(
        update={"section_coverage": coverage, "readiness_score": score}
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_resume_workspace(
    profile_id: UUID,
    user: CurrentUser,
    expected_revision: int = Query(ge=0),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Delete only the resume workspace while retaining confirmed career evidence."""

    # Lock the profile first, matching workspace creation, so reset cannot race a first POST.
    await _owned_profile(session, profile_id, user.id, for_update=True)
    workspace = await _load_workspace(session, profile_id, for_update=True)
    if not workspace:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if expected_revision != workspace.revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_workspace_revision_conflict",
            "The resume workspace changed; reload it before clearing it",
        )
    # `_load_workspace` deliberately limits response relationships to recent rows. Explicit bulk
    # deletes ensure reset removes older rows too, including on SQLite where relying on a partially
    # loaded ORM collection is unsafe. Break the self-referential version chain before deletion.
    await session.execute(delete(ResumeMessage).where(ResumeMessage.workspace_id == workspace.id))
    await session.execute(
        update(ResumeDraftVersion)
        .where(ResumeDraftVersion.workspace_id == workspace.id)
        .values(base_version_id=None)
    )
    await session.execute(
        delete(ResumeDraftVersion).where(ResumeDraftVersion.workspace_id == workspace.id)
    )
    await session.execute(delete(ResumeWorkspace).where(ResumeWorkspace.id == workspace.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import/prepare", response_model=ResumeWorkspaceRead)
async def prepare_resume_import(
    profile_id: UUID,
    payload: ResumeImportDraftCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    """Assess one fully reviewed import and start its guided additions-and-gaps flow."""

    profile = await _owned_profile(session, profile_id, user.id, for_update=True)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_versions=False,
    )
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume workspace not found",
        )
    provider = get_resume_writer_provider(settings)
    metadata = workspace.provider_metadata if isinstance(workspace.provider_metadata, dict) else {}
    flow = _import_flow(workspace)
    if (
        str(metadata.get("last_import_prepare_request_id") or "") == str(payload.client_request_id)
        and isinstance(flow, dict)
        and str(flow.get("source_id") or "") == str(payload.source_id)
    ):
        reloaded = await _load_workspace(session, profile_id)
        assert reloaded is not None
        return _workspace_read(reloaded, provider)
    if flow is not None:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_import_phase_conflict",
            "Finish or clear the active resume import before preparing another file",
        )
    if workspace.current_draft is not None:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_import_draft_exists",
            "Clear the current resume before preparing another imported file",
        )
    if payload.expected_revision != workspace.revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_workspace_revision_conflict",
            "The resume workspace changed; reload it before preparing the import",
        )
    if payload.expected_evidence_revision != profile.evidence_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_evidence_revision_conflict",
            "Professional evidence changed; reload the imported resume",
        )
    source = await session.scalar(
        select(EvidenceSource).where(
            EvidenceSource.id == payload.source_id,
            EvidenceSource.profile_id == profile_id,
            EvidenceSource.kind == SourceKind.CV_UPLOAD,
        )
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume source not found")
    source_facts = list(
        (
            await session.scalars(
                select(CareerFact)
                .where(
                    CareerFact.profile_id == profile_id,
                    CareerFact.source_id == payload.source_id,
                    CareerFact.category.in_(PROFESSIONAL_CATEGORIES),
                )
                .order_by(CareerFact.created_at, CareerFact.id)
            )
        ).all()
    )
    unresolved = [
        fact for fact in source_facts if fact.verification_status is VerificationStatus.EXTRACTED
    ]
    if unresolved:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_import_review_incomplete",
            (
                f"Review every extracted fact before continuing; "
                f"{len(unresolved)} fact(s) remain unresolved"
            ),
        )
    confirmed = [
        fact for fact in source_facts if fact.verification_status is VerificationStatus.CONFIRMED
    ]
    evidence = build_resume_evidence(confirmed)
    if not evidence:
        raise _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_import_confirmed_evidence_required",
            "Confirm at least one useful fact from this file before preparing the resume",
        )
    source_metadata = source.source_metadata if isinstance(source.source_metadata, dict) else {}
    assessment = build_resume_assessment(confirmed, source_metadata)
    assessment_data = assessment.model_dump(mode="json")
    gap_queue = [gap.model_dump(mode="json") for gap in assessment.gaps]
    file_name = source.original_filename or source.label
    import_flow = {
        "phase": "additions_choice",
        "can_generate": False,
        "source_id": str(source.id),
        "file_name": file_name,
        "assessment": assessment_data,
        "gap_queue": gap_queue,
        "active_gap_key": None,
        "completed_gap_keys": [],
        "skipped_gap_keys": [],
        "page_target": 1,
    }
    workspace.revision += 1
    workspace.evidence_revision = profile.evidence_revision
    workspace.pending_understanding = None
    workspace.pending_suggestion = None
    workspace.stage = ResumeWorkspaceStage.UNDERSTANDING
    workspace.provider_metadata = {
        **metadata,
        "active_import_source_id": str(source.id),
        "generation_fact_ids": [str(fact.id) for fact in confirmed],
        "generation_evidence_fingerprint": _evidence_fingerprint(evidence),
        "last_import_prepare_request_id": str(payload.client_request_id),
        "draft_mode": "import_assessment",
        "generation_warning": None,
        "pending_import_source_id": None,
        "pending_import_filename": None,
        "pending_import_analysis_status": None,
        "current_question": None,
        "pending_question": None,
        "import_flow": import_flow,
    }
    message = (
        "اكتمل التقييم المبدئي. قبل أسئلة النواقص، هل تريد إضافة معلومات غير موجودة في الملف؟"
        if _conversation_language(workspace) is PreferredLanguage.AR
        else (
            "The initial assessment is ready. Before the gap questions, would you like to add "
            "information that is not in the file?"
        )
    )
    session.add(
        ResumeMessage(
            workspace_id=workspace.id,
            sequence=_next_sequence(workspace),
            role=ResumeMessageRole.ASSISTANT,
            kind=ResumeMessageKind.STATUS,
            content=message,
            structured_payload={
                "import_flow_phase": "additions_choice",
                "quick_replies": ["additions_yes", "additions_no"],
            },
            status=ResumeMessageStatus.SENT,
        )
    )
    await _refresh_workspace(session, workspace)
    await session.commit()
    workspace = await _load_workspace(session, profile_id)
    assert workspace is not None
    return _workspace_read(workspace, provider)


@router.post("/draft/from-import", response_model=ResumeWorkspaceRead)
async def create_resume_draft_from_import(
    profile_id: UUID,
    payload: ResumeImportDraftCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    """Reject the retired shortcut so every imported resume follows the reviewed ATS flow."""

    await _owned_profile(session, profile_id, user.id)
    raise _api_error(
        status.HTTP_410_GONE,
        "resume_import_guided_flow_required",
        "Use the resume assessment, additions, and gap interview before AI generation",
    )


@router.post("/messages", response_model=ResumeWorkspaceRead)
async def send_resume_message(
    profile_id: UUID,
    payload: ResumeMessageCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    await _owned_profile(session, profile_id, user.id)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_versions=False,
    )
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
        )
    provider = get_resume_writer_provider(settings)
    duplicate = await session.scalar(
        select(ResumeMessage).where(
            ResumeMessage.workspace_id == workspace.id,
            ResumeMessage.client_turn_id == payload.client_turn_id,
        )
    )
    if duplicate:
        reloaded = await _load_workspace(session, profile_id)
        assert reloaded is not None
        return _workspace_read(reloaded, provider)
    await _refresh_workspace(session, workspace)
    if payload.expected_revision != workspace.revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_workspace_revision_conflict",
            "The resume workspace changed; reload it before sending another answer",
        )
    if workspace.pending_understanding is not None:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_understanding_pending",
            "Confirm or correct the current understanding before another action",
        )
    provider_optional_action = payload.quick_action == "additions_yes"
    if not provider.available and not provider_optional_action:
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_not_configured",
            "The AI resume writer is not configured on the server",
        )
    if not _has_current_consent(workspace, provider) and not provider_optional_action:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            "resume_writer_consent_required",
            "Acknowledge sending professional evidence to the AI provider before continuing",
        )

    facts = await _workspace_facts(session, workspace)
    evidence = build_resume_evidence(facts)
    conversation_language = _conversation_language(workspace)
    current_question = dict(workspace.provider_metadata.get("current_question") or {})
    answer = payload.content or str(payload.quick_action or "")
    sequence = _next_sequence(workspace)
    user_message = ResumeMessage(
        workspace_id=workspace.id,
        sequence=sequence,
        role=ResumeMessageRole.USER,
        kind=ResumeMessageKind.TEXT,
        content=answer,
        structured_payload={"quick_action": payload.quick_action},
        status=ResumeMessageStatus.PENDING,
        client_turn_id=payload.client_turn_id,
    )
    session.add(user_message)
    await session.flush()

    if payload.quick_action is not None:
        try:
            await _handle_resume_quick_action(
                session=session,
                workspace=workspace,
                provider=provider,
                action=payload.quick_action,
                evidence=evidence,
                current_question=current_question,
                user_message=user_message,
            )
        except ResumeWriterError as exc:
            logger.warning("Resume workspace quick action failed: %s", exc)
            user_message.status = ResumeMessageStatus.FAILED
            await session.commit()
            raise _api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "resume_writer_unavailable",
                "The AI resume writer is temporarily unavailable; retry the command",
            ) from exc
        await session.commit()
        workspace = await _load_workspace(session, profile_id)
        assert workspace is not None
        return _workspace_read(workspace, provider)

    dispatch_revision = workspace.revision
    output_language = workspace.language
    recent_turns = [
        {"role": message.role.value, "content": message.content}
        for message in workspace.messages[-12:]
    ]
    ordered_conversation = _workspace_conversation(workspace)
    # Release the row lock during the provider round trip: the PENDING user message is
    # already persisted, and a slow upstream must not pin a pooled connection or block
    # every other operation on this workspace.
    await session.commit()
    try:
        adaptive = getattr(provider, "generate_adaptive_turn", None)
        if callable(adaptive):
            result = await adaptive(
                conversation_language=conversation_language,
                output_language=output_language,
                target_role=None,
                evidence=evidence,
                conversation=recent_turns,
                current_question=current_question,
                answer=answer,
                answer_handle=f"answer_{payload.client_turn_id.hex}",
            )
            understanding_payload = _dump(getattr(result, "understanding", None))
            if isinstance(understanding_payload, dict):
                understanding = str(understanding_payload.get("summary") or "").strip()
            else:
                understanding = str(understanding_payload or "").strip()
            # Provider records are model output: strip reserved keys and stamp their
            # origin so confirmation cannot mistake them for user-grounded records.
            proposed_records = [
                {**sanitize_structured_evidence(record), "source": "provider"}
                for record in _dump(getattr(result, "proposed_records", []))
                if isinstance(record, dict)
            ]
            next_question = _dump(getattr(result, "next_question", None))
            draft_patch = _dump(getattr(result, "draft_patch", None))
            ready_to_generate = bool(getattr(result, "ready_to_generate", False))
        else:
            raw_category = str(current_question.get("category") or "")
            required_category = (
                raw_category
                if raw_category in RESUME_SECTION_ORDER
                else _first_interview_section(facts)
            )
            next_question = await _generate_ordered_question(
                provider,
                language=conversation_language,
                evidence=evidence,
                category=cast(ResumeWriterCategory, required_category),
                conversation=ordered_conversation,
            )
            understanding = answer
            proposed_records = [
                {
                    "category": current_question.get("category", "achievement"),
                    "label": answer[:500],
                    "detail": answer,
                    "source": "conversation",
                }
            ]
            draft_patch = None
            ready_to_generate = bool(evidence)
    except ResumeWriterError as exc:
        logger.warning("Resume workspace adaptive turn failed: %s", exc)
        user_message.status = ResumeMessageStatus.FAILED
        await session.commit()
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_unavailable",
            "The AI resume writer is temporarily unavailable; your answer was saved",
        ) from exc

    workspace = await _relock_workspace_for_dispatch(
        session,
        profile_id,
        dispatch_revision=dispatch_revision,
        user_message=user_message,
    )
    understanding_id = uuid4()
    pending = {
        "id": str(understanding_id),
        "answer": answer,
        "understanding": understanding or answer,
        "understanding_detail": (
            understanding_payload
            if "understanding_payload" in locals()
            else {"summary": understanding or answer}
        ),
        "proposed_records": proposed_records or [],
        "next_question": next_question,
        "draft_patch": draft_patch,
        "ready_to_generate": ready_to_generate,
        "quick_action": payload.quick_action,
        "question": current_question,
        "source_message_id": str(user_message.id),
    }
    user_message.status = ResumeMessageStatus.SENT
    assistant_message = ResumeMessage(
        workspace_id=workspace.id,
        sequence=sequence + 1,
        role=ResumeMessageRole.ASSISTANT,
        kind=ResumeMessageKind.UNDERSTANDING,
        content=understanding or answer,
        structured_payload={"understanding": pending},
        status=ResumeMessageStatus.PENDING,
    )
    session.add(assistant_message)
    workspace.pending_understanding = pending
    workspace.revision += 1
    workspace.provider_metadata = {
        **workspace.provider_metadata,
        "pending_question": next_question,
    }
    await session.commit()
    workspace = await _load_workspace(session, profile_id)
    assert workspace is not None
    return _workspace_read(workspace, provider)


async def _relock_workspace_for_dispatch(
    session: AsyncSession,
    profile_id: UUID,
    *,
    dispatch_revision: int,
    dispatch_draft_revision: int | None = None,
    user_message: ResumeMessage | None = None,
) -> ResumeWorkspace:
    """Re-acquire the workspace row lock after a provider round trip.

    Provider calls run with the transaction committed so a slow upstream never pins a
    pooled connection or blocks other workspace operations. This verifies nothing else
    mutated the workspace while the lock was released before results are applied.
    """
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_versions=False,
    )
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
        )
    draft_conflict = (
        dispatch_draft_revision is not None
        and workspace.draft_revision != dispatch_draft_revision
    )
    if workspace.revision != dispatch_revision or draft_conflict:
        if user_message is not None:
            user_message.status = ResumeMessageStatus.FAILED
            await session.commit()
        if draft_conflict:
            raise _api_error(
                status.HTTP_409_CONFLICT,
                "resume_draft_revision_conflict",
                "The resume draft changed while the assistant was responding; "
                "reload it and retry",
            )
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_workspace_revision_conflict",
            "The resume workspace changed while the assistant was responding; "
            "reload it and retry",
        )
    return workspace


def _pending_understanding(
    workspace: ResumeWorkspace,
    understanding_id: UUID,
) -> dict[str, Any]:
    pending = dict(workspace.pending_understanding or {})
    if pending.get("id") != str(understanding_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Understanding not found")
    return pending


@router.post(
    "/understandings/{understanding_id}/confirm",
    response_model=ResumeWorkspaceRead,
)
async def confirm_resume_understanding(
    profile_id: UUID,
    understanding_id: UUID,
    payload: ResumeUnderstandingActionCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    profile = await _owned_profile(session, profile_id, user.id, for_update=True)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_versions=False,
    )
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
        )
    provider = get_resume_writer_provider(settings)
    await _refresh_workspace(session, workspace)
    if payload.expected_revision != workspace.revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_workspace_revision_conflict",
            "The resume workspace changed; reload before confirming",
        )
    pending = _pending_understanding(workspace, understanding_id)
    text = payload.corrected_text or str(pending.get("understanding") or "")
    confirmed_answer = payload.corrected_text or str(pending.get("answer") or text)
    records = list(pending.get("proposed_records") or [])
    if payload.corrected_text:
        pending["draft_patch"] = None
        pending["next_question"] = None
        pending["ready_to_generate"] = False
        pending["quick_action"] = None
        pending["corrected_by_user"] = True
        records = [
            {
                "category": (pending.get("question") or {}).get("category", "achievement"),
                "label": payload.corrected_text[:500],
                "detail": payload.corrected_text,
                "source": "user_correction",
            }
        ]
    now = datetime.now(UTC)
    existing_generation_facts = await _workspace_facts(session, workspace)
    fact_gap_target = _active_fact_gap_target(workspace, existing_generation_facts)
    enriched_fact: CareerFact | None = None
    if fact_gap_target is not None and _is_gap_non_answer(confirmed_answer):
        # A confirmed "I don't know" is interview progress, not professional evidence.
        records = []
    elif fact_gap_target is not None:
        target, gap_key, requested_fields, current_gap_question = fact_gap_target
        normalized_records = [record for record in records if isinstance(record, dict)]
        target_records: list[dict[str, Any]] = []
        remaining_records: list[Any] = []
        for raw_record in records:
            if not isinstance(raw_record, dict):
                remaining_records.append(raw_record)
                continue
            if _record_category(
                raw_record, target.category.value
            ) is target.category and _record_targets_gap_fact(
                raw_record, target, answer=confirmed_answer
            ):
                target_records.append(raw_record)
            else:
                remaining_records.append(raw_record)
        field_values = (
            _mapped_gap_field_values(
                requested_fields,
                target_records,
                answer=confirmed_answer,
            )
            if target_records or not normalized_records
            else {}
        )
        if field_values:
            enriched_fact = target
            _enrich_fact_from_confirmed_gap(
                enriched_fact,
                gap_key=gap_key,
                field_values=field_values,
                question=current_gap_question,
                confirmed_text=confirmed_answer,
                source_message_id=str(pending.get("source_message_id") or "") or None,
                confirmed_at=now,
            )
        # Records mapped to the existing fact are consumed even if they did not safely resolve a
        # field. Distinct records remain eligible to become their own confirmed facts.
        if target_records:
            records = remaining_records
    created_facts: list[CareerFact] = []
    fact_records: list[tuple[CareerFact, dict[str, Any]]] = []
    if records:
        source = await _manual_source(session, profile_id)
        for raw_record in records[:12]:
            record = sanitize_structured_evidence(
                dict(raw_record) if isinstance(raw_record, dict) else {"label": str(raw_record)}
            )
            category = _record_category(
                record, str((pending.get("question") or {}).get("category", "achievement"))
            )
            label = _record_label(record, text)
            detail = _record_detail(record, text)
            # The user confirmed a prose summary, not the structured records. Records whose
            # text is the user's own words stay confirmed; anything the model invented beyond
            # that goes through the normal review queue before it can feed matching or export.
            grounded = record.get("source") in {"conversation", "user_correction"} or (
                _record_text_grounded(record, confirmed_answer, text)
            )
            fact = CareerFact(
                profile_id=profile_id,
                source_id=source.id,
                category=category,
                label=label,
                detail=detail,
                structured_value={**record, "record_version": "resume-records-v2"},
                source_excerpt=text[:10_000],
                verification_status=(
                    VerificationStatus.CONFIRMED if grounded else VerificationStatus.EXTRACTED
                ),
                extraction_confidence=1.0 if grounded else None,
                confirmed_at=now if grounded else None,
                original_extraction=record,
            )
            session.add(fact)
            created_facts.append(fact)
            fact_records.append((fact, record))
    if created_facts or enriched_fact is not None:
        profile.evidence_revision += 1
        workspace.evidence_revision = profile.evidence_revision
    if enriched_fact is not None:
        await _invalidate_enriched_fact_dependents(
            session,
            workspace=workspace,
            fact_id=enriched_fact.id,
            changed_at=now,
        )
    elif any(
        fact.verification_status is VerificationStatus.CONFIRMED for fact in created_facts
    ):
        # New confirmed evidence changes matching inputs the same way an enrichment does;
        # stale analyses must not keep presenting pre-change coverage as current.
        await _invalidate_profile_match_analyses(
            session,
            profile_id=workspace.profile_id,
            changed_at=now,
            reason="New confirmed professional evidence was added",
        )

    await session.flush()
    source_handle_map: dict[str, list[str]] = {}
    created_handles = [_fact_handle(fact) for fact in created_facts]
    affected_handles = list(
        dict.fromkeys(
            [
                *created_handles,
                *([_fact_handle(enriched_fact)] if enriched_fact is not None else []),
            ]
        )
    )
    raw_generation_fact_ids = workspace.provider_metadata.get("generation_fact_ids")
    if isinstance(raw_generation_fact_ids, list) and created_facts:
        workspace.provider_metadata = {
            **workspace.provider_metadata,
            "generation_fact_ids": list(
                dict.fromkeys(
                    [
                        *(str(value) for value in raw_generation_fact_ids),
                        *(str(fact.id) for fact in created_facts),
                    ]
                )
            ),
        }
    for fact, record in fact_records:
        actual_handle = _fact_handle(fact)
        raw_handles = record.get("source_handles")
        if isinstance(raw_handles, list):
            for raw_handle in raw_handles:
                handle = str(raw_handle).strip()
                if handle:
                    source_handle_map.setdefault(handle, []).append(actual_handle)
    understanding_detail = pending.get("understanding_detail")
    if isinstance(understanding_detail, dict):
        raw_handles = understanding_detail.get("evidence_handles")
        if isinstance(raw_handles, list):
            for raw_handle in raw_handles:
                handle = str(raw_handle).strip()
                if handle and affected_handles:
                    source_handle_map.setdefault(handle, []).extend(affected_handles)
    confirmed_facts = await _workspace_facts(session, workspace)
    confirmed_evidence = build_resume_evidence(confirmed_facts)
    remapped_patch = _remap_patch_evidence_handles(
        pending.get("draft_patch"),
        source_handle_map=source_handle_map,
        created_handles=affected_handles,
        available_handles={item.handle for item in confirmed_evidence},
    )
    if created_facts or enriched_fact is not None:
        workspace.provider_metadata = {
            **workspace.provider_metadata,
            "generation_evidence_fingerprint": _evidence_fingerprint(confirmed_evidence),
        }
    if remapped_patch and not resume_patch_uses_requested_language(
        remapped_patch,
        workspace.language,
    ):
        remapped_patch = None
        workspace.provider_metadata = {
            **workspace.provider_metadata,
            "generation_warning": "draft_patch_language_mismatch",
        }
    draft: ResumeDraftContent | None = None
    draft_generation_evidence: tuple[Any, ...] | None = None
    explicit_generation = pending.get("quick_action") in {"generate", "review"}
    guided_import_flow = _import_flow(workspace)
    should_generate_full_draft = (
        (bool(pending.get("ready_to_generate")) or explicit_generation)
        and (
            workspace.current_draft is None or pending.get("quick_action") in {"generate", "review"}
        )
        and (guided_import_flow is None or explicit_generation)
    )
    revision_already_bumped = False
    if should_generate_full_draft:
        generation_facts = await _workspace_facts(session, workspace)
        draft_generation_evidence = build_resume_evidence(generation_facts)
        output_language = workspace.language
        # Consume the pending understanding and persist the confirmed evidence before
        # the writer round trip, then release the row locks: the bumped revision makes a
        # duplicate confirm 409 instead of double-creating facts, and a slow provider no
        # longer pins a pooled connection or serializes other workspace operations.
        workspace.pending_understanding = None
        workspace.revision += 1
        revision_already_bumped = True
        dispatch_revision = workspace.revision
        await session.commit()
        generation_failed = False
        try:
            draft = await provider.generate_draft(
                language=output_language,
                target_role=None,
                evidence=draft_generation_evidence,
                answers=[],
            )
        except ResumeWriterError as exc:
            logger.warning("Resume workspace full generation failed: %s", exc)
            generation_failed = True
        await _owned_profile(session, profile_id, user.id, for_update=True)
        workspace = await _relock_workspace_for_dispatch(
            session, profile_id, dispatch_revision=dispatch_revision
        )
        if generation_failed:
            workspace.provider_metadata = {
                **workspace.provider_metadata,
                "generation_warning": "full_generation_unavailable",
            }
        else:
            workspace.provider_metadata = {
                **workspace.provider_metadata,
                "last_full_generation_at": datetime.now(UTC).isoformat(),
                "generation_warning": None,
            }
    if (
        draft is None
        and remapped_patch
        and (
            workspace.current_draft is not None
            or _conversation_language(workspace) is workspace.language
        )
        and (guided_import_flow is None or workspace.current_draft is not None)
    ):
        # When the interview and resume languages differ, the conversational understanding is
        # not a safe professional-summary fallback for a brand-new draft. Wait for the full
        # writer pass, which validates the requested output language. Existing drafts can still
        # receive a provider-authored patch in the output language.
        draft = _draft_from_patch(
            workspace.current_draft,
            remapped_patch,
            fallback_summary=text,
            language=workspace.language,
        )
    if draft:
        if draft_generation_evidence is not None:
            _store_verified_supplemental_translations(
                workspace,
                draft=draft,
                evidence=draft_generation_evidence,
            )
        workspace.current_draft = draft.model_dump(mode="json")
        workspace.draft_revision += 1
        workspace.pending_suggestion = None
        await _create_version(
            session,
            workspace,
            reason=ResumeDraftVersionReason.INITIAL_GENERATION,
            diff={"understanding_id": str(understanding_id)},
        )
        workspace.stage = ResumeWorkspaceStage.WRITING
    next_question = pending.get("next_question")
    current_import_flow = _import_flow(workspace)
    if current_import_flow is not None and current_import_flow.get("phase") in {
        "additions_interview",
        "gap_interview",
    }:
        _refresh_import_gap_queue(
            workspace,
            confirmed_facts,
            complete_active_gap=current_import_flow.get("phase") == "gap_interview",
        )
        next_question = await _advance_import_gap(
            workspace=workspace,
            provider=provider,
            evidence=confirmed_evidence,
        )
    elif pending.get("corrected_by_user") and not next_question:
        corrected_facts = await _workspace_facts(session, workspace)
        raw_category = str((pending.get("question") or {}).get("category") or "")
        corrected_category = (
            cast(ResumeWriterCategory, raw_category)
            if raw_category in RESUME_SECTION_ORDER
            else _first_interview_section(corrected_facts)
        )
        if provider.available and _has_current_consent(workspace, provider):
            try:
                next_question = await _generate_ordered_question(
                    provider,
                    language=_conversation_language(workspace),
                    evidence=build_resume_evidence(corrected_facts),
                    category=corrected_category,
                    conversation=_workspace_conversation(workspace),
                )
            except ResumeWriterError as exc:
                logger.warning("Corrected-answer follow-up generation failed: %s", exc)
                next_question = _first_question(
                    _conversation_language(workspace),
                    corrected_facts,
                )
        else:
            next_question = _first_question(
                _conversation_language(workspace),
                corrected_facts,
            )
    workspace.pending_understanding = None
    if not revision_already_bumped:
        workspace.revision += 1
    if isinstance(next_question, dict) and next_question.get("question"):
        sequence = _next_sequence(workspace)
        session.add(
            ResumeMessage(
                workspace_id=workspace.id,
                sequence=sequence,
                role=ResumeMessageRole.ASSISTANT,
                kind=ResumeMessageKind.QUESTION,
                content=str(next_question["question"]),
                structured_payload={"question": next_question},
                status=ResumeMessageStatus.SENT,
            )
        )
        workspace.provider_metadata = {
            **workspace.provider_metadata,
            "current_question": next_question,
            "pending_question": None,
        }
    facts = await _workspace_facts(session, workspace)
    active_draft = draft or (
        ResumeDraftContent.model_validate(workspace.current_draft)
        if workspace.current_draft
        else None
    )
    coverage, score = _coverage(facts, active_draft)
    workspace.section_coverage = coverage
    workspace.readiness_score = score
    await session.commit()
    workspace = await _load_workspace(session, profile_id)
    assert workspace is not None
    return _workspace_read(workspace, provider)


@router.post(
    "/understandings/{understanding_id}/correct",
    response_model=ResumeWorkspaceRead,
)
async def correct_resume_understanding(
    profile_id: UUID,
    understanding_id: UUID,
    payload: ResumeUnderstandingActionCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    await _owned_profile(session, profile_id, user.id)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_versions=False,
    )
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
        )
    if payload.expected_revision != workspace.revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_workspace_revision_conflict",
            "The resume workspace changed; reload before correcting",
        )
    if not payload.corrected_text:
        raise _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_correction_required",
            "Enter the corrected understanding",
        )
    pending = _pending_understanding(workspace, understanding_id)
    pending["understanding"] = payload.corrected_text
    pending["proposed_records"] = [
        {
            "category": (pending.get("question") or {}).get("category", "achievement"),
            "label": payload.corrected_text[:500],
            "detail": payload.corrected_text,
            "source": "user_correction",
        }
    ]
    # All downstream AI output was based on the interpretation the user just rejected.
    # Keeping any of it would silently re-introduce the incorrect wording on confirmation.
    pending["draft_patch"] = None
    pending["next_question"] = None
    pending["ready_to_generate"] = False
    pending["quick_action"] = None
    pending["corrected_by_user"] = True
    workspace.pending_understanding = pending
    workspace.revision += 1
    sequence = _next_sequence(workspace)
    session.add(
        ResumeMessage(
            workspace_id=workspace.id,
            sequence=sequence,
            role=ResumeMessageRole.USER,
            kind=ResumeMessageKind.UNDERSTANDING,
            content=payload.corrected_text,
            structured_payload={"corrects_understanding_id": str(understanding_id)},
            status=ResumeMessageStatus.CORRECTED,
        )
    )
    await session.commit()
    workspace = await _load_workspace(session, profile_id)
    assert workspace is not None
    return _workspace_read(workspace, get_resume_writer_provider(settings))


@router.patch("/draft", response_model=ResumeWorkspaceRead)
async def patch_resume_draft(
    profile_id: UUID,
    payload: ResumeDraftPatchCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    await _owned_profile(session, profile_id, user.id)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_messages=False,
        include_versions=False,
    )
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
        )
    import_flow = _import_flow(workspace)
    if workspace.current_draft is None:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_draft_required",
            "Generate the resume draft before editing it",
        )
    if import_flow is not None and import_flow.get("phase") != "draft_review":
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_import_phase_conflict",
            "Complete the guided import and generate the AI draft before editing",
        )
    if payload.expected_draft_revision != workspace.draft_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_draft_revision_conflict",
            "The resume draft changed; reload it before saving",
        )
    before_hash = sha256(
        json.dumps(workspace.current_draft or {}, sort_keys=True).encode()
    ).hexdigest()
    workspace.current_draft = payload.draft.model_dump(mode="json")
    workspace.draft_revision += 1
    workspace.pending_suggestion = None
    workspace.revision += 1
    workspace.stage = ResumeWorkspaceStage.WRITING
    await _create_version(
        session,
        workspace,
        reason=ResumeDraftVersionReason.MANUAL_EDIT,
        diff={"before_hash": before_hash},
    )
    await _refresh_workspace(session, workspace)
    await session.commit()
    workspace = await _load_workspace(session, profile_id)
    assert workspace is not None
    return _workspace_read(workspace, get_resume_writer_provider(settings))


def _target_text(draft: ResumeDraftContent, payload: ResumeRewriteCreate) -> tuple[str, list[str]]:
    if payload.target_kind == "headline":
        return draft.headline, list(draft.summary_evidence_handles)
    if payload.target_kind == "professional_summary":
        return draft.professional_summary, list(draft.summary_evidence_handles)
    section = next(
        (item for item in draft.sections if item.key == payload.section_key),
        None,
    )
    if not section:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume section not found"
        )
    item = next((item for item in section.items if item.id == payload.item_id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume item not found")
    assert payload.bullet_index is not None
    if payload.bullet_index >= len(item.bullets):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume bullet not found")
    return item.bullets[payload.bullet_index], list(item.evidence_handles)


def _rewrite_instruction(payload: ResumeRewriteCreate) -> str:
    if payload.mode == "custom":
        assert payload.instruction
        return payload.instruction
    target = {
        "headline": "professional headline",
        "professional_summary": "professional summary",
        "bullet": "resume bullet",
    }[payload.target_kind]
    if payload.mode == "shorter":
        return (
            f"Shorten this {target} without dropping any supported number, date, proper noun, "
            "tool, responsibility, result, or negation."
        )
    if payload.mode == "professional":
        return (
            f"Rewrite this {target} with polished, natural professional wording. "
            "For a resume bullet, keep one sentence and avoid repetitive sentence openings. "
            "Preserve every fact and invent no outcome or metric."
        )
    return (
        f"Strengthen this {target} with a concise evidence-grounded action verb. "
        "For a resume bullet, keep one sentence. Preserve every fact and invent no "
        "outcome or metric."
    )


@router.post("/draft/rewrite", response_model=ResumeRewriteSuggestionRead)
async def rewrite_resume_draft(
    profile_id: UUID,
    payload: ResumeRewriteCreate,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeRewriteSuggestionRead:
    await _owned_profile(session, profile_id, user.id)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_messages=False,
        include_versions=False,
    )
    if not workspace or not workspace.current_draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume draft not found")
    import_flow = _import_flow(workspace)
    if import_flow is not None and import_flow.get("phase") != "draft_review":
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_import_phase_conflict",
            "Complete the guided import and generate the AI draft before rewriting",
        )
    await _refresh_workspace(session, workspace)
    if payload.expected_draft_revision != workspace.draft_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_draft_revision_conflict",
            "The resume draft changed; reload before requesting a rewrite",
        )
    provider = get_resume_writer_provider(settings)
    if not provider.available or not _has_current_consent(workspace, provider):
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_not_configured",
            "The AI resume writer is not available for rewriting",
        )
    draft = ResumeDraftContent.model_validate(workspace.current_draft)
    original_text, handles = _target_text(draft, payload)
    rewrite = getattr(provider, "rewrite_section", None)
    if not callable(rewrite):
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_rewrite_not_supported",
            "The configured resume writer does not support section rewrites",
        )
    evidence = _workspace_evidence_with_verified_translations(
        workspace,
        build_resume_evidence(await _workspace_facts(session, workspace)),
    )
    instruction = _rewrite_instruction(payload)
    dispatch_revision = workspace.revision
    dispatch_draft_revision = workspace.draft_revision
    output_language = workspace.language
    # Release the row locks while the rewrite round trip runs.
    await session.commit()
    try:
        candidate = await rewrite(
            language=output_language,
            target_role=None,
            evidence=evidence,
            section_key=payload.section_key or payload.target_kind,
            item_id=payload.item_id,
            original_text=original_text,
            instruction=instruction,
            evidence_handles=handles,
        )
    except ResumeWriterError as exc:
        logger.warning("Resume workspace rewrite failed: %s", exc)
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_unavailable",
            "The AI resume rewrite is temporarily unavailable",
        ) from exc
    after_text = str(getattr(candidate, "text", getattr(candidate, "after_text", ""))).strip()
    candidate_handles = list(getattr(candidate, "evidence_handles", handles))
    if not after_text:
        raise _api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resume_writer_unavailable",
            "The AI resume writer returned no usable rewrite",
        )
    workspace = await _relock_workspace_for_dispatch(
        session,
        profile_id,
        dispatch_revision=dispatch_revision,
        dispatch_draft_revision=dispatch_draft_revision,
    )
    suggestion = ResumeRewriteSuggestionRead(
        suggestion_id=uuid4(),
        target_kind=payload.target_kind,
        section_key=payload.section_key,
        item_id=payload.item_id,
        bullet_index=payload.bullet_index,
        mode=payload.mode,
        instruction=payload.instruction,
        before_text=original_text,
        after_text=after_text,
        base_draft_revision=workspace.draft_revision,
        evidence_handles=candidate_handles,
    )
    workspace.pending_suggestion = suggestion.model_dump(mode="json")
    workspace.stage = ResumeWorkspaceStage.REVIEW
    workspace.revision += 1
    await session.commit()
    return suggestion


def _apply_suggestion(
    draft: ResumeDraftContent,
    suggestion: ResumeRewriteSuggestionRead,
) -> ResumeDraftContent:
    data = draft.model_dump(mode="json")
    if suggestion.target_kind == "headline":
        data["headline"] = suggestion.after_text
    elif suggestion.target_kind == "professional_summary":
        data["professional_summary"] = suggestion.after_text
    else:
        section = next(
            (item for item in data["sections"] if item["key"] == suggestion.section_key),
            None,
        )
        if not section:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Resume section not found"
            )
        item = next(
            (row for row in section["items"] if row["id"] == suggestion.item_id),
            None,
        )
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Resume item not found"
            )
        assert suggestion.bullet_index is not None
        if suggestion.bullet_index >= len(item["bullets"]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume bullet not found",
            )
        item["bullets"][suggestion.bullet_index] = suggestion.after_text
    return ResumeDraftContent.model_validate(data)


async def _suggestion_action(
    *,
    profile_id: UUID,
    suggestion_id: UUID,
    expected_draft_revision: int,
    accept: bool,
    user: CurrentUser,
    settings: Settings,
    session: AsyncSession,
) -> ResumeWorkspaceRead:
    await _owned_profile(session, profile_id, user.id)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_messages=False,
        include_versions=False,
    )
    if not workspace or not workspace.current_draft or not workspace.pending_suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume suggestion not found"
        )
    await _refresh_workspace(session, workspace)
    if not workspace.pending_suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume suggestion not found"
        )
    suggestion = ResumeRewriteSuggestionRead.model_validate(workspace.pending_suggestion)
    if suggestion.suggestion_id != suggestion_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume suggestion not found"
        )
    if accept and suggestion.base_draft_revision != workspace.draft_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_suggestion_stale",
            "The resume draft changed; request a new rewrite before applying it",
        )
    if expected_draft_revision != workspace.draft_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_draft_revision_conflict",
            "The resume draft changed; reload before applying this suggestion",
        )
    if accept:
        draft = _apply_suggestion(
            ResumeDraftContent.model_validate(workspace.current_draft),
            suggestion,
        )
        workspace.current_draft = draft.model_dump(mode="json")
        workspace.draft_revision += 1
        await _create_version(
            session,
            workspace,
            reason=ResumeDraftVersionReason.AI_REWRITE,
            diff={"suggestion": suggestion.model_dump(mode="json")},
        )
    workspace.pending_suggestion = None
    workspace.revision += 1
    await session.commit()
    workspace = await _load_workspace(session, profile_id)
    assert workspace is not None
    return _workspace_read(workspace, get_resume_writer_provider(settings))


@router.post("/draft/suggestions/{suggestion_id}/accept", response_model=ResumeWorkspaceRead)
async def accept_resume_suggestion(
    profile_id: UUID,
    suggestion_id: UUID,
    user: CurrentUser,
    payload: ResumeDraftRevisionCreate,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    return await _suggestion_action(
        profile_id=profile_id,
        suggestion_id=suggestion_id,
        expected_draft_revision=payload.expected_draft_revision,
        accept=True,
        user=user,
        settings=settings,
        session=session,
    )


@router.post("/draft/suggestions/{suggestion_id}/reject", response_model=ResumeWorkspaceRead)
async def reject_resume_suggestion(
    profile_id: UUID,
    suggestion_id: UUID,
    user: CurrentUser,
    payload: ResumeDraftRevisionCreate,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    return await _suggestion_action(
        profile_id=profile_id,
        suggestion_id=suggestion_id,
        expected_draft_revision=payload.expected_draft_revision,
        accept=False,
        user=user,
        settings=settings,
        session=session,
    )


@router.get("/versions", response_model=list[ResumeDraftVersionRead])
async def list_resume_versions(
    profile_id: UUID,
    user: CurrentUser,
    limit: int = Query(
        default=VERSION_HISTORY_DEFAULT_LIMIT,
        ge=1,
        le=VERSION_HISTORY_MAX_LIMIT,
    ),
    session: AsyncSession = Depends(get_db),
) -> list[ResumeDraftVersion]:
    await _owned_profile(session, profile_id, user.id)
    workspace = await _load_workspace(
        session,
        profile_id,
        include_messages=False,
        include_versions=False,
    )
    if not workspace:
        return []
    return list(
        (
            await session.scalars(
                select(ResumeDraftVersion)
                .where(ResumeDraftVersion.workspace_id == workspace.id)
                .order_by(ResumeDraftVersion.version.desc())
                .limit(limit)
            )
        ).all()
    )


@router.post("/versions/{version_id}/restore", response_model=ResumeWorkspaceRead)
async def restore_resume_version(
    profile_id: UUID,
    version_id: UUID,
    user: CurrentUser,
    payload: ResumeDraftRevisionCreate,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db),
) -> ResumeWorkspaceRead:
    await _owned_profile(session, profile_id, user.id)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_messages=False,
        include_versions=False,
    )
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
        )
    if payload.expected_draft_revision != workspace.draft_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_draft_revision_conflict",
            "The resume draft changed; reload before restoring a version",
        )
    version = await session.scalar(
        select(ResumeDraftVersion).where(
            ResumeDraftVersion.id == version_id,
            ResumeDraftVersion.workspace_id == workspace.id,
        )
    )
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume version not found"
        )
    restored_metadata = dict(workspace.provider_metadata)
    for key in (
        "active_import_source_id",
        "generation_fact_ids",
        "generation_evidence_fingerprint",
        VERIFIED_SUPPLEMENTAL_TRANSLATIONS_KEY,
    ):
        restored_metadata.pop(key, None)
        if key in version.diff:
            restored_metadata[key] = version.diff[key]
    restored_facts = _facts_selected_by_metadata(
        await _profile_facts(session, workspace.profile_id),
        restored_metadata,
    )
    _workspace_evidence_with_verified_translations(
        workspace,
        build_resume_evidence(restored_facts),
        metadata_override=restored_metadata,
    )
    workspace.current_draft = version.content
    workspace.provider_metadata = restored_metadata
    workspace.draft_revision += 1
    workspace.pending_suggestion = None
    workspace.revision += 1
    workspace.stage = ResumeWorkspaceStage.WRITING
    await _create_version(
        session,
        workspace,
        reason=ResumeDraftVersionReason.RESTORE,
        base_version_id=version.id,
        diff={"restored_version": version.version},
    )
    await session.commit()
    workspace = await _load_workspace(session, profile_id)
    assert workspace is not None
    return _workspace_read(workspace, get_resume_writer_provider(settings))


def _review_blockers(
    draft: ResumeDraftContent,
    workspace: ResumeWorkspace,
    evidence: tuple[Any, ...],
) -> list[str]:
    blockers: list[str] = []
    if workspace.pending_understanding:
        blockers.append("pending_understanding")
    if workspace.pending_suggestion:
        blockers.append("pending_suggestion")
    if not draft.summary_evidence_handles:
        blockers.append("summary_without_evidence")

    evidence_by_handle = {item.handle: item for item in evidence}

    def validate_claim(
        label: str,
        text: str,
        handles: list[str],
        *,
        education_metadata: bool = False,
    ) -> None:
        unknown = [handle for handle in handles if handle not in evidence_by_handle]
        if unknown:
            blockers.append(f"unknown_evidence:{label}")
            return
        claim_text = text
        if education_metadata and handles:
            supports = [evidence_by_handle[handle] for handle in handles]
            all_supports_are_education = all(
                support.category == "education" for support in supports
            )
            if all_supports_are_education:
                stripped = text.strip()
                if stripped.startswith("GPA:"):
                    normalized_gpa = " ".join(stripped.split())
                    supported_gpa_values = {
                        " ".join(f"GPA: {score}/{scale}".split())
                        for support in supports
                        if support.structured_value.get("gpa_display_recommended") is True
                        and isinstance(
                            score := support.structured_value.get("gpa_score"),
                            str | int | float,
                        )
                        and not isinstance(score, bool)
                        and isinstance(
                            scale := support.structured_value.get("gpa_scale"),
                            str | int | float,
                        )
                        and not isinstance(scale, bool)
                    }
                    if normalized_gpa not in supported_gpa_values:
                        blockers.append(f"unsupported_claim:{label}")
                        return
                    claim_text = stripped.removeprefix("GPA:").strip()
                for prefix in ("Relevant Coursework:", "المقررات ذات الصلة:"):
                    if stripped.startswith(prefix):
                        coursework = stripped.removeprefix(prefix).strip()
                        normalized_coursework = " ".join(coursework.split())
                        supported_coursework_lists = {
                            " ".join(", ".join(values).split())
                            for support in supports
                            if (values := resume_evidence_coursework(support))
                        }
                        if (
                            not normalized_coursework
                            or normalized_coursework not in supported_coursework_lists
                        ):
                            blockers.append(f"unsupported_claim:{label}")
                            return
                        claim_text = coursework
                        break
        try:
            validate_claim_grounding(claim_text, handles, evidence)
        except ResumeWriterError:
            blockers.append(f"unsupported_claim:{label}")

    if draft.summary_evidence_handles:
        validate_claim(
            "professional_summary",
            draft.professional_summary,
            draft.summary_evidence_handles,
        )
    all_handles = list(evidence_by_handle)
    if all_handles:
        validate_claim("headline", draft.headline, all_handles)
    else:
        blockers.append("confirmed_evidence_required")

    for section in draft.sections:
        for item in section.items:
            if not item.evidence_handles:
                blockers.append(f"item_without_evidence:{item.id}")
                continue
            unknown = [
                handle for handle in item.evidence_handles if handle not in evidence_by_handle
            ]
            if unknown:
                blockers.append(f"unknown_evidence:{item.id}")
                continue
            allowed_categories = SECTION_SUPPORT_CATEGORIES[section.key]
            if not any(
                evidence_by_handle[handle].category in allowed_categories
                for handle in item.evidence_handles
            ):
                blockers.append(f"evidence_category_mismatch:{item.id}")
                continue
            item_heading = " ".join(
                part
                for part in (
                    item.title,
                    item.organization,
                    item.date_range,
                    item.location,
                )
                if part
            )
            validate_claim(f"item:{item.id}", item_heading, item.evidence_handles)
            for bullet_index, bullet in enumerate(item.bullets):
                validate_claim(
                    f"bullet:{item.id}:{bullet_index}",
                    bullet,
                    item.evidence_handles,
                    education_metadata=section.key == "education",
                )
            if section.key in {"experience", "trading_experience", "project"} and not item.bullets:
                blockers.append(f"item_without_bullets:{item.id}")
    return list(dict.fromkeys(blockers))


@router.post("/review", response_model=ResumeReviewRead)
async def review_resume_workspace(
    profile_id: UUID,
    payload: ResumeReviewCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> ResumeReviewRead:
    profile = await _owned_profile(session, profile_id, user.id, for_update=True)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_messages=False,
        include_versions=False,
    )
    if not workspace or not workspace.current_draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume draft not found")
    import_flow = _import_flow(workspace)
    if import_flow is not None and import_flow.get("phase") != "draft_review":
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_import_phase_conflict",
            "Complete the guided import and generate the AI draft before review",
        )
    if payload.expected_draft_revision != workspace.draft_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_draft_revision_conflict",
            "The resume draft changed; reload before reviewing it",
        )
    if not payload.review_acknowledged:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            "resume_review_required",
            "Review the generated resume before exporting it",
        )
    await _refresh_workspace(session, workspace)
    draft = ResumeDraftContent.model_validate(workspace.current_draft)
    evidence = _workspace_evidence_with_verified_translations(
        workspace,
        build_resume_evidence(await _workspace_facts(session, workspace)),
    )
    blockers = _review_blockers(draft, workspace, evidence)
    if blockers:
        raise _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_review_blocked",
            "Resolve unsupported or incomplete resume content before export: "
            + ", ".join(blockers),
        )
    review_hash = _resume_review_hash(profile=profile, workspace=workspace)
    workspace.stage = ResumeWorkspaceStage.REVIEW
    workspace.revision += 1
    version = await _create_version(
        session,
        workspace,
        reason=ResumeDraftVersionReason.REVIEW,
        status_value=ResumeDraftStatus.EXPORT_READY,
        reviewed_by=user.id,
        review_hash=review_hash,
    )
    await session.commit()
    return ResumeReviewRead(
        workspace_id=workspace.id,
        draft_version_id=version.id,
        draft_revision=workspace.draft_revision,
        status=ResumeDraftStatus.EXPORT_READY,
        reviewed_at=version.reviewed_at or datetime.now(UTC),
        review_hash=review_hash,
        evidence_revision=workspace.evidence_revision,
        export_allowed=True,
    )


async def _pdf_response(
    *,
    profile: CareerProfile,
    workspace: ResumeWorkspace,
    attachment: bool,
) -> Response:
    if not workspace.current_draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume draft not found")
    draft = ResumeDraftContent.model_validate(workspace.current_draft)
    try:
        pdf_bytes = await run_in_threadpool(
            partial(
                render_resume_pdf,
                profile_name=profile.full_name,
                city=profile.city,
                language=workspace.language,
                draft=draft,
                contact=ResumeExportContact.model_validate(workspace.contact),
            )
        )
    except Exception as exc:
        raise _api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "resume_export_failed",
            "The resume PDF could not be generated",
        ) from exc
    display_name = f"{profile.full_name.strip() or 'resume'}-resume.pdf"
    disposition = "attachment" if attachment else "inline"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"{disposition}; filename=resume.pdf; filename*=UTF-8''{quote(display_name)}"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/preview.pdf", response_class=Response)
async def preview_resume_pdf(
    profile_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _owned_profile(session, profile_id, user.id)
    workspace = await _load_workspace(
        session,
        profile_id,
        include_messages=False,
        include_versions=False,
    )
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume workspace not found"
        )
    _workspace_evidence_with_verified_translations(
        workspace,
        build_resume_evidence(await _workspace_facts(session, workspace)),
    )
    return await _pdf_response(profile=profile, workspace=workspace, attachment=False)


@router.post("/export.pdf", response_class=Response)
async def export_resume_workspace_pdf(
    profile_id: UUID,
    payload: ResumeReviewCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _owned_profile(session, profile_id, user.id, for_update=True)
    workspace = await _load_workspace(
        session,
        profile_id,
        for_update=True,
        include_messages=False,
        include_versions=False,
    )
    if not workspace or not workspace.current_draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume draft not found")
    await _refresh_workspace(session, workspace)
    if payload.expected_draft_revision != workspace.draft_revision:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_draft_revision_conflict",
            "The resume draft changed; review it again before export",
        )
    if not payload.review_acknowledged:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            "resume_review_required",
            "Review the generated resume before exporting it",
        )
    current_review_hash = _resume_review_hash(profile=profile, workspace=workspace)
    latest_reviews = (
        await session.scalars(
            select(ResumeDraftVersion)
            .where(
                ResumeDraftVersion.workspace_id == workspace.id,
                ResumeDraftVersion.status == ResumeDraftStatus.EXPORT_READY,
            )
            .order_by(ResumeDraftVersion.version.desc())
            .limit(WORKSPACE_VERSION_RESPONSE_LIMIT)
        )
    ).all()
    latest_review = next(
        (
            version
            for version in latest_reviews
            if version.evidence_revision == workspace.evidence_revision
            and version.content == workspace.current_draft
            and version.review_hash == current_review_hash
        ),
        None,
    )
    if not latest_review:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            "resume_review_stale",
            "Review the current resume version before exporting it",
        )
    draft = ResumeDraftContent.model_validate(workspace.current_draft)
    evidence = _workspace_evidence_with_verified_translations(
        workspace,
        build_resume_evidence(await _workspace_facts(session, workspace)),
    )
    blockers = _review_blockers(draft, workspace, evidence)
    if blockers:
        raise _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "resume_review_blocked",
            "Resolve unsupported or incomplete resume content before export: "
            + ", ".join(blockers),
        )
    response = await _pdf_response(profile=profile, workspace=workspace, attachment=True)
    workspace.stage = ResumeWorkspaceStage.COMPLETE
    workspace.revision += 1
    await session.commit()
    return response
