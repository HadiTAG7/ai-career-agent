"use client";

import { Bookmark, CalendarCheck2, FileCheck2, Send } from "lucide-react";
import { useLocale } from "@/lib/i18n";
import type { DashboardStageCounts } from "@/lib/types";

const demoCounts: DashboardStageCounts = { saved: 12, ready: 6, applied: 4, interviews: 2 };

export function ApplicationStageRail({ counts = demoCounts }: { counts?: DashboardStageCounts }) {
  const { locale } = useLocale();
  const stages = [
    { ar: "محفوظة", en: "Saved", count: counts.saved, icon: Bookmark },
    { ar: "جاهزة", en: "Ready", count: counts.ready, icon: FileCheck2 },
    { ar: "تم التقديم", en: "Applied", count: counts.applied, icon: Send },
    { ar: "مقابلات", en: "Interviews", count: counts.interviews, icon: CalendarCheck2 },
  ];

  return (
    <div className="grid grid-cols-4 gap-2" aria-label={locale === "ar" ? "رحلة التقديم" : "Application journey"}>
      {stages.map((stage, index) => {
        const Icon = stage.icon;
        return (
          <div className="relative text-center" key={stage.en}>
            {index < stages.length - 1 ? <span className="absolute start-[58%] top-6 hidden w-[84%] border-t border-dashed border-muted md:block" aria-hidden="true" /> : null}
            <span className="relative mx-auto grid h-12 w-12 place-items-center rounded-full border border-border bg-white">
              <Icon className="h-5 w-5" strokeWidth={1.6} aria-hidden="true" />
            </span>
            <span className="mt-2 block text-xs text-muted">{locale === "ar" ? stage.ar : stage.en}</span>
            <strong className="mt-1 block text-lg">{stage.count}</strong>
          </div>
        );
      })}
    </div>
  );
}
