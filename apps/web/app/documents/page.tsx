"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Clipboard, Download, FileCheck2, FileText, LockKeyhole, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DemoNotice } from "@/components/ui/demo-notice";
import { demoJobs } from "@/lib/demo-data";
import { apiConfiguration } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type DocumentKind = "cv" | "cover";

const cvSections = {
  ar: [
    { heading: "الملخص", text: "خريج نظم معلومات في بداية مساره، لديه خبرة عملية مؤكدة في تنظيف البيانات وإعداد التقارير باستخدام Python، ومشروع موثق لتحليل المبيعات باستخدام SQL وPower BI." },
    { heading: "الخبرة ذات الصلة", text: "تدريب تعاوني في تحليل البيانات — استخدام Python لتنظيف البيانات وإعداد تقارير أسبوعية." },
    { heading: "المشاريع", text: "لوحة تحليل المبيعات — بناء لوحة باستخدام Power BI وSQL." },
    { heading: "المهارات المؤكدة", text: "Python · SQL · Power BI" },
  ],
  en: [
    { heading: "Summary", text: "Early-career Information Systems graduate with confirmed practical experience cleaning data and preparing reports in Python, plus a documented sales analysis project using SQL and Power BI." },
    { heading: "Relevant experience", text: "Data analytics internship — used Python to clean data and prepare weekly reports." },
    { heading: "Projects", text: "Sales analysis dashboard — built a dashboard using Power BI and SQL." },
    { heading: "Confirmed skills", text: "Python · SQL · Power BI" },
  ],
};

export default function DocumentsPage() {
  const { locale, text } = useLocale();
  const [activeKind, setActiveKind] = useState<DocumentKind>("cv");
  const [generated, setGenerated] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [targetJobId, setTargetJobId] = useState(demoJobs[0].id);

  useEffect(() => {
    const job = new URLSearchParams(window.location.search).get("job");
    if (job) {
      queueMicrotask(() => {
        setTargetJobId(job);
        setGenerated(true);
      });
    }
  }, []);

  const targetJob = demoJobs.find((job) => job.id === targetJobId) ?? demoJobs[0];
  const documentText = useMemo(() => {
    if (activeKind === "cv") return cvSections[locale].map((section) => `${section.heading}\n${section.text}`).join("\n\n");
    return locale === "ar"
      ? `السادة فريق التوظيف،\n\nأتقدم إلى وظيفة ${text(targetJob.title)}. يدعم طلبي تدريب تعاوني موثق في تحليل البيانات، إضافة إلى مشروع لوحة مبيعات باستخدام SQL وPower BI. يسعدني مناقشة مدى ملاءمة هذه الخبرات لمتطلبات الدور.\n\nمع التحية،\nمحمد العتيبي`
      : `Dear hiring team,\n\nI am applying for the ${text(targetJob.title)} role. My application is supported by a documented data analytics internship and a sales dashboard project using SQL and Power BI. I would welcome the opportunity to discuss how this experience aligns with the role.\n\nKind regards,\nMohammed Alotaibi`;
  }, [activeKind, locale, targetJob.title, text]);
  const markedDemoText = `${locale === "ar" ? "تجربة خيالية — ليست سيرة ذاتية حقيقية ولا يجوز استخدامها للتقديم" : "FICTIONAL DEMO — NOT A REAL CV AND NOT FOR APPLICATION USE"}\n\n${documentText}`;

  async function copyDocument() {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(markedDemoText);
    else {
      const area = document.createElement("textarea");
      area.value = markedDemoText;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setNotice(locale === "ar" ? "تم نسخ المستند." : "Document copied.");
    window.setTimeout(() => setNotice(null), 2200);
  }

  function downloadDocument() {
    const blob = new Blob([markedDemoText], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = activeKind === "cv" ? "DO-NOT-USE_fictional-cv-demo.txt" : "DO-NOT-USE_fictional-cover-letter-demo.txt";
    anchor.click();
    URL.revokeObjectURL(url);
    setNotice(locale === "ar" ? "تم تنزيل النسخة التجريبية." : "Demo document downloaded.");
  }

  if (apiConfiguration.baseUrl) {
    return (
      <div className="page-wrap page-enter">
        <h1 className="page-title">{locale === "ar" ? "المستندات" : "Documents"}</h1>
        <p className="mt-2 max-w-2xl text-muted">{locale === "ar" ? "لن نُنشئ أو نُصدّر أي ادعاء قبل ربطه بحقيقة مؤكدة ومراجعته منك." : "No claim will be generated or exported until it is linked to a confirmed fact and reviewed by you."}</p>
        <section className="mt-8 grid min-h-[420px] place-items-center border-y border-border py-10 text-center">
          <div className="max-w-lg">
            <LockKeyhole className="mx-auto h-10 w-10 text-emerald" />
            <h2 className="mt-5 text-xl font-bold">{locale === "ar" ? "توليد المستندات الحقيقي غير مربوط بعد" : "Live document generation is not connected yet"}</h2>
            <p className="mt-3 text-sm leading-7 text-muted">{locale === "ar" ? "أوقفنا الإنشاء والنسخ والتنزيل في الوضع المتصل حتى يكتمل تدفق الخادم الذي يربط كل جملة بحقائقك المؤكدة ويمنع التصدير قبل مراجعتك." : "Generation, copying, and downloading are disabled in connected mode until the server flow can trace every sentence to your confirmed facts and require your review before export."}</p>
            <p className="mt-5 border-y border-emerald bg-emerald-pale/50 py-4 text-sm font-semibold text-emerald">{locale === "ar" ? "يمكنك الآن إكمال ملف الأدلة وتحليل وظيفة؛ لن تُعرض هنا أي بيانات خيالية بدلًا من بياناتك." : "You can complete your evidence profile and analyze a job now; fictional content will never be shown here in place of your data."}</p>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-wrap page-enter">
      <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div><h1 className="page-title">{locale === "ar" ? "المستندات" : "Documents"}</h1><p className="mt-2 max-w-2xl text-muted">{locale === "ar" ? "ساحة واجهة خيالية فقط لاختبار التنسيق؛ كل الأسماء والخبرات أدناه بيانات تجريبية وليست بياناتك." : "A fictional UI sandbox for testing layout only; every name and experience below is demo data, not yours."}</p><DemoNotice className="mt-3" /></div>
        <Button size="lg" onClick={() => setGenerated(true)}><FileCheck2 className="h-5 w-5" />{locale === "ar" ? "إنشاء حزمة تجريبية" : "Generate demo package"}</Button>
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[280px_minmax(0,1fr)]" dir="ltr">
        <aside className="border-e border-border pe-5" dir={locale === "ar" ? "rtl" : "ltr"}>
          <h2 className="section-title">{locale === "ar" ? "الحزمة الحالية" : "Current package"}</h2>
          <button onClick={() => setActiveKind("cv")} className={cn("mt-4 flex min-h-[72px] w-full items-center gap-3 border-y px-1 py-4 text-start", activeKind === "cv" ? "border-primary text-primary-text" : "border-border text-muted hover:text-foreground")}><FileText className="h-6 w-6" /><span><strong className="block text-sm">{locale === "ar" ? "CV مخصص" : "Tailored CV"}</strong><small className="text-muted">{text(targetJob.title)}</small></span></button>
          <button onClick={() => setActiveKind("cover")} className={cn("flex min-h-[72px] w-full items-center gap-3 border-b px-1 py-4 text-start", activeKind === "cover" ? "border-primary text-primary-text" : "border-border text-muted hover:text-foreground")}><Mail className="h-6 w-6" /><span><strong className="block text-sm">{locale === "ar" ? "رسالة تقديم" : "Cover letter"}</strong><small className="text-muted">{locale === "ar" ? "نسخة موجزة" : "Concise version"}</small></span></button>
          <div className="mt-5 border-y border-danger bg-danger-pale/50 py-4 text-sm"><p className="flex items-center gap-2 font-semibold text-danger"><LockKeyhole className="h-4 w-4" />{locale === "ar" ? "بيانات خيالية للعرض فقط" : "Fictional data for preview only"}</p><p className="mt-2 text-xs text-danger">{locale === "ar" ? "هذه الحقائق جزء من سيناريو تجريبي وليست حقائقك المهنية. لا تستخدم المستند للتقديم." : "These facts belong to a demo scenario, not your career profile. Do not use this document to apply."}</p></div>
        </aside>

        <section dir={locale === "ar" ? "rtl" : "ltr"}>
          {!generated ? (
            <div className="grid min-h-[480px] place-items-center border-y border-border p-8 text-center"><div><FileCheck2 className="mx-auto h-10 w-10 text-muted" /><h2 className="mt-4 section-title">{locale === "ar" ? "أنشئ الحزمة لمعاينة المستندات" : "Generate the package to preview documents"}</h2><p className="mt-2 text-sm text-muted">{locale === "ar" ? "الإنشاء المحلي يستخدم الحقائق التجريبية المؤكدة فقط." : "Local generation uses only confirmed demo facts."}</p></div></div>
          ) : (
            <>
              <div className="flex flex-col justify-between gap-4 border-b border-border pb-4 md:flex-row md:items-center"><div><h2 className="section-title">{activeKind === "cv" ? (locale === "ar" ? "CV مخصص — محلل بيانات" : "Tailored CV — Data Analyst") : (locale === "ar" ? "رسالة تقديم مخصصة" : "Tailored cover letter")}</h2><p className="mt-1 text-xs text-muted">{locale === "ar" ? "نسخة تجريبية · ATS آمنة · راجعها قبل الاستخدام" : "Demo version · ATS-safe · review before use"}</p></div><div className="flex gap-3"><Button variant="secondary" onClick={copyDocument}><Clipboard className="h-4 w-4" />{locale === "ar" ? "نسخ" : "Copy"}</Button><Button onClick={downloadDocument}><Download className="h-4 w-4" />{locale === "ar" ? "تنزيل" : "Download"}</Button></div></div>
              <div className="relative mt-6 min-h-[520px] overflow-hidden border-2 border-danger bg-white p-6 text-[#0f1729] shadow-subtle md:p-10">
                <div className="pointer-events-none absolute inset-x-0 top-44 -rotate-12 border-y-4 border-danger/20 bg-danger-pale/90 py-5 text-center text-2xl font-black tracking-widest text-danger/70" aria-hidden="true">{locale === "ar" ? "تجربة خيالية — ليس للاستخدام" : "FICTIONAL DEMO — DO NOT USE"}</div>
                <div className="border-b-2 border-[#0f1729] pb-5"><h3 className="text-2xl font-bold">{locale === "ar" ? "محمد العتيبي" : "Mohammed Alotaibi"}</h3><p className="mt-1 text-sm text-[#64748b]">{text(targetJob.title)} · {text(targetJob.location)}</p></div>
                {activeKind === "cv" ? <div className="mt-6 space-y-6">{cvSections[locale].map((section) => <section key={section.heading}><h4 className="border-b border-[#d7dde8] pb-2 font-bold">{section.heading}</h4><p className="mt-3 text-sm leading-7">{section.text}</p><p className="mt-2 flex items-center gap-1 text-xs text-[#0f9873]"><CheckCircle2 className="h-3.5 w-3.5" />{locale === "ar" ? "مرتبط بحقيقة مؤكدة" : "Linked to a confirmed fact"}</p></section>)}</div> : <p className="mt-8 whitespace-pre-line text-sm leading-8">{documentText}</p>}
              </div>
            </>
          )}
        </section>
      </div>
      {notice ? <div className="fixed bottom-24 start-5 z-50 flex items-center gap-2 border border-emerald bg-surface px-4 py-3 text-sm shadow-subtle lg:bottom-6" role="status"><CheckCircle2 className="h-4 w-4 text-emerald" />{notice}</div> : null}
    </div>
  );
}
