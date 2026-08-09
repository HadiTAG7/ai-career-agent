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
  Send,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ResumeCanvasSelection } from "@/components/resume/resume-document-canvas";
import { ResumeProofingPaper } from "@/components/resume/resume-proofing-paper";
import {
  ProofingEvidenceRail,
  ProofingVersionRail,
} from "@/components/resume/resume-proofing-rails";
import {
  apiErrorMessage,
  ApiHttpError,
  buildResumeDraftFromImport,
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
type QueuedDraftSave = { draft: ApiResumeDraftContent; generation: number; operationEpoch: number };
type ResumeQuickAction =
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

const stageCopy = {
  understanding: { ar: "نفهم قصتك", en: "Understand your story" },
  writing: { ar: "نكتب السيرة", en: "Write the resume" },
  review: { ar: "نراجع وننزّل", en: "Review and download" },
} as const;

function freshTurnId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `resume-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function supportsResume(file: File) {
  const lower = file.name.toLocaleLowerCase("en");
  return lower.endsWith(".pdf") || lower.endsWith(".docx");
}

function workspaceStageIndex(workspace: ApiResumeWorkspace | null) {
  if (!workspace || workspace.stage === "understanding") return 1;
  if (workspace.stage === "writing" && !workspace.pending_suggestion) return 2;
  return 3;
}

function latestUnderstandingId(workspace: ApiResumeWorkspace) {
  if (workspace.pending_understanding?.id) return workspace.pending_understanding.id;
  return [...workspace.messages].reverse().find((message) => message.kind === "understanding" && message.status === "pending")?.id ?? null;
}

function latestSuggestionId(workspace: ApiResumeWorkspace) {
  if (workspace.pending_suggestion?.suggestion_id) return workspace.pending_suggestion.suggestion_id;
  return [...workspace.messages].reverse().find((message) => message.kind === "suggestion" && message.status === "pending")?.id ?? null;
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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

function MessageBubble({ message }: { message: ApiResumeMessage }) {
  const isUser = message.role === "user";
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
        <span className="mt-1 block text-[10px] leading-none text-muted" dir="auto">
          {new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(message.created_at))}
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
    <div className="flex items-center gap-3 text-sm" aria-label={locale === "ar" ? `جاهزية السيرة ${score}%` : `Resume readiness ${score}%`}>
      <strong className="whitespace-nowrap text-foreground">{locale === "ar" ? "جاهزية السيرة" : "Resume readiness"} <span className="text-emerald">{score}%</span></strong>
      <span className="h-2 w-24 overflow-hidden rounded-full bg-white/10 sm:w-36"><span className="block h-full rounded-full bg-emerald transition-[width] duration-500" style={{ width: `${score}%` }} /></span>
    </div>
  );
}

function StageRail({ current, locale }: { current: number; locale: "ar" | "en" }) {
  const stages = [stageCopy.understanding, stageCopy.writing, stageCopy.review];
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
    <div className="grid grid-cols-2 divide-x divide-x-reverse divide-border border-y border-border py-2 text-[10px] sm:grid-cols-4">
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

function ImportResultCard({
  locale,
  result,
  building,
  onBuild,
}: {
  locale: "ar" | "en";
  result: RecentImportState;
  building: boolean;
  onBuild: () => void;
}) {
  const reused = result.analysisStatus === "already_ai_analyzed";
  const canBuild = result.confirmedCount > 0;
  return (
    <section className="ms-10 border-s-2 border-emerald py-3 ps-4" aria-labelledby="resume-import-result-title">
      <div className="flex items-start gap-2">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" aria-hidden="true" />
        <div>
          <h3 id="resume-import-result-title" className="font-bold text-foreground">
            {reused
              ? (locale === "ar" ? "استعدنا تحليل هذا الملف" : "Previous analysis restored")
              : (locale === "ar" ? "اكتمل تحليل الملف" : "File analysis complete")}
          </h3>
          <p className="mt-1 text-xs leading-6 text-muted">
            {locale === "ar"
              ? `${result.fileName}: ${result.confirmedCount} معلومة مؤكدة، ${result.extractedCount} تحتاج مراجعة${result.rejectedCount ? `، و${result.rejectedCount} مستبعدة سابقًا` : ""}.`
              : `${result.fileName}: ${result.confirmedCount} confirmed, ${result.extractedCount} need review${result.rejectedCount ? `, and ${result.rejectedCount} previously rejected` : ""}.`}
          </p>
        </div>
      </div>
      {canBuild ? (
        <>
          {result.extractedCount > 0 ? (
            <p className="mt-3 text-xs leading-5 text-muted">
              {locale === "ar"
                ? "يمكنك إنشاء المسودة من المعلومات المؤكدة الآن، أو مراجعة المعلومات المتبقية وإضافتها أولًا."
                : "Create the draft from confirmed facts now, or review and add the remaining facts first."}
            </p>
          ) : null}
          <Button className="mt-4 w-full" disabled={building} onClick={onBuild}>
            {building ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
            {building
              ? (locale === "ar" ? "جارٍ إنشاء المسودة…" : "Creating draft…")
              : (locale === "ar" ? "إنشاء مسودة من هذا الملف" : "Create draft from this file")}
          </Button>
        </>
      ) : null}
      {!canBuild && result.extractedCount === 0 ? (
        <p className="mt-3 border border-amber/40 bg-amber/10 px-3 py-2 text-xs leading-5 text-foreground">
          {locale === "ar"
            ? "لا توجد معلومات مؤكدة قابلة للاستخدام من هذا الملف. عدّل المعلومات المستبعدة من الملف المهني أو ارفع نسخة محدّثة."
            : "This file has no confirmed usable facts. Edit rejected facts in your profile or upload an updated copy."}
        </p>
      ) : null}
    </section>
  );
}

function ExtractedFactsReview({
  locale,
  facts,
  selectedFactIds,
  busySourceId,
  sourceNames,
  onToggle,
  onToggleSource,
  onBuild,
}: {
  locale: "ar" | "en";
  facts?: ApiCareerFact[];
  selectedFactIds: string[];
  busySourceId: string | null;
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
              ? "راجع المعلومات وحدد الصحيح منها. سنعتمد المحدد دفعة واحدة ونبني منه مسودة كاملة؛ غير المحدد لن يدخل المسودة."
              : "Review and select the accurate facts. We will confirm them together and build a complete draft; unselected facts stay out."}
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
                            {fact.detail ? <p className="mt-2 whitespace-pre-wrap ps-7 text-xs leading-6 text-muted">{fact.detail}</p> : null}
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
              <Button className="mt-3 w-full" disabled={!selectedCount || Boolean(busySourceId)} onClick={() => onBuild(sourceId)}>
                {building ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                {building
                  ? (locale === "ar" ? "جارٍ اعتماد المعلومات وبناء المسودة…" : "Confirming facts and building draft…")
                  : (locale === "ar" ? "اعتماد المحدد وإنشاء المسودة" : "Confirm selected and create draft")}
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
  const controlsLocked = busy || interactionLocked;
  const importReviewLocked = Boolean(
    importing
    || pendingImportFileName
    || (!workspace.current_draft && importedFacts.length)
    || busyImportSourceId,
  );
  const conversationControlsLocked = controlsLocked || importReviewLocked;
  const attachmentLocked = conversationControlsLocked || Boolean(workspace.current_draft);

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [busy, optimisticMessage?.id, workspace.messages.length]);

  return (
    <section className="relative flex min-h-0 flex-col overflow-hidden border-y border-border xl:border-y-0" aria-label={locale === "ar" ? "محادثة بناء السيرة" : "Resume-building conversation"}>
      <header className="flex min-h-[62px] items-center justify-between gap-3 border-b border-border px-5">
        <div><div className="flex items-center gap-2 text-primary-text"><Pencil className="h-4 w-4" /><h2 className="font-bold">{locale === "ar" ? "ملاحظات المحرر" : "Editor notes"}</h2></div><p className="text-[11px] text-muted">{workspace.provider_ready ? (locale === "ar" ? "الذكاء الاصطناعي جاهز" : "AI is ready") : (locale === "ar" ? "الذكاء الاصطناعي غير جاهز" : "AI unavailable")}</p></div>
        <button type="button" className={cn("inline-flex min-h-10 items-center gap-2 border px-3 text-xs font-semibold", showContact ? "border-primary text-primary-text" : "border-border text-foreground hover:border-primary hover:text-primary-text")} aria-expanded={showContact} disabled={controlsLocked} onClick={() => onShowContact(!showContact)}><Mail className="h-4 w-4" />{locale === "ar" ? "التواصل" : "Contact"}</button>
      </header>
      {showContact ? <ContactPopover locale={locale} contact={workspace.contact} disabled={busy} onChange={onContactChange} onClose={() => onShowContact(false)} /> : null}

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-5" aria-live="polite">
        {!workspace.messages.length ? (
          <AssistantBubble>
            <p dir={conversationLanguage === "ar" ? "rtl" : "ltr"}>{conversationLanguage === "ar" ? "جميل، خلّنا نبني سيرتك من قصتك الحقيقية. أرفق سيرة موجودة هنا، أو اكتب نبذة قصيرة عن آخر تجربة دراسية أو مهنية لك." : "Great—let's build your resume from your real story. Attach an existing resume here, or tell me briefly about your latest study or work experience."}</p>
          </AssistantBubble>
        ) : null}
        {recentImport && !workspace.current_draft ? (
          <ImportResultCard
            locale={locale}
            result={recentImport}
            building={controlsLocked || busyImportSourceId === recentImport.sourceId}
            onBuild={() => onBuildImportDraft(recentImport.sourceId, false)}
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
          sourceNames={importSourceNames}
          onToggle={onToggleImportFact}
          onToggleSource={onToggleImportSource}
          onBuild={(sourceId) => onBuildImportDraft(sourceId, true)}
        />
        {workspace.messages.filter((item) => item.status !== "failed").map((item) => <MessageBubble key={item.id} message={item} />)}
        {optimisticMessage ? <MessageBubble message={optimisticMessage} /> : null}
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

      <footer className="space-y-3 border-t border-border p-3 sm:p-4">
        <div className="grid grid-cols-2 divide-x divide-x-reverse divide-border border-y border-border sm:grid-cols-4">
          <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 px-2 text-[11px] font-semibold text-primary-text hover:bg-primary hover:text-primary-foreground" disabled={conversationControlsLocked || Boolean(workspace.pending_understanding)} onClick={() => onQuickAction(conversationLanguage === "ar" ? "اكتب سيرتي كاملة الآن اعتمادًا على المعلومات التي أكّدتها، من دون اختراع أي معلومة." : "Write my complete resume now using only the information I confirmed, without inventing anything.", "generate")}><PencilLine className="h-4 w-4" />{locale === "ar" ? "اكتب السيرة الآن" : "Write resume now"}</button>
          <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 px-2 text-[11px] font-semibold text-foreground hover:text-primary-text" disabled={conversationControlsLocked} onClick={() => onQuickAction(conversationLanguage === "ar" ? "أعطني مثالًا" : "Give me an example", "show_example")}><Lightbulb className="h-4 w-4" />{locale === "ar" ? "أعطني مثالًا" : "Give an example"}</button>
          <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 border-t border-border px-2 text-[11px] font-semibold text-foreground hover:text-primary-text sm:border-t-0" disabled={conversationControlsLocked} onClick={() => onQuickAction(conversationLanguage === "ar" ? "ما عندي رقم دقيق" : "I do not have an exact metric", "no_exact_metric")}><Info className="h-4 w-4" />{locale === "ar" ? "ما عندي رقم دقيق" : "No exact metric"}</button>
          <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 border-t border-border px-2 text-[11px] font-semibold text-foreground hover:text-primary-text sm:border-t-0" disabled={conversationControlsLocked} onClick={() => onQuickAction(conversationLanguage === "ar" ? "تخطَّ هذا السؤال" : "Skip this question", "skip")}><ChevronDown className="h-4 w-4" />{locale === "ar" ? "تخطَّ هذا السؤال" : "Skip this question"}</button>
        </div>
        <CoverageStrip workspace={workspace} locale={locale} />
        <form className="grid grid-cols-[1fr_auto] border border-border" onSubmit={onSend}>
          <label className="sr-only" htmlFor="resume-workspace-message">{locale === "ar" ? "اكتب رسالتك" : "Write your message"}</label>
          <textarea id="resume-workspace-message" className="min-h-[58px] resize-none bg-transparent px-3 py-3 text-sm text-foreground placeholder:text-muted" dir="auto" placeholder={locale === "ar" ? "اكتب رسالتك هنا…" : "Write your message…"} value={message} disabled={conversationControlsLocked || Boolean(workspace.pending_understanding)} onChange={(event) => onMessageChange(event.target.value)} />
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
      </footer>
    </section>
  );
}

function ReviewPanel({
  locale,
  workspace,
  selection,
  busy,
  rewriting,
  onRewrite,
  onDecision,
}: {
  locale: "ar" | "en";
  workspace: ApiResumeWorkspace;
  selection: ResumeCanvasSelection | null;
  busy: boolean;
  rewriting: boolean;
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
    <section className="flex min-h-0 flex-col overflow-hidden border-y border-border xl:border-y-0" aria-label={locale === "ar" ? "مراجعة السيرة" : "Resume review"}>
      <header className="border-b border-border px-4 py-4 xl:px-5">
        <div className="flex items-center gap-2 text-primary-text">
          <Pencil className="h-4 w-4" aria-hidden="true" />
          <h2 className="text-sm font-bold">{locale === "ar" ? "ملاحظات التحرير الذكي" : "Editorial notes"}</h2>
        </div>
        <p className="mt-1 text-[11px] text-muted">{locale === "ar" ? "ملاحظات مبنية في الهامش مرتبطة بالنص" : "Margin notes connected to the text"}</p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 xl:px-5">
        {suggestion ? (
          <section className="relative border-s-2 border-primary ps-5" aria-labelledby="resume-suggestion-title">
            <span className="absolute -start-8 top-0 text-lg font-bold text-primary-text" aria-hidden="true">03</span>
            <h3 id="resume-suggestion-title" className="text-sm font-bold leading-6 text-primary-text">{locale === "ar" ? "حوّلنا الوصف إلى إنجاز قابل للقياس" : "Turned the description into a measurable achievement"}</h3>
            <p className="mt-1 inline-flex items-center gap-1.5 text-[11px] text-muted"><Bookmark className="h-3 w-3" aria-hidden="true" />{locale === "ar" ? "مرتبطة بفقرة النص" : "Linked to the selected passage"}</p>

            <div className="mt-5 grid grid-cols-2 divide-x divide-x-reverse divide-border text-xs leading-6">
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
              <p className="mt-1 text-xs leading-6 text-foreground">{locale === "ar" ? "صياغة أوضح تربط العمل بنتيجة قابلة للتحقق." : "Clearer wording that connects the work to a verifiable result."}</p>
            </div>

            <div className="mt-5 grid grid-cols-2 divide-x divide-x-reverse divide-border border-t border-border">
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
    initialWorkspace ? workspaceConversationLanguage(initialWorkspace) : "ar",
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
  const [exporting, setExporting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(
    initialWorkspace?.stage === "complete",
  );
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
  const queuedDraftSaveRef = useRef<QueuedDraftSave | null>(null);
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

  const stageIndex = workspaceStageIndex(workspace);
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

  function commitWorkspace(next: ApiResumeWorkspace | null) {
    workspaceRef.current = next;
    setWorkspace(next);
  }

  function operationIsCurrent(operationEpoch: number) {
    return operationEpochRef.current === operationEpoch;
  }

  function persistenceIsPending() {
    return Boolean(
      draftSaveInFlightRef.current
      || queuedDraftSaveRef.current
      || saveTimerRef.current
      || contactSaveInFlightRef.current
      || contactTimerRef.current,
    );
  }

  async function refreshWorkspace(operationEpoch = operationEpochRef.current) {
    const [freshWorkspace, freshFacts] = await Promise.all([
      getResumeWorkspace(profile.id),
      getCareerFacts(profile.id),
    ]);
    if (!operationIsCurrent(operationEpoch)) {
      return { workspace: null, facts: [] as ApiCareerFact[] };
    }
    if (freshWorkspace) {
      commitWorkspace(freshWorkspace);
      setVersions(freshWorkspace.versions ?? []);
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
      || saveState !== "saved"
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
      setOptimisticMessage(null);
      if (restoreMessageOnError) {
        setMessage((currentMessage) => currentMessage || normalizedContent);
      }
      if (nextError instanceof ApiHttpError && nextError.code === "resume_workspace_revision_conflict") {
        await refreshWorkspace(operationEpoch).catch(() => undefined);
      }
      if (operationIsCurrent(operationEpoch)) setError(nextError);
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
      if (
        result.analysis_status === "already_ai_analyzed"
        && confirmedCount > 0
        && extractedCount === 0
        && refreshed.workspace
        && !refreshed.workspace.current_draft
      ) {
        setBusyImportSourceId(result.source.id);
        const next = await buildResumeDraftFromImport(profile.id, {
          sourceId: result.source.id,
          clientRequestId: freshTurnId(),
          expectedRevision: refreshed.workspace.revision,
          expectedEvidenceRevision: refreshed.workspace.evidence_revision,
        });
        if (!operationIsCurrent(operationEpoch)) return;
        commitWorkspace(next);
        setVersions(next.versions ?? []);
        setRecentImport(null);
        setMobilePanel(next.current_draft ? "resume" : "conversation");
      }
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        const refreshed = await refreshWorkspace(operationEpoch).catch(() => null);
        const refreshedMetadata = refreshed?.workspace?.provider_metadata;
        const activeSourceId = typeof refreshedMetadata?.active_import_source_id === "string"
          ? refreshedMetadata.active_import_source_id
          : null;
        const requestCompleted = Boolean(
          analyzedSourceId
          && activeSourceId === analyzedSourceId
          && (
            refreshed?.workspace?.current_draft
            || refreshedMetadata?.draft_mode === "import_translation_required"
          ),
        );
        if (requestCompleted) {
          setError(null);
          setPendingImportFile(null);
          setImportedFacts([]);
          setSelectedImportFactIds([]);
          setRecentImport(null);
          setMobilePanel(refreshed?.workspace?.current_draft ? "resume" : "conversation");
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
      if (selectedFactIds.length) {
        const confirmation = await confirmCareerFactsBatch(profile.id, {
          sourceId,
          clientRequestId,
          factIds: selectedFactIds,
          expectedEvidenceRevision: evidenceRevision,
        });
        evidenceRevision = confirmation.evidence_revision;
        const confirmedById = new Map(confirmation.facts.map((fact) => [fact.id, fact]));
        setFacts((currentFacts) => currentFacts.map((fact) => confirmedById.get(fact.id) ?? fact));
      }
      if (!operationIsCurrent(operationEpoch)) return;
      const next = await buildResumeDraftFromImport(profile.id, {
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
      setMobilePanel(next.current_draft ? "resume" : "conversation");
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        const refreshed = await refreshWorkspace(operationEpoch).catch(() => null);
        if (refreshed && operationIsCurrent(operationEpoch)) {
          const refreshedMetadata = refreshed.workspace?.provider_metadata;
          const requestCompleted = Boolean(
            refreshedMetadata?.active_import_source_id === sourceId
            && (
              refreshed.workspace?.current_draft
              || refreshedMetadata?.draft_mode === "import_translation_required"
            ),
          );
          if (requestCompleted) {
            setError(null);
            setImportedFacts((currentFacts) => currentFacts.filter((fact) => fact.source_id !== sourceId));
            setSelectedImportFactIds((currentIds) => currentIds.filter((factId) => !sourcePendingFacts.some((fact) => fact.id === factId)));
            setRecentImport(null);
            setMobilePanel(refreshed.workspace?.current_draft ? "resume" : "conversation");
            return;
          }
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
      setCorrecting(false);
      setCorrection("");
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
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
      setCorrecting(false);
      setCorrection("");
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) setError(nextError);
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
        setSaveState("error");
        setError(nextError);
      }
    } finally {
      if (!operationIsCurrent(queuedSave.operationEpoch)) return;
      draftSaveInFlightRef.current = false;
      if (queuedDraftSaveRef.current) {
        setSaveState("saving");
        if (!saveTimerRef.current) void flushDraftSave();
      } else if (succeeded) {
        setSaveState(persistenceIsPending() ? "saving" : "saved");
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
    commitWorkspace({ ...current, current_draft: nextDraft });
    setReviewAcknowledged(false);
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

  function handleContactChange(contact: ApiResumeWorkspace["contact"]) {
    const current = workspaceRef.current;
    if (!current) return;
    const operationEpoch = operationEpochRef.current;
    commitWorkspace({ ...current, contact });
    setSaveState("saving");
    if (contactTimerRef.current) window.clearTimeout(contactTimerRef.current);
    contactTimerRef.current = window.setTimeout(async () => {
      contactTimerRef.current = null;
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
            consent_required: saved.consent_required,
            consent_version: saved.consent_version,
            consented_at: saved.consented_at,
            provider_ready: saved.provider_ready,
            provider: saved.provider,
            model: saved.model,
            provider_metadata: saved.provider_metadata,
            updated_at: saved.updated_at,
          });
        }
        succeeded = true;
      } catch (nextError) {
        if (operationIsCurrent(operationEpoch)) {
          setSaveState("error");
          setError(nextError);
        }
      } finally {
        if (!operationIsCurrent(operationEpoch)) return;
        contactSaveInFlightRef.current = false;
        if (succeeded) setSaveState(persistenceIsPending() ? "saving" : "saved");
      }
    }, 700);
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
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      setReviewAcknowledged(false);
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
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      setReviewAcknowledged(false);
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
      setReviewAcknowledged(false);
      return;
    }
    const operationEpoch = operationEpochRef.current;
    setReviewing(true);
    setError(null);
    try {
      const result = await reviewResumeWorkspace(profile.id, current.draft_revision);
      if (!operationIsCurrent(operationEpoch)) return;
      await refreshWorkspace(operationEpoch);
      if (!operationIsCurrent(operationEpoch)) return;
      setReviewAcknowledged(result.export_allowed);
      await loadVersions(operationEpoch);
    } catch (nextError) {
      if (operationIsCurrent(operationEpoch)) {
        setReviewAcknowledged(false);
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
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
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
    setError(null);
    try {
      const blob = await exportResumeWorkspacePdf(profile.id, current.draft_revision);
      if (!operationIsCurrent(operationEpoch)) return;
      saveBlob(blob, `${profile.full_name.trim() || "resume"}-resume.pdf`);
      commitWorkspace({ ...current, stage: "complete" });
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
    draftSaveInFlightRef.current = false;
    contactSaveInFlightRef.current = false;
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
          <div className="grid items-end gap-3 xl:grid-cols-[minmax(220px,1fr)_minmax(300px,1fr)_minmax(220px,1fr)]">
            <div className="order-2 flex items-center justify-center xl:order-1 xl:justify-start">
              <div>
                <ReadinessBar score={workspace?.readiness_score ?? 0} locale={locale} />
                <p className="mt-1 text-[11px] text-muted">
                  {workspace
                    ? (locale === "ar" ? "الحقائق المؤكدة مرتبطة بالمسودة" : "Confirmed facts are linked to the draft")
                    : (locale === "ar" ? "ابدأ من قصتك المهنية" : "Start with your professional story")}
                </p>
              </div>
            </div>

            <div className="order-1 text-center xl:order-2">
              <div className="inline-flex items-center justify-center gap-3">
                <Pencil className="hidden h-8 w-8 text-primary-text sm:block" strokeWidth={1.25} aria-hidden="true" />
                <div>
                  <h1 className="text-[28px] font-bold leading-tight tracking-[-0.025em] text-foreground sm:text-[31px]">
                    {hasDraft
                      ? (locale === "ar" ? "مختبر تحرير السيرة" : "Resume Proofing Studio")
                      : (locale === "ar" ? "خلّنا نبني قصتك المهنية" : "Let’s build your professional story")}
                  </h1>
                  <p className="mt-1 text-xs text-muted">{locale === "ar" ? "استوديو التحرير والتحقق قبل الاعتماد" : "Edit and verify before approval"}</p>
                </div>
              </div>
            </div>

            <div className="order-3 flex flex-wrap items-center justify-center gap-x-3 gap-y-2 xl:justify-end">
              <div className={cn("inline-flex items-center gap-2 text-xs font-semibold", saveState === "error" ? "text-danger" : saveState === "saving" ? "text-primary-text" : "text-emerald")} role="status">
                {saveState === "saving" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : saveState === "error" ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                {saveState === "saving" ? (locale === "ar" ? "جارٍ الحفظ…" : "Saving…") : saveState === "error" ? (locale === "ar" ? "تعذر الحفظ" : "Save failed") : (locale === "ar" ? "تم الحفظ تلقائيًا" : "Autosaved")}
              </div>
              {workspace ? (
                <>
                  <span className="hidden h-5 w-px bg-border sm:block" aria-hidden="true" />
                  <span className="text-xs font-semibold text-primary-text">
                    {locale === "ar" ? "الحوار" : "Chat"} {activeConversationLanguage.toUpperCase()} · {locale === "ar" ? "السيرة" : "Resume"} {activeOutputLanguage.toUpperCase()}
                  </span>
                  <button
                    type="button"
                    className="inline-flex min-h-9 items-center gap-1.5 border-s border-danger ps-3 text-xs font-semibold text-danger hover:text-danger/80 disabled:cursor-not-allowed disabled:opacity-45"
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
          <div className={cn("mx-auto mt-3 max-w-xl", hasDraft && "hidden xl:block")}><StageRail current={stageIndex} locale={locale} /></div>
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
            !isReview && mobilePanel !== "conversation" && "hidden xl:block",
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
                interactionLocked={saveState !== "saved" || persistenceIsPending()}
                importing={importing}
                correcting={correcting}
                correction={correction}
                recentImport={recentImport}
                pendingImportFileName={pendingImportFile?.name ?? null}
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
          <footer className="fixed inset-x-0 bottom-[72px] z-30 grid grid-cols-[0.9fr_1fr_1.35fr] border-y border-border bg-background/95 backdrop-blur-sm xl:static xl:z-auto xl:mt-3 xl:grid-cols-4 xl:bg-transparent xl:backdrop-blur-none" aria-label={locale === "ar" ? "إجراءات اعتماد السيرة" : "Resume approval actions"}>
            <label className="col-span-3 flex min-h-10 cursor-pointer items-center justify-center gap-2 border-b border-border px-3 text-xs font-semibold text-foreground xl:order-2 xl:col-span-1 xl:min-h-14 xl:border-b-0 xl:border-s">
              <input type="checkbox" className="h-5 w-5 accent-primary" checked={reviewAcknowledged} disabled={reviewing || resetting || saveState === "saving"} onChange={(event) => void handleReviewChange(event.target.checked)} />
              {reviewing ? (locale === "ar" ? "جارٍ اعتماد المراجعة…" : "Confirming review…") : (locale === "ar" ? "راجعت المعلومات" : "I reviewed the information")}
            </label>
            <button type="button" className="inline-flex min-h-14 items-center justify-center gap-2 border-s border-border px-2 text-sm font-semibold text-foreground hover:text-primary-text xl:order-1" onClick={() => setMobilePanel("conversation")}><Pencil className="h-5 w-5" />{locale === "ar" ? "ملاحظات" : "Notes"}</button>
            <button type="button" className="inline-flex min-h-14 items-center justify-center gap-2 border-s border-border px-2 text-sm font-semibold text-foreground hover:text-primary-text disabled:opacity-45 xl:order-3" disabled={previewing || resetting || saveState === "saving"} onClick={() => void handlePreviewPdf()}>{previewing ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <FileDown className="h-5 w-5" />}{locale === "ar" ? "معاينة PDF" : "Preview PDF"}</button>
            <button type="button" className="inline-flex min-h-14 items-center justify-center gap-2 bg-primary px-3 text-base font-bold text-primary-foreground hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-45 xl:order-4" aria-label={locale === "ar" ? "تنزيل PDF" : "Download PDF"} disabled={!reviewAcknowledged || exporting || reviewing || resetting || saveState !== "saved"} onClick={() => void handleExport()}>{exporting ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Download className="h-5 w-5" />}{exporting ? (locale === "ar" ? "جارٍ التنزيل…" : "Downloading…") : (locale === "ar" ? "اعتماد وتحميل" : "Approve & download")}</button>
          </footer>
        ) : null}

        {error && isReview ? <p className="mt-2 text-xs text-danger" role="alert">{apiErrorMessage(error, locale)}</p> : null}
      </div>
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
