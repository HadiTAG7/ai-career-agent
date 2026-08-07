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
  Globe2,
  History,
  Info,
  Lightbulb,
  LoaderCircle,
  Mail,
  MessageCircle,
  Paperclip,
  Pencil,
  Send,
  Sparkles,
  WandSparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  ResumeDocumentCanvas,
  type ResumeCanvasSelection,
} from "@/components/resume/resume-document-canvas";
import {
  apiErrorMessage,
  ApiHttpError,
  confirmCareerFact,
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
type QueuedDraftSave = { draft: ApiResumeDraftContent; generation: number };
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
  onLocaleChange: (locale: "ar" | "en") => void;
};

const MAX_FILE_BYTES = 10_000_000;

const coverageCopy: Record<string, { ar: string; en: string }> = {
  identity: { ar: "الهوية", en: "Identity" },
  experience: { ar: "الخبرة", en: "Experience" },
  education: { ar: "التعليم", en: "Education" },
  skill: { ar: "المهارات", en: "Skills" },
  project: { ar: "المشاريع", en: "Projects" },
  certification: { ar: "الشهادات", en: "Certifications" },
  language: { ar: "اللغات", en: "Languages" },
  achievement: { ar: "الإنجازات", en: "Achievements" },
};

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
    <div className="flex items-start gap-3">
      <span className="mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-emerald text-white shadow-sm" aria-hidden="true"><WandSparkles className="h-4.5 w-4.5" /></span>
      <div className="max-w-[88%] rounded-2xl rounded-tr-sm border border-slate-200 bg-white px-4 py-3 text-sm leading-7 text-ink shadow-[0_2px_8px_rgba(15,23,42,0.04)]">{children}</div>
    </div>
  );
}

function MessageBubble({ message }: { message: ApiResumeMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex items-start gap-3", isUser ? "flex-row-reverse" : "flex-row")}>
      <span className={cn("mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-full", isUser ? "border border-emerald/30 bg-white text-emerald" : "bg-emerald text-white")} aria-hidden="true">
        {isUser ? <CircleUserRound className="h-5 w-5" /> : <WandSparkles className="h-4.5 w-4.5" />}
      </span>
      <div className={cn(
        "max-w-[82%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-7",
        isUser ? "rounded-tl-sm border border-[#b8d7f8] bg-[#edf6ff] text-ink" : "rounded-tr-sm border border-slate-200 bg-white text-ink",
      )}>
        {message.content}
        <span className="mt-1 block text-[10px] leading-none text-slate-400">
          {new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(message.created_at))}
        </span>
      </div>
    </div>
  );
}

function ReadinessBar({ score, locale }: { score: number; locale: "ar" | "en" }) {
  return (
    <div className="flex items-center gap-3 text-sm" aria-label={locale === "ar" ? `جاهزية السيرة ${score}%` : `Resume readiness ${score}%`}>
      <strong className="whitespace-nowrap text-ink">{locale === "ar" ? "جاهزية السيرة" : "Resume readiness"} <span className="text-emerald">{score}%</span></strong>
      <span className="h-2 w-32 overflow-hidden rounded-full bg-slate-200 sm:w-40"><span className="block h-full rounded-full bg-emerald transition-[width] duration-500" style={{ width: `${score}%` }} /></span>
    </div>
  );
}

function StageRail({ current, locale }: { current: number; locale: "ar" | "en" }) {
  const stages = [stageCopy.understanding, stageCopy.writing, stageCopy.review];
  return (
    <ol className="flex items-center justify-center gap-2 sm:gap-5" aria-label={locale === "ar" ? "مراحل بناء السيرة" : "Resume-building stages"}>
      {stages.map((stage, index) => {
        const number = index + 1;
        const active = number === current;
        const complete = number < current;
        return (
          <li className="contents" key={stage.en}>
            {index ? <span className={cn("h-px w-7 sm:w-14", number <= current ? "bg-emerald" : "bg-slate-300")} aria-hidden="true" /> : null}
            <div className={cn("flex items-center gap-2 whitespace-nowrap text-xs sm:text-sm", active ? "font-bold text-ink" : "text-slate-500")}>
              <span className={cn("grid h-7 w-7 place-items-center rounded-full border text-xs", active || complete ? "border-emerald bg-emerald text-white" : "border-slate-300 bg-white text-slate-500")}>
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
  selectedLanguage,
  consentAccepted,
  starting,
  error,
  onLanguage,
  onConsent,
  onStart,
}: {
  locale: "ar" | "en";
  selectedLanguage: "ar" | "en";
  consentAccepted: boolean;
  starting: boolean;
  error: unknown;
  onLanguage: (language: "ar" | "en") => void;
  onConsent: (accepted: boolean) => void;
  onStart: () => void;
}) {
  return (
    <div className="flex h-full min-h-[560px] flex-col rounded-xl border border-slate-200 bg-white">
      <header className="border-b border-slate-200 px-5 py-4">
        <h2 className="font-bold text-ink">{locale === "ar" ? "محادثة بناء السيرة" : "Resume-building conversation"}</h2>
        <p className="mt-1 text-xs text-slate-500">{locale === "ar" ? "نبدأ باللغة ثم نفهم قصتك خطوة خطوة" : "Choose a language, then we will understand your story step by step"}</p>
      </header>
      <div className="flex-1 space-y-5 overflow-y-auto p-5">
        <AssistantBubble>
          <p>{locale === "ar" ? "أهلًا! قبل أن نبدأ، اختر لغة السيرة التي تريد بناءها." : "Welcome! Before we begin, choose the language for your resume."}</p>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <button type="button" className={cn("min-h-11 rounded-lg border px-3 font-semibold", selectedLanguage === "ar" ? "border-emerald bg-emerald-pale text-emerald-dark" : "border-slate-200 hover:border-emerald")} aria-pressed={selectedLanguage === "ar"} onClick={() => onLanguage("ar")}>العربية</button>
            <button type="button" className={cn("min-h-11 rounded-lg border px-3 font-semibold", selectedLanguage === "en" ? "border-emerald bg-emerald-pale text-emerald-dark" : "border-slate-200 hover:border-emerald")} aria-pressed={selectedLanguage === "en"} onClick={() => onLanguage("en")}>English</button>
          </div>
        </AssistantBubble>
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-emerald/25 bg-emerald-pale/60 p-4 text-xs leading-6 text-slate-600">
          <input type="checkbox" className="mt-1 h-5 w-5 shrink-0 accent-emerald" checked={consentAccepted} onChange={(event) => onConsent(event.target.checked)} />
          <span><strong className="block text-sm text-ink">{locale === "ar" ? "موافقة استخدام الذكاء الاصطناعي" : "AI-use acknowledgement"}</strong>{locale === "ar" ? "أوافق على إرسال إجاباتي المهنية والنص المستخرج بعد تنقيح بيانات التواصل. يُحفظ هذا الاختيار ولن نطلبه في كل سؤال." : "I agree to share my professional answers and redacted extracted text. This choice is saved and will not be requested for every question."}</span>
        </label>
        {error ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{apiErrorMessage(error, locale)}</p> : null}
      </div>
      <div className="border-t border-slate-200 p-4">
        <Button className="w-full" size="lg" disabled={!consentAccepted || starting} onClick={onStart}>
          {starting ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <MessageCircle className="h-5 w-5" />}
          {starting ? (locale === "ar" ? "جارٍ تجهيز المساحة…" : "Preparing workspace…") : (locale === "ar" ? "ابدأ المحادثة" : "Start conversation")}
        </Button>
      </div>
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
    <section className="flex h-full min-h-[560px] flex-col rounded-xl border border-slate-200 bg-white" aria-labelledby="resume-consent-renewal-title">
      <header className="border-b border-slate-200 px-5 py-4">
        <h2 id="resume-consent-renewal-title" className="font-bold text-ink">
          {locale === "ar" ? "جدّد موافقتك للمتابعة" : "Renew your consent to continue"}
        </h2>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          {locale === "ar"
            ? "تغيّرت شروط معالجة البيانات بالذكاء الاصطناعي، لذلك أوقفنا المحادثة والتحليل حتى توافق صراحةً على النسخة الحالية."
            : "The AI data-processing terms changed, so conversation and analysis are paused until you explicitly accept the current version."}
        </p>
      </header>
      <div className="flex-1 space-y-5 p-5">
        <div className="rounded-xl border border-amber/40 bg-[#fffdf7] p-4 text-sm leading-7 text-slate-600">
          <Info className="me-2 inline h-4 w-4 text-amber" aria-hidden="true" />
          {locale === "ar"
            ? "لن نرسل بيانات التواصل إلى مزود الذكاء الاصطناعي. لا يبدأ أي طلب جديد قبل تجديد هذه الموافقة."
            : "Contact details are not sent to the AI provider. No new request starts before you renew this consent."}
        </div>
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-emerald/25 bg-emerald-pale/60 p-4 text-xs leading-6 text-slate-600">
          <input
            type="checkbox"
            className="mt-1 h-5 w-5 shrink-0 accent-emerald"
            checked={accepted}
            onChange={(event) => onAcceptedChange(event.target.checked)}
          />
          <span>
            <strong className="block text-sm text-ink">
              {locale === "ar" ? "أوافق على النسخة الحالية" : "I accept the current version"}
            </strong>
            {locale === "ar"
              ? "أوافق على معالجة إجاباتي المهنية والنص المستخرج بعد تنقيح بيانات التواصل."
              : "I agree to process my professional answers and redacted extracted text."}
          </span>
        </label>
        {error ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{apiErrorMessage(error, locale)}</p> : null}
      </div>
      <div className="border-t border-slate-200 p-4">
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
    <section className="ms-12 rounded-xl border border-slate-200 bg-white p-4 shadow-[0_3px_12px_rgba(15,23,42,0.04)]" aria-labelledby="resume-understanding-title">
      <div className="flex items-center gap-2 text-emerald">
        <Sparkles className="h-4 w-4" aria-hidden="true" />
        <h3 id="resume-understanding-title" className="text-sm font-bold">{locale === "ar" ? "فهمت منك" : "What I understood"}</h3>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-ink">{understanding.understanding}</p>
      <p className="mt-2 text-xs text-slate-500">{understanding.understanding_detail?.confirmation_question ?? (locale === "ar" ? "هل فهمت كلامك بشكل صحيح؟" : "Did I understand you correctly?")}</p>
      {correcting ? (
        <div className="mt-4">
          <label className="sr-only" htmlFor="resume-understanding-correction">{locale === "ar" ? "صحح ما فهمه المساعد" : "Correct the assistant's understanding"}</label>
          <textarea id="resume-understanding-correction" className="field-control min-h-24 resize-y" value={correction} onChange={(event) => onCorrectionChange(event.target.value)} autoFocus />
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
    <div className="grid grid-cols-2 divide-x divide-x-reverse divide-slate-200 rounded-lg border border-slate-200 bg-slate-50 px-2 py-3 text-[11px] sm:grid-cols-4">
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
  onChange,
  onClose,
}: {
  locale: "ar" | "en";
  contact: ApiResumeWorkspace["contact"];
  onChange: (contact: ApiResumeWorkspace["contact"]) => void;
  onClose: () => void;
}) {
  return (
    <section className="absolute inset-x-4 top-[62px] z-20 rounded-xl border border-slate-200 bg-white p-4 shadow-xl" aria-label={locale === "ar" ? "بيانات التواصل" : "Contact details"}>
      <div className="flex items-start justify-between gap-4">
        <div><h3 className="font-bold text-ink">{locale === "ar" ? "بيانات التواصل في PDF" : "Contact details in the PDF"}</h3><p className="mt-1 text-xs text-slate-500">{locale === "ar" ? "لا تُرسل هذه الحقول إلى مزود الذكاء الاصطناعي." : "These fields are never sent to the AI provider."}</p></div>
        <button type="button" className="grid h-9 w-9 place-items-center rounded-lg hover:bg-slate-50" aria-label={locale === "ar" ? "إغلاق" : "Close"} onClick={onClose}><X className="h-4 w-4" /></button>
      </div>
      <div className="mt-4 grid gap-3">
        <input className="field-control" type="email" aria-label={locale === "ar" ? "البريد الإلكتروني" : "Email"} placeholder={locale === "ar" ? "البريد الإلكتروني" : "Email"} value={contact.email ?? ""} onChange={(event) => onChange({ ...contact, email: event.target.value })} />
        <input className="field-control" type="tel" aria-label={locale === "ar" ? "رقم الهاتف" : "Phone"} placeholder={locale === "ar" ? "رقم الهاتف" : "Phone"} value={contact.phone ?? ""} onChange={(event) => onChange({ ...contact, phone: event.target.value })} />
        <input className="field-control" type="url" aria-label="LinkedIn" placeholder="LinkedIn" value={contact.linkedin ?? ""} onChange={(event) => onChange({ ...contact, linkedin: event.target.value })} />
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
    <section className="ms-12 rounded-xl border border-emerald/25 bg-emerald-pale/45 p-4" aria-labelledby="resume-import-consent-title">
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white text-emerald shadow-sm" aria-hidden="true"><FileText className="h-4 w-4" /></span>
        <div className="min-w-0">
          <h3 id="resume-import-consent-title" className="font-bold text-ink">
            {locale === "ar" ? "حلّل هذا الملف بالذكاء الاصطناعي؟" : "Analyze this file with AI?"}
          </h3>
          <p className="mt-1 truncate text-xs font-semibold text-emerald-dark" dir="auto">{fileName}</p>
          <p className="mt-2 text-xs leading-6 text-slate-600">
            {locale === "ar"
              ? "عند المتابعة سيُرسل النص المهني المستخرج بعد تنقيح بيانات التواصل. ستراجع كل معلومة قبل اعتمادها."
              : "Continuing sends redacted professional text for analysis. You will review every extracted fact before it is confirmed."}
          </p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <Button disabled={importing} onClick={onConfirm}>
          {importing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
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

function ExtractedFactsReview({
  locale,
  facts,
  confirmingFactId,
  onConfirm,
}: {
  locale: "ar" | "en";
  facts?: ApiCareerFact[];
  confirmingFactId: string | null;
  onConfirm: (factId: string) => void;
}) {
  if (!facts?.length) return null;
  return (
    <section className="ms-12 rounded-xl border border-amber/50 bg-[#fffdf7] p-4" aria-labelledby="resume-import-facts-title">
      <div className="flex items-start gap-2">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber" aria-hidden="true" />
        <div>
          <h3 id="resume-import-facts-title" className="font-bold text-ink">
            {locale === "ar" ? "راجع المعلومات المستخرجة" : "Review extracted facts"}
          </h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            {locale === "ar"
              ? "هذه المعلومات من الملف الذي رفعته الآن ولم تُعتمد بعد. أكّد الصحيح منها واحدةً تلو الأخرى."
              : "These facts came from the file you just uploaded and are not confirmed yet. Confirm each accurate item explicitly."}
          </p>
        </div>
      </div>
      <div className="mt-4 space-y-3">
        {facts.map((fact) => {
          const category = coverageCopy[fact.category]?.[locale] ?? fact.category;
          const confirming = confirmingFactId === fact.id;
          return (
            <article className="rounded-lg border border-slate-200 bg-white p-3" key={fact.id}>
              <span className="text-[10px] font-bold uppercase tracking-wide text-emerald">{category}</span>
              <h4 className="mt-1 text-sm font-bold text-ink">{fact.label}</h4>
              {fact.detail ? <p className="mt-1 whitespace-pre-wrap text-xs leading-6 text-slate-600">{fact.detail}</p> : null}
              {fact.source_excerpt ? (
                <p className="mt-2 border-s border-slate-300 ps-2 text-[11px] leading-5 text-slate-500">
                  {locale === "ar" ? "من الملف: " : "From the file: "}{fact.source_excerpt}
                </p>
              ) : null}
              <Button className="mt-3 w-full" size="sm" disabled={Boolean(confirmingFactId)} onClick={() => onConfirm(fact.id)}>
                {confirming ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                {confirming
                  ? (locale === "ar" ? "جارٍ التأكيد…" : "Confirming…")
                  : (locale === "ar" ? "تأكيد هذه المعلومة" : "Confirm this fact")}
              </Button>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ConversationPanel({
  locale,
  workspace,
  message,
  error,
  busy,
  importing,
  correcting,
  correction,
  recentImportName,
  pendingImportFileName,
  importedFacts,
  confirmingFactId,
  showContact,
  onShowContact,
  onContactChange,
  onMessageChange,
  onSend,
  onQuickAction,
  onFile,
  onConfirmImport,
  onCancelImport,
  onConfirmFact,
  onConfirm,
  onStartCorrection,
  onCancelCorrection,
  onCorrectionChange,
  onCorrect,
}: {
  locale: "ar" | "en";
  workspace: ApiResumeWorkspace;
  message: string;
  error: unknown;
  busy: boolean;
  importing: boolean;
  correcting: boolean;
  correction: string;
  recentImportName: string | null;
  pendingImportFileName: string | null;
  importedFacts: ApiCareerFact[];
  confirmingFactId: string | null;
  showContact: boolean;
  onShowContact: (show: boolean) => void;
  onContactChange: (contact: ApiResumeWorkspace["contact"]) => void;
  onMessageChange: (message: string) => void;
  onSend: (event: FormEvent<HTMLFormElement>) => void;
  onQuickAction: (content: string, action?: ResumeQuickAction) => void;
  onFile: (event: ChangeEvent<HTMLInputElement>) => void;
  onConfirmImport: () => void;
  onCancelImport: () => void;
  onConfirmFact: (factId: string) => void;
  onConfirm: () => void;
  onStartCorrection: () => void;
  onCancelCorrection: () => void;
  onCorrectionChange: (value: string) => void;
  onCorrect: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  return (
    <section className="relative flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-[#fbfcfd]" aria-label={locale === "ar" ? "محادثة بناء السيرة" : "Resume-building conversation"}>
      <header className="flex min-h-[62px] items-center justify-between gap-3 border-b border-slate-200 bg-white px-5">
        <div><h2 className="font-bold text-ink">{locale === "ar" ? "المحادثة" : "Conversation"}</h2><p className="text-[11px] text-slate-500">{workspace.provider_ready ? (locale === "ar" ? "الذكاء الاصطناعي جاهز" : "AI is ready") : (locale === "ar" ? "الذكاء الاصطناعي غير جاهز" : "AI unavailable")}</p></div>
        <button type="button" className={cn("inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-xs font-semibold", showContact ? "border-emerald bg-emerald-pale text-emerald" : "border-slate-200 bg-white text-ink hover:border-emerald")} aria-expanded={showContact} onClick={() => onShowContact(!showContact)}><Mail className="h-4 w-4" />{locale === "ar" ? "التواصل" : "Contact"}</button>
      </header>
      {showContact ? <ContactPopover locale={locale} contact={workspace.contact} onChange={onContactChange} onClose={() => onShowContact(false)} /> : null}

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4 sm:p-5" aria-live="polite">
        {!workspace.messages.length ? (
          <AssistantBubble>
            <p>{locale === "ar" ? "جميل، خلّنا نبني سيرتك من قصتك الحقيقية. أرفق سيرة موجودة هنا، أو اكتب نبذة قصيرة عن آخر تجربة دراسية أو مهنية لك." : "Great—let's build your resume from your real story. Attach an existing resume here, or tell me briefly about your latest study or work experience."}</p>
          </AssistantBubble>
        ) : null}
        {recentImportName ? <div className="mx-auto flex w-fit items-center gap-2 rounded-full bg-emerald-pale px-3 py-1.5 text-xs font-semibold text-emerald-dark"><FileText className="h-3.5 w-3.5" />{locale === "ar" ? `تم استخراج معلومات من ${recentImportName}` : `Facts extracted from ${recentImportName}`}</div> : null}
        {pendingImportFileName ? (
          <ImportConsentCard
            locale={locale}
            fileName={pendingImportFileName}
            importing={importing}
            onConfirm={onConfirmImport}
            onCancel={onCancelImport}
          />
        ) : null}
        <ExtractedFactsReview locale={locale} facts={importedFacts} confirmingFactId={confirmingFactId} onConfirm={onConfirmFact} />
        {workspace.messages.filter((item) => item.status !== "failed").map((item) => <MessageBubble key={item.id} message={item} />)}
        <UnderstandingCard
          workspace={workspace}
          locale={locale}
          busy={busy}
          correcting={correcting}
          correction={correction}
          onCorrectionChange={onCorrectionChange}
          onConfirm={onConfirm}
          onStartCorrection={onStartCorrection}
          onCancelCorrection={onCancelCorrection}
          onCorrect={onCorrect}
        />
        {busy ? <div className="flex items-center gap-2 ps-12 text-xs text-slate-500" role="status"><LoaderCircle className="h-4 w-4 animate-spin text-emerald" />{locale === "ar" ? "المساعد يفهم إجابتك ويحدّث السيرة…" : "The assistant is understanding your answer and updating the resume…"}</div> : null}
        {error ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert"><AlertCircle className="me-2 inline h-4 w-4" />{apiErrorMessage(error, locale)}</p> : null}
      </div>

      <footer className="space-y-3 border-t border-slate-200 bg-white p-3 sm:p-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-emerald bg-emerald-pale px-2 text-[11px] font-semibold text-emerald-dark hover:bg-emerald hover:text-white" disabled={busy || Boolean(workspace.pending_understanding)} onClick={() => onQuickAction(locale === "ar" ? "اكتب سيرتي كاملة الآن اعتمادًا على المعلومات التي أكّدتها، من دون اختراع أي معلومة." : "Write my complete resume now using only the information I confirmed, without inventing anything.", "generate")}><WandSparkles className="h-4 w-4" />{locale === "ar" ? "اكتب السيرة الآن" : "Write resume now"}</button>
          <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 text-[11px] font-semibold text-ink hover:border-emerald hover:text-emerald" disabled={busy} onClick={() => onQuickAction(locale === "ar" ? "أعطني مثالًا" : "Give me an example", "show_example")}><Lightbulb className="h-4 w-4" />{locale === "ar" ? "أعطني مثالًا" : "Give an example"}</button>
          <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 text-[11px] font-semibold text-ink hover:border-emerald hover:text-emerald" disabled={busy} onClick={() => onQuickAction(locale === "ar" ? "ما عندي رقم دقيق" : "I do not have an exact metric", "no_exact_metric")}><Info className="h-4 w-4" />{locale === "ar" ? "ما عندي رقم دقيق" : "No exact metric"}</button>
          <button type="button" className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 text-[11px] font-semibold text-ink hover:border-emerald hover:text-emerald" disabled={busy} onClick={() => onQuickAction(locale === "ar" ? "تخطَّ هذا السؤال" : "Skip this question", "skip")}><ChevronDown className="h-4 w-4" />{locale === "ar" ? "تخطَّ هذا السؤال" : "Skip this question"}</button>
        </div>
        <CoverageStrip workspace={workspace} locale={locale} />
        <form className="grid grid-cols-[1fr_auto] gap-2" onSubmit={onSend}>
          <label className="sr-only" htmlFor="resume-workspace-message">{locale === "ar" ? "اكتب رسالتك" : "Write your message"}</label>
          <textarea id="resume-workspace-message" className="field-control min-h-[58px] resize-none py-3" placeholder={locale === "ar" ? "اكتب رسالتك هنا…" : "Write your message…"} value={message} disabled={busy || importing || Boolean(workspace.pending_understanding)} onChange={(event) => onMessageChange(event.target.value)} />
          <button type="submit" className="grid h-[58px] w-[58px] place-items-center self-start rounded-lg bg-emerald text-white transition hover:bg-emerald-dark disabled:cursor-not-allowed disabled:opacity-45" disabled={!message.trim() || busy || importing || Boolean(workspace.pending_understanding)} aria-label={locale === "ar" ? "إرسال الرسالة" : "Send message"}>{busy ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5 rtl:-scale-x-100" />}</button>
          <input ref={fileInputRef} className="sr-only" id="resume-workspace-file" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={busy || importing} onChange={onFile} />
          <button type="button" className="col-span-2 inline-flex min-h-10 w-fit items-center gap-2 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-600 hover:border-emerald hover:text-emerald disabled:opacity-50" disabled={busy || importing} onClick={() => fileInputRef.current?.click()}>
            {importing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
            {importing ? (locale === "ar" ? "جارٍ تحليل الملف…" : "Analyzing file…") : (locale === "ar" ? "إرفاق سيرة موجودة" : "Attach an existing resume")}
          </button>
        </form>
      </footer>
    </section>
  );
}

function ReadinessRing({ score }: { score: number }) {
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  return (
    <div className="relative h-24 w-24 shrink-0">
      <svg viewBox="0 0 96 96" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="48" cy="48" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="8" />
        <circle cx="48" cy="48" r={radius} fill="none" stroke="#07845c" strokeWidth="8" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset} />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-xl font-bold text-ink">{score}%</span>
    </div>
  );
}

function ReviewPanel({
  locale,
  workspace,
  versions,
  selection,
  busy,
  rewriting,
  onRewrite,
  onDecision,
  onRestore,
}: {
  locale: "ar" | "en";
  workspace: ApiResumeWorkspace;
  versions: ApiResumeDraftVersion[];
  selection: ResumeCanvasSelection | null;
  busy: boolean;
  rewriting: boolean;
  onRewrite: (selection: ResumeCanvasSelection, mode: ResumeRewriteMode, instruction?: string) => void;
  onDecision: (decision: "accept" | "reject") => void;
  onRestore: (versionId: string) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const suggestion = workspace.pending_suggestion;
  const coverage = Object.values(workspace.section_coverage);
  const completed = coverage.filter(Boolean).length;
  const allCovered = coverage.length > 0 && completed === coverage.length;

  function submitInstruction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selection || !instruction.trim()) return;
    onRewrite(selection, "custom", instruction);
    setInstruction("");
  }

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-[#fbfcfd]" aria-label={locale === "ar" ? "مراجعة السيرة" : "Resume review"}>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-ink">{locale === "ar" ? `راجعت السيرة: جاهزيتها ${workspace.readiness_score}%` : `Resume reviewed: ${workspace.readiness_score}% ready`}</h2>
              <ul className="mt-3 space-y-2 text-sm text-slate-600">
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald" />{locale === "ar" ? "الحقائق مرتبطة بمصادرها" : "Facts are linked to evidence"}</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald" />{locale === "ar" ? "تنسيق مناسب لأنظمة ATS" : "ATS-friendly formatting"}</li>
                <li className="flex items-center gap-2">{allCovered ? <CheckCircle2 className="h-4 w-4 text-emerald" /> : <span className="h-4 w-4 rounded-full bg-amber" />}{allCovered ? (locale === "ar" ? "الأقسام الأساسية مكتملة" : "Core sections complete") : (locale === "ar" ? "بقي تحسين واحد" : "One improvement remains")}</li>
              </ul>
            </div>
            <ReadinessRing score={workspace.readiness_score} />
          </div>
        </section>

        {suggestion ? (
          <section className="rounded-xl border border-amber/50 bg-[#fffdf7] p-4" aria-labelledby="resume-suggestion-title">
            <div className="flex items-start gap-2"><span className="mt-1 h-4 w-4 shrink-0 rounded-full bg-amber" /><h3 id="resume-suggestion-title" className="font-bold text-ink">{locale === "ar" ? "هذه الصياغة أوضح وأقوى" : "This wording is clearer and stronger"}</h3></div>
            <p className="mt-4 text-xs font-semibold text-slate-500">{locale === "ar" ? "النص الحالي" : "Current text"}</p>
            <p className="mt-1 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-600">{suggestion.before_text}</p>
            <p className="mt-4 text-xs font-semibold text-slate-500">{locale === "ar" ? "الصياغة المقترحة" : "Suggested wording"}</p>
            <p className="mt-1 rounded-lg border border-emerald/15 bg-emerald-pale p-3 text-sm leading-6 text-ink">{suggestion.after_text}</p>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <Button disabled={busy} onClick={() => onDecision("accept")}><Check className="h-4 w-4" />{locale === "ar" ? "اعتمد التحسين" : "Accept improvement"}</Button>
              <Button variant="secondary" disabled={busy} onClick={() => onDecision("reject")}><X className="h-4 w-4" />{locale === "ar" ? "احتفظ بالأصل" : "Keep original"}</Button>
            </div>
          </section>
        ) : (
          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h3 className="font-bold text-ink">{locale === "ar" ? "أوامر سريعة للنص المحدد" : "Quick actions for selected text"}</h3>
            <p className="mt-1 text-xs text-slate-500">{selection ? (locale === "ar" ? "اختر التحسين وسنعرضه قبل اعتماده." : "Choose an improvement and review it before applying.") : (locale === "ar" ? "اضغط على ملخص أو نقطة في السيرة أولًا." : "Select a summary or bullet in the resume first.")}</p>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {([
                ["stronger", locale === "ar" ? "قوّها" : "Strengthen"],
                ["professional", locale === "ar" ? "أكثر مهنية" : "Professional"],
                ["shorter", locale === "ar" ? "اختصرها" : "Shorten"],
                ["custom", locale === "ar" ? "اسألني" : "Ask me"],
              ] as const).map(([mode, label]) => <button type="button" key={mode} className="min-h-16 rounded-lg border border-slate-200 bg-white px-2 text-xs font-semibold text-ink hover:border-emerald hover:text-emerald disabled:opacity-45" disabled={!selection || rewriting} onClick={() => selection && onRewrite(selection, mode, mode === "custom" ? (locale === "ar" ? "اسألني سؤالًا واحدًا يساعدك على تحسين هذا النص." : "Ask me one question that will help you improve this text.") : undefined)}><WandSparkles className="mx-auto mb-1 h-4 w-4" />{label}</button>)}
            </div>
          </section>
        )}

        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2"><History className="h-4 w-4 text-emerald" /><h3 className="font-bold text-ink">{locale === "ar" ? "النسخ السابقة" : "Version history"}</h3></div>
          <div className="mt-3 divide-y divide-slate-200">
            {versions.slice(0, 4).map((version, index) => (
              <div className="flex min-h-11 items-center justify-between gap-3 text-xs" key={version.id}>
                <div><strong className="text-ink">{index === 0 ? (locale === "ar" ? "النسخة الحالية" : "Current version") : `${locale === "ar" ? "النسخة" : "Version"} ${version.version}`}</strong><span className="ms-2 text-slate-400">{new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "short" }).format(new Date(version.created_at))}</span></div>
                {index ? <button type="button" className="font-semibold text-emerald hover:underline disabled:opacity-50" disabled={busy} onClick={() => onRestore(version.id)}>{locale === "ar" ? "استعد" : "Restore"}</button> : <span className="text-emerald">{locale === "ar" ? "محفوظة" : "Saved"}</span>}
              </div>
            ))}
            {!versions.length ? <p className="py-3 text-xs text-slate-500">{locale === "ar" ? "ستظهر النسخ بعد أول حفظ للمسودة." : "Versions appear after the first draft save."}</p> : null}
          </div>
        </section>
      </div>

      <form className="grid grid-cols-[auto_1fr] gap-2 border-t border-slate-200 bg-white p-4" onSubmit={submitInstruction}>
        <button type="submit" className="grid h-12 w-12 place-items-center rounded-lg bg-emerald text-white disabled:opacity-45" disabled={!selection || !instruction.trim() || rewriting} aria-label={locale === "ar" ? "إرسال طلب التعديل" : "Send edit request"}>{rewriting ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5 rtl:-scale-x-100" />}</button>
        <input className="field-control" value={instruction} disabled={!selection || rewriting} onChange={(event) => setInstruction(event.target.value)} placeholder={selection ? (locale === "ar" ? "اكتب تعديلًا للذكاء…" : "Ask AI for an edit…") : (locale === "ar" ? "حدد نصًا من السيرة أولًا" : "Select text in the resume first")} />
      </form>
    </section>
  );
}

export function ResumeWorkspaceV2({
  locale,
  profile,
  initialFacts,
  initialWorkspace,
  onLocaleChange,
}: ResumeWorkspaceV2Props) {
  const [workspace, setWorkspace] = useState<ApiResumeWorkspace | null>(initialWorkspace);
  const [facts, setFacts] = useState(initialFacts);
  const [selectedLanguage, setSelectedLanguage] = useState<"ar" | "en">(initialWorkspace?.language ?? locale);
  const [consentAccepted, setConsentAccepted] = useState(
    initialWorkspace ? !initialWorkspace.consent_required : false,
  );
  const [renewConsentAccepted, setRenewConsentAccepted] = useState(false);
  const [starting, setStarting] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [rewriting, setRewriting] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(
    initialWorkspace?.stage === "complete",
  );
  const [error, setError] = useState<unknown>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [selection, setSelection] = useState<ResumeCanvasSelection | null>(null);
  const [correction, setCorrection] = useState("");
  const [correcting, setCorrecting] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("conversation");
  const [recentImportName, setRecentImportName] = useState<string | null>(null);
  const [pendingImportFile, setPendingImportFile] = useState<File | null>(null);
  const [importedFacts, setImportedFacts] = useState<ApiCareerFact[]>([]);
  const [confirmingFactId, setConfirmingFactId] = useState<string | null>(null);
  const [showContact, setShowContact] = useState(false);
  const [versions, setVersions] = useState<ApiResumeDraftVersion[]>(initialWorkspace?.versions ?? []);
  const workspaceRef = useRef(workspace);
  const saveTimerRef = useRef<number | null>(null);
  const contactTimerRef = useRef<number | null>(null);
  const draftSaveInFlightRef = useRef(false);
  const contactSaveInFlightRef = useRef(false);
  const queuedDraftSaveRef = useRef<QueuedDraftSave | null>(null);
  const draftEditGenerationRef = useRef(0);

  useEffect(() => {
    workspaceRef.current = workspace;
  }, [workspace]);

  useEffect(() => () => {
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    if (contactTimerRef.current) window.clearTimeout(contactTimerRef.current);
  }, []);

  const stageIndex = workspaceStageIndex(workspace);
  const isReview = Boolean(workspace && (
    workspace.stage === "review"
    || workspace.stage === "complete"
    || workspace.pending_suggestion
  ));
  const rewriteLocked = rewriting || saveState !== "saved";
  const displayedVersions = useMemo(
    () => [...versions].sort((a, b) => b.version - a.version),
    [versions],
  );

  function commitWorkspace(next: ApiResumeWorkspace | null) {
    workspaceRef.current = next;
    setWorkspace(next);
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

  async function refreshWorkspace() {
    const [freshWorkspace, freshFacts] = await Promise.all([
      getResumeWorkspace(profile.id),
      getCareerFacts(profile.id),
    ]);
    if (freshWorkspace) {
      commitWorkspace(freshWorkspace);
      setVersions(freshWorkspace.versions ?? []);
    }
    setFacts(freshFacts);
    return { workspace: freshWorkspace, facts: freshFacts };
  }

  async function handleStart() {
    if (!consentAccepted) return;
    setStarting(true);
    setError(null);
    try {
      const created = await startResumeWorkspace(profile.id, {
        language: selectedLanguage,
        dataSharingAcknowledged: true,
      });
      commitWorkspace(created);
      setVersions(created.versions ?? []);
      onLocaleChange(selectedLanguage);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setStarting(false);
    }
  }

  async function handleRenewConsent() {
    const current = workspaceRef.current;
    if (!current || !renewConsentAccepted) return;
    setStarting(true);
    setError(null);
    try {
      const renewed = await startResumeWorkspace(profile.id, {
        language: current.language,
        contact: {
          email: current.contact.email ?? undefined,
          phone: current.contact.phone ?? undefined,
          linkedin: current.contact.linkedin ?? undefined,
        },
        dataSharingAcknowledged: true,
      });
      commitWorkspace(renewed);
      setVersions(renewed.versions ?? []);
      setRenewConsentAccepted(false);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setStarting(false);
    }
  }

  async function performMessage(content: string, quickAction?: ResumeQuickAction) {
    const current = workspaceRef.current;
    const normalizedContent = content.trim();
    if (!current || (!normalizedContent && !quickAction)) return;
    setBusy(true);
    setError(null);
    try {
      const next = await sendResumeWorkspaceMessage(profile.id, {
        content: normalizedContent,
        clientTurnId: freshTurnId(),
        expectedRevision: current.revision,
        quickAction,
      });
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      setMessage("");
      setRecentImportName(null);
      if (next.current_draft && next.stage !== "understanding") setMobilePanel("resume");
    } catch (nextError) {
      if (nextError instanceof ApiHttpError && nextError.code === "resume_workspace_revision_conflict") {
        await refreshWorkspace().catch(() => undefined);
      }
      setError(nextError);
    } finally {
      setBusy(false);
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
    if (!supportsResume(file)) {
      setError(new Error(locale === "ar" ? "اختر ملف PDF أو DOCX فقط." : "Choose a PDF or DOCX file."));
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError(new Error(locale === "ar" ? "حجم الملف أكبر من 10 ميجابايت." : "The file is larger than 10 MB."));
      return;
    }
    setPendingImportFile(file);
    setRecentImportName(null);
    setImportedFacts([]);
  }

  async function handleConfirmImport() {
    const file = pendingImportFile;
    const current = workspaceRef.current;
    if (!file || !current || current.consent_required) return;
    setImporting(true);
    setError(null);
    try {
      const result = await importResumeWorkspaceFile(profile.id, file, {
        // This acknowledgement is sent only after the explicit confirmation above.
        dataSharingAcknowledged: true,
      });
      const currentImportIds = new Set(result.facts.map((fact) => fact.id));
      const refreshed = await refreshWorkspace();
      const refreshedById = new Map(refreshed.facts.map((fact) => [fact.id, fact]));
      setImportedFacts(
        result.facts
          .filter((fact) => currentImportIds.has(fact.id))
          .map((fact) => refreshedById.get(fact.id) ?? fact)
          .filter((fact) => fact.verification_status !== "confirmed"),
      );
      setRecentImportName(file.name);
      setPendingImportFile(null);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setImporting(false);
    }
  }

  async function handleConfirmImportedFact(factId: string) {
    if (!importedFacts.some((fact) => fact.id === factId)) return;
    setConfirmingFactId(factId);
    setError(null);
    try {
      await confirmCareerFact(profile.id, factId);
      setImportedFacts((currentFacts) => currentFacts.filter((fact) => fact.id !== factId));
      await refreshWorkspace();
    } catch (nextError) {
      setError(nextError);
    } finally {
      setConfirmingFactId(null);
    }
  }

  async function handleConfirmUnderstanding() {
    const current = workspaceRef.current;
    if (!current) return;
    const id = latestUnderstandingId(current);
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      const next = await confirmResumeUnderstanding(profile.id, id, current.revision);
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      setCorrecting(false);
      setCorrection("");
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  }

  async function handleCorrectUnderstanding() {
    const current = workspaceRef.current;
    if (!current || !correction.trim()) return;
    const id = latestUnderstandingId(current);
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      const next = await correctResumeUnderstanding(profile.id, id, {
        expectedRevision: current.revision,
        correctedText: correction,
      });
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      setCorrecting(false);
      setCorrection("");
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  }

  async function flushDraftSave() {
    if (draftSaveInFlightRef.current) return;
    const queuedSave = queuedDraftSaveRef.current;
    const current = workspaceRef.current;
    if (!queuedSave || !current) return;

    queuedDraftSaveRef.current = null;
    draftSaveInFlightRef.current = true;
    let succeeded = false;
    try {
      const saved = await patchResumeWorkspaceDraft(profile.id, {
        draft: queuedSave.draft,
        expectedDraftRevision: current.draft_revision,
      });
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
      setSaveState("error");
      setError(nextError);
    } finally {
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
    queuedDraftSaveRef.current = { draft: nextDraft, generation };
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
    commitWorkspace({ ...current, contact });
    setSaveState("saving");
    if (contactTimerRef.current) window.clearTimeout(contactTimerRef.current);
    contactTimerRef.current = window.setTimeout(async () => {
      contactTimerRef.current = null;
      const latest = workspaceRef.current;
      if (!latest) return;
      contactSaveInFlightRef.current = true;
      let succeeded = false;
      try {
        const saved = await startResumeWorkspace(profile.id, {
          language: latest.language,
          contact: {
            email: contact.email ?? undefined,
            phone: contact.phone ?? undefined,
            linkedin: contact.linkedin ?? undefined,
          },
          dataSharingAcknowledged: false,
        });
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
        setSaveState("error");
        setError(nextError);
      } finally {
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
      setMobilePanel("conversation");
    } catch (nextError) {
      setError(nextError);
    } finally {
      setRewriting(false);
    }
  }

  async function handleSuggestionDecision(decision: "accept" | "reject") {
    const current = workspaceRef.current;
    if (!current) return;
    const id = latestSuggestionId(current);
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      const next = await decideResumeRewriteSuggestion(profile.id, id, decision, current.draft_revision);
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      setReviewAcknowledged(false);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  }

  async function handleRestore(versionId: string) {
    const current = workspaceRef.current;
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      const next = await restoreResumeDraftVersion(profile.id, versionId, current.draft_revision);
      commitWorkspace(next);
      setVersions(next.versions ?? versions);
      setReviewAcknowledged(false);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  }

  async function loadVersions() {
    try {
      setVersions(await getResumeDraftVersions(profile.id));
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
    setReviewing(true);
    setError(null);
    try {
      const result = await reviewResumeWorkspace(profile.id, current.draft_revision);
      await refreshWorkspace();
      setReviewAcknowledged(result.export_allowed);
      await loadVersions();
    } catch (nextError) {
      setReviewAcknowledged(false);
      setError(nextError);
    } finally {
      setReviewing(false);
    }
  }

  async function handlePreviewPdf() {
    if (!workspace?.current_draft) return;
    setPreviewing(true);
    setError(null);
    try {
      const blob = await previewResumeWorkspacePdf(profile.id);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setPreviewing(false);
    }
  }

  async function handleExport() {
    const current = workspaceRef.current;
    if (!current?.current_draft || !reviewAcknowledged) return;
    setExporting(true);
    setError(null);
    try {
      const blob = await exportResumeWorkspacePdf(profile.id, current.draft_revision);
      saveBlob(blob, `${profile.full_name.trim() || "resume"}-resume.pdf`);
      commitWorkspace({ ...current, stage: "complete" });
    } catch (nextError) {
      setError(nextError);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#f7f8fa] px-3 pb-24 pt-5 sm:px-5 lg:px-6 lg:pb-5" dir={locale === "ar" ? "rtl" : "ltr"}>
      <div className="mx-auto max-w-[1500px]">
        <header className="relative pb-5">
          <div className="flex min-h-10 items-center justify-between gap-4">
            <div className={cn("inline-flex items-center gap-2 text-xs font-semibold", saveState === "error" ? "text-danger" : saveState === "saving" ? "text-amber" : "text-emerald-dark")} role="status">
              {saveState === "saving" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : saveState === "error" ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
              {saveState === "saving" ? (locale === "ar" ? "جارٍ الحفظ…" : "Saving…") : saveState === "error" ? (locale === "ar" ? "تعذر الحفظ" : "Save failed") : (locale === "ar" ? "تم الحفظ تلقائيًا" : "Autosaved")}
            </div>
            <ReadinessBar score={workspace?.readiness_score ?? 0} locale={locale} />
          </div>
          <h1 className="mt-1 text-center text-[26px] font-bold leading-tight tracking-[-0.025em] text-[#123b33] sm:text-[30px]">
            {isReview ? (locale === "ar" ? "راجع سيرتك قبل التنزيل" : "Review your resume before downloading") : (locale === "ar" ? "خلّنا نبني قصتك المهنية" : "Let’s build your professional story")}
          </h1>
          <div className="mt-4"><StageRail current={stageIndex} locale={locale} /></div>
        </header>

        <div className="mb-3 grid grid-cols-2 rounded-xl border border-slate-200 bg-white p-1 lg:hidden" role="tablist" aria-label={locale === "ar" ? "عرض مساحة السيرة" : "Resume workspace view"}>
          <button type="button" role="tab" aria-selected={mobilePanel === "conversation"} className={cn("min-h-11 rounded-lg text-sm font-semibold", mobilePanel === "conversation" ? "bg-emerald text-white" : "text-slate-600")} onClick={() => setMobilePanel("conversation")}><MessageCircle className="me-2 inline h-4 w-4" />{locale === "ar" ? "المحادثة" : "Conversation"}</button>
          <button type="button" role="tab" aria-selected={mobilePanel === "resume"} className={cn("min-h-11 rounded-lg text-sm font-semibold", mobilePanel === "resume" ? "bg-emerald text-white" : "text-slate-600")} onClick={() => setMobilePanel("resume")}><FileText className="me-2 inline h-4 w-4" />{locale === "ar" ? "السيرة" : "Resume"}</button>
        </div>

        <div className="grid min-h-[650px] gap-3 lg:h-[calc(100vh-225px)] lg:grid-cols-[minmax(0,1.18fr)_minmax(390px,0.82fr)] lg:[direction:ltr]">
          <div className={cn("min-h-0 lg:block lg:[direction:rtl]", mobilePanel !== "resume" && "hidden")}>
            <ResumeDocumentCanvas
              locale={locale}
              profile={profile}
              facts={facts}
              draft={workspace?.current_draft ?? null}
              contact={workspace?.contact ?? {}}
              editable={Boolean(workspace?.current_draft)}
              editingLocked={rewriting}
              selection={selection}
              rewriting={rewriteLocked}
              onSelect={setSelection}
              onDraftChange={handleDraftChange}
              onRewrite={(target, mode, instruction) => void handleRewrite(target, mode, instruction)}
            />
          </div>
          <div className={cn("min-h-0 lg:block lg:[direction:rtl]", mobilePanel !== "conversation" && "hidden")}>
            {!workspace ? (
              <SetupConversation
                locale={locale}
                selectedLanguage={selectedLanguage}
                consentAccepted={consentAccepted}
                starting={starting}
                error={error}
                onLanguage={(language) => { setSelectedLanguage(language); onLocaleChange(language); }}
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
                versions={displayedVersions}
                selection={selection}
                busy={busy}
                rewriting={rewriteLocked}
                onRewrite={(target, mode, instruction) => void handleRewrite(target, mode, instruction)}
                onDecision={(decision) => void handleSuggestionDecision(decision)}
                onRestore={(versionId) => void handleRestore(versionId)}
              />
            ) : (
              <ConversationPanel
                locale={locale}
                workspace={workspace}
                message={message}
                error={error}
                busy={busy}
                importing={importing}
                correcting={correcting}
                correction={correction}
                recentImportName={recentImportName}
                pendingImportFileName={pendingImportFile?.name ?? null}
                importedFacts={importedFacts}
                confirmingFactId={confirmingFactId}
                showContact={showContact}
                onShowContact={setShowContact}
                onContactChange={handleContactChange}
                onMessageChange={setMessage}
                onSend={handleSend}
                onQuickAction={(content, action) => void performMessage(content, action)}
                onFile={(event) => void handleFile(event)}
                onConfirmImport={() => void handleConfirmImport()}
                onCancelImport={() => setPendingImportFile(null)}
                onConfirmFact={(factId) => void handleConfirmImportedFact(factId)}
                onConfirm={() => void handleConfirmUnderstanding()}
                onStartCorrection={() => { setCorrection(workspace.pending_understanding?.understanding ?? ""); setCorrecting(true); }}
                onCancelCorrection={() => { setCorrection(""); setCorrecting(false); }}
                onCorrectionChange={setCorrection}
                onCorrect={() => void handleCorrectUnderstanding()}
              />
            )}
          </div>
        </div>

        {workspace?.current_draft ? (
          <footer className="mt-3 grid gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-[0_-4px_18px_rgba(15,23,42,0.04)] sm:grid-cols-[auto_auto_1fr_auto_auto] sm:items-center">
            <label className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-ink"><Globe2 className="h-4 w-4 text-emerald" /><select className="bg-transparent outline-none" aria-label={locale === "ar" ? "لغة السيرة" : "Resume language"} value={workspace.language} disabled><option value="ar">العربية</option><option value="en">English</option></select><ChevronDown className="h-3.5 w-3.5" /></label>
            <span className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-ink"><FileText className="h-4 w-4 text-emerald" />{locale === "ar" ? "قالب ATS الاحترافي" : "Professional ATS template"}</span>
            <label className="flex min-h-11 cursor-pointer items-center justify-center gap-2 text-xs font-semibold text-ink"><input type="checkbox" className="h-5 w-5 accent-emerald" checked={reviewAcknowledged} disabled={reviewing || saveState === "saving"} onChange={(event) => void handleReviewChange(event.target.checked)} />{reviewing ? (locale === "ar" ? "جارٍ اعتماد المراجعة…" : "Confirming review…") : (locale === "ar" ? "راجعت المعلومات" : "I reviewed the information")}</label>
            <Button variant="secondary" disabled={previewing || saveState === "saving"} onClick={() => void handlePreviewPdf()}>{previewing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}{locale === "ar" ? "معاينة PDF" : "Preview PDF"}</Button>
            <Button disabled={!reviewAcknowledged || exporting || reviewing || saveState !== "saved"} onClick={() => void handleExport()}>{exporting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}{exporting ? (locale === "ar" ? "جارٍ التنزيل…" : "Downloading…") : (locale === "ar" ? "تنزيل PDF" : "Download PDF")}</Button>
            <div className="sm:col-span-5 flex items-center justify-between border-t border-slate-100 pt-2 text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1.5"><Bookmark className="h-3.5 w-3.5" />{locale === "ar" ? "يمكنك الإغلاق والعودة لاحقًا؛ كل شيء محفوظ." : "You can close this and return later; everything is saved."}</span>
              {error && isReview ? <span className="text-danger">{apiErrorMessage(error, locale)}</span> : null}
            </div>
          </footer>
        ) : null}
      </div>
    </div>
  );
}
