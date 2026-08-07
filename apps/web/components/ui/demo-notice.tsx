"use client";

import { FlaskConical } from "lucide-react";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function DemoNotice({ className, compact = false }: { className?: string; compact?: boolean }) {
  const { locale } = useLocale();
  return (
    <div className={cn("flex items-center gap-2 text-xs font-medium text-muted", className)} role="status">
      <FlaskConical aria-hidden="true" className="h-4 w-4 text-emerald" />
      <span>
        {compact
          ? locale === "ar" ? "بيانات تجريبية" : "Demo data"
          : locale === "ar"
            ? "هذه بيانات تجريبية واضحة ويمكن استبدالها ببيانات FastAPI."
            : "This is clearly marked demo data and can be replaced by FastAPI data."}
      </span>
    </div>
  );
}
