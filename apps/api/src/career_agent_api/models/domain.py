from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from career_agent_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from career_agent_api.models.enums import (
    ApplicationStatus,
    ApplyDecision,
    CareerPathMessageRole,
    ClaimType,
    ConfidenceBand,
    DocumentKind,
    DocumentStatus,
    FactCategory,
    IntakeMethod,
    OutcomeKind,
    PreferredLanguage,
    ReadinessBand,
    RequirementCategory,
    RequirementImportance,
    RequirementMatchStatus,
    SourceKind,
    VerificationStatus,
)


def enum_type(enum_class: type, name: str) -> SAEnum:
    return SAEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
    )


class CareerProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "career_profiles"

    owner_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    headline: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    preferred_language: Mapped[PreferredLanguage] = mapped_column(
        enum_type(PreferredLanguage, "preferred_language"), default=PreferredLanguage.AR
    )
    city: Mapped[str | None] = mapped_column(String(120))
    years_experience: Mapped[float | None] = mapped_column(Float)
    completed_fact_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_revision: Mapped[int] = mapped_column(Integer, default=0)
    deletion_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sources: Mapped[list[EvidenceSource]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    facts: Mapped[list[CareerFact]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    career_path_conversation: Mapped[CareerPathConversation | None] = relationship(
        back_populates="profile", cascade="all, delete-orphan", uselist=False
    )


class EvidenceSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_sources"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("career_profiles.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SourceKind] = mapped_column(enum_type(SourceKind, "source_kind"))
    label: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(500))
    source_locator: Mapped[str | None] = mapped_column(String(1000))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    profile: Mapped[CareerProfile] = relationship(back_populates="sources")
    facts: Mapped[list[CareerFact]] = relationship(back_populates="source")


class CareerFact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "career_facts"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("career_profiles.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_sources.id", ondelete="RESTRICT"), index=True
    )
    category: Mapped[FactCategory] = mapped_column(enum_type(FactCategory, "fact_category"))
    label: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str | None] = mapped_column(Text)
    structured_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_type(VerificationStatus, "verification_status"),
        default=VerificationStatus.UNCONFIRMED,
        index=True,
    )
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_correction_reason: Mapped[str | None] = mapped_column(Text)
    user_corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_extraction: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    profile: Mapped[CareerProfile] = relationship(back_populates="facts")
    source: Mapped[EvidenceSource] = relationship(back_populates="facts")


class CareerPathConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "career_path_conversations"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("career_profiles.id", ondelete="CASCADE"), unique=True, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    last_evidence_revision: Mapped[int | None] = mapped_column(Integer)
    consent_version: Mapped[str | None] = mapped_column(String(40))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[CareerProfile] = relationship(back_populates="career_path_conversation")
    messages: Mapped[list[CareerPathMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="CareerPathMessage.sequence",
    )


class CareerPathMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "career_path_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "sequence", name="uq_career_path_messages_conversation_sequence"
        ),
        UniqueConstraint(
            "conversation_id",
            "client_turn_id",
            name="uq_career_path_messages_conversation_client_turn",
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("career_path_conversations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[CareerPathMessageRole] = mapped_column(
        enum_type(CareerPathMessageRole, "career_path_message_role")
    )
    content: Mapped[str] = mapped_column(Text)
    suggestions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(120))
    evidence_revision: Mapped[int | None] = mapped_column(Integer)
    client_turn_id: Mapped[UUID | None] = mapped_column(Uuid)

    conversation: Mapped[CareerPathConversation] = relationship(back_populates="messages")


class SourcePolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_policies"

    source_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    intake_method: Mapped[IntakeMethod] = mapped_column(
        enum_type(IntakeMethod, "intake_method"), default=IntakeMethod.MANUAL
    )
    permission_basis: Mapped[str] = mapped_column(
        String(1000), default="User-supplied content only"
    )
    terms_reviewed_at: Mapped[date | None] = mapped_column(Date)
    can_search_automatically: Mapped[bool] = mapped_column(Boolean, default=False)
    can_fetch_details: Mapped[bool] = mapped_column(Boolean, default=False)
    can_apply_automatically: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("owner_id", "content_hash", name="uq_jobs_owner_hash"),)

    owner_id: Mapped[str] = mapped_column(String(255), index=True)
    source_policy_id: Mapped[UUID] = mapped_column(ForeignKey("source_policies.id"), index=True)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    intake_method: Mapped[IntakeMethod] = mapped_column(
        enum_type(IntakeMethod, "job_intake_method"), default=IntakeMethod.MANUAL
    )
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    posted_at: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    requirements_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requirements_reviewed_by_owner_id: Mapped[str | None] = mapped_column(String(255))
    requirements_review_hash: Mapped[str | None] = mapped_column(String(64))
    requirements_revision: Mapped[int] = mapped_column(Integer, default=0)

    source_policy: Mapped[SourcePolicy] = relationship()
    requirements: Mapped[list[JobRequirement]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobRequirement.created_at"
    )


class JobRequirement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_requirements"

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    category: Mapped[RequirementCategory] = mapped_column(
        enum_type(RequirementCategory, "requirement_category")
    )
    importance: Mapped[RequirementImportance] = mapped_column(
        enum_type(RequirementImportance, "requirement_importance")
    )
    text: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(String(500), index=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    needs_user_review: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user_added: Mapped[bool] = mapped_column(Boolean, default=False)
    user_correction_reason: Mapped[str | None] = mapped_column(Text)
    user_corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_extraction: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    job: Mapped[Job] = relationship(back_populates="requirements")


class MatchAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "match_analyses"

    profile_id: Mapped[UUID] = mapped_column(ForeignKey("career_profiles.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    coverage_score: Mapped[int] = mapped_column(Integer)
    mandatory_coverage_score: Mapped[int] = mapped_column(Integer)
    readiness_band: Mapped[ReadinessBand] = mapped_column(
        enum_type(ReadinessBand, "readiness_band")
    )
    confidence_band: Mapped[ConfidenceBand] = mapped_column(
        enum_type(ConfidenceBand, "confidence_band")
    )
    decision: Mapped[ApplyDecision] = mapped_column(enum_type(ApplyDecision, "apply_decision"))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    invalidation_reason: Mapped[str | None] = mapped_column(String(500))
    evidence_revision: Mapped[int] = mapped_column(Integer)
    requirements_revision: Mapped[int] = mapped_column(Integer)

    requirement_matches: Mapped[list[RequirementMatch]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class RequirementMatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "requirement_matches"

    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("match_analyses.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[UUID] = mapped_column(ForeignKey("job_requirements.id"), index=True)
    evidence_fact_id: Mapped[UUID | None] = mapped_column(ForeignKey("career_facts.id"), index=True)
    status: Mapped[RequirementMatchStatus] = mapped_column(
        enum_type(RequirementMatchStatus, "requirement_match_status")
    )
    reason: Mapped[str] = mapped_column(Text)
    earned_weight: Mapped[int] = mapped_column(Integer, default=0)

    analysis: Mapped[MatchAnalysis] = relationship(back_populates="requirement_matches")
    requirement: Mapped[JobRequirement] = relationship()
    evidence_fact: Mapped[CareerFact | None] = relationship()


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"

    profile_id: Mapped[UUID] = mapped_column(ForeignKey("career_profiles.id"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    base_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_versions.id"))
    kind: Mapped[DocumentKind] = mapped_column(enum_type(DocumentKind, "document_kind"))
    language: Mapped[PreferredLanguage] = mapped_column(
        enum_type(PreferredLanguage, "document_language")
    )
    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus, "document_status"), default=DocumentStatus.DRAFT
    )
    content: Mapped[str] = mapped_column(Text)
    diff_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_owner_id: Mapped[str | None] = mapped_column(String(255))
    review_hash: Mapped[str | None] = mapped_column(String(64))
    evidence_revision_at_review: Mapped[int | None] = mapped_column(Integer)

    claims: Mapped[list[DocumentClaim]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentClaim.position"
    )


class DocumentClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_claims"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    claim_type: Mapped[ClaimType] = mapped_column(enum_type(ClaimType, "claim_type"))
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    supported: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped[DocumentVersion] = relationship(back_populates="claims")
    evidence_links: Mapped[list[ClaimEvidence]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ClaimEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (UniqueConstraint("claim_id", "fact_id", name="uq_claim_evidence_claim_fact"),)

    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_claims.id", ondelete="CASCADE"), index=True
    )
    fact_id: Mapped[UUID] = mapped_column(ForeignKey("career_facts.id"), index=True)

    claim: Mapped[DocumentClaim] = relationship(back_populates="evidence_links")
    fact: Mapped[CareerFact] = relationship()


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("profile_id", "job_id", name="uq_applications_profile_job"),)

    profile_id: Mapped[UUID] = mapped_column(ForeignKey("career_profiles.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("match_analyses.id"))
    cv_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_versions.id"))
    cover_letter_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id")
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        enum_type(ApplicationStatus, "application_status"), default=ApplicationStatus.SAVED
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    outcomes: Mapped[list[Outcome]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class Outcome(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outcomes"

    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[OutcomeKind] = mapped_column(enum_type(OutcomeKind, "outcome_kind"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=True)
    qualified_human_interview: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str | None] = mapped_column(Text)

    application: Mapped[Application] = relationship(back_populates="outcomes")


class DeletionReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-identifying audit receipt retained after user data is removed."""

    __tablename__ = "deletion_receipts"

    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
