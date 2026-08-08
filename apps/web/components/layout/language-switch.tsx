"use client";

import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function LanguageSwitch() {
  const { locale, setLocale } = useLocale();
  return (
    <div className="inline-flex h-11 border border-border bg-background" aria-label={locale === "ar" ? "تغيير اللغة" : "Change language"} role="group">
      {(["ar", "en"] as const).map((option) => (
        <button
          className={cn(
            "min-w-11 border-s border-border px-3 font-latin text-sm font-semibold uppercase transition-colors first:border-s-0",
            locale === option ? "text-primary-text" : "text-muted hover:text-secondary-foreground"
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
