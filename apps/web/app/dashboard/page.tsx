"use client";

import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  BriefcaseBusiness,
  CheckCircle2,
  Compass,
  FileUser,
  LoaderCircle,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  UserRoundCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { ApplicationStageRail } from "@/components/dashboard/application-stage-rail";
import { CareerPathStatusCard } from "@/components/career-path/career-path-status-card";
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
      icon: CheckCircle2,
    },
    {
      label: locale === "ar" ? "طلبات مرسلة" : "Submitted applications",
      value: data.submittedApplications.toLocaleString(locale === "ar" ? "ar-SA" : "en-US"),
      detail: locale === "ar" ? "طلبات أُرسلت فعليًا" : "Applications actually sent",
      icon: Send,
    },
    {
      label: locale === "ar" ? "مقابلات مؤهلة" : "Qualified interviews",
      value: data.qualifiedInterviews.toLocaleString(locale === "ar" ? "ar-SA" : "en-US"),
      detail: locale === "ar" ? "نتائج أكدتها بنفسك" : "Outcomes you confirmed",
      icon: UserRoundCheck,
    },
    {
      label: locale === "ar" ? "معدل الوصول للمقابلة" : "Interview conversion",
      value: data.interviewRate === null ? "—" : `${Math.round(data.interviewRate * 100)}%`,
      detail: locale === "ar" ? "من الطلبات المرسلة" : "From submitted applications",
      icon: BriefcaseBusiness,
    },
  ] : [];

  return (
    <div className="page-wrap page-enter">
      {!connected ? <DemoNotice className="mb-5 lg:hidden" /> : null}
      <div className="mb-8 flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div>
          <h1 className="page-title">
            {connected
              ? (locale === "ar" ? "مساحتك المهنية" : "Your career workspace")
              : (locale === "ar" ? "صباح الخير" : "Good morning")}
          </h1>
          <p className="mt-2 text-base text-muted md:text-lg">
            {connected
              ? (locale === "ar" ? "ملخص حقيقي لملفك وفرصك وطلباتك الحالية." : "A real-time summary of your profile, opportunities, and applications.")
              : (locale === "ar" ? "هذه أهم الخطوات التي ترفع جودة بحثك اليوم." : "These are the highest-impact steps for your search today.")}
          </p>
        </div>
        <Link href={connected ? (resumeRequired ? "/resume" : "/career-path") : "/jobs/new"} className="inline-flex min-h-[52px] items-center justify-center gap-3 rounded-lg bg-emerald px-6 text-base font-semibold text-white transition-colors hover:bg-emerald-dark md:min-w-[210px]">
          {resumeRequired ? <FileUser className="h-5 w-5" aria-hidden="true" /> : connected ? <Compass className="h-5 w-5" aria-hidden="true" /> : <Search className="h-5 w-5" aria-hidden="true" />}
          {resumeRequired
            ? (locale === "ar" ? "جهّز سيرتك الذاتية" : "Prepare your resume")
            : connected
              ? careerPathStarted
                ? (locale === "ar" ? "أكمل اكتشاف مسارك" : "Continue discovering your path")
                : (locale === "ar" ? "ابدأ اكتشاف مسارك" : "Discover your path")
              : (locale === "ar" ? "حلّل وظيفة جديدة" : "Analyze a new job")}
        </Link>
      </div>

      <CareerPathStatusCard workspace={careerPath} unavailable={careerPathUnavailable} connected={connected} />

      {data ? (
        <section className="mb-9 grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label={locale === "ar" ? "مؤشرات المساحة المهنية" : "Career workspace metrics"}>
          {metrics.map((metric) => {
            const Icon = metric.icon;
            return (
              <article className="rounded-xl border border-border p-5" key={metric.label}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-muted">{metric.label}</p>
                    <strong className="mt-2 block text-3xl text-ink">{metric.value}</strong>
                  </div>
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-emerald-pale text-emerald">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                </div>
                <p className="mt-3 text-xs text-muted">{metric.detail}</p>
              </article>
            );
          })}
        </section>
      ) : null}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <section aria-labelledby="best-opportunities-title">
            <div className="flex items-center justify-between border-b border-border pb-4">
              <h2 id="best-opportunities-title" className="section-title flex items-center gap-3">
                <BriefcaseBusiness className="h-6 w-6 text-emerald lg:hidden" aria-hidden="true" />
                {locale === "ar" ? "أفضل الفرص لك" : "Best opportunities for you"}
              </h2>
              <Link href="/jobs" className="subtle-link hidden md:inline-flex">
                {locale === "ar" ? "عرض جميع الفرص" : "View all opportunities"}
                <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
              </Link>
            </div>
            {opportunities.length > 0 ? (
              <>
                <div className="hidden grid-cols-[minmax(190px,1.3fr)_minmax(130px,.8fr)_minmax(150px,.9fr)_minmax(145px,.8fr)_44px] gap-4 border-b border-border py-3 text-xs font-semibold text-muted md:grid">
                  <span>{locale === "ar" ? "الوظيفة" : "Role"}</span>
                  <span>{locale === "ar" ? "تغطية المتطلبات" : "Coverage"}</span>
                  <span>{locale === "ar" ? "المصدر" : "Source"}</span>
                  <span>{locale === "ar" ? "التوصية" : "Recommendation"}</span>
                  <span />
                </div>
                <div className="relative">
                  {opportunities.map((job) => <JobRow job={job} key={job.id} />)}
                </div>
              </>
            ) : (
              <div className="rounded-b-xl border-x border-b border-border px-5 py-10 text-center">
                <BriefcaseBusiness className="mx-auto h-8 w-8 text-muted" aria-hidden="true" />
                <p className="mt-3 font-semibold">{locale === "ar" ? "لا توجد فرص محللة بعد" : "No analyzed opportunities yet"}</p>
                <p className="mx-auto mt-2 max-w-md text-sm text-muted">
                  {locale === "ar" ? "أضف وصف وظيفة لنعرض ملاءمتها هنا بعد تحليلها." : "Add a job description and its fit will appear here after analysis."}
                </p>
                <Link href="/jobs/new" className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg border border-emerald px-4 text-sm font-semibold text-emerald hover:bg-emerald-pale">
                  {locale === "ar" ? "إضافة وظيفة" : "Add a job"}
                  <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
                </Link>
              </div>
            )}
          </section>

          <section className="mt-8" aria-labelledby="journey-title">
            <div className="flex items-center justify-between">
              <h2 id="journey-title" className="section-title">{locale === "ar" ? "رحلة التقديم" : "Application journey"}</h2>
              <Link href="/applications" className="subtle-link">
                {locale === "ar" ? "عرض التقديمات" : "View applications"}
                <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
              </Link>
            </div>
            <div className="mt-5"><ApplicationStageRail counts={data?.applicationStages} /></div>
          </section>

          <section className="mt-8 flex flex-col gap-4 rounded-xl border border-border p-5 md:flex-row md:items-center" aria-label={locale === "ar" ? "وعد الأدلة" : "Evidence promise"}>
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-emerald-pale text-emerald"><ShieldCheck className="h-7 w-7" aria-hidden="true" /></span>
            <div className="flex-1">
              <h2 className="font-bold">{locale === "ar" ? "كل ادعاء نولّده مرتبط بحقيقة موثّقة." : "Every generated claim is linked to a verified fact."}</h2>
              <p className="mt-1 text-sm text-muted">{locale === "ar" ? "نربط المتطلبات بمصادر راجعتها أنت، ولا نخترع أرقامًا أو خبرات." : "We map requirements to sources you reviewed and never invent numbers or experience."}</p>
            </div>
            <Link href="/profile" className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-border px-4 text-sm font-semibold hover:border-emerald">
              {locale === "ar" ? "اعرف المزيد" : "Learn more"}
              <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
            </Link>
          </section>
        </div>

        <EvidenceProgress data={data} />
      </div>
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
    return () => {
      active = false;
    };
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
      <div>
        <h1 className="page-title">{locale === "ar" ? "مساحتك المهنية" : "Your career workspace"}</h1>
        <p className="mt-2 max-w-2xl text-muted">{locale === "ar" ? "ملخص حقيقي لملفك وفرصك وطلباتك الحالية." : "A real-time summary of your profile, opportunities, and applications."}</p>
      </div>

      {loadState === "loading" ? (
        <div className="mt-10 flex min-h-56 items-center justify-center gap-3 rounded-xl border border-border text-sm text-muted" role="status">
          <LoaderCircle className="h-5 w-5 animate-spin text-emerald" aria-hidden="true" />
          {locale === "ar" ? "جارٍ تحميل لوحة التحكم…" : "Loading your dashboard…"}
        </div>
      ) : null}

      {loadState === "error" ? (
        <div className="mt-10 rounded-xl border border-red-200 bg-red-50 p-6" role="alert">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-6 w-6 shrink-0 text-red-700" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-bold text-red-900">
                {profileMissing
                  ? (locale === "ar" ? "أنشئ ملفك المهني أولًا" : "Create your career profile first")
                  : (locale === "ar" ? "تعذر تحميل لوحة التحكم" : "Could not load the dashboard")}
              </h2>
              <p className="mt-2 text-sm text-red-800">
                {profileMissing
                  ? (locale === "ar" ? "أضف معلوماتك الأساسية، ثم ستظهر مؤشراتك وفرصك هنا." : "Add your basic information, then your metrics and opportunities will appear here.")
                  : apiErrorMessage(loadError, locale)}
              </p>
              {profileMissing ? (
                <Link href="/profile" className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald px-4 text-sm font-semibold text-white hover:bg-emerald-dark">
                  {locale === "ar" ? "إنشاء الملف" : "Create profile"}
                  <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
                </Link>
              ) : (
                <button className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg border border-red-300 px-4 text-sm font-semibold text-red-900 hover:bg-red-100" type="button" onClick={retryLoad}>
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
