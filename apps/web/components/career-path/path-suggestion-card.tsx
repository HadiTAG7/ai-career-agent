"use client";

import { Beaker, CheckCircle2, CircleHelp, MessageCircle, Quote } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLocale } from "@/lib/i18n";
import type { CareerPathSuggestion } from "@/lib/types";
import { cn } from "@/lib/utils";

const signalStyles: Record<CareerPathSuggestion["signal"], string> = {
  strong: "border-emerald text-emerald",
  partial: "border-border text-muted",
  needs_experiment: "border-primary text-primary-text",
};

export function PathSuggestionCard({ suggestion, onDiscuss }: { suggestion: CareerPathSuggestion; onDiscuss: (title: string) => void }) {
  const { locale } = useLocale();
  const signalLabel = {
    strong: locale === "ar" ? "مؤشرات قوية" : "Strong signals",
    partial: locale === "ar" ? "مؤشرات جزئية" : "Partial signals",
    needs_experiment: locale === "ar" ? "تحتاج تجربة" : "Needs an experiment",
  }[suggestion.signal];

  return (
    <article className="border-y border-border py-6" aria-label={suggestion.title}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-xl font-bold text-foreground">{suggestion.title}</h3>
          <p className="mt-1 text-xs text-muted">
            {locale === "ar" ? "اقتراح للاستكشاف، وليس حكمًا نهائيًا." : "A path to explore, not a final verdict."}
          </p>
        </div>
        <span className={cn("inline-flex w-fit items-center gap-2 border-s-2 px-3 py-1 text-xs font-bold", signalStyles[suggestion.signal])}>
          <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
          {signalLabel}
        </span>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section aria-label={locale === "ar" ? "لماذا قد يناسبك" : "Why it may fit"}>
          <h4 className="flex items-center gap-2 text-sm font-bold"><CheckCircle2 className="h-4 w-4 text-emerald" aria-hidden="true" />{locale === "ar" ? "لماذا قد يناسبك" : "Why it may fit"}</h4>
          {suggestion.why_fit.length > 0 ? (
            <ul className="mt-2 space-y-2 text-sm text-muted">
              {suggestion.why_fit.map((reason, index) => <li className="grid grid-cols-[28px_1fr] gap-2" key={reason}><span className="font-latin text-xs text-emerald" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span><span>{reason}</span></li>)}
            </ul>
          ) : <p className="mt-2 text-sm text-muted">{locale === "ar" ? "لم تُذكر أسباب كافية بعد." : "Not enough reasons were provided yet."}</p>}
        </section>

        <section aria-label={locale === "ar" ? "ما الذي لا نعرفه بعد" : "What we still need to learn"}>
          <h4 className="flex items-center gap-2 text-sm font-bold"><CircleHelp className="h-4 w-4 text-muted" aria-hidden="true" />{locale === "ar" ? "ما الذي لا نعرفه بعد" : "What we still need to learn"}</h4>
          {suggestion.unknowns.length > 0 ? (
            <ul className="mt-2 space-y-2 text-sm text-muted">
              {suggestion.unknowns.map((unknown, index) => <li className="grid grid-cols-[28px_1fr] gap-2" key={unknown}><span className="font-latin text-xs text-muted" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span><span>{unknown}</span></li>)}
            </ul>
          ) : <p className="mt-2 text-sm text-muted">{locale === "ar" ? "لا توجد نقاط مجهولة مسجلة." : "No open questions were recorded."}</p>}
        </section>
      </div>

      <section className="mt-5 border-y border-primary/35 bg-primary/5 py-4" aria-label={locale === "ar" ? "تجربة سبعة أيام" : "Seven-day experiment"}>
        <h4 className="flex items-center gap-2 text-sm font-bold"><Beaker className="h-4 w-4 text-emerald" aria-hidden="true" />{locale === "ar" ? "تجربة لمدة 7 أيام" : "A seven-day experiment"}</h4>
        <p className="mt-2 text-sm text-muted">{suggestion.seven_day_experiment}</p>
      </section>

      {suggestion.evidence.length > 0 ? (
        <section className="mt-5 border-t border-border pt-4" aria-label={locale === "ar" ? "الأدلة المستخدمة" : "Evidence used"}>
          <h4 className="flex items-center gap-2 text-sm font-bold"><Quote className="h-4 w-4 text-emerald" aria-hidden="true" />{locale === "ar" ? "ما استند إليه الاقتراح" : "What informed this suggestion"}</h4>
          <ul className="mt-3 space-y-2">
            {suggestion.evidence.map((evidence, index) => (
              <li className="flex flex-col gap-1 border-b border-border py-2 text-xs text-muted last:border-b-0 sm:flex-row sm:items-start" key={`${evidence.source}-${evidence.reference}-${index}`}>
                <span className="w-fit shrink-0 font-bold text-foreground">
                  {evidence.source === "confirmed_fact"
                    ? (locale === "ar" ? "حقيقة مؤكدة" : "Confirmed fact")
                    : (locale === "ar" ? "من المحادثة" : "From the chat")}
                </span>
                <span className="break-words">{evidence.reference}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <Button variant="secondary" className="mt-5 w-full sm:w-auto" onClick={() => onDiscuss(suggestion.title)}>
        <MessageCircle className="h-4 w-4" aria-hidden="true" />
        {locale === "ar" ? "ناقش هذا المسار" : "Discuss this path"}
      </Button>
    </article>
  );
}
