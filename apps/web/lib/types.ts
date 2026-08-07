export type Locale = "ar" | "en";

export type LocalizedText = {
  ar: string;
  en: string;
};

export type EvidenceStatus = "confirmed" | "extracted" | "unconfirmed";
export type RequirementStatus = "supported" | "partial" | "unsupported" | "unknown";
export type JobRequirementCategory = "skill" | "experience" | "education" | "certification" | "language" | "location" | "eligibility" | "other";
export type JobRecommendation = "apply_now" | "improve_then_apply" | "low_return" | "need_information";
export type ReadinessBand = "low" | "medium" | "high";
export type CareerPathSignal = "strong" | "partial" | "needs_experiment";
export type CareerPathEvidenceSource = "confirmed_fact" | "chat";
export type ApplicationStage =
  | "discovered"
  | "saved"
  | "preparing"
  | "ready"
  | "applied"
  | "interview"
  | "rejected"
  | "offer"
  | "withdrawn";

export type EvidenceFact = {
  id: string;
  category: "identity" | "experience" | "education" | "skill" | "project" | "certificate" | "language" | "achievement" | "preference" | "eligibility";
  title: LocalizedText;
  detail: LocalizedText;
  source: LocalizedText;
  status: EvidenceStatus;
  updatedAt: string;
  structuredValue?: Record<string, unknown>;
  sourceExcerpt?: string | null;
  extractionConfidence?: number | null;
};

export type CareerPathEvidence = {
  source: CareerPathEvidenceSource;
  reference: string;
};

export type CareerPathSuggestion = {
  title: string;
  why_fit: string[];
  unknowns: string[];
  seven_day_experiment: string;
  signal: CareerPathSignal;
  evidence: CareerPathEvidence[];
};

export type CareerPathMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  suggestions: CareerPathSuggestion[];
  model: string | null;
  created_at: string;
};

export type CareerPathConversation = {
  id: string;
  revision: number;
  messages: CareerPathMessage[];
};

export type CareerPathWorkspace = {
  provider_ready: boolean;
  provider: string;
  model: string | null;
  profile_id: string;
  confirmed_fact_count: number;
  consent_required: boolean;
  conversation: CareerPathConversation | null;
};

export type CareerPathMessageInput = {
  content: string;
  client_turn_id: string;
  expected_revision: number;
  data_sharing_acknowledged: boolean;
};

export type JobRequirement = {
  id: string;
  category: JobRequirementCategory;
  label: LocalizedText;
  kind: "essential" | "preferred";
  weight: number;
  status: RequirementStatus;
  evidence?: LocalizedText;
  evidenceFactId?: string;
  explanation: LocalizedText;
  needsUserReview?: boolean;
  userAdded?: boolean;
};

export type Job = {
  id: string;
  analysisId?: string;
  requirementsReviewedAt?: string;
  title: LocalizedText;
  company: LocalizedText;
  location: LocalizedText;
  source: LocalizedText;
  freshness: LocalizedText;
  employmentType: LocalizedText;
  coverage: number;
  recommendation: JobRecommendation;
  readiness: ReadinessBand;
  confidence: ReadinessBand;
  description: LocalizedText;
  originalUrl?: string;
  requirements: JobRequirement[];
  isDemo: boolean;
};

export type DashboardStageCounts = {
  saved: number;
  ready: number;
  applied: number;
  interviews: number;
};

export type DashboardData = {
  profileQualityPercent: number;
  confirmedFacts: number;
  totalFacts: number;
  submittedApplications: number;
  qualifiedInterviews: number;
  interviewRate: number | null;
  actionsDue: number;
  applicationStages: DashboardStageCounts;
  topOpportunities: Job[];
};

export type Application = {
  id: string;
  jobId: string;
  role: LocalizedText;
  company: LocalizedText;
  location: LocalizedText;
  stage: ApplicationStage;
  updatedAt: string;
  nextAction: LocalizedText;
  documentVersion: string;
  isDemo: boolean;
};

export type ManualJobInput = {
  title: string;
  company: string;
  location: string;
  description: string;
  originalUrl?: string;
};

export type ApiResult<T> = {
  data: T;
  source: "api" | "demo";
  notice?: string;
};
