"use client";

import Link from "next/link";
import { ArrowLeft, Compass, FileUser, MessageCircle, ServerOff, Sparkles } from "lucide-react";
import { useLocale } from "@/lib/i18n";
import type { CareerPathWorkspace } from "@/lib/types";

type CareerPathStatusCardProps = {
  workspace?: CareerPathWorkspace | null;
  unavailable?: boolean;
  connected: boolean;
};

export function CareerPathStatusCard({ workspace, unavailable = false, connected }: CareerPathStatusCardProps) {
  const { locale } = useLocale();
  const messages = workspace?.conversation?.messages ?? [];
  const latestSuggestionMessage = [...messages].reverse().find((message) => message.suggestions.length > 0);
  const suggestionCount = latestSuggestionMessage?.suggestions.length ?? 0;

  let Icon = Compass;
  let title = locale === "ar" ? "الخطوة الثانية: اكتشف مسارك" : "Second step: discover your path";
  let description = locale === "ar"
    ? "تحدث مع المستشار الذكي عن اهتماماتك ونقاط قوتك وقيودك، ثم راجع مسارات قابلة للتجربة."
    : "Talk with the AI adviser about your interests, strengths, and constraints, then review paths you can test.";
  let action = locale === "ar" ? "ابدأ المحادثة" : "Start the conversation";
  let href = "/career-path";

  if (!connected || unavailable) {
    Icon = ServerOff;
    title = locale === "ar" ? "تعذر تحميل حالة مسارك" : "Your path status is unavailable";
    description = locale === "ar" ? "افتح صفحة مساري لإعادة المحاولة. لن نعرض اقتراحات تجريبية بدلًا من بياناتك." : "Open My path to try again. Demo suggestions will not replace your data.";
    action = locale === "ar" ? "فتح مساري" : "Open My path";
  } else if (workspace?.confirmed_fact_count === 0) {
    Icon = FileUser;
    title = locale === "ar" ? "الخطوة الأولى: جهّز سيرتك الذاتية" : "First step: prepare your resume";
    description = locale === "ar" ? "ارفع سيرتك الحالية أو أنشئ واحدة بمساعدة الذكاء الاصطناعي، ثم راجع المعلومات المستخرجة قبل تحديد مسارك." : "Upload your current resume or create one with AI, then review the extracted information before choosing your path.";
    action = locale === "ar" ? "ابدأ بالسيرة الذاتية" : "Start with your resume";
    href = "/resume";
  } else if (workspace && !workspace.provider_ready) {
    Icon = ServerOff;
    title = locale === "ar" ? "المستشار الذكي غير مفعّل" : "The AI adviser is not enabled";
    description = locale === "ar" ? "يحتاج مزود الذكاء الاصطناعي إلى إعداد داخل خادم API. لا يوجد حقل مفتاح في الواجهة." : "The AI provider must be configured on the API server. There is no key field in the interface.";
    action = locale === "ar" ? "عرض الحالة" : "View status";
  } else if (suggestionCount > 0) {
    Icon = Sparkles;
    title = locale === "ar" ? `${suggestionCount} مسارات تستحق المراجعة` : `${suggestionCount} paths are ready to review`;
    description = locale === "ar" ? "راجع أسباب كل اقتراح وما لا يزال مجهولًا، ثم ناقشه مع المستشار." : "Review the reasoning and open questions for each suggestion, then discuss it with the adviser.";
    action = locale === "ar" ? "راجع الاقتراحات" : "Review suggestions";
  } else if (messages.length > 0) {
    Icon = MessageCircle;
    title = locale === "ar" ? "محادثة اكتشاف المسار قيد التكوين" : "Your path conversation is in progress";
    description = locale === "ar" ? "أكمل الحديث حتى تتضح اهتماماتك وقيودك قبل عرض اقتراحات المسارات." : "Continue until your interests and constraints are clear enough to suggest paths.";
    action = locale === "ar" ? "أكمل المحادثة" : "Continue the conversation";
  }

  return (
    <section className="mb-9 flex flex-col gap-5 rounded-xl border border-emerald bg-emerald-pale p-5 md:flex-row md:items-center" aria-labelledby="career-path-status-title">
      <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-white text-emerald"><Icon className="h-6 w-6" aria-hidden="true" /></span>
      <div className="min-w-0 flex-1">
        <h2 id="career-path-status-title" className="text-lg font-bold text-ink">{title}</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>
      </div>
      <Link href={href} className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg bg-emerald px-5 text-sm font-semibold text-white hover:bg-emerald-dark">
        {action}
        <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
      </Link>
    </section>
  );
}
