"use client";

import { useLocale } from "@/lib/i18n";
import type { DashboardStageCounts } from "@/lib/types";

// Without real data the rail shows an honest empty state, never fabricated pipeline numbers.
const emptyCounts: DashboardStageCounts = { saved: 0, ready: 0, applied: 0, interviews: 0 };

export function ApplicationStageRail({ counts = emptyCounts }: { counts?: DashboardStageCounts }) {
  const { locale } = useLocale();
  const stages = [
    { ar: "محفوظة", en: "Saved", count: counts.saved },
    { ar: "جاهزة", en: "Ready", count: counts.ready },
    { ar: "تم التقديم", en: "Applied", count: counts.applied },
    { ar: "مقابلات", en: "Interviews", count: counts.interviews },
  ];

  return (
    <div className="relative" aria-label={locale === "ar" ? "رحلة التقديم" : "Application journey"}>
      <span className="absolute inset-x-[7%] top-[7px] h-px bg-border" aria-hidden="true" />
      <div className="relative grid grid-cols-4">
      {stages.map((stage) => {
        return (
          <div className="min-w-0 px-1 text-center" key={stage.en}>
            <span className={`mx-auto block h-[15px] w-[15px] rounded-full border ${stage.count > 0 ? "border-primary bg-primary" : "border-border bg-transparent"}`} aria-hidden="true" />
            <span className="mt-3 block truncate text-xs text-muted sm:text-sm">{locale === "ar" ? stage.ar : stage.en}</span>
            <strong className="mt-1 block text-lg font-medium text-foreground">{stage.count}</strong>
          </div>
        );
      })}
      </div>
    </div>
  );
}
