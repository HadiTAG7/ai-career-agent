"use client";

import { FormEvent, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, FileCheck2, FileText, Link2, LoaderCircle, LockKeyhole } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DemoNotice } from "@/components/ui/demo-notice";
import { apiConfiguration, apiErrorMessage, createManualJob } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import { saveLastAnalysis } from "@/lib/local-store";

const MIN_DESCRIPTION_LENGTH = 80;

export default function NewJobPage() {
  const router = useRouter();
  const { locale } = useLocale();
  const [description, setDescription] = useState("");
  const [submitting, startSubmitTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    if (description.trim().length < MIN_DESCRIPTION_LENGTH) {
      setError(locale === "ar" ? `ألصق وصفًا من ${MIN_DESCRIPTION_LENGTH} حرفًا على الأقل لنتمكن من فصل المتطلبات.` : `Paste at least ${MIN_DESCRIPTION_LENGTH} characters so requirements can be separated.`);
      return;
    }
    const input = {
        title: String(form.get("title") ?? "").trim(),
        company: String(form.get("company") ?? "").trim(),
        location: String(form.get("location") ?? "").trim(),
        originalUrl: String(form.get("originalUrl") ?? "").trim() || undefined,
        description: description.trim(),
    };
    startSubmitTransition(async () => {
      try {
        const result = await createManualJob(input);
        if (result.source === "demo") saveLastAnalysis(result.data);
        router.push(`/jobs/${result.data.id}`);
      } catch (caughtError) {
        setError(apiErrorMessage(caughtError, locale));
      }
    });
  }

  return (
    <div className="page-wrap page-enter max-w-[1120px]">
      <button className="subtle-link" onClick={() => router.back()} type="button"><ArrowLeft className="h-4 w-4 rtl:rotate-180" />{locale === "ar" ? "العودة" : "Back"}</button>
      <header className="mt-5 border-b border-border pb-7">
        <p className="mb-3 text-xs font-bold text-primary-text">{locale === "ar" ? "الخطوة 1 من 3 — الصق وصف الوظيفة" : "Step 1 of 3 — Paste the job description"}</p>
        <h1 className="text-[40px] font-bold leading-tight tracking-[-0.03em] text-foreground md:text-[52px]">{locale === "ar" ? "حلّل وظيفة جديدة" : "Analyze a new job"}</h1>
        <p className="mt-2 max-w-2xl text-muted">{locale === "ar" ? "ألصق الوصف الذي وجدته بنفسك. سنفصل المتطلبات ونربطها فقط بما أكدته في ملفك." : "Paste a description you found. We will separate its requirements and map them only to facts you confirmed."}</p>
        {!apiConfiguration.baseUrl ? <DemoNotice className="mt-3" /> : <p className="mt-3 flex items-center gap-2 text-xs font-medium text-emerald"><LockKeyhole className="h-4 w-4" />{locale === "ar" ? "متصل بـFastAPI؛ ستُحفظ الوظيفة في مساحتك الآمنة." : "Connected to FastAPI; this job will be saved to your secure workspace."}</p>}
      </header>

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <form className="space-y-6 border-y border-border py-6" onSubmit={handleSubmit}>
          <div className="grid gap-5 md:grid-cols-2">
            <label><span className="field-label">{locale === "ar" ? "المسمى الوظيفي" : "Job title"}</span><input className="field-control" name="title" required placeholder={locale === "ar" ? "مثال: محلل بيانات مبتدئ" : "e.g. Junior Data Analyst"} /></label>
            <label><span className="field-label">{locale === "ar" ? "الشركة" : "Company"}</span><input className="field-control" name="company" required placeholder={locale === "ar" ? "اسم الشركة كما ظهر" : "Company name as listed"} /></label>
          </div>
          <div className="grid gap-5 md:grid-cols-2">
            <label><span className="field-label">{locale === "ar" ? "المدينة أو نمط العمل" : "City or work mode"}</span><input className="field-control" name="location" placeholder={locale === "ar" ? "الرياض / هجين" : "Riyadh / hybrid"} /></label>
            <label><span className="field-label flex items-center gap-2"><Link2 className="h-4 w-4" />{locale === "ar" ? "رابط الوظيفة (اختياري)" : "Job URL (optional)"}</span><input className="field-control ltr:text-left" dir="ltr" name="originalUrl" type="url" placeholder="https://…" /></label>
          </div>
          <label>
            <span className="field-label flex items-center gap-2"><FileText className="h-4 w-4" />{locale === "ar" ? "الوصف الوظيفي الكامل" : "Full job description"}</span>
            <textarea className="field-control min-h-[260px] resize-y py-4" name="description" required value={description} onChange={(event) => setDescription(event.target.value)} placeholder={locale === "ar" ? "الصق النص هنا، بما في ذلك المتطلبات الأساسية والمفضلة…" : "Paste the text here, including essential and preferred requirements…"} aria-describedby="description-help" />
            <span id="description-help" className="mt-2 flex justify-between text-xs text-muted"><span>{locale === "ar" ? "لا نُرسل أو ننشر هذا النص خارج مساحة التحليل." : "We do not publish this text outside the analysis workspace."}</span><span dir="ltr">{description.length} / {MIN_DESCRIPTION_LENGTH}+</span></span>
          </label>
          {error ? <p className="flex items-start gap-2 border-s-2 border-danger py-2 ps-3 text-sm text-danger" role="alert"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</p> : null}
          <Button type="submit" size="lg" className="w-full md:w-auto" disabled={submitting}>
            {submitting ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <FileCheck2 className="h-5 w-5" />}
            {submitting ? (locale === "ar" ? "جارٍ استخراج المتطلبات…" : "Extracting requirements…") : (locale === "ar" ? "استخرج المتطلبات وراجعها" : "Extract and review requirements")}
          </Button>
        </form>

        <aside className="border-t border-border pt-5 lg:border-s lg:border-t-0 lg:ps-6 lg:pt-0" aria-label={locale === "ar" ? "سياسة المصادر" : "Source policy"}>
          <section className="border-b border-border pb-6">
            <p className="text-xs text-muted">{locale === "ar" ? "هامش 01" : "Margin 01"}</p>
            <LockKeyhole className="mt-4 h-6 w-6 text-emerald" />
            <h2 className="mt-3 font-bold">{locale === "ar" ? "أنت تنقل النص، لا النظام" : "You provide the text; the system does not fetch it"}</h2>
            <p className="mt-2 text-sm text-muted">{locale === "ar" ? "لن نجلب الصفحة من LinkedIn أو Indeed أو Bayt. الرابط يُحفظ للرجوع إليه فقط." : "We will not fetch LinkedIn, Indeed, or Bayt pages. The URL is saved only for your reference."}</p>
          </section>
          <section className="py-6">
            <h2 className="font-bold">{locale === "ar" ? "ماذا ستحصل عليه؟" : "What you will get"}</h2>
            <ul className="mt-3 list-inside list-disc space-y-3 text-sm text-muted marker:text-primary-text">
              <li>{locale === "ar" ? "متطلبات أساسية ومفضلة منفصلة" : "Separated essential and preferred requirements"}</li>
              <li>{locale === "ar" ? "تغطية مفسّرة، لا احتمال قبول" : "Explainable coverage, not an acceptance probability"}</li>
              <li>{locale === "ar" ? "دليل مؤكد أو فجوة واضحة لكل بند" : "Confirmed evidence or a clear gap for each item"}</li>
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
