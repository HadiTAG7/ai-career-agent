"use client";

import Link from "next/link";
import { AlertCircle, Award, CheckCircle2, ChevronLeft, IdCard, Link2, ShieldCheck } from "lucide-react";
import { ProgressRing } from "@/components/ui/progress-ring";
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
      <aside className="border-border lg:border-r lg:pr-6" aria-labelledby="evidence-progress-title">
        <section className="rounded-xl border border-border p-5 lg:rounded-none lg:border-0 lg:p-0">
          <div className="flex items-start justify-between gap-4 lg:block">
            <div>
              <h2 id="evidence-progress-title" className="section-title">
                {locale === "ar" ? `جودة ملفك ${data.profileQualityPercent}%` : `Your profile quality is ${data.profileQualityPercent}%`}
              </h2>
              <p className="mt-2 text-sm text-muted">
                {locale === "ar" ? "تقيس تغطية فئات الأدلة الأساسية، لا فرص التوظيف." : "This measures core evidence coverage, not employability."}
              </p>
            </div>
            <ProgressRing
              value={data.profileQualityPercent}
              size="sm"
              label={locale === "ar" ? `جودة الملف ${data.profileQualityPercent} بالمئة` : `Profile quality is ${data.profileQualityPercent} percent`}
            />
          </div>

          <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg bg-slate-50 p-3">
              <dt className="text-muted">{locale === "ar" ? "حقائق مؤكدة" : "Confirmed facts"}</dt>
              <dd className="mt-1 text-xl font-bold text-ink">{data.confirmedFacts}</dd>
            </div>
            <div className="rounded-lg bg-slate-50 p-3">
              <dt className="text-muted">{locale === "ar" ? "تحتاج مراجعة" : "Need review"}</dt>
              <dd className="mt-1 text-xl font-bold text-ink">{factsToReview}</dd>
            </div>
          </dl>
          <Link href="/profile" className="subtle-link mt-4">
            {locale === "ar" ? "عرض تفاصيل الملف" : "View profile details"}
            <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
          </Link>
        </section>

        <section className="mt-6 border-t border-border pt-5" aria-labelledby="attention-title">
          <h2 id="attention-title" className="section-title">{locale === "ar" ? "تحتاج انتباهك" : "Needs your attention"}</h2>
          {data.actionsDue > 0 ? (
            <Link href="/applications" className="mt-4 flex min-h-[74px] items-center gap-3 rounded-lg border border-amber p-3 transition-colors hover:bg-amber-pale">
              <AlertCircle className="h-6 w-6 shrink-0 text-amber" strokeWidth={1.6} aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold">
                  {locale === "ar" ? `${data.actionsDue} إجراءات مستحقة` : `${data.actionsDue} actions due`}
                </span>
                <span className="block text-xs text-muted">{locale === "ar" ? "راجع طلباتك وحدّث الخطوة التالية" : "Review applications and update the next step"}</span>
              </span>
              <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
            </Link>
          ) : (
            <div className="mt-4 flex items-center gap-3 rounded-lg border border-border p-4 text-sm">
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald" aria-hidden="true" />
              <span>{locale === "ar" ? "لا توجد إجراءات متأخرة حاليًا." : "No actions are overdue right now."}</span>
            </div>
          )}
        </section>
      </aside>
    );
  }

  return (
    <aside className="border-border lg:border-r lg:pr-6" aria-labelledby="evidence-progress-title">
      <section className="rounded-xl border border-border p-5 lg:rounded-none lg:border-0 lg:p-0">
        <div className="flex items-start justify-between gap-4 lg:block">
          <div>
            <h2 id="evidence-progress-title" className="section-title">
              {locale === "ar" ? `ملفك موثّق بنسبة ${profileCompletion}%` : `Your profile is ${profileCompletion}% verified`}
            </h2>
            <p className="mt-2 text-sm text-muted lg:hidden">
              {locale === "ar" ? "النسبة تقيس اكتمال الأدلة، لا فرص التوظيف." : "This measures evidence completeness, not employability."}
            </p>
          </div>
          <ProgressRing value={profileCompletion} size="sm" label={locale === "ar" ? "اكتمال توثيق الملف 82 بالمئة" : "Profile verification is 82 percent"} />
        </div>

        <div className="mt-5 hidden gap-2 lg:grid">
          {groups.map((group) => (
            <div className="flex items-center justify-between py-1 text-sm" key={group.en}>
              <span>{locale === "ar" ? group.ar : group.en}</span>
              {group.complete ? (
                <CheckCircle2 className="h-4 w-4 text-emerald" aria-label={locale === "ar" ? "مكتمل" : "Complete"} />
              ) : (
                <AlertCircle className="h-4 w-4 text-amber" aria-label={locale === "ar" ? "يحتاج مراجعة" : "Needs review"} />
              )}
            </div>
          ))}
        </div>
        <div className="mt-5 h-2 overflow-hidden rounded-full bg-slate-100 lg:hidden" aria-hidden="true">
          <div className="h-full rounded-full bg-emerald" style={{ width: `${profileCompletion}%` }} />
        </div>
        <Link href="/profile" className="subtle-link mt-3">
          {locale === "ar" ? "عرض تفاصيل التوثيق" : "View verification details"}
          <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
        </Link>
      </section>

      <section className="mt-6 border-t border-border pt-5" aria-labelledby="attention-title">
        <h2 id="attention-title" className="section-title">{locale === "ar" ? "تحتاج انتباهك" : "Needs your attention"}</h2>
        <div className="mt-4 space-y-3">
          <Link href="/profile" className="flex min-h-[74px] items-center gap-3 rounded-lg border border-border p-3 transition-colors hover:border-emerald">
            <Award className="h-6 w-6 shrink-0 text-ink" strokeWidth={1.6} aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">{locale === "ar" ? "راجع Google Data Analytics" : "Review Google Data Analytics"}</span>
              <span className="block text-xs text-muted">{locale === "ar" ? "أضف الرابط والتاريخ للتحقق" : "Add the link and date to verify"}</span>
            </span>
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </Link>
          <Link href="/profile" className="flex min-h-[74px] items-center gap-3 rounded-lg border border-border p-3 transition-colors hover:border-emerald">
            <IdCard className="h-6 w-6 shrink-0 text-ink" strokeWidth={1.6} aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">{locale === "ar" ? "أكمل حق العمل" : "Complete work eligibility"}</span>
              <span className="block text-xs text-muted">{locale === "ar" ? "لن نستنتجه من اسمك أو لغتك" : "We never infer it from your name or language"}</span>
            </span>
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      </section>

      <section className="mt-6 hidden border-t border-border pt-5 lg:block" aria-labelledby="evidence-example-title">
        <h2 id="evidence-example-title" className="text-base font-bold">{locale === "ar" ? "مثال على الربط بالأدلة" : "Evidence mapping example"}</h2>
        <div className="mt-4 flex items-center justify-center gap-2 text-center text-xs">
          <div className="w-[112px] rounded-lg border border-border p-3">
            <span className="font-semibold">Python</span>
            <span className="mt-1 block text-muted">{locale === "ar" ? "متطلب وظيفة" : "Job requirement"}</span>
          </div>
          <Link2 className="h-5 w-5 text-emerald" aria-hidden="true" />
          <div className="w-[112px] rounded-lg border border-border p-3">
            <span className="font-semibold">{locale === "ar" ? "تدريب تعاوني" : "Internship"}</span>
            <span className="mt-1 block text-muted">{locale === "ar" ? "حقيقة مؤكدة" : "Confirmed fact"}</span>
          </div>
        </div>
        <Link href="/profile" className="subtle-link mt-3">
          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          {locale === "ar" ? "فتح درج الأدلة" : "Open evidence drawer"}
        </Link>
      </section>
    </aside>
  );
}
