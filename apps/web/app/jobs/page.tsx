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
    return () => {
      active = false;
    };
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
      <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div>
          <h1 className="page-title">{locale === "ar" ? "الفرص" : "Opportunities"}</h1>
          <p className="mt-2 max-w-2xl text-muted">
            {locale === "ar"
              ? "حلّل فقط الفرص التي تستحق وقتك، واعرف ما يدعم القرار وما ينقصه."
              : "Analyze only the opportunities worth your time, with evidence for what supports the decision and what is missing."}
          </p>
          {!connected ? (
            <DemoNotice className="mt-3" />
          ) : (
            <p className="mt-3 text-xs font-semibold text-emerald">
              {locale === "ar"
                ? "هذه بيانات مساحتك الحقيقية. أضف وصف وظيفة وجدته بنفسك لبدء التحليل."
                : "This is your real workspace data. Add a job description you found to start an analysis."}
            </p>
          )}
        </div>
        <Link href="/jobs/new" className="inline-flex min-h-[52px] items-center justify-center gap-2 rounded-lg bg-emerald px-6 font-semibold text-white hover:bg-emerald-dark">
          <Plus className="h-5 w-5" aria-hidden="true" />
          {locale === "ar" ? "أضف وظيفة يدويًا" : "Add a job manually"}
        </Link>
      </div>

      <label className="relative mt-8 block max-w-xl">
        <span className="sr-only">{locale === "ar" ? "ابحث في الفرص" : "Search opportunities"}</span>
        <Search className="pointer-events-none absolute start-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted" aria-hidden="true" />
        <input
          className="field-control ps-12"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={locale === "ar" ? "المسمى أو الشركة أو المدينة" : "Role, company, or city"}
        />
      </label>

      <section className="mt-8 border-t border-border" aria-label={locale === "ar" ? "قائمة الفرص" : "Opportunity list"}>
        {connected && loadState === "loading" ? (
          <div className="flex min-h-48 items-center justify-center gap-3 text-sm text-muted" role="status">
            <LoaderCircle className="h-5 w-5 animate-spin text-emerald" aria-hidden="true" />
            {locale === "ar" ? "جارٍ تحميل فرصك…" : "Loading your opportunities…"}
          </div>
        ) : null}

        {connected && loadState === "error" ? (
          <div className="my-8 rounded-xl border border-red-200 bg-red-50 p-5" role="alert">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-700" aria-hidden="true" />
              <div>
                <h2 className="font-bold text-red-900">{locale === "ar" ? "تعذر تحميل الفرص" : "Could not load opportunities"}</h2>
                <p className="mt-1 text-sm text-red-800">{apiErrorMessage(loadError, locale)}</p>
                <button className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg border border-red-300 px-4 text-sm font-semibold text-red-900 hover:bg-red-100" type="button" onClick={retryLoad}>
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
            <article className="grid gap-5 border-b border-border py-6 md:grid-cols-[minmax(0,1fr)_130px_180px] md:items-center" key={job.id}>
              <div>
                <div className="flex items-start gap-3">
                  <BriefcaseBusiness className="mt-1 h-5 w-5 shrink-0 text-emerald" aria-hidden="true" />
                  <div>
                    <h2 className="text-lg font-bold">{text(job.title)}</h2>
                    <p className="mt-1 text-sm text-muted">{text(job.company)}</p>
                  </div>
                </div>
                <p className="mt-3 flex items-center gap-1 text-xs text-muted">
                  <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
                  {text(job.location)} · {text(job.employmentType)} · {text(job.freshness)}
                </p>
              </div>
              <div>
                <strong className={hasAnalysis ? "text-2xl text-emerald" : "text-xl text-muted"}>{hasAnalysis ? `${job.coverage}%` : "—"}</strong>
                <span className="block text-xs text-muted">
                  {hasAnalysis
                    ? (locale === "ar" ? "تغطية المتطلبات" : "requirement coverage")
                    : (locale === "ar" ? "لم تُحلل بعد" : "Not analyzed yet")}
                </span>
              </div>
              <Link href={`/jobs/${job.id}`} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-emerald px-4 text-sm font-semibold text-emerald hover:bg-emerald-pale">
                {hasAnalysis ? (locale === "ar" ? "عرض التحليل" : "View analysis") : (locale === "ar" ? "فتح الوظيفة" : "Open job")}
                <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
              </Link>
            </article>
          );
        }) : null}

        {loadState === "success" && visibleJobs.length === 0 ? (
          <div className="py-16 text-center">
            {allJobs.length === 0 ? <BriefcaseBusiness className="mx-auto h-8 w-8 text-muted" aria-hidden="true" /> : <Search className="mx-auto h-8 w-8 text-muted" aria-hidden="true" />}
            <p className="mt-3 font-semibold">
              {allJobs.length === 0
                ? (locale === "ar" ? "لا توجد فرص مضافة بعد" : "No opportunities added yet")
                : (locale === "ar" ? "لا توجد نتائج مطابقة" : "No matching opportunities")}
            </p>
            <p className="mx-auto mt-2 max-w-lg text-sm text-muted">
              {allJobs.length === 0
                ? (locale === "ar" ? "أضف وصف وظيفة وجدته بنفسك، وسنحلله مقابل حقائق ملفك المؤكدة." : "Add a job description you found and we will analyze it against your confirmed profile facts.")
                : (locale === "ar" ? "جرّب البحث بمسمى أو شركة أو مدينة أخرى." : "Try another role, company, or city.")}
            </p>
            {allJobs.length > 0 ? (
              <button className="mt-4 min-h-11 rounded-lg border border-border px-4 text-sm font-semibold hover:border-emerald" type="button" onClick={() => setQuery("")}>
                {locale === "ar" ? "مسح البحث" : "Clear search"}
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
