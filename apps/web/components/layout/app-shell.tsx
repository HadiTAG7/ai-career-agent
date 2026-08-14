"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Lightbulb, Menu, X } from "lucide-react";
import { AccountControl } from "@/components/auth/account-control";
import { authConfiguration } from "@/components/auth/auth-gate";
import { Brand } from "@/components/layout/brand";
import { LanguageSwitch } from "@/components/layout/language-switch";
import {
  currentNavigationItem,
  isCurrentPath,
  navigationItems,
} from "@/components/layout/navigation";
import type { NavigationItem } from "@/components/layout/navigation";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { DemoNotice } from "@/components/ui/demo-notice";
import { apiConfiguration } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import type { LocalizedText } from "@/lib/types";
import { cn } from "@/lib/utils";

function ChapterLink({
  item,
  active,
  label,
  mobile = false,
}: {
  item: NavigationItem;
  active: boolean;
  label: string;
  mobile?: boolean;
}) {
  return (
    <Link
      href={item.href}
      className={cn(
        "group relative flex min-h-14 w-full items-baseline gap-2 border-s-2 px-4 py-3 text-start transition-colors",
        active
          ? "border-primary text-foreground"
          : "border-transparent text-muted hover:border-control/60 hover:text-secondary-foreground",
        mobile && "min-h-12 py-2.5",
      )}
      dir="ltr"
      aria-current={active ? "page" : undefined}
    >
      <span
        className={cn(
          "font-latin tabular-nums leading-none transition-all",
          active ? mobile ? "text-2xl text-primary-text" : "text-[32px] text-primary-text" : "text-lg text-muted",
        )}
        aria-hidden="true"
      >
        {item.chapter}
      </span>
      <span className="text-muted" aria-hidden="true">/</span>
      <span className={cn("text-sm font-medium", active && "font-semibold text-foreground")} dir="auto">{label}</span>
    </Link>
  );
}

function ChapterNavigation({
  pathname,
  text,
  mobile = false,
}: {
  pathname: string;
  text: (value: LocalizedText) => string;
  mobile?: boolean;
}) {
  return (
    <ol className={cn("grid gap-1", mobile && "gap-0")}>
      {navigationItems.map((item) => (
        <li key={item.href}>
          <ChapterLink item={item} active={isCurrentPath(pathname, item.href)} label={text(item.label)} mobile={mobile} />
        </li>
      ))}
    </ol>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { locale, text } = useLocale();
  const [menuOpen, setMenuOpen] = useState(false);
  const activeChapter = currentNavigationItem(pathname);
  const primaryNavigationLabel = locale === "ar" ? "التنقل الرئيسي" : "Primary navigation";

  useEffect(() => {
    // Route changes are an external navigation event; close any stale mobile drawer.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMenuOpen(false);
  }, [pathname]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside
        className="fixed inset-y-0 start-0 z-40 hidden w-[244px] flex-col border-e border-border bg-background shell:flex"
        aria-label={primaryNavigationLabel}
      >
        <div className="flex h-16 shrink-0 items-center border-b border-border px-7">
          <Brand />
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-5 py-7" aria-label={primaryNavigationLabel}>
          <ChapterNavigation pathname={pathname} text={text} />
        </nav>

        <div className="shrink-0 border-t border-border px-7 py-6">
          <p className="flex items-center gap-2 text-sm font-semibold text-primary-text">
            <Lightbulb className="h-5 w-5" strokeWidth={1.7} aria-hidden="true" />
            {locale === "ar" ? "وعد الأدلة" : "Evidence promise"}
          </p>
          <p className="mt-2 text-xs leading-6 text-muted">
            {locale === "ar" ? "نعمل بالأدلة لا بالادعاء." : "Evidence over unsupported claims."}
          </p>
        </div>
      </aside>

      <div className="shell:ps-[244px]">
        <header className="sticky top-0 z-30 hidden h-16 items-center justify-between border-b border-border bg-background px-7 shell:flex">
          <div className="flex min-w-0 items-center gap-2">
            <LanguageSwitch />
            <ThemeToggle />
            {!apiConfiguration.baseUrl ? <DemoNotice compact /> : null}
            {!authConfiguration.clerkEnabled ? (
              <span className="ms-2 border-s border-border ps-4 text-xs font-semibold text-primary-text">
                {locale === "ar" ? "وضع تطوير بلا مصادقة" : "Development mode · no auth"}
              </span>
            ) : null}
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <div className="min-w-0 [&>div>span:first-child]:border [&>div>span:first-child]:border-primary/70 [&>div>span:first-child]:bg-transparent [&>div>span:first-child]:text-foreground">
              <AccountControl />
            </div>
          </div>
        </header>

        <header className="sticky top-0 z-30 border-b border-border bg-background shell:hidden">
          <div className="flex h-16 items-center justify-between px-5">
            <Brand />
            <div className="flex items-center gap-1">
              <ThemeToggle />
              <button
                className="grid h-11 w-11 place-items-center text-secondary-foreground transition-colors hover:text-primary-text"
                type="button"
                aria-label={menuOpen ? (locale === "ar" ? "إغلاق القائمة" : "Close menu") : (locale === "ar" ? "فتح القائمة" : "Open menu")}
                aria-expanded={menuOpen}
                aria-controls="mobile-chapter-menu"
                onClick={() => setMenuOpen((open) => !open)}
              >
                {menuOpen ? <X className="h-6 w-6" aria-hidden="true" /> : <Menu className="h-6 w-6" aria-hidden="true" />}
              </button>
            </div>
          </div>
          <div
            className="flex h-10 items-center border-t border-border px-5"
            aria-label={locale === "ar" ? `الفصل الحالي: ${text(activeChapter.label)}` : `Current chapter: ${text(activeChapter.label)}`}
          >
            <span className="font-latin text-lg font-semibold tabular-nums text-primary-text" aria-hidden="true">{activeChapter.chapter}</span>
            <span className="mx-2 text-muted" aria-hidden="true">/</span>
            <span className="text-sm font-semibold text-secondary-foreground">{text(activeChapter.mobileLabel)}</span>
          </div>
        </header>

        {menuOpen ? (
          <div id="mobile-chapter-menu" className="fixed inset-x-0 bottom-0 top-[104px] z-40 overflow-y-auto border-t border-border bg-background px-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] pt-5 shell:hidden">
            <div className="flex items-center border-b border-border pb-5">
              <LanguageSwitch />
            </div>
            <nav className="py-4" aria-label={locale === "ar" ? "القائمة الإضافية" : "More navigation"}>
              <ChapterNavigation pathname={pathname} text={text} mobile />
            </nav>
            <div className="grid gap-4 border-t border-border pt-5">
              {!apiConfiguration.baseUrl ? <DemoNotice /> : null}
              {!authConfiguration.clerkEnabled ? (
                <p className="text-xs font-semibold leading-6 text-primary-text">
                  {locale === "ar" ? "وضع تطوير بلا مصادقة — لا تستخدم بيانات حقيقية." : "Development mode without authentication — do not use real data."}
                </p>
              ) : null}
              <div className="[&>div>span:first-child]:border [&>div>span:first-child]:border-primary/70 [&>div>span:first-child]:bg-transparent [&>div>span:first-child]:text-foreground">
                <AccountControl sidebar />
              </div>
            </div>
          </div>
        ) : null}

        <main className="min-h-[calc(100vh-104px)] shell:min-h-[calc(100vh-64px)]">{children}</main>
      </div>
    </div>
  );
}
