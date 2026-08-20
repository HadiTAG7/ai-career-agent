from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    ResumeDraftStatus,
    ResumeDraftVersionReason,
    ResumeMessageKind,
    ResumeMessageRole,
    ResumeMessageStatus,
    ResumeWorkspaceStage,
    SourceKind,
    VerificationStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CareerProfileCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    headline: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=10_000)
    preferred_language: PreferredLanguage = PreferredLanguage.AR
    city: str | None = Field(default=None, max_length=120)
    years_experience: float | None = Field(default=None, ge=0, le=60)
    completed_fact_categories: list[FactCategory] = Field(default_factory=list, max_length=10)


class CareerProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    headline: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=10_000)
    preferred_language: PreferredLanguage | None = None
    city: str | None = Field(default=None, max_length=120)
    years_experience: float | None = Field(default=None, ge=0, le=60)
    completed_fact_categories: list[FactCategory] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def non_nullable_profile_fields(self) -> "CareerProfileUpdate":
        for field_name in ("full_name", "preferred_language", "completed_fact_categories"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class CareerProfileRead(ORMModel):
    id: UUID
    owner_id: str
    full_name: str
    headline: str | None
    summary: str | None
    preferred_language: PreferredLanguage
    city: str | None
    years_experience: float | None
    completed_fact_categories: list[FactCategory]
    evidence_revision: int
    created_at: datetime
    updated_at: datetime


class CareerProfileSummaryRead(BaseModel):
    profile_id: UUID
    profile_quality_percent: int
    confirmed_facts: int
    total_facts: int
    extracted_facts: int
    unconfirmed_facts: int
    covered_quality_categories: list[FactCategory]
    total_quality_categories: int


class CareerPathEvidenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["confirmed_fact", "chat"]
    reference: str = Field(min_length=1, max_length=500)


class CareerPathSuggestionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=160)
    why_fit: list[str] = Field(min_length=1, max_length=4)
    unknowns: list[str] = Field(max_length=4)
    seven_day_experiment: str = Field(min_length=2, max_length=1_000)
    signal: Literal["strong", "partial", "needs_experiment"]
    evidence: list[CareerPathEvidenceRead] = Field(max_length=6)

    @field_validator("why_fit", "unknowns")
    @classmethod
    def bounded_points(cls, value: list[str]) -> list[str]:
        return [item.strip()[:500] for item in value if item.strip()]


class CareerPathGeneratedReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4_000)
    suggestions: list[CareerPathSuggestionRead] = Field(max_length=3)


class CareerPathMessageRead(ORMModel):
    id: UUID
    role: CareerPathMessageRole
    content: str
    suggestions: list[CareerPathSuggestionRead]
    model: str | None
    created_at: datetime


class CareerPathConversationRead(ORMModel):
    id: UUID
    revision: int
    last_evidence_revision: int | None
    consent_version: str | None
    consented_at: datetime | None
    messages: list[CareerPathMessageRead]


class CareerPathWorkspaceRead(BaseModel):
    provider_ready: bool
    provider: str
    model: str | None
    profile_id: UUID
    confirmed_fact_count: int
    consent_required: bool
    conversation: CareerPathConversationRead | None


class CareerPathMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4_000)
    client_turn_id: UUID
    expected_revision: int = Field(ge=0)
    data_sharing_acknowledged: bool = False

    @field_validator("content")
    @classmethod
    def non_blank_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content cannot be blank")
        return value


class EvidenceSourceCreate(BaseModel):
    kind: SourceKind
    label: str = Field(min_length=1, max_length=255)
    original_filename: str | None = Field(default=None, max_length=500)
    source_locator: str | None = Field(default=None, max_length=1000)
    source_metadata: dict[str, Any] = Field(default_factory=dict, max_length=50)


class EvidenceSourceRead(ORMModel):
    id: UUID
    profile_id: UUID
    kind: SourceKind
    label: str
    original_filename: str | None
    source_locator: str | None
    source_metadata: dict[str, Any]
    created_at: datetime


class ImportResultRead(BaseModel):
    source: EvidenceSourceRead
    facts: list["CareerFactRead"]
    requires_user_review: bool = True
    analysis_status: Literal["created", "ai_upgraded", "already_ai_analyzed"] = "created"


class CareerFactBatchConfirmCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    client_request_id: UUID
    fact_ids: list[UUID] = Field(default_factory=list, max_length=120)
    rejected_fact_ids: list[UUID] = Field(default_factory=list, max_length=120)
    expected_evidence_revision: int = Field(ge=0)

    @field_validator("fact_ids", "rejected_fact_ids")
    @classmethod
    def unique_fact_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("fact_ids must be unique")
        return value

    @model_validator(mode="after")
    def reviewed_fact_partition(self) -> "CareerFactBatchConfirmCreate":
        accepted = set(self.fact_ids)
        rejected = set(self.rejected_fact_ids)
        if not accepted and not rejected:
            raise ValueError("At least one accepted or rejected fact is required")
        if accepted & rejected:
            raise ValueError("A fact cannot be both accepted and rejected")
        if len(accepted | rejected) > 120:
            raise ValueError("At most 120 facts can be reviewed in one request")
        return self


class CareerFactBatchConfirmRead(BaseModel):
    facts: list["CareerFactRead"]
    evidence_revision: int = Field(ge=0)


class ResumeNarrativeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=20, max_length=20_000)
    data_sharing_acknowledged: bool = False


class ResumeQuestionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_]+$")
    category: FactCategory
    question: str = Field(min_length=3, max_length=600)
    why_it_matters: str = Field(min_length=3, max_length=500)
    placeholder: str = Field(min_length=3, max_length=800)
    required: bool = False


class ResumeInterviewAnswerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_]+$")
    category: FactCategory
    question: str = Field(min_length=3, max_length=600)
    answer: str = Field(default="", max_length=4_000)
    skipped: bool = False

    @model_validator(mode="after")
    def answer_or_skip(self) -> "ResumeInterviewAnswerCreate":
        self.answer = self.answer.strip()
        if not self.skipped and not self.answer:
            raise ValueError("answer cannot be blank unless the question is skipped")
        return self


ResumeSectionKey = Literal[
    "education",
    "experience",
    "trading_experience",
    "project",
    "skill",
    "certification",
    "language",
    "achievement",
]


class ResumeDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=500)
    organization: str | None = Field(default=None, max_length=500)
    date_range: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=200)
    bullets: list[str] = Field(default_factory=list, max_length=20)
    evidence_handles: list[str] = Field(min_length=1, max_length=12)

    @field_validator("bullets")
    @classmethod
    def clean_bullets(cls, value: list[str]) -> list[str]:
        return [item.strip()[:1_000] for item in value if item.strip()]


class ResumeDraftSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: ResumeSectionKey
    title: str = Field(min_length=1, max_length=160)
    items: list[ResumeDraftItem] = Field(min_length=1, max_length=30)


class ResumeVerifiedSupplementalTranslation(BaseModel):
    """Server-owned proof for one independently verified evidence translation.

    The source text is deliberately represented only by a digest.  This model is attached to
    the in-memory draft returned by the writer and excluded from every serialized resume draft;
    the workspace API persists it separately in provider metadata.
    """

    model_config = ConfigDict(extra="forbid")

    handle: str = Field(min_length=1, max_length=120)
    field: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    value_index: int = Field(ge=0, le=100)
    source_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    translated_value: str = Field(min_length=1, max_length=4_000)
    pair_id: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    verdict: Literal["pass"]


class ResumeDraftContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, max_length=300)
    professional_summary: str = Field(min_length=20, max_length=2_500)
    summary_evidence_handles: list[str] = Field(min_length=1, max_length=15)
    sections: list[ResumeDraftSection] = Field(min_length=1, max_length=8)
    verified_supplemental_translations: list[ResumeVerifiedSupplementalTranslation] = Field(
        default_factory=list,
        max_length=100,
        exclude=True,
        repr=False,
    )

    @field_validator("sections")
    @classmethod
    def unique_sections(cls, value: list[ResumeDraftSection]) -> list[ResumeDraftSection]:
        keys = [section.key for section in value]
        if len(keys) != len(set(keys)):
            raise ValueError("resume section keys must be unique")
        return value


class ResumeExportContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    linkedin: str | None = Field(default=None, max_length=500)


ResumeQuickAction = Literal[
    "skip",
    "continue",
    "show_example",
    "no_exact_metric",
    "additions_yes",
    "additions_no",
    "generate",
    "improve",
    "review",
]
ResumeRewriteTargetKind = Literal[
    "headline",
    "professional_summary",
    "bullet",
]
ResumeRewriteMode = Literal["stronger", "shorter", "professional", "custom"]


class ResumeWorkspaceStartCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: PreferredLanguage = PreferredLanguage.AR
    conversation_language: PreferredLanguage | None = None
    contact: ResumeExportContact = Field(default_factory=ResumeExportContact)
    data_sharing_acknowledged: bool = False


class ResumeImportDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    client_request_id: UUID
    expected_revision: int = Field(ge=0)
    expected_evidence_revision: int = Field(ge=0)


class ResumeMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=4_000)
    client_turn_id: UUID
    expected_revision: int = Field(ge=0)
    quick_action: ResumeQuickAction | None = None

    @model_validator(mode="after")
    def content_or_quick_action(self) -> "ResumeMessageCreate":
        self.content = self.content.strip()
        if not self.content and self.quick_action is None:
            raise ValueError("content or quick_action is required")
        return self


class ResumeUnderstandingActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    corrected_text: str | None = Field(default=None, max_length=4_000)

    @field_validator("corrected_text")
    @classmethod
    def non_blank_correction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("corrected_text cannot be blank")
        return value


class ResumeDraftPatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: ResumeDraftContent
    expected_draft_revision: int = Field(ge=0)


class ResumeDraftRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_revision: int = Field(ge=0)


class ResumeRewriteConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant", "user"]
    content: str = Field(min_length=1, max_length=1_000)

    @field_validator("content")
    @classmethod
    def non_blank_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("conversation content cannot be blank")
        return value


# One clarify-then-rewrite exchange never needs more than question/answer twice.
REWRITE_CLARIFYING_QUESTION_CAP = 2


class ResumeRewriteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_kind: ResumeRewriteTargetKind
    section_key: ResumeSectionKey | None = None
    item_id: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9_]+$")
    bullet_index: int | None = Field(default=None, ge=0, le=19)
    mode: ResumeRewriteMode
    instruction: str | None = Field(default=None, max_length=1_000)
    # The clarification exchange for this same request, held by the client and resent
    # whole: the editor's questions and the user's answers, oldest first.
    conversation: list[ResumeRewriteConversationTurn] = Field(default_factory=list, max_length=6)
    expected_draft_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_target_and_instruction(self) -> "ResumeRewriteCreate":
        if self.target_kind == "bullet" and self.section_key is None:
            raise ValueError("section_key is required for this target")
        if self.target_kind == "bullet" and self.item_id is None:
            raise ValueError("item_id is required for this target")
        if self.target_kind == "bullet" and self.bullet_index is None:
            raise ValueError("bullet_index is required for a bullet target")
        if self.target_kind != "bullet" and self.bullet_index is not None:
            raise ValueError("bullet_index is only valid for a bullet target")
        if self.mode == "custom":
            instruction = (self.instruction or "").strip()
            if not instruction:
                raise ValueError("instruction is required for custom mode")
            self.instruction = instruction
        elif self.instruction is not None:
            self.instruction = self.instruction.strip() or None
        if self.conversation:
            if self.conversation[0].role != "assistant":
                raise ValueError("a clarification exchange starts with the editor's question")
            for previous, current in zip(self.conversation, self.conversation[1:], strict=False):
                if previous.role == current.role:
                    raise ValueError("clarification roles must alternate")
            if self.conversation[-1].role != "user":
                raise ValueError("a rewrite request is sent to answer the editor's question")
            asked = sum(1 for turn in self.conversation if turn.role == "assistant")
            if asked > REWRITE_CLARIFYING_QUESTION_CAP:
                raise ValueError("the clarification exchange exceeded the question cap")
        return self


class ResumeReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_revision: int = Field(ge=0)
    review_acknowledged: bool = False


class ResumeMessageRead(ORMModel):
    id: UUID
    sequence: int
    role: ResumeMessageRole
    kind: ResumeMessageKind
    content: str
    structured_payload: dict[str, Any]
    status: ResumeMessageStatus
    client_turn_id: UUID | None
    created_at: datetime


class ResumeDraftVersionRead(ORMModel):
    id: UUID
    workspace_id: UUID
    version: int
    base_version_id: UUID | None
    reason: ResumeDraftVersionReason
    status: ResumeDraftStatus
    content: ResumeDraftContent
    diff: dict[str, Any]
    evidence_revision: int
    reviewed_at: datetime | None
    reviewed_by_owner_id: str | None
    review_hash: str | None
    created_at: datetime


class ResumeRewriteSuggestionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: UUID
    target_kind: ResumeRewriteTargetKind
    section_key: ResumeSectionKey | None = None
    item_id: str | None = None
    bullet_index: int | None = None
    mode: ResumeRewriteMode
    instruction: str | None = None
    before_text: str = Field(max_length=10_000)
    after_text: str = Field(min_length=1, max_length=10_000)
    base_draft_revision: int = Field(ge=0)
    evidence_handles: list[str] = Field(default_factory=list, max_length=20)


class ResumeRewriteTurnRead(BaseModel):
    """One turn of the rewrite exchange: a suggestion to review, or a question to answer."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["suggestion", "question"]
    suggestion: ResumeRewriteSuggestionRead | None = None
    question: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> "ResumeRewriteTurnRead":
        if self.kind == "suggestion" and (self.suggestion is None or self.question is not None):
            raise ValueError("a suggestion turn carries a suggestion and no question")
        if self.kind == "question" and (
            self.suggestion is not None or not (self.question or "").strip()
        ):
            raise ValueError("a question turn carries a non-blank question and no suggestion")
        return self


class ResumeReviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    draft_version_id: UUID
    draft_revision: int = Field(ge=0)
    status: ResumeDraftStatus
    reviewed_at: datetime
    review_hash: str = Field(min_length=1, max_length=64)
    evidence_revision: int = Field(ge=0)
    export_allowed: bool


class ResumeWorkspaceRead(ORMModel):
    id: UUID
    profile_id: UUID
    language: PreferredLanguage
    conversation_language: PreferredLanguage = PreferredLanguage.AR
    stage: ResumeWorkspaceStage
    revision: int
    evidence_revision: int
    readiness_score: int = Field(ge=0, le=100)
    section_coverage: dict[ResumeSectionKey, bool]
    current_draft: ResumeDraftContent | None
    draft_revision: int
    contact: ResumeExportContact
    pending_understanding: dict[str, Any] | None = None
    pending_suggestion: ResumeRewriteSuggestionRead | None = None
    provider_ready: bool = False
    provider: str | None = None
    model: str | None = None
    provider_metadata: dict[str, Any]
    consent_required: bool = True
    consent_version: str | None = None
    consented_at: datetime | None = None
    messages: list[ResumeMessageRead] = Field(default_factory=list)
    versions: list[ResumeDraftVersionRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


RESERVED_STRUCTURED_KEY = "profile_field"


def has_reserved_structured_keys(value: dict[str, Any]) -> bool:
    return RESERVED_STRUCTURED_KEY in value or any(key.startswith("_") for key in value)


def sanitize_structured_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """Drop keys reserved for internal use before storing model-proposed records.

    User-submitted facts are rejected outright by the schema validators below; records
    that arrive from an AI provider cannot be rejected mid-flow, so the reserved keys
    are stripped instead.
    """
    return {
        key: item
        for key, item in record.items()
        if key != RESERVED_STRUCTURED_KEY and not key.startswith("_")
    }


class CareerFactCreate(BaseModel):
    source_id: UUID
    category: FactCategory
    label: str = Field(min_length=1, max_length=500)
    detail: str | None = Field(default=None, max_length=20_000)
    structured_value: dict[str, Any] = Field(default_factory=dict, max_length=100)
    source_excerpt: str | None = Field(default=None, max_length=10_000)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("structured_value")
    @classmethod
    def reject_reserved_structured_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        if has_reserved_structured_keys(value):
            raise ValueError("Reserved structured evidence key")
        return value


class CareerFactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FactCategory | None = None
    label: str | None = Field(default=None, min_length=1, max_length=500)
    detail: str | None = Field(default=None, max_length=20_000)
    structured_value: dict[str, Any] | None = Field(default=None, max_length=100)
    correction_reason: str = Field(min_length=3, max_length=2_000)

    @field_validator("structured_value")
    @classmethod
    def reject_reserved_structured_keys(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value and has_reserved_structured_keys(value):
            raise ValueError("Reserved structured evidence key")
        return value

    @model_validator(mode="after")
    def contains_an_edit(self) -> "CareerFactUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one fact field must be supplied")
        editable = {"category", "label", "detail", "structured_value"}
        if not (self.model_fields_set & editable):
            raise ValueError("At least one fact field must be supplied")
        for field_name in ("category", "label", "structured_value"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class CareerFactRead(ORMModel):
    id: UUID
    profile_id: UUID
    source_id: UUID
    category: FactCategory
    label: str
    detail: str | None
    structured_value: dict[str, Any]
    source_excerpt: str | None
    verification_status: VerificationStatus
    extraction_confidence: float | None
    confirmed_at: datetime | None
    user_correction_reason: str | None
    user_corrected_at: datetime | None
    original_extraction: dict[str, Any] | None
    created_at: datetime


class SourcePolicyRead(ORMModel):
    id: UUID
    source_key: str
    display_name: str
    intake_method: IntakeMethod
    permission_basis: str
    terms_reviewed_at: date | None
    can_search_automatically: bool
    can_fetch_details: bool
    can_apply_automatically: bool
    active: bool


class JobRequirementCreate(BaseModel):
    category: RequirementCategory
    importance: RequirementImportance
    text: str = Field(min_length=1, max_length=10_000)
    normalized_value: str | None = Field(default=None, max_length=500)
    weight: int = Field(default=1, ge=1, le=10)


class JobRequirementRead(ORMModel):
    id: UUID
    category: RequirementCategory
    importance: RequirementImportance
    text: str
    normalized_value: str | None
    weight: int
    needs_user_review: bool
    is_active: bool
    user_added: bool
    user_correction_reason: str | None
    user_corrected_at: datetime | None
    original_extraction: dict[str, Any] | None


class JobRequirementUpdate(BaseModel):
    category: RequirementCategory | None = None
    importance: RequirementImportance | None = None
    text: str | None = Field(default=None, min_length=1, max_length=10_000)
    normalized_value: str | None = Field(default=None, max_length=500)
    weight: int | None = Field(default=None, ge=1, le=10)
    correction_reason: str = Field(min_length=3, max_length=2_000)

    @model_validator(mode="after")
    def contains_a_correction(self) -> "JobRequirementUpdate":
        editable = {"category", "importance", "text", "normalized_value", "weight"}
        if not (self.model_fields_set & editable):
            raise ValueError("At least one requirement field must be supplied")
        for field_name in ("category", "importance", "text", "weight"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class JobRequirementUserCreate(BaseModel):
    category: RequirementCategory
    importance: RequirementImportance
    text: str = Field(min_length=1, max_length=10_000)
    normalized_value: str | None = Field(default=None, max_length=500)
    weight: int = Field(default=1, ge=1, le=10)
    correction_reason: str = Field(min_length=3, max_length=2_000)


class JobRequirementRetire(BaseModel):
    correction_reason: str = Field(min_length=3, max_length=2_000)


class ManualJobCreate(BaseModel):
    source_key: str = Field(default="manual", min_length=1, max_length=120)
    source_url: str | None = Field(default=None, max_length=2000)
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=100_000)
    location: str | None = Field(default=None, max_length=255)
    posted_at: date | None = None
    expires_at: date | None = None
    requirements: list[JobRequirementCreate] = Field(default_factory=list, max_length=100)

    @field_validator("source_key")
    @classmethod
    def normalize_source_key(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @field_validator("source_url")
    @classmethod
    def safe_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.casefold()
        if not lowered.startswith(("https://", "http://")):
            raise ValueError("source_url must use http or https")
        return value

    @model_validator(mode="after")
    def dates_in_order(self) -> "ManualJobCreate":
        if self.posted_at and self.expires_at and self.expires_at < self.posted_at:
            raise ValueError("expires_at cannot precede posted_at")
        return self


class JobRead(ORMModel):
    id: UUID
    source_url: str | None
    intake_method: IntakeMethod
    title: str
    company: str
    description: str
    location: str | None
    posted_at: date | None
    expires_at: date | None
    fetched_at: datetime | None
    requirements_reviewed_at: datetime | None
    requirements_reviewed_by_owner_id: str | None
    requirements_review_hash: str | None
    requirements_revision: int
    created_at: datetime
    source_policy: SourcePolicyRead
    requirements: list[JobRequirementRead]


class RequirementMatchRead(ORMModel):
    id: UUID
    requirement_id: UUID
    evidence_fact_id: UUID | None
    status: RequirementMatchStatus
    reason: str
    earned_weight: int
    requirement: JobRequirementRead


class MatchAnalysisRead(ORMModel):
    id: UUID
    profile_id: UUID
    job_id: UUID
    coverage_score: int
    mandatory_coverage_score: int
    readiness_band: ReadinessBand
    confidence_band: ConfidenceBand
    decision: ApplyDecision
    explanation: dict[str, Any]
    invalidated_at: datetime | None
    invalidation_reason: str | None
    evidence_revision: int
    requirements_revision: int
    requirement_matches: list[RequirementMatchRead]
    created_at: datetime


class AnalyzeJobRequest(BaseModel):
    profile_id: UUID


class DocumentClaimCreate(BaseModel):
    claim_type: ClaimType
    text: str = Field(min_length=1, max_length=10_000)
    evidence_fact_ids: list[UUID] = Field(default_factory=list, max_length=25)


class DocumentCreate(BaseModel):
    profile_id: UUID
    job_id: UUID | None = None
    base_version_id: UUID | None = None
    kind: DocumentKind
    language: PreferredLanguage
    title: str = Field(min_length=1, max_length=500)
    status: DocumentStatus = DocumentStatus.DRAFT
    content: str | None = Field(default=None, max_length=100_000)
    diff_summary: dict[str, Any] = Field(default_factory=dict, max_length=100)
    claims: list[DocumentClaimCreate] = Field(min_length=1, max_length=250)


class ClaimEvidenceRead(ORMModel):
    fact_id: UUID


class DocumentClaimRead(ORMModel):
    id: UUID
    claim_type: ClaimType
    text: str
    position: int
    supported: bool
    evidence_links: list[ClaimEvidenceRead]


class DocumentRead(ORMModel):
    id: UUID
    profile_id: UUID
    job_id: UUID | None
    base_version_id: UUID | None
    kind: DocumentKind
    language: PreferredLanguage
    title: str
    status: DocumentStatus
    content: str
    diff_summary: dict[str, Any]
    reviewed_at: datetime | None
    reviewed_by_owner_id: str | None
    review_hash: str | None
    evidence_revision_at_review: int | None
    claims: list[DocumentClaimRead]
    created_at: datetime
    updated_at: datetime


class DocumentValidationRead(BaseModel):
    document_id: UUID
    valid: bool
    unsupported_claim_ids: list[UUID]
    export_allowed: bool


class ApplicationCreate(BaseModel):
    profile_id: UUID
    job_id: UUID
    analysis_id: UUID | None = None
    cv_document_id: UUID | None = None
    cover_letter_document_id: UUID | None = None
    status: ApplicationStatus = ApplicationStatus.SAVED
    next_action_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class ApplicationUpdate(BaseModel):
    analysis_id: UUID | None = None
    cv_document_id: UUID | None = None
    cover_letter_document_id: UUID | None = None
    status: ApplicationStatus | None = None
    submitted_at: datetime | None = None
    next_action_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class OutcomeCreate(BaseModel):
    kind: OutcomeKind
    occurred_at: datetime
    confirmed_by_user: bool = True
    qualified_human_interview: bool = False
    detail: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def qualified_means_interview(self) -> "OutcomeCreate":
        if self.qualified_human_interview and self.kind is not OutcomeKind.INTERVIEW:
            raise ValueError("qualified_human_interview is only valid for interview outcomes")
        return self


class OutcomeRead(ORMModel):
    id: UUID
    application_id: UUID
    kind: OutcomeKind
    occurred_at: datetime
    confirmed_by_user: bool
    qualified_human_interview: bool
    detail: str | None


class ApplicationRead(ORMModel):
    id: UUID
    profile_id: UUID
    job_id: UUID
    analysis_id: UUID | None
    cv_document_id: UUID | None
    cover_letter_document_id: UUID | None
    status: ApplicationStatus
    submitted_at: datetime | None
    next_action_at: datetime | None
    notes: str | None
    outcomes: list[OutcomeRead]
    created_at: datetime
    updated_at: datetime


class DashboardRead(BaseModel):
    profile_id: UUID
    profile_quality_percent: int
    confirmed_facts: int
    total_facts: int
    application_pipeline: dict[ApplicationStatus, int]
    submitted_applications: int
    qualified_interviews: int
    qualified_interviews_per_completed_application: float | None
    actions_due: int
    top_opportunities: list[MatchAnalysisRead]


class DeletionReceiptRead(ORMModel):
    id: UUID
    completed_at: datetime
    deleted_counts: dict[str, int]
