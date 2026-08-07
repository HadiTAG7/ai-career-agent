"use client";

import Link from "next/link";
import { ChevronDown, ChevronLeft, FileCheck2, MapPin } from "lucide-react";
import { useState } from "react";
import { useLocale } from "@/lib/i18n";
import type { Job, JobRecommendation } from "@/lib/types";
import { cn } from "@/lib/utils";

const recommendationCopy: Record<JobRecommendation, { ar: string; en: string }> = {
  apply_now: { ar: "تقدّم الآن", en: "Apply now" },
  improve_then_apply: { ar: "حسّن ثم تقدّم", en: "Improve, then apply" },
  low_return: { ar: "عائد منخفض", en: "Low return" },
  need_information: { ar: "نحتاج معلومات", en: "Need information" },
};

export function JobRow({ job }: { job: Job }) {
  const { locale, text } = useLocale();
  const [expanded, setExpanded] = useState(false);
  const analyzed = job.isDemo || Boolean(job.analysisId);
  const positive = job.recommendation === "apply_now";

  return (
    <article className="border-b border-border">
      <div className="grid items-center gap-4 py-5 md:grid-cols-[minmax(190px,1.3fr)_minmax(130px,.8fr)_minmax(150px,.9fr)_minmax(145px,.8fr)_44px]">
        <div>
          <Link href={`/jobs/${job.id}`} className="rounded font-bold text-ink hover:text-emerald">
            {text(job.title)}
          </Link>
          <div className="mt-1 flex items-center gap-1 text-xs text-muted">
            <MapPin className="h-3.5 w-3.5" aria-hidden="true" /> {text(job.location)}
          </div>
        </div>
        <div>
          <div className="flex items-center gap-2">
            <strong className="text-lg font-semibold">{analyzed ? `${job.coverage}%` : "—"}</strong>
            <span className="text-xs text-muted">
              {analyzed ? (locale === "ar" ? "تغطية" : "coverage") : (locale === "ar" ? "لم تُحلل" : "not analyzed")}
            </span>
          </div>
          {analyzed ? (
            <div className="mt-2 h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-emerald" style={{ width: `${job.coverage}%` }} />
            </div>
          ) : null}
        </div>
        <div className="hidden text-sm md:block">
          <span className="block font-medium">{text(job.source)}</span>
          <span className="block text-xs text-muted">{text(job.freshness)}</span>
        </div>
        <Link
          href={`/jobs/${job.id}`}
          className={cn(
            "inline-flex min-h-11 items-center justify-center gap-2 justify-self-start rounded-lg border px-4 text-sm font-semibold md:justify-self-auto",
            positive ? "border-emerald text-emerald hover:bg-emerald-pale" : "border-amber text-amber hover:bg-amber-pale"
          )}
        >
          {analyzed ? text(recommendationCopy[job.recommendation]) : (locale === "ar" ? "فتح الوظيفة" : "Open job")}
          <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
        </Link>
        <button
          className="absolute end-5 mt-20 grid h-11 w-11 place-items-center rounded-lg hover:bg-slate-50 md:static md:mt-0"
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-label={locale === "ar" ? "عرض ملخص الدليل" : "Show evidence summary"}
          aria-expanded={expanded}
        >
          <ChevronDown className={cn("h-5 w-5 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
        </button>
      </div>
      {expanded ? (
        <div className="mb-4 flex items-start gap-3 rounded-lg bg-slate-50 p-4 text-sm">
          <FileCheck2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald" aria-hidden="true" />
          <p>
            {analyzed
              ? (locale === "ar"
                ? `النتيجة مبنية على تغطية ${job.coverage}% من المتطلبات الظاهرة في الوصف، باستخدام حقائق مؤكدة فقط.`
                : `This result covers ${job.coverage}% of visible requirements and uses confirmed facts only.`)
              : (locale === "ar" ? "لم تُحلل هذه الوظيفة بعد." : "This job has not been analyzed yet.")}
          </p>
        </div>
      ) : null}
    </article>
  );
}
