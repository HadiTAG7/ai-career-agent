"use client";

import { useMemo, useState } from "react";
import {
  FileText,
  Mail,
  MapPin,
  Minus,
  Phone,
  Plus,
  Sparkles,
} from "lucide-react";
import type {
  ApiCareerFact,
  ApiCareerProfile,
  ApiResumeDraftContent,
  ApiResumeDraftSection,
  ApiResumeSectionKey,
  ResumeRewriteMode,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";

export type ResumeCanvasSelection = {
  targetKind: "headline" | "professional_summary" | "bullet";
  sectionKey?: string;
  itemId?: string;
  bulletIndex?: number;
  text: string;
};

type ResumeDocumentCanvasProps = {
  locale: "ar" | "en";
  profile: ApiCareerProfile;
  facts: ApiCareerFact[];
  draft: ApiResumeDraftContent | null;
  contact: { email?: string | null; phone?: string | null; linkedin?: string | null };
  editable?: boolean;
  editingLocked?: boolean;
  selection: ResumeCanvasSelection | null;
  rewriting?: boolean;
  onSelect: (selection: ResumeCanvasSelection) => void;
  onDraftChange: (draft: ApiResumeDraftContent) => void;
  onRewrite: (selection: ResumeCanvasSelection, mode: ResumeRewriteMode, instruction?: string) => void;
};

const sectionOrder: ApiResumeSectionKey[] = [
  "experience",
  "education",
  "project",
  "skill",
  "certification",
  "language",
  "achievement",
];

const sectionLabels: Record<ApiResumeSectionKey, { ar: string; en: string }> = {
  experience: { ar: "الخبرة المهنية", en: "Professional experience" },
  education: { ar: "التعليم", en: "Education" },
  project: { ar: "المشاريع", en: "Projects" },
  skill: { ar: "المهارات", en: "Skills" },
  certification: { ar: "الشهادات", en: "Certifications" },
  language: { ar: "اللغات", en: "Languages" },
  achievement: { ar: "الإنجازات", en: "Achievements" },
};

function fallbackDraft(
  locale: "ar" | "en",
  profile: ApiCareerProfile,
  facts: ApiCareerFact[],
): ApiResumeDraftContent {
  const sections: ApiResumeDraftSection[] = [];
  for (const key of sectionOrder) {
    const matches = facts.filter((fact) => fact.category === key);
    if (!matches.length) continue;
    sections.push({
      key,
      title: sectionLabels[key][locale],
      items: matches.map((fact) => ({
        id: fact.id,
        title: fact.label,
        organization: typeof fact.structured_value.organization === "string"
          ? fact.structured_value.organization
          : null,
        date_range: typeof fact.structured_value.date_range === "string"
          ? fact.structured_value.date_range
          : null,
        location: typeof fact.structured_value.location === "string"
          ? fact.structured_value.location
          : null,
        bullets: fact.detail ? [fact.detail] : [],
        evidence_handles: [`fact:${fact.id}`],
      })),
    });
  }
  return {
    headline: profile.headline ?? (locale === "ar" ? "عنوانك المهني" : "Your professional headline"),
    professional_summary: locale === "ar"
      ? "سيتكوّن ملخصك المهني هنا أثناء حديثنا. كل إجابة تؤكدها تضيف معنى أقوى إلى سيرتك."
      : "Your professional summary will take shape here as we talk. Every confirmed answer makes it stronger.",
    summary_evidence_handles: [],
    sections,
  };
}

function selectionMatches(
  current: ResumeCanvasSelection | null,
  target: Omit<ResumeCanvasSelection, "text">,
) {
  return current?.targetKind === target.targetKind
    && current.sectionKey === target.sectionKey
    && current.itemId === target.itemId
    && current.bulletIndex === target.bulletIndex;
}

function RewriteToolbar({
  locale,
  selection,
  rewriting,
  onRewrite,
}: {
  locale: "ar" | "en";
  selection: ResumeCanvasSelection;
  rewriting: boolean;
  onRewrite: (selection: ResumeCanvasSelection, mode: ResumeRewriteMode, instruction?: string) => void;
}) {
  const actions: Array<{ mode: ResumeRewriteMode; ar: string; en: string; instruction?: { ar: string; en: string } }> = [
    { mode: "stronger", ar: "قوّها", en: "Strengthen" },
    { mode: "shorter", ar: "اختصرها", en: "Shorten" },
    { mode: "custom", ar: "اسألني لتحسينها", en: "Ask to improve", instruction: { ar: "اسألني سؤالًا واحدًا يساعدك على تحسين هذا النص.", en: "Ask me one question that will help you improve this text." } },
  ];
  return (
    <div className="mt-2 inline-flex max-w-full flex-wrap items-center gap-1 rounded-lg border border-slate-200 bg-white p-1.5 text-[11px] shadow-lg" role="toolbar" aria-label={locale === "ar" ? "تحسين النص المحدد" : "Improve selected text"}>
      {actions.map((action) => (
        <button
          key={action.mode}
          type="button"
          className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 font-semibold text-slate-700 transition hover:bg-emerald-pale hover:text-emerald disabled:opacity-50"
          disabled={rewriting}
          onClick={() => onRewrite(selection, action.mode, action.instruction?.[locale])}
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          {locale === "ar" ? action.ar : action.en}
        </button>
      ))}
    </div>
  );
}

export function ResumeDocumentCanvas({
  locale,
  profile,
  facts,
  draft,
  contact,
  editable = false,
  editingLocked = false,
  selection,
  rewriting = false,
  onSelect,
  onDraftChange,
  onRewrite,
}: ResumeDocumentCanvasProps) {
  const [zoom, setZoom] = useState(100);
  const displayedDraft = useMemo(
    () => draft ?? fallbackDraft(locale, profile, facts),
    [draft, facts, locale, profile],
  );
  const canEdit = editable && Boolean(draft);

  function commit(next: ApiResumeDraftContent) {
    if (canEdit && !editingLocked) onDraftChange(next);
  }

  function updateItemBullet(sectionIndex: number, itemIndex: number, bulletIndex: number, value: string) {
    commit({
      ...displayedDraft,
      sections: displayedDraft.sections.map((section, currentSectionIndex) => (
        currentSectionIndex === sectionIndex
          ? {
            ...section,
            items: section.items.map((item, currentItemIndex) => (
              currentItemIndex === itemIndex
                ? {
                  ...item,
                  bullets: item.bullets.map((bullet, currentBulletIndex) => (
                    currentBulletIndex === bulletIndex ? value : bullet
                  )),
                }
                : item
            )),
          }
          : section
      )),
    });
  }

  const canvasStyle = { zoom: zoom / 100 } as React.CSSProperties & { zoom: number };

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[#d9e2ec] bg-[#f7f9fb]" aria-label={locale === "ar" ? "معاينة السيرة الحية" : "Live resume preview"}>
      <header className="flex min-h-[50px] items-center justify-between gap-3 border-b border-[#d9e2ec] bg-white px-4 text-xs text-slate-600">
        <div className="inline-flex items-center gap-2 font-semibold text-ink">
          <FileText className="h-4 w-4 text-emerald" aria-hidden="true" />
          {locale === "ar" ? "معاينة ATS الحية" : "Live ATS preview"}
        </div>
        <div className="inline-flex items-center overflow-hidden rounded-md border border-[#d9e2ec] bg-white">
          <button type="button" className="grid h-8 w-9 place-items-center hover:bg-slate-50 disabled:opacity-40" aria-label={locale === "ar" ? "تصغير" : "Zoom out"} disabled={zoom <= 80} onClick={() => setZoom((value) => Math.max(80, value - 10))}><Minus className="h-3.5 w-3.5" /></button>
          <span className="min-w-14 border-x border-[#d9e2ec] px-2 text-center font-semibold text-ink">{zoom}%</span>
          <button type="button" className="grid h-8 w-9 place-items-center hover:bg-slate-50 disabled:opacity-40" aria-label={locale === "ar" ? "تكبير" : "Zoom in"} disabled={zoom >= 120} onClick={() => setZoom((value) => Math.min(120, value + 10))}><Plus className="h-3.5 w-3.5" /></button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-3 sm:p-6">
        <article
          className="mx-auto min-h-[820px] w-full max-w-[720px] border border-slate-200 bg-white px-7 py-9 text-[12px] leading-[1.65] text-[#192536] shadow-[0_3px_14px_rgba(15,23,42,0.12)] sm:px-10"
          dir={locale === "ar" ? "rtl" : "ltr"}
          style={canvasStyle}
        >
          <header className="text-center">
            <h2 className="text-[25px] font-bold leading-tight tracking-[-0.02em] text-[#101828]">{profile.full_name}</h2>
            {canEdit ? (
              <input
                aria-label={locale === "ar" ? "العنوان المهني" : "Professional headline"}
                className={cn(
                  "mx-auto mt-2 block w-full max-w-md border-0 bg-transparent text-center text-[16px] font-semibold text-emerald outline-none transition focus:ring-0",
                  selectionMatches(selection, { targetKind: "headline" }) && "rounded bg-emerald-pale",
                )}
                disabled={editingLocked}
                value={displayedDraft.headline}
                onFocus={() => onSelect({ targetKind: "headline", text: displayedDraft.headline })}
                onChange={(event) => commit({ ...displayedDraft, headline: event.target.value })}
              />
            ) : <p className="mt-2 text-[16px] font-semibold text-emerald">{displayedDraft.headline}</p>}
            <div className="mt-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[10px] text-slate-600">
              {contact.email ? <span className="inline-flex items-center gap-1"><Mail className="h-3 w-3" />{contact.email}</span> : null}
              {contact.phone ? <span className="inline-flex items-center gap-1"><Phone className="h-3 w-3" />{contact.phone}</span> : null}
              {profile.city ? <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{profile.city}</span> : null}
              {contact.linkedin ? <span>{contact.linkedin}</span> : null}
            </div>
          </header>

          <section className="mt-7 border-t border-slate-400 pt-3">
            <h3 className="text-[15px] font-bold text-[#101828]">{locale === "ar" ? "ملخص مهني" : "Professional summary"}</h3>
            {canEdit ? (
              <div className={cn("mt-1.5 rounded transition", selectionMatches(selection, { targetKind: "professional_summary" }) && "bg-emerald-pale/70 px-2 py-1") }>
                <textarea
                  aria-label={locale === "ar" ? "الملخص المهني" : "Professional summary"}
                  className="block w-full resize-none overflow-hidden border-0 bg-transparent p-0 text-[12px] leading-[1.8] text-slate-700 outline-none focus:ring-0"
                  rows={Math.max(3, Math.ceil(displayedDraft.professional_summary.length / 90))}
                  disabled={editingLocked}
                  value={displayedDraft.professional_summary}
                  onFocus={() => onSelect({ targetKind: "professional_summary", text: displayedDraft.professional_summary })}
                  onChange={(event) => commit({ ...displayedDraft, professional_summary: event.target.value })}
                />
                {selectionMatches(selection, { targetKind: "professional_summary" }) && selection ? <RewriteToolbar locale={locale} selection={selection} rewriting={rewriting} onRewrite={onRewrite} /> : null}
              </div>
            ) : <p className="mt-1.5 whitespace-pre-wrap text-slate-700">{displayedDraft.professional_summary}</p>}
          </section>

          {displayedDraft.sections.map((section, sectionIndex) => (
            <section className="mt-6 border-t border-slate-400 pt-3" key={section.key}>
              <h3 className="text-[15px] font-bold text-[#101828]">{section.title}</h3>
              <div className="mt-2.5 space-y-5">
                {section.items.map((item, itemIndex) => (
                  <article key={item.id}>
                    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                      <div>
                        <h4 className="font-bold text-[#101828]">{item.title}</h4>
                        {item.organization ? <p className="text-slate-700">{item.organization}</p> : null}
                      </div>
                      {[item.date_range, item.location].some(Boolean) ? <p className="text-[10px] text-slate-600">{[item.date_range, item.location].filter(Boolean).join(" · ")}</p> : null}
                    </div>
                    {item.bullets.length ? (
                      <ul className="mt-2 list-disc space-y-1 pe-4 text-slate-700">
                        {item.bullets.map((bullet, bulletIndex) => {
                          const target = { targetKind: "bullet" as const, sectionKey: section.key, itemId: item.id, bulletIndex };
                          const selected = selectionMatches(selection, target);
                          return (
                            <li key={`${item.id}-${bulletIndex}`} className={cn("rounded transition", selected && "bg-emerald-pale/80 px-2 py-1")}>
                              {canEdit ? (
                                <textarea
                                  aria-label={locale === "ar" ? `${section.title}، نقطة ${bulletIndex + 1}` : `${section.title}, bullet ${bulletIndex + 1}`}
                                  className="block w-full resize-none overflow-hidden border-0 bg-transparent p-0 text-[12px] leading-[1.75] text-slate-700 outline-none focus:ring-0"
                                  rows={Math.max(1, Math.ceil(bullet.length / 90))}
                                  disabled={editingLocked}
                                  value={bullet}
                                  onFocus={() => onSelect({ ...target, text: bullet })}
                                  onChange={(event) => updateItemBullet(sectionIndex, itemIndex, bulletIndex, event.target.value)}
                                />
                              ) : bullet}
                              {selected && selection ? <RewriteToolbar locale={locale} selection={selection} rewriting={rewriting} onRewrite={onRewrite} /> : null}
                            </li>
                          );
                        })}
                      </ul>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ))}

          {!displayedDraft.sections.length ? (
            <div className="mt-12 border-y border-dashed border-slate-300 py-12 text-center text-sm text-slate-400">
              {locale === "ar" ? "ستظهر أقسام سيرتك هنا مع تقدّم المحادثة" : "Your resume sections will appear here as the conversation progresses"}
            </div>
          ) : null}
        </article>
      </div>
    </section>
  );
}
