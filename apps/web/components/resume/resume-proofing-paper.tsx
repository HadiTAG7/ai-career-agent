"use client";

import { useMemo, useState } from "react";
import {
  FileText,
  Mail,
  MapPin,
  Minus,
  PencilLine,
  Phone,
  Plus,
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
import type { ResumeCanvasSelection } from "@/components/resume/resume-document-canvas";

type ResumeProofingPaperProps = {
  locale: "ar" | "en";
  documentLanguage: "ar" | "en";
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
  experience: { ar: "الخبرة العملية", en: "Experience" },
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

function ProofToolbar({
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
  const actions: Array<{
    mode: ResumeRewriteMode;
    ar: string;
    en: string;
    instruction?: { ar: string; en: string };
  }> = [
    { mode: "stronger", ar: "قوّها", en: "Strengthen" },
    { mode: "shorter", ar: "اختصرها", en: "Shorten" },
    {
      mode: "custom",
      ar: "اسألني",
      en: "Ask me",
      instruction: {
        ar: "اسألني سؤالًا واحدًا يساعدك على تحسين هذا النص.",
        en: "Ask me one question that will help you improve this text.",
      },
    },
  ];

  return (
    <div
      className="mt-2 flex max-w-full flex-wrap items-center border-y border-border bg-background text-[10px] text-foreground shadow-[0_8px_18px_rgba(7,17,31,0.14)]"
      role="toolbar"
      aria-label={locale === "ar" ? "تحسين النص المحدد" : "Improve selected text"}
    >
      {actions.map((action) => (
        <button
          key={action.mode}
          type="button"
          className="inline-flex min-h-9 flex-1 items-center justify-center gap-1.5 border-e border-border px-2 font-semibold transition-colors last:border-e-0 hover:bg-primary hover:text-primary-foreground disabled:opacity-45"
          disabled={rewriting}
          onClick={() => onRewrite(selection, action.mode, action.instruction?.[locale])}
        >
          <PencilLine className="h-3.5 w-3.5" aria-hidden="true" />
          {locale === "ar" ? action.ar : action.en}
        </button>
      ))}
    </div>
  );
}

export function ResumeProofingPaper({
  locale,
  documentLanguage,
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
}: ResumeProofingPaperProps) {
  const [zoom, setZoom] = useState(100);
  const displayedDraft = useMemo(
    () => draft ?? fallbackDraft(documentLanguage, profile, facts),
    [documentLanguage, draft, facts, profile],
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
    <section
      className="flex min-h-0 flex-col overflow-hidden"
      aria-label={locale === "ar" ? "معاينة السيرة الحية" : "Live resume preview"}
    >
      <header className="hidden min-h-[44px] items-center justify-between gap-3 border-y border-border px-3 text-[11px] text-muted xl:flex">
        <div className="inline-flex items-center gap-2 font-semibold text-foreground">
          <FileText className="h-4 w-4 text-primary-text" aria-hidden="true" />
          {locale === "ar" ? "ورقة التحرير" : "Proofing paper"}
        </div>
        <div className="inline-flex items-center">
          <button type="button" className="grid h-8 w-8 place-items-center border-s border-border hover:text-primary-text disabled:opacity-40" aria-label={locale === "ar" ? "تصغير" : "Zoom out"} disabled={zoom <= 80} onClick={() => setZoom((value) => Math.max(80, value - 10))}><Minus className="h-3.5 w-3.5" /></button>
          <span className="min-w-12 border-x border-border px-2 text-center font-semibold text-foreground">{zoom}%</span>
          <button type="button" className="grid h-8 w-8 place-items-center border-e border-border hover:text-primary-text disabled:opacity-40" aria-label={locale === "ar" ? "تكبير" : "Zoom in"} disabled={zoom >= 120} onClick={() => setZoom((value) => Math.min(120, value + 10))}><Plus className="h-3.5 w-3.5" /></button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-0 py-3 sm:px-3 xl:px-2 xl:py-4">
        <article
          className="mx-auto min-h-[790px] w-full max-w-[650px] border border-[#d8dde5] bg-white px-6 py-8 text-[11px] leading-[1.72] text-[#1b2533] shadow-[0_16px_38px_rgba(0,0,0,0.2)] sm:px-9 xl:px-8"
          dir={documentLanguage === "ar" ? "rtl" : "ltr"}
          lang={documentLanguage}
          style={canvasStyle}
        >
          <header className="text-center">
            <h2 className="text-[24px] font-bold leading-tight tracking-[-0.02em] text-[#101828]">{profile.full_name}</h2>
            {canEdit ? (
              <input
                aria-label={locale === "ar" ? "العنوان المهني" : "Professional headline"}
                className={cn(
                  "mx-auto mt-2 block w-full max-w-md border-0 bg-transparent text-center text-[14px] font-medium text-[#344054] outline-none",
                  selectionMatches(selection, { targetKind: "headline" }) && "border-b border-[#f6bd2a] bg-[#fff8e6]",
                )}
                disabled={editingLocked}
                value={displayedDraft.headline}
                onFocus={() => onSelect({ targetKind: "headline", text: displayedDraft.headline })}
                onChange={(event) => commit({ ...displayedDraft, headline: event.target.value })}
              />
            ) : <p className="mt-2 text-[14px] font-medium text-[#344054]">{displayedDraft.headline}</p>}
            <div className="mt-4 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[8px] text-[#475467]">
              {contact.email ? <span className="inline-flex items-center gap-1"><Mail className="h-2.5 w-2.5" />{contact.email}</span> : null}
              {contact.phone ? <span className="inline-flex items-center gap-1"><Phone className="h-2.5 w-2.5" />{contact.phone}</span> : null}
              {profile.city ? <span className="inline-flex items-center gap-1"><MapPin className="h-2.5 w-2.5" />{profile.city}</span> : null}
              {contact.linkedin ? <span>{contact.linkedin}</span> : null}
            </div>
          </header>

          <section className="mt-6 border-t border-[#667085] pt-2.5">
            <h3 className="text-[14px] font-bold text-[#101828]">{documentLanguage === "ar" ? "نبذة مهنية" : "Professional summary"}</h3>
            {canEdit ? (
              <div className={cn("relative mt-1", selectionMatches(selection, { targetKind: "professional_summary" }) && "border-b border-[#f6bd2a] bg-[#fff8e6] px-1.5 py-1") }>
                <textarea
                  aria-label={locale === "ar" ? "الملخص المهني" : "Professional summary"}
                  className="block w-full resize-none overflow-hidden border-0 bg-transparent p-0 text-[11px] leading-[1.8] text-[#344054] outline-none"
                  rows={Math.max(3, Math.ceil(displayedDraft.professional_summary.length / 90))}
                  disabled={editingLocked}
                  value={displayedDraft.professional_summary}
                  onFocus={() => onSelect({ targetKind: "professional_summary", text: displayedDraft.professional_summary })}
                  onChange={(event) => commit({ ...displayedDraft, professional_summary: event.target.value })}
                />
                {selectionMatches(selection, { targetKind: "professional_summary" }) && selection ? <ProofToolbar locale={locale} selection={selection} rewriting={rewriting} onRewrite={onRewrite} /> : null}
              </div>
            ) : <p className="mt-1 whitespace-pre-wrap text-[#344054]">{displayedDraft.professional_summary}</p>}
          </section>

          {displayedDraft.sections.map((section, sectionIndex) => (
            <section className="mt-5 border-t border-[#667085] pt-2.5" key={section.key}>
              <h3 className="text-[14px] font-bold text-[#101828]">{section.title}</h3>
              <div className="mt-2 space-y-4">
                {section.items.map((item, itemIndex) => (
                  <article key={item.id}>
                    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                      <div>
                        <h4 className="font-bold text-[#101828]">{item.title}</h4>
                        {item.organization ? <p className="text-[#344054]">{item.organization}</p> : null}
                      </div>
                      {[item.date_range, item.location].some(Boolean) ? <p className="text-[9px] text-[#475467]">{[item.date_range, item.location].filter(Boolean).join(" · ")}</p> : null}
                    </div>
                    {item.bullets.length ? (
                      <ul className="mt-1.5 list-disc space-y-0.5 pe-4 text-[#344054]">
                        {item.bullets.map((bullet, bulletIndex) => {
                          const target = { targetKind: "bullet" as const, sectionKey: section.key, itemId: item.id, bulletIndex };
                          const selected = selectionMatches(selection, target);
                          return (
                            <li key={`${item.id}-${bulletIndex}`} className={cn("relative", selected && "border-b border-[#f6bd2a] bg-[#fff8e6] px-1.5 py-0.5")}>
                              {selected ? <span className="absolute -end-7 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full border border-[#f6bd2a] bg-white text-[9px] font-bold text-[#1b2533]" aria-hidden="true">03</span> : null}
                              {canEdit ? (
                                <textarea
                                  aria-label={locale === "ar" ? `${section.title}، نقطة ${bulletIndex + 1}` : `${section.title}, bullet ${bulletIndex + 1}`}
                                  className="block w-full resize-none overflow-hidden border-0 bg-transparent p-0 text-[11px] leading-[1.75] text-[#344054] outline-none"
                                  rows={Math.max(1, Math.ceil(bullet.length / 90))}
                                  disabled={editingLocked}
                                  value={bullet}
                                  onFocus={() => onSelect({ ...target, text: bullet })}
                                  onChange={(event) => updateItemBullet(sectionIndex, itemIndex, bulletIndex, event.target.value)}
                                />
                              ) : bullet}
                              {selected && selection ? <ProofToolbar locale={locale} selection={selection} rewriting={rewriting} onRewrite={onRewrite} /> : null}
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
            <div className="mt-10 border-y border-dashed border-[#98a2b3] py-10 text-center text-xs text-[#667085]">
              {documentLanguage === "ar" ? "ستظهر أقسام سيرتك هنا مع تقدّم المحادثة" : "Your resume sections will appear here as the conversation progresses"}
            </div>
          ) : null}
        </article>
      </div>
    </section>
  );
}
