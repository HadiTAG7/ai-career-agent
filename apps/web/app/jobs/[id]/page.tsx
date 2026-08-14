"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import {
  AlertCircle,
  Bookmark,
  Building2,
  CheckCircle2,
  ChevronLeft,
  ExternalLink,
  FilePlus2,
  Info,
  LoaderCircle,
  LockKeyhole,
  MapPin,
  Send,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { EvidenceDrawer, type DrawerEvidenceDetail, type RequirementEditInput } from "@/components/jobs/evidence-drawer";
import { EmptyRequirementEditor } from "@/components/jobs/empty-requirement-editor";
import { RequirementRow } from "@/components/jobs/requirement-row";
import { Button } from "@/components/ui/button";
import { DemoNotice } from "@/components/ui/demo-notice";
import { addJobRequirement, analyzeJob, apiConfiguration, apiErrorMessage, correctJobRequirement, getCareerFacts, getCareerProfile, getEvidenceSources, getJob, retireJobRequirement, reviewJobRequirements, saveApplication } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import { readLastAnalysis, saveJobForTracking, saveLastAnalysis } from "@/lib/local-store";
import type { Job, JobRecommendation, JobRequirement, ReadinessBand } from "@/lib/types";
import { cn } from "@/lib/utils";

const recommendationCopy: Record<JobRecommendation, { ar: string; en: string }> = {
  apply_now: { ar: "تقدّم الآن", en: "Apply now" },
  improve_then_apply: { ar: "حسّن ثم تقدّم", en: "Improve, then apply" },
  low_return: { ar: "عائد منخفض", en: "Low return" },
  need_information: { ar: "نحتاج معلومات", en: "Need information" },
};

const readinessCopy: Record<ReadinessBand, { ar: string; en: string }> = {
  low: { ar: "منخفضة", en: "Low" },
  medium: { ar: "متوسطة", en: "Medium" },
  high: { ar: "مرتفعة", en: "High" },
};

type PageNotice = { tone: "success" | "error"; message: string };

function isSafeHttpUrl(value?: string) {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

export default function JobAnalysisPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { locale, text } = useLocale();
  const [job, setJob] = useState<Job | null>(null);
  const [selectedRequirement, setSelectedRequirement] = useState<JobRequirement | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [notice, setNotice] = useState<PageNotice | null>(null);
  // Raw error kept in state and formatted at render time so switching the UI language
  // does not force a refetch that wipes selection and optimistic state.
  const [loadError, setLoadError] = useState<unknown>(null);
  const [evidenceDetails, setEvidenceDetails] = useState<Record<string, DrawerEvidenceDetail>>({});
  const [reviewingRequirements, startReviewTransition] = useTransition();
  const [savingApplication, startSaveTransition] = useTransition();
  const [applicationSaved, setApplicationSaved] = useState(false);
  const actionBarRef = useRef<HTMLDivElement>(null);
  const reviewSectionRef = useRef<HTMLDivElement>(null);
  const noticeTimerRef = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      const savedAnalysis = readLastAnalysis();
      const local = savedAnalysis?.id === params.id ? savedAnalysis : null;
      try {
        const result = local ? { data: local } : await getJob(params.id);
        if (!active) return;
        setJob(result.data);
        setSelectedRequirement(result.data.requirements[0] ?? null);
        if (!result.data.isDemo && apiConfiguration.baseUrl) {
          const profile = await getCareerProfile();
          if (profile) {
            const [facts, sources] = await Promise.all([getCareerFacts(profile.id), getEvidenceSources(profile.id)]);
            const sourceMap = new Map(sources.map((source) => [source.id, source]));
            const details = Object.fromEntries(facts.map((fact) => [fact.id, { fact, source: sourceMap.get(fact.source_id) }]));
            if (active) setEvidenceDetails(details);
          }
        }
        if (window.matchMedia("(min-width: 900px)").matches) setDrawerOpen(true);
      } catch (caughtError) {
        if (active) setLoadError(caughtError);
      }
    }
    void load();
    return () => { active = false; };
  }, [params.id]);

  useEffect(() => () => {
    if (noticeTimerRef.current) window.clearTimeout(noticeTimerRef.current);
  }, []);

  function showNotice(tone: PageNotice["tone"], message: string) {
    setNotice({ tone, message });
    if (noticeTimerRef.current) window.clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = window.setTimeout(() => setNotice(null), 3600);
  }

  const analysisComplete = Boolean(job?.isDemo || (job?.requirementsReviewedAt && job?.analysisId));

  const groups = useMemo(() => {
    if (!job) return [];
    if (!analysisComplete) {
      return [
        { key: "essential-review", title: locale === "ar" ? "المتطلبات الأساسية المستخرجة" : "Extracted essential requirements", requirements: job.requirements.filter((item) => item.kind === "essential") },
        { key: "preferred-review", title: locale === "ar" ? "المتطلبات المفضلة المستخرجة" : "Extracted preferred requirements", requirements: job.requirements.filter((item) => item.kind === "preferred") },
      ].filter((group) => group.requirements.length > 0);
    }
    return [
      { key: "essential", title: locale === "ar" ? "متطلبات أساسية مدعومة" : "Supported essential requirements", requirements: job.requirements.filter((item) => item.kind === "essential" && (item.status === "supported" || item.status === "partial")) },
      { key: "preferred", title: locale === "ar" ? "متطلبات مفضلة مدعومة" : "Supported preferred requirements", requirements: job.requirements.filter((item) => item.kind === "preferred" && (item.status === "supported" || item.status === "partial")) },
      { key: "gaps", title: locale === "ar" ? "الفجوات والبيانات غير الكافية" : "Gaps and insufficient data", requirements: job.requirements.filter((item) => item.status === "unsupported" || item.status === "unknown") },
    ].filter((group) => group.requirements.length > 0);
  }, [analysisComplete, job, locale]);

  function selectRequirement(requirement: JobRequirement) {
    setSelectedRequirement(requirement);
    setDrawerOpen(true);
  }

  async function handleRequirementCorrection(input: RequirementEditInput) {
    if (!job || !selectedRequirement || job.isDemo) return;
    await correctJobRequirement(job.id, selectedRequirement.id, input);
    const refreshedJob = (await getJob(job.id)).data;
    const refreshedSelection = refreshedJob.requirements.find((item) => item.id === selectedRequirement.id)
      ?? refreshedJob.requirements[0]
      ?? null;
    setJob(refreshedJob);
    setSelectedRequirement(refreshedSelection);
    showNotice("success", locale === "ar" ? "حُفظ التصحيح. راجع القائمة ثم اعتمدها لتشغيل المطابقة." : "Correction saved. Review the list, then confirm it to run matching.");
  }

  async function handleAddRequirement(input: RequirementEditInput) {
    if (!job || job.isDemo) return;
    const added = await addJobRequirement(job.id, input);
    const refreshedJob = (await getJob(job.id)).data;
    setJob(refreshedJob);
    setSelectedRequirement(refreshedJob.requirements.find((item) => item.id === added.id) ?? refreshedJob.requirements[0] ?? null);
    showNotice("success", locale === "ar" ? "أُضيف المتطلب. راجع القائمة ثم اعتمدها." : "Requirement added. Review the list, then confirm it.");
  }

  async function handleRetireRequirement(correctionReason: string) {
    if (!job || !selectedRequirement || job.isDemo) return;
    await retireJobRequirement(job.id, selectedRequirement.id, correctionReason);
    const refreshedJob = (await getJob(job.id)).data;
    setJob(refreshedJob);
    setSelectedRequirement(refreshedJob.requirements[0] ?? null);
    showNotice("success", locale === "ar" ? "حُذفت النتيجة الخاطئة. راجع القائمة ثم اعتمدها." : "False positive removed. Review the list, then confirm it.");
  }

  function handleRequirementsReview() {
    if (!job || job.isDemo) return;
    startReviewTransition(async () => {
      try {
        if (!job.requirementsReviewedAt) {
          const reviewedJob = await reviewJobRequirements(job.id);
          setJob(reviewedJob);
          setSelectedRequirement((current) => reviewedJob.requirements.find((item) => item.id === current?.id) ?? reviewedJob.requirements[0] ?? null);
        }
        const analyzedJob = await analyzeJob(job.id);
        setJob(analyzedJob);
        setSelectedRequirement((current) => analyzedJob.requirements.find((item) => item.id === current?.id) ?? analyzedJob.requirements[0] ?? null);
        saveLastAnalysis(analyzedJob);
        showNotice("success", locale === "ar" ? "اعتمدت المتطلبات واكتملت المطابقة مع حقائق ملفك المؤكدة." : "Requirements confirmed and matched against your confirmed profile facts.");
      } catch (error) {
        showNotice("error", apiErrorMessage(error, locale));
      }
    });
  }

  function handleSaveToTracker() {
    if (!job) return;
    if (!job.isDemo && (!job.requirementsReviewedAt || !job.analysisId)) {
      showNotice("error", locale === "ar" ? "اعتمد المتطلبات وشغّل المطابقة قبل حفظ الفرصة." : "Confirm requirements and run matching before saving this opportunity.");
      return;
    }
    startSaveTransition(async () => {
      try {
        if (job.isDemo) saveJobForTracking(job);
        else await saveApplication(job.id, job.analysisId!);
        setApplicationSaved(true);
        showNotice("success", locale === "ar" ? "حُفظت الوظيفة في لوحة التقديمات." : "Job saved to the application tracker.");
      } catch (error) {
        showNotice("error", apiErrorMessage(error, locale));
      }
    });
  }

  if (loadError != null) {
    return <div className="page-wrap grid min-h-[60vh] place-items-center"><section className="w-full max-w-lg border-y border-danger py-6 text-center" role="alert"><h1 className="text-xl font-bold">{locale === "ar" ? "تعذر تحميل التحليل" : "Could not load analysis"}</h1><p className="mt-3 text-sm text-danger">{apiErrorMessage(loadError, locale)}</p><Button variant="secondary" className="mt-5" onClick={() => router.push("/jobs")}>{locale === "ar" ? "العودة إلى الفرص" : "Back to opportunities"}</Button></section></div>;
  }

  if (!job) {
    return <div className="grid min-h-[60vh] place-items-center"><div className="text-center"><LoaderCircle className="mx-auto h-7 w-7 animate-spin text-primary-text" /><p className="mt-3 text-sm text-muted">{locale === "ar" ? "جارٍ تجهيز التحليل…" : "Preparing analysis…"}</p></div></div>;
  }

  if (job.requirements.length === 0) {
    return <div className="page-wrap grid min-h-[60vh] place-items-center"><EmptyRequirementEditor locale={locale} onAdd={handleAddRequirement} onBack={() => router.push("/jobs/new")} /></div>;
  }

  if (!selectedRequirement) return null;

  const supportedCount = job.requirements.filter((requirement) => requirement.status === "supported").length;
  const gapCount = job.requirements.filter((requirement) => requirement.status === "unsupported" || requirement.status === "unknown").length;
  const displayedRecommendation: JobRecommendation = analysisComplete ? job.recommendation : "need_information";

  return (
    <div className="page-enter pb-28 shell:pb-24">
      <div className="grid shell:grid-cols-[minmax(0,1fr)_320px]" dir="ltr">
        <div className="min-w-0 px-5 py-8 md:px-8 shell:py-10" dir={locale === "ar" ? "rtl" : "ltr"}>
          <div className="mx-auto max-w-[900px]">
            <Link href="/jobs" className="subtle-link"><ChevronLeft className="h-4 w-4 ltr:rotate-180" />{locale === "ar" ? "العودة إلى الفرص" : "Back to opportunities"}</Link>
            {job.isDemo ? <DemoNotice className="mt-3" /> : null}
            {!job.isDemo && !job.requirementsReviewedAt ? <div ref={reviewSectionRef} tabIndex={-1} className="mt-3 flex flex-col gap-3 border-y border-primary/45 bg-primary/5 py-4 text-sm md:flex-row md:items-center md:justify-between" role="note"><p><strong className="text-primary-text">{locale === "ar" ? "الخطوة 2 من 3 — راجع المتطلبات:" : "Step 2 of 3 — Review requirements:"}</strong> {locale === "ar" ? "صحّح النص والفئة والأهمية، وأضف أي متطلب مفقود أو احذف النتيجة الخاطئة، ثم اعتمد القائمة لتبدأ المطابقة." : "Correct text, category, and importance; add missed requirements or remove false positives, then confirm the list to start matching."}</p><Button className="shrink-0" disabled={reviewingRequirements} onClick={handleRequirementsReview}>{reviewingRequirements ? (locale === "ar" ? "جارٍ الاعتماد والمطابقة…" : "Confirming and matching…") : (locale === "ar" ? "اعتماد وتشغيل المطابقة" : "Confirm and run matching")}</Button></div> : null}
            {!job.isDemo && job.requirementsReviewedAt && !job.analysisId ? <div ref={reviewSectionRef} tabIndex={-1} className="mt-3 flex flex-col gap-3 border-y border-primary/45 bg-primary/5 py-4 text-sm md:flex-row md:items-center md:justify-between" role="alert"><p>{locale === "ar" ? "اعتُمدت المتطلبات، لكن المطابقة لم تكتمل. أعد تشغيلها دون إعادة الاعتماد." : "Requirements are confirmed, but matching did not finish. Run it again without reconfirming."}</p><Button className="shrink-0" disabled={reviewingRequirements} onClick={handleRequirementsReview}>{reviewingRequirements ? (locale === "ar" ? "جارٍ تشغيل المطابقة…" : "Running matching…") : (locale === "ar" ? "إعادة تشغيل المطابقة" : "Run matching again")}</Button></div> : null}
            {!job.isDemo && job.requirementsReviewedAt && job.analysisId ? <p className="mt-3 flex items-center gap-2 border-y border-emerald/45 py-4 text-sm text-emerald" role="status"><CheckCircle2 className="h-5 w-5 shrink-0" />{locale === "ar" ? "الخطوة 3 من 3 — اكتملت المطابقة؛ القرار مبني على المتطلبات التي راجعتها وحقائق ملفك المؤكدة فقط." : "Step 3 of 3 — Matching is complete; the decision uses your reviewed requirements and confirmed profile facts only."}</p> : null}

            <header className="mt-7 border-b border-border pb-7">
              <div className="flex flex-col justify-between gap-5 md:flex-row md:items-start">
                <div>
                  <h1 className="page-title">{text(job.title)}</h1>
                  <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted">
                    <span className="flex items-center gap-1"><Building2 className="h-4 w-4" />{text(job.company)}</span>
                    <span className="flex items-center gap-1"><MapPin className="h-4 w-4" />{text(job.location)}</span>
                    {job.employmentType ? <span>{text(job.employmentType)}</span> : null}
                  </p>
                </div>
                <Button onClick={() => analysisComplete ? actionBarRef.current?.focus() : reviewSectionRef.current?.focus()} size="lg"><Send className="h-5 w-5" />{analysisComplete ? text(recommendationCopy[displayedRecommendation]) : (locale === "ar" ? "راجع المتطلبات" : "Review requirements")}</Button>
              </div>
              <p className="mt-6 text-base text-muted">
                {!analysisComplete
                  ? (locale === "ar" ? "استخرجنا المتطلبات من النص ولم نحسب التغطية بعد. راجع القائمة أولًا حتى لا نبني القرار على استخراج غير دقيق." : "Requirements were extracted from the text, but coverage has not been calculated yet. Review the list first so the decision is not based on an inaccurate extraction.")
                  : displayedRecommendation === "apply_now"
                  ? locale === "ar" ? `تغطي أدلتك معظم المتطلبات الأساسية${gapCount ? `، مع ${gapCount} فجوات يمكن معالجتها قبل الإرسال` : " دون فجوات واضحة"}.` : `Your evidence covers most essential requirements${gapCount ? `, with ${gapCount} gap${gapCount === 1 ? "" : "s"} to address before sending` : " with no visible gaps"}.`
                  : locale === "ar" ? "هناك أساس جيد، لكن تحسين الأدلة المحددة سيرفع جودة الطلب قبل الإرسال." : "There is a solid base, but strengthening the highlighted evidence will improve the application."}
              </p>
            </header>

            {analysisComplete ? <section className="mt-6 grid gap-5 border-y border-emerald/45 py-6 md:grid-cols-[1fr_auto_1fr] md:items-center" aria-labelledby="decision-summary-title">
              <div className="flex items-center gap-4">
                <span className="grid h-14 w-14 shrink-0 place-items-center rounded-full border border-emerald text-emerald"><UserRound className="h-7 w-7" /></span>
                <div><h2 id="decision-summary-title" className="font-bold">{job.isDemo ? (locale === "ar" ? "جاهزية المقابلة" : "Interview readiness") : (locale === "ar" ? "جاهزية المقابلة" : "Interview readiness")}: <span className="text-emerald">{text(readinessCopy[job.readiness])}</span></h2><p className="mt-1 text-sm text-muted">{locale === "ar" ? "الثقة" : "Confidence"}: {text(readinessCopy[job.confidence])}</p></div>
              </div>
              <div className="hidden h-16 w-px bg-border md:block" />
              <div className="flex items-center justify-between gap-5">
                <div><strong className="text-4xl text-emerald">{job.coverage}%</strong><span className="mt-1 block text-sm text-muted">{locale === "ar" ? "تغطية المتطلبات" : "Requirement coverage"}</span></div>
                <div className="w-28" role="img" aria-label={locale === "ar" ? `تغطية المتطلبات ${job.coverage} بالمئة` : `${job.coverage} percent requirement coverage`}>
                  <span className="block text-end text-sm font-semibold text-emerald">{job.coverage}%</span>
                  <span className="mt-2 block h-px bg-border" aria-hidden="true"><span className="block h-px bg-emerald" style={{ width: `${job.coverage}%` }} /></span>
                </div>
              </div>
            </section> : <section className="mt-6 border-y border-primary/45 py-6" aria-labelledby="decision-summary-title"><h2 id="decision-summary-title" className="font-bold text-primary-text">{locale === "ar" ? "النتيجة بانتظار مراجعتك" : "Result waiting for your review"}</h2><p className="mt-2 text-sm text-muted">{locale === "ar" ? "لن نعرض نسبة تغطية أو توصية قبل اعتماد المتطلبات وتشغيل المطابقة." : "Coverage and a recommendation will stay hidden until you confirm requirements and run matching."}</p></section>}

            <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4 text-xs text-muted">
              <p>{analysisComplete ? `${supportedCount} ${locale === "ar" ? `من ${job.requirements.length} متطلبات مدعومة` : `of ${job.requirements.length} requirements supported`}` : (locale === "ar" ? `استُخرج ${job.requirements.length} متطلبات للمراجعة` : `${job.requirements.length} requirements extracted for review`)}</p>
              {analysisComplete ? <div className="flex flex-wrap gap-4"><span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-emerald" />{locale === "ar" ? "تم التحقق" : "Verified"}</span><span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-amber" />{locale === "ar" ? "متوافق جزئيًا" : "Partial"}</span><span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-danger" />{locale === "ar" ? "غير مدعوم" : "Unsupported"}</span></div> : <span>{locale === "ar" ? "اختر أي بند لتصحيحه أو إضافة متطلب مفقود." : "Select any item to correct it or add a missed requirement."}</span>}
            </div>

            <button className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-[2px] border border-border px-4 text-sm font-semibold shell:hidden" onClick={() => setDrawerOpen(true)}><Info className="h-4 w-4" />{locale === "ar" ? "فتح دليل القرار" : "Open decision evidence"}</button>

            <section className="mt-2" aria-label={locale === "ar" ? "تفاصيل المتطلبات" : "Requirement details"}>
              {groups.map((group) => (
                <div className="mt-6" key={group.key}>
                  <h2 className="mb-3 flex items-center gap-2 font-bold">{group.title}<span className="border-s border-border ps-2 text-sm font-normal text-muted">{group.requirements.length}</span></h2>
                  <div className="border-y border-border">
                    {group.requirements.map((requirement) => <RequirementRow key={requirement.id} requirement={requirement} reviewMode={!analysisComplete} selected={selectedRequirement.id === requirement.id} onSelect={() => selectRequirement(requirement)} />)}
                  </div>
                </div>
              ))}
            </section>
          </div>
        </div>

        <div className="border-border shell:border-l" dir={locale === "ar" ? "rtl" : "ltr"}>
          <EvidenceDrawer key={selectedRequirement.id} requirement={selectedRequirement} reviewMode={!analysisComplete} evidenceDetail={selectedRequirement.evidenceFactId ? evidenceDetails[selectedRequirement.evidenceFactId] : undefined} open={drawerOpen} onClose={() => setDrawerOpen(false)} onCorrectRequirement={!job.isDemo && apiConfiguration.baseUrl ? handleRequirementCorrection : undefined} onAddRequirement={!job.isDemo && apiConfiguration.baseUrl ? handleAddRequirement : undefined} onRetireRequirement={!job.isDemo && apiConfiguration.baseUrl ? handleRetireRequirement : undefined} />
        </div>
      </div>

      {notice ? <div className={cn("fixed bottom-28 start-5 z-50 flex max-w-sm items-start gap-2 border bg-background p-4 text-sm shell:bottom-24", notice.tone === "error" ? "border-danger text-danger" : "border-emerald")} role={notice.tone === "error" ? "alert" : "status"}>{notice.tone === "error" ? <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" />}<div><p>{notice.message}</p>{applicationSaved && notice.tone === "success" ? <Link href="/applications" className="mt-2 inline-flex font-semibold text-emerald underline underline-offset-4">{locale === "ar" ? "عرض لوحة التقديمات" : "View application tracker"}</Link> : null}</div></div> : null}

      <div ref={actionBarRef} tabIndex={-1} className="fixed inset-x-0 bottom-[76px] z-30 border-t border-border bg-background/95 px-5 py-3 backdrop-blur-sm shell:bottom-0 shell:end-0 shell:start-[244px] shell:px-8" aria-label={locale === "ar" ? "إجراءات الوظيفة" : "Job actions"}>
        <div className="mx-auto flex max-w-[1220px] flex-col-reverse gap-3 md:flex-row md:items-center md:justify-between">
          <p className="hidden items-center gap-2 text-sm text-muted shell:flex"><LockKeyhole className="h-4 w-4" />{locale === "ar" ? "لن تُضاف أي حقيقة غير مؤكدة إلى مستنداتك." : "No unconfirmed fact will be added to your documents."}</p>
          <div className="grid grid-cols-2 gap-3 md:flex">
            {job.isDemo || !apiConfiguration.baseUrl ? (
              <Button disabled={!analysisComplete} onClick={() => router.push(`/documents?job=${job.id}`)}><FilePlus2 className="h-4 w-4" />{locale === "ar" ? "أنشئ CV مخصصًا" : "Create tailored CV"}</Button>
            ) : (
              // Honest dead-end: per-job document generation has not shipped for connected
              // accounts yet, so do not navigate into a walled page.
              <Button disabled title={locale === "ar" ? "توليد مستندات لكل وظيفة لم يتوفر بعد؛ استخدم صفحة السيرة لإنشاء سيرتك." : "Per-job document generation is not available yet; use the resume page to build your CV."}><FilePlus2 className="h-4 w-4" />{locale === "ar" ? "أنشئ CV مخصصًا (قريبًا)" : "Create tailored CV (soon)"}</Button>
            )}
            <Button variant="secondary" disabled={!analysisComplete || savingApplication || applicationSaved} onClick={handleSaveToTracker}><Bookmark className="h-4 w-4" />{applicationSaved ? (locale === "ar" ? "محفوظ للمتابعة" : "Saved to tracker") : savingApplication ? (locale === "ar" ? "جارٍ الحفظ…" : "Saving…") : (locale === "ar" ? "حفظ للمتابعة" : "Save to tracker")}</Button>
            {isSafeHttpUrl(job.originalUrl) ? <a href={job.originalUrl} target="_blank" rel="noopener noreferrer" className="col-span-2 inline-flex min-h-11 items-center justify-center gap-2 text-sm font-semibold text-primary-text hover:text-primary-hover md:px-3">{locale === "ar" ? "فتح صفحة التقديم" : "Open application page"}<ExternalLink className="h-4 w-4" /></a> : <span className="col-span-2 flex min-h-11 items-center justify-center gap-2 text-xs text-muted"><ShieldCheck className="h-4 w-4" />{locale === "ar" ? "لا يوجد رابط صالح محفوظ" : "No valid saved URL"}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
