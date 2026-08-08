"use client";

import Link from "next/link";
import { AlertCircle, Award, CheckCircle2, ChevronLeft, IdCard, ShieldCheck } from "lucide-react";
import { useLocale } from "@/lib/i18n";
import { profileCompletion } from "@/lib/demo-data";
import type { DashboardData } from "@/lib/types";

const groups = [
  { ar: "الخبرات", en: "Experience", complete: true },
  { ar: "المهارات", en: "Skills", complete: true },
  { ar: "المشاريع", en: "Projects", complete: true },
  { ar: "المؤهلات", en: "Qualifications", complete: true },
  { ar: "حق العمل", en: "Work eligibility", complete: false },
];

type EvidenceProgressProps = {
  data?: Pick<DashboardData, "profileQualityPercent" | "confirmedFacts" | "totalFacts" | "actionsDue">;
};

export function EvidenceProgress({ data }: EvidenceProgressProps = {}) {
  const { locale } = useLocale();

  if (data) {
    const factsToReview = Math.max(data.totalFacts - data.confirmedFacts, 0);
    return (
      <aside className="border-t border-border py-5" aria-labelledby="evidence-progress-title">
        <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center lg:grid-cols-[minmax(0,1fr)_210px_240px]">
          <div>
            <p className="text-xs text-muted">{locale === "ar" ? "ملاحظة 01" : "Note 01"}</p>
            <div className="mt-2 flex items-start gap-3">
              <ShieldCheck className="mt-1 h-6 w-6 shrink-0 text-emerald" strokeWidth={1.7} aria-hidden="true" />
              <div>
                <h2 id="evidence-progress-title" className="text-xl font-bold text-foreground">
                  {locale === "ar" ? "وعد الأدلة" : "Evidence promise"}
                </h2>
                <p className="mt-1 text-sm text-muted">
                  {locale === "ar" ? "نقيس تغطية الأدلة الأساسية، ولا نحوّلها إلى ضمان للتوظيف." : "We measure core evidence coverage, never a guarantee of employment."}
                </p>
                <p className="mt-2 hidden text-sm font-semibold text-foreground sm:block">
                  {locale === "ar" ? `جودة ملفك ${data.profileQualityPercent}%` : `Your profile quality is ${data.profileQualityPercent}%`}
                </p>
              </div>
            </div>
          </div>

          <div className="border-s border-border ps-3 md:min-w-[190px] md:ps-6">
            <p className="text-2xl font-semibold tabular-nums text-foreground md:text-3xl">
              <span className="text-primary-text">{data.confirmedFacts}</span>
              <span className="mx-2 text-muted">/</span>
              {data.totalFacts}
            </p>
            <p className="mt-1 text-sm text-muted">{locale === "ar" ? "حقيقة مؤكدة" : "confirmed facts"}</p>
            <div className="mt-2 hidden flex-wrap gap-x-5 gap-y-2 text-xs sm:flex">
              <span className="text-emerald">{locale === "ar" ? `${data.confirmedFacts} مؤكدة` : `${data.confirmedFacts} confirmed`}</span>
              <span className="text-muted">{locale === "ar" ? `${factsToReview} تحتاج مراجعة` : `${factsToReview} need review`}</span>
            </div>
          </div>
          <div className="col-span-2 flex flex-wrap items-center justify-between gap-x-5 border-t border-border pt-3 text-sm md:col-span-2 lg:col-span-1 lg:border-s lg:border-t-0 lg:ps-5 lg:pt-0">
            {data.actionsDue > 0 ? (
              <Link href="/applications" className="inline-flex min-h-11 items-center gap-2 font-semibold text-primary-text hover:text-foreground">
                <AlertCircle className="h-4 w-4" aria-hidden="true" />
                {locale === "ar" ? `${data.actionsDue} إجراءات مستحقة` : `${data.actionsDue} actions due`}
              </Link>
            ) : (
              <span className="inline-flex min-h-11 items-center gap-2 text-muted">
                <CheckCircle2 className="h-4 w-4 text-emerald" aria-hidden="true" />
                {locale === "ar" ? "لا توجد إجراءات متأخرة حاليًا." : "No overdue actions."}
              </span>
            )}
            <Link href="/profile" className="inline-flex min-h-11 items-center gap-2 font-semibold text-primary-text hover:text-foreground">
              {locale === "ar" ? "عرض تفاصيل الملف" : "View profile details"}
              <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="border-t border-border py-6" aria-labelledby="evidence-progress-title">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,.7fr)]">
        <div>
          <p className="text-xs text-muted">{locale === "ar" ? "ملاحظة 01" : "Note 01"}</p>
          <div className="mt-3 flex items-start gap-3">
            <ShieldCheck className="mt-1 h-6 w-6 shrink-0 text-emerald" strokeWidth={1.7} aria-hidden="true" />
            <div>
              <h2 id="evidence-progress-title" className="text-xl font-bold text-foreground">
                {locale === "ar" ? "وعد الأدلة" : "Evidence promise"}
              </h2>
              <p className="mt-1 text-sm text-muted">
                {locale === "ar" ? "النسبة تقيس اكتمال الأدلة، لا فرص التوظيف." : "This measures evidence completeness, not employability."}
              </p>
              <p className="mt-3 text-3xl font-semibold text-primary-text">{profileCompletion}%</p>
            </div>
          </div>
          <Link href="/profile" className="mt-4 inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-primary-text hover:text-foreground">
            {locale === "ar" ? "عرض تفاصيل التوثيق" : "View verification details"}
            <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
          </Link>
        </div>

        <div className="border-t border-border pt-4 lg:border-s lg:border-t-0 lg:ps-6 lg:pt-0">
          <div className="grid grid-cols-2 gap-x-5 gap-y-2 text-sm">
            {groups.map((group) => (
              <div className="flex items-center justify-between gap-2 border-b border-border py-2" key={group.en}>
                <span>{locale === "ar" ? group.ar : group.en}</span>
                {group.complete ? <CheckCircle2 className="h-4 w-4 text-emerald" aria-label={locale === "ar" ? "مكتمل" : "Complete"} /> : <AlertCircle className="h-4 w-4 text-primary-text" aria-label={locale === "ar" ? "يحتاج مراجعة" : "Needs review"} />}
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
            <Link href="/profile" className="flex min-h-11 items-center gap-2 text-muted hover:text-foreground">
              <Award className="h-5 w-5" strokeWidth={1.7} aria-hidden="true" />
              {locale === "ar" ? "راجع Google Data Analytics" : "Review Google Data Analytics"}
            </Link>
            <Link href="/profile" className="flex min-h-11 items-center gap-2 text-muted hover:text-foreground">
              <IdCard className="h-5 w-5" strokeWidth={1.7} aria-hidden="true" />
              {locale === "ar" ? "أكمل حق العمل" : "Complete work eligibility"}
            </Link>
          </div>
        </div>
      </div>
    </aside>
  );
}
