"use client";

import Link from "next/link";
import { AlertCircle, ArrowLeft, BriefcaseBusiness, LoaderCircle, Plus, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { ApplicationStageRail } from "@/components/dashboard/application-stage-rail";
import { CareerEvidencePath } from "@/components/dashboard/career-evidence-path";
import { EvidenceProgress } from "@/components/dashboard/evidence-progress";
import { JobRow } from "@/components/dashboard/job-row";
import { DemoNotice } from "@/components/ui/demo-notice";
import { demoJobs } from "@/lib/demo-data";
import { ApiHttpError, apiConfiguration, apiErrorMessage, getCareerPathWorkspace, getDashboard } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import type { CareerPathWorkspace, DashboardData } from "@/lib/types";

type LoadState = "loading" | "success" | "error";

export function DashboardWorkspace({ data, careerPath, careerPathUnavailable = false }: { data?: DashboardData; careerPath?: CareerPathWorkspace | null; careerPathUnavailable?: boolean }) {
  const { locale } = useLocale();
  const connected = Boolean(data);
  const careerPathStarted = Boolean(careerPath?.conversation?.messages.length);
  const resumeRequired = connected && careerPath?.confirmed_fact_count === 0;
  const opportunities = data?.topOpportunities ?? demoJobs;
  const metrics = data ? [
    {
      label: locale === "ar" ? "جودة الملف" : "Profile quality",
      value: `${data.profileQualityPercent}%`,
      detail: locale === "ar" ? `${data.confirmedFacts} من ${data.totalFacts} حقائق مؤكدة` : `${data.confirmedFacts} of ${data.totalFacts} facts confirmed`,
      verified: true,
    },
    {
      label: locale === "ar" ? "طلبات مرسلة" : "Submitted applications",
      value: data.submittedApplications.toLocaleString(locale === "ar" ? "ar-SA" : "en-US"),
      detail: locale === "ar" ? "طلبات أُرسلت فعليًا" : "Applications actually sent",
      verified: false,
    },
    {
      label: locale === "ar" ? "مقابلات مؤهلة" : "Qualified interviews",
      value: data.qualifiedInterviews.toLocaleString(locale === "ar" ? "ar-SA" : "en-US"),
      detail: locale === "ar" ? "نتائج أكدتها بنفسك" : "Outcomes you confirmed",
      verified: false,
    },
    {
      label: locale === "ar" ? "معدل الوصول للمقابلة" : "Interview conversion",
      value: data.interviewRate === null ? "—" : `${Math.round(data.interviewRate * 100)}%`,
      detail: locale === "ar" ? "من الطلبات المرسلة" : "From submitted applications",
      verified: false,
    },
  ] : [];

  const primaryHref = connected ? (resumeRequired ? "/resume" : "/career-path") : "/jobs/new";
  const primaryLabel = resumeRequired
    ? (locale === "ar" ? "جهّز سيرتك الذاتية" : "Prepare your resume")
    : connected
      ? careerPathStarted
        ? (locale === "ar" ? "أكمل اكتشاف مسارك" : "Continue discovering your path")
        : (locale === "ar" ? "ابدأ اكتشاف مسارك" : "Discover your path")
      : (locale === "ar" ? "حلّل وظيفة جديدة" : "Analyze a new job");

  return (
    <div className="page-wrap page-enter">
      {!connected ? <DemoNotice className="mb-5 lg:hidden" /> : null}

      <section className="grid gap-10 border-b border-border pb-8 lg:grid-cols-[430px_minmax(0,1fr)] lg:gap-12" dir="ltr">
        <div className="flex flex-col items-start justify-center" dir={locale === "ar" ? "rtl" : "ltr"}>
          <h1 className="text-[40px] font-bold leading-[1.35] tracking-[-0.03em] text-foreground md:text-[50px]">
            {connected
              ? (locale === "ar" ? "مساحتك المهنية" : "Your career workspace")
              : (locale === "ar" ? "صباح الخير" : "Good morning")}
          </h1>
          <p className="mt-5 max-w-md text-base leading-8 text-muted">
            {connected
              ? (locale === "ar" ? "ملخص حقيقي لملفك وفرصك وطلباتك الحالية. نحو قرارات مهنية مدروسة بالأدلة." : "A real-time summary of your profile, opportunities, and applications. Built for evidence-led career decisions.")
              : (locale === "ar" ? "هذه أهم الخطوات التي ترفع جودة بحثك اليوم." : "These are the highest-impact steps for your search today.")}
          </p>
          <Link href={primaryHref} className="mt-6 inline-flex min-h-[52px] w-full items-center justify-center bg-primary px-7 text-base font-bold text-primary-foreground transition-colors hover:bg-primary-hover sm:w-auto">
            {primaryLabel}
          </Link>
        </div>

        <div dir={locale === "ar" ? "rtl" : "ltr"}>
          <CareerEvidencePath connected={connected} data={data} workspace={careerPath} unavailable={careerPathUnavailable} />
        </div>
      </section>

      {data ? (
        <section className="border-b border-border py-4" aria-label={locale === "ar" ? "مؤشرات المساحة المهنية" : "Career workspace metrics"}>
          <p className="mb-1 text-xs text-muted">{locale === "ar" ? "ملاحظة 02" : "Note 02"}</p>
          <div className="grid grid-cols-2 md:grid-cols-4">
            {metrics.map((metric) => (
              <article className="border-b border-s border-border px-4 py-2 first:border-s-0 [&:nth-child(3)]:border-s-0 md:border-b-0 md:[&:nth-child(3)]:border-s" key={metric.label}>
                <p className="text-sm text-muted">{metric.label}</p>
                <strong className={`mt-1 block text-3xl font-medium leading-none tabular-nums ${metric.verified ? "text-emerald" : "text-foreground"}`}>{metric.value}</strong>
                <p className="mt-2 text-xs text-muted">{metric.detail}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="py-7" aria-labelledby="best-opportunities-title">
        <div className="mb-4 flex items-end justify-between gap-5">
          <div>
            <h2 id="best-opportunities-title" className="text-2xl font-bold text-foreground">
              {locale === "ar" ? "الفرص المتاحة" : "Available opportunities"}
            </h2>
            <p className="mt-1 text-sm text-muted">
              {locale === "ar" ? "فرص مختارة وفق مسارك وملفك." : "Opportunities selected from your path and profile."}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <p className="text-xs text-muted">{locale === "ar" ? "مرجع 04" : "Reference 04"}</p>
            <Link href="/jobs" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-primary-text hover:text-foreground">
              {locale === "ar" ? "عرض جميع الفرص" : "View all opportunities"}
              <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
            </Link>
          </div>
        </div>

        <div className="border border-border">
          <div className="hidden grid-cols-[minmax(160px,1.25fr)_minmax(105px,.8fr)_minmax(110px,.8fr)_minmax(105px,.75fr)_minmax(125px,.9fr)_minmax(100px,.7fr)_44px] gap-3 border-b border-border px-3 py-3 text-xs font-medium text-muted md:grid">
            <span>{locale === "ar" ? "الوظيفة" : "Role"}</span>
            <span>{locale === "ar" ? "الشركة" : "Company"}</span>
            <span>{locale === "ar" ? "الموقع" : "Location"}</span>
            <span>{locale === "ar" ? "نوع العمل" : "Work type"}</span>
            <span>{locale === "ar" ? "تطابق المسار" : "Path match"}</span>
            <span>{locale === "ar" ? "آخر تحديث" : "Updated"}</span>
            <span />
          </div>
          {opportunities.length > 0 ? (
            <div>{opportunities.map((job) => <JobRow job={job} key={job.id} />)}</div>
          ) : (
            <div className="flex min-h-24 flex-col items-center justify-center gap-3 px-4 py-5 text-center sm:flex-row">
              <BriefcaseBusiness className="h-5 w-5 shrink-0 text-muted" strokeWidth={1.7} aria-hidden="true" />
              <p className="text-sm text-muted">
                {locale === "ar" ? "لا توجد فرص محللة بعد — أضف وصف وظيفة لتحليلها." : "No analyzed opportunities yet — add a job description to analyze it."}
              </p>
              <Link href="/jobs/new" className="inline-flex min-h-11 shrink-0 items-center gap-2 font-semibold text-primary-text hover:text-foreground">
                <Plus className="h-4 w-4" aria-hidden="true" />
                {locale === "ar" ? "إضافة وظيفة" : "Add a job"}
              </Link>
            </div>
          )}
        </div>
      </section>

      <section className="border-t border-border py-7" aria-labelledby="journey-title">
        <div className="mb-6 flex items-end justify-between gap-5">
          <div>
            <h2 id="journey-title" className="text-2xl font-bold text-foreground">{locale === "ar" ? "رحلة التقديم" : "Application journey"}</h2>
            <p className="mt-1 text-sm text-muted">{locale === "ar" ? "تتبّع طلباتك حتى الوصول للقرار." : "Track applications through to a decision."}</p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <p className="text-xs text-muted">{locale === "ar" ? "مرجع 05" : "Reference 05"}</p>
            <Link href="/applications" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-primary-text hover:text-foreground">
              {locale === "ar" ? "عرض التقديمات" : "View applications"}
              <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
            </Link>
          </div>
        </div>
        <ApplicationStageRail counts={data?.applicationStages} />
      </section>

      <EvidenceProgress data={data} />
    </div>
  );
}

export default function DashboardPage() {
  const { locale } = useLocale();
  const connected = apiConfiguration.mode === "connected-api";
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [careerPath, setCareerPath] = useState<CareerPathWorkspace | null>(null);
  const [careerPathUnavailable, setCareerPathUnavailable] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>(connected ? "loading" : "success");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!connected) return;
    let active = true;
    Promise.allSettled([getDashboard(), getCareerPathWorkspace()])
      .then(([dashboardResult, careerPathResult]) => {
        if (!active) return;
        if (dashboardResult.status === "fulfilled") {
          setDashboard(dashboardResult.value);
          setLoadState("success");
        } else {
          setLoadError(dashboardResult.reason);
          setLoadState("error");
        }
        if (careerPathResult.status === "fulfilled") {
          setCareerPath(careerPathResult.value);
          setCareerPathUnavailable(false);
        } else {
          setCareerPath(null);
          setCareerPathUnavailable(true);
        }
      });
    return () => { active = false; };
  }, [connected, retryKey]);

  function retryLoad() {
    setDashboard(null);
    setCareerPath(null);
    setCareerPathUnavailable(false);
    setLoadError(null);
    setLoadState("loading");
    setRetryKey((value) => value + 1);
  }

  if (!connected) return <DashboardWorkspace />;
  if (loadState === "success" && dashboard) return <DashboardWorkspace data={dashboard} careerPath={careerPath} careerPathUnavailable={careerPathUnavailable} />;

  const profileMissing = loadError instanceof ApiHttpError && loadError.status === 404;
  return (
    <div className="page-wrap page-enter">
      <h1 className="page-title">{locale === "ar" ? "مساحتك المهنية" : "Your career workspace"}</h1>
      <p className="mt-2 max-w-2xl text-muted">{locale === "ar" ? "ملخص حقيقي لملفك وفرصك وطلباتك الحالية." : "A real-time summary of your profile, opportunities, and applications."}</p>

      {loadState === "loading" ? (
        <div className="mt-10 flex min-h-56 items-center justify-center gap-3 border-y border-border text-sm text-muted" role="status">
          <LoaderCircle className="h-5 w-5 animate-spin text-primary-text" aria-hidden="true" />
          {locale === "ar" ? "جارٍ تحميل لوحة التحكم…" : "Loading your dashboard…"}
        </div>
      ) : null}

      {loadState === "error" ? (
        <div className="mt-10 border-y border-danger py-6" role="alert">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-6 w-6 shrink-0 text-danger" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-bold text-foreground">
                {profileMissing
                  ? (locale === "ar" ? "أنشئ ملفك المهني أولًا" : "Create your career profile first")
                  : (locale === "ar" ? "تعذر تحميل لوحة التحكم" : "Could not load the dashboard")}
              </h2>
              <p className="mt-2 text-sm text-muted">
                {profileMissing
                  ? (locale === "ar" ? "أضف معلوماتك الأساسية، ثم ستظهر مؤشراتك وفرصك هنا." : "Add your basic information, then your metrics and opportunities will appear here.")
                  : apiErrorMessage(loadError, locale)}
              </p>
              {profileMissing ? (
                <Link href="/profile" className="mt-4 inline-flex min-h-11 items-center gap-2 bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary-hover">
                  {locale === "ar" ? "إنشاء الملف" : "Create profile"}
                  <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
                </Link>
              ) : (
                <button className="mt-4 inline-flex min-h-11 items-center gap-2 border border-danger px-4 text-sm font-semibold text-danger hover:text-foreground" type="button" onClick={retryLoad}>
                  <RotateCcw className="h-4 w-4" aria-hidden="true" />
                  {locale === "ar" ? "إعادة المحاولة" : "Try again"}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
