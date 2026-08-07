from enum import StrEnum


class PreferredLanguage(StrEnum):
    AR = "ar"
    EN = "en"


class CareerPathMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ResumeWorkspaceStage(StrEnum):
    UNDERSTANDING = "understanding"
    WRITING = "writing"
    REVIEW = "review"
    COMPLETE = "complete"


class ResumeMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ResumeMessageKind(StrEnum):
    TEXT = "text"
    QUESTION = "question"
    UNDERSTANDING = "understanding"
    SUGGESTION = "suggestion"
    STATUS = "status"


class ResumeMessageStatus(StrEnum):
    SENT = "sent"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DISMISSED = "dismissed"
    FAILED = "failed"


class ResumeDraftVersionReason(StrEnum):
    INITIAL_GENERATION = "initial_generation"
    MANUAL_EDIT = "manual_edit"
    AI_REWRITE = "ai_rewrite"
    RESTORE = "restore"
    REVIEW = "review"


class ResumeDraftStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    EXPORT_READY = "export_ready"


class SourceKind(StrEnum):
    MANUAL = "manual"
    CV_UPLOAD = "cv_upload"
    LINKEDIN_EXPORT = "linkedin_export"
    LICENSED_FEED = "licensed_feed"


class VerificationStatus(StrEnum):
    EXTRACTED = "extracted"
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"


class FactCategory(StrEnum):
    IDENTITY = "identity"
    EDUCATION = "education"
    EXPERIENCE = "experience"
    CERTIFICATION = "certification"
    SKILL = "skill"
    PROJECT = "project"
    LANGUAGE = "language"
    ACHIEVEMENT = "achievement"
    PREFERENCE = "preference"
    ELIGIBILITY = "eligibility"


class IntakeMethod(StrEnum):
    MANUAL = "manual"
    USER_UPLOAD = "user_upload"
    LICENSED_FEED = "licensed_feed"


class RequirementCategory(StrEnum):
    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    LANGUAGE = "language"
    LOCATION = "location"
    ELIGIBILITY = "eligibility"
    OTHER = "other"


class RequirementImportance(StrEnum):
    MANDATORY = "mandatory"
    PREFERRED = "preferred"


class RequirementMatchStatus(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ReadinessBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConfidenceBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApplyDecision(StrEnum):
    APPLY_NOW = "apply_now"
    IMPROVE_THEN_APPLY = "improve_then_apply"
    LOW_RETURN = "low_return"
    NEED_INFORMATION = "need_information"


class DocumentKind(StrEnum):
    CV = "cv"
    COVER_LETTER = "cover_letter"


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    EXPORT_READY = "export_ready"


class ClaimType(StrEnum):
    IDENTITY = "identity"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    SKILL = "skill"
    ACHIEVEMENT = "achievement"
    PROJECT = "project"
    CERTIFICATION = "certification"
    LANGUAGE = "language"
    PREFERENCE = "preference"
    SALUTATION = "salutation"
    INTENT = "intent"
    TRANSITION = "transition"

    @property
    def is_factual(self) -> bool:
        return self not in {self.SALUTATION, self.INTENT, self.TRANSITION}


class ApplicationStatus(StrEnum):
    DISCOVERED = "discovered"
    SAVED = "saved"
    PREPARING = "preparing"
    READY = "ready"
    SUBMITTED = "submitted"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"


class OutcomeKind(StrEnum):
    SCREENING = "screening"
    INTERVIEW = "interview"
    REJECTION = "rejection"
    OFFER = "offer"
    WITHDRAWAL = "withdrawal"
