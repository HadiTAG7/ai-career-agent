import { demoJobs } from "@/lib/demo-data";
import { localized } from "@/lib/i18n";
import { formatDisplayDate, normalizeApiDate } from "@/lib/utils";
import type { ApiResult, Application, CareerPathMessageInput, CareerPathWorkspace, DashboardData, Job, JobRequirement, JobRequirementCategory, ManualJobInput, RequirementStatus } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
// Render's free staging service may need close to a minute to wake after being idle.
// Keep each read attempt bounded, but retry one idempotent GET so the first visit does
// not fail while the service is already spinning up.
const REQUEST_TIMEOUT_MS = 35_000;
const SAFE_GET_ATTEMPTS = 2;
const SAFE_GET_RETRY_DELAY_MS = 500;
const RETRYABLE_GET_STATUSES = new Set([502, 503, 504]);
type ApiRequestOptions = RequestInit & { timeoutMs?: number };
type TokenGetter = () => Promise<string | null>;
let tokenGetter: TokenGetter | null = null;

class ApiUnavailableError extends Error {}

export class ApiHttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly code?: string,
    public readonly requestId?: string,
  ) {
    super(`API request failed with ${status}: ${detail}`);
    this.name = "ApiHttpError";
  }
}

export function setApiTokenGetter(getter: TokenGetter | null) {
  tokenGetter = getter;
}

function canUseDemoFallback(error: unknown) {
  return !API_BASE_URL && error instanceof ApiUnavailableError;
}

const API_ERROR_MESSAGES: Record<string, { ar: string; en: string }> = {
  ai_provider_not_configured: { ar: "المستشار الذكي غير مفعّل على الخادم بعد.", en: "The AI adviser is not enabled on the server yet." },
  ai_provider_unavailable: { ar: "المستشار الذكي غير متاح مؤقتًا. رسالتك محفوظة ويمكنك المحاولة مرة أخرى.", en: "The AI adviser is temporarily unavailable. Your message is preserved so you can try again." },
  career_path_rate_limited: { ar: "وصلت إلى حد المحادثة المؤقت. حاول لاحقًا.", en: "You have reached the temporary conversation limit. Please try again later." },
  career_path_revision_conflict: { ar: "تغيّرت المحادثة أو حقائق الملف. حدّثنا السجل؛ راجع الرسالة ثم أعد الإرسال.", en: "The conversation or profile facts changed. We refreshed the transcript; review it and send again." },
  career_path_context_changed: { ar: "تغيّرت المحادثة أو حقائق الملف. حدّثنا السجل؛ راجع الرسالة ثم أعد الإرسال.", en: "The conversation or profile facts changed. We refreshed the transcript; review it and send again." },
  career_path_save_conflict: { ar: "تغيّرت المحادثة أثناء الحفظ. حدّثنا السجل؛ راجعه ثم أعد المحاولة.", en: "The conversation changed while saving. We refreshed it; review and try again." },
  career_profile_evidence_required: { ar: "جهّز سيرتك وراجع حقيقة مهنية واحدة على الأقل قبل تحديد المسار.", en: "Prepare your resume and confirm at least one career fact before discovering your path." },
  profile_required: { ar: "أنشئ ملفك المهني من صفحة السيرة أولًا قبل تحليل الوظائف أو حفظ التقديمات.", en: "Create your career profile from the resume page before analyzing jobs or saving applications." },
  data_sharing_acknowledgement_required: { ar: "وافق على إشعار مشاركة البيانات قبل بدء المحادثة.", en: "Acknowledge the data-sharing notice before starting the conversation." },
  profile_deletion_in_progress: { ar: "جارٍ حذف بياناتك حاليًا. انتظر اكتمال الحذف قبل أي إجراء جديد.", en: "Your data deletion is in progress. Wait for it to finish before starting new actions." },
  internal_error: { ar: "حدث خطأ داخلي في الخادم. حاول مرة أخرى.", en: "An internal server error occurred. Please try again." },
  unsupported_claims: { ar: "بعض العبارات غير مدعومة بأدلة مؤكدة، لذا لم يُنشأ المستند.", en: "Some claims are not backed by confirmed evidence, so the document was not created." },
  resume_ai_consent_required: { ar: "وافق على إرسال محتوى السيرة إلى مزود الذكاء الاصطناعي قبل المتابعة.", en: "Acknowledge sending the resume content to the AI provider before continuing." },
  resume_ai_not_configured: { ar: "مساعد السيرة الذكي غير مفعّل على الخادم.", en: "The AI resume assistant is not enabled on the server." },
  resume_ai_unavailable: { ar: "تعذر تحليل السيرة مؤقتًا. احتفظنا بمدخلاتك ويمكنك إعادة المحاولة.", en: "Resume analysis is temporarily unavailable. Your input is preserved so you can retry." },
  resume_text_unreadable: { ar: "لم نجد نصًا مقروءًا في الملف. استخدم PDF نصيًا أو ملف DOCX؛ صور السيرة الممسوحة تحتاج دعم OCR لاحقًا.", en: "No readable text was found. Use a text-based PDF or DOCX; scanned resumes require OCR support later." },
  resume_content_duplicate: { ar: "سبق استيراد الملف ولم يُحلل بالذكاء بعد.", en: "This file was imported before but has not been analyzed by AI yet." },
  resume_writer_consent_required: { ar: "وافق على استخدام الحقائق المهنية مع كاتب السيرة الذكي قبل المتابعة.", en: "Acknowledge sharing professional evidence with the AI resume writer before continuing." },
  resume_writer_not_configured: { ar: "كاتب السيرة الذكي غير مفعّل على الخادم.", en: "The AI resume writer is not enabled on the server." },
  resume_writer_unavailable: { ar: "تعذر تشغيل كاتب السيرة مؤقتًا. إجاباتك محفوظة في الصفحة ويمكنك إعادة المحاولة.", en: "The AI resume writer is temporarily unavailable. Your answers remain on the page so you can retry." },
  resume_writer_evidence_required: { ar: "حلّل سيرتك أو أكمل المقابلة المنظمة أولًا، ثم ابدأ الأسئلة الذكية.", en: "Analyze a resume or complete the guided interview before starting smart questions." },
  resume_review_required: { ar: "راجع نص السيرة ووافق عليه قبل تنزيل PDF.", en: "Review and approve the resume text before downloading the PDF." },
  resume_review_stale: { ar: "تغيّر محتوى السيرة بعد موافقتك. راجع النسخة الأخيرة ثم أكّد مجددًا قبل التنزيل.", en: "The resume changed after your approval. Review the latest version and re-acknowledge before downloading." },
  resume_review_blocked: { ar: "توجد عبارات غير مدعومة بأدلة مؤكدة. عالج الملاحظات الظاهرة قبل التصدير.", en: "Some content is not backed by confirmed evidence. Resolve the flagged items before exporting." },
  resume_export_failed: { ar: "تعذر إنشاء ملف PDF مؤقتًا. حاول مرة أخرى.", en: "The PDF could not be generated. Please try again." },
  resume_workspace_revision_conflict: { ar: "تغيّرت مساحة السيرة في تبويب آخر. حدّثنا آخر نسخة؛ راجعها ثم أعد المحاولة.", en: "The resume workspace changed in another tab. We loaded the latest version; review it and try again." },
  resume_draft_revision_conflict: { ar: "تغيّرت مسودة السيرة في مكان آخر. حمّلنا أحدث نسخة؛ راجعها ثم أعد المحاولة.", en: "The resume draft changed elsewhere. We loaded the latest version; review it and try again." },
  resume_evidence_revision_conflict: { ar: "تغيّرت معلومات السيرة أثناء المراجعة. حدّثنا القائمة؛ راجعها ثم أعد المحاولة.", en: "Resume facts changed during review. We refreshed the list; review it and try again." },
  resume_import_draft_exists: { ar: "توجد مسودة حالية. امسحها أولًا إذا أردت إنشاء مسودة من ملف آخر.", en: "A draft already exists. Clear it before creating one from another file." },
  resume_import_confirmed_evidence_required: { ar: "حدد معلومة صحيحة واحدة على الأقل من الملف قبل إنشاء المسودة.", en: "Select at least one accurate fact from the file before creating the draft." },
  resume_import_fact_mismatch: { ar: "بعض المعلومات المحددة لا تنتمي إلى هذا الملف. حدّثنا المراجعة؛ اختر معلومات الملف نفسه فقط.", en: "Some selected facts do not belong to this file. We refreshed the review; select facts from this file only." },
  resume_import_fact_rejected: { ar: "إحدى المعلومات المحددة سبق استبعادها. راجع القائمة واختر المعلومات غير المستبعدة فقط.", en: "One selected fact was previously rejected. Review the list and select only active facts." },
  resume_import_review_incomplete: { ar: "راجع كل معلومات الملف وحدد الصحيح منها قبل الانتقال إلى التقييم والأسئلة.", en: "Review every extracted fact before moving to the assessment and questions." },
  resume_import_review_idempotency_conflict: { ar: "استُخدم معرف المراجعة نفسه لطلب مختلف. حدّث الصفحة ثم أعد المحاولة.", en: "The same review request id was reused for different content. Refresh the page and try again." },
  resume_import_phase_conflict: { ar: "تغيّرت مرحلة بناء السيرة. حدّثنا الصفحة؛ راجع الخطوة الظاهرة ثم حاول مجددًا.", en: "The resume flow changed. We refreshed it; review the current step and try again." },
  resume_import_guided_flow_required: { ar: "هذا الملف يمر عبر المسار الموجّه. تابع خطوات الاستيراد الظاهرة.", en: "This file goes through the guided flow. Continue with the shown import steps." },
  resume_import_questions_incomplete: { ar: "أكمل أسئلة النقص المتبقية أو تخطَّها قبل إنشاء المسودة.", en: "Complete or skip the remaining gap questions before generating the draft." },
  resume_understanding_pending: { ar: "أكد ما فهمه المساعد أو عدّله قبل الانتقال للخطوة التالية.", en: "Confirm or correct the current understanding before continuing." },
  resume_correction_required: { ar: "اكتب النص المصحح قبل الحفظ.", en: "Enter the corrected text before saving." },
  resume_gap_interview: { ar: "أجب عن سؤال النقص الحالي أو تخطَّه قبل المتابعة.", en: "Answer or skip the current gap question before continuing." },
  resume_draft_required: { ar: "أنشئ مسودة السيرة أولًا قبل محاولة تعديلها.", en: "Generate the resume draft before editing it." },
  resume_suggestion_stale: { ar: "انتهت صلاحية التحسين المقترح لأن المسودة تغيّرت. اطلب تحسينًا جديدًا.", en: "The suggested improvement expired because the draft changed. Request a new one." },
  resume_rewrite_not_supported: { ar: "مزوّد الكتابة الحالي لا يدعم إعادة صياغة المقاطع.", en: "The configured writer does not support section rewrites." },
  resume_quick_action_invalid: { ar: "هذا الأمر غير مدعوم في هذه المرحلة.", en: "That command is not supported at this step." },
  resume_language_change_requires_new_version: { ar: "تغيير لغة السيرة يتطلب إنشاء نسخة جديدة بدل تعديل النسخة الحالية.", en: "Changing the resume language requires creating a new version instead of editing this one." },
  resume_conversation_language_change_not_allowed: { ar: "لا يمكن تغيير لغة المحادثة بعد بدايتها. أنشئ مساحة جديدة لتغييرها.", en: "The conversation language cannot change after it starts. Start a new workspace to change it." },
  resume_verified_translation_invalid: { ar: "تعذر التحقق من الترجمة المعتمدة. أعد إنشاء المسودة.", en: "The verified translation could not be validated. Regenerate the draft." },
};

export function apiErrorMessage(error: unknown, locale: "ar" | "en") {
  if (error instanceof ApiHttpError) {
    const known = error.code ? API_ERROR_MESSAGES[error.code] : undefined;
    if (known) return known[locale];
    // Unknown codes fall through to generic copy; keep the request id visible so a
    // reported failure can be correlated with server logs.
    const reference = error.requestId
      ? (locale === "ar" ? ` (مرجع الطلب: ${error.requestId})` : ` (request ref: ${error.requestId})`)
      : "";
    if (error.status === 401) return locale === "ar" ? "انتهت جلسة الدخول أو لم تعد صالحة. سجّل الدخول مجددًا." : "Your sign-in session is missing or expired. Please sign in again.";
    if (error.status === 422) return (locale === "ar" ? `تعذر قبول البيانات: ${error.detail}` : `The submitted data was rejected: ${error.detail}`) + reference;
    return (locale === "ar" ? `تعذر إكمال الطلب (رمز ${error.status}): ${error.detail}` : `The request could not be completed (${error.status}): ${error.detail}`) + reference;
  }
  if (error instanceof TypeError || (error instanceof DOMException && error.name === "AbortError")) {
    return locale === "ar"
      ? "لم يستجب الخادم بعد الانتظار وإعادة المحاولة. إذا كانت هذه أول زيارة بعد خمول، انتظر قليلًا ثم حاول مجددًا."
      : "The server did not respond after waiting and retrying. If this is the first visit after idle time, wait briefly and try again.";
  }
  return locale === "ar" ? "حدث خطأ غير متوقع. لم نستبدل النتيجة ببيانات تجريبية." : "An unexpected error occurred. The result was not replaced with demo data.";
}

function isRetryableGetError(error: unknown) {
  return error instanceof TypeError || (error instanceof DOMException && error.name === "AbortError");
}

async function waitForRetry(attempt: number) {
  await new Promise<void>((resolve) => {
    globalThis.setTimeout(resolve, SAFE_GET_RETRY_DELAY_MS * attempt);
  });
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number) {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

async function apiResponse(path: string, init?: ApiRequestOptions): Promise<Response> {
  if (!API_BASE_URL) throw new ApiUnavailableError("API base URL is not configured");

  const { timeoutMs = REQUEST_TIMEOUT_MS, ...requestInit } = init ?? {};
  // Fetch timeouts should measure the API request, not Clerk token initialization.
  const token = tokenGetter ? await tokenGetter() : null;
  const headers = new Headers(requestInit.headers);
  if (!(requestInit.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const method = (requestInit.method ?? "GET").toUpperCase();
  const attempts = method === "GET" ? SAFE_GET_ATTEMPTS : 1;
  const url = `${API_BASE_URL}${path}`;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    let response: Response;
    try {
      response = await fetchWithTimeout(url, { ...requestInit, headers }, timeoutMs);
    } catch (error) {
      if (attempt < attempts && isRetryableGetError(error)) {
        await waitForRetry(attempt);
        continue;
      }
      throw error;
    }

    if (attempt < attempts && RETRYABLE_GET_STATUSES.has(response.status)) {
      await response.body?.cancel().catch(() => undefined);
      await waitForRetry(attempt);
      continue;
    }

    if (!response.ok) {
      let detail = response.statusText || "Request failed";
      let code: string | undefined;
      let requestId: string | undefined;
      try {
        const payload = await response.json() as { detail?: unknown };
        if (typeof payload.detail === "string") {
          detail = payload.detail;
        } else if (Array.isArray(payload.detail)) {
          // FastAPI validation errors arrive as an array of {loc, msg, type} entries;
          // render them as readable text instead of raw JSON.
          detail = payload.detail
            .map((entry) => {
              if (entry && typeof entry === "object") {
                const item = entry as { msg?: unknown; loc?: unknown };
                const location = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
                const message = typeof item.msg === "string" ? item.msg : String(item.msg ?? "");
                return location ? `${location}: ${message}` : message;
              }
              return String(entry);
            })
            .join("; ");
        } else if (payload.detail && typeof payload.detail === "object") {
          const structured = payload.detail as { code?: unknown; message?: unknown; request_id?: unknown };
          code = typeof structured.code === "string" ? structured.code : undefined;
          requestId = typeof structured.request_id === "string" ? structured.request_id : undefined;
          detail = typeof structured.message === "string" ? structured.message : JSON.stringify(payload.detail);
        } else {
          detail = JSON.stringify(payload.detail ?? payload);
        }
      } catch {
        // Keep the status text when the API does not return JSON.
      }
      throw new ApiHttpError(response.status, detail, code, requestId);
    }
    return response;
  }

  throw new ApiUnavailableError("API request exhausted its retry budget");
}

async function apiRequest<T>(path: string, init?: ApiRequestOptions): Promise<T> {
  const response = await apiResponse(path, init);
  return (await response.json()) as T;
}

type BackendRequirement = {
  id: string;
  category: JobRequirementCategory;
  importance: "mandatory" | "preferred";
  text: string;
  weight: number;
  needs_user_review: boolean;
  is_active: boolean;
  user_added: boolean;
};

type BackendJob = {
  id: string;
  source_url: string | null;
  title: string;
  company: string;
  description: string;
  location: string | null;
  created_at: string;
  requirements_reviewed_at: string | null;
  source_policy: { display_name: string };
  requirements: BackendRequirement[];
};

type BackendProfile = { id: string };

export type ApiCareerProfile = {
  id: string;
  full_name: string;
  headline: string | null;
  preferred_language: "ar" | "en";
  city: string | null;
  completed_fact_categories: string[];
};

export type ApiCareerFact = {
  id: string;
  source_id: string;
  category: string;
  label: string;
  detail: string | null;
  verification_status: "confirmed" | "extracted" | "unconfirmed";
  source_excerpt: string | null;
  extraction_confidence: number | null;
  structured_value: Record<string, unknown>;
  created_at: string;
};

export type ApiCareerProfileSummary = {
  profile_id: string;
  profile_quality_percent: number;
  confirmed_facts: number;
  total_facts: number;
  extracted_facts: number;
  unconfirmed_facts: number;
  covered_quality_categories: string[];
  total_quality_categories: number;
};

export type ApiEvidenceSource = {
  id: string;
  kind: "manual" | "cv_upload" | "linkedin_export" | "licensed_feed";
  label: string;
  original_filename: string | null;
};

export type ApiImportResult = {
  source: ApiEvidenceSource;
  facts: ApiCareerFact[];
  requires_user_review: boolean;
  analysis_status: "created" | "ai_upgraded" | "already_ai_analyzed";
};

export type ApiCareerFactBatchConfirmResult = {
  facts: ApiCareerFact[];
  evidence_revision: number;
};

export type ApiResumeFactCategory =
  | "identity"
  | "experience"
  | "education"
  | "skill"
  | "project"
  | "certification"
  | "language"
  | "achievement"
  | "preference"
  | "eligibility";

export type ApiResumeSectionKey =
  | Exclude<ApiResumeFactCategory, "identity" | "preference" | "eligibility">
  | "trading_experience";

export type ApiResumeQuestion = {
  id: string;
  category: ApiResumeFactCategory;
  question: string;
  why_it_matters: string;
  placeholder: string;
  required: boolean;
};

export type ApiResumeDraftItem = {
  id: string;
  title: string;
  organization: string | null;
  date_range: string | null;
  location: string | null;
  bullets: string[];
  evidence_handles: string[];
};

export type ApiResumeDraftSection = {
  key: ApiResumeSectionKey;
  title: string;
  items: ApiResumeDraftItem[];
};

export type ApiResumeDraftContent = {
  headline: string;
  professional_summary: string;
  summary_evidence_handles: string[];
  sections: ApiResumeDraftSection[];
};

export type ApiResumeWorkspaceStage = "understanding" | "writing" | "review" | "complete";
export type ApiResumeMessageKind = "text" | "question" | "understanding" | "suggestion" | "status";
export type ApiResumeMessageStatus = "sent" | "pending" | "confirmed" | "corrected" | "dismissed" | "failed";

export type ApiResumeRecord = {
  schema_version: "resume_record.v1";
  record_type: ApiResumeFactCategory;
  source_handles: string[];
  source_section?: string | null;
  title: string;
  organization?: string | null;
  date_range?: string | null;
  location?: string | null;
  degree?: string | null;
  institution?: string | null;
  issuer?: string | null;
  gpa_score?: string | null;
  gpa_scale?: string | null;
  gpa_display_recommended?: boolean | null;
  honors?: string | null;
  proficiency?: string | null;
  responsibilities: string[];
  outcomes: string[];
  tools: string[];
  coursework: string[];
};

export type ApiResumeUnderstanding = {
  id: string;
  understanding: string;
  understanding_detail?: {
    summary?: string;
    confidence?: "low" | "medium" | "high";
    evidence_handles?: string[];
    confirmation_question?: string;
  };
  proposed_records: ApiResumeRecord[];
  next_question?: ApiResumeQuestion | null;
  draft_patch?: Record<string, unknown> | null;
  ready_to_generate?: boolean;
  question?: Record<string, unknown>;
  source_message_id?: string;
};

export type ApiResumeRewriteSuggestion = {
  suggestion_id: string;
  target_kind: "headline" | "professional_summary" | "bullet";
  section_key: ApiResumeSectionKey | null;
  item_id?: string | null;
  bullet_index?: number | null;
  mode: "stronger" | "shorter" | "professional" | "custom";
  instruction?: string | null;
  before_text: string;
  after_text: string;
  base_draft_revision: number;
  evidence_handles: string[];
};

export type ApiResumeMessage = {
  id: string;
  sequence: number;
  role: "user" | "assistant";
  kind: ApiResumeMessageKind;
  content: string;
  structured_payload: Record<string, unknown>;
  status: ApiResumeMessageStatus;
  client_turn_id: string | null;
  created_at: string;
};

export type ApiResumeDraftVersion = {
  id: string;
  workspace_id: string;
  version: number;
  base_version_id: string | null;
  reason: "initial_generation" | "manual_edit" | "ai_rewrite" | "restore" | "review";
  status: "draft" | "reviewed" | "export_ready";
  content: ApiResumeDraftContent;
  diff: Record<string, unknown>;
  evidence_revision: number;
  reviewed_at: string | null;
  reviewed_by_owner_id?: string | null;
  review_hash?: string | null;
  created_at: string;
};

export type ApiResumeWorkspace = {
  id: string;
  profile_id: string;
  /** Language used by the assistant while interviewing the user. */
  conversation_language?: "ar" | "en";
  /** Language of the generated resume and exported document. */
  language: "ar" | "en";
  stage: ApiResumeWorkspaceStage;
  revision: number;
  evidence_revision: number;
  readiness_score: number;
  section_coverage: Record<string, boolean>;
  current_draft: ApiResumeDraftContent | null;
  draft_revision: number;
  contact: { email?: string | null; phone?: string | null; linkedin?: string | null };
  pending_understanding: ApiResumeUnderstanding | null;
  pending_suggestion: ApiResumeRewriteSuggestion | null;
  consent_required: boolean;
  consent_version?: string | null;
  consented_at?: string | null;
  provider_ready: boolean;
  provider: string | null;
  model: string | null;
  provider_metadata?: Record<string, unknown>;
  messages: ApiResumeMessage[];
  versions: ApiResumeDraftVersion[];
  created_at?: string;
  updated_at: string;
};

export type ApiResumeReview = {
  workspace_id: string;
  draft_version_id: string;
  draft_revision: number;
  status: "draft" | "reviewed" | "export_ready";
  reviewed_at: string;
  review_hash: string;
  evidence_revision: number;
  export_allowed: boolean;
};

type BackendMatch = {
  id: string;
  requirement_id: string;
  evidence_fact_id: string | null;
  status: "matched" | "missing" | "unknown";
  reason: string;
  requirement: BackendRequirement;
};

type BackendAnalysis = {
  id: string;
  job_id: string;
  coverage_score: number;
  readiness_band: Job["readiness"];
  confidence_band: Job["confidence"];
  decision: Job["recommendation"];
  requirement_matches: BackendMatch[];
};

type BackendDashboard = {
  profile_id: string;
  profile_quality_percent: number;
  confirmed_facts: number;
  total_facts: number;
  application_pipeline: Partial<Record<
    "discovered" | "saved" | "preparing" | "ready" | "submitted" | "interview" | "rejected" | "offer" | "withdrawn",
    number
  >>;
  submitted_applications: number;
  qualified_interviews: number;
  qualified_interviews_per_completed_application: number | null;
  actions_due: number;
  top_opportunities: BackendAnalysis[];
};

function mapStatus(status: BackendMatch["status"]): RequirementStatus {
  if (status === "matched") return "supported";
  if (status === "missing") return "unsupported";
  return "unknown";
}

function mapRequirement(requirement: BackendRequirement, match?: BackendMatch): JobRequirement {
  const status = match ? mapStatus(match.status) : "unknown";
  return {
    id: requirement.id,
    category: requirement.category,
    label: localized(requirement.text, requirement.text),
    kind: requirement.importance === "mandatory" ? "essential" : "preferred",
    weight: requirement.weight,
    status,
    evidence: match?.evidence_fact_id ? localized("حقيقة مؤكدة في ملفك", "Confirmed fact in your profile") : undefined,
    evidenceFactId: match?.evidence_fact_id ?? undefined,
    explanation: localized(match?.reason ?? "لم يُحلل هذا المتطلب بعد.", match?.reason ?? "This requirement has not been analyzed yet."),
    needsUserReview: requirement.needs_user_review,
    userAdded: requirement.user_added,
  };
}

function mapBackendJob(job: BackendJob, analysis?: BackendAnalysis): Job {
  const matches = new Map(analysis?.requirement_matches.map((match) => [match.requirement_id, match]));
  const createdDate = normalizeApiDate(job.created_at);
  return {
    id: job.id,
    analysisId: analysis?.id,
    requirementsReviewedAt: job.requirements_reviewed_at ?? undefined,
    title: localized(job.title, job.title),
    company: localized(job.company, job.company),
    location: localized(job.location || "غير محدد", job.location || "Not specified"),
    source: localized(job.source_policy.display_name, job.source_policy.display_name),
    freshness: createdDate
      ? localized(`أضيف في ${formatDisplayDate(createdDate, "ar")}`, `Added ${formatDisplayDate(createdDate, "en")}`)
      : localized("تاريخ الإضافة غير متاح", "Added date unavailable"),
    coverage: analysis?.coverage_score ?? 0,
    recommendation: analysis?.decision ?? "need_information",
    readiness: analysis?.readiness_band ?? "low",
    confidence: analysis?.confidence_band ?? "low",
    description: localized(job.description, job.description),
    originalUrl: job.source_url ?? undefined,
    requirements: job.requirements.filter((requirement) => requirement.is_active).map((requirement) => mapRequirement(requirement, matches.get(requirement.id))),
    isDemo: false,
  };
}

async function getLatestAnalysis(jobId: string): Promise<BackendAnalysis | undefined> {
  try {
    return await apiRequest<BackendAnalysis>(`/v1/jobs/${encodeURIComponent(jobId)}/analyses/latest`);
  } catch (error) {
    if (error instanceof ApiHttpError && error.status === 404) return undefined;
    throw error;
  }
}

async function mapWithConcurrency<T, R>(items: T[], limit: number, mapper: (item: T) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  async function worker() {
    while (nextIndex < items.length) {
      const currentIndex = nextIndex;
      nextIndex += 1;
      results[currentIndex] = await mapper(items[currentIndex]);
    }
  }
  const workerCount = Math.min(limit, items.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return results;
}

export async function getJobs(): Promise<Job[]> {
  const jobs = await apiRequest<BackendJob[]>("/v1/jobs");
  const analyses = await mapWithConcurrency(jobs, 4, (job) => getLatestAnalysis(job.id));
  return jobs.map((job, index) => mapBackendJob(job, analyses[index]));
}

// Deduplicated, concurrency-capped job lookups: several views need one job per row and
// must not issue an unbounded parallel fan-out of GET /v1/jobs/{id} requests.
async function fetchJobsByIds(jobIds: string[]): Promise<Map<string, BackendJob>> {
  const uniqueIds = Array.from(new Set(jobIds));
  const results = await mapWithConcurrency(uniqueIds, 4, async (jobId) => {
    try {
      return await apiRequest<BackendJob>(`/v1/jobs/${encodeURIComponent(jobId)}`);
    } catch (error) {
      if (error instanceof ApiHttpError && error.status === 404) return null;
      throw error;
    }
  });
  const jobsById = new Map<string, BackendJob>();
  uniqueIds.forEach((jobId, index) => {
    const job = results[index];
    if (job) jobsById.set(jobId, job);
  });
  return jobsById;
}

export async function getDashboard(): Promise<DashboardData> {
  const dashboard = await apiRequest<BackendDashboard>("/v1/dashboard");
  const jobsById = await fetchJobsByIds(dashboard.top_opportunities.map((analysis) => analysis.job_id));
  const topOpportunities = dashboard.top_opportunities.flatMap((analysis) => {
    const job = jobsById.get(analysis.job_id);
    return job ? [mapBackendJob(job, analysis)] : [];
  });
  const pipeline = dashboard.application_pipeline;

  return {
    profileQualityPercent: dashboard.profile_quality_percent,
    confirmedFacts: dashboard.confirmed_facts,
    totalFacts: dashboard.total_facts,
    submittedApplications: dashboard.submitted_applications,
    qualifiedInterviews: dashboard.qualified_interviews,
    interviewRate: dashboard.qualified_interviews_per_completed_application,
    actionsDue: dashboard.actions_due,
    applicationStages: {
      saved: (pipeline.discovered ?? 0) + (pipeline.saved ?? 0),
      ready: (pipeline.preparing ?? 0) + (pipeline.ready ?? 0),
      applied: pipeline.submitted ?? 0,
      interviews: pipeline.interview ?? 0,
    },
    topOpportunities,
  };
}

export async function getJob(jobId: string): Promise<ApiResult<Job>> {
  const explicitDemo = demoJobs.find((job) => job.id === jobId);
  if (explicitDemo) return { data: explicitDemo, source: "demo", notice: "Showing an explicit local demo opportunity." };
  // Never silently substitute a different record: an unknown id must surface as
  // not-found rather than rendering the wrong job.
  const job = await apiRequest<BackendJob>(`/v1/jobs/${encodeURIComponent(jobId)}`);
  const analysis = await getLatestAnalysis(jobId);
  return { data: mapBackendJob(job, analysis), source: "api" };
}

export async function correctJobRequirement(
  jobId: string,
  requirementId: string,
  input: { text: string; category: JobRequirementCategory; importance: "mandatory" | "preferred"; correctionReason: string }
) {
  return apiRequest<BackendRequirement>(
    `/v1/jobs/${encodeURIComponent(jobId)}/requirements/${encodeURIComponent(requirementId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ text: input.text, category: input.category, importance: input.importance, correction_reason: input.correctionReason }),
    }
  );
}

export async function addJobRequirement(jobId: string, input: { text: string; category: JobRequirementCategory; importance: "mandatory" | "preferred"; correctionReason: string }) {
  return apiRequest<BackendRequirement>(`/v1/jobs/${encodeURIComponent(jobId)}/requirements`, {
    method: "POST",
    body: JSON.stringify({ text: input.text, category: input.category, importance: input.importance, weight: 1, correction_reason: input.correctionReason }),
  });
}

export async function retireJobRequirement(jobId: string, requirementId: string, correctionReason: string) {
  return apiRequest<BackendRequirement>(`/v1/jobs/${encodeURIComponent(jobId)}/requirements/${encodeURIComponent(requirementId)}/retire`, {
    method: "POST",
    body: JSON.stringify({ correction_reason: correctionReason }),
  });
}

export async function reviewJobRequirements(jobId: string): Promise<Job> {
  const job = await apiRequest<BackendJob>(`/v1/jobs/${encodeURIComponent(jobId)}/requirements/review`, { method: "POST" });
  return mapBackendJob(job);
}

// A user who has not created a profile yet gets a purposeful message instead of a raw 404.
async function requireProfile(): Promise<BackendProfile> {
  try {
    return await apiRequest<BackendProfile>("/v1/profiles");
  } catch (error) {
    if (error instanceof ApiHttpError && error.status === 404) {
      throw new ApiHttpError(404, error.detail, "profile_required", error.requestId);
    }
    throw error;
  }
}

export async function analyzeJob(jobId: string): Promise<Job> {
  const [job, profile] = await Promise.all([
    apiRequest<BackendJob>(`/v1/jobs/${encodeURIComponent(jobId)}`),
    requireProfile(),
  ]);
  const analysis = await apiRequest<BackendAnalysis>(`/v1/jobs/${encodeURIComponent(jobId)}/analyze`, {
    method: "POST",
    body: JSON.stringify({ profile_id: profile.id }),
  });
  return mapBackendJob(job, analysis);
}

type BackendApplication = {
  id: string;
  job_id: string;
  status: Exclude<Application["stage"], "applied"> | "submitted";
  next_action_at: string | null;
  notes: string | null;
  cv_document_id: string | null;
  updated_at: string | null;
};

export function mapApplicationStageFromApi(status: BackendApplication["status"]): Application["stage"] {
  return status === "submitted" ? "applied" : status;
}

export function mapApplicationStageToApi(status: Application["stage"]): BackendApplication["status"] {
  return status === "applied" ? "submitted" : status;
}

function mapBackendApplication(application: BackendApplication, job: BackendJob): Application {
  return {
    id: application.id,
    jobId: job.id,
    role: localized(job.title, job.title),
    company: localized(job.company, job.company),
    location: localized(job.location || "غير محدد", job.location || "Not specified"),
    stage: mapApplicationStageFromApi(application.status),
    updatedAt: normalizeApiDate(application.updated_at),
    nextAction: localized(application.notes || "راجع الوظيفة وحدد خطوتك التالية", application.notes || "Review the job and choose your next action"),
    documentVersion: application.cv_document_id ? "CV" : "—",
    isDemo: false,
  };
}

export async function getApplications(): Promise<Application[]> {
  const applications = await apiRequest<BackendApplication[]>("/v1/applications");
  const jobsById = await fetchJobsByIds(applications.map((application) => application.job_id));
  return applications.flatMap((application) => {
    const job = jobsById.get(application.job_id);
    return job ? [mapBackendApplication(application, job)] : [];
  });
}

export async function saveApplication(jobId: string, analysisId: string) {
  const profile = await requireProfile();
  return apiRequest<BackendApplication>("/v1/applications", {
    method: "POST",
    body: JSON.stringify({ profile_id: profile.id, job_id: jobId, analysis_id: analysisId, status: "saved" }),
  });
}

export async function updateApplication(applicationId: string, stage: Application["stage"]) {
  return apiRequest<BackendApplication>(`/v1/applications/${encodeURIComponent(applicationId)}`, {
    method: "PATCH",
    body: JSON.stringify({ status: mapApplicationStageToApi(stage) }),
  });
}

export async function createManualJob(input: ManualJobInput): Promise<ApiResult<Job>> {
  try {
    const createdJob = await apiRequest<BackendJob>("/v1/jobs/manual", {
      method: "POST",
      body: JSON.stringify({
        source_key: "manual",
        source_url: input.originalUrl,
        title: input.title,
        company: input.company,
        location: input.location || null,
        description: input.description,
      }),
    });
    return { data: mapBackendJob(createdJob), source: "api" };
  } catch (error) {
    if (!canUseDemoFallback(error)) throw error;
    const base = demoJobs[0];
    return {
      source: "demo",
      notice: "FastAPI is not configured; an explicit local demo analysis was created.",
      data: {
        ...base,
        id: "local-analysis",
        title: localized(input.title, input.title),
        company: localized(input.company, input.company),
        location: localized(input.location || "غير محدد", input.location || "Not specified"),
        description: localized(input.description, input.description),
        originalUrl: input.originalUrl,
        source: localized("وصف أدخله المستخدم", "User-provided description"),
        freshness: localized("أضيف الآن", "Added now"),
      },
    };
  }
}

export async function getCareerProfile(): Promise<ApiCareerProfile | null> {
  try {
    return await apiRequest<ApiCareerProfile>("/v1/profiles");
  } catch (error) {
    if (error instanceof ApiHttpError && error.status === 404) return null;
    throw error;
  }
}

export async function getCareerPathWorkspace() {
  return apiRequest<CareerPathWorkspace>("/v1/career-path");
}

export async function sendCareerPathMessage(input: CareerPathMessageInput) {
  return apiRequest<CareerPathWorkspace>("/v1/career-path/messages", {
    method: "POST",
    body: JSON.stringify(input),
    timeoutMs: 45_000,
  });
}

export async function deleteCareerPathConversation() {
  await apiResponse("/v1/career-path/conversation", { method: "DELETE" });
}

export async function createCareerProfile(input: { fullName: string; city?: string; preferredLanguage: "ar" | "en" }) {
  return apiRequest<ApiCareerProfile>("/v1/profiles", {
    method: "POST",
    body: JSON.stringify({
      full_name: input.fullName,
      city: input.city || null,
      preferred_language: input.preferredLanguage,
    }),
  });
}

export async function updateCompletedFactCategories(categories: string[]) {
  return apiRequest<ApiCareerProfile>("/v1/profiles", {
    method: "PATCH",
    body: JSON.stringify({ completed_fact_categories: categories }),
  });
}

export async function getCareerFacts(profileId: string) {
  return apiRequest<ApiCareerFact[]>(`/v1/profiles/${encodeURIComponent(profileId)}/facts`);
}

export async function getCareerProfileSummary(profileId: string) {
  return apiRequest<ApiCareerProfileSummary>(`/v1/profiles/${encodeURIComponent(profileId)}/summary`);
}

export async function getEvidenceSources(profileId: string) {
  return apiRequest<ApiEvidenceSource[]>(`/v1/profiles/${encodeURIComponent(profileId)}/sources`);
}

export async function createCareerFact(profileId: string, input: { category: string; label: string; detail: string }) {
  const sources = await getEvidenceSources(profileId);
  const manualSource = sources.find((source) => source.kind === "manual");
  if (!manualSource) throw new Error("The profile has no manual evidence source.");
  const fact = await apiRequest<ApiCareerFact>(`/v1/profiles/${encodeURIComponent(profileId)}/facts`, {
    method: "POST",
    body: JSON.stringify({
      source_id: manualSource.id,
      category: input.category,
      label: input.label,
      detail: input.detail,
    }),
  });
  return { fact, source: manualSource };
}

export async function importCareerFile(
  profileId: string,
  file: File,
  options: { useAi?: boolean; dataSharingAcknowledged?: boolean } = {},
) {
  const body = new FormData();
  body.set("file", file);
  body.set("use_ai", String(Boolean(options.useAi)));
  body.set("data_sharing_acknowledged", String(Boolean(options.dataSharingAcknowledged)));
  return apiRequest<ApiImportResult>(`/v1/profiles/${encodeURIComponent(profileId)}/imports`, { method: "POST", body, timeoutMs: 60_000 });
}

function resumeWorkspacePath(profileId: string, suffix = "") {
  return `/v1/profiles/${encodeURIComponent(profileId)}/resume-workspace${suffix}`;
}

export async function getResumeWorkspace(profileId: string): Promise<ApiResumeWorkspace | null> {
  try {
    return await apiRequest<ApiResumeWorkspace>(resumeWorkspacePath(profileId));
  } catch (error) {
    if (error instanceof ApiHttpError && error.status === 404) return null;
    throw error;
  }
}

export async function startResumeWorkspace(
  profileId: string,
  input: {
    conversationLanguage: "ar" | "en";
    language: "ar" | "en";
    contact?: { email?: string; phone?: string; linkedin?: string };
    dataSharingAcknowledged: boolean;
  },
) {
  return apiRequest<ApiResumeWorkspace>(resumeWorkspacePath(profileId), {
    method: "POST",
    body: JSON.stringify({
      conversation_language: input.conversationLanguage,
      language: input.language,
      contact: {
        email: input.contact?.email?.trim() || null,
        phone: input.contact?.phone?.trim() || null,
        linkedin: input.contact?.linkedin?.trim() || null,
      },
      data_sharing_acknowledged: input.dataSharingAcknowledged,
    }),
  });
}

export async function resetResumeWorkspace(
  profileId: string,
  expectedRevision: number,
) {
  const query = new URLSearchParams({ expected_revision: String(expectedRevision) });
  await apiResponse(`${resumeWorkspacePath(profileId)}?${query.toString()}`, {
    method: "DELETE",
  });
}

export async function importResumeWorkspaceFile(
  profileId: string,
  file: File,
  input: { dataSharingAcknowledged: boolean },
) {
  const body = new FormData();
  body.set("file", file);
  body.set("data_sharing_acknowledged", String(input.dataSharingAcknowledged));
  return apiRequest<ApiImportResult>(resumeWorkspacePath(profileId, "/import"), {
    method: "POST",
    body,
    timeoutMs: 90_000,
  });
}

export async function sendResumeWorkspaceMessage(
  profileId: string,
  input: {
    content: string;
    clientTurnId: string;
    expectedRevision: number;
    quickAction?:
      | "additions_yes"
      | "additions_no"
      | "skip"
      | "continue"
      | "generate"
      | "improve"
      | "review"
      | "show_example"
      | "no_exact_metric";
  },
) {
  return apiRequest<ApiResumeWorkspace>(resumeWorkspacePath(profileId, "/messages"), {
    method: "POST",
    body: JSON.stringify({
      content: input.content,
      client_turn_id: input.clientTurnId,
      expected_revision: input.expectedRevision,
      quick_action: input.quickAction || null,
    }),
    // Import generation can include a translation, an independent semantic verification, and
    // the grounded draft. Keep the browser deadline beyond the server's bounded worst case so a
    // completed draft is not mistaken for a failed request.
    timeoutMs: 190_000,
  });
}

export async function prepareResumeImportFlow(
  profileId: string,
  input: {
    sourceId: string;
    clientRequestId: string;
    expectedRevision: number;
    expectedEvidenceRevision: number;
  },
) {
  return apiRequest<ApiResumeWorkspace>(resumeWorkspacePath(profileId, "/import/prepare"), {
    method: "POST",
    body: JSON.stringify({
      source_id: input.sourceId,
      client_request_id: input.clientRequestId,
      expected_revision: input.expectedRevision,
      expected_evidence_revision: input.expectedEvidenceRevision,
    }),
  });
}

export async function confirmResumeUnderstanding(
  profileId: string,
  understandingId: string,
  expectedRevision: number,
) {
  return apiRequest<ApiResumeWorkspace>(
    resumeWorkspacePath(profileId, `/understandings/${encodeURIComponent(understandingId)}/confirm`),
    {
      method: "POST",
      body: JSON.stringify({ expected_revision: expectedRevision }),
      timeoutMs: 120_000,
    },
  );
}

export async function correctResumeUnderstanding(
  profileId: string,
  understandingId: string,
  input: { expectedRevision: number; correctedText: string },
) {
  return apiRequest<ApiResumeWorkspace>(
    resumeWorkspacePath(profileId, `/understandings/${encodeURIComponent(understandingId)}/correct`),
    {
      method: "POST",
      body: JSON.stringify({
        expected_revision: input.expectedRevision,
        corrected_text: input.correctedText.trim(),
      }),
      timeoutMs: 120_000,
    },
  );
}

export async function patchResumeWorkspaceDraft(
  profileId: string,
  input: {
    draft: ApiResumeDraftContent;
    expectedDraftRevision: number;
  },
) {
  return apiRequest<ApiResumeWorkspace>(resumeWorkspacePath(profileId, "/draft"), {
    method: "PATCH",
    body: JSON.stringify({
      draft: input.draft,
      expected_draft_revision: input.expectedDraftRevision,
    }),
    timeoutMs: 60_000,
  });
}

export type ResumeRewriteMode = "stronger" | "shorter" | "professional" | "custom";

export async function rewriteResumeDraftSelection(
  profileId: string,
  input: {
    targetKind: "headline" | "professional_summary" | "bullet";
    sectionKey?: string;
    itemId?: string;
    bulletIndex?: number;
    mode: ResumeRewriteMode;
    instruction?: string;
    expectedDraftRevision: number;
  },
) {
  return apiRequest<ApiResumeRewriteSuggestion>(resumeWorkspacePath(profileId, "/draft/rewrite"), {
    method: "POST",
    body: JSON.stringify({
      target_kind: input.targetKind,
      section_key: input.sectionKey || null,
      item_id: input.itemId || null,
      bullet_index: input.bulletIndex ?? null,
      mode: input.mode,
      instruction: input.instruction?.trim() || null,
      expected_draft_revision: input.expectedDraftRevision,
    }),
    timeoutMs: 120_000,
  });
}

export async function decideResumeRewriteSuggestion(
  profileId: string,
  suggestionId: string,
  decision: "accept" | "reject",
  expectedDraftRevision: number,
) {
  return apiRequest<ApiResumeWorkspace>(
    resumeWorkspacePath(profileId, `/draft/suggestions/${encodeURIComponent(suggestionId)}/${decision}`),
    {
      method: "POST",
      body: JSON.stringify({ expected_draft_revision: expectedDraftRevision }),
      timeoutMs: 60_000,
    },
  );
}

export async function getResumeDraftVersions(profileId: string) {
  return apiRequest<ApiResumeDraftVersion[]>(resumeWorkspacePath(profileId, "/versions"));
}

export async function restoreResumeDraftVersion(
  profileId: string,
  versionId: string,
  expectedDraftRevision: number,
) {
  return apiRequest<ApiResumeWorkspace>(
    resumeWorkspacePath(profileId, `/versions/${encodeURIComponent(versionId)}/restore`),
    {
      method: "POST",
      body: JSON.stringify({ expected_draft_revision: expectedDraftRevision }),
    },
  );
}

export async function reviewResumeWorkspace(
  profileId: string,
  expectedDraftRevision: number,
) {
  return apiRequest<ApiResumeReview>(resumeWorkspacePath(profileId, "/review"), {
    method: "POST",
    body: JSON.stringify({
      expected_draft_revision: expectedDraftRevision,
      review_acknowledged: true,
    }),
    timeoutMs: 60_000,
  });
}

export async function previewResumeWorkspacePdf(profileId: string) {
  const response = await apiResponse(resumeWorkspacePath(profileId, "/preview.pdf"), {
    timeoutMs: 90_000,
  });
  return response.blob();
}

export async function exportResumeWorkspacePdf(profileId: string, expectedDraftRevision: number) {
  const response = await apiResponse(resumeWorkspacePath(profileId, "/export.pdf"), {
    method: "POST",
    body: JSON.stringify({
      expected_draft_revision: expectedDraftRevision,
      review_acknowledged: true,
    }),
    timeoutMs: 90_000,
  });
  return response.blob();
}

export async function confirmCareerFact(profileId: string, factId: string) {
  return apiRequest<ApiCareerFact>(`/v1/profiles/${encodeURIComponent(profileId)}/facts/${encodeURIComponent(factId)}/confirm`, { method: "POST" });
}

export async function confirmCareerFactsBatch(
  profileId: string,
  input: {
    sourceId: string;
    clientRequestId: string;
    factIds: string[];
    rejectedFactIds?: string[];
    expectedEvidenceRevision: number;
  },
) {
  return apiRequest<ApiCareerFactBatchConfirmResult>(
    `/v1/profiles/${encodeURIComponent(profileId)}/facts/confirm-batch`,
    {
      method: "POST",
      body: JSON.stringify({
        source_id: input.sourceId,
        client_request_id: input.clientRequestId,
        fact_ids: input.factIds,
        rejected_fact_ids: input.rejectedFactIds ?? [],
        expected_evidence_revision: input.expectedEvidenceRevision,
      }),
    },
  );
}

export async function updateCareerFact(profileId: string, factId: string, input: { category: string; label: string; detail: string; correctionReason: string }) {
  return apiRequest<ApiCareerFact>(`/v1/profiles/${encodeURIComponent(profileId)}/facts/${encodeURIComponent(factId)}`, {
    method: "PATCH",
    body: JSON.stringify({ category: input.category, label: input.label, detail: input.detail, correction_reason: input.correctionReason }),
  });
}

export async function unconfirmCareerFact(profileId: string, factId: string) {
  return apiRequest<ApiCareerFact>(`/v1/profiles/${encodeURIComponent(profileId)}/facts/${encodeURIComponent(factId)}/unconfirm`, { method: "POST" });
}

export async function exportMyData() {
  const response = await apiResponse("/v1/me/export");
  return response.blob();
}

export async function deleteMyData() {
  return apiRequest<{ id: string; completed_at: string; deleted_counts: Record<string, number> }>("/v1/me/data", { method: "DELETE" });
}

export const apiConfiguration = {
  baseUrl: API_BASE_URL,
  mode: API_BASE_URL ? "connected-api" : "demo-only",
} as const;
