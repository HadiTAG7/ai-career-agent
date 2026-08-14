"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  FileUp,
  Filter,
  Link2,
  Plus,
  Pencil,
  RotateCcw,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { DemoNotice } from "@/components/ui/demo-notice";
import { ProgressRing } from "@/components/ui/progress-ring";
import { evidenceFacts, profileCompletion } from "@/lib/demo-data";
import { useLocale } from "@/lib/i18n";
import type { EvidenceFact, EvidenceStatus } from "@/lib/types";
import { cn, formatDisplayDate } from "@/lib/utils";
import {
  apiConfiguration,
  apiErrorMessage,
  confirmCareerFact,
  createCareerFact,
  createCareerProfile,
  getCareerFacts,
  getCareerProfile,
  getCareerProfileSummary,
  getEvidenceSources,
  importCareerFile,
  unconfirmCareerFact,
  updateCompletedFactCategories,
  updateCareerFact,
  type ApiCareerFact,
  type ApiCareerProfileSummary,
  type ApiEvidenceSource,
} from "@/lib/api-client";

type FactStatusFilter = "all" | "review" | EvidenceStatus;
type ProfileNotice = {
  message: string;
  tone: "success" | "warning" | "error";
  dashboardLink?: boolean;
};

const statusCopy: Record<EvidenceStatus, { ar: string; en: string }> = {
  confirmed: { ar: "مؤكدة", en: "Confirmed" },
  extracted: { ar: "مستخرجة للمراجعة", en: "Extracted for review" },
  unconfirmed: { ar: "غير مؤكدة", en: "Unconfirmed" },
};

const categoryCopy: Record<EvidenceFact["category"], { ar: string; en: string }> = {
  identity: { ar: "الهوية المهنية", en: "Professional identity" },
  experience: { ar: "الخبرات", en: "Experience" },
  education: { ar: "التعليم", en: "Education" },
  skill: { ar: "المهارات", en: "Skills" },
  project: { ar: "المشاريع", en: "Projects" },
  certification: { ar: "الشهادات", en: "Certificates" },
  language: { ar: "اللغات", en: "Languages" },
  achievement: { ar: "الإنجازات", en: "Achievements" },
  preference: { ar: "التفضيلات والأهلية", en: "Preferences & eligibility" },
  eligibility: { ar: "أهلية العمل", en: "Work eligibility" },
};

const completionCategories = [
  { key: "identity", ar: "الهوية المهنية", en: "Professional identity" },
  { key: "education", ar: "التعليم", en: "Education" },
  { key: "experience", ar: "الخبرات", en: "Experience" },
  { key: "certification", ar: "الشهادات", en: "Certifications" },
  { key: "skill", ar: "المهارات", en: "Skills" },
  { key: "project", ar: "المشاريع", en: "Projects" },
  { key: "language", ar: "اللغات", en: "Languages" },
  { key: "achievement", ar: "الإنجازات", en: "Achievements" },
  { key: "preference", ar: "التفضيلات", en: "Preferences" },
  { key: "eligibility", ar: "أهلية العمل", en: "Work eligibility" },
] as const;

function mapApiFact(fact: ApiCareerFact, source?: ApiEvidenceSource): EvidenceFact {
  const categoryMap: Record<string, EvidenceFact["category"]> = {
    experience: "experience", education: "education", skill: "skill", project: "project",
    certification: "certification", language: "language", achievement: "achievement",
    preference: "preference", eligibility: "eligibility", identity: "identity",
  };
  return {
    id: fact.id,
    category: categoryMap[fact.category] ?? "achievement",
    title: { ar: fact.label, en: fact.label },
    detail: { ar: fact.detail || fact.source_excerpt || "لا توجد تفاصيل", en: fact.detail || fact.source_excerpt || "No details" },
    source: source
      ? { ar: `${source.label}${source.original_filename ? ` — ${source.original_filename}` : ""}`, en: `${source.label}${source.original_filename ? ` — ${source.original_filename}` : ""}` }
      : { ar: "بيانات المصدر غير متاحة", en: "Source metadata unavailable" },
    status: fact.verification_status,
    updatedAt: fact.created_at.slice(0, 10),
    structuredValue: fact.structured_value,
    sourceExcerpt: fact.source_excerpt,
    extractionConfidence: fact.extraction_confidence,
  };
}

// Minimal dialog focus containment: keeps Tab cycling inside the open modal.
function trapDialogFocus(event: React.KeyboardEvent<HTMLElement>) {
  if (event.key !== "Tab") return;
  const focusable = event.currentTarget.querySelectorAll<HTMLElement>(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function isProfileManagedFact(fact: EvidenceFact) {
  const profileField = fact.structuredValue?.profile_field;
  return profileField === "full_name" || profileField === "city" || profileField === "years_experience";
}

export default function ProfilePage() {
  const { locale, text } = useLocale();
  const apiMode = Boolean(apiConfiguration.baseUrl);
  const [facts, setFacts] = useState<EvidenceFact[]>(apiMode ? [] : evidenceFacts);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [profileSummary, setProfileSummary] = useState<ApiCareerProfileSummary | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [apiLoading, setApiLoading] = useState(apiMode);
  const [apiLoadError, setApiLoadError] = useState<unknown>(null);
  const [uploading, setUploading] = useState(false);
  const [completedCategories, setCompletedCategories] = useState<string[]>([]);
  const [completionBusy, setCompletionBusy] = useState<string | null>(null);
  const [evidenceSources, setEvidenceSources] = useState<ApiEvidenceSource[]>([]);
  const [statusFilter, setStatusFilter] = useState<FactStatusFilter>("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(apiMode ? null : "fact-google-analytics");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingFact, setEditingFact] = useState<EvidenceFact | null>(null);
  const [notice, setNotice] = useState<ProfileNotice | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [busyFactId, setBusyFactId] = useState<string | null>(null);
  const [savingFact, setSavingFact] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!modalOpen && !editingFact) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setModalOpen(false);
      setEditingFact(null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [modalOpen, editingFact]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("status") !== "review") return;
    // Query params are client-only input here; applying them after hydration is intentional.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatusFilter("review");
  }, []);

  useEffect(() => {
    if (!apiMode) return;
    let active = true;
    async function loadProfile() {
      try {
        const profile = await getCareerProfile();
        if (!active) return;
        if (!profile) {
          setNeedsOnboarding(true);
          return;
        }
        setProfileId(profile.id);
        setCompletedCategories(profile.completed_fact_categories ?? []);
        const [apiFacts, sources, summary] = await Promise.all([
          getCareerFacts(profile.id),
          getEvidenceSources(profile.id),
          getCareerProfileSummary(profile.id),
        ]);
        if (active) {
          setEvidenceSources(sources);
          setProfileSummary(summary);
          const sourceMap = new Map(sources.map((source) => [source.id, source]));
          setFacts(apiFacts.map((fact) => mapApiFact(fact, sourceMap.get(fact.source_id))));
        }
      } catch (error) {
        if (active) setApiLoadError(error);
      } finally {
        if (active) setApiLoading(false);
      }
    }
    void loadProfile();
    return () => { active = false; };
  }, [apiMode]);

  const visibleFacts = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase(locale === "ar" ? "ar" : "en");
    return facts.filter((fact) => {
      const statusMatches = statusFilter === "all"
        || (statusFilter === "review" ? fact.status !== "confirmed" : fact.status === statusFilter);
      const queryMatches = !normalized || `${text(fact.title)} ${text(fact.detail)}`.toLocaleLowerCase().includes(normalized);
      return statusMatches && queryMatches;
    });
  }, [facts, locale, query, statusFilter, text]);

  async function confirmFact(id: string) {
    if (busyFactId) return;
    setBusyFactId(id);
    try {
      if (apiMode && profileId) {
        const confirmedFact = await confirmCareerFact(profileId, id);
        const confirmed = mapApiFact(confirmedFact, evidenceSources.find((source) => source.id === confirmedFact.source_id));
        setFacts((current) => current.map((fact) => fact.id === id ? confirmed : fact));
        setProfileSummary(await getCareerProfileSummary(profileId));
      } else {
        setFacts((current) => current.map((fact) => fact.id === id ? { ...fact, status: "confirmed" } : fact));
      }
      setNotice({
        message: locale === "ar" ? "تم تأكيد الحقيقة وربطها بسجل الأدلة." : "Fact confirmed and linked to the evidence record.",
        tone: "success",
        dashboardLink: apiMode,
      });
    } catch (error) {
      setNotice({ message: apiErrorMessage(error, locale), tone: "error" });
    } finally {
      setBusyFactId(null);
    }
  }

  const MAX_IMPORT_BYTES = 10_000_000;
  const IMPORT_EXTENSIONS = [".pdf", ".docx", ".zip"];

  async function handleFileSelected(file?: File) {
    if (!file) return;
    const lowerName = file.name.toLocaleLowerCase("en");
    if (!IMPORT_EXTENSIONS.some((extension) => lowerName.endsWith(extension))) {
      setNotice({
        message: locale === "ar" ? "نوع الملف غير مدعوم؛ استخدم PDF أو DOCX أو أرشيف ZIP." : "Unsupported file type; use PDF, DOCX, or a ZIP archive.",
        tone: "warning",
      });
      return;
    }
    if (file.size > MAX_IMPORT_BYTES) {
      setNotice({
        message: locale === "ar" ? "حجم الملف يتجاوز 10 ميغابايت؛ صغّر الملف ثم أعد المحاولة." : "The file exceeds 10 MB; reduce its size and try again.",
        tone: "warning",
      });
      return;
    }
    if (!apiMode || !profileId) {
      setNotice({
        message: locale === "ar" ? `تم اختيار ${file.name} للمراجعة التجريبية فقط.` : `${file.name} selected for demo-only review.`,
        tone: "warning",
      });
      return;
    }
    setUploading(true);
    try {
      const result = await importCareerFile(profileId, file);
      setEvidenceSources((current) => [result.source, ...current.filter((source) => source.id !== result.source.id)]);
      const importedFacts = result.facts.map((fact) => mapApiFact(fact, result.source));
      setFacts((current) => [...importedFacts, ...current]);
      setQuery("");
      setStatusFilter("review");
      setExpanded(importedFacts[0]?.id ?? null);
      setNotice({
        message: locale === "ar" ? `استُخرجت ${result.facts.length} حقائق؛ راجعها وأكد الصحيح فقط.` : `${result.facts.length} facts extracted; review and confirm only accurate ones.`,
        tone: "success",
      });
    } catch (error) {
      setNotice({ message: apiErrorMessage(error, locale), tone: "error" });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleOnboarding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setApiLoading(true);
    setApiLoadError(null);
    try {
      const profile = await createCareerProfile({
        fullName: String(form.get("fullName") ?? "").trim(),
        city: String(form.get("city") ?? "").trim(),
        preferredLanguage: locale,
      });
      setProfileId(profile.id);
      setCompletedCategories(profile.completed_fact_categories ?? []);
      setNeedsOnboarding(false);
      const [apiFacts, sources, summary] = await Promise.all([
        getCareerFacts(profile.id),
        getEvidenceSources(profile.id),
        getCareerProfileSummary(profile.id),
      ]);
      setEvidenceSources(sources);
      setProfileSummary(summary);
      const sourceMap = new Map(sources.map((source) => [source.id, source]));
      setFacts(apiFacts.map((fact) => mapApiFact(fact, sourceMap.get(fact.source_id))));
      setNotice({
        message: locale === "ar" ? "أُنشئ ملفك. يمكنك الآن استيراد السيرة ومراجعة الحقائق." : "Your profile is ready. You can now import a CV and review its facts.",
        tone: "success",
      });
    } catch (error) {
      setApiLoadError(error);
    } finally {
      setApiLoading(false);
    }
  }

  async function toggleCategoryCompletion(category: string, complete: boolean) {
    const previous = completedCategories;
    const next = complete ? [...new Set([...previous, category])] : previous.filter((item) => item !== category);
    setCompletedCategories(next);
    setCompletionBusy(category);
    try {
      const updated = await updateCompletedFactCategories(next);
      setCompletedCategories(updated.completed_fact_categories ?? []);
      setNotice({
        message: complete
          ? (locale === "ar" ? "سنعامل غياب عناصر هذه الفئة كفجوة واضحة بدل معلومة غير معروفة." : "Missing items in this category will now be treated as clear gaps rather than unknowns.")
          : (locale === "ar" ? "أصبحت الفئة غير مكتملة؛ سيبقى الغائب غير معلوم." : "The category is incomplete again; missing items will remain unknown."),
        tone: "success",
      });
    } catch (error) {
      setCompletedCategories(previous);
      setNotice({ message: apiErrorMessage(error, locale), tone: "error" });
    } finally {
      setCompletionBusy(null);
    }
  }

  async function withdrawConfirmation(fact: EvidenceFact) {
    if (busyFactId) return;
    setBusyFactId(fact.id);
    try {
      if (apiMode && profileId) {
        const updatedFact = await unconfirmCareerFact(profileId, fact.id);
        const updated = mapApiFact(updatedFact, evidenceSources.find((source) => source.id === updatedFact.source_id));
        setFacts((current) => current.map((item) => item.id === fact.id ? updated : item));
        setProfileSummary(await getCareerProfileSummary(profileId));
      } else {
        setFacts((current) => current.map((item) => item.id === fact.id ? { ...item, status: "unconfirmed" } : item));
      }
      setNotice({
        message: locale === "ar" ? "سُحب التأكيد. لن تُستخدم الحقيقة في مستند جديد حتى تؤكدها مجددًا." : "Confirmation withdrawn. The fact will not be used in a new document until reconfirmed.",
        tone: "warning",
        dashboardLink: apiMode,
      });
    } catch (error) {
      setNotice({ message: apiErrorMessage(error, locale), tone: "error" });
    } finally {
      setBusyFactId(null);
    }
  }

  async function handleEditFact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingFact) return;
    const form = new FormData(event.currentTarget);
    const label = String(form.get("label") ?? "").trim();
    const detail = String(form.get("detail") ?? "").trim();
    const correctionReason = String(form.get("correctionReason") ?? "").trim();
    const rawCategory = String(form.get("category") ?? editingFact.category);
    const category = rawCategory as EvidenceFact["category"];
    setSavingFact(true);
    setDialogError(null);
    try {
      if (apiMode && profileId) {
        const updatedFact = await updateCareerFact(profileId, editingFact.id, { category, label, detail, correctionReason });
        const updated = mapApiFact(updatedFact, evidenceSources.find((source) => source.id === updatedFact.source_id));
        setFacts((current) => current.map((item) => item.id === editingFact.id ? updated : item));
        setProfileSummary(await getCareerProfileSummary(profileId));
      } else {
        setFacts((current) => current.map((item) => item.id === editingFact.id ? { ...item, category: rawCategory as EvidenceFact["category"], title: { ar: label, en: label }, detail: { ar: detail, en: detail }, status: "unconfirmed" } : item));
      }
      setEditingFact(null);
      setNotice({
        message: locale === "ar" ? "حُفظ التصحيح وأصبحت الحقيقة غير مؤكدة حتى تراجعها." : "Correction saved; the fact is unconfirmed until you review it again.",
        tone: "warning",
      });
    } catch (error) {
      setDialogError(apiErrorMessage(error, locale));
    } finally {
      setSavingFact(false);
    }
  }

  async function handleAddFact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const title = String(form.get("title") ?? "").trim();
    const detail = String(form.get("detail") ?? "").trim();
    if (!title || !detail) return;
    const rawCategory = String(form.get("category") ?? "achievement");
    const category = rawCategory as EvidenceFact["category"];
    setSavingFact(true);
    setDialogError(null);
    if (apiMode && profileId) {
      try {
        const createdResult = await createCareerFact(profileId, { category, label: title, detail });
        const created = mapApiFact(createdResult.fact, createdResult.source);
        setFacts((current) => [created, ...current]);
        setModalOpen(false);
        setStatusFilter("review");
        setQuery("");
        setExpanded(created.id);
        setNotice({
          message: locale === "ar" ? "أُضيفت الحقيقة كغير مؤكدة؛ راجعها ثم أكدها." : "Fact added as unconfirmed; review it before confirming.",
          tone: "success",
        });
      } catch (error) {
        setDialogError(apiErrorMessage(error, locale));
      } finally {
        setSavingFact(false);
      }
      return;
    }
    const nextFact: EvidenceFact = {
      id: `local-${Date.now()}`,
      category,
      title: { ar: title, en: title },
      detail: { ar: detail, en: detail },
      source: { ar: "إدخال مباشر من المستخدم", en: "Direct user input" },
      status: "confirmed",
      updatedAt: new Date().toISOString().slice(0, 10),
    };
    setFacts((current) => [nextFact, ...current]);
    setModalOpen(false);
    setSavingFact(false);
    setNotice({
      message: locale === "ar" ? "أُضيفت الحقيقة كمعلومة مؤكدة من المستخدم." : "Fact added as confirmed user input.",
      tone: "success",
    });
  }

  const confirmedCount = facts.filter((fact) => fact.status === "confirmed").length;
  const extractedCount = facts.filter((fact) => fact.status === "extracted").length;
  const unconfirmedCount = facts.filter((fact) => fact.status === "unconfirmed").length;
  const pendingReviewCount = extractedCount + unconfirmedCount;
  const completion = apiMode ? (profileSummary?.profile_quality_percent ?? 0) : profileCompletion;
  const hasImportedSource = evidenceSources.some((source) => source.kind !== "manual");

  if (apiLoading) return <div className="grid min-h-[60vh] place-items-center" role="status"><div className="text-center"><FileUp className="mx-auto h-8 w-8 animate-pulse text-emerald" /><p className="mt-3 text-sm text-muted">{locale === "ar" ? "جارٍ تحميل ملفك…" : "Loading your profile…"}</p></div></div>;

  if (apiMode && needsOnboarding) {
    return (
      <div className="page-wrap page-enter max-w-[760px]">
        <h1 className="page-title">{locale === "ar" ? "أنشئ ملفك المهني" : "Create your career profile"}</h1>
        <p className="mt-2 text-muted">{locale === "ar" ? "نحتاج اسمك فقط للبدء. لن نستنتج الجنسية أو أهلية العمل من الاسم." : "We only need your name to begin. We never infer nationality or work eligibility from it."}</p>
        {apiLoadError ? <p className="mt-5 border-y border-danger bg-danger-pale/50 py-4 text-sm text-danger" role="alert">{apiErrorMessage(apiLoadError, locale)}</p> : null}
        <form className="mt-8 space-y-5 border-y border-border py-7" onSubmit={handleOnboarding}>
          <label><span className="field-label">{locale === "ar" ? "الاسم الكامل" : "Full name"}</span><input className="field-control" name="fullName" required autoComplete="name" /></label>
          <label><span className="field-label">{locale === "ar" ? "المدينة (اختياري)" : "City (optional)"}</span><input className="field-control" name="city" autoComplete="address-level2" /></label>
          <Button type="submit" size="lg">{locale === "ar" ? "إنشاء الملف" : "Create profile"}</Button>
        </form>
      </div>
    );
  }

  if (apiMode && apiLoadError && !profileId) return <div className="page-wrap"><div className="border-y border-danger bg-danger-pale/50 py-6" role="alert"><h1 className="section-title">{locale === "ar" ? "تعذر تحميل الملف" : "Could not load profile"}</h1><p className="mt-3 text-sm text-danger">{apiErrorMessage(apiLoadError, locale)}</p></div></div>;

  return (
    <div className="page-wrap page-enter">
      <div className="flex flex-col justify-between gap-5 md:flex-row md:items-start">
        <div>
          <h1 className="page-title">{locale === "ar" ? "ملفك المهني الموثّق" : "Your verified career profile"}</h1>
          <p className="mt-2 max-w-2xl text-muted">
            {locale === "ar"
              ? "راجع الحقائق التي نستخدمها في التحليل والتخصيص. لا تدخل أي حقيقة مولّدة في مستنداتك قبل تأكيدك."
              : "Review facts used for analysis and tailoring. No generated fact enters your documents before your confirmation."}
          </p>
          {!apiMode ? <DemoNotice className="mt-3" /> : null}
        </div>
        <div className="flex flex-wrap gap-3">
          <input
            className="sr-only"
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.zip"
            onChange={(event) => { void handleFileSelected(event.target.files?.[0]); }}
            aria-label={locale === "ar" ? "رفع سيرة ذاتية أو أرشيف لينكدإن" : "Upload CV or LinkedIn archive"}
          />
          {hasImportedSource || !apiMode ? <Button variant="secondary" disabled={uploading} onClick={() => fileRef.current?.click()}><FileUp className="h-4 w-4" />{uploading ? (locale === "ar" ? "جارٍ الاستخراج…" : "Extracting…") : (locale === "ar" ? "استورد ملفًا" : "Import file")}</Button> : null}
          <Button onClick={() => { setDialogError(null); setModalOpen(true); }}><Plus className="h-4 w-4" />{apiMode ? (locale === "ar" ? "أضف حقيقة" : "Add fact") : (locale === "ar" ? "أضف حقيقة تجريبية" : "Add demo fact")}</Button>
        </div>
      </div>

      {notice ? (
        <div
          className={cn(
            "mt-5 flex items-center justify-between gap-3 border-y px-1 py-3 text-sm",
            notice.tone === "success" && "border-emerald bg-emerald-pale",
            notice.tone === "warning" && "border-amber bg-amber-pale",
            notice.tone === "error" && "border-danger bg-danger-pale text-danger",
          )}
          role={notice.tone === "error" ? "alert" : "status"}
        >
          <span className="flex items-center gap-2">
            {notice.tone === "success" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald" /> : <AlertCircle className={cn("h-4 w-4 shrink-0", notice.tone === "error" ? "text-danger" : "text-amber")} />}
            <span>{notice.message}</span>
          </span>
          <span className="flex shrink-0 items-center gap-2">
            {notice.dashboardLink ? <Link href="/dashboard" className="subtle-link">{locale === "ar" ? "عرض التحديث" : "View update"}<ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" /></Link> : null}
            <button className="grid h-11 w-11 place-items-center" onClick={() => setNotice(null)} aria-label={locale === "ar" ? "إغلاق" : "Dismiss"}><X className="h-4 w-4" /></button>
          </span>
        </div>
      ) : null}

      {apiMode && profileId && !hasImportedSource ? (
        <section className="mt-6 flex flex-col gap-5 border-y border-primary/55 bg-primary/5 py-6 md:flex-row md:items-center" aria-labelledby="cv-import-title">
          <span className="grid h-14 w-14 shrink-0 place-items-center border border-primary/55 text-primary-text"><FileUp className="h-7 w-7" aria-hidden="true" /></span>
          <div className="flex-1">
            <h2 id="cv-import-title" className="section-title">{locale === "ar" ? "ابدأ باستيراد سيرتك" : "Start by importing your CV"}</h2>
            <p className="mt-2 text-sm text-muted">{locale === "ar" ? "ندعم PDF وDOCX وأرشيف LinkedIn بصيغة ZIP. نستخرج مرشحات للحقائق كي تراجعها، ولا نحتفظ بالملف الخام." : "PDF, DOCX, and LinkedIn ZIP are supported. We extract candidate facts for your review and do not retain the raw file."}</p>
          </div>
          <Button disabled={uploading} onClick={() => fileRef.current?.click()}><FileUp className="h-4 w-4" />{uploading ? (locale === "ar" ? "جارٍ الاستخراج…" : "Extracting…") : (locale === "ar" ? "اختر ملف السيرة" : "Choose CV file")}</Button>
        </section>
      ) : null}

      <section className="mt-8 grid gap-6 border-y border-border py-7 md:grid-cols-[auto_1fr] md:items-center" aria-labelledby="verification-summary-title">
        <ProgressRing value={completion} size="lg" label={locale === "ar" ? `جودة الملف ${completion} بالمئة` : `Profile quality is ${completion} percent`} />
        <div>
          <h2 id="verification-summary-title" className="section-title">{locale === "ar" ? "جودة الملف تقيس تغطية فئات الأدلة" : "Profile quality measures evidence-category coverage"}</h2>
          <p className="mt-2 text-sm text-muted">{locale === "ar" ? "تعتمد النسبة نفسها الظاهرة في لوحة التحكم على ست فئات مؤكدة: التعليم والخبرة والمهارات والمشاريع واللغات والشهادات. ليست احتمالًا للمقابلة." : "This is the same dashboard metric across six confirmed categories: education, experience, skills, projects, languages, and certifications. It is not an interview probability."}</p>
          <div className="mt-5 grid border-y border-border sm:grid-cols-4">
            <div className="py-3 sm:border-s sm:border-border sm:px-4"><strong className="text-xl text-emerald">{confirmedCount}</strong><span className="ms-2 text-sm text-muted">{locale === "ar" ? "حقائق مؤكدة" : "confirmed facts"}</span></div>
            <div className="border-t border-border py-3 sm:border-s sm:border-t-0 sm:px-4"><strong className="text-xl text-amber">{extractedCount}</strong><span className="ms-2 text-sm text-muted">{locale === "ar" ? "تحتاج مراجعة" : "needs review"}</span></div>
            <div className="border-t border-border py-3 sm:border-s sm:border-t-0 sm:px-4"><strong className="text-xl text-danger">{unconfirmedCount}</strong><span className="ms-2 text-sm text-muted">{locale === "ar" ? "غير مؤكدة" : "unconfirmed"}</span></div>
            {apiMode && profileSummary ? <div className="border-t border-border py-3 sm:border-s sm:border-t-0 sm:px-4"><strong className="text-xl text-foreground">{profileSummary.covered_quality_categories.length}/{profileSummary.total_quality_categories}</strong><span className="ms-2 text-sm text-muted">{locale === "ar" ? "فئات مغطاة" : "categories covered"}</span></div> : null}
          </div>
        </div>
      </section>

      {apiMode && profileId ? (
        <section className="mt-6 border-y border-border py-6" aria-labelledby="category-completion-title">
          <h2 id="category-completion-title" className="section-title">{locale === "ar" ? "هل أكملت هذه الفئات؟" : "Have you completed these categories?"}</h2>
          <p className="mt-2 text-sm text-muted">{locale === "ar" ? "لا تفعّل الفئة إلا بعد إدخال كل ما تريد ذكره. عند تفعيلها يصبح غياب متطلب من هذه الفئة فجوة واضحة؛ وإلا يبقى غير معلوم." : "Only mark a category complete after listing everything you want included. Missing requirements then become clear gaps; otherwise they remain unknown."}</p>
          <div className="mt-5 grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {completionCategories.map((category) => (
              <label className="flex min-h-12 items-center gap-3 border-b border-border px-2 transition-colors hover:bg-surface" key={category.key}>
                <input className="h-5 w-5 accent-emerald" type="checkbox" checked={completedCategories.includes(category.key)} disabled={completionBusy === category.key} onChange={(event) => { void toggleCategoryCompletion(category.key, event.target.checked); }} />
                <span><strong className="block text-sm">{locale === "ar" ? category.ar : category.en}</strong><small className="text-muted">{completedCategories.includes(category.key) ? (locale === "ar" ? "القائمة مكتملة" : "List is complete") : (locale === "ar" ? "قد توجد معلومات أخرى" : "More information may exist")}</small></span>
              </label>
            ))}
          </div>
        </section>
      ) : null}

      {apiMode && pendingReviewCount > 0 ? (
        <section className="mt-6 flex flex-col gap-4 border-y border-amber bg-amber-pale/50 py-5 md:flex-row md:items-center" aria-labelledby="review-queue-title">
          <AlertCircle className="h-7 w-7 shrink-0 text-amber" aria-hidden="true" />
          <div className="flex-1">
            <h2 id="review-queue-title" className="font-bold">{locale === "ar" ? `${pendingReviewCount} حقائق تنتظر مراجعتك` : `${pendingReviewCount} facts are waiting for review`}</h2>
            <p className="mt-1 text-sm text-muted">{locale === "ar" ? "افتح كل حقيقة، راجع مصدرها، ثم أكد الصحيح فقط." : "Open each fact, review its source, and confirm only what is accurate."}</p>
          </div>
          <Button variant="secondary" onClick={() => { setQuery(""); setStatusFilter("review"); document.getElementById("facts-title")?.scrollIntoView({ behavior: "smooth" }); }}>
            {locale === "ar" ? "ابدأ المراجعة" : "Start review"}
          </Button>
        </section>
      ) : null}

      {apiMode && hasImportedSource && pendingReviewCount === 0 ? (
        <section className="mt-6 flex flex-col gap-4 border-y border-emerald bg-emerald-pale/50 py-5 md:flex-row md:items-center" aria-labelledby="review-complete-title">
          <CheckCircle2 className="h-7 w-7 shrink-0 text-emerald" aria-hidden="true" />
          <div className="flex-1">
            <h2 id="review-complete-title" className="font-bold">{locale === "ar" ? "لا توجد حقائق معلقة" : "No facts are awaiting review"}</h2>
            <p className="mt-1 text-sm text-muted">{locale === "ar" ? "يمكنك رؤية جودة الملف المحدثة والبدء بتحليل فرصة." : "You can view the updated profile quality and start analyzing an opportunity."}</p>
          </div>
          <Link href="/dashboard" className="inline-flex min-h-11 items-center justify-center gap-2 border border-emerald px-4 text-sm font-semibold text-emerald hover:bg-emerald-pale">
            {locale === "ar" ? "عرض لوحة التحكم" : "View dashboard"}
            <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
          </Link>
        </section>
      ) : null}

      <section className="mt-8" aria-labelledby="facts-title">
        <div className="flex flex-col justify-between gap-4 border-b border-border pb-4 md:flex-row md:items-end">
          <div>
            <h2 id="facts-title" className="section-title">{locale === "ar" ? "سجل الأدلة المهنية" : "Career evidence record"}</h2>
            <p className="mt-1 text-sm text-muted">{visibleFacts.length} {locale === "ar" ? "حقائق ظاهرة" : "facts shown"}</p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <label className="relative min-w-[220px]">
              <span className="sr-only">{locale === "ar" ? "ابحث في الحقائق" : "Search facts"}</span>
              <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" />
              <input className="field-control ps-10" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={locale === "ar" ? "ابحث في الحقائق" : "Search facts"} />
            </label>
            <label className="relative min-w-[190px]">
              <span className="sr-only">{locale === "ar" ? "تصفية حسب الحالة" : "Filter by status"}</span>
              <Filter className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" />
              <select className="field-control ps-10" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as FactStatusFilter)}>
                <option value="all">{locale === "ar" ? "كل الحالات" : "All statuses"}</option>
                <option value="review">{locale === "ar" ? "تحتاج مراجعة" : "Needs review"}</option>
                <option value="confirmed">{locale === "ar" ? "مؤكدة" : "Confirmed"}</option>
                <option value="extracted">{locale === "ar" ? "مستخرجة" : "Extracted"}</option>
                <option value="unconfirmed">{locale === "ar" ? "غير مؤكدة" : "Unconfirmed"}</option>
              </select>
            </label>
          </div>
        </div>

        <div>
          {visibleFacts.map((fact) => {
            const isExpanded = expanded === fact.id;
            const statusColor = fact.status === "confirmed" ? "text-emerald" : fact.status === "extracted" ? "text-amber" : "text-danger";
            return (
              <article className="scroll-mt-28 border-b border-border" id={`fact-${fact.id}`} key={fact.id}>
                <button className="grid min-h-[88px] w-full grid-cols-[1fr_auto] items-center gap-4 py-4 text-start md:grid-cols-[150px_1fr_190px_44px]" onClick={() => setExpanded(isExpanded ? null : fact.id)} aria-expanded={isExpanded}>
                  <span className="text-xs font-semibold text-muted">{text(categoryCopy[fact.category])}</span>
                  <span>
                    <span className="block font-semibold">{text(fact.title)}</span>
                    <span className="mt-1 block text-sm text-muted">{text(fact.detail)}</span>
                  </span>
                  <span className={cn("hidden items-center gap-2 text-sm font-semibold md:flex", statusColor)}>
                    {fact.status === "confirmed" ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                    {text(statusCopy[fact.status])}
                  </span>
                  <ChevronDown className={cn("h-5 w-5 transition-transform", isExpanded && "rotate-180")} aria-hidden="true" />
                </button>
                {isExpanded ? (
                  <div className="mb-5 grid gap-4 border-s-2 border-primary bg-surface px-4 py-5 md:grid-cols-[1fr_auto] md:items-center">
                    <div>
                      <p className="flex items-center gap-2 text-sm font-semibold"><Link2 className="h-4 w-4 text-emerald" />{locale === "ar" ? "المصدر" : "Source"}</p>
                      <p className="mt-1 text-sm text-muted">{text(fact.source)} · {formatDisplayDate(fact.updatedAt, locale)}</p>
                      {fact.sourceExcerpt ? <div className="mt-3 border-y border-border py-3"><p className="text-xs font-semibold text-muted">{locale === "ar" ? "النص المستخرج من المصدر" : "Source excerpt"}</p><p className="mt-1 text-sm">{fact.sourceExcerpt}</p></div> : null}
                      {fact.structuredValue && Object.keys(fact.structuredValue).length > 0 ? <div className="mt-3 border-y border-amber bg-amber-pale/40 py-3"><p className="text-xs font-semibold text-foreground">{locale === "ar" ? "قيم منظمة ستدخل في الربط بعد التأكيد" : "Structured values used for grounding after confirmation"}</p><dl className="mt-2 grid gap-2">{Object.entries(fact.structuredValue).map(([key, value]) => <div className="grid grid-cols-[120px_1fr] gap-3 text-xs" key={key}><dt className="font-semibold text-muted" dir="ltr">{key}</dt><dd className="break-words">{typeof value === "string" ? value : JSON.stringify(value)}</dd></div>)}</dl></div> : null}
                      {fact.extractionConfidence != null ? <p className="mt-2 text-xs text-muted">{locale === "ar" ? "ثقة الاستخراج" : "Extraction confidence"}: {Math.round(fact.extractionConfidence * 100)}%</p> : null}
                    </div>
                    <div className="flex flex-wrap gap-2 md:max-w-[230px]">
                      {fact.status !== "confirmed" ? <Button disabled={busyFactId === fact.id} onClick={() => { void confirmFact(fact.id); }}><ShieldCheck className="h-4 w-4" />{busyFactId === fact.id ? (locale === "ar" ? "جارٍ التأكيد…" : "Confirming…") : (locale === "ar" ? "أؤكد صحة المعلومة" : "Confirm this fact")}</Button> : <Button variant="secondary" disabled={busyFactId === fact.id} onClick={() => { void withdrawConfirmation(fact); }}><RotateCcw className="h-4 w-4" />{busyFactId === fact.id ? (locale === "ar" ? "جارٍ السحب…" : "Withdrawing…") : (locale === "ar" ? "سحب التأكيد" : "Withdraw confirmation")}</Button>}
                      {!apiMode || !isProfileManagedFact(fact) ? <Button variant="ghost" disabled={Boolean(busyFactId)} onClick={() => { setDialogError(null); setEditingFact(fact); }}><Pencil className="h-4 w-4" />{locale === "ar" ? "تصحيح" : "Correct"}</Button> : <p className="max-w-[230px] text-xs text-muted">{locale === "ar" ? "هذه الحقيقة تُدار من بيانات الملف الأساسية؛ عُطّل تصحيحها هنا لتفادي اختلاف الملف عن سجل الأدلة." : "This fact is managed by core profile fields; correction is disabled here to prevent profile/evidence drift."}</p>}
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
          {visibleFacts.length === 0 ? (
            <div className="py-14 text-center">
              <Search className="mx-auto h-8 w-8 text-muted" aria-hidden="true" />
              <p className="mt-3 font-semibold">
                {facts.length === 0
                  ? (locale === "ar" ? "لا توجد حقائق مهنية بعد" : "No career facts yet")
                  : (locale === "ar" ? "لا توجد حقائق تطابق البحث أو الفلتر" : "No facts match the search or filter")}
              </p>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted">
                {facts.length === 0
                  ? (locale === "ar" ? "استورد سيرتك أو أضف حقيقة يدويًا للبدء." : "Import your CV or add a fact manually to get started.")
                  : (locale === "ar" ? "امسح البحث واعرض كل الحالات." : "Clear the search and show all statuses.")}
              </p>
              {facts.length > 0 ? <Button className="mt-4" variant="secondary" onClick={() => { setQuery(""); setStatusFilter("all"); }}>{locale === "ar" ? "مسح الفلاتر" : "Clear filters"}</Button> : null}
            </div>
          ) : null}
        </div>
      </section>

      {modalOpen ? (
        <div className="fixed inset-0 z-50 grid overflow-y-auto bg-black/70 p-5 backdrop-blur-sm" role="presentation" onMouseDown={(event) => { if (!savingFact && event.target === event.currentTarget) setModalOpen(false); }}>
          <section className="my-auto max-h-[calc(100vh-2.5rem)] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-card p-6 shadow-subtle" role="dialog" aria-modal="true" onKeyDown={trapDialogFocus} aria-labelledby="add-fact-title">
            <div className="flex items-center justify-between">
              <h2 id="add-fact-title" className="section-title">{locale === "ar" ? "أضف حقيقة مهنية" : "Add a career fact"}</h2>
              <button className="grid h-11 w-11 place-items-center rounded-lg hover:bg-surface" disabled={savingFact} onClick={() => setModalOpen(false)} aria-label={locale === "ar" ? "إغلاق" : "Close"}><X className="h-5 w-5" /></button>
            </div>
            <form className="mt-5 space-y-4" onSubmit={handleAddFact}>
              <label><span className="field-label">{locale === "ar" ? "الفئة" : "Category"}</span><select className="field-control" name="category" defaultValue="achievement"><option value="identity">{locale === "ar" ? "هوية مهنية" : "Professional identity"}</option><option value="experience">{locale === "ar" ? "خبرة" : "Experience"}</option><option value="education">{locale === "ar" ? "تعليم" : "Education"}</option><option value="skill">{locale === "ar" ? "مهارة" : "Skill"}</option><option value="project">{locale === "ar" ? "مشروع" : "Project"}</option><option value="certification">{locale === "ar" ? "شهادة" : "Certificate"}</option><option value="language">{locale === "ar" ? "لغة" : "Language"}</option><option value="achievement">{locale === "ar" ? "إنجاز" : "Achievement"}</option><option value="preference">{locale === "ar" ? "تفضيل مهني" : "Career preference"}</option><option value="eligibility">{locale === "ar" ? "أهلية العمل" : "Work eligibility"}</option></select></label>
              <label><span className="field-label">{locale === "ar" ? "عنوان الحقيقة" : "Fact title"}</span><input className="field-control" name="title" required autoFocus /></label>
              <label><span className="field-label">{locale === "ar" ? "التفاصيل" : "Details"}</span><textarea className="field-control min-h-28 py-3" name="detail" required /></label>
              <p className="text-xs text-muted">{locale === "ar" ? "سنسجل المصدر كإدخال مباشر منك. لا تضف معلومة لا يمكنك إثباتها." : "The source will be recorded as direct user input. Do not add information you cannot support."}</p>
              {dialogError ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{dialogError}</p> : null}
              <div className="flex justify-end gap-3"><Button variant="secondary" disabled={savingFact} onClick={() => setModalOpen(false)}>{locale === "ar" ? "إلغاء" : "Cancel"}</Button><Button type="submit" disabled={savingFact}>{savingFact ? (locale === "ar" ? "جارٍ الحفظ…" : "Saving…") : (locale === "ar" ? "حفظ الحقيقة" : "Save fact")}</Button></div>
            </form>
          </section>
        </div>
      ) : null}

      {editingFact ? (
        <div className="fixed inset-0 z-50 grid overflow-y-auto bg-black/70 p-5 backdrop-blur-sm" role="presentation" onMouseDown={(event) => { if (!savingFact && event.target === event.currentTarget) setEditingFact(null); }}>
          <section className="my-auto max-h-[calc(100vh-2.5rem)] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-card p-6 shadow-subtle" role="dialog" aria-modal="true" onKeyDown={trapDialogFocus} aria-labelledby="edit-fact-title">
            <div className="flex items-center justify-between"><h2 id="edit-fact-title" className="section-title">{locale === "ar" ? "صحّح الحقيقة" : "Correct fact"}</h2><button className="grid h-11 w-11 place-items-center rounded-lg hover:bg-surface" disabled={savingFact} onClick={() => setEditingFact(null)} aria-label={locale === "ar" ? "إغلاق" : "Close"}><X className="h-5 w-5" /></button></div>
            <p className="mt-2 text-sm text-muted">{locale === "ar" ? "أي تعديل يسحب التأكيد ويبطل تحليلات أو مستندات اعتمدت على النسخة السابقة حتى تراجعها مجددًا." : "Any edit withdraws confirmation and invalidates analyses or documents grounded in the previous version until you review it again."}</p>
            <form className="mt-5 space-y-4" onSubmit={handleEditFact}>
              <label><span className="field-label">{locale === "ar" ? "الفئة الصحيحة" : "Correct category"}</span><select className="field-control" name="category" defaultValue={editingFact.category}><option value="identity">{locale === "ar" ? "هوية مهنية" : "Professional identity"}</option><option value="experience">{locale === "ar" ? "خبرة" : "Experience"}</option><option value="education">{locale === "ar" ? "تعليم" : "Education"}</option><option value="skill">{locale === "ar" ? "مهارة" : "Skill"}</option><option value="project">{locale === "ar" ? "مشروع" : "Project"}</option><option value="certification">{locale === "ar" ? "شهادة" : "Certificate"}</option><option value="language">{locale === "ar" ? "لغة" : "Language"}</option><option value="achievement">{locale === "ar" ? "إنجاز" : "Achievement"}</option><option value="preference">{locale === "ar" ? "تفضيل مهني" : "Career preference"}</option><option value="eligibility">{locale === "ar" ? "أهلية العمل" : "Work eligibility"}</option></select></label>
              <label><span className="field-label">{locale === "ar" ? "العنوان الصحيح" : "Correct title"}</span><input className="field-control" name="label" required defaultValue={text(editingFact.title)} autoFocus /></label>
              <label><span className="field-label">{locale === "ar" ? "التفاصيل الصحيحة" : "Correct details"}</span><textarea className="field-control min-h-28 py-3" name="detail" required defaultValue={text(editingFact.detail)} /></label>
              <label><span className="field-label">{locale === "ar" ? "سبب التصحيح" : "Correction reason"}</span><textarea className="field-control min-h-20 py-3" name="correctionReason" required minLength={3} placeholder={locale === "ar" ? "مثال: التاريخ المستخرج غير صحيح" : "e.g. The extracted date was incorrect"} /></label>
              {dialogError ? <p className="rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{dialogError}</p> : null}
              <div className="flex justify-end gap-3"><Button variant="secondary" disabled={savingFact} onClick={() => setEditingFact(null)}>{locale === "ar" ? "إلغاء" : "Cancel"}</Button><Button type="submit" disabled={savingFact}>{savingFact ? (locale === "ar" ? "جارٍ الحفظ…" : "Saving…") : (locale === "ar" ? "حفظ التصحيح" : "Save correction")}</Button></div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}
