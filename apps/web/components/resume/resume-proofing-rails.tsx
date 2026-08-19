"use client";

import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  History,
  RotateCcw,
} from "lucide-react";
import type {
  ApiCareerFact,
  ApiResumeDraftVersion,
  ApiResumeWorkspace,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";

type ProofingVersionRailProps = {
  locale: "ar" | "en";
  versions: ApiResumeDraftVersion[];
  busy: boolean;
  onRestore: (versionId: string) => void;
  className?: string;
};

function versionTime(value: string, locale: "ar" | "en") {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-SA" : "en", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function ProofingVersionRail({
  locale,
  versions,
  busy,
  onRestore,
  className,
}: ProofingVersionRailProps) {
  const recent = versions.slice(0, 3);

  return (
    <aside className={cn("min-h-0 border-border", className)} aria-label={locale === "ar" ? "سجل النسخ" : "Version history"}>
      <div className="hidden h-full min-h-0 flex-col border-e border-border pe-4 xl:flex">
        <div className="flex items-center gap-2 pb-3 text-xs font-semibold text-muted">
          <History className="h-4 w-4" aria-hidden="true" />
          {locale === "ar" ? "النسخ" : "Versions"}
        </div>
        <div className="mt-2 flex-1 space-y-6">
          {recent.map((version, index) => {
            const current = index === 0;
            return (
              <div className="text-xs" key={version.id}>
                <div className={cn("font-semibold", current ? "text-primary-text" : "text-muted")}>
                  {String(version.version).padStart(2, "0")}
                  {current ? <span className="ms-1 font-normal">· {locale === "ar" ? "الحالية" : "current"}</span> : null}
                </div>
                <p className="mt-0.5 text-muted">{versionTime(version.created_at, locale)}</p>
                {!current ? (
                  <button type="button" className="mt-1 inline-flex min-h-8 items-center gap-1 font-semibold text-muted hover:text-primary-text disabled:opacity-45" disabled={busy} onClick={() => onRestore(version.id)}>
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                    {locale === "ar" ? "استعد" : "Restore"}
                  </button>
                ) : null}
              </div>
            );
          })}
          {!recent.length ? <p className="pe-4 text-xs leading-6 text-muted">{locale === "ar" ? "ستظهر النسخ بعد أول حفظ." : "Versions appear after the first save."}</p> : null}
        </div>
      </div>

      <div className="border-y border-border xl:hidden">
        <div className="grid min-h-14 grid-cols-3 divide-x divide-border rtl:divide-x-reverse" dir="rtl">
          {recent.length ? recent.map((version, index) => {
            const current = index === 0;
            return (
              <button
                key={version.id}
                type="button"
                className={cn("inline-flex min-w-0 items-center justify-center gap-2 px-2 text-xs font-semibold", current ? "text-primary-text" : "text-muted hover:text-foreground")}
                disabled={current || busy}
                onClick={() => !current && onRestore(version.id)}
                aria-label={current
                  ? (locale === "ar" ? `النسخة الحالية ${version.version}` : `Current version ${version.version}`)
                  : (locale === "ar" ? `استعد النسخة ${version.version}` : `Restore version ${version.version}`)}
              >
                <span className={cn("h-3 w-3 rounded-full border", current ? "border-primary bg-primary" : "border-slate-400")} aria-hidden="true" />
                <span className="truncate">{String(version.version).padStart(2, "0")}{current ? (locale === "ar" ? " الحالية" : " current") : ""}</span>
              </button>
            );
          }) : <p className="col-span-3 px-3 py-3 text-center text-xs text-muted">{locale === "ar" ? "لا توجد نسخ محفوظة بعد" : "No saved versions yet"}</p>}
        </div>
      </div>
    </aside>
  );
}

type ProofingEvidenceRailProps = {
  locale: "ar" | "en";
  workspace: ApiResumeWorkspace;
  facts: ApiCareerFact[];
  className?: string;
};

export function ProofingEvidenceRail({ locale, workspace, facts, className }: ProofingEvidenceRailProps) {
  const confirmed = facts.filter((fact) => fact.verification_status === "confirmed");
  const needsReview = facts.filter((fact) => fact.verification_status === "extracted");
  const total = confirmed.length + needsReview.length;
  const coverageMissing = Object.values(workspace.section_coverage).filter((complete) => !complete).length;

  return (
    <aside className={cn("min-h-0 border-border", className)} aria-label={locale === "ar" ? "الأدلة" : "Evidence"}>
      <div className="hidden h-full min-h-0 flex-col border-s border-border ps-4 xl:flex">
        <header className="pb-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted">
            <CheckCircle2 className="h-4 w-4 text-emerald" aria-hidden="true" />
            {locale === "ar" ? "الأدلة" : "Evidence"}
          </div>
          <p className="mt-3 text-2xl text-foreground"><span className="text-emerald">{confirmed.length}</span> / {total}</p>
          <p className="text-xs text-muted">{locale === "ar" ? "حقيقة مؤكدة مرتبطة بالمسودة" : "confirmed facts back this draft"}</p>
          {needsReview.length ? (
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-primary-text">
              <AlertCircle className="h-4 w-4" aria-hidden="true" />
              {locale === "ar" ? `${needsReview.length} تحتاج مراجعة` : `${needsReview.length} need review`}
            </p>
          ) : null}
        </header>

        {/* The full fact list is on demand; a permanent wall of rows is noise, the count is the signal. */}
        <details className="group min-h-0 flex-1 overflow-y-auto border-t border-border pt-3">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-semibold text-muted hover:text-foreground [&::-webkit-details-marker]:hidden">
            <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true" />
            {locale === "ar" ? "عرض القائمة" : "Show the list"}
          </summary>
          <ol className="mt-3 space-y-2">
            {confirmed.map((fact) => (
              <li className="flex items-start gap-1.5 text-xs leading-5" key={fact.id}>
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald" aria-label={locale === "ar" ? "مؤكدة" : "Confirmed"} />
                <span className="min-w-0 truncate text-foreground" title={fact.label}>{fact.label}</span>
              </li>
            ))}
            {needsReview.map((fact) => (
              <li className="flex items-start gap-1.5 text-xs leading-5" key={fact.id}>
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary-text" aria-label={locale === "ar" ? "تحتاج مراجعة" : "Needs review"} />
                <span className="min-w-0 truncate text-primary-text" title={fact.label}>{fact.label}</span>
              </li>
            ))}
            {!confirmed.length && !needsReview.length ? <li className="text-xs leading-6 text-muted">{locale === "ar" ? "لا توجد حقائق مؤكدة بعد." : "No confirmed facts yet."}</li> : null}
          </ol>
        </details>
      </div>

      <div className="border-y border-border px-4 py-3 xl:hidden">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-6 w-6 text-emerald" aria-hidden="true" />
            <p className="text-sm text-foreground"><strong className="text-xl text-emerald">{confirmed.length}</strong> / {total} {locale === "ar" ? "حقيقة مؤكدة" : "confirmed facts"}</p>
          </div>
          {needsReview.length || coverageMissing ? (
            <span className="inline-flex items-center gap-2 text-xs text-primary-text"><AlertCircle className="h-5 w-5" />{locale === "ar" ? `${needsReview.length || coverageMissing} تحتاج مراجعة` : `${needsReview.length || coverageMissing} need review`}</span>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
