"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  FileText,
  FileUp,
  LoaderCircle,
  LockKeyhole,
  PenLine,
  RotateCcw,
  ServerOff,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  GuidedResumeInterview,
  type GuidedResumeAnswers,
} from "@/components/resume/guided-resume-interview";
import { ResumeAiWorkspace } from "@/components/resume/resume-ai-workspace";
import {
  apiConfiguration,
  apiErrorMessage,
  ApiHttpError,
  createCareerProfile,
  createResumeDraft,
  getCareerFacts,
  getCareerPathWorkspace,
  getCareerProfile,
  importCareerFile,
  type ApiCareerFact,
  type ApiCareerProfile,
  type ApiImportResult,
} from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import type { CareerPathWorkspace } from "@/lib/types";
import { cn } from "@/lib/utils";

type StartMode = "upload" | "create";
type LoadState = "loading" | "ready" | "error";

const MAX_FILE_BYTES = 10_000_000;
const categoryCopy: Record<string, { ar: string; en: string }> = {
  identity: { ar: "الهوية المهنية", en: "Professional identity" },
  experience: { ar: "الخبرات", en: "Experience" },
  education: { ar: "التعليم", en: "Education" },
  skill: { ar: "المهارات", en: "Skills" },
  project: { ar: "المشاريع", en: "Projects" },
  certification: { ar: "الشهادات", en: "Certifications" },
  language: { ar: "اللغات", en: "Languages" },
  achievement: { ar: "الإنجازات", en: "Achievements" },
  preference: { ar: "التفضيلات", en: "Preferences" },
  eligibility: { ar: "أهلية العمل", en: "Work eligibility" },
};

function isSupportedResume(file: File) {
  const name = file.name.toLocaleLowerCase("en");
  return name.endsWith(".pdf") || name.endsWith(".docx");
}

function formatFileSize(bytes: number, locale: "ar" | "en") {
  return new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en", {
    maximumFractionDigits: 1,
  }).format(bytes / 1_000_000);
}

function FactReviewItem({ fact, locale }: { fact: ApiCareerFact; locale: "ar" | "en" }) {
  const detail = fact.detail || fact.source_excerpt;
  const category = categoryCopy[fact.category]?.[locale] ?? fact.category;

  return (
    <li className="border-b border-border py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-emerald">{category}</span>
        <span className="rounded-full bg-amber-pale px-2.5 py-1 text-xs font-semibold text-amber">
          {locale === "ar" ? "بحاجة إلى مراجعة" : "Needs review"}
        </span>
      </div>
      <h3 className="mt-2 font-bold text-ink">{fact.label}</h3>
      {detail ? <p className="mt-1 whitespace-pre-wrap text-sm text-muted">{detail}</p> : null}
    </li>
  );
}

export function ResumePreparation() {
  const { locale } = useLocale();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [profile, setProfile] = useState<ApiCareerProfile | null>(null);
  const [workspace, setWorkspace] = useState<CareerPathWorkspace | null>(null);
  const [facts, setFacts] = useState<ApiCareerFact[]>([]);
  const [creatingProfile, setCreatingProfile] = useState(false);
  const [profileError, setProfileError] = useState<unknown>(null);
  const [mode, setMode] = useState<StartMode>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [draft, setDraft] = useState("");
  const [guidedAnswers, setGuidedAnswers] = useState<GuidedResumeAnswers | null>(null);
  const [consentAcknowledged, setConsentAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [result, setResult] = useState<ApiImportResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!apiConfiguration.baseUrl) return;
    let active = true;

    async function load() {
      try {
        const existingProfile = await getCareerProfile();
        if (!active) return;
        setProfile(existingProfile);
        if (existingProfile) {
          const [providerWorkspace, profileFacts] = await Promise.all([
            getCareerPathWorkspace(),
            getCareerFacts(existingProfile.id),
          ]);
          if (!active) return;
          setWorkspace(providerWorkspace);
          setFacts(profileFacts);
        }
        setLoadState("ready");
      } catch (error) {
        if (!active) return;
        setLoadError(error);
        setLoadState("error");
      }
    }

    void load();
    return () => { active = false; };
  }, [retryKey]);

  function retryLoad() {
    setLoadError(null);
    setWorkspace(null);
    setLoadState("loading");
    setRetryKey((value) => value + 1);
  }

  async function handleCreateProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const fullName = String(form.get("fullName") ?? "").trim();
    const city = String(form.get("city") ?? "").trim();
    if (!fullName) return;

    setCreatingProfile(true);
    setProfileError(null);
    try {
      const createdProfile = await createCareerProfile({
        fullName,
        city,
        preferredLanguage: locale,
      });
      setProfile(createdProfile);
      setFacts([]);
      try {
        setWorkspace(await getCareerPathWorkspace());
      } catch (error) {
        setLoadError(error);
        setLoadState("error");
      }
    } catch (error) {
      setProfileError(error);
    } finally {
      setCreatingProfile(false);
    }
  }

  function chooseMode(nextMode: StartMode) {
    setMode(nextMode);
    setSubmitError(null);
    setResult(null);
    setConsentAcknowledged(false);
    setDraft("");
    setGuidedAnswers(null);
  }

  function handleFileSelected(selectedFile: File | undefined) {
    setSubmitError(null);
    setResult(null);
    if (!selectedFile) {
      setFile(null);
      return;
    }
    if (!isSupportedResume(selectedFile)) {
      setFile(null);
      setSubmitError(locale === "ar" ? "نوع الملف غير مدعوم. اختر ملف PDF أو DOCX فقط." : "Unsupported file type. Choose a PDF or DOCX file.");
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    if (selectedFile.size > MAX_FILE_BYTES) {
      setFile(null);
      setSubmitError(locale === "ar" ? "حجم الملف أكبر من 10 ميجابايت." : "The file is larger than 10 MB.");
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setFile(selectedFile);
  }

  const providerReady = Boolean(workspace?.provider_ready);
  const draftReady = Boolean(guidedAnswers && draft.trim());
  const providerName = workspace?.provider ?? (locale === "ar" ? "الذكاء الاصطناعي" : "the AI provider");
  const dataSharingCopy = locale === "ar"
    ? mode === "upload"
      ? `أوافق على إرسال النص المستخرج محليًا من الملف إلى مزود ${providerName} بعد تنقيح البريد الإلكتروني ورقم الهاتف ورقم الهوية وIBAN. لا يُرسل ملف PDF أو DOCX نفسه إلى المزود. هذه الموافقة تخص هذه العملية فقط ولا تفعّل موافقة مستشار المسار.`
      : `أوافق على إرسال إجابات المقابلة المهنية إلى مزود ${providerName} بعد تنقيح البريد الإلكتروني ورقم الهاتف ورقم الهوية وIBAN. بيانات التواصل الاختيارية المخصصة للمعاينة لا تدخل في النص المرسل. هذه الموافقة تخص هذه العملية فقط ولا تفعّل موافقة مستشار المسار.`
    : mode === "upload"
      ? `I agree to send locally extracted text to ${providerName} after email addresses, phone numbers, national IDs, and IBANs are redacted. The PDF or DOCX file itself is not sent to the provider. This consent applies only to this action and does not enable path-adviser consent.`
      : `I agree to send my career-interview answers to ${providerName} after email addresses, phone numbers, national IDs, and IBANs are redacted. Optional preview contact details are excluded from the text sent. This consent applies only to this action and does not enable path-adviser consent.`;
  const canSubmit = providerReady
    && consentAcknowledged
    && !submitting
    && (mode === "upload" ? Boolean(file) : draftReady);
  const duplicateImportError = submitError instanceof ApiHttpError
    && submitError.code === "resume_content_duplicate";
  const resultAnalysisStatus = result?.analysis_status ?? "created";
  const hasNewReviewFacts = Boolean(result?.facts.length)
    && resultAnalysisStatus !== "already_ai_analyzed";
  const factsLinkHref = hasNewReviewFacts
    ? "/profile?status=review#facts-title"
    : "/profile#facts-title";

  async function handleAiSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile || !workspace || !canSubmit) return;

    setSubmitting(true);
    setSubmitError(null);
    try {
      const nextResult = mode === "upload" && file
        ? await importCareerFile(profile.id, file, { useAi: true, dataSharingAcknowledged: true })
        : await createResumeDraft(profile.id, {
          content: draft.trim(),
          dataSharingAcknowledged: true,
        });
      setResult(nextResult);
      setFacts(await getCareerFacts(profile.id));
      setConsentAcknowledged(false);
      if (mode === "upload") {
        setFile(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    } catch (error) {
      setSubmitError(error);
    } finally {
      setSubmitting(false);
    }
  }

  const pageHeader = (
    <header>
      <h1 className="page-title">{locale === "ar" ? "ابدأ بسيرتك، ثم حدّد مسارك" : "Start with your resume, then choose your path"}</h1>
      <p className="mt-2 max-w-3xl text-base text-muted">
        {locale === "ar"
          ? "ارفع سيرتك الحالية أو اكتب معلوماتك من الصفر. يفهم المساعد معلوماتك، يسألك عن النواقص، ثم يكتب سيرة احترافية قابلة للتعديل والتنزيل بصيغة PDF."
          : "Upload your current resume or describe your background from scratch. The assistant understands your information, asks about gaps, then writes an editable professional resume you can download as a PDF."}
      </p>
    </header>
  );

  if (!apiConfiguration.baseUrl) {
    return (
      <div className="page-wrap page-enter max-w-[1080px]">
        {pageHeader}
        <section className="mt-8 rounded-xl border border-amber bg-amber-pale p-6" role="alert">
          <ServerOff className="h-8 w-8 text-amber" aria-hidden="true" />
          <h2 className="mt-4 text-xl font-bold">{locale === "ar" ? "تجهيز السيرة يحتاج اتصال الخادم" : "Resume preparation needs a server connection"}</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            {locale === "ar" ? "اربط الواجهة بخادم API أولًا. لن نعرض تحليلًا أو حقائق تجريبية بدلًا من بياناتك." : "Connect the interface to the API server first. No demo analysis or facts will replace your data."}
          </p>
        </section>
      </div>
    );
  }

  if (loadState === "loading") {
    return (
      <div className="page-wrap page-enter max-w-[1080px]">
        {pageHeader}
        <div className="mt-8 flex min-h-64 items-center justify-center gap-3 rounded-xl border border-border text-sm text-muted" role="status">
          <LoaderCircle className="h-5 w-5 animate-spin text-emerald" aria-hidden="true" />
          {locale === "ar" ? "جارٍ تجهيز مساحة السيرة…" : "Preparing your resume workspace…"}
        </div>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="page-wrap page-enter max-w-[1080px]">
        {pageHeader}
        <section className="mt-8 rounded-xl border border-danger bg-danger-pale p-6" role="alert">
          <AlertCircle className="h-8 w-8 text-danger" aria-hidden="true" />
          <h2 className="mt-4 text-xl font-bold">{locale === "ar" ? "تعذر تحميل مساحة السيرة" : "Could not load the resume workspace"}</h2>
          <p className="mt-2 text-sm text-muted">{apiErrorMessage(loadError, locale)}</p>
          <Button variant="secondary" className="mt-4" onClick={retryLoad}>
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            {locale === "ar" ? "إعادة المحاولة" : "Try again"}
          </Button>
        </section>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="page-wrap page-enter max-w-[1080px]">
        {pageHeader}
        <section className="mt-8 max-w-2xl rounded-xl border border-border bg-white p-6 shadow-subtle" aria-labelledby="resume-profile-title">
          <h2 id="resume-profile-title" className="section-title">{locale === "ar" ? "أنشئ ملفك الأساسي أولًا" : "Create your basic profile first"}</h2>
          <p className="mt-2 text-sm text-muted">{locale === "ar" ? "نحتاج اسمك ولغتك لربط السيرة والحقائق بحسابك. هذه البيانات لا تُرسل إلى مزود الذكاء في هذه الخطوة." : "We need your name and language to attach the resume and facts to your account. This step does not send data to the AI provider."}</p>
          <form className="mt-6 grid gap-5" onSubmit={handleCreateProfile} aria-busy={creatingProfile}>
            <div>
              <label className="field-label" htmlFor="resume-profile-name">{locale === "ar" ? "الاسم الكامل" : "Full name"}</label>
              <input id="resume-profile-name" name="fullName" className="field-control" required maxLength={200} autoComplete="name" disabled={creatingProfile} />
            </div>
            <div>
              <label className="field-label" htmlFor="resume-profile-city">{locale === "ar" ? "المدينة (اختياري)" : "City (optional)"}</label>
              <input id="resume-profile-city" name="city" className="field-control" maxLength={120} autoComplete="address-level2" disabled={creatingProfile} />
            </div>
            {profileError ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{apiErrorMessage(profileError, locale)}</p> : null}
            <Button type="submit" size="lg" className="justify-self-start" disabled={creatingProfile}>
              {creatingProfile ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" /> : <ArrowLeft className="h-5 w-5 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />}
              {creatingProfile ? (locale === "ar" ? "جارٍ الإنشاء…" : "Creating…") : (locale === "ar" ? "إنشاء الملف والمتابعة" : "Create profile and continue")}
            </Button>
          </form>
        </section>
      </div>
    );
  }

  return (
    <div className="page-wrap page-enter max-w-[1180px]">
      {pageHeader}

      <ol className="mt-7 grid gap-3 sm:grid-cols-2" aria-label={locale === "ar" ? "خطوات بدء البرنامج" : "Getting-started steps"}>
        <li className="flex items-center gap-3 border-b-2 border-emerald pb-3">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-emerald text-sm font-bold text-white">1</span>
          <div><strong className="block text-sm">{locale === "ar" ? "السيرة والحقائق" : "Resume and facts"}</strong><span className="text-xs text-muted">{locale === "ar" ? "الخطوة الحالية" : "Current step"}</span></div>
        </li>
        <li className="flex items-center gap-3 border-b-2 border-border pb-3 text-muted">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-border text-sm font-bold">2</span>
          <div><strong className="block text-sm text-ink">{locale === "ar" ? "تحديد المسار" : "Choose your path"}</strong><span className="text-xs">{locale === "ar" ? "بعد مراجعة حقائقك" : "After reviewing your facts"}</span></div>
        </li>
      </ol>

      <section className={cn("mt-6 rounded-xl border p-4", providerReady ? "border-emerald bg-emerald-pale" : "border-amber bg-amber-pale")} aria-labelledby="resume-provider-title" role={providerReady ? undefined : "alert"}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <span className={cn("grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white", providerReady ? "text-emerald" : "text-amber")}>
            {providerReady ? <Bot className="h-5 w-5" aria-hidden="true" /> : <ServerOff className="h-5 w-5" aria-hidden="true" />}
          </span>
          <div className="min-w-0 flex-1">
            <h2 id="resume-provider-title" className="font-bold">{providerReady ? (locale === "ar" ? "مساعد السيرة الذكي جاهز" : "AI resume assistant is ready") : (locale === "ar" ? "مساعد السيرة الذكي غير مفعّل" : "AI resume assistant is not enabled")}</h2>
            <p className="mt-1 text-sm text-muted">{providerReady ? (locale === "ar" ? "يحلل معلوماتك، يولّد أسئلة متابعة، ويكتب الملخص والنقاط المهنية حتى تصبح السيرة جاهزة للمراجعة والتنزيل." : "It analyzes your information, generates follow-up questions, and writes the professional summary and bullets until your resume is ready to review and download.") : (locale === "ar" ? "لن نحلل أي مصدر ولن ننشئ نتيجة تجريبية حتى يُفعّل المزود على الخادم." : "No source will be analyzed and no demo result will be created until the server provider is enabled.")}</p>
          </div>
          <p className="shrink-0 text-xs font-semibold text-muted" aria-label={locale === "ar" ? "مزود ونموذج الذكاء الاصطناعي" : "AI provider and model"}>
            {workspace?.model ? `${workspace.provider} · ${workspace.model}` : (workspace?.provider ?? (locale === "ar" ? "غير متاح" : "Unavailable"))}
          </p>
        </div>
      </section>

      <div className="mt-7 grid gap-7 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 rounded-xl border border-border bg-white p-5 md:p-6" aria-labelledby="resume-start-title">
          <h2 id="resume-start-title" className="section-title">{locale === "ar" ? "كيف تبغى تبدأ؟" : "How would you like to start?"}</h2>
          <p className="mt-1 text-sm text-muted">{locale === "ar" ? "اختر مصدرًا واحدًا الآن؛ تقدر تضيف مصادر أخرى لاحقًا من ملفك المهني." : "Choose one source now; you can add more later from your career profile."}</p>

          <div className="mt-5 grid gap-3 sm:grid-cols-2" aria-label={locale === "ar" ? "طريقة تجهيز السيرة" : "Resume preparation method"}>
            <button
              type="button"
              className={cn("min-h-28 rounded-xl border p-4 text-start transition-colors", mode === "upload" ? "border-emerald bg-emerald-pale" : "border-border bg-white hover:border-slate-400")}
              aria-pressed={mode === "upload"}
              onClick={() => chooseMode("upload")}
            >
              <FileUp className="h-6 w-6 text-emerald" aria-hidden="true" />
              <strong className="mt-3 block">{locale === "ar" ? "ارفع سيرتك الحالية" : "Upload your current resume"}</strong>
              <span className="mt-1 block text-xs text-muted">{locale === "ar" ? "PDF أو DOCX حتى 10 ميجابايت" : "PDF or DOCX up to 10 MB"}</span>
            </button>
            <button
              type="button"
              className={cn("min-h-28 rounded-xl border p-4 text-start transition-colors", mode === "create" ? "border-emerald bg-emerald-pale" : "border-border bg-white hover:border-slate-400")}
              aria-pressed={mode === "create"}
              onClick={() => chooseMode("create")}
            >
              <PenLine className="h-6 w-6 text-emerald" aria-hidden="true" />
              <strong className="mt-3 block">{locale === "ar" ? "ابنِ محتوى سيرتك من الصفر" : "Build resume content from scratch"}</strong>
              <span className="mt-1 block text-xs text-muted">{locale === "ar" ? "جاوب عن أسئلة قصيرة ومنظمة في كل قسم، والمساعد يرتب المحتوى" : "Answer short, structured questions in each section and let the assistant organize the content"}</span>
            </button>
          </div>

          <form className="mt-6" onSubmit={handleAiSubmit} aria-busy={submitting}>
            {mode === "upload" ? (
              <div>
                <label
                  htmlFor="resume-file"
                  className={cn("flex min-h-44 flex-col items-center justify-center rounded-xl border border-dashed px-5 py-7 text-center transition-colors", providerReady && !submitting ? "cursor-pointer" : "cursor-not-allowed opacity-60", file ? "border-emerald bg-emerald-pale" : "border-slate-400 bg-slate-50 hover:border-emerald")}
                  aria-disabled={!providerReady || submitting}
                >
                  {file ? <FileText className="h-9 w-9 text-emerald" aria-hidden="true" /> : <FileUp className="h-9 w-9 text-emerald" aria-hidden="true" />}
                  <strong className="mt-3 block">{file ? file.name : (locale === "ar" ? "اختر ملف السيرة" : "Choose your resume file")}</strong>
                  <span className="mt-1 block text-xs text-muted">
                    {file ? `${formatFileSize(file.size, locale)} MB · ${locale === "ar" ? "اضغط للاستبدال" : "Select to replace"}` : (locale === "ar" ? "نقبل PDF وDOCX فقط، ولن يبدأ الرفع قبل موافقتك." : "PDF and DOCX only. Upload will not start before your consent.")}
                  </span>
                </label>
                <input
                  ref={fileInputRef}
                  id="resume-file"
                  className="sr-only"
                  type="file"
                  accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  disabled={submitting || !providerReady}
                  onChange={(event) => handleFileSelected(event.target.files?.[0])}
                />
              </div>
            ) : (
              <GuidedResumeInterview
                locale={locale}
                disabled={submitting || !providerReady}
                onComplete={(answers, content) => {
                  setGuidedAnswers(answers);
                  setDraft(content);
                  setSubmitError(null);
                }}
                onInvalidate={() => {
                  setGuidedAnswers(null);
                  setDraft("");
                  setSubmitError(null);
                  setResult(null);
                  setConsentAcknowledged(false);
                }}
              />
            )}

            {mode === "upload" || draftReady ? (
              <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-lg border border-border p-4 text-sm">
                <input
                  className="mt-1 h-5 w-5 shrink-0 accent-emerald"
                  type="checkbox"
                  checked={consentAcknowledged}
                  disabled={submitting || !providerReady}
                  onChange={(event) => setConsentAcknowledged(event.target.checked)}
                />
                <span>
                  <strong className="block">{locale === "ar" ? "موافقة مستقلة لتحليل السيرة" : "Separate consent for resume analysis"}</strong>
                  <span className="mt-1 block text-xs text-muted">{dataSharingCopy}</span>
                </span>
              </label>
            ) : null}

            {submitError ? (
              <div className="mt-4 rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">
                <p>{typeof submitError === "string" ? submitError : apiErrorMessage(submitError, locale)}</p>
                {duplicateImportError ? (
                  <Link className="mt-3 inline-flex min-h-11 items-center gap-2 font-semibold underline underline-offset-4" href="/profile#facts-title">
                    {locale === "ar" ? "افتح الحقائق وعدّلها" : "Open and edit facts"}
                    <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
                  </Link>
                ) : (
                  <p className="mt-1 text-xs">{locale === "ar" ? "احتفظنا باختيارك لتقدر تعدّل أو تعيد المحاولة." : "Your selection was preserved so you can edit or retry."}</p>
                )}
              </div>
            ) : null}

            <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="flex max-w-xl items-start gap-2 text-xs text-muted">
                <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{locale === "ar" ? "لا ترفق رقم الهوية أو بيانات بنكية أو كلمات مرور أو معلومات صحية. مفتاح المزود يبقى داخل الخادم ولا يُحفظ في المتصفح." : "Do not include national IDs, banking details, passwords, or health information. The provider key stays on the server and is never stored in the browser."}</span>
              </p>
              <Button type="submit" size="lg" className="shrink-0" disabled={!canSubmit}>
                {submitting ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" /> : <Sparkles className="h-5 w-5" aria-hidden="true" />}
                {submitting
                  ? (locale === "ar" ? "جارٍ التحليل…" : "Analyzing…")
                  : mode === "upload"
                    ? (locale === "ar" ? "حلّل السيرة بالذكاء الاصطناعي" : "Analyze resume with AI")
                    : (locale === "ar" ? "ابنِ مسودة السيرة" : "Build resume draft")}
              </Button>
            </div>
          </form>

          {result ? (
            <section className="mt-7 rounded-xl border border-emerald bg-white p-5" aria-labelledby="resume-result-title" aria-live="polite">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-emerald" aria-hidden="true" />
                <div>
                  <h2 id="resume-result-title" className="text-lg font-bold">
                    {resultAnalysisStatus === "ai_upgraded"
                      ? (locale === "ar" ? "اكتمل تحليل السيرة بالذكاء الاصطناعي" : "AI resume analysis is complete")
                      : resultAnalysisStatus === "already_ai_analyzed"
                        ? (locale === "ar" ? "هذه السيرة محللة بالذكاء الاصطناعي مسبقًا" : "This resume was already analyzed by AI")
                        : (locale === "ar" ? `استخرجنا ${result.facts.length} حقائق للمراجعة` : `We extracted ${result.facts.length} facts for review`)}
                  </h2>
                  <p className="mt-1 text-sm text-muted">
                    {resultAnalysisStatus === "ai_upgraded"
                      ? result.facts.length > 0
                        ? (locale === "ar" ? "أضاف التحليل اقتراحات جديدة تحتاج مراجعتك؛ صحّح ما يلزم وأكد الصحيح فقط." : `The analysis added ${result.facts.length} suggestions for your review. Correct anything necessary and confirm only accurate facts.`)
                        : (locale === "ar" ? "لم نجد اقتراحات جديدة. حافظنا على الحقائق السابقة ولم نستبدل أي حقيقة مؤكدة." : "We found no new suggestions. Your existing facts were preserved and no confirmed fact was replaced.")
                      : resultAnalysisStatus === "already_ai_analyzed"
                        ? (locale === "ar" ? "لم نكرر التحليل أو ننشئ حقائق مكررة. افتح ملفك المهني لمراجعة النتائج الحالية وتعديلها." : "We did not repeat the analysis or create duplicate facts. Open your career profile to review and edit the current results.")
                        : (locale === "ar" ? "لم نؤكد أي معلومة بالنيابة عنك. افتح ملفك المهني، صحّح ما يلزم، ثم أكد الصحيح فقط." : "Nothing was confirmed on your behalf. Open your career profile, correct anything necessary, and confirm only accurate facts.")}
                  </p>
                </div>
              </div>
              {resultAnalysisStatus !== "already_ai_analyzed" && result.facts.length > 0 ? <ul className="mt-4 border-y border-border">{result.facts.map((fact) => <FactReviewItem key={fact.id} fact={fact} locale={locale} />)}</ul> : null}
              {resultAnalysisStatus === "created" && result.facts.length === 0 ? <p className="mt-4 rounded-lg bg-amber-pale p-3 text-sm text-muted">{locale === "ar" ? "لم نجد حقائق واضحة كفاية. أضف تفاصيل أكثر ثم أعد المحاولة." : "We did not find enough clear facts. Add more detail and try again."}</p> : null}
              <div className="mt-5 flex flex-wrap gap-3">
                <a href="#resume-ai-workspace-title" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald px-5 text-sm font-semibold text-white hover:bg-emerald-dark">
                  <Sparkles className="h-4 w-4" aria-hidden="true" />
                  {locale === "ar" ? "كمّل كتابة السيرة بالذكاء" : "Continue writing with AI"}
                </a>
                <Link href={factsLinkHref} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-border bg-white px-5 text-sm font-semibold text-ink hover:border-emerald">
                  {locale === "ar" ? "افتح الحقائق وعدّلها" : "Open and edit facts"}
                  <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
                </Link>
              </div>
            </section>
          ) : null}
        </section>

        <aside className="space-y-5" aria-labelledby="resume-process-title">
          <section className="rounded-xl border border-border p-5">
            <ShieldCheck className="h-6 w-6 text-emerald" aria-hidden="true" />
            <h2 id="resume-process-title" className="mt-3 font-bold">{locale === "ar" ? "وش يصير بعد التحليل؟" : "What happens after analysis?"}</h2>
            <ol className="mt-4 space-y-4 text-sm text-muted">
              <li className="flex gap-3"><span className="font-bold text-emerald">1</span><span>{locale === "ar" ? "عند الرفع، يستخرج الخادم النص محليًا وينقّح البريد والهاتف والهوية وIBAN قبل إرساله للمساعد." : "For uploads, the server extracts text locally and redacts emails, phone numbers, national IDs, and IBANs before sending it to the assistant."}</span></li>
              <li className="flex gap-3"><span className="font-bold text-emerald">2</span><span>{locale === "ar" ? "يقرأ Mistral الحقائق المهنية ويسألك أسئلة مخصصة عن المعلومات الناقصة." : "Mistral reads the professional facts and asks tailored questions about missing information."}</span></li>
              <li className="flex gap-3"><span className="font-bold text-emerald">3</span><span>{locale === "ar" ? "يكتب الملخص والأقسام والنقاط المهنية، ثم تعدّل أي كلمة داخل المحرر." : "It writes the summary, sections, and professional bullets, and you can edit every word."}</span></li>
              <li className="flex gap-3"><span className="font-bold text-emerald">4</span><span>{locale === "ar" ? "تراجع النسخة النهائية وتحمّلها PDF، وبعدها تنتقل لتحديد المسار." : "Review the final version, download the PDF, then continue to path selection."}</span></li>
            </ol>
          </section>

          <section className="rounded-xl border border-border p-5">
            <h2 className="font-bold">{locale === "ar" ? "مهم قبل الإرسال" : "Before you submit"}</h2>
            <ul className="mt-3 space-y-3 text-sm text-muted">
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" aria-hidden="true" /><span>{locale === "ar" ? "احذف البيانات شديدة الحساسية." : "Remove highly sensitive personal data."}</span></li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" aria-hidden="true" /><span>{locale === "ar" ? "نتائج الذكاء تحتاج مراجعتك دائمًا." : "AI output always needs your review."}</span></li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" aria-hidden="true" /><span>{locale === "ar" ? "يمكنك تعديل الحقائق أو سحب تأكيدها لاحقًا." : "You can edit facts or withdraw confirmation later."}</span></li>
            </ul>
          </section>
        </aside>
      </div>

      {facts.length > 0 ? (
        <ResumeAiWorkspace locale={locale} profile={profile} facts={facts} />
      ) : null}
    </div>
  );
}
