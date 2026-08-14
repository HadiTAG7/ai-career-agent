"use client";

import Link from "next/link";
import { AlertCircle, BriefcaseBusiness, ChevronLeft, LoaderCircle, MapPin, Plus, RotateCcw, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { DemoNotice } from "@/components/ui/demo-notice";
import { demoJobs } from "@/lib/demo-data";
import { apiConfiguration, apiErrorMessage, getJobs } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import type { Job } from "@/lib/types";

type LoadState = "loading" | "success" | "error";

export default function JobsPage() {
  const { locale, text } = useLocale();
  const connected = apiConfiguration.mode === "connected-api";
  const [query, setQuery] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loadState, setLoadState] = useState<LoadState>(connected ? "loading" : "success");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!connected) return;
    let active = true;
    getJobs()
      .then((result) => {
        if (!active) return;
        setJobs(result);
        setLoadState("success");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setLoadError(error);
        setLoadState("error");
      });
    return () => { active = false; };
  }, [connected, retryKey]);

  function retryLoad() {
    setLoadError(null);
    setLoadState("loading");
    setRetryKey((value) => value + 1);
  }

  const allJobs = connected ? jobs : demoJobs;
  const normalizedQuery = query.trim().toLocaleLowerCase(locale === "ar" ? "ar-SA" : "en-US");
  const visibleJobs = allJobs.filter((job) => {
    const searchableText = `${text(job.title)} ${text(job.company)} ${text(job.location)}`.toLocaleLowerCase(locale === "ar" ? "ar-SA" : "en-US");
    return !normalizedQuery || searchableText.includes(normalizedQuery);
  });

  return (
    <div className="page-wrap page-enter">
      <header className="flex flex-col justify-between gap-6 border-b border-border pb-7 md:flex-row md:items-end">
        <div>
          <p className="text-xs text-muted">{locale === "ar" ? "دليل 05 / الفرص" : "Guide 05 / Opportunities"}</p>
          <h1 className="mt-3 text-[40px] font-bold leading-tight tracking-[-0.03em] text-foreground md:text-[52px]">{locale === "ar" ? "الفرص" : "Opportunities"}</h1>
          <p className="mt-3 max-w-2xl text-muted">
            {locale === "ar"
              ? "حلّل فقط الفرص التي تستحق وقتك، واعرف ما يدعم القرار وما ينقصه."
              : "Analyze only the opportunities worth your time, with evidence for what supports the decision and what is missing."}
          </p>
          {!connected ? <DemoNotice className="mt-3" /> : <p className="mt-3 text-xs font-semibold text-emerald">{locale === "ar" ? "هذه بيانات مساحتك الحقيقية. أضف وصف وظيفة وجدته بنفسك لبدء التحليل." : "This is your real workspace data. Add a job description you found to start an analysis."}</p>}
        </div>
        <Link href="/jobs/new" className="inline-flex min-h-[52px] items-center justify-center gap-2 bg-primary px-6 font-semibold text-primary-foreground hover:bg-primary-hover">
          <Plus className="h-5 w-5" aria-hidden="true" />
          {locale === "ar" ? "أضف وظيفة يدويًا" : "Add a job manually"}
        </Link>
      </header>

      <div className="flex flex-col gap-4 border-b border-border py-5 md:flex-row md:items-center md:justify-between">
        <label className="relative block w-full max-w-xl">
          <span className="sr-only">{locale === "ar" ? "ابحث في الفرص" : "Search opportunities"}</span>
          <Search className="pointer-events-none absolute start-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted" aria-hidden="true" />
          <input className="field-control ps-12" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={locale === "ar" ? "المسمى أو الشركة أو المدينة" : "Role, company, or city"} />
        </label>
        <p className="text-xs text-muted">{locale === "ar" ? `${visibleJobs.length} نتيجة` : `${visibleJobs.length} results`}</p>
      </div>

      <section className="mt-7" aria-label={locale === "ar" ? "قائمة الفرص" : "Opportunity list"}>
        <div className="hidden grid-cols-[minmax(260px,1.4fr)_140px_minmax(170px,.8fr)_180px] gap-5 border-y border-border px-3 py-3 text-xs font-medium text-muted md:grid">
          <span>{locale === "ar" ? "الفرصة" : "Opportunity"}</span>
          <span>{locale === "ar" ? "تغطية المتطلبات" : "Coverage"}</span>
          <span>{locale === "ar" ? "المصدر والتحديث" : "Source and update"}</span>
          <span>{locale === "ar" ? "الإجراء" : "Action"}</span>
        </div>

        {connected && loadState === "loading" ? (
          <div className="flex min-h-48 items-center justify-center gap-3 border-b border-border text-sm text-muted" role="status">
            <LoaderCircle className="h-5 w-5 animate-spin text-primary-text" aria-hidden="true" />
            {locale === "ar" ? "جارٍ تحميل فرصك…" : "Loading your opportunities…"}
          </div>
        ) : null}

        {connected && loadState === "error" ? (
          <div className="border-b border-danger py-6" role="alert">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-danger" aria-hidden="true" />
              <div>
                <h2 className="font-bold text-foreground">{locale === "ar" ? "تعذر تحميل الفرص" : "Could not load opportunities"}</h2>
                <p className="mt-1 text-sm text-muted">{apiErrorMessage(loadError, locale)}</p>
                <button className="mt-4 inline-flex min-h-11 items-center gap-2 border border-danger px-4 text-sm font-semibold text-danger hover:text-foreground" type="button" onClick={retryLoad}>
                  <RotateCcw className="h-4 w-4" aria-hidden="true" />
                  {locale === "ar" ? "إعادة المحاولة" : "Try again"}
                </button>
              </div>
            </div>
          </div>
        ) : null}

        {loadState === "success" ? visibleJobs.map((job) => {
          const hasAnalysis = job.isDemo || Boolean(job.analysisId);
          return (
            <article className="grid gap-4 border-b border-border px-3 py-5 md:grid-cols-[minmax(260px,1.4fr)_140px_minmax(170px,.8fr)_180px] md:items-center" key={job.id}>
              <div>
                <div className="flex items-start gap-3">
                  <BriefcaseBusiness className="mt-1 h-5 w-5 shrink-0 text-muted" strokeWidth={1.7} aria-hidden="true" />
                  <div>
                    <h2 className="text-lg font-bold text-foreground">{text(job.title)}</h2>
                    <p className="mt-1 text-sm text-muted">{text(job.company)}</p>
                  </div>
                </div>
                <p className="mt-3 flex flex-wrap items-center gap-1 text-xs text-muted">
                  <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
                  {text(job.location)}{job.employmentType ? ` · ${text(job.employmentType)}` : null}
                </p>
              </div>
              <div>
                <strong className={hasAnalysis ? "text-2xl font-medium text-emerald" : "text-xl font-medium text-muted"}>{hasAnalysis ? `${job.coverage}%` : "—"}</strong>
                <span className="block text-xs text-muted">{hasAnalysis ? (locale === "ar" ? "تغطية موثقة" : "verified coverage") : (locale === "ar" ? "لم تُحلل بعد" : "Not analyzed yet")}</span>
              </div>
              <div className="text-sm">
                <p className="font-medium text-foreground">{text(job.source)}</p>
                <p className="mt-1 text-xs text-muted">{text(job.freshness)}</p>
              </div>
              <Link href={`/jobs/${job.id}`} className="inline-flex min-h-11 items-center gap-2 font-semibold text-primary-text hover:text-primary-hover">
                {hasAnalysis ? (locale === "ar" ? "عرض التحليل" : "View analysis") : (locale === "ar" ? "فتح الوظيفة" : "Open job")}
                <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
              </Link>
            </article>
          );
        }) : null}

        {loadState === "success" && visibleJobs.length === 0 ? (
          <div className="border-b border-border py-16 text-center">
            {allJobs.length === 0 ? <BriefcaseBusiness className="mx-auto h-8 w-8 text-muted" strokeWidth={1.6} aria-hidden="true" /> : <Search className="mx-auto h-8 w-8 text-muted" strokeWidth={1.6} aria-hidden="true" />}
            <p className="mt-3 font-semibold text-foreground">{allJobs.length === 0 ? (locale === "ar" ? "لا توجد فرص مضافة بعد" : "No opportunities added yet") : (locale === "ar" ? "لا توجد نتائج مطابقة" : "No matching opportunities")}</p>
            <p className="mx-auto mt-2 max-w-lg text-sm text-muted">{allJobs.length === 0 ? (locale === "ar" ? "أضف وصف وظيفة وجدته بنفسك، وسنحلله مقابل حقائق ملفك المؤكدة." : "Add a job description you found and we will analyze it against your confirmed profile facts.") : (locale === "ar" ? "جرّب البحث بمسمى أو شركة أو مدينة أخرى." : "Try another role, company, or city.")}</p>
            {allJobs.length > 0 ? <button className="mt-4 min-h-11 border-b border-primary px-1 text-sm font-semibold text-primary-text" type="button" onClick={() => setQuery("")}>{locale === "ar" ? "مسح البحث" : "Clear search"}</button> : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
