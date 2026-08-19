"use client";

import Link from "next/link";
import { ChevronDown, ChevronLeft, FileCheck2 } from "lucide-react";
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
    <article className="relative border-b border-border last:border-b-0">
      <div className="grid items-center gap-3 px-3 py-4 md:grid-cols-[minmax(160px,1.25fr)_minmax(105px,.8fr)_minmax(110px,.8fr)_minmax(105px,.75fr)_minmax(125px,.9fr)_minmax(100px,.7fr)_44px]">
        <div>
          <Link href={`/jobs/${job.id}`} className="font-bold text-foreground transition-colors hover:text-primary-text">
            {text(job.title)}
          </Link>
          <p className="mt-1 text-xs text-muted md:hidden">{text(job.company)} · {text(job.location)}</p>
        </div>
        <p className="hidden text-sm text-muted md:block">{text(job.company)}</p>
        <p className="hidden text-sm text-muted md:block">{text(job.location)}</p>
        <p className="hidden text-sm text-muted md:block">{job.employmentType ? text(job.employmentType) : "—"}</p>
        <Link
          href={`/jobs/${job.id}`}
          className={cn("inline-flex min-h-11 items-center gap-2 justify-self-start text-sm font-semibold md:justify-self-auto", positive ? "text-emerald" : "text-primary-text")}
        >
          {analyzed ? text(recommendationCopy[job.recommendation]) : (locale === "ar" ? "فتح الوظيفة" : "Open job")}
          <span className="text-xs text-muted">{analyzed ? `${job.coverage}%` : (locale === "ar" ? "لم تُحلل" : "Not analyzed")}</span>
          <ChevronLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
        </Link>
        <span className="hidden text-xs text-muted md:block">{text(job.freshness)}</span>
        <button
          className="absolute end-2 top-[62px] grid h-11 w-11 place-items-center text-muted transition-colors hover:text-foreground md:static md:mt-0"
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-label={locale === "ar" ? "عرض ملخص الدليل" : "Show evidence summary"}
          aria-expanded={expanded}
        >
          <ChevronDown className={cn("h-5 w-5 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
        </button>
      </div>
      {expanded ? (
        <div className="mx-3 mb-4 flex items-start gap-3 border-t border-border pt-4 text-sm text-muted">
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
