"use client";

import { FormEvent, useState, useTransition } from "react";
import { AlertCircle, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-client";
import type { JobRequirementCategory } from "@/lib/types";

type Locale = "ar" | "en";
type RequirementInput = {
  text: string;
  category: JobRequirementCategory;
  importance: "mandatory" | "preferred";
  correctionReason: string;
};

const categories: Array<{ value: JobRequirementCategory; ar: string; en: string }> = [
  { value: "skill", ar: "مهارة", en: "Skill" },
  { value: "experience", ar: "خبرة", en: "Experience" },
  { value: "education", ar: "تعليم", en: "Education" },
  { value: "certification", ar: "شهادة", en: "Certification" },
  { value: "language", ar: "لغة", en: "Language" },
  { value: "location", ar: "موقع", en: "Location" },
  { value: "eligibility", ar: "أهلية", en: "Eligibility" },
  { value: "other", ar: "أخرى", en: "Other" },
];

export function EmptyRequirementEditor({ locale, onAdd, onBack }: { locale: Locale; onAdd: (input: RequirementInput) => Promise<void>; onBack: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [saving, startSaveTransition] = useTransition();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const input: RequirementInput = {
      text: String(form.get("requirementText") ?? "").trim(),
      category: String(form.get("category") ?? "other") as JobRequirementCategory,
      importance: String(form.get("importance") ?? "mandatory") as RequirementInput["importance"],
      correctionReason: "Missing from automatic extraction",
    };
    startSaveTransition(async () => {
      try {
        await onAdd(input);
      } catch (caughtError) {
        setError(apiErrorMessage(caughtError, locale));
      }
    });
  }

  return (
    <section className="w-full max-w-xl rounded-xl border border-border p-6 md:p-8" aria-labelledby="empty-requirements-title">
      <h1 id="empty-requirements-title" className="text-xl font-bold">{locale === "ar" ? "لم نجد متطلبات واضحة" : "No clear requirements were found"}</h1>
      <p className="mt-3 text-sm text-muted">{locale === "ar" ? "أضف أول متطلب يدويًا لهذه الوظيفة بدل فقدان الوصف الذي حفظته، ثم راجع القائمة واعتمدها." : "Add the first requirement to this saved job instead of losing its description, then review and confirm the list."}</p>
      <form className="mt-6 space-y-4 text-start" onSubmit={handleSubmit}>
        <label><span className="field-label">{locale === "ar" ? "نص المتطلب" : "Requirement text"}</span><textarea className="field-control min-h-28 py-3" name="requirementText" required minLength={2} autoFocus /></label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label><span className="field-label">{locale === "ar" ? "الفئة" : "Category"}</span><select className="field-control" name="category" defaultValue="other">{categories.map((category) => <option key={category.value} value={category.value}>{locale === "ar" ? category.ar : category.en}</option>)}</select></label>
          <label><span className="field-label">{locale === "ar" ? "الأهمية" : "Importance"}</span><select className="field-control" name="importance" defaultValue="mandatory"><option value="mandatory">{locale === "ar" ? "أساسي" : "Mandatory"}</option><option value="preferred">{locale === "ar" ? "مفضل" : "Preferred"}</option></select></label>
        </div>
        {error ? <p className="flex items-start gap-2 rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</p> : null}
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button type="submit" disabled={saving}><Plus className="h-4 w-4" />{saving ? (locale === "ar" ? "جارٍ الإضافة…" : "Adding…") : (locale === "ar" ? "إضافة المتطلب" : "Add requirement")}</Button>
          <Button type="button" variant="ghost" disabled={saving} onClick={onBack}>{locale === "ar" ? "العودة إلى الوصف" : "Back to description"}</Button>
        </div>
      </form>
    </section>
  );
}
