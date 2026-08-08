"use client";

import Link from "next/link";
import { AlertCircle, Check, Circle } from "lucide-react";
import { useLocale } from "@/lib/i18n";
import type { CareerPathWorkspace, DashboardData } from "@/lib/types";
import { cn } from "@/lib/utils";

type StageState = "complete" | "current" | "pending" | "unknown";

type CareerEvidencePathProps = {
  connected: boolean;
  data?: DashboardData;
  workspace?: CareerPathWorkspace | null;
  unavailable?: boolean;
};

export function CareerEvidencePath({ connected, data, workspace, unavailable = false }: CareerEvidencePathProps) {
  const { locale } = useLocale();
  const messages = workspace?.conversation?.messages ?? [];
  const suggestionCount = messages.reduce((count, message) => count + message.suggestions.length, 0);
  const hasFacts = Boolean((workspace?.confirmed_fact_count ?? data?.confirmedFacts ?? 0) > 0);
  const hasOpportunities = Boolean(data?.topOpportunities.length);
  const applicationCount = data
    ? Object.values(data.applicationStages).reduce((total, count) => total + count, 0)
    : 0;

  const stages: Array<{ ar: string; en: string; state: StageState }> = connected && !unavailable
    ? [
        { ar: "الملف", en: "Profile", state: "complete" },
        { ar: "السيرة", en: "Resume", state: hasFacts ? "complete" : "current" },
        { ar: "المسار", en: "Path", state: suggestionCount > 0 ? "complete" : hasFacts ? "current" : "pending" },
        { ar: "الفرص", en: "Opportunities", state: hasOpportunities ? "complete" : suggestionCount > 0 ? "current" : "pending" },
        { ar: "التقديم", en: "Applications", state: applicationCount > 0 ? "complete" : hasOpportunities ? "current" : "pending" },
      ]
    : [
        { ar: "الملف", en: "Profile", state: "unknown" },
        { ar: "السيرة", en: "Resume", state: "unknown" },
        { ar: "المسار", en: "Path", state: "unknown" },
        { ar: "الفرص", en: "Opportunities", state: "unknown" },
        { ar: "التقديم", en: "Applications", state: "unknown" },
      ];

  const stateLabel: Record<StageState, { ar: string; en: string }> = {
    complete: { ar: "مكتمل", en: "Complete" },
    current: { ar: "الخطوة الحالية", en: "Current step" },
    pending: { ar: "لم يبدأ", en: "Not started" },
    unknown: { ar: "غير متاح", en: "Unavailable" },
  };

  return (
    <section className="border-t border-border pt-4" aria-labelledby="career-evidence-path-title">
      <div className="flex items-start justify-between gap-5">
        <div>
          <p className="text-xs text-muted">{locale === "ar" ? "مرجع 03" : "Reference 03"}</p>
          <h2 id="career-evidence-path-title" className="mt-3 text-2xl font-bold text-foreground">
            {locale === "ar" ? "مسار الأدلة" : "Evidence path"}
          </h2>
          <p className="mt-1 text-sm text-muted">
            {locale === "ar" ? "مسار التحقق من ملفك المهني خطوة بخطوة." : "A step-by-step view of your career evidence."}
          </p>
        </div>
        {unavailable ? <AlertCircle className="mt-7 h-5 w-5 shrink-0 text-danger" aria-hidden="true" /> : null}
      </div>

      <div className="relative mt-6">
        <span className="absolute bottom-[15px] inset-x-[9%] hidden h-px bg-border md:block" aria-hidden="true" />
        <span className="absolute bottom-8 end-[15px] top-8 w-px bg-border md:hidden" aria-hidden="true" />
        <div className="relative grid gap-0 md:grid-cols-5">
          {stages.map((stage) => {
            const Marker = stage.state === "pending" ? Circle : stage.state === "unknown" ? AlertCircle : Check;
            return (
              <div className="grid min-h-[96px] grid-cols-[minmax(0,1fr)_32px] items-start gap-4 text-end md:block md:min-h-0 md:text-center" key={stage.en}>
                <div>
                  <p className={cn("font-semibold", stage.state === "current" ? "text-foreground" : "text-muted")}>{locale === "ar" ? stage.ar : stage.en}</p>
                  <p className={cn("mt-1 text-sm", stage.state === "current" ? "text-primary-text" : "text-muted")}>{locale === "ar" ? stateLabel[stage.state].ar : stateLabel[stage.state].en}</p>
                </div>
                <span className={cn(
                  "relative z-10 mt-1 grid h-8 w-8 place-items-center rounded-full border bg-background md:mx-auto md:mt-3",
                  stage.state === "complete" && "border-emerald text-emerald",
                  stage.state === "current" && "border-primary text-primary-text",
                  stage.state === "pending" && "border-border text-muted",
                  stage.state === "unknown" && "border-danger text-danger",
                )}>
                  <Marker className="h-4 w-4" strokeWidth={1.8} aria-hidden="true" />
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {!connected || unavailable ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3 text-sm">
          <p className="text-muted">
            {locale === "ar" ? "تعذر تحميل حالة مسارك؛ لن نعرض حالة تجريبية بدلًا من بياناتك." : "Your path status is unavailable; demo state will not replace your data."}
          </p>
          <Link href="/career-path" className="inline-flex min-h-11 items-center text-sm font-semibold text-primary-text hover:text-foreground">
            {locale === "ar" ? "فتح مساري" : "Open My path"}
          </Link>
        </div>
      ) : null}
    </section>
  );
}
