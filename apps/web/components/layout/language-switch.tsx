"use client";

import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function LanguageSwitch() {
  const { locale, setLocale } = useLocale();
  return (
    <div className="inline-flex h-11 overflow-hidden rounded-lg border border-border bg-white" aria-label={locale === "ar" ? "تغيير اللغة" : "Change language"} role="group">
      {(["ar", "en"] as const).map((option) => (
        <button
          className={cn(
            "min-w-12 px-3 text-sm font-semibold uppercase transition-colors",
            locale === option ? "bg-ink text-white" : "text-ink hover:bg-slate-50"
          )}
          key={option}
          onClick={() => setLocale(option)}
          aria-pressed={locale === option}
          type="button"
        >
          {option}
        </button>
      ))}
    </div>
  );
}
