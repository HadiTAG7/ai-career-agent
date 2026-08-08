"use client";

import { ChevronDown, FileCheck2, Pencil } from "lucide-react";
import { useState } from "react";
import { StatusLabel } from "@/components/ui/status-label";
import { useLocale } from "@/lib/i18n";
import type { JobRequirement, RequirementStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const labels: Record<"ar" | "en", Record<RequirementStatus, string>> = {
  ar: { supported: "تم التحقق", partial: "متوافق جزئيًا", unsupported: "غير مدعوم", unknown: "غير معلوم" },
  en: { supported: "Verified", partial: "Partial match", unsupported: "Unsupported", unknown: "Unknown" },
};

const categoryLabels: Record<JobRequirement["category"], { ar: string; en: string }> = {
  skill: { ar: "مهارة", en: "Skill" },
  experience: { ar: "خبرة", en: "Experience" },
  education: { ar: "تعليم", en: "Education" },
  certification: { ar: "شهادة", en: "Certification" },
  language: { ar: "لغة", en: "Language" },
  location: { ar: "موقع", en: "Location" },
  eligibility: { ar: "أهلية", en: "Eligibility" },
  other: { ar: "أخرى", en: "Other" },
};

export function RequirementRow({ requirement, reviewMode = false, selected, onSelect }: { requirement: JobRequirement; reviewMode?: boolean; selected: boolean; onSelect: () => void }) {
  const { locale, text } = useLocale();
  const [expanded, setExpanded] = useState(false);
  return (
    <article className={cn("relative border-b border-border transition-colors last:border-b-0", selected && "bg-primary/5 before:absolute before:inset-y-0 before:start-0 before:w-0.5 before:bg-primary")}>
      <div className="grid min-h-[76px] items-center gap-3 px-4 py-3 md:grid-cols-[160px_minmax(150px,1fr)_minmax(130px,.7fr)_44px]">
        {reviewMode ? <span className="w-fit border-s-2 border-primary ps-2 text-xs font-semibold text-primary-text">{requirement.kind === "essential" ? (locale === "ar" ? "أساسي" : "Essential") : (locale === "ar" ? "مفضل" : "Preferred")}</span> : <StatusLabel status={requirement.status} labels={labels[locale]} compact />}
        <button className="text-start font-semibold text-foreground transition-colors hover:text-primary-text" onClick={onSelect} type="button">{text(requirement.label)}</button>
        {reviewMode ? <button className="text-start text-sm text-muted hover:text-ink" onClick={onSelect} type="button">{text(categoryLabels[requirement.category])}</button> : <button className="flex items-center gap-2 text-start text-sm text-muted hover:text-ink" onClick={onSelect} type="button">
          {requirement.evidence ? <FileCheck2 className="h-4 w-4 shrink-0" aria-hidden="true" /> : null}
          {requirement.evidence ? text(requirement.evidence) : (locale === "ar" ? "لم يُعثر على دليل" : "No evidence found")}
        </button>}
        {reviewMode ? <button type="button" className="absolute end-4 top-4 grid h-11 w-11 place-items-center text-muted transition-colors hover:text-primary-text md:static md:mt-0" onClick={onSelect} aria-label={locale === "ar" ? "مراجعة المتطلب" : "Review requirement"}><Pencil className="h-4 w-4" aria-hidden="true" /></button> : <button
          type="button"
          className="absolute end-4 top-4 grid h-11 w-11 place-items-center text-muted transition-colors hover:text-foreground md:static md:mt-0"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-label={locale === "ar" ? "عرض تفسير المطابقة" : "Show match explanation"}
        >
          <ChevronDown className={cn("h-5 w-5 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
        </button>}
      </div>
      {expanded && !reviewMode ? <p className="mx-4 mb-4 border-s-2 border-emerald bg-emerald/5 px-4 py-3 text-sm text-muted">{text(requirement.explanation)}</p> : null}
    </article>
  );
}
