"use client";

import { useState } from "react";
import {
  CheckCircle2,
  Download,
  FileCheck2,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  apiErrorMessage,
  exportProfessionalResumePdf,
  type ApiCareerProfile,
  type ApiResumeDraft,
} from "@/lib/api-client";

type ResumeDraftEditorProps = {
  locale: "ar" | "en";
  profile: ApiCareerProfile;
  draft: ApiResumeDraft;
  onChange: (draft: ApiResumeDraft) => void;
  onRegenerate: () => Promise<void>;
  regenerating: boolean;
};

export function ResumeDraftEditor({
  locale,
  profile,
  draft,
  onChange,
  onRegenerate,
  regenerating,
}: ResumeDraftEditorProps) {
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [linkedin, setLinkedin] = useState("");
  const [reviewedDraft, setReviewedDraft] = useState<ApiResumeDraft | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<unknown>(null);
  const reviewed = reviewedDraft === draft;

  function commit(next: ApiResumeDraft) {
    setReviewedDraft(null);
    setExportError(null);
    onChange(next);
  }

  function updateSectionTitle(sectionIndex: number, title: string) {
    commit({
      ...draft,
      sections: draft.sections.map((section, index) => (
        index === sectionIndex ? { ...section, title } : section
      )),
    });
  }

  function updateItem(
    sectionIndex: number,
    itemIndex: number,
    field: "title" | "organization" | "date_range" | "location",
    value: string,
  ) {
    commit({
      ...draft,
      sections: draft.sections.map((section, index) => (
        index === sectionIndex
          ? {
            ...section,
            items: section.items.map((item, nestedIndex) => (
              nestedIndex === itemIndex ? { ...item, [field]: value || null } : item
            )),
          }
          : section
      )),
    });
  }

  function updateBullet(
    sectionIndex: number,
    itemIndex: number,
    bulletIndex: number,
    value: string,
  ) {
    commit({
      ...draft,
      sections: draft.sections.map((section, index) => (
        index === sectionIndex
          ? {
            ...section,
            items: section.items.map((item, nestedIndex) => (
              nestedIndex === itemIndex
                ? {
                  ...item,
                  bullets: item.bullets.map((bullet, indexInItem) => (
                    indexInItem === bulletIndex ? value : bullet
                  )),
                }
                : item
            )),
          }
          : section
      )),
    });
  }

  function addBullet(sectionIndex: number, itemIndex: number) {
    commit({
      ...draft,
      sections: draft.sections.map((section, index) => (
        index === sectionIndex
          ? {
            ...section,
            items: section.items.map((item, nestedIndex) => (
              nestedIndex === itemIndex
                ? { ...item, bullets: [...item.bullets, ""] }
                : item
            )),
          }
          : section
      )),
    });
  }

  function removeBullet(sectionIndex: number, itemIndex: number, bulletIndex: number) {
    commit({
      ...draft,
      sections: draft.sections.map((section, index) => (
        index === sectionIndex
          ? {
            ...section,
            items: section.items.map((item, nestedIndex) => (
              nestedIndex === itemIndex
                ? {
                  ...item,
                  bullets: item.bullets.filter((_, indexInItem) => indexInItem !== bulletIndex),
                }
                : item
            )),
          }
          : section
      )),
    });
  }

  async function downloadPdf() {
    if (!reviewed) return;
    setExporting(true);
    setExportError(null);
    try {
      const blob = await exportProfessionalResumePdf(profile.id, {
        language: locale,
        draft,
        contact: { email, phone, linkedin },
        reviewAcknowledged: true,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${profile.full_name.trim() || "resume"}-resume.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportError(error);
    } finally {
      setExporting(false);
    }
  }

  async function regenerateDraft() {
    setReviewedDraft(null);
    setExportError(null);
    await onRegenerate();
  }

  return (
    <section className="mt-8" aria-labelledby="resume-editor-title">
      <div className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-emerald">
            <FileCheck2 className="h-5 w-5" aria-hidden="true" />
            <span className="text-sm font-bold">
              {locale === "ar" ? "صياغة Mistral جاهزة للتحرير" : "Mistral draft ready to edit"}
            </span>
          </div>
          <h2 id="resume-editor-title" className="mt-2 text-2xl font-bold text-ink">
            {locale === "ar" ? "راجع السيرة وعدّلها قبل التنزيل" : "Review and edit before downloading"}
          </h2>
          <p className="mt-1 text-sm text-muted">
            {locale === "ar"
              ? "كل النصوص أدناه قابلة للتعديل. إعادة التوليد تستبدل المسودة الحالية فقط."
              : "Every field below is editable. Regenerating replaces only the current draft."}
          </p>
        </div>
        <Button type="button" variant="secondary" disabled={regenerating || exporting} onClick={() => void regenerateDraft()}>
          {regenerating ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
          {regenerating
            ? (locale === "ar" ? "جارٍ تحسين الصياغة…" : "Improving…")
            : (locale === "ar" ? "أعد توليد الصياغة" : "Regenerate wording")}
        </Button>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0 space-y-6">
          <section className="rounded-xl border border-border bg-white p-5">
            <h3 className="font-bold text-ink">{locale === "ar" ? "العنوان والملخص" : "Headline and summary"}</h3>
            <label className="mt-4 block">
              <span className="field-label">{locale === "ar" ? "العنوان المهني" : "Professional headline"}</span>
              <input
                className="field-control"
                value={draft.headline}
                maxLength={300}
                onChange={(event) => commit({ ...draft, headline: event.target.value })}
              />
            </label>
            <label className="mt-4 block">
              <span className="field-label">{locale === "ar" ? "الملخص المهني" : "Professional summary"}</span>
              <textarea
                className="field-control min-h-36 resize-y"
                value={draft.professional_summary}
                maxLength={2500}
                onChange={(event) => commit({ ...draft, professional_summary: event.target.value })}
              />
            </label>
          </section>

          {draft.sections.map((section, sectionIndex) => (
            <section key={section.key} className="rounded-xl border border-border bg-white p-5">
              <label className="block">
                <span className="field-label">{locale === "ar" ? "عنوان القسم" : "Section title"}</span>
                <input
                  className="field-control text-base font-bold"
                  value={section.title}
                  maxLength={160}
                  onChange={(event) => updateSectionTitle(sectionIndex, event.target.value)}
                />
              </label>
              <div className="mt-5 space-y-5">
                {section.items.map((item, itemIndex) => (
                  <article key={item.id} className="border-t border-border pt-5 first:border-t-0 first:pt-0">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label>
                        <span className="field-label">{locale === "ar" ? "المسمى أو المؤهل" : "Role or qualification"}</span>
                        <input className="field-control" value={item.title} maxLength={500} onChange={(event) => updateItem(sectionIndex, itemIndex, "title", event.target.value)} />
                      </label>
                      <label>
                        <span className="field-label">{locale === "ar" ? "الجهة" : "Organization"}</span>
                        <input className="field-control" value={item.organization ?? ""} maxLength={500} onChange={(event) => updateItem(sectionIndex, itemIndex, "organization", event.target.value)} />
                      </label>
                      <label>
                        <span className="field-label">{locale === "ar" ? "الفترة" : "Date range"}</span>
                        <input className="field-control" value={item.date_range ?? ""} maxLength={160} onChange={(event) => updateItem(sectionIndex, itemIndex, "date_range", event.target.value)} />
                      </label>
                      <label>
                        <span className="field-label">{locale === "ar" ? "الموقع" : "Location"}</span>
                        <input className="field-control" value={item.location ?? ""} maxLength={200} onChange={(event) => updateItem(sectionIndex, itemIndex, "location", event.target.value)} />
                      </label>
                    </div>
                    <div className="mt-4 space-y-3">
                      {item.bullets.map((bullet, bulletIndex) => (
                        <div key={`${item.id}-bullet-${bulletIndex}`} className="flex items-start gap-2">
                          <textarea
                            aria-label={locale === "ar" ? `نقطة ${bulletIndex + 1}` : `Bullet ${bulletIndex + 1}`}
                            className="field-control min-h-24 flex-1 resize-y"
                            value={bullet}
                            maxLength={1000}
                            onChange={(event) => updateBullet(sectionIndex, itemIndex, bulletIndex, event.target.value)}
                          />
                          <button
                            type="button"
                            className="mt-1 grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-border text-muted hover:border-danger hover:text-danger"
                            aria-label={locale === "ar" ? "حذف النقطة" : "Remove bullet"}
                            onClick={() => removeBullet(sectionIndex, itemIndex, bulletIndex)}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          </button>
                        </div>
                      ))}
                    </div>
                    {item.bullets.length < 8 ? (
                      <Button type="button" variant="ghost" className="mt-3" onClick={() => addBullet(sectionIndex, itemIndex)}>
                        <Plus className="h-4 w-4" aria-hidden="true" />
                        {locale === "ar" ? "أضف نقطة" : "Add bullet"}
                      </Button>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>

        <aside className="self-start xl:sticky xl:top-6">
          <section className="overflow-hidden rounded-xl border border-border bg-white shadow-subtle" aria-label={locale === "ar" ? "معاينة السيرة" : "Resume preview"}>
            <header className="border-b border-border bg-emerald-pale p-5">
              <h3 className="text-xl font-bold text-ink">{profile.full_name}</h3>
              <p className="mt-1 font-semibold text-emerald-dark">{draft.headline}</p>
              {profile.city ? <p className="mt-2 text-xs text-muted">{profile.city}</p> : null}
            </header>
            <div className="max-h-[680px] overflow-y-auto p-5 text-sm">
              <section>
                <h4 className="font-bold text-ink">{locale === "ar" ? "الملخص المهني" : "Professional summary"}</h4>
                <p className="mt-2 whitespace-pre-wrap leading-7 text-muted">{draft.professional_summary}</p>
              </section>
              {draft.sections.map((section) => (
                <section key={`preview-${section.key}`} className="mt-5 border-t border-border pt-4">
                  <h4 className="font-bold text-emerald-dark">{section.title}</h4>
                  <div className="mt-3 space-y-4">
                    {section.items.map((item) => (
                      <article key={`preview-${item.id}`}>
                        <p className="font-semibold text-ink">{[item.title, item.organization].filter(Boolean).join(" · ")}</p>
                        {[item.date_range, item.location].some(Boolean) ? <p className="mt-1 text-xs text-muted">{[item.date_range, item.location].filter(Boolean).join(" · ")}</p> : null}
                        {item.bullets.filter(Boolean).length ? <ul className="mt-2 list-disc space-y-1 pe-5 text-muted">{item.bullets.filter(Boolean).map((bullet, index) => <li key={`${item.id}-preview-${index}`}>{bullet}</li>)}</ul> : null}
                      </article>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </section>

          <section className="mt-5 rounded-xl border border-border bg-white p-5">
            <h3 className="font-bold text-ink">{locale === "ar" ? "بيانات التواصل في الملف" : "Contact details in the file"}</h3>
            <p className="mt-1 text-xs text-muted">
              {locale === "ar" ? "تدخل في PDF فقط ولا تُرسل إلى Mistral." : "Added only to the PDF and never sent to Mistral."}
            </p>
            <div className="mt-4 space-y-3">
              <input aria-label={locale === "ar" ? "البريد الإلكتروني" : "Email"} className="field-control" type="email" autoComplete="email" placeholder={locale === "ar" ? "البريد الإلكتروني" : "Email"} value={email} onChange={(event) => { setEmail(event.target.value); setReviewedDraft(null); }} />
              <input aria-label={locale === "ar" ? "رقم الهاتف" : "Phone"} className="field-control" type="tel" autoComplete="tel" placeholder={locale === "ar" ? "رقم الهاتف" : "Phone"} value={phone} onChange={(event) => { setPhone(event.target.value); setReviewedDraft(null); }} />
              <input aria-label="LinkedIn" className="field-control" type="url" placeholder="LinkedIn" value={linkedin} onChange={(event) => { setLinkedin(event.target.value); setReviewedDraft(null); }} />
            </div>

            <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-lg border border-emerald/30 bg-emerald-pale p-3 text-sm">
              <input className="mt-1 h-5 w-5 shrink-0 accent-emerald" type="checkbox" checked={reviewed} onChange={(event) => setReviewedDraft(event.target.checked ? draft : null)} />
              <span>
                <strong className="flex items-center gap-2 text-ink"><ShieldCheck className="h-4 w-4 text-emerald" aria-hidden="true" />{locale === "ar" ? "راجعت النص والمعلومات" : "I reviewed the text and facts"}</strong>
                <span className="mt-1 block text-xs text-muted">{locale === "ar" ? "أتحمل قرار اعتماد الصياغة النهائية قبل التنزيل." : "I approve this final wording before export."}</span>
              </span>
            </label>

            {exportError ? <p className="mt-4 rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{apiErrorMessage(exportError, locale)}</p> : null}

            <Button type="button" size="lg" className="mt-4 w-full" disabled={!reviewed || exporting || regenerating} onClick={() => void downloadPdf()}>
              {exporting ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" /> : reviewed ? <Download className="h-5 w-5" aria-hidden="true" /> : <CheckCircle2 className="h-5 w-5" aria-hidden="true" />}
              {exporting
                ? (locale === "ar" ? "جارٍ إنشاء PDF…" : "Creating PDF…")
                : (locale === "ar" ? "تحميل السيرة PDF" : "Download resume PDF")}
            </Button>
          </section>
        </aside>
      </div>
    </section>
  );
}
