"use client";

import { Moon, Sun } from "lucide-react";
import { useLocale } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";

export function ThemeToggle() {
  const { locale } = useLocale();
  const { theme, toggleTheme } = useTheme();
  const nextThemeLabel = theme === "dark"
    ? locale === "ar" ? "تفعيل الوضع الفاتح" : "Switch to light mode"
    : locale === "ar" ? "تفعيل الوضع الداكن" : "Switch to dark mode";

  return (
    <button
      type="button"
      className="grid h-11 w-11 shrink-0 place-items-center border border-border text-secondary-foreground transition-colors hover:border-primary/60 hover:text-primary-text"
      onClick={toggleTheme}
      aria-label={nextThemeLabel}
      title={nextThemeLabel}
    >
      {theme === "dark"
        ? <Sun className="h-5 w-5" strokeWidth={1.7} aria-hidden="true" />
        : <Moon className="h-5 w-5" strokeWidth={1.7} aria-hidden="true" />}
    </button>
  );
}
