"use client";

import {
  AlertCircle,
  CheckCircle2,
  FileCheck2,
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

function versionDate(value: string, locale: "ar" | "en") {
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-SA" : "en", {
    month: "numeric",
    day: "numeric",
    year: "2-digit",
  }).format(new Date(value));
}

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
  const recent = versions.slice(0, 4);

  return (
    <aside className={cn("min-h-0 border-border", className)} aria-label={locale === "ar" ? "سجل النسخ" : "Version history"}>
      <div className="hidden h-full min-h-0 flex-col border-e border-border pe-4 xl:flex">
        <div className="flex items-center gap-2 border-b border-border pb-3 text-xs font-semibold text-foreground">
          <History className="h-4 w-4 text-primary-text" aria-hidden="true" />
          {locale === "ar" ? "سجل النسخ" : "Version history"}
        </div>
        <div className="relative mt-5 flex-1 space-y-7 before:absolute before:bottom-5 before:end-[5px] before:top-3 before:w-px before:bg-border">
          {recent.map((version, index) => {
            const current = index === 0;
            return (
              <div className="relative pe-7 text-xs" key={version.id}>
                <span className={cn("absolute end-0 top-1 h-3 w-3 rounded-full border bg-background", current ? "border-primary ring-2 ring-primary/20" : "border-slate-400")} aria-hidden="true" />
                <div className={cn("flex items-center justify-between gap-2 font-semibold", current ? "text-primary-text" : "text-muted")}>
                  <span>{locale === "ar" ? "نسخة" : "Version"} {String(version.version).padStart(2, "0")}</span>
                  {current ? <span>{locale === "ar" ? "الحالية" : "Current"}</span> : null}
                </div>
                <p className="mt-1 text-muted">{versionTime(version.created_at, locale)}</p>
                <p className="text-muted">{versionDate(version.created_at, locale)}</p>
                {!current ? (
                  <button type="button" className="mt-2 inline-flex min-h-8 items-center gap-1 font-semibold text-foreground hover:text-primary-text disabled:opacity-45" disabled={busy} onClick={() => onRestore(version.id)}>
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                    {locale === "ar" ? "استعد" : "Restore"}
                  </button>
                ) : null}
              </div>
            );
          })}
          {!recent.length ? <p className="pe-6 text-xs leading-6 text-muted">{locale === "ar" ? "ستظهر النسخ بعد أول حفظ للمسودة." : "Versions appear after the first draft save."}</p> : null}
        </div>
      </div>

      <div className="border-y border-border xl:hidden">
        <div className="grid min-h-14 grid-cols-4 divide-x divide-x-reverse divide-border" dir="rtl">
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
                <span className={cn("h-4 w-4 rounded-full border", current ? "border-primary ring-2 ring-primary/20" : "border-slate-400")} aria-hidden="true" />
                <span className="truncate">{String(version.version).padStart(2, "0")}{current ? (locale === "ar" ? " الحالية" : " current") : ""}</span>
              </button>
            );
          }) : <p className="col-span-4 px-3 py-3 text-center text-xs text-muted">{locale === "ar" ? "لا توجد نسخ محفوظة بعد" : "No saved versions yet"}</p>}
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
  const needsReview = facts.filter((fact) => fact.verification_status !== "confirmed");
  const total = facts.length;
  const coverageMissing = Object.values(workspace.section_coverage).filter((complete) => !complete).length;

  return (
    <aside className={cn("min-h-0 border-border", className)} aria-label={locale === "ar" ? "الأدلة" : "Evidence"}>
      <div className="hidden h-full min-h-0 flex-col border-s border-border ps-4 xl:flex">
        <header className="border-b border-border pb-4">
          <div className="flex items-center gap-2 text-primary-text"><FileCheck2 className="h-4 w-4" aria-hidden="true" /><h2 className="text-sm font-bold">{locale === "ar" ? "الأدلة" : "Evidence"}</h2></div>
          <p className="mt-1 text-[11px] text-muted">{locale === "ar" ? "الحقائق المؤكدة" : "Confirmed facts"}</p>
          <p className="mt-3 text-2xl text-foreground"><span className="text-emerald">{confirmed.length}</span> / {total}</p>
          <p className="text-xs text-muted">{locale === "ar" ? "حقيقة مؤكدة" : "confirmed facts"}</p>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto py-3">
          <ol className="space-y-2.5">
            {confirmed.map((fact, index) => (
              <li className="grid grid-cols-[2rem_1fr_auto] items-start gap-1.5 text-[10px] leading-5" key={fact.id}>
                <span className="font-semibold text-emerald">{String(index + 1).padStart(2, "0")}</span>
                <span className="min-w-0 truncate text-foreground" title={fact.label}>{fact.label}</span>
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 text-emerald" aria-label={locale === "ar" ? "مؤكدة" : "Confirmed"} />
              </li>
            ))}
            {!confirmed.length ? <li className="text-xs leading-6 text-muted">{locale === "ar" ? "لا توجد حقائق مؤكدة بعد." : "No confirmed facts yet."}</li> : null}
          </ol>

          {needsReview.length ? (
            <div className="mt-4 border-t border-border pt-3">
              <p className="mb-2 text-[11px] text-muted">{locale === "ar" ? "تحتاج مراجعة" : "Needs review"}</p>
              {needsReview.map((fact, index) => (
                <div className="grid grid-cols-[2rem_1fr_auto] items-start gap-1.5 py-1.5 text-[10px] leading-5" key={fact.id}>
                  <span className="font-semibold text-primary-text">{String(confirmed.length + index + 1).padStart(2, "0")}</span>
                  <span className="min-w-0 text-primary-text">{fact.label}</span>
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 text-primary-text" aria-label={locale === "ar" ? "تحتاج مراجعة" : "Needs review"} />
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <footer className="border-t border-border pt-4">
          <p className="text-xs font-semibold text-primary-text">{locale === "ar" ? "وعد الأدلة" : "Evidence promise"}</p>
          <p className="mt-1 text-[11px] leading-5 text-muted">{locale === "ar" ? "نعمل بالأدلة بلا ادّعاء." : "Evidence before claims."}</p>
          <p className="mt-3 text-xl text-foreground"><span className="text-emerald">{confirmed.length}</span> / {total}</p>
        </footer>
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
