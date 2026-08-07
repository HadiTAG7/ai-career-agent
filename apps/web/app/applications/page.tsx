"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AlertCircle, BriefcaseBusiness, CalendarDays, ChevronLeft, FileText, LoaderCircle, MapPin, Plus, RotateCcw } from "lucide-react";
import { DemoNotice } from "@/components/ui/demo-notice";
import { demoApplications } from "@/lib/demo-data";
import { apiConfiguration, apiErrorMessage, getApplications, updateApplication } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import { readApplications, updateApplicationStage } from "@/lib/local-store";
import type { Application, ApplicationStage } from "@/lib/types";
import { cn, formatDemoDate } from "@/lib/utils";

const stageCopy: Record<ApplicationStage, { ar: string; en: string }> = {
  discovered: { ar: "مكتشفة", en: "Discovered" },
  saved: { ar: "محفوظة", en: "Saved" },
  preparing: { ar: "قيد التجهيز", en: "Preparing" },
  ready: { ar: "جاهزة", en: "Ready" },
  applied: { ar: "تم التقديم", en: "Applied" },
  interview: { ar: "مقابلة", en: "Interview" },
  rejected: { ar: "مرفوضة", en: "Rejected" },
  offer: { ar: "عرض", en: "Offer" },
  withdrawn: { ar: "منسحب", en: "Withdrawn" },
};

const filterGroups: Array<{ key: "all" | ApplicationStage; ar: string; en: string }> = [
  { key: "all", ar: "الكل", en: "All" },
  { key: "saved", ar: "محفوظة", en: "Saved" },
  { key: "ready", ar: "جاهزة", en: "Ready" },
  { key: "applied", ar: "تم التقديم", en: "Applied" },
  { key: "interview", ar: "مقابلات", en: "Interviews" },
];

export default function ApplicationsPage() {
  const { locale, text } = useLocale();
  const [applications, setApplications] = useState<Application[]>(apiConfiguration.baseUrl ? [] : demoApplications);
  const [filter, setFilter] = useState<"all" | ApplicationStage>("all");
  const [notice, setNotice] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "success" | "error">(apiConfiguration.baseUrl ? "loading" : "success");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const data = apiConfiguration.baseUrl ? await getApplications() : readApplications();
        if (active) {
          setApplications(data);
          setLoadState("success");
        }
      } catch (error) {
        if (active) {
          setLoadError(apiErrorMessage(error, locale));
          setLoadState("error");
        }
      }
    }
    void load();
    return () => { active = false; };
  }, [locale, retryKey]);

  function retryLoad() {
    setLoadError(null);
    setLoadState("loading");
    setRetryKey((value) => value + 1);
  }

  const visibleApplications = useMemo(() => filter === "all" ? applications : applications.filter((application) => application.stage === filter), [applications, filter]);

  async function setStage(id: string, stage: ApplicationStage) {
    try {
      if (apiConfiguration.baseUrl) {
        await updateApplication(id, stage);
        setApplications((current) => current.map((application) => application.id === id ? { ...application, stage, updatedAt: new Date().toISOString() } : application));
      } else {
        setApplications(updateApplicationStage(id, stage));
      }
      setNotice(locale === "ar" ? "تم تحديث الحالة بتأكيدك." : "Stage updated with your confirmation.");
    } catch (error) {
      setNotice(apiErrorMessage(error, locale));
    }
    window.setTimeout(() => setNotice(null), 2400);
  }

  return (
    <div className="page-wrap page-enter">
      <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div>
          <h1 className="page-title">{locale === "ar" ? "لوحة التقديمات" : "Application tracker"}</h1>
          <p className="mt-2 max-w-2xl text-muted">{locale === "ar" ? "كل حالة هنا يؤكدها المستخدم؛ لا نستنتج نتائج طلباتك من البريد." : "Every stage here is user-confirmed; we do not infer outcomes from your email."}</p>
          {!apiConfiguration.baseUrl ? <DemoNotice className="mt-3" /> : null}
        </div>
        <Link href="/jobs/new" className="inline-flex min-h-[52px] items-center justify-center gap-2 rounded-lg bg-emerald px-6 font-semibold text-white hover:bg-emerald-dark"><Plus className="h-5 w-5" />{locale === "ar" ? "أضف فرصة" : "Add opportunity"}</Link>
      </div>

      <div className="mt-8 overflow-x-auto border-b border-border" role="tablist" aria-label={locale === "ar" ? "تصفية التقديمات" : "Filter applications"}>
        <div className="flex min-w-max gap-2">
          {filterGroups.map((item) => {
            const count = item.key === "all" ? applications.length : applications.filter((application) => application.stage === item.key).length;
            return (
              <button key={item.key} type="button" role="tab" aria-selected={filter === item.key} onClick={() => setFilter(item.key)} className={cn("relative min-h-12 px-4 text-sm font-semibold", filter === item.key ? "text-ink" : "text-muted hover:text-ink")}>
                {locale === "ar" ? item.ar : item.en} <span className="ms-1 text-xs">({count})</span>
                {filter === item.key ? <span className="absolute inset-x-1 bottom-0 h-0.5 bg-emerald" /> : null}
              </button>
            );
          })}
        </div>
      </div>

      <section aria-live="polite" aria-label={locale === "ar" ? "التقديمات" : "Applications"}>
        {loadState === "loading" ? <div className="my-8 flex min-h-40 items-center justify-center gap-3 rounded-xl border border-border text-sm text-muted" role="status"><LoaderCircle className="h-5 w-5 animate-spin text-emerald" />{locale === "ar" ? "جارٍ تحميل التقديمات…" : "Loading applications…"}</div> : null}
        {loadState === "error" && loadError ? <div className="my-5 rounded-lg border border-danger bg-danger-pale p-4 text-sm text-danger" role="alert"><p className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{loadError}</p><button type="button" className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg border border-danger px-4 font-semibold" onClick={retryLoad}><RotateCcw className="h-4 w-4" />{locale === "ar" ? "إعادة المحاولة" : "Try again"}</button></div> : null}
        {apiConfiguration.baseUrl ? <p className="mt-5 rounded-lg border border-amber bg-amber-pale p-4 text-sm" role="note">{locale === "ar" ? "مرحلتا «جاهزة» وما بعد الإرسال معطلتان حتى يُربط تدفق حزمة CV الموثقة والمراجعة. لن نسجل تقديمًا لا يملك مستندًا صالحًا." : "Ready and post-submission stages are disabled until the reviewed, evidence-backed CV package flow is connected. We will not record an application without a valid document."}</p> : null}
        {loadState === "success" ? visibleApplications.map((application) => (
          <article className="grid gap-5 border-b border-border py-6 lg:grid-cols-[minmax(210px,1.2fr)_150px_minmax(190px,1fr)_170px_44px] lg:items-center" key={application.id}>
            <div>
              <Link href={`/jobs/${application.jobId}`} className="font-bold hover:text-emerald">{text(application.role)}</Link>
              <p className="mt-1 text-sm text-muted">{text(application.company)}</p>
              <p className="mt-2 flex items-center gap-1 text-xs text-muted"><MapPin className="h-3.5 w-3.5" />{text(application.location)}</p>
            </div>
            <label>
              <span className="sr-only">{locale === "ar" ? "حالة التقديم" : "Application stage"}</span>
              <select className="field-control min-h-11 py-0 text-sm" value={application.stage} onChange={(event) => { void setStage(application.id, event.target.value as ApplicationStage); }}>
                {Object.entries(stageCopy).map(([key, label]) => <option value={key} key={key} disabled={Boolean(apiConfiguration.baseUrl) && ["ready", "applied", "interview", "rejected", "offer"].includes(key)}>{text(label)}</option>)}
              </select>
            </label>
            <div><p className="text-sm font-semibold">{text(application.nextAction)}</p><p className="mt-1 flex items-center gap-1 text-xs text-muted"><CalendarDays className="h-3.5 w-3.5" />{formatDemoDate(application.updatedAt, locale)}</p></div>
            <div className="flex items-center gap-2 text-sm text-muted"><FileText className="h-4 w-4" />{application.documentVersion}</div>
            <Link href={`/jobs/${application.jobId}`} className="grid h-11 w-11 place-items-center rounded-lg border border-border hover:border-emerald" aria-label={locale === "ar" ? "فتح تحليل الوظيفة" : "Open job analysis"}><ChevronLeft className="h-5 w-5 rtl:rotate-0 ltr:rotate-180" /></Link>
          </article>
        )) : null}
        {loadState === "success" && visibleApplications.length === 0 ? <div className="py-20 text-center"><BriefcaseBusiness className="mx-auto h-9 w-9 text-muted" /><h2 className="mt-4 font-bold">{locale === "ar" ? "لا توجد تقديمات في هذه المرحلة" : "No applications in this stage"}</h2><p className="mt-2 text-sm text-muted">{locale === "ar" ? "غيّر التصفية أو أضف فرصة جديدة." : "Change the filter or add a new opportunity."}</p></div> : null}
      </section>

      {notice ? <div className="fixed bottom-24 start-5 z-50 rounded-lg border border-emerald bg-white px-4 py-3 text-sm shadow-subtle lg:bottom-6" role="status">{notice}</div> : null}
    </div>
  );
}
