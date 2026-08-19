"use client";

import {
  ChangeEvent,
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AlertCircle,
  ArrowLeft,
  Bookmark,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleUserRound,
  Download,
  FileDown,
  FileText,
  Info,
  Lightbulb,
  LoaderCircle,
  Mail,
  MessageCircle,
  Paperclip,
  Pencil,
  PencilLine,
  RotateCcw,
  ScanSearch,
  Send,
  Sparkles,
  Target,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ResumeCanvasSelection } from "@/lib/resume-presentation";
import { ResumeProofingPaper } from "@/components/resume/resume-proofing-paper";
import {
  ProofingEvidenceRail,
  ProofingVersionRail,
} from "@/components/resume/resume-proofing-rails";
import {
  apiErrorMessage,
  ApiHttpError,
  confirmCareerFactsBatch,
  confirmResumeUnderstanding,
  correctResumeUnderstanding,
  decideResumeRewriteSuggestion,
  exportResumeWorkspacePdf,
  getCareerFacts,
  getResumeDraftVersions,
  getResumeWorkspace,
  importResumeWorkspaceFile,
  patchResumeWorkspaceDraft,
  prepareResumeImportFlow,
  previewResumeWorkspacePdf,
  resetResumeWorkspace,
  restoreResumeDraftVersion,
  reviewResumeWorkspace,
  rewriteResumeDraftSelection,
  sendResumeWorkspaceMessage,
  startResumeWorkspace,
  type ApiCareerFact,
  type ApiCareerProfile,
  type ApiResumeDraftContent,
  type ApiResumeDraftVersion,
  type ApiResumeMessage,
  type ApiResumeWorkspace,
  type ResumeRewriteMode,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";

type SaveState = "saved" | "saving" | "error";
type MobilePanel = "conversation" | "resume";
type QueuedDraftSave = {
  draft: ApiResumeDraftContent;
  generation: number;
  operationEpoch: number;
  // Marks a payload restored after a failed request: it waits for an explicit
  // retry (or a newer edit) instead of re-flushing in a loop, and it does not
  // count as "actively pending" persistence.
  failed?: boolean;
};
type ResumeQuickAction =
  | "additions_yes"
  | "additions_no"
  | "skip"
  | "continue"
  | "generate"
  | "improve"
  | "review"
  | "show_example"
  | "no_exact_metric";

type ResumeWorkspaceV2Props = {
  locale: "ar" | "en";
  profile: ApiCareerProfile;
  initialFacts: ApiCareerFact[];
  initialWorkspace: ApiResumeWorkspace | null;
};

type RecentImportState = {
  sourceId: string;
  fileName: string;
  analysisStatus: "created" | "ai_upgraded" | "already_ai_analyzed";
  confirmedCount: number;
  extractedCount: number;
  rejectedCount: number;
};

type PendingImportSnapshot = {
  recentImport: RecentImportState;
  pendingFacts: ApiCareerFact[];
};

function pendingImportSnapshot(
  workspace: ApiResumeWorkspace | null | undefined,
  facts: ApiCareerFact[],
  fallbackFileName?: string,
): PendingImportSnapshot | null {
  const metadata = workspace?.provider_metadata;
  const sourceId = typeof metadata?.pending_import_source_id === "string"
    ? metadata.pending_import_source_id
    : null;
  const fileName = typeof metadata?.pending_import_filename === "string"
    ? metadata.pending_import_filename
    : fallbackFileName;
  if (!sourceId || !fileName) return null;
  const sourceFacts = facts.filter((fact) => fact.source_id === sourceId);
  const rawStatus = metadata?.pending_import_analysis_status;
  const analysisStatus = rawStatus === "ai_upgraded" || rawStatus === "already_ai_analyzed"
    ? rawStatus
    : "created";
  return {
    recentImport: {
      sourceId,
      fileName,
      analysisStatus,
      confirmedCount: sourceFacts.filter((fact) => fact.verification_status === "confirmed").length,
      extractedCount: sourceFacts.filter((fact) => fact.verification_status === "extracted").length,
      rejectedCount: sourceFacts.filter((fact) => fact.verification_status === "unconfirmed").length,
    },
    pendingFacts: sourceFacts.filter((fact) => fact.verification_status === "extracted"),
  };
}

type ResumeImportFlowPhase =
  | "ats_assessment"
  | "additions_choice"
  | "additions_interview"
  | "gap_interview"
  | "ready_to_generate"
  | "draft_review";

type ResumeAssessmentGap = {
  key: string;
  category: string;
  record_label?: string;
  label_ar?: string;
  label_en?: string;
  reason_ar?: string;
  reason_en?: string;
  requested_fields?: string[];
  priority?: "required" | "high" | "medium" | "low" | "recommended" | "optional";
};

type ResumeImportAssessment = {
  disclaimer?: string;
  verdict?: string;
  found_sections?: string[];
  missing_sections?: string[];
  section_counts?: Record<string, number>;
  gaps?: ResumeAssessmentGap[];
  ats_checks?: Array<{
    key: string;
    status: "pass" | "warning" | "not_assessed";
    label_ar?: string;
    label_en?: string;
    detail?: string;
  }>;
  page_target?: number;
};

type ResumeImportFlow = {
  phase: ResumeImportFlowPhase;
  source_id: string;
  file_name?: string;
  assessment?: ResumeImportAssessment;
  gap_queue?: ResumeAssessmentGap[];
  active_gap_key?: string | null;
  completed_gap_keys?: string[];
  skipped_gap_keys?: string[];
  can_generate?: boolean;
  page_target?: number;
};

const MAX_FILE_BYTES = 10_000_000;

const importCategoryOrder = [
  "education",
  "experience",
  "certification",
  "skill",
  "language",
  "project",
  "achievement",
];

const atsAssessmentCategories = [
  "education",
  "experience",
  "certification",
  "skill",
  "language",
  "project",
  "achievement",
] as const;

function importFlowFromWorkspace(workspace: ApiResumeWorkspace | null): ResumeImportFlow | null {
  const candidate = workspace?.provider_metadata?.import_flow;
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  const value = candidate as Record<string, unknown>;
  if (typeof value.phase !== "string" || typeof value.source_id !== "string") return null;
  const allowedPhases = new Set<ResumeImportFlowPhase>([
    "ats_assessment",
    "additions_choice",
    "additions_interview",
    "gap_interview",
    "ready_to_generate",
    "draft_review",
  ]);
  if (!allowedPhases.has(value.phase as ResumeImportFlowPhase)) return null;
  return value as ResumeImportFlow;
}

function preliminaryAssessment(facts: ApiCareerFact[]): ResumeImportAssessment {
  const activeFacts = facts.filter((fact) => fact.verification_status !== "unconfirmed");
  const sectionCounts = Object.fromEntries(
    atsAssessmentCategories.map((category) => [
      category,
      activeFacts.filter((fact) => fact.category === category).length,
    ]),
  );
  const foundSections = atsAssessmentCategories.filter((category) => sectionCounts[category] > 0);
  const missingSections: Array<(typeof atsAssessmentCategories)[number]> = [];
  if (sectionCounts.education === 0) missingSections.push("education");
  if (sectionCounts.experience === 0 && sectionCounts.project === 0) missingSections.push("experience");
  if (sectionCounts.skill === 0) missingSections.push("skill");
  if (sectionCounts.language === 0) missingSections.push("language");
  const gaps: ResumeAssessmentGap[] = missingSections.map((category) => ({
    key: `missing_${category}`,
    category,
    priority: category === "education" || category === "experience" || category === "skill" || category === "language"
      ? "high"
      : "recommended",
  }));
  return {
    verdict: foundSections.length >= 5 ? "strong_structure" : foundSections.length >= 3 ? "good_start" : "needs_completion",
    found_sections: [...foundSections],
    missing_sections: [...missingSections],
    section_counts: sectionCounts,
    gaps,
    page_target: 1,
  };
}

function assessmentCategoryLabel(category: string, locale: "ar" | "en") {
  return coverageCopy[category]?.[locale] ?? category;
}

const coverageCopy: Record<string, { ar: string; en: string }> = {
  identity: { ar: "الهوية", en: "Identity" },
  experience: { ar: "الخبرة", en: "Experience" },
  trading_experience: { ar: "خبرة التداول", en: "Trading experience" },
  education: { ar: "التعليم", en: "Education" },
  skill: { ar: "المهارات", en: "Skills" },
  project: { ar: "المشاريع", en: "Projects" },
  certification: { ar: "الشهادات", en: "Certifications" },
  language: { ar: "اللغات", en: "Languages" },
  achievement: { ar: "الإنجازات", en: "Achievements" },
};

const structuredReviewLabels: Record<string, { ar: string; en: string }> = {
  degree: { ar: "الدرجة العلمية", en: "Degree" },
  institution: { ar: "الجامعة أو الجهة التعليمية", en: "Institution" },
  organization: { ar: "الجهة", en: "Organization" },
  issuer: { ar: "الجهة المانحة", en: "Issuer" },
  date_range: { ar: "الفترة", en: "Date range" },
  location: { ar: "الموقع", en: "Location" },
  proficiency: { ar: "المستوى", en: "Proficiency" },
  level: { ar: "المستوى", en: "Level" },
  gpa_score: { ar: "المعدل", en: "GPA" },
  gpa_scale: { ar: "مقياس المعدل", en: "GPA scale" },
  responsibilities: { ar: "المسؤوليات والإنجازات", en: "Responsibilities and achievements" },
  outcomes: { ar: "النتائج", en: "Outcomes" },
  tools: { ar: "الأدوات", en: "Tools" },
  coursework: { ar: "المقررات ذات الصلة", en: "Relevant coursework" },
};

const hiddenStructuredReviewKeys = new Set([
  "record_type",
  "record_version",
  "schema_version",
  "source_handles",
  "source_section",
  "title",
  "profile_field",
  "gpa_display_recommended",
]);

function structuredReviewRows(fact: ApiCareerFact, locale: "ar" | "en") {
  return Object.entries(fact.structured_value ?? {}).flatMap(([key, value]) => {
    if (hiddenStructuredReviewKeys.has(key) || value == null) return [];
    const rawValues = Array.isArray(value) ? value : [value];
    const values = rawValues.flatMap((item) => {
      if (typeof item === "string") return item.trim() ? [item.trim()] : [];
      if (typeof item === "number") return [String(item)];
      if (typeof item === "boolean") {
        return [item ? (locale === "ar" ? "نعم" : "Yes") : (locale === "ar" ? "لا" : "No")];
      }
      if (typeof item === "object" && item) return [JSON.stringify(item)];
      return [];
    });
    if (!values.length) return [];
    const fallbackLabel = key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
    return [{
      key,
      label: structuredReviewLabels[key]?.[locale] ?? fallbackLabel,
      values: [...new Set(values)],
    }];
  });
}

const structuredDetailNoiseWords = new Set([
  "achievement",
  "achievements",
  "course",
  "courses",
  "coursework",
  "date",
  "degree",
  "gpa",
  "graduation",
  "institution",
  "issuer",
  "level",
  "location",
  "organization",
  "proficiency",
  "relevant",
  "responsibilities",
  "responsibility",
]);

function reviewMaterialWords(value: string) {
  return (value.normalize("NFKC").toLocaleLowerCase("en").match(/[\p{L}\p{N}]+/gu) ?? [])
    .filter((word) => !structuredDetailNoiseWords.has(word));
}

function structuredRowsCoverDetail(
  detail: string,
  rows: ReturnType<typeof structuredReviewRows>,
) {
  if (!rows.length) return false;
  const detailWords = reviewMaterialWords(detail);
  if (!detailWords.length) return false;
  const representedWords = new Set(reviewMaterialWords(rows.flatMap((row) => row.values).join(" ")));
  return detailWords.every((word) => representedWords.has(word));
}

function freshTurnId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `resume-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function supportsResume(file: File) {
  const lower = file.name.toLocaleLowerCase("en");
  return lower.endsWith(".pdf") || lower.endsWith(".docx");
}

function latestUnderstandingId(workspace: ApiResumeWorkspace) {
  // Never fall back to a message id: the understanding API only accepts
  // understanding ids and 404s on anything else. Callers skip the call on null.
  return workspace.pending_understanding?.id ?? null;
}

function latestSuggestionId(workspace: ApiResumeWorkspace) {
  // Never fall back to a message id: the suggestion API only accepts
  // suggestion ids and 404s on anything else. Callers skip the call on null.
  return workspace.pending_suggestion?.suggestion_id ?? null;
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  return url;
}

function resumeExportContentKey(profile: ApiCareerProfile, workspace: ApiResumeWorkspace | null) {
  return JSON.stringify([
    profile.full_name,
    profile.city,
    workspace?.current_draft ?? null,
    workspace?.contact ?? null,
  ]);
}

function jsonValuesEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left)
      && Array.isArray(right)
      && left.length === right.length
      && left.every((value, index) => jsonValuesEqual(value, right[index]));
  }
  if (
    left === null
    || right === null
    || typeof left !== "object"
    || typeof right !== "object"
  ) return false;

  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const leftKeys = Object.keys(leftRecord).sort();
  const rightKeys = Object.keys(rightRecord).sort();
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key, index) => (
      key === rightKeys[index]
      && jsonValuesEqual(leftRecord[key], rightRecord[key])
    ));
}

function workspaceHasCurrentServerReview(workspace: ApiResumeWorkspace | null) {
  if (!workspace?.current_draft) return false;
  return workspace.versions.some((version) => (
    version.status === "export_ready"
    && Boolean(version.reviewed_at)
    && Boolean(version.review_hash)
    && version.evidence_revision === workspace.evidence_revision
    && jsonValuesEqual(version.content, workspace.current_draft)
  ));
}

function AssistantBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 border-b border-border/70 pb-4">
      <span className="mt-1 grid h-8 w-8 shrink-0 place-items-center border border-primary text-primary-text" aria-hidden="true"><PencilLine className="h-4 w-4" /></span>
      <div className="max-w-[90%] text-sm leading-7 text-foreground">{children}</div>
    </div>
  );
}

function workspaceConversationLanguage(workspace: ApiResumeWorkspace) {
  return workspace.conversation_language ?? workspace.language;
}

function MessageBubble({ message, locale }: { message: ApiResumeMessage; locale: "ar" | "en" }) {
  const isUser = message.role === "user";
  const question = message.kind === "question" && message.structured_payload.question
    && typeof message.structured_payload.question === "object"
    && !Array.isArray(message.structured_payload.question)
    ? message.structured_payload.question as Record<string, unknown>
    : null;
  const whyItMatters = typeof question?.why_it_matters === "string" ? question.why_it_matters : null;
  return (
    <div className={cn("flex items-start gap-3 border-b border-border/70 pb-4", isUser ? "flex-row-reverse" : "flex-row")}>
      <span className={cn("mt-1 grid h-8 w-8 shrink-0 place-items-center border", isUser ? "border-muted text-muted" : "border-primary text-primary-text")} aria-hidden="true">
        {isUser ? <CircleUserRound className="h-5 w-5" /> : <PencilLine className="h-4.5 w-4.5" />}
      </span>
      <div className={cn(
        "max-w-[86%] whitespace-pre-wrap text-sm leading-7 text-foreground",
        isUser && "text-end",
      )} dir="auto">
        {message.content}
        {whyItMatters ? (
          <span className="mt-2 block border-s-2 border-primary ps-3 text-xs leading-5 text-muted">
            <strong className="text-foreground">{locale === "ar" ? "لماذا أسأل؟ " : "Why I’m asking: "}</strong>{whyItMatters}
          </span>
        ) : null}
        <span className="mt-1 block text-[10px] leading-none text-muted" dir="auto">
          {new Intl.DateTimeFormat(locale === "ar" ? "ar-SA" : "en", { hour: "2-digit", minute: "2-digit" }).format(new Date(message.created_at))}
        </span>
      </div>
    </div>
  );
}

function ResumeWriterBusyStatus({ locale }: { locale: "ar" | "en" }) {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const workingTimer = window.setTimeout(() => setPhase(1), 2_500);
    const delayedTimer = window.setTimeout(() => setPhase(2), 7_000);
    return () => {
      window.clearTimeout(workingTimer);
      window.clearTimeout(delayedTimer);
    };
  }, []);

  const copy = locale === "ar"
    ? [
      "تم إرسال إجابتك. كاتب السيرة يقرأها الآن…",
      "كاتب السيرة يحوّل إجابتك إلى معلومات مهنية…",
      "استغرق الطلب وقتًا أطول من المعتاد، لكن إجابتك ما زالت ظاهرة هنا…",
    ]
    : [
      "Your answer was sent. The resume writer is reading it now…",
      "The resume writer is turning your answer into professional evidence…",
      "This is taking longer than usual, but your answer is still visible here…",
    ];

  return (
    <div className="flex items-center gap-2 ps-10 text-xs text-muted" role="status">
      <LoaderCircle className="h-4 w-4 animate-spin text-primary-text" />
      {copy[phase]}
    </div>
  );
}

function ReadinessBar({ score, locale }: { score: number; locale: "ar" | "en" }) {
  return (
    <div className="flex items-center gap-3 text-sm" aria-label={locale === "ar" ? `اكتمال المعلومات ${score}%` : `Information completeness ${score}%`}>
      <strong className="whitespace-nowrap text-foreground">{locale === "ar" ? "اكتمال المعلومات" : "Information completeness"} <span className="text-emerald">{score}%</span></strong>
      <span className="h-2 w-24 overflow-hidden rounded-full bg-white/10 sm:w-36"><span className="block h-full rounded-full bg-emerald transition-[width] duration-500" style={{ width: `${score}%` }} /></span>
    </div>
  );
}

function StageRail({ current, locale }: { current: number; locale: "ar" | "en" }) {
  const stages = [
    { ar: "الملف", en: "Resume" },
    { ar: "التقييم", en: "Assess" },
    { ar: "الإكمال", en: "Complete" },
    { ar: "المسودة", en: "Draft" },
  ];
  return (
    <ol className="flex items-center justify-center gap-2 sm:gap-4" aria-label={locale === "ar" ? "مراحل بناء السيرة" : "Resume-building stages"}>
      {stages.map((stage, index) => {
        const number = index + 1;
        const active = number === current;
        const complete = number < current;
        return (
          <li className="contents" key={stage.en}>
            {index ? <span className={cn("h-px w-7 sm:w-14", complete ? "bg-emerald" : active ? "bg-primary" : "bg-border")} aria-hidden="true" /> : null}
            <div className={cn("flex items-center gap-2 whitespace-nowrap text-xs sm:text-sm", active ? "font-bold text-foreground" : complete ? "text-foreground" : "text-muted")}>
              <span className={cn("grid h-7 w-7 place-items-center rounded-full border text-xs font-bold", complete ? "border-emerald bg-emerald text-white" : active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface text-muted")}>
                {complete ? <Check className="h-4 w-4" /> : number}
              </span>
              <span className="hidden sm:inline">{locale === "ar" ? stage.ar : stage.en}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function SetupConversation({
  locale,
  conversationLanguage,
  outputLanguage,
  consentAccepted,
  starting,
  error,
  onConversationLanguage,
  onOutputLanguage,
  onConsent,
  onStart,
}: {
  locale: "ar" | "en";
  conversationLanguage: "ar" | "en";
  outputLanguage: "ar" | "en";
  consentAccepted: boolean;
  starting: boolean;
  error: unknown;
  onConversationLanguage: (language: "ar" | "en") => void;
  onOutputLanguage: (language: "ar" | "en") => void;
  onConsent: (accepted: boolean) => void;
  onStart: () => void;
}) {
  const choiceClass = (selected: boolean) => cn(
    "min-h-11 border px-3 text-sm font-semibold transition-colors",
    selected
      ? "border-primary bg-primary text-primary-foreground"
      : "border-border bg-surface text-foreground hover:border-primary hover:text-primary-text",
  );

  return (
    <div className="flex h-full min-h-[560px] flex-col overflow-hidden border-y border-border">
      <header className="border-b border-border px-5 py-4">
        <div className="flex items-center gap-2 text-primary-text"><PencilLine className="h-4 w-4" aria-hidden="true" /><h2 className="font-bold text-foreground">{locale === "ar" ? "المساعد الذكي" : "AI assistant"}</h2></div>
        <p className="mt-1 text-xs text-muted">{locale === "ar" ? "اختر لغة الحديث ولغة المستند كلًا على حدة" : "Choose the conversation and document languages separately"}</p>
      </header>
      <div className="flex-1 space-y-5 overflow-y-auto p-5">
        <AssistantBubble>
          <p>{locale === "ar" ? "تكلّم معي بالعربي وسأكتب سيرتك بالإنجليزي، أو غيّر أي لغة كما يناسبك." : "Talk to me in Arabic while I write your resume in English, or change either language."}</p>
          <div className="mt-5 space-y-5">
            <fieldset>
              <legend className="mb-2 text-xs font-bold text-foreground">{locale === "ar" ? "لغة الحوار مع المساعد" : "Conversation language"}</legend>
              <div className="grid grid-cols-2 gap-2">
                <button type="button" className={choiceClass(conversationLanguage === "ar")} aria-label={locale === "ar" ? "لغة الحوار: العربية" : "Conversation language: Arabic"} aria-pressed={conversationLanguage === "ar"} onClick={() => onConversationLanguage("ar")}>العربية</button>
                <button type="button" className={choiceClass(conversationLanguage === "en")} aria-label={locale === "ar" ? "لغة الحوار: الإنجليزية" : "Conversation language: English"} aria-pressed={conversationLanguage === "en"} onClick={() => onConversationLanguage("en")}>English</button>
              </div>
            </fieldset>
            <fieldset>
              <legend className="mb-2 text-xs font-bold text-foreground">{locale === "ar" ? "لغة السيرة النهائية" : "Final resume language"}</legend>
              <div className="grid grid-cols-2 gap-2">
                <button type="button" className={choiceClass(outputLanguage === "ar")} aria-label={locale === "ar" ? "لغة السيرة: العربية" : "Resume language: Arabic"} aria-pressed={outputLanguage === "ar"} onClick={() => onOutputLanguage("ar")}>العربية</button>
                <button type="button" className={choiceClass(outputLanguage === "en")} aria-label={locale === "ar" ? "لغة السيرة: الإنجليزية" : "Resume language: English"} aria-pressed={outputLanguage === "en"} onClick={() => onOutputLanguage("en")}>English</button>
              </div>
            </fieldset>
          </div>
        </AssistantBubble>
        <label className="flex cursor-pointer items-start gap-3 border-s-2 border-primary py-3 ps-4 text-xs leading-6 text-muted">
          <input type="checkbox" className="mt-1 h-5 w-5 shrink-0 accent-primary" checked={consentAccepted} onChange={(event) => onConsent(event.target.checked)} />
          <span><strong className="block text-sm text-foreground">{locale === "ar" ? "موافقة استخدام الذكاء الاصطناعي" : "AI-use acknowledgement"}</strong>{locale === "ar" ? "أوافق على إرسال إجاباتي المهنية والنص المستخرج بعد تنقيح بيانات التواصل. يُحفظ هذا الاختيار ولن نطلبه في كل سؤال." : "I agree to share my professional answers and redacted extracted text. This choice is saved and will not be requested for every question."}</span>
        </label>
        {error ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{apiErrorMessage(error, locale)}</p> : null}
      </div>
      <div className="border-t border-border p-4">
        <Button className="w-full" size="lg" disabled={!consentAccepted || starting} onClick={onStart}>
          {starting ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <MessageCircle className="h-5 w-5" />}
          {starting ? (locale === "ar" ? "جارٍ تجهيز المساحة…" : "Preparing workspace…") : (locale === "ar" ? "ابدأ المحادثة" : "Start conversation")}
        </Button>
      </div>
    </div>
  );
}

function ResetWorkspaceDialog({
  locale,
  resetting,
  error,
  onCancel,
  onConfirm,
}: {
  locale: "ar" | "en";
  resetting: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);
  const resettingRef = useRef(resetting);

  useEffect(() => {
    onCancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    resettingRef.current = resetting;
  }, [resetting]);

  useEffect(() => {
    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const background = overlayRef.current?.previousElementSibling instanceof HTMLElement
      ? overlayRef.current.previousElementSibling
      : null;
    const previousBodyOverflow = document.body.style.overflow;
    const previousAriaHidden = background?.getAttribute("aria-hidden") ?? null;
    const previousInert = background?.inert ?? false;

    document.body.style.overflow = "hidden";
    if (background) {
      background.inert = true;
      background.setAttribute("aria-hidden", "true");
    }
    cancelRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !resettingRef.current) {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const panel = panelRef.current;
      if (!panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hasAttribute("hidden"));
      if (!focusable.length) {
        event.preventDefault();
        panel.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !panel.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      if (background) {
        background.inert = previousInert;
        if (previousAriaHidden === null) background.removeAttribute("aria-hidden");
        else background.setAttribute("aria-hidden", previousAriaHidden);
      }
      if (previousFocusRef.current?.isConnected) previousFocusRef.current.focus();
    };
  }, []);

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-[70] flex items-center justify-center bg-background/85 px-4 py-8 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !resetting) onCancel();
      }}
    >
      <section
        ref={panelRef}
        tabIndex={-1}
        className="w-full max-w-lg border-y border-danger bg-surface px-5 py-6 shadow-panel sm:px-7"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="reset-resume-title"
        aria-describedby="reset-resume-description"
      >
        <div className="flex items-start gap-4">
          <span className="grid h-11 w-11 shrink-0 place-items-center border border-danger text-danger" aria-hidden="true"><Trash2 className="h-5 w-5" /></span>
          <div>
            <h2 id="reset-resume-title" className="text-lg font-bold text-foreground">
              {locale === "ar" ? "مسح مساحة السيرة والبدء من جديد؟" : "Clear this resume workspace and start over?"}
            </h2>
            <p id="reset-resume-description" className="mt-2 text-sm leading-7 text-muted">
              {locale === "ar"
                ? "سيتم حذف المحادثة والمسودة الحالية وكل الإصدارات السابقة وبيانات الاتصال المحفوظة للسيرة نهائيًا. ستبقى الحقائق المهنية المؤكدة في ملفك المهني."
                : "This permanently deletes the conversation, current draft, all prior versions, and resume contact details. Confirmed career facts remain in your career profile."}
            </p>
          </div>
        </div>
        {error ? <p className="mt-5 border-y border-danger bg-danger-pale px-3 py-3 text-sm text-danger" role="alert">{error}</p> : null}
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button ref={cancelRef} variant="secondary" disabled={resetting} onClick={onCancel}>
            {locale === "ar" ? "إلغاء" : "Cancel"}
          </Button>
          <Button variant="danger" disabled={resetting} onClick={onConfirm}>
            {resetting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            {resetting ? (locale === "ar" ? "جارٍ المسح…" : "Clearing…") : (locale === "ar" ? "امسح وابدأ من جديد" : "Clear and start over")}
          </Button>
        </div>
      </section>
    </div>
  );
}

function ConsentRenewalPanel({
  locale,
  accepted,
  renewing,
  error,
  onAcceptedChange,
  onRenew,
}: {
  locale: "ar" | "en";
  accepted: boolean;
  renewing: boolean;
  error: unknown;
  onAcceptedChange: (accepted: boolean) => void;
  onRenew: () => void;
}) {
  return (
    <section className="flex h-full min-h-[560px] flex-col overflow-hidden border-y border-border" aria-labelledby="resume-consent-renewal-title">
      <header className="border-b border-border px-5 py-4">
        <h2 id="resume-consent-renewal-title" className="font-bold text-foreground">
          {locale === "ar" ? "جدّد موافقتك للمتابعة" : "Renew your consent to continue"}
        </h2>
        <p className="mt-1 text-xs leading-5 text-muted">
          {locale === "ar"
            ? "تغيّرت شروط معالجة البيانات بالذكاء الاصطناعي، لذلك أوقفنا المحادثة والتحليل حتى توافق صراحةً على النسخة الحالية."
            : "The AI data-processing terms changed, so conversation and analysis are paused until you explicitly accept the current version."}
        </p>
      </header>
      <div className="flex-1 space-y-5 p-5">
        <div className="border-y border-border border-s-2 border-s-primary bg-background px-4 py-4 text-sm leading-7 text-muted">
          <Info className="me-2 inline h-4 w-4 text-primary-text" aria-hidden="true" />
          {locale === "ar"
            ? "لن نرسل بيانات التواصل إلى مزود الذكاء الاصطناعي. لا يبدأ أي طلب جديد قبل تجديد هذه الموافقة."
            : "Contact details are not sent to the AI provider. No new request starts before you renew this consent."}
        </div>
        <label className="flex cursor-pointer items-start gap-3 border-s-2 border-primary py-3 ps-4 text-xs leading-6 text-muted">
          <input
            type="checkbox"
            className="mt-1 h-5 w-5 shrink-0 accent-primary"
            checked={accepted}
            onChange={(event) => onAcceptedChange(event.target.checked)}
          />
          <span>
            <strong className="block text-sm text-foreground">
              {locale === "ar" ? "أوافق على النسخة الحالية" : "I accept the current version"}
            </strong>
            {locale === "ar"
              ? "أوافق على معالجة إجاباتي المهنية والنص المستخرج بعد تنقيح بيانات التواصل."
              : "I agree to process my professional answers and redacted extracted text."}
          </span>
        </label>
        {error ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{apiErrorMessage(error, locale)}</p> : null}
      </div>
      <div className="border-t border-border p-4">
        <Button className="w-full" size="lg" disabled={!accepted || renewing} onClick={onRenew}>
          {renewing ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <CheckCircle2 className="h-5 w-5" />}
          {renewing
            ? (locale === "ar" ? "جارٍ تجديد الموافقة…" : "Renewing consent…")
            : (locale === "ar" ? "جدّد الموافقة وتابع" : "Renew consent and continue")}
        </Button>
      </div>
    </section>
  );
}

function UnderstandingCard({
  workspace,
  locale,
  busy,
  correcting,
  correction,
  onCorrectionChange,
  onConfirm,
  onStartCorrection,
  onCancelCorrection,
  onCorrect,
}: {
  workspace: ApiResumeWorkspace;
  locale: "ar" | "en";
  busy: boolean;
  correcting: boolean;
  correction: string;
  onCorrectionChange: (value: string) => void;
  onConfirm: () => void;
  onStartCorrection: () => void;
  onCancelCorrection: () => void;
  onCorrect: () => void;
}) {
  const understanding = workspace.pending_understanding;
  if (!understanding) return null;
  return (
    <section className="ms-12 border-y border-border border-s-2 border-s-primary bg-background p-4" aria-labelledby="resume-understanding-title">
      <div className="flex items-center gap-2 text-primary-text">
        <PencilLine className="h-4 w-4" aria-hidden="true" />
        <h3 id="resume-understanding-title" className="text-sm font-bold">{locale === "ar" ? "فهمت منك" : "What I understood"}</h3>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-foreground" dir="auto">{understanding.understanding}</p>
      <p className="mt-2 text-xs text-muted" dir="auto">{understanding.understanding_detail?.confirmation_question ?? (locale === "ar" ? "هل فهمت كلامك بشكل صحيح؟" : "Did I understand you correctly?")}</p>
      {correcting ? (
        <div className="mt-4">
          <label className="sr-only" htmlFor="resume-understanding-correction">{locale === "ar" ? "صحح ما فهمه المساعد" : "Correct the assistant's understanding"}</label>
          <textarea id="resume-understanding-correction" className="field-control min-h-24 resize-y" dir="auto" value={correction} onChange={(event) => onCorrectionChange(event.target.value)} autoFocus />
          <div className="mt-3 flex gap-2">
            <Button className="flex-1" disabled={!correction.trim() || busy} onClick={onCorrect}>{locale === "ar" ? "احفظ التصحيح" : "Save correction"}</Button>
            <Button variant="secondary" disabled={busy} onClick={onCancelCorrection}>{locale === "ar" ? "إلغاء" : "Cancel"}</Button>
          </div>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Button disabled={busy} onClick={onConfirm}><Check className="h-4 w-4" />{locale === "ar" ? "صحيح" : "Correct"}</Button>
          <Button variant="secondary" disabled={busy} onClick={onStartCorrection}><Pencil className="h-4 w-4" />{locale === "ar" ? "عدّل" : "Edit"}</Button>
        </div>
      )}
    </section>
  );
}

function CoverageStrip({ workspace, locale }: { workspace: ApiResumeWorkspace; locale: "ar" | "en" }) {
  const entries = Object.entries(workspace.section_coverage).slice(0, 4);
  if (!entries.length) return null;
  return (
    <div className="grid grid-cols-2 divide-x rtl:divide-x-reverse divide-border border-y border-border py-2 text-[10px] sm:grid-cols-4">
      {entries.map(([key, complete]) => (
        <div className="flex items-center justify-center gap-1.5 px-2" key={key}>
          {complete ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald" /> : <span className="h-3.5 w-3.5 shrink-0 rounded-full bg-amber" />}
          <span className="truncate">{coverageCopy[key]?.[locale] ?? key} {complete ? (locale === "ar" ? "مكتمل" : "complete") : (locale === "ar" ? "يحتاج تفصيل" : "needs detail")}</span>
        </div>
      ))}
    </div>
  );
}

function ContactPopover({
  locale,
  contact,
  disabled,
  onChange,
  onClose,
}: {
  locale: "ar" | "en";
  contact: ApiResumeWorkspace["contact"];
  disabled: boolean;
  onChange: (contact: ApiResumeWorkspace["contact"]) => void;
  onClose: () => void;
}) {
  return (
    <section className="absolute inset-x-4 top-[62px] z-20 border border-border bg-surface p-4 shadow-panel" aria-label={locale === "ar" ? "بيانات التواصل" : "Contact details"}>
      <div className="flex items-start justify-between gap-4">
        <div><h3 className="font-bold text-foreground">{locale === "ar" ? "بيانات التواصل في PDF" : "Contact details in the PDF"}</h3><p className="mt-1 text-xs text-muted">{locale === "ar" ? "لا تُرسل هذه الحقول إلى مزود الذكاء الاصطناعي." : "These fields are never sent to the AI provider."}</p></div>
        <button type="button" className="grid h-9 w-9 place-items-center border border-border hover:border-primary hover:text-primary-text" aria-label={locale === "ar" ? "إغلاق" : "Close"} onClick={onClose}><X className="h-4 w-4" /></button>
      </div>
      <div className="mt-4 grid gap-3">
        <input className="field-control" type="email" aria-label={locale === "ar" ? "البريد الإلكتروني" : "Email"} placeholder={locale === "ar" ? "البريد الإلكتروني" : "Email"} value={contact.email ?? ""} disabled={disabled} onChange={(event) => onChange({ ...contact, email: event.target.value })} />
        <input className="field-control" type="tel" aria-label={locale === "ar" ? "رقم الهاتف" : "Phone"} placeholder={locale === "ar" ? "رقم الهاتف" : "Phone"} value={contact.phone ?? ""} disabled={disabled} onChange={(event) => onChange({ ...contact, phone: event.target.value })} />
        <input className="field-control" type="url" aria-label="LinkedIn" placeholder="LinkedIn" value={contact.linkedin ?? ""} disabled={disabled} onChange={(event) => onChange({ ...contact, linkedin: event.target.value })} />
      </div>
    </section>
  );
}

function ImportConsentCard({
  locale,
  fileName,
  importing,
  onConfirm,
  onCancel,
}: {
  locale: "ar" | "en";
  fileName: string;
  importing: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <section className="ms-10 border-s-2 border-primary py-2 ps-4" aria-labelledby="resume-import-consent-title">
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center border border-primary text-primary-text" aria-hidden="true"><FileText className="h-4 w-4" /></span>
        <div className="min-w-0">
          <h3 id="resume-import-consent-title" className="font-bold text-ink">
            {locale === "ar" ? "حلّل هذا الملف بالذكاء الاصطناعي؟" : "Analyze this file with AI?"}
          </h3>
          <p className="mt-1 truncate text-xs font-semibold text-primary-text" dir="auto">{fileName}</p>
          <p className="mt-2 text-xs leading-6 text-muted">
            {locale === "ar"
              ? "عند المتابعة سيُرسل النص المهني المستخرج بعد تنقيح بيانات التواصل. ستراجع كل معلومة قبل اعتمادها."
              : "Continuing sends redacted professional text for analysis. You will review every extracted fact before it is confirmed."}
          </p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <Button disabled={importing} onClick={onConfirm}>
          {importing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <PencilLine className="h-4 w-4" />}
          {importing
            ? (locale === "ar" ? "جارٍ التحليل…" : "Analyzing…")
            : (locale === "ar" ? "حلّل الملف" : "Analyze file")}
        </Button>
        <Button variant="secondary" disabled={importing} onClick={onCancel}>
          {locale === "ar" ? "إلغاء" : "Cancel"}
        </Button>
      </div>
    </section>
  );
}

function AtsAssessmentCard({
  locale,
  result,
  assessment,
  continuing,
  onContinue,
}: {
  locale: "ar" | "en";
  result: RecentImportState;
  assessment: ResumeImportAssessment;
  continuing: boolean;
  onContinue: () => void;
}) {
  const reused = result.analysisStatus === "already_ai_analyzed";
  const found = assessment.found_sections ?? [];
  const missing = assessment.missing_sections ?? [];
  const counts = assessment.section_counts ?? {};
  const assessedChecks = (assessment.ats_checks ?? []).filter((check) => check.status !== "not_assessed");
  const passedChecks = assessedChecks.filter((check) => check.status === "pass").length;
  const noUsableFacts = result.confirmedCount === 0 && result.extractedCount === 0;
  return (
    <section className="ms-2 border border-border bg-surface/35 p-4 sm:ms-10" aria-labelledby="resume-ats-assessment-title">
      <div className="flex items-start justify-between gap-4 border-b border-border pb-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center border border-primary text-primary-text"><ScanSearch className="h-5 w-5" aria-hidden="true" /></span>
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-primary-text">{locale === "ar" ? "الخطوة 02 · التقييم" : "STEP 02 · ASSESS"}</p>
            <h3 id="resume-ats-assessment-title" className="mt-1 font-bold text-foreground">{locale === "ar" ? "تقييم مبدئي لجاهزية ATS" : "Initial ATS readiness assessment"}</h3>
            <p className="mt-1 truncate text-xs text-muted">{result.fileName}</p>
          </div>
        </div>
        <span className="shrink-0 border border-emerald/50 px-2 py-1 text-[10px] font-bold text-emerald">{reused ? (locale === "ar" ? "تحليل مستعاد" : "RESTORED") : (locale === "ar" ? "تم التحليل" : "ANALYZED")}</span>
      </div>
      <p className="mt-4 border-s-2 border-amber ps-3 text-xs leading-6 text-muted">
        {locale === "ar"
          ? "هذا تقييم لاكتمال بنية السيرة، وليس احتمال قبول وظيفي. أنظمة ATS تختلف حسب الجهة والوصف الوظيفي."
          : "This assesses resume structure, not your probability of being hired. ATS rules vary by employer and job description."}
      </p>
      <div className="mt-4 grid gap-px bg-border sm:grid-cols-2">
        <div className="bg-background p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-emerald">{locale === "ar" ? "موجود في الملف" : "FOUND"}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {found.length ? found.map((category) => (
              <span className="inline-flex items-center gap-1.5 text-xs text-foreground" key={category}><Check className="h-3.5 w-3.5 text-emerald" />{assessmentCategoryLabel(category, locale)}{counts[category] ? ` · ${counts[category]}` : ""}</span>
            )) : <span className="text-xs text-muted">{locale === "ar" ? "لم نجد قسمًا مكتملًا بعد" : "No complete section found yet"}</span>}
          </div>
        </div>
        <div className="bg-background p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-amber">{locale === "ar" ? "سنراجع أو نسأل عنه" : "TO REVIEW"}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {missing.length ? missing.map((category) => (
              <span className="inline-flex items-center gap-1.5 text-xs text-foreground" key={category}><span className="h-2 w-2 bg-amber" />{assessmentCategoryLabel(category, locale)}</span>
            )) : <span className="inline-flex items-center gap-1.5 text-xs text-emerald"><CheckCircle2 className="h-3.5 w-3.5" />{locale === "ar" ? "الأقسام الأساسية موجودة" : "Core sections are present"}</span>}
          </div>
        </div>
      </div>
      {assessedChecks.length ? (
        <div className="mt-4 flex items-center justify-between gap-3 border border-border/70 px-3 py-2 text-xs">
          <span className="font-bold text-foreground">{locale === "ar" ? "فحوصات ATS البنيوية" : "ATS structural checks"}</span>
          <span className="text-muted">
            {locale === "ar"
              ? `نجح ${passedChecks} من ${assessedChecks.length}`
              : `${passedChecks} of ${assessedChecks.length} passed`}
          </span>
        </div>
      ) : null}
      <div className="mt-4 flex items-center justify-between gap-3 border-y border-border py-3 text-xs">
        <span className="inline-flex items-center gap-2 text-foreground"><FileText className="h-4 w-4 text-primary-text" />{locale === "ar" ? "الهدف: صفحة واحدة بتخطيط أحادي العمود" : "Target: one-page, single-column layout"}</span>
        <span className="text-muted">{locale === "ar" ? `${result.extractedCount} للمراجعة` : `${result.extractedCount} to review`}</span>
      </div>
      {result.extractedCount > 0 ? (
        <p className="mt-4 flex items-center justify-center gap-2 border border-primary/35 px-3 py-3 text-xs font-semibold text-primary-text">
          <ArrowLeft className="h-4 w-4 -rotate-90" aria-hidden="true" />
          {locale === "ar" ? "راجع المعلومات المستخرجة أدناه، ثم اعتمد التحليل." : "Review the extracted facts below, then confirm the assessment."}
        </p>
      ) : (
        <>
          {noUsableFacts ? (
            <p className="mt-4 border-s-2 border-amber ps-3 text-xs leading-6 text-muted">
              {locale === "ar"
                ? "لم نستخرج معلومات قابلة للاستخدام من هذا الملف. يمكنك المتابعة إلى المقابلة الموجهة وسنبني سيرتك من إجاباتك سؤالًا بسؤال."
                : "We could not extract usable facts from this file. Continue to the guided interview and we will build your resume from your answers, one question at a time."}
            </p>
          ) : null}
          <Button className="mt-4 w-full" disabled={continuing} onClick={onContinue}>
            {continuing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" />}
            {continuing
              ? (locale === "ar" ? "جارٍ تجهيز الخطوة التالية…" : "Preparing next step…")
              : noUsableFacts
                ? (locale === "ar" ? "تابع إلى المقابلة الموجهة" : "Continue to the guided interview")
                : (locale === "ar" ? "اعتماد التحليل والمتابعة" : "Confirm assessment and continue")}
          </Button>
        </>
      )}
    </section>
  );
}

function AdditionsChoiceCard({
  locale,
  flow,
  busy,
  onAnswer,
}: {
  locale: "ar" | "en";
  flow: ResumeImportFlow;
  busy: boolean;
  onAnswer: (hasAdditions: boolean) => void;
}) {
  const gapCount = flow.gap_queue?.length ?? flow.assessment?.gaps?.length ?? 0;
  const gaps = flow.assessment?.gaps?.slice(0, 4) ?? [];
  const passedChecks = flow.assessment?.ats_checks?.filter((check) => check.status === "pass").length ?? 0;
  const assessedChecks = flow.assessment?.ats_checks?.filter((check) => check.status !== "not_assessed").length ?? 0;
  return (
    <section className="ms-2 border-s-2 border-primary py-2 ps-4 sm:ms-10" aria-labelledby="resume-additions-title">
      <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-primary-text">{locale === "ar" ? "الخطوة 03 · الإكمال" : "STEP 03 · COMPLETE"}</p>
      <h3 id="resume-additions-title" className="mt-1 text-base font-bold text-foreground">{locale === "ar" ? "هل عندك معلومات غير موجودة في الملف؟" : "Is there anything missing from the uploaded resume?"}</h3>
      <p className="mt-2 text-xs leading-6 text-muted">
        {locale === "ar"
          ? `لن نكتب المسودة الآن. أولًا نضيف ما فات، ثم يسألك الذكاء الاصطناعي عن ${gapCount ? `${gapCount} نقاط` : "النقاط المهمة"} واحدةً واحدة.`
          : `We will not write the draft yet. First add anything missing, then the AI will ask about ${gapCount || "the"} important gaps one at a time.`}
      </p>
      <div className="mt-4 grid gap-px bg-border sm:grid-cols-[0.72fr_1.28fr]">
        <div className="bg-background p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-emerald">{locale === "ar" ? "فحوصات بنيوية" : "STRUCTURAL CHECKS"}</p>
          <p className="mt-2 text-xl font-bold text-foreground">{passedChecks}<span className="text-sm font-normal text-muted"> / {assessedChecks || "—"}</span></p>
          <p className="mt-1 text-[11px] leading-5 text-muted">{locale === "ar" ? "نجحت وفق المعلومات المؤكدة فقط" : "Passed using confirmed information only"}</p>
        </div>
        <div className="bg-background p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-amber">{locale === "ar" ? "أولوية المقابلة" : "INTERVIEW PRIORITIES"}</p>
          <ul className="mt-2 space-y-2">
            {gaps.length ? gaps.map((gap) => (
              <li className="flex items-center justify-between gap-3 text-xs" key={gap.key}>
                <span className="text-foreground" dir="auto">{gap.record_label || assessmentCategoryLabel(gap.category, locale)}</span>
                <span className={cn("text-[10px] font-bold", gap.priority === "high" ? "text-danger" : "text-amber")}>
                  {gap.priority === "high" ? (locale === "ar" ? "مهم" : "HIGH") : (locale === "ar" ? "تحسين" : "IMPROVE")}
                </span>
              </li>
            )) : <li className="text-xs text-emerald">{locale === "ar" ? "لا توجد فجوات أساسية" : "No core gaps found"}</li>}
          </ul>
        </div>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <Button disabled={busy} onClick={() => onAnswer(true)}><Sparkles className="h-4 w-4" />{locale === "ar" ? "نعم، أضيفها" : "Yes, I want to add details"}</Button>
        <Button variant="secondary" disabled={busy} onClick={() => onAnswer(false)}><Target className="h-4 w-4" />{locale === "ar" ? "لا، اسألني عن النواقص" : "No, ask me about the gaps"}</Button>
      </div>
    </section>
  );
}

function ExtractedFactsReview({
  locale,
  facts,
  selectedFactIds,
  busySourceId,
  allowEmptySelectionSourceId,
  sourceNames,
  onToggle,
  onToggleSource,
  onBuild,
}: {
  locale: "ar" | "en";
  facts?: ApiCareerFact[];
  selectedFactIds: string[];
  busySourceId: string | null;
  allowEmptySelectionSourceId: string | null;
  sourceNames: Record<string, string>;
  onToggle: (factId: string, selected: boolean) => void;
  onToggleSource: (sourceId: string, selected: boolean) => void;
  onBuild: (sourceId: string) => void;
}) {
  if (!facts?.length) return null;
  const selected = new Set(selectedFactIds);
  const sourceIds = Array.from(new Set(facts.map((fact) => fact.source_id)));
  return (
    <section className="ms-10 border-s-2 border-primary py-2 ps-4" aria-labelledby="resume-import-facts-title">
      <div className="flex items-start gap-2">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber" aria-hidden="true" />
        <div>
          <h3 id="resume-import-facts-title" className="font-bold text-ink">
            {locale === "ar" ? "راجع المعلومات المستخرجة" : "Review extracted facts"}
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted">
            {locale === "ar"
              ? "حدد المعلومات الصحيحة فقط. سنعتمد المحدد ونستبعد غير المحدد، ثم نكمل النواقص قبل أن يكتب الذكاء الاصطناعي السيرة."
              : "Select only accurate facts. We will confirm those, reject the rest, and complete the gaps before the AI writes the resume."}
          </p>
        </div>
      </div>
      <div className="mt-4 space-y-6">
        {sourceIds.map((sourceId) => {
          const sourceFacts = facts
            .filter((fact) => fact.source_id === sourceId)
            .sort((left, right) => {
              const categoryDifference = importCategoryOrder.indexOf(left.category) - importCategoryOrder.indexOf(right.category);
              return categoryDifference || left.created_at.localeCompare(right.created_at);
            });
          const selectedCount = sourceFacts.filter((fact) => selected.has(fact.id)).length;
          const allSelected = selectedCount === sourceFacts.length;
          const building = busySourceId === sourceId;
          return (
            <div className="border border-border bg-surface/40 p-3" key={sourceId}>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
                <div>
                  <p className="text-xs font-bold text-foreground">{sourceNames[sourceId] ?? (locale === "ar" ? "ملف سيرة مستورد" : "Imported resume")}</p>
                  <p className="mt-1 text-[11px] text-muted">{locale === "ar" ? `${selectedCount} من ${sourceFacts.length} محددة` : `${selectedCount} of ${sourceFacts.length} selected`}</p>
                </div>
                <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-xs font-semibold text-primary-text">
                  <input type="checkbox" checked={allSelected} disabled={Boolean(busySourceId)} onChange={(event) => onToggleSource(sourceId, event.target.checked)} />
                  {locale === "ar" ? "تحديد الكل" : "Select all"}
                </label>
              </div>
              <div className="divide-y divide-border">
                {Array.from(new Set(sourceFacts.map((fact) => fact.category))).map((categoryKey) => (
                  <section className="py-4" key={categoryKey}>
                    <h4 className="text-xs font-bold uppercase tracking-wide text-primary-text">
                      {coverageCopy[categoryKey]?.[locale] ?? categoryKey}
                    </h4>
                    <div className="mt-2 divide-y divide-border/70">
                      {sourceFacts.filter((fact) => fact.category === categoryKey).map((fact) => {
                        const structuredRows = structuredReviewRows(fact, locale);
                        return (
                          <article className="py-3" key={fact.id}>
                            <label className="flex cursor-pointer items-start gap-3">
                              <input className="mt-1" type="checkbox" checked={selected.has(fact.id)} disabled={Boolean(busySourceId)} onChange={(event) => onToggle(fact.id, event.target.checked)} />
                              <span className="min-w-0 flex-1 text-sm font-bold text-foreground">{fact.label}</span>
                            </label>
                            {fact.detail && !structuredRowsCoverDetail(fact.detail, structuredRows) ? (
                              <p className="mt-2 whitespace-pre-wrap ps-7 text-xs leading-6 text-muted">{fact.detail}</p>
                            ) : null}
                            {structuredRows.length ? (
                              <dl className="ms-7 mt-3 space-y-2 border-s border-primary/40 ps-3 text-xs">
                                {structuredRows.map((row) => (
                                  <div key={row.key}>
                                    <dt className="font-bold text-foreground">{row.label}</dt>
                                    <dd className="mt-1 text-muted">
                                      {row.values.length === 1 ? row.values[0] : (
                                        <ul className="list-disc space-y-1 ps-5">
                                          {row.values.map((value) => <li key={value}>{value}</li>)}
                                        </ul>
                                      )}
                                    </dd>
                                  </div>
                                ))}
                              </dl>
                            ) : null}
                            {fact.source_excerpt ? (
                              <p className="ms-7 mt-2 border-s border-border ps-2 text-[11px] leading-5 text-muted">
                                {locale === "ar" ? "من الملف: " : "From the file: "}{fact.source_excerpt}
                              </p>
                            ) : null}
                          </article>
                        );
                      })}
                    </div>
                  </section>
                ))}
              </div>
              <Button className="mt-3 w-full" disabled={(!selectedCount && allowEmptySelectionSourceId !== sourceId) || Boolean(busySourceId)} onClick={() => onBuild(sourceId)}>
                {building ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                {building
                  ? (locale === "ar" ? "جارٍ اعتماد التحليل…" : "Confirming assessment…")
                  : (locale === "ar" ? "اعتماد التحليل والمتابعة" : "Confirm assessment and continue")}
              </Button>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ConversationPanel({
  locale,
  conversationLanguage,
  workspace,
  message,
  optimisticMessage,
  error,
  busy,
  interactionLocked,
  importing,
  correcting,
  correction,
  recentImport,
  pendingImportFileName,
  profileFacts,
  importedFacts,
  selectedImportFactIds,
  busyImportSourceId,
  importSourceNames,
  showContact,
  onShowContact,
  onContactChange,
  onMessageChange,
  onSend,
  onQuickAction,
  onFile,
  onConfirmImport,
  onCancelImport,
  onToggleImportFact,
  onToggleImportSource,
  onBuildImportDraft,
  onConfirm,
  onStartCorrection,
  onCancelCorrection,
  onCorrectionChange,
  onCorrect,
}: {
  locale: "ar" | "en";
  conversationLanguage: "ar" | "en";
  workspace: ApiResumeWorkspace;
  message: string;
  optimisticMessage: ApiResumeMessage | null;
  error: unknown;
  busy: boolean;
  interactionLocked: boolean;
  importing: boolean;
  correcting: boolean;
  correction: string;
  recentImport: RecentImportState | null;
  pendingImportFileName: string | null;
  profileFacts: ApiCareerFact[];
  importedFacts: ApiCareerFact[];
  selectedImportFactIds: string[];
  busyImportSourceId: string | null;
  importSourceNames: Record<string, string>;
  showContact: boolean;
  onShowContact: (show: boolean) => void;
  onContactChange: (contact: ApiResumeWorkspace["contact"]) => void;
  onMessageChange: (message: string) => void;
  onSend: (event: FormEvent<HTMLFormElement>) => void;
  onQuickAction: (content: string, action?: ResumeQuickAction) => void;
  onFile: (event: ChangeEvent<HTMLInputElement>) => void;
  onConfirmImport: () => void;
  onCancelImport: () => void;
  onToggleImportFact: (factId: string, selected: boolean) => void;
  onToggleImportSource: (sourceId: string, selected: boolean) => void;
  onBuildImportDraft: (sourceId: string, includeSelectedFacts: boolean) => void;
  onConfirm: () => void;
  onStartCorrection: () => void;
  onCancelCorrection: () => void;
  onCorrectionChange: (value: string) => void;
  onCorrect: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const conversationEndRef = useRef<HTMLDivElement>(null);
  const importFlow = importFlowFromWorkspace(workspace);
  // Prefer the server's real assessment (gaps, ats_checks, section_counts) when the
  // prepared import flow covers this upload; the local fact-count heuristic is only
  // a fallback for imports the server has not assessed yet.
  const serverAssessment = importFlow && recentImport && importFlow.source_id === recentImport.sourceId
    ? importFlow.assessment ?? null
    : null;
  const assessment = recentImport
    ? serverAssessment
      ?? preliminaryAssessment(profileFacts.filter((fact) => fact.source_id === recentImport.sourceId))
    : null;
  const canGenerate = !importFlow || importFlow.can_generate === true || importFlow.phase === "ready_to_generate";
  const processedGapKeys = new Set([
    ...(importFlow?.completed_gap_keys ?? []),
    ...(importFlow?.skipped_gap_keys ?? []),
  ]);
  const remainingGaps = importFlow?.gap_queue?.length ?? 0;
  const hasActiveGap = Boolean(importFlow?.active_gap_key);
  const totalGaps = Math.max(
    importFlow?.assessment?.gaps?.length ?? 0,
    processedGapKeys.size + remainingGaps + (hasActiveGap ? 1 : 0),
  );
  const activeGapNumber = hasActiveGap ? processedGapKeys.size + 1 : 0;
  const currentQuestion = workspace.provider_metadata?.current_question;
  const currentQuestionPlaceholder = currentQuestion && typeof currentQuestion === "object" && !Array.isArray(currentQuestion)
    && typeof (currentQuestion as Record<string, unknown>).placeholder === "string"
    ? String((currentQuestion as Record<string, unknown>).placeholder)
    : null;
  const importFlowStartIndex = workspace.messages.reduce((latestIndex, entry, index) => (
    entry.structured_payload?.import_flow_phase === "additions_choice" ? index : latestIndex
  ), -1);
  const importFlowMessages = importFlowStartIndex >= 0
    ? workspace.messages.slice(importFlowStartIndex)
    : workspace.messages;
  const displayedMessages = importFlow
    ? (importFlow.phase === "additions_choice" ? [] : importFlowMessages)
    : workspace.messages;
  const controlsLocked = busy || interactionLocked;
  const importReviewLocked = Boolean(
    importing
    || pendingImportFileName
    || recentImport
    || (!workspace.current_draft && importedFacts.length)
    || busyImportSourceId,
  );
  const conversationControlsLocked = controlsLocked
    || importReviewLocked
    || Boolean(workspace.pending_understanding);
  const attachmentLocked = conversationControlsLocked
    || Boolean(importFlow)
    || Boolean(workspace.current_draft);
  // Contact autosave makes saveState="saving" while the user is still typing; do not
  // let that state disable its own input. Lock only for external/flow operations.
  const contactLocked = busy
    || importReviewLocked
    || Boolean(importFlow)
    || Boolean(workspace.pending_understanding);
  const questionHelpersVisible = !importFlow
    || importFlow.phase === "additions_interview"
    || importFlow.phase === "gap_interview";

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [busy, optimisticMessage?.id, workspace.messages.length]);

  return (
    <section className="relative flex min-h-0 flex-col overflow-hidden border-y border-border xl:border-y-0" aria-label={locale === "ar" ? "محادثة بناء السيرة" : "Resume-building conversation"}>
      <header className="flex min-h-[62px] items-center justify-between gap-3 border-b border-border px-5">
        <div><div className="flex items-center gap-2 text-primary-text"><Pencil className="h-4 w-4" /><h2 className="font-bold">{locale === "ar" ? "ملاحظات المحرر" : "Editor notes"}</h2></div><p className="text-[11px] text-muted">{workspace.provider_ready ? (locale === "ar" ? "الذكاء الاصطناعي جاهز" : "AI is ready") : (locale === "ar" ? "الذكاء الاصطناعي غير جاهز" : "AI unavailable")}</p></div>
        <button type="button" className={cn("inline-flex min-h-10 items-center gap-2 border px-3 text-xs font-semibold", showContact ? "border-primary text-primary-text" : "border-border text-foreground hover:border-primary hover:text-primary-text")} aria-expanded={showContact} disabled={contactLocked} onClick={() => onShowContact(!showContact)}><Mail className="h-4 w-4" />{locale === "ar" ? "التواصل" : "Contact"}</button>
      </header>
      {showContact ? <ContactPopover locale={locale} contact={workspace.contact} disabled={contactLocked} onChange={onContactChange} onClose={() => onShowContact(false)} /> : null}

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-5" role="log">
        {!workspace.messages.length ? (
          <AssistantBubble>
            <p dir={conversationLanguage === "ar" ? "rtl" : "ltr"}>{conversationLanguage === "ar" ? "جميل، خلّنا نبني سيرتك من قصتك الحقيقية. أرفق سيرة موجودة هنا، أو اكتب نبذة قصيرة عن آخر تجربة دراسية أو مهنية لك." : "Great—let's build your resume from your real story. Attach an existing resume here, or tell me briefly about your latest study or work experience."}</p>
          </AssistantBubble>
        ) : null}
        {recentImport && assessment && !workspace.current_draft ? (
          <AtsAssessmentCard
            locale={locale}
            result={recentImport}
            assessment={assessment}
            continuing={controlsLocked || busyImportSourceId === recentImport.sourceId}
            onContinue={() => onBuildImportDraft(recentImport.sourceId, true)}
          />
        ) : null}
        {pendingImportFileName ? (
          <ImportConsentCard
            locale={locale}
            fileName={pendingImportFileName}
            importing={importing}
            onConfirm={onConfirmImport}
            onCancel={onCancelImport}
          />
        ) : null}
        <ExtractedFactsReview
          locale={locale}
          facts={workspace.current_draft ? [] : importedFacts}
          selectedFactIds={selectedImportFactIds}
          busySourceId={controlsLocked ? "workspace-locked" : busyImportSourceId}
          allowEmptySelectionSourceId={recentImport?.confirmedCount ? recentImport.sourceId : null}
          sourceNames={importSourceNames}
          onToggle={onToggleImportFact}
          onToggleSource={onToggleImportSource}
          onBuild={(sourceId) => onBuildImportDraft(sourceId, true)}
        />
        {importFlow?.phase === "additions_choice" ? (
          <AdditionsChoiceCard
            locale={locale}
            flow={importFlow}
            busy={controlsLocked}
            onAnswer={(hasAdditions) => onQuickAction(
              hasAdditions
                ? (conversationLanguage === "ar" ? "عندي معلومات إضافية غير موجودة في الملف." : "I have additional information that is not in the file.")
                : (conversationLanguage === "ar" ? "ما عندي إضافات الآن؛ اسألني عن أهم النواقص." : "I have no additions right now; ask me about the most important gaps."),
              hasAdditions ? "additions_yes" : "additions_no",
            )}
          />
        ) : null}
        {importFlow?.phase === "additions_interview" || importFlow?.phase === "gap_interview" ? (
          <div className="ms-10 flex items-center justify-between gap-3 border-y border-border py-2 text-[11px]">
            <span className="font-bold text-primary-text">
              {importFlow.phase === "additions_interview"
                ? (locale === "ar" ? "إضافة معلومة جديدة" : "Adding new information")
                : (locale === "ar" ? `سؤال النقص ${activeGapNumber} من ${totalGaps}` : `Gap question ${activeGapNumber} of ${totalGaps}`)}
            </span>
            <span className="text-muted">{locale === "ar" ? "سؤال واحد في كل مرة" : "One question at a time"}</span>
          </div>
        ) : null}
        {displayedMessages
          .filter((item) => item.status !== "failed" && !(
            item.kind === "understanding" && item.status === "pending"
          ))
          .map((item) => <MessageBubble key={item.id} message={item} locale={locale} />)}
        {optimisticMessage ? <MessageBubble message={optimisticMessage} locale={locale} /> : null}
        <UnderstandingCard
          workspace={workspace}
          locale={locale}
          busy={controlsLocked}
          correcting={correcting}
          correction={correction}
          onCorrectionChange={onCorrectionChange}
          onConfirm={onConfirm}
          onStartCorrection={onStartCorrection}
          onCancelCorrection={onCancelCorrection}
          onCorrect={onCorrect}
        />
        {busy ? <ResumeWriterBusyStatus locale={locale} /> : null}
        {error ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert"><AlertCircle className="me-2 inline h-4 w-4" />{apiErrorMessage(error, locale)}</p> : null}
        <div ref={conversationEndRef} aria-hidden="true" />
      </div>

      {importFlow?.phase === "additions_choice" ? (
        <footer className="border-t border-border px-4 py-3 text-center text-xs text-muted">
          {locale === "ar" ? "اختر أحد الخيارين أعلاه لنبدأ المقابلة الذكية." : "Choose one option above to start the focused interview."}
        </footer>
      ) : <footer className="space-y-3 border-t border-border p-3 sm:p-4">
        <div className="grid grid-cols-2 divide-x rtl:divide-x-reverse divide-border border-y border-border sm:grid-cols-4">
          {canGenerate ? (
            <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 px-2 text-[11px] font-semibold text-primary-text hover:bg-primary hover:text-primary-foreground" disabled={conversationControlsLocked || Boolean(workspace.pending_understanding)} onClick={() => onQuickAction(conversationLanguage === "ar" ? "اكتب سيرتي الجديدة بصياغة احترافية متوافقة مع ATS، اعتمادًا على المعلومات التي أكّدتها فقط، واستهدف صفحة واحدة من دون حذف إنجاز مهم." : "Write my new ATS-friendly resume using only my confirmed information, targeting one page without dropping important achievements.", "generate")}><PencilLine className="h-4 w-4" />{importFlow ? (locale === "ar" ? "أنشئ مسودة ATS" : "Create ATS draft") : (locale === "ar" ? "اكتب السيرة الآن" : "Write resume now")}</button>
          ) : null}
          {questionHelpersVisible ? (
            <>
              <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 px-2 text-[11px] font-semibold text-foreground hover:text-primary-text" disabled={conversationControlsLocked} onClick={() => onQuickAction(conversationLanguage === "ar" ? "أعطني مثالًا" : "Give me an example", "show_example")}><Lightbulb className="h-4 w-4" />{locale === "ar" ? "أعطني مثالًا" : "Give an example"}</button>
              <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 border-t border-border px-2 text-[11px] font-semibold text-foreground hover:text-primary-text sm:border-t-0" disabled={conversationControlsLocked} onClick={() => onQuickAction(conversationLanguage === "ar" ? "ما عندي رقم دقيق" : "I do not have an exact metric", "no_exact_metric")}><Info className="h-4 w-4" />{locale === "ar" ? "ما عندي رقم دقيق" : "No exact metric"}</button>
              <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 border-t border-border px-2 text-[11px] font-semibold text-foreground hover:text-primary-text sm:border-t-0" disabled={conversationControlsLocked} onClick={() => onQuickAction(conversationLanguage === "ar" ? "تخطَّ هذا السؤال" : "Skip this question", "skip")}><ChevronDown className="h-4 w-4" />{locale === "ar" ? "تخطَّ هذا السؤال" : "Skip this question"}</button>
            </>
          ) : null}
        </div>
        {importFlow ? null : <CoverageStrip workspace={workspace} locale={locale} />}
        <form className="grid grid-cols-[1fr_auto] border border-border" onSubmit={onSend}>
          <label className="sr-only" htmlFor="resume-workspace-message">{locale === "ar" ? "اكتب رسالتك" : "Write your message"}</label>
          <textarea id="resume-workspace-message" className="min-h-[58px] resize-none bg-transparent px-3 py-3 text-sm text-foreground placeholder:text-muted" dir="auto" placeholder={currentQuestionPlaceholder ?? (locale === "ar" ? "اكتب رسالتك هنا…" : "Write your message…")} value={message} disabled={conversationControlsLocked || Boolean(workspace.pending_understanding)} onChange={(event) => onMessageChange(event.target.value)} />
          <button type="submit" className="grid h-[58px] w-[58px] place-items-center self-start border-s border-border text-primary-text transition hover:bg-primary hover:text-primary-foreground disabled:cursor-not-allowed disabled:opacity-45" disabled={!message.trim() || conversationControlsLocked || Boolean(workspace.pending_understanding)} aria-label={locale === "ar" ? "إرسال الرسالة" : "Send message"}>{busy ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5 rtl:-scale-x-100" />}</button>
          <input ref={fileInputRef} className="sr-only" id="resume-workspace-file" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={attachmentLocked} onChange={onFile} />
          <button type="button" className="col-span-2 inline-flex min-h-10 w-fit items-center gap-2 text-xs font-semibold text-muted hover:text-primary-text disabled:opacity-50" disabled={attachmentLocked} onClick={() => fileInputRef.current?.click()}>
            {importing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
            {importing
              ? (locale === "ar" ? "جارٍ تحليل الملف…" : "Analyzing file…")
              : workspace.current_draft
                ? (locale === "ar" ? "امسح المسودة أولًا لرفع ملف آخر" : "Clear the draft before uploading another file")
                : (locale === "ar" ? "إرفاق سيرة موجودة" : "Attach an existing resume")}
          </button>
        </form>
      </footer>}
    </section>
  );
}

function ReviewPanel({
  locale,
  workspace,
  selection,
  busy,
  rewriting,
  showContact,
  contactDisabled,
  onShowContact,
  onContactChange,
  onRewrite,
  onDecision,
}: {
  locale: "ar" | "en";
  workspace: ApiResumeWorkspace;
  selection: ResumeCanvasSelection | null;
  busy: boolean;
  rewriting: boolean;
  showContact: boolean;
  contactDisabled: boolean;
  onShowContact: (show: boolean) => void;
  onContactChange: (contact: ApiResumeWorkspace["contact"]) => void;
  onRewrite: (selection: ResumeCanvasSelection, mode: ResumeRewriteMode, instruction?: string) => void;
  onDecision: (decision: "accept" | "reject") => void;
}) {
  const [instruction, setInstruction] = useState("");
  const suggestion = workspace.pending_suggestion;

  function submitInstruction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selection || !instruction.trim()) return;
    onRewrite(selection, "custom", instruction);
    setInstruction("");
  }

  return (
    <section className="relative flex min-h-0 flex-col overflow-hidden border-y border-border xl:border-y-0" aria-label={locale === "ar" ? "مراجعة السيرة" : "Resume review"}>
      <header className="flex min-h-[62px] items-center justify-between gap-3 border-b border-border px-4 xl:px-5">
        <div>
          <div className="flex items-center gap-2 text-primary-text">
            <Pencil className="h-4 w-4" aria-hidden="true" />
            <h2 className="text-sm font-bold">{locale === "ar" ? "ملاحظات التحرير الذكي" : "Editorial notes"}</h2>
          </div>
          <p className="mt-1 text-[11px] text-muted">{locale === "ar" ? "ملاحظات مبنية في الهامش مرتبطة بالنص" : "Margin notes connected to the text"}</p>
        </div>
        <button type="button" className={cn("inline-flex min-h-10 shrink-0 items-center gap-2 border px-3 text-xs font-semibold", showContact ? "border-primary text-primary-text" : "border-border text-foreground hover:border-primary hover:text-primary-text")} aria-expanded={showContact} disabled={contactDisabled} onClick={() => onShowContact(!showContact)}><Mail className="h-4 w-4" />{locale === "ar" ? "التواصل" : "Contact"}</button>
      </header>
      {showContact ? <ContactPopover locale={locale} contact={workspace.contact} disabled={contactDisabled} onChange={onContactChange} onClose={() => onShowContact(false)} /> : null}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 xl:px-5">
        {suggestion ? (
          <section className="relative border-s-2 border-primary ps-5" aria-labelledby="resume-suggestion-title">
            <span className="absolute -start-8 top-0 text-lg font-bold text-primary-text" aria-hidden="true">03</span>
            <h3 id="resume-suggestion-title" className="text-sm font-bold leading-6 text-primary-text">{locale === "ar" ? "اقتراح تحرير بالذكاء الاصطناعي" : "AI editing suggestion"}</h3>
            <p className="mt-1 inline-flex items-center gap-1.5 text-[11px] text-muted"><Bookmark className="h-3 w-3" aria-hidden="true" />{locale === "ar" ? "مرتبطة بفقرة النص" : "Linked to the selected passage"}</p>

            <div className="mt-5 grid grid-cols-2 divide-x rtl:divide-x-reverse divide-border text-xs leading-6">
              <div className="pe-3">
                <p className="mb-2 text-muted">{locale === "ar" ? "قبل التحرير" : "Before"}</p>
                <p className="text-muted" dir={workspace.language === "ar" ? "rtl" : "ltr"}>{suggestion.before_text}</p>
              </div>
              <div className="ps-3">
                <p className="mb-2 text-muted">{locale === "ar" ? "بعد التحرير" : "After"}</p>
                <p className="font-semibold text-primary-text" dir={workspace.language === "ar" ? "rtl" : "ltr"}>{suggestion.after_text}</p>
              </div>
            </div>

            <div className="mt-5 border-t border-border pt-4">
              <p className="text-[11px] text-muted">{locale === "ar" ? "السبب" : "Reason"}</p>
              <p className="mt-1 text-xs leading-6 text-foreground">{locale === "ar" ? "صياغة بديلة مدعومة بنفس الأدلة. راجعها قبل الاعتماد." : "Alternative wording grounded in the same evidence. Review it before applying."}</p>
            </div>

            <div className="mt-5 grid grid-cols-2 divide-x rtl:divide-x-reverse divide-border border-t border-border">
              <button type="button" className="inline-flex min-h-12 items-center justify-center gap-2 font-semibold text-emerald hover:bg-emerald/5 disabled:opacity-45" disabled={busy} onClick={() => onDecision("accept")}><CheckCircle2 className="h-5 w-5" />{locale === "ar" ? "اعتمد التحسين" : "Accept improvement"}</button>
              <button type="button" className="inline-flex min-h-12 items-center justify-center gap-2 font-semibold text-danger hover:bg-danger/5 disabled:opacity-45" disabled={busy} onClick={() => onDecision("reject")}><X className="h-5 w-5" />{locale === "ar" ? "احتفظ بالأصل" : "Keep original"}</button>
            </div>
          </section>
        ) : (
          <section>
            <h3 className="font-bold text-foreground">{locale === "ar" ? "أوامر التحرير" : "Editing commands"}</h3>
            <p className="mt-1 text-xs leading-6 text-muted">{selection ? (locale === "ar" ? "اختر التحسين وسنعرضه قبل اعتماده." : "Choose an improvement and review it before applying.") : (locale === "ar" ? "اضغط على ملخص أو نقطة في السيرة أولًا." : "Select a summary or bullet in the resume first.")}</p>
            <div className="mt-4 grid grid-cols-2 border-y border-border sm:grid-cols-4 xl:grid-cols-2">
              {([
                ["stronger", locale === "ar" ? "قوّها" : "Strengthen"],
                ["professional", locale === "ar" ? "أكثر مهنية" : "Professional"],
                ["shorter", locale === "ar" ? "اختصرها" : "Shorten"],
                ["custom", locale === "ar" ? "اسألني" : "Ask me"],
              ] as const).map(([mode, label]) => <button type="button" key={mode} className="min-h-14 border-b border-e border-border px-2 text-xs font-semibold text-foreground hover:bg-primary hover:text-primary-foreground disabled:opacity-45" disabled={!selection || rewriting} onClick={() => selection && onRewrite(selection, mode, mode === "custom" ? (locale === "ar" ? "اسألني سؤالًا واحدًا يساعدك على تحسين هذا النص." : "Ask me one question that will help you improve this text.") : undefined)}><PencilLine className="mx-auto mb-1 h-4 w-4" />{label}</button>)}
            </div>
          </section>
        )}
      </div>

      <form className="grid grid-cols-[1fr_auto] border-t border-border" onSubmit={submitInstruction}>
        <input className="min-h-12 min-w-0 bg-transparent px-4 text-sm text-foreground placeholder:text-muted disabled:opacity-45" value={instruction} disabled={!selection || rewriting} onChange={(event) => setInstruction(event.target.value)} placeholder={selection ? (locale === "ar" ? "اكتب تعديلًا للمحرر…" : "Ask for an edit…") : (locale === "ar" ? "حدد نصًا من السيرة أولًا" : "Select text in the resume first")} />
        <button type="submit" className="grid h-12 w-12 place-items-center border-s border-border text-primary-text hover:bg-primary hover:text-primary-foreground disabled:opacity-45" disabled={!selection || !instruction.trim() || rewriting} aria-label={locale === "ar" ? "إرسال طلب التعديل" : "Send edit request"}>{rewriting ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5 rtl:-scale-x-100" />}</button>
      </form>
    </section>
  );
}

export function ResumeWorkspaceV2({
  locale,
  profile,
  initialFacts,
  initialWorkspace,
}: ResumeWorkspaceV2Props) {
  const initialPendingSourceId = typeof initialWorkspace?.provider_metadata?.pending_import_source_id === "string"
    ? initialWorkspace.provider_metadata.pending_import_source_id
    : null;
  const initialPendingFileName = typeof initialWorkspace?.provider_metadata?.pending_import_filename === "string"
    ? initialWorkspace.provider_metadata.pending_import_filename
    : null;
  const initialPendingAnalysisStatus = initialWorkspace?.provider_metadata?.pending_import_analysis_status;
  const initialPendingSourceFacts = initialPendingSourceId
    ? initialFacts.filter((fact) => fact.source_id === initialPendingSourceId)
    : [];
  const [workspace, setWorkspace] = useState<ApiResumeWorkspace | null>(initialWorkspace);
  const [facts, setFacts] = useState(initialFacts);
  const [conversationLanguage, setConversationLanguage] = useState<"ar" | "en">(
    initialWorkspace ? workspaceConversationLanguage(initialWorkspace) : locale,
  );
  const [outputLanguage, setOutputLanguage] = useState<"ar" | "en">(
    initialWorkspace?.language ?? "en",
  );
  const [consentAccepted, setConsentAccepted] = useState(
    initialWorkspace ? !initialWorkspace.consent_required : false,
  );
  const [renewConsentAccepted, setRenewConsentAccepted] = useState(false);
  const [starting, setStarting] = useState(false);
  const [message, setMessage] = useState("");
  const [optimisticMessage, setOptimisticMessage] = useState<ApiResumeMessage | null>(null);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [rewriting, setRewriting] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [downloadNotice, setDownloadNotice] = useState(false);
  const [downloadReady, setDownloadReady] = useState<{
    url: string;
    filename: string;
    contentKey: string;
  } | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(() => (
    workspaceHasCurrentServerReview(initialWorkspace)
  ));
  const [error, setError] = useState<unknown>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [selection, setSelection] = useState<ResumeCanvasSelection | null>(null);
  const [correction, setCorrection] = useState("");
  const [correcting, setCorrecting] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("conversation");
  const [recentImport, setRecentImport] = useState<RecentImportState | null>(() => (
    initialPendingSourceId && initialPendingFileName
      ? {
          sourceId: initialPendingSourceId,
          fileName: initialPendingFileName,
          analysisStatus: initialPendingAnalysisStatus === "created"
            || initialPendingAnalysisStatus === "ai_upgraded"
            || initialPendingAnalysisStatus === "already_ai_analyzed"
            ? initialPendingAnalysisStatus
            : "created",
          confirmedCount: initialPendingSourceFacts.filter((fact) => fact.verification_status === "confirmed").length,
          extractedCount: initialPendingSourceFacts.filter((fact) => fact.verification_status === "extracted").length,
          rejectedCount: initialPendingSourceFacts.filter((fact) => fact.verification_status === "unconfirmed").length,
        }
      : null
  ));
  const [pendingImportFile, setPendingImportFile] = useState<File | null>(null);
  const [importedFacts, setImportedFacts] = useState<ApiCareerFact[]>(
    initialPendingSourceFacts.filter((fact) => fact.verification_status === "extracted"),
  );
  const [selectedImportFactIds, setSelectedImportFactIds] = useState<string[]>(
    initialPendingSourceFacts
      .filter((fact) => fact.verification_status === "extracted")
      .map((fact) => fact.id),
  );
  const [busyImportSourceId, setBusyImportSourceId] = useState<string | null>(null);
  const [importSourceNames, setImportSourceNames] = useState<Record<string, string>>(
    initialPendingSourceId && initialPendingFileName
      ? { [initialPendingSourceId]: initialPendingFileName }
      : {},
  );
  const [showContact, setShowContact] = useState(false);
  const [versions, setVersions] = useState<ApiResumeDraftVersion[]>(initialWorkspace?.versions ?? []);
  const workspaceRef = useRef(workspace);
  const saveTimerRef = useRef<number | null>(null);
  const contactTimerRef = useRef<number | null>(null);
  const draftSaveInFlightRef = useRef(false);
  const contactSaveInFlightRef = useRef(false);
  const reviewAcknowledgementInvalidatedRef = useRef(false);
  const reviewAcknowledgementGenerationRef = useRef(0);
  const revokedDownloadUrlRef = useRef<string | null>(null);
  const queuedDraftSaveRef = useRef<QueuedDraftSave | null>(null);
  const failedContactSaveRef = useRef<ApiResumeWorkspace["contact"] | null>(null);
  const draftEditGenerationRef = useRef(0);
  const operationEpochRef = useRef(0);
  const resetRequestInFlightRef = useRef(false);

  useEffect(() => {
    workspaceRef.current = workspace;
  }, [workspace]);

  useEffect(() => () => {
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    if (contactTimerRef.current) window.clearTimeout(contactTimerRef.current);
  }, []);

  useEffect(() => () => {
    if (pdfPreviewUrl) URL.revokeObjectURL(pdfPreviewUrl);
  }, [pdfPreviewUrl]);

  useEffect(() => () => {
    if (downloadReady && revokedDownloadUrlRef.current !== downloadReady.url) {
      URL.revokeObjectURL(downloadReady.url);
      revokedDownloadUrlRef.current = downloadReady.url;
    }
  }, [downloadReady]);

  const exportContentKey = useMemo(
    () => resumeExportContentKey(profile, workspace),
    [profile, workspace],
  );
  const pdfFilename = `${profile.full_name.trim() || "resume"}-resume.pdf`;

  const visibleDownloadReady = downloadReady
    && downloadReady.contentKey === exportContentKey
    && saveState === "saved"
    && revokedDownloadUrlRef.current !== downloadReady.url
    ? downloadReady
    : null;

  useEffect(() => {
    if (
      !downloadReady
      || (downloadReady.contentKey === exportContentKey && saveState === "saved")
      || revokedDownloadUrlRef.current === downloadReady.url
    ) return;
    URL.revokeObjectURL(downloadReady.url);
    revokedDownloadUrlRef.current = downloadReady.url;
  }, [downloadReady, exportContentKey, saveState]);

  const activeImportFlow = importFlowFromWorkspace(workspace);
  const stageIndex = workspace?.current_draft
    ? 4
    : activeImportFlow?.phase === "additions_choice"
      || activeImportFlow?.phase === "additions_interview"
      || activeImportFlow?.phase === "gap_interview"
      || activeImportFlow?.phase === "ready_to_generate"
      ? 3
      : recentImport
        ? 2
        : 1;
  const generationWarningValue = workspace?.provider_metadata?.generation_warning;
  const generationWarning = generationWarningValue === "ai_unavailable_existing_draft_preserved"
    || generationWarningValue === "ai_unavailable_evidence_fallback_created"
    ? generationWarningValue
    : null;
  const isReview = Boolean(workspace && (
    workspace.stage === "review"
    || workspace.stage === "complete"
    || workspace.pending_suggestion
  ));
  const rewriteLocked = rewriting || saveState !== "saved" || persistenceIsPending();
  const displayedVersions = useMemo(
    () => [...versions].sort((a, b) => b.version - a.version),
    [versions],
  );

  function commitWorkspace(
    next: ApiResumeWorkspace | null,
    { rehydrateServerReview = true }: { rehydrateServerReview?: boolean } = {},
  ) {
    workspaceRef.current = next;
    setWorkspace(next);
    if (rehydrateServerReview) {
      setReviewAcknowledged(
        !reviewAcknowledgementInvalidatedRef.current
        && workspaceHasCurrentServerReview(next),
      );
    }
  }

  function invalidateReviewAcknowledgement() {
    reviewAcknowledgementInvalidatedRef.current = true;
    reviewAcknowledgementGenerationRef.current += 1;
    setReviewAcknowledged(false);
  }

  function operationIsCurrent(operationEpoch: number) {
    return operationEpochRef.current === operationEpoch;
  }

  function persistenceIsPending() {
    // A payload restored after a failed save waits for an explicit retry; it is
    // not "actively pending" and must not keep the conversation frozen.
    const activeQueuedDraftSave = queuedDraftSaveRef.current && !queuedDraftSaveRef.current.failed;
    return Boolean(
      draftSaveInFlightRef.current
      || activeQueuedDraftSave
      || saveTimerRef.current
      || contactSaveInFlightRef.current
      || contactTimerRef.current,
    );
  }

  async function refreshWorkspace(operationEpoch = operationEpochRef.current) {
    const previousWorkspace = workspaceRef.current;
    const [freshWorkspace, freshFacts] = await Promise.all([
      getResumeWorkspace(profile.id),
      getCareerFacts(profile.id),
    ]);
    if (!operationIsCurrent(operationEpoch)) {
      return { workspace: null, facts: [] as ApiCareerFact[] };
    }
    if (!freshWorkspace) {
      if (previousWorkspace) applyLocalWorkspaceReset(previousWorkspace);
      else {
        commitWorkspace(null);
        setVersions([]);
      }
      setFacts(freshFacts);
      return { workspace: null, facts: freshFacts };
    }
    commitWorkspace(freshWorkspace, { rehydrateServerReview: true });
    setVersions(freshWorkspace.versions ?? []);
    const refreshedFlow = importFlowFromWorkspace(freshWorkspace);
    const refreshedImport = pendingImportSnapshot(freshWorkspace, freshFacts);
    if (refreshedFlow) {
      setPendingImportFile(null);
      setRecentImport(null);
      setImportedFacts([]);
      setSelectedImportFactIds([]);
    } else if (refreshedImport) {
      setPendingImportFile(null);
      setRecentImport(refreshedImport.recentImport);
      setImportedFacts(refreshedImport.pendingFacts);
      setSelectedImportFactIds((currentIds) => {
        const pendingIds = new Set(refreshedImport.pendingFacts.map((fact) => fact.id));
        return recentImport?.sourceId === refreshedImport.recentImport.sourceId
          ? currentIds.filter((factId) => pendingIds.has(factId))
          : Array.from(pendingIds);
      });
      setImportSourceNames((currentNames) => ({
        ...currentNames,
        [refreshedImport.recentImport.sourceId]: refreshedImport.recentImport.fileName,
      }));
    } else {
      setRecentImport(null);
      setImportedFacts([]);
      setSelectedImportFactIds([]);
    }
    setFacts(freshFacts);
    return { workspace: freshWorkspace, facts: freshFacts };
  }

  async function handleStart() {
    if (!consentAccepted) return;
    const operationEpoch = operationEpochRef.current;
    setStarting(true);
    setError(null);
    try {
      const created = await startResumeWorkspace(profile.id, {
        conversationLanguage,
        language: outputLanguage,
        dataSharingAcknowledged: true,
      });
      if (!operationIsCurrent(operationEpoch)) return;
      commitWorkspace(created);
      setVersions(created.versions ?? []);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
    } finally {
      if (operationIsCurrent(operationEpoch)) setStarting(false);
    }
  }

  async function handleRenewConsent() {
    const current = workspaceRef.current;
    if (!current || !renewConsentAccepted) return;
    const operationEpoch = operationEpochRef.current;
    setStarting(true);
    setError(null);
    try {
      const renewed = await startResumeWorkspace(profile.id, {
        conversationLanguage: workspaceConversationLanguage(current),
        language: current.language,
        contact: {
          email: current.contact.email ?? undefined,
          phone: current.contact.phone ?? undefined,
          linkedin: current.contact.linkedin ?? undefined,
        },
        dataSharingAcknowledged: true,
      });
      if (!operationIsCurrent(operationEpoch)) return;
      commitWorkspace(renewed);
      setVersions(renewed.versions ?? []);
      setRenewConsentAccepted(false);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
    } finally {
      if (operationIsCurrent(operationEpoch)) setStarting(false);
    }
  }

  async function performMessage(content: string, quickAction?: ResumeQuickAction) {
    const current = workspaceRef.current;
    const normalizedContent = content.trim();
    if (
      !current
      || (!normalizedContent && !quickAction)
      // Block chat only while a save is actively running or queued; a FAILED
      // save must not freeze the conversation (the header offers "Retry save").
      || saveState === "saving"
      || persistenceIsPending()
    ) return;
    const operationEpoch = operationEpochRef.current;
    const clientTurnId = freshTurnId();
    const restoreMessageOnError = !quickAction && Boolean(normalizedContent);
    setOptimisticMessage({
      id: `optimistic-${clientTurnId}`,
      sequence: current.messages.length + 1,
      role: "user",
      kind: "text",
      content: normalizedContent,
      structured_payload: quickAction ? { quick_action: quickAction } : {},
      status: "pending",
      client_turn_id: clientTurnId,
      created_at: new Date().toISOString(),
    });
    if (restoreMessageOnError) setMessage("");
    setBusy(true);
    setError(null);
    try {
      const next = await sendResumeWorkspaceMessage(profile.id, {
        content: normalizedContent,
        clientTurnId,
        expectedRevision: current.revision,
        quickAction,
      });
      if (!operationIsCurrent(operationEpoch)) return;
      commitWorkspace(next);
      setVersions((currentVersions) => next.versions ?? currentVersions);
      setOptimisticMessage(null);
      setRecentImport(null);
      if (next.current_draft && next.stage !== "understanding") setMobilePanel("resume");
    } catch (nextError) {
      if (!operationIsCurrent(operationEpoch)) return;
      const refreshed = await refreshWorkspace(operationEpoch).catch(() => null);
      if (!operationIsCurrent(operationEpoch)) return;
      const requestCommitted = Boolean(
        refreshed?.workspace?.messages.some((entry) => (
          entry.client_turn_id === clientTurnId && entry.status !== "failed"
        )),
      );
      setOptimisticMessage(null);
      if (requestCommitted && refreshed?.workspace) {
        if (restoreMessageOnError) setMessage("");
        setError(null);
        setRecentImport(null);
        if (refreshed.workspace.current_draft && refreshed.workspace.stage !== "understanding") {
          setMobilePanel("resume");
        }
        return;
      }
      if (restoreMessageOnError) {
        setMessage((currentMessage) => currentMessage || normalizedContent);
      }
      setError(nextError);
    } finally {
      if (operationIsCurrent(operationEpoch)) setBusy(false);
    }
  }

  function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void performMessage(message);
  }

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    const current = workspaceRef.current;
    if (!file || !current || current.consent_required) return;
    setError(null);
    if (current.current_draft) {
      setError(new Error(locale === "ar" ? "امسح المسودة الحالية أولًا قبل رفع ملف سيرة آخر." : "Clear the current draft before uploading another resume."));
      return;
    }
    if (!supportsResume(file)) {
      setError(new Error(locale === "ar" ? "اختر ملف PDF أو DOCX فقط." : "Choose a PDF or DOCX file."));
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError(new Error(locale === "ar" ? "حجم الملف أكبر من 10 ميجابايت." : "The file is larger than 10 MB."));
      return;
    }
    setPendingImportFile(file);
    setRecentImport(null);
  }

  async function handleConfirmImport() {
    const file = pendingImportFile;
    const current = workspaceRef.current;
    if (!file || !current || current.consent_required) return;
    const operationEpoch = operationEpochRef.current;
    let analyzedSourceId: string | null = null;
    setImporting(true);
    setError(null);
    try {
      const result = await importResumeWorkspaceFile(profile.id, file, {
        // This acknowledgement is sent only after the explicit confirmation above.
        dataSharingAcknowledged: true,
      });
      analyzedSourceId = result.source.id;
      if (!operationIsCurrent(operationEpoch)) return;
      const refreshed = await refreshWorkspace(operationEpoch);
      if (!operationIsCurrent(operationEpoch)) return;
      const currentSourceFacts = refreshed.facts.filter((fact) => fact.source_id === result.source.id);
      const pendingFacts = currentSourceFacts.filter((fact) => fact.verification_status === "extracted");
      const currentSourcePendingIds = currentSourceFacts
        .filter((fact) => fact.verification_status === "extracted")
        .map((fact) => fact.id);
      const confirmedCount = currentSourceFacts.filter((fact) => fact.verification_status === "confirmed").length;
      const extractedCount = currentSourcePendingIds.length;
      const rejectedCount = currentSourceFacts.filter((fact) => fact.verification_status === "unconfirmed").length;
      setImportedFacts(pendingFacts);
      setSelectedImportFactIds((currentIds) => {
        const pendingIds = new Set(pendingFacts.map((fact) => fact.id));
        return Array.from(new Set([
          ...currentIds.filter((factId) => pendingIds.has(factId)),
          ...currentSourcePendingIds,
        ]));
      });
      setImportSourceNames((currentNames) => ({
        ...currentNames,
        [result.source.id]: result.source.original_filename ?? file.name,
      }));
      setRecentImport({
        sourceId: result.source.id,
        fileName: result.source.original_filename ?? file.name,
        analysisStatus: result.analysis_status,
        confirmedCount,
        extractedCount,
        rejectedCount,
      });
      setPendingImportFile(null);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        const refreshed = await refreshWorkspace(operationEpoch).catch(() => null);
        const refreshedFlow = importFlowFromWorkspace(refreshed?.workspace ?? null);
        const recovered = pendingImportSnapshot(refreshed?.workspace, refreshed?.facts ?? [], file.name);
        const responseWasLost = nextError instanceof TypeError
          || (nextError instanceof DOMException && nextError.name === "AbortError");
        const requestCompleted = Boolean(
          recovered
          && (
            recovered.recentImport.sourceId === analyzedSourceId
            || (
              analyzedSourceId === null
              && responseWasLost
              && recovered.recentImport.fileName.trim().toLocaleLowerCase() === file.name.trim().toLocaleLowerCase()
            )
          )
        );
        if (refreshedFlow) {
          // Another tab may have advanced an already prepared import while this upload
          // was in flight. The persisted flow is authoritative; do not leave a stale
          // consent card beside it or guess ownership from a duplicate filename.
          setError(null);
          setPendingImportFile(null);
          setImportedFacts([]);
          setSelectedImportFactIds([]);
          setRecentImport(null);
        } else if (requestCompleted && recovered) {
          setError(null);
          setPendingImportFile(null);
          setImportedFacts(recovered.pendingFacts);
          setSelectedImportFactIds(recovered.pendingFacts.map((fact) => fact.id));
          setRecentImport(recovered.recentImport);
          setImportSourceNames((currentNames) => ({
            ...currentNames,
            [recovered.recentImport.sourceId]: recovered.recentImport.fileName,
          }));
        } else {
          setError(nextError);
        }
      }
    } finally {
      if (operationIsCurrent(operationEpoch)) {
        setImporting(false);
        setBusyImportSourceId(null);
      }
    }
  }

  function handleToggleImportFact(factId: string, selected: boolean) {
    setSelectedImportFactIds((currentIds) => selected
      ? Array.from(new Set([...currentIds, factId]))
      : currentIds.filter((currentId) => currentId !== factId));
  }

  function handleToggleImportSource(sourceId: string, selected: boolean) {
    const sourceFactIds = importedFacts
      .filter((fact) => fact.source_id === sourceId)
      .map((fact) => fact.id);
    setSelectedImportFactIds((currentIds) => {
      const next = new Set(currentIds);
      sourceFactIds.forEach((factId) => {
        if (selected) next.add(factId);
        else next.delete(factId);
      });
      return Array.from(next);
    });
  }

  async function handleBuildImportDraft(sourceId: string, includeSelectedFacts: boolean) {
    const current = workspaceRef.current;
    if (
      !current
      || current.current_draft
      || busyImportSourceId
      || busy
      || importing
      || rewriting
      || reviewing
      || resetting
      || saveState !== "saved"
      || persistenceIsPending()
    ) return;
    const sourcePendingFacts = importedFacts.filter((fact) => fact.source_id === sourceId);
    const selectedFactIds = includeSelectedFacts
      ? sourcePendingFacts
          .filter((fact) => selectedImportFactIds.includes(fact.id))
          .map((fact) => fact.id)
      : [];
    const rejectedFactIds = includeSelectedFacts
      ? sourcePendingFacts
          .filter((fact) => !selectedImportFactIds.includes(fact.id))
          .map((fact) => fact.id)
      : [];
    if (
      sourcePendingFacts.length
      && !selectedFactIds.length
      && !(recentImport?.sourceId === sourceId && recentImport.confirmedCount > 0)
    ) return;
    const operationEpoch = operationEpochRef.current;
    const clientRequestId = freshTurnId();
    setBusyImportSourceId(sourceId);
    setError(null);
    try {
      let evidenceRevision = current.evidence_revision;
      if (selectedFactIds.length || rejectedFactIds.length) {
        const confirmation = await confirmCareerFactsBatch(profile.id, {
          sourceId,
          clientRequestId,
          factIds: selectedFactIds,
          rejectedFactIds,
          expectedEvidenceRevision: evidenceRevision,
        });
        evidenceRevision = confirmation.evidence_revision;
        const confirmedById = new Map(confirmation.facts.map((fact) => [fact.id, fact]));
        setFacts((currentFacts) => currentFacts.map((fact) => confirmedById.get(fact.id) ?? fact));
      }
      if (!operationIsCurrent(operationEpoch)) return;
      const next = await prepareResumeImportFlow(profile.id, {
        sourceId,
        clientRequestId,
        expectedRevision: current.revision,
        expectedEvidenceRevision: evidenceRevision,
      });
      if (!operationIsCurrent(operationEpoch)) return;
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      const sourceFactIds = new Set(sourcePendingFacts.map((fact) => fact.id));
      setImportedFacts((currentFacts) => currentFacts.filter((fact) => fact.source_id !== sourceId));
      setSelectedImportFactIds((currentIds) => currentIds.filter((factId) => !sourceFactIds.has(factId)));
      setRecentImport(null);
      setMobilePanel("conversation");
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        const refreshed = await refreshWorkspace(operationEpoch).catch(() => null);
        if (refreshed && operationIsCurrent(operationEpoch)) {
          const refreshedImportFlow = importFlowFromWorkspace(refreshed.workspace);
          const requestCompleted = refreshedImportFlow?.source_id === sourceId;
          if (refreshedImportFlow) {
            setImportedFacts([]);
            setSelectedImportFactIds([]);
            setRecentImport(null);
            setMobilePanel("conversation");
            if (requestCompleted) {
              setError(null);
              return;
            }
          } else {
            const refreshedSourceFacts = refreshed.facts.filter((fact) => fact.source_id === sourceId);
            const pendingFacts = refreshedSourceFacts.filter((fact) => fact.verification_status === "extracted");
            setImportedFacts(pendingFacts);
            setSelectedImportFactIds((currentIds) => currentIds.filter((factId) => pendingFacts.some((fact) => fact.id === factId)));
            setRecentImport((currentImport) => currentImport?.sourceId === sourceId
              ? {
                  ...currentImport,
                  confirmedCount: refreshedSourceFacts.filter((fact) => fact.verification_status === "confirmed").length,
                  extractedCount: refreshedSourceFacts.filter((fact) => fact.verification_status === "extracted").length,
                  rejectedCount: refreshedSourceFacts.filter((fact) => fact.verification_status === "unconfirmed").length,
                }
              : currentImport);
          }
        }
        setError(nextError);
      }
    } finally {
      if (operationIsCurrent(operationEpoch)) setBusyImportSourceId(null);
    }
  }

  async function handleConfirmUnderstanding() {
    const current = workspaceRef.current;
    if (!current) return;
    const id = latestUnderstandingId(current);
    if (!id) return;
    const operationEpoch = operationEpochRef.current;
    setBusy(true);
    setError(null);
    try {
      const next = await confirmResumeUnderstanding(profile.id, id, current.revision);
      if (!operationIsCurrent(operationEpoch)) return;
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      const refreshedFacts = await getCareerFacts(profile.id);
      if (!operationIsCurrent(operationEpoch)) return;
      setFacts(refreshedFacts);
      setCorrecting(false);
      setCorrection("");
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        const refreshed = await refreshWorkspace(operationEpoch).catch(() => null);
        const completed = Boolean(
          refreshed?.workspace
          && latestUnderstandingId(refreshed.workspace) !== id,
        );
        if (completed) {
          setError(null);
          setCorrecting(false);
          setCorrection("");
        } else {
          setError(nextError);
        }
      }
    } finally {
      if (operationIsCurrent(operationEpoch)) setBusy(false);
    }
  }

  async function handleCorrectUnderstanding() {
    const current = workspaceRef.current;
    if (!current || !correction.trim()) return;
    const id = latestUnderstandingId(current);
    if (!id) return;
    const operationEpoch = operationEpochRef.current;
    setBusy(true);
    setError(null);
    try {
      const next = await correctResumeUnderstanding(profile.id, id, {
        expectedRevision: current.revision,
        correctedText: correction,
      });
      if (!operationIsCurrent(operationEpoch)) return;
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      const refreshedFacts = await getCareerFacts(profile.id);
      if (!operationIsCurrent(operationEpoch)) return;
      setFacts(refreshedFacts);
      setCorrecting(false);
      setCorrection("");
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        const refreshed = await refreshWorkspace(operationEpoch).catch(() => null);
        const completed = Boolean(
          refreshed?.workspace
          && latestUnderstandingId(refreshed.workspace) !== id,
        );
        if (completed) {
          setError(null);
          setCorrecting(false);
          setCorrection("");
        } else {
          setError(nextError);
        }
      }
    } finally {
      if (operationIsCurrent(operationEpoch)) setBusy(false);
    }
  }

  async function flushDraftSave() {
    if (draftSaveInFlightRef.current) return;
    const queuedSave = queuedDraftSaveRef.current;
    const current = workspaceRef.current;
    if (!queuedSave || !current) return;
    if (!operationIsCurrent(queuedSave.operationEpoch)) {
      queuedDraftSaveRef.current = null;
      return;
    }

    queuedDraftSaveRef.current = null;
    draftSaveInFlightRef.current = true;
    let succeeded = false;
    try {
      const saved = await patchResumeWorkspaceDraft(profile.id, {
        draft: queuedSave.draft,
        expectedDraftRevision: current.draft_revision,
      });
      if (!operationIsCurrent(queuedSave.operationEpoch)) return;
      const latest = workspaceRef.current;
      if (latest) {
        const hasNewerLocalDraft = draftEditGenerationRef.current > queuedSave.generation;
        const serverDraftIsCurrent = saved.draft_revision >= latest.draft_revision;
        const merged: ApiResumeWorkspace = {
          ...latest,
          current_draft: hasNewerLocalDraft || !serverDraftIsCurrent
            ? latest.current_draft
            : saved.current_draft,
          draft_revision: Math.max(latest.draft_revision, saved.draft_revision),
          versions: serverDraftIsCurrent ? (saved.versions ?? latest.versions) : latest.versions,
          updated_at: serverDraftIsCurrent && saved.updated_at > latest.updated_at
            ? saved.updated_at
            : latest.updated_at,
        };
        commitWorkspace(merged);
        setVersions(merged.versions ?? []);
      }
      succeeded = true;
    } catch (nextError) {
      if (operationIsCurrent(queuedSave.operationEpoch)) {
        // Restore the failed payload (unless a newer edit superseded it while the
        // request was in flight) so "Retry save" has something to flush.
        if (!queuedDraftSaveRef.current) {
          queuedDraftSaveRef.current = { ...queuedSave, failed: true };
        }
        setSaveState("error");
        setError(nextError);
      }
    } finally {
      if (!operationIsCurrent(queuedSave.operationEpoch)) return;
      draftSaveInFlightRef.current = false;
      if (queuedDraftSaveRef.current && !queuedDraftSaveRef.current.failed) {
        setSaveState("saving");
        if (!saveTimerRef.current) void flushDraftSave();
      } else if (succeeded) {
        setSaveState(persistenceIsPending()
          ? "saving"
          : failedContactSaveRef.current ? "error" : "saved");
      }
    }
  }

  function scheduleDraftSave(nextDraft: ApiResumeDraftContent) {
    const current = workspaceRef.current;
    if (!current) return;
    const generation = draftEditGenerationRef.current + 1;
    draftEditGenerationRef.current = generation;
    queuedDraftSaveRef.current = {
      draft: nextDraft,
      generation,
      operationEpoch: operationEpochRef.current,
    };
    invalidateReviewAcknowledgement();
    commitWorkspace({ ...current, current_draft: nextDraft });
    setSaveState("saving");
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null;
      void flushDraftSave();
    }, 700);
  }

  function handleDraftChange(nextDraft: ApiResumeDraftContent) {
    const current = workspaceRef.current;
    if (!current) return;
    scheduleDraftSave(nextDraft);
  }

  async function performContactSave(
    contact: ApiResumeWorkspace["contact"],
    operationEpoch: number,
  ) {
    if (!operationIsCurrent(operationEpoch)) return;
    const latest = workspaceRef.current;
    if (!latest) return;
    contactSaveInFlightRef.current = true;
    let succeeded = false;
    try {
      const saved = await startResumeWorkspace(profile.id, {
        conversationLanguage: workspaceConversationLanguage(latest),
        language: latest.language,
        contact: {
          email: contact.email ?? undefined,
          phone: contact.phone ?? undefined,
          linkedin: contact.linkedin ?? undefined,
        },
        dataSharingAcknowledged: false,
      });
      if (!operationIsCurrent(operationEpoch)) return;
      const newest = workspaceRef.current;
      if (newest) {
        commitWorkspace({
          ...newest,
          updated_at: saved.updated_at,
        });
      }
      failedContactSaveRef.current = null;
      succeeded = true;
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        // Keep the failed payload so "Retry save" can re-send it.
        failedContactSaveRef.current = contact;
        setSaveState("error");
        setError(nextError);
      }
    } finally {
      if (!operationIsCurrent(operationEpoch)) return;
      contactSaveInFlightRef.current = false;
      if (succeeded) {
        setSaveState(persistenceIsPending()
          ? "saving"
          : queuedDraftSaveRef.current?.failed ? "error" : "saved");
      }
    }
  }

  function handleContactChange(contact: ApiResumeWorkspace["contact"]) {
    const current = workspaceRef.current;
    if (!current) return;
    const operationEpoch = operationEpochRef.current;
    invalidateReviewAcknowledgement();
    commitWorkspace({ ...current, contact });
    // A newer edit supersedes any previously failed payload: the scheduled save
    // sends the full latest contact object.
    failedContactSaveRef.current = null;
    setSaveState("saving");
    if (contactTimerRef.current) window.clearTimeout(contactTimerRef.current);
    contactTimerRef.current = window.setTimeout(() => {
      contactTimerRef.current = null;
      void performContactSave(contact, operationEpoch);
    }, 700);
  }

  function retryPendingSaves() {
    const failedContact = failedContactSaveRef.current;
    const hasDraftRetry = Boolean(queuedDraftSaveRef.current) && !draftSaveInFlightRef.current;
    const hasContactRetry = Boolean(failedContact)
      && !contactSaveInFlightRef.current
      && !contactTimerRef.current;
    if (!hasDraftRetry && !hasContactRetry) {
      // Nothing left to retry (the failed payloads were superseded); reflect the
      // actual persistence state instead of staying stuck on "error".
      setSaveState(persistenceIsPending() ? "saving" : "saved");
      return;
    }
    setError(null);
    setSaveState("saving");
    if (hasDraftRetry) {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      void flushDraftSave();
    }
    if (hasContactRetry && failedContact) {
      failedContactSaveRef.current = null;
      void performContactSave(failedContact, operationEpochRef.current);
    }
  }

  async function handleRewrite(
    target: ResumeCanvasSelection,
    mode: ResumeRewriteMode,
    instruction?: string,
  ) {
    const current = workspaceRef.current;
    if (!current?.current_draft || saveState !== "saved" || persistenceIsPending()) return;
    const requestedDraftRevision = current.draft_revision;
    const requestedEditGeneration = draftEditGenerationRef.current;
    const operationEpoch = operationEpochRef.current;
    setRewriting(true);
    setError(null);
    try {
      const suggestion = await rewriteResumeDraftSelection(profile.id, {
        targetKind: target.targetKind,
        sectionKey: target.sectionKey,
        itemId: target.itemId,
        bulletIndex: target.bulletIndex,
        mode,
        instruction,
        expectedDraftRevision: requestedDraftRevision,
      });
      if (!operationIsCurrent(operationEpoch)) return;
      const latest = workspaceRef.current;
      const draftStayedCurrent = Boolean(
        latest?.current_draft
        && suggestion.base_draft_revision === requestedDraftRevision
        && suggestion.base_draft_revision === latest.draft_revision
        && draftEditGenerationRef.current === requestedEditGeneration
      );
      if (!latest || !draftStayedCurrent) {
        setError(new Error(locale === "ar"
          ? "تغيّرت المسودة أثناء إعداد التحسين. حُفظت تعديلاتك؛ اطلب التحسين مرة أخرى."
          : "The draft changed while the improvement was being prepared. Your edits were kept; request the improvement again."));
        return;
      }
      invalidateReviewAcknowledgement();
      commitWorkspace({ ...latest, pending_suggestion: suggestion, stage: "review" });
      setMobilePanel("resume");
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
    } finally {
      if (operationIsCurrent(operationEpoch)) setRewriting(false);
    }
  }

  async function handleSuggestionDecision(decision: "accept" | "reject") {
    const current = workspaceRef.current;
    if (!current) return;
    const id = latestSuggestionId(current);
    if (!id) return;
    const operationEpoch = operationEpochRef.current;
    setBusy(true);
    setError(null);
    try {
      const next = await decideResumeRewriteSuggestion(profile.id, id, decision, current.draft_revision);
      if (!operationIsCurrent(operationEpoch)) return;
      invalidateReviewAcknowledgement();
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
    } finally {
      if (operationIsCurrent(operationEpoch)) setBusy(false);
    }
  }

  async function handleRestore(versionId: string) {
    const current = workspaceRef.current;
    if (!current) return;
    const operationEpoch = operationEpochRef.current;
    setBusy(true);
    setError(null);
    try {
      const next = await restoreResumeDraftVersion(profile.id, versionId, current.draft_revision);
      if (!operationIsCurrent(operationEpoch)) return;
      invalidateReviewAcknowledgement();
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
    } finally {
      if (operationIsCurrent(operationEpoch)) setBusy(false);
    }
  }

  async function loadVersions(operationEpoch = operationEpochRef.current) {
    try {
      const nextVersions = await getResumeDraftVersions(profile.id);
      if (operationIsCurrent(operationEpoch)) setVersions(nextVersions);
    } catch {
      // The workspace response already carries recent versions; keep them if refresh fails.
    }
  }

  async function handleReviewChange(checked: boolean) {
    const current = workspaceRef.current;
    if (!checked || !current?.current_draft) {
      invalidateReviewAcknowledgement();
      return;
    }
    const operationEpoch = operationEpochRef.current;
    const reviewAcknowledgementGeneration = reviewAcknowledgementGenerationRef.current;
    setReviewing(true);
    setError(null);
    try {
      const result = await reviewResumeWorkspace(profile.id, current.draft_revision);
      if (!operationIsCurrent(operationEpoch)) return;
      if (reviewAcknowledgementGenerationRef.current === reviewAcknowledgementGeneration) {
        reviewAcknowledgementInvalidatedRef.current = false;
      }
      await refreshWorkspace(operationEpoch);
      if (!operationIsCurrent(operationEpoch)) return;
      setReviewAcknowledged(
        result.export_allowed && !reviewAcknowledgementInvalidatedRef.current,
      );
      await loadVersions(operationEpoch);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        invalidateReviewAcknowledgement();
        setError(nextError);
      }
    } finally {
      if (operationIsCurrent(operationEpoch)) setReviewing(false);
    }
  }

  async function handlePreviewPdf() {
    if (!workspace?.current_draft) return;
    const operationEpoch = operationEpochRef.current;
    setPreviewing(true);
    setError(null);
    try {
      const blob = await previewResumeWorkspacePdf(profile.id);
      if (!operationIsCurrent(operationEpoch)) return;
      const url = URL.createObjectURL(blob);
      setPdfPreviewUrl(url);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
    } finally {
      if (operationIsCurrent(operationEpoch)) setPreviewing(false);
    }
  }

  async function handleExport() {
    const current = workspaceRef.current;
    if (!current?.current_draft || !reviewAcknowledged) return;
    const operationEpoch = operationEpochRef.current;
    setExporting(true);
    setDownloadNotice(false);
    setDownloadReady(null);
    setError(null);
    try {
      const blob = await exportResumeWorkspacePdf(profile.id, current.draft_revision);
      if (!operationIsCurrent(operationEpoch)) return;
      const url = saveBlob(blob, pdfFilename);
      revokedDownloadUrlRef.current = null;
      setDownloadReady({
        url,
        filename: pdfFilename,
        contentKey: resumeExportContentKey(profile, current),
      });
      commitWorkspace({ ...current, stage: "complete" });
      setDownloadNotice(true);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
    } finally {
      if (operationIsCurrent(operationEpoch)) setExporting(false);
    }
  }

  function applyLocalWorkspaceReset(current: ApiResumeWorkspace) {
    const preservedConversationLanguage = workspaceConversationLanguage(current);
    const preservedOutputLanguage = current.language;

    operationEpochRef.current += 1;
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    if (contactTimerRef.current) window.clearTimeout(contactTimerRef.current);
    saveTimerRef.current = null;
    contactTimerRef.current = null;
    queuedDraftSaveRef.current = null;
    failedContactSaveRef.current = null;
    draftSaveInFlightRef.current = false;
    contactSaveInFlightRef.current = false;
    reviewAcknowledgementInvalidatedRef.current = false;
    draftEditGenerationRef.current += 1;

    commitWorkspace(null);
    setVersions([]);
    setConversationLanguage(preservedConversationLanguage);
    setOutputLanguage(preservedOutputLanguage);
    setConsentAccepted(false);
    setRenewConsentAccepted(false);
    setStarting(false);
    setBusy(false);
    setImporting(false);
    setRewriting(false);
    setReviewing(false);
    setPreviewing(false);
    setExporting(false);
    setMessage("");
    setOptimisticMessage(null);
    setReviewAcknowledged(false);
    setSaveState("saved");
    setSelection(null);
    setCorrection("");
    setCorrecting(false);
    setMobilePanel("conversation");
    setRecentImport(null);
    setPendingImportFile(null);
    setImportedFacts([]);
    setSelectedImportFactIds([]);
    setBusyImportSourceId(null);
    setImportSourceNames({});
    setShowContact(false);
    setError(null);
    setResetError(null);
    setResetDialogOpen(false);
  }

  function closeResetDialog() {
    if (resetting) return;
    setResetDialogOpen(false);
    setResetError(null);
  }

  async function handleResetWorkspace() {
    const current = workspaceRef.current;
    if (
      !current
      || resetRequestInFlightRef.current
      || resetting
      || starting
      || busy
      || importing
      || rewriting
      || reviewing
      || previewing
      || exporting
      || busyImportSourceId !== null
      || correcting
      || saveState === "saving"
      || persistenceIsPending()
    ) return;

    resetRequestInFlightRef.current = true;
    setResetting(true);
    setResetError(null);
    setError(null);
    try {
      await resetResumeWorkspace(profile.id, current.revision);
      applyLocalWorkspaceReset(current);
    } catch (nextError) {
      if (nextError instanceof ApiHttpError && nextError.status === 404) {
        applyLocalWorkspaceReset(current);
      } else if (nextError instanceof ApiHttpError && nextError.status === 409) {
        try {
          const refreshed = await refreshWorkspace(operationEpochRef.current);
          if (!refreshed.workspace) {
            applyLocalWorkspaceReset(current);
          } else {
            setResetError(locale === "ar"
              ? "تغيّرت مساحة السيرة في تبويب آخر. حدّثنا أحدث نسخة؛ راجعها ثم اضغط المسح مرة أخرى."
              : "The resume workspace changed in another tab. We loaded the latest version; review it, then clear it again.");
          }
        } catch {
          setResetError(locale === "ar"
            ? "تغيّرت مساحة السيرة، لكن تعذر تحميل أحدث نسخة. أغلق النافذة وحدّث الصفحة قبل المحاولة مجددًا."
            : "The resume workspace changed, but the latest version could not be loaded. Close this dialog and refresh the page before trying again.");
        }
      } else {
        setResetError(apiErrorMessage(nextError, locale));
      }
    } finally {
      resetRequestInFlightRef.current = false;
      setResetting(false);
    }
  }

  const annotationsCount = workspace?.pending_suggestion || workspace?.pending_understanding ? 1 : 0;
  const hasDraft = Boolean(workspace?.current_draft);
  const resetBlocked = Boolean(
    resetting
    || starting
    || busy
    || importing
    || rewriting
    || reviewing
    || previewing
    || exporting
    || busyImportSourceId !== null
    || correcting
    || saveState === "saving"
  );
  const activeConversationLanguage = workspace
    ? workspaceConversationLanguage(workspace)
    : conversationLanguage;
  const activeOutputLanguage = workspace?.language ?? outputLanguage;

  return (
    <div className="min-h-[calc(100vh-86px)] bg-background px-3 pb-44 pt-4 text-foreground sm:px-5 xl:h-[calc(100vh-80px)] xl:min-h-[720px] xl:px-6 xl:pb-4 xl:pt-3" dir={locale === "ar" ? "rtl" : "ltr"}>
      <div className="mx-auto flex h-full w-full max-w-[1600px] flex-col">
        <header className="shrink-0 pb-3 xl:pb-4">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <h1 className="truncate text-xl font-bold leading-tight tracking-[-0.02em] text-foreground sm:text-2xl">
                {hasDraft
                  ? (locale === "ar" ? "مختبر تحرير السيرة" : "Resume Proofing Studio")
                  : (locale === "ar" ? "خلّنا نبني قصتك المهنية" : "Let’s build your professional story")}
              </h1>
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <div className="hidden sm:block"><ReadinessBar score={workspace?.readiness_score ?? 0} locale={locale} /></div>
              <div className={cn("inline-flex items-center gap-1.5 text-xs font-semibold", saveState === "error" ? "text-danger" : saveState === "saving" ? "text-primary-text" : "text-emerald")} role="status">
                {saveState === "saving" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : saveState === "error" ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                {saveState === "saving" ? (locale === "ar" ? "جارٍ الحفظ…" : "Saving…") : saveState === "error" ? (locale === "ar" ? "تعذر الحفظ" : "Save failed") : (locale === "ar" ? "محفوظ" : "Saved")}
              </div>
              {saveState === "error" ? (
                <button
                  type="button"
                  className="inline-flex min-h-9 items-center gap-1.5 border border-danger px-3 text-xs font-semibold text-danger hover:bg-danger hover:text-white"
                  onClick={retryPendingSaves}
                >
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  {locale === "ar" ? "أعد محاولة الحفظ" : "Retry save"}
                </button>
              ) : null}
              {workspace ? (
                <>
                  <span className="hidden text-xs text-muted sm:inline">
                    {locale === "ar" ? "الحوار" : "Chat"} {activeConversationLanguage.toUpperCase()} · {locale === "ar" ? "السيرة" : "Resume"} {activeOutputLanguage.toUpperCase()}
                  </span>
                  <button
                    type="button"
                    className="inline-flex min-h-9 items-center gap-1.5 text-xs font-semibold text-muted hover:text-danger disabled:cursor-not-allowed disabled:opacity-45"
                    disabled={resetBlocked}
                    onClick={() => { setResetError(null); setResetDialogOpen(true); }}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    {locale === "ar" ? "مسح والبدء من جديد" : "Clear and start over"}
                  </button>
                </>
              ) : null}
            </div>
          </div>
          {/* The stage rail guides the interview; once a draft exists every step is done
              and the studio's own controls carry the state, so it retires. */}
          {!hasDraft ? <div className="mx-auto mt-3 max-w-xl"><StageRail current={stageIndex} locale={locale} /></div> : null}
        </header>

        {generationWarning ? (
          <p className="mb-3 flex items-center gap-2 border border-primary/35 bg-primary/10 px-4 py-3 text-sm font-medium text-foreground" role="status">
            <AlertCircle className="h-4 w-4 shrink-0 text-primary-text" aria-hidden="true" />
            {generationWarning === "ai_unavailable_existing_draft_preserved"
              ? (locale === "ar"
                ? "تعذر الوصول إلى كاتب الذكاء الاصطناعي مؤقتًا؛ مسودتك الحالية محفوظة دون تغيير."
                : "The AI writer is temporarily unavailable; your current draft is saved unchanged.")
              : (locale === "ar"
                ? "هذه مسودة موثقة من معلوماتك المؤكدة لأن كاتب الذكاء الاصطناعي غير متاح مؤقتًا."
                : "This is an evidence-only draft because the AI writer is temporarily unavailable.")}
          </p>
        ) : null}

        <div className="mb-3 grid shrink-0 grid-cols-2 border-b border-border xl:hidden" role="tablist" aria-label={locale === "ar" ? "عرض مساحة السيرة" : "Resume workspace view"}>
          <button
            type="button"
            role="tab"
            aria-label={locale === "ar" ? "المحادثة" : "Conversation"}
            aria-selected={mobilePanel === "conversation"}
            className={cn("min-h-12 border-b-2 text-sm font-semibold", mobilePanel === "conversation" ? "border-primary text-primary-text" : "border-transparent text-muted")}
            onClick={() => setMobilePanel("conversation")}
          >
            <Pencil className="me-2 inline h-4 w-4" />
            {hasDraft ? (locale === "ar" ? "الهوامش" : "Annotations") : (locale === "ar" ? "المحادثة" : "Conversation")}
            {annotationsCount ? ` · ${annotationsCount}` : ""}
          </button>
          <button type="button" role="tab" aria-selected={mobilePanel === "resume"} className={cn("min-h-12 border-b-2 text-sm font-semibold", mobilePanel === "resume" ? "border-primary text-primary-text" : "border-transparent text-muted")} onClick={() => setMobilePanel("resume")}><FileText className="me-2 inline h-4 w-4" />{locale === "ar" ? "السيرة" : "Resume"}</button>
        </div>

        <div className={cn(
          "grid min-h-[620px] flex-1 gap-y-3 xl:min-h-0 xl:gap-0 xl:[direction:ltr]",
          workspace
            ? "xl:grid-cols-[112px_minmax(430px,1.08fr)_minmax(250px,0.58fr)_minmax(220px,0.46fr)]"
            : "xl:grid-cols-[minmax(440px,1.1fr)_minmax(360px,0.72fr)]",
        )}>
          {workspace ? (
            <ProofingVersionRail
              locale={locale}
              versions={displayedVersions}
              busy={busy || resetting}
              onRestore={(versionId) => void handleRestore(versionId)}
              className={cn("order-4 xl:order-none xl:block xl:[direction:rtl]", mobilePanel !== "resume" && "hidden xl:block")}
            />
          ) : null}

          <div className={cn("order-1 min-h-0 xl:order-none xl:block", mobilePanel !== "resume" && "hidden xl:block")} dir={locale === "ar" ? "rtl" : "ltr"}>
            <ResumeProofingPaper
              locale={locale}
              documentLanguage={activeOutputLanguage}
              profile={profile}
              facts={facts}
              draft={workspace?.current_draft ?? null}
              contact={workspace?.contact ?? {}}
              editable={Boolean(workspace?.current_draft)}
              editingLocked={busy || rewriting || resetting}
              selection={selection}
              rewriting={rewriteLocked}
              onSelect={setSelection}
              onDraftChange={handleDraftChange}
              onRewrite={(target, mode, instruction) => void handleRewrite(target, mode, instruction)}
            />
          </div>

          <div className={cn(
            "order-2 min-h-0 xl:order-none xl:block xl:[direction:rtl]",
            mobilePanel !== "conversation" && "hidden xl:block",
          )} dir={locale === "ar" ? "rtl" : "ltr"}>
            {!workspace ? (
              <SetupConversation
                locale={locale}
                conversationLanguage={conversationLanguage}
                outputLanguage={outputLanguage}
                consentAccepted={consentAccepted}
                starting={starting}
                error={error}
                onConversationLanguage={setConversationLanguage}
                onOutputLanguage={setOutputLanguage}
                onConsent={setConsentAccepted}
                onStart={() => void handleStart()}
              />
            ) : workspace.consent_required ? (
              <ConsentRenewalPanel
                locale={locale}
                accepted={renewConsentAccepted}
                renewing={starting}
                error={error}
                onAcceptedChange={setRenewConsentAccepted}
                onRenew={() => void handleRenewConsent()}
              />
            ) : isReview ? (
              <ReviewPanel
                locale={locale}
                workspace={workspace}
                selection={selection}
                busy={busy || resetting || saveState !== "saved" || persistenceIsPending()}
                rewriting={rewriteLocked}
                showContact={showContact}
                // Contact autosave makes saveState="saving" while the user is still
                // typing; do not let that state disable its own input.
                contactDisabled={busy || resetting}
                onShowContact={setShowContact}
                onContactChange={handleContactChange}
                onRewrite={(target, mode, instruction) => void handleRewrite(target, mode, instruction)}
                onDecision={(decision) => void handleSuggestionDecision(decision)}
              />
            ) : (
              <ConversationPanel
                locale={locale}
                conversationLanguage={activeConversationLanguage}
                workspace={workspace}
                message={message}
                optimisticMessage={optimisticMessage}
                error={error}
                busy={busy || resetting}
                interactionLocked={saveState === "saving" || persistenceIsPending()}
                importing={importing}
                correcting={correcting}
                correction={correction}
                recentImport={recentImport}
                pendingImportFileName={pendingImportFile?.name ?? null}
                profileFacts={facts}
                importedFacts={importedFacts}
                selectedImportFactIds={selectedImportFactIds}
                busyImportSourceId={busyImportSourceId}
                importSourceNames={importSourceNames}
                showContact={showContact}
                onShowContact={setShowContact}
                onContactChange={handleContactChange}
                onMessageChange={setMessage}
                onSend={handleSend}
                onQuickAction={(content, action) => void performMessage(content, action)}
                onFile={(event) => void handleFile(event)}
                onConfirmImport={() => void handleConfirmImport()}
                onCancelImport={() => setPendingImportFile(null)}
                onToggleImportFact={handleToggleImportFact}
                onToggleImportSource={handleToggleImportSource}
                onBuildImportDraft={(sourceId, includeSelectedFacts) => void handleBuildImportDraft(sourceId, includeSelectedFacts)}
                onConfirm={() => void handleConfirmUnderstanding()}
                onStartCorrection={() => { setCorrection(workspace.pending_understanding?.understanding ?? ""); setCorrecting(true); }}
                onCancelCorrection={() => { setCorrection(""); setCorrecting(false); }}
                onCorrectionChange={setCorrection}
                onCorrect={() => void handleCorrectUnderstanding()}
              />
            )}
          </div>

          {workspace ? (
            <ProofingEvidenceRail
              locale={locale}
              workspace={workspace}
              facts={facts}
              className={cn("order-3 xl:order-none xl:block xl:[direction:rtl]", mobilePanel !== "resume" && "hidden xl:block")}
            />
          ) : null}
        </div>

        {workspace?.current_draft ? (
          <footer className="fixed inset-x-0 bottom-[72px] z-30 grid grid-cols-[0.9fr_1fr_1.35fr] border-y border-border bg-background/95 backdrop-blur-sm xl:relative xl:bottom-auto xl:z-50 xl:mt-3 xl:grid-cols-4 xl:bg-background xl:backdrop-blur-none" aria-label={locale === "ar" ? "إجراءات اعتماد السيرة" : "Resume approval actions"}>
            <label className="col-span-3 flex min-h-10 cursor-pointer items-center justify-center gap-2 border-b border-border px-3 text-xs font-semibold text-foreground xl:order-2 xl:col-span-1 xl:min-h-14 xl:border-b-0 xl:border-s">
              <input type="checkbox" className="h-5 w-5 accent-primary" checked={reviewAcknowledged} disabled={reviewing || resetting || saveState !== "saved"} onChange={(event) => void handleReviewChange(event.target.checked)} />
              {reviewing ? (locale === "ar" ? "جارٍ اعتماد المراجعة…" : "Confirming review…") : (locale === "ar" ? "راجعت المعلومات" : "I reviewed the information")}
            </label>
            <button type="button" className="inline-flex min-h-14 items-center justify-center gap-2 border-s border-border px-2 text-sm font-semibold text-foreground hover:text-primary-text xl:order-1" onClick={() => setMobilePanel("conversation")}><Pencil className="h-5 w-5" />{locale === "ar" ? "ملاحظات" : "Notes"}</button>
            <button type="button" className="inline-flex min-h-14 items-center justify-center gap-2 border-s border-border px-2 text-sm font-semibold text-foreground hover:text-primary-text disabled:opacity-45 xl:order-3" disabled={previewing || resetting || saveState === "saving"} onClick={() => void handlePreviewPdf()}>{previewing ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <FileDown className="h-5 w-5" />}{locale === "ar" ? "معاينة PDF" : "Preview PDF"}</button>
            <button type="button" className="inline-flex min-h-14 items-center justify-center gap-2 bg-primary px-3 text-base font-bold text-primary-foreground hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-45 xl:order-4" aria-label={locale === "ar" ? "تنزيل PDF" : "Download PDF"} disabled={!reviewAcknowledged || exporting || reviewing || resetting || saveState !== "saved"} onClick={() => void handleExport()}>{exporting ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Download className="h-5 w-5" />}{exporting ? (locale === "ar" ? "جارٍ التنزيل…" : "Downloading…") : (locale === "ar" ? "اعتماد وتحميل" : "Approve & download")}</button>
          </footer>
        ) : null}

        {error && isReview ? <p className="mt-2 text-xs text-danger" role="alert">{apiErrorMessage(error, locale)}</p> : null}
        {downloadNotice && visibleDownloadReady ? (
          <p className="mt-2 text-xs font-medium text-emerald" role="status">
            {locale === "ar" ? "تم تجهيز ملف PDF. إذا لم يبدأ تلقائيًا، " : "The PDF is ready. If it did not start automatically, "}
            {visibleDownloadReady ? (
              <a className="underline underline-offset-4" href={visibleDownloadReady.url} download={visibleDownloadReady.filename}>
                {locale === "ar" ? "نزّله من هنا" : "download it here"}
              </a>
            ) : null}
            .
          </p>
        ) : null}
      </div>
      {pdfPreviewUrl ? (
        <div className="fixed inset-0 z-[80] grid place-items-center bg-black/70 p-3 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="resume-pdf-preview-title">
          <section className="flex h-[92vh] w-full max-w-5xl flex-col border border-border bg-background shadow-2xl">
            <header className="flex min-h-14 flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
              <h2 id="resume-pdf-preview-title" className="font-bold text-foreground">{locale === "ar" ? "معاينة السيرة بصيغة PDF" : "Resume PDF preview"}</h2>
              <div className="flex items-center gap-2">
                <a className="inline-flex min-h-10 items-center gap-2 border border-primary px-3 text-sm font-semibold text-primary-text hover:bg-primary hover:text-primary-foreground" href={pdfPreviewUrl} download={pdfFilename}>
                  <Download className="h-4 w-4" aria-hidden="true" />
                  {locale === "ar" ? "تنزيل ملف PDF" : "Download PDF file"}
                </a>
                <button type="button" className="grid h-10 w-10 place-items-center border border-border text-foreground hover:border-primary hover:text-primary-text" aria-label={locale === "ar" ? "إغلاق معاينة PDF" : "Close PDF preview"} onClick={() => setPdfPreviewUrl(null)}><X className="h-5 w-5" /></button>
              </div>
            </header>
            <iframe className="min-h-0 flex-1 bg-white" src={pdfPreviewUrl} title={locale === "ar" ? "ملف السيرة بصيغة PDF" : "Resume PDF document"} />
          </section>
        </div>
      ) : null}
      {resetDialogOpen ? (
        <ResetWorkspaceDialog
          locale={locale}
          resetting={resetting}
          error={resetError}
          onCancel={closeResetDialog}
          onConfirm={() => void handleResetWorkspace()}
        />
      ) : null}
    </div>
  );
}
