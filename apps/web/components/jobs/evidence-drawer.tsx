"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { AlertCircle, CheckCircle2, FileText, Info, Pencil, Plus, ShieldCheck, Trash2, X } from "lucide-react";
import { StatusLabel } from "@/components/ui/status-label";
import { Button } from "@/components/ui/button";
import { useLocale } from "@/lib/i18n";
import { apiErrorMessage, type ApiCareerFact, type ApiEvidenceSource } from "@/lib/api-client";
import type { JobRequirement, JobRequirementCategory, RequirementStatus } from "@/lib/types";

const labels: Record<"ar" | "en", Record<RequirementStatus, string>> = {
  ar: { supported: "تم التحقق", partial: "متوافق جزئيًا", unsupported: "غير مدعوم", unknown: "غير معلوم" },
  en: { supported: "Verified", partial: "Partial match", unsupported: "Unsupported", unknown: "Unknown" },
};

export type DrawerEvidenceDetail = { fact: ApiCareerFact; source?: ApiEvidenceSource };
export type RequirementEditInput = { text: string; category: JobRequirementCategory; importance: "mandatory" | "preferred"; correctionReason: string };

const requirementCategories: Array<{ value: JobRequirementCategory; ar: string; en: string }> = [
  { value: "skill", ar: "مهارة", en: "Skill" }, { value: "experience", ar: "خبرة", en: "Experience" },
  { value: "education", ar: "تعليم", en: "Education" }, { value: "certification", ar: "شهادة", en: "Certification" },
  { value: "language", ar: "لغة", en: "Language" }, { value: "location", ar: "موقع", en: "Location" },
  { value: "eligibility", ar: "أهلية", en: "Eligibility" }, { value: "other", ar: "أخرى", en: "Other" },
];

type EvidenceDrawerProps = {
  requirement: JobRequirement;
  reviewMode?: boolean;
  evidenceDetail?: DrawerEvidenceDetail;
  onClose: () => void;
  open: boolean;
  onCorrectRequirement?: (input: RequirementEditInput) => Promise<void>;
  onAddRequirement?: (input: RequirementEditInput) => Promise<void>;
  onRetireRequirement?: (correctionReason: string) => Promise<void>;
};

export function EvidenceDrawer({ requirement, reviewMode = false, evidenceDetail, onClose, open, onCorrectRequirement, onAddRequirement, onRetireRequirement }: EvidenceDrawerProps) {
  const { locale, text } = useLocale();
  const [editingRequirement, setEditingRequirement] = useState(false);
  const [addingRequirement, setAddingRequirement] = useState(false);
  const [retiringRequirement, setRetiringRequirement] = useState(false);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [correctionError, setCorrectionError] = useState<string | null>(null);
  if (!open) return null;

  async function handleCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!onCorrectRequirement) return;
    const form = new FormData(event.currentTarget);
    setSavingCorrection(true);
    setCorrectionError(null);
    try {
      await onCorrectRequirement({
        text: String(form.get("requirementText") ?? "").trim(),
        category: String(form.get("category") ?? "other") as JobRequirementCategory,
        importance: String(form.get("importance") ?? "mandatory") as "mandatory" | "preferred",
        correctionReason: String(form.get("correctionReason") ?? "").trim(),
      });
      setEditingRequirement(false);
    } catch (error) {
      setCorrectionError(apiErrorMessage(error, locale));
    } finally {
      setSavingCorrection(false);
    }
  }

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!onAddRequirement) return;
    const form = new FormData(event.currentTarget);
    setSavingCorrection(true);
    setCorrectionError(null);
    try {
      await onAddRequirement({
        text: String(form.get("requirementText") ?? "").trim(),
        category: String(form.get("category") ?? "other") as JobRequirementCategory,
        importance: String(form.get("importance") ?? "mandatory") as "mandatory" | "preferred",
        correctionReason: String(form.get("correctionReason") ?? "").trim(),
      });
      setAddingRequirement(false);
    } catch (error) { setCorrectionError(apiErrorMessage(error, locale)); }
    finally { setSavingCorrection(false); }
  }

  async function handleRetire(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!onRetireRequirement) return;
    const form = new FormData(event.currentTarget);
    setSavingCorrection(true);
    setCorrectionError(null);
    try {
      await onRetireRequirement(String(form.get("correctionReason") ?? "").trim());
      setRetiringRequirement(false);
    } catch (error) { setCorrectionError(apiErrorMessage(error, locale)); }
    finally { setSavingCorrection(false); }
  }

  return (
    <aside
      className="fixed inset-x-0 bottom-[76px] top-[86px] z-40 overflow-y-auto border-s border-border bg-background p-5 lg:sticky lg:inset-auto lg:top-24 lg:z-auto lg:block lg:max-h-[calc(100vh-112px)]"
      aria-labelledby="decision-evidence-title"
    >
      <div className="flex items-center justify-between border-b border-border pb-4">
        <h2 id="decision-evidence-title" className="section-title flex items-center gap-2"><Info className="h-5 w-5" />{reviewMode ? (locale === "ar" ? "مراجعة المتطلب" : "Requirement review") : (locale === "ar" ? "دليل القرار" : "Decision evidence")}</h2>
        <button className="grid h-11 w-11 place-items-center text-muted hover:text-foreground" onClick={onClose} aria-label={locale === "ar" ? "إغلاق الدليل" : "Close evidence"}><X className="h-5 w-5" /></button>
      </div>

      <section className="open-section">
        <p className="text-xs font-semibold text-muted">{locale === "ar" ? "المتطلب المحدد" : "Selected requirement"}</p>
        <div className="mt-3 border-y border-emerald/45 py-4">
          <p className="font-semibold">{text(requirement.label)}</p>
          <div className="mt-2">{reviewMode ? <span className="border-s-2 border-primary ps-2 text-xs font-semibold text-primary-text">{requirement.kind === "essential" ? (locale === "ar" ? "أساسي" : "Essential") : (locale === "ar" ? "مفضل" : "Preferred")}</span> : <StatusLabel status={requirement.status} labels={labels[locale]} compact />}</div>
        </div>
      </section>

      {!reviewMode ? <>
      <section className="open-section">
        <h3 className="text-sm font-bold">{locale === "ar" ? "المصدر" : "Source"}</h3>
        {evidenceDetail ? (
          <div className="mt-3 border-y border-border py-4">
            <p className="flex items-center gap-2 font-semibold"><FileText className="h-5 w-5" />{evidenceDetail.source?.label ?? (locale === "ar" ? "بيانات المصدر غير متاحة" : "Source metadata unavailable")}</p>
            <dl className="mt-3 grid gap-2 text-xs">
              <div className="flex justify-between gap-3"><dt className="text-muted">{locale === "ar" ? "النوع" : "Kind"}</dt><dd dir="ltr">{evidenceDetail.source?.kind ?? "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted">{locale === "ar" ? "الملف" : "File"}</dt><dd className="break-all" dir="ltr">{evidenceDetail.source?.original_filename ?? (locale === "ar" ? "إدخال يدوي" : "Manual entry")}</dd></div>
            </dl>
          </div>
        ) : requirement.evidence ? (
          <div className="mt-3 border-y border-border py-4">
            <p className="flex items-center gap-2 font-semibold"><FileText className="h-5 w-5" />{text(requirement.evidence)}</p>
            <p className="mt-2 text-sm text-muted">{locale === "ar" ? "تعذر تحميل تفاصيل المصدر؛ افتح الحقيقة في الملف للمراجعة." : "Source details could not be loaded; open the fact in your profile to review it."}</p>
          </div>
        ) : (
          <div className="mt-3 border-s-2 border-danger py-3 ps-3">
            <p className="flex items-center gap-2 font-semibold text-danger"><AlertCircle className="h-5 w-5" />{locale === "ar" ? "لا يوجد مصدر داعم" : "No supporting source"}</p>
          </div>
        )}
      </section>

      <section className="open-section">
        <h3 className="text-sm font-bold">{locale === "ar" ? "حالة التحقق" : "Verification status"}</h3>
        <div className="mt-3 flex items-start gap-2 border-y border-border py-4">
          {requirement.status === "supported" ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald" /> : <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-muted" />}
          <p className="text-sm">{text(requirement.explanation)}</p>
        </div>
        {evidenceDetail ? <div className="mt-3 border-y border-border py-4 text-sm"><p className="font-semibold">{evidenceDetail.fact.label}</p>{evidenceDetail.fact.detail ? <p className="mt-1 text-muted">{evidenceDetail.fact.detail}</p> : null}<p className="mt-2 text-xs font-semibold text-emerald">{locale === "ar" ? "حالة الحقيقة" : "Fact status"}: {evidenceDetail.fact.verification_status}</p>{evidenceDetail.fact.source_excerpt ? <p className="mt-3 border-t border-border pt-3 text-xs"><span className="font-semibold text-muted">{locale === "ar" ? "النص المصدر" : "Source excerpt"}: </span>{evidenceDetail.fact.source_excerpt}</p> : null}{Object.keys(evidenceDetail.fact.structured_value ?? {}).length > 0 ? <dl className="mt-3 grid gap-2 border-t border-border pt-3">{Object.entries(evidenceDetail.fact.structured_value).map(([key, value]) => <div className="grid grid-cols-[90px_1fr] gap-2 text-xs" key={key}><dt className="font-semibold text-muted" dir="ltr">{key}</dt><dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd></div>)}</dl> : null}</div> : null}
      </section>
      </> : null}

      <section className="pt-5">
        <p className="text-xs font-semibold text-muted">{locale === "ar" ? "تعديل من قبلك" : "Correction by you"}</p>
        {!reviewMode ? <Link href={requirement.evidenceFactId ? `/profile#fact-${requirement.evidenceFactId}` : "/profile"} className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 border-y border-border px-4 text-sm font-semibold hover:border-emerald"><Pencil className="h-4 w-4" />{locale === "ar" ? "فتح الحقيقة في الملف" : "Open fact in profile"}</Link> : null}
        {onCorrectRequirement ? (
          <div className="mt-3">
            {!editingRequirement ? (
              <Button className="w-full" variant="secondary" onClick={() => setEditingRequirement(true)}><Pencil className="h-4 w-4" />{locale === "ar" ? "تصحيح نص المتطلب" : "Correct requirement text"}</Button>
            ) : (
              <form className="space-y-3 border-y border-border py-4" onSubmit={handleCorrection}>
                <label><span className="field-label">{locale === "ar" ? "نص المتطلب الصحيح" : "Correct requirement text"}</span><textarea className="field-control min-h-24 py-3" defaultValue={text(requirement.label)} name="requirementText" required minLength={2} /></label>
                <div className="grid grid-cols-2 gap-3"><label><span className="field-label">{locale === "ar" ? "الفئة" : "Category"}</span><select className="field-control" name="category" defaultValue={requirement.category}>{requirementCategories.map((item) => <option key={item.value} value={item.value}>{locale === "ar" ? item.ar : item.en}</option>)}</select></label><label><span className="field-label">{locale === "ar" ? "الأهمية" : "Importance"}</span><select className="field-control" name="importance" defaultValue={requirement.kind === "essential" ? "mandatory" : "preferred"}><option value="mandatory">{locale === "ar" ? "أساسي" : "Mandatory"}</option><option value="preferred">{locale === "ar" ? "مفضل" : "Preferred"}</option></select></label></div>
                <label><span className="field-label">{locale === "ar" ? "سبب التصحيح" : "Correction reason"}</span><textarea className="field-control min-h-20 py-3" name="correctionReason" required minLength={3} placeholder={locale === "ar" ? "مثال: صُنّف المتطلب أو استُخرج نصه بشكل غير صحيح" : "e.g. The requirement was extracted or classified incorrectly"} /></label>
                <p className="text-xs text-muted">{locale === "ar" ? "سيُحفظ التصحيح في سجل التدقيق، ثم يمكنك اعتماد القائمة وتشغيل المطابقة." : "The correction is audit-logged; then you can confirm the list and run matching."}</p>
                {correctionError ? <p className="text-sm text-danger" role="alert">{correctionError}</p> : null}
                <div className="grid grid-cols-2 gap-2"><Button type="submit" disabled={savingCorrection}>{savingCorrection ? (locale === "ar" ? "جارٍ الحفظ…" : "Saving…") : (locale === "ar" ? "حفظ التصحيح" : "Save correction")}</Button><Button variant="ghost" disabled={savingCorrection} onClick={() => setEditingRequirement(false)}>{locale === "ar" ? "إلغاء" : "Cancel"}</Button></div>
              </form>
            )}
            {!retiringRequirement ? <Button className="mt-2 w-full" variant="danger" onClick={() => setRetiringRequirement(true)}><Trash2 className="h-4 w-4" />{locale === "ar" ? "حذف نتيجة خاطئة" : "Remove false positive"}</Button> : <form className="mt-2 space-y-3 border-y border-danger py-4" onSubmit={handleRetire}><label><span className="field-label">{locale === "ar" ? "سبب الحذف" : "Removal reason"}</span><textarea className="field-control min-h-20 py-3" name="correctionReason" required minLength={3} /></label>{correctionError ? <p className="text-sm text-danger" role="alert">{correctionError}</p> : null}<div className="grid grid-cols-2 gap-2"><Button type="submit" variant="danger" disabled={savingCorrection}>{locale === "ar" ? "تأكيد الحذف" : "Confirm removal"}</Button><Button variant="ghost" disabled={savingCorrection} onClick={() => setRetiringRequirement(false)}>{locale === "ar" ? "إلغاء" : "Cancel"}</Button></div></form>}
          </div>
        ) : null}
      </section>

      {onAddRequirement ? <section className="mt-5 border-t border-border pt-5">{!addingRequirement ? <Button className="w-full" variant="secondary" onClick={() => setAddingRequirement(true)}><Plus className="h-4 w-4" />{locale === "ar" ? "إضافة متطلب أسقطه التحليل" : "Add a missed requirement"}</Button> : <form className="space-y-3 border-y border-emerald py-4" onSubmit={handleAdd}><label><span className="field-label">{locale === "ar" ? "نص المتطلب" : "Requirement text"}</span><textarea className="field-control min-h-24 py-3" name="requirementText" required minLength={2} /></label><div className="grid grid-cols-2 gap-3"><label><span className="field-label">{locale === "ar" ? "الفئة" : "Category"}</span><select className="field-control" name="category" defaultValue="other">{requirementCategories.map((item) => <option key={item.value} value={item.value}>{locale === "ar" ? item.ar : item.en}</option>)}</select></label><label><span className="field-label">{locale === "ar" ? "الأهمية" : "Importance"}</span><select className="field-control" name="importance"><option value="mandatory">{locale === "ar" ? "أساسي" : "Mandatory"}</option><option value="preferred">{locale === "ar" ? "مفضل" : "Preferred"}</option></select></label></div><label><span className="field-label">{locale === "ar" ? "سبب الإضافة" : "Addition reason"}</span><textarea className="field-control min-h-20 py-3" name="correctionReason" required minLength={3} /></label>{correctionError ? <p className="text-sm text-danger" role="alert">{correctionError}</p> : null}<div className="grid grid-cols-2 gap-2"><Button type="submit" disabled={savingCorrection}>{locale === "ar" ? "إضافة" : "Add"}</Button><Button variant="ghost" disabled={savingCorrection} onClick={() => setAddingRequirement(false)}>{locale === "ar" ? "إلغاء" : "Cancel"}</Button></div></form>}</section> : null}

      <section className="mt-6 border-t border-border pt-5">
        <h3 className="flex items-center gap-2 text-sm font-bold"><Info className="h-4 w-4" />{locale === "ar" ? "كيف نتحقق؟" : "How verification works"}</h3>
        <p className="mt-2 text-sm text-muted">{reviewMode ? (locale === "ar" ? "بعد اعتماد القائمة سنطابق كل متطلب مع الحقائق المهنية المؤكدة فقط." : "After you confirm the list, each requirement will be matched only to confirmed career facts.") : (locale === "ar" ? "نطابق كلمات المتطلب مع حقائق مهنية مؤكدة فقط، ثم نعرض لك الرابط والتفسير." : "We match requirement language only to confirmed career facts, then show you the link and explanation.")}</p>
      </section>
    </aside>
  );
}
