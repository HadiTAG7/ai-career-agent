"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bell,
  BriefcaseBusiness,
  Compass,
  FileText,
  FileUser,
  FolderOpen,
  LayoutDashboard,
  Menu,
  Settings,
  UserRound,
  X,
} from "lucide-react";
import { AccountControl } from "@/components/auth/account-control";
import { authConfiguration } from "@/components/auth/auth-gate";
import { Brand } from "@/components/layout/brand";
import { LanguageSwitch } from "@/components/layout/language-switch";
import { DemoNotice } from "@/components/ui/demo-notice";
import { apiConfiguration } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: { ar: "نظرة عامة", en: "Overview" }, mobileLabel: { ar: "الرئيسية", en: "Home" }, icon: LayoutDashboard, mobile: true },
  { href: "/resume", label: { ar: "السيرة الذاتية", en: "Resume" }, mobileLabel: { ar: "السيرة", en: "Resume" }, icon: FileUser, mobile: true },
  { href: "/career-path", label: { ar: "مساري", en: "My path" }, mobileLabel: { ar: "مساري", en: "My path" }, icon: Compass, mobile: true },
  { href: "/profile", label: { ar: "الملف المهني", en: "Career profile" }, mobileLabel: { ar: "الملف", en: "Profile" }, icon: UserRound, mobile: false },
  { href: "/jobs", label: { ar: "الفرص", en: "Opportunities" }, mobileLabel: { ar: "الفرص", en: "Jobs" }, icon: BriefcaseBusiness, mobile: true },
  { href: "/applications", label: { ar: "التقديمات", en: "Applications" }, mobileLabel: { ar: "التقديمات", en: "Applications" }, icon: FileText, mobile: true },
  { href: "/documents", label: { ar: "المستندات", en: "Documents" }, mobileLabel: { ar: "المستندات", en: "Documents" }, icon: FolderOpen, mobile: false },
  { href: "/settings", label: { ar: "الإعدادات", en: "Settings" }, mobileLabel: { ar: "الإعدادات", en: "Settings" }, icon: Settings, mobile: false },
];

const mobileItems = navItems.filter((item) => item.mobile);
const moreItems = navItems.filter((item) => !item.mobile);

function isCurrentPath(pathname: string, href: string) {
  if (href === "/dashboard") return pathname === href;
  return pathname.startsWith(href);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { locale, text } = useLocale();
  const [menuOpen, setMenuOpen] = useState(false);
  const resumeWorkspace = pathname.startsWith("/resume");

  useEffect(() => {
    // Route changes are an external navigation event; close any stale mobile drawer.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMenuOpen(false);
  }, [pathname]);

  return (
    <div className="min-h-screen bg-white text-ink">
      <aside className={cn(
        "fixed inset-y-0 right-0 z-40 hidden border-l lg:flex lg:flex-col",
        resumeWorkspace ? "w-[174px] border-emerald-dark bg-[#00563f] text-white" : "w-[244px] border-border bg-white",
      )} aria-label={locale === "ar" ? "التنقل الرئيسي" : "Primary navigation"}>
        <div className={cn("flex h-20 items-center px-6", resumeWorkspace ? "border-b border-white/15 [&_a]:!text-white" : "border-b border-border")}>
          <Brand compact={resumeWorkspace} />
          {resumeWorkspace ? <span className="ms-2 text-sm font-bold leading-5 text-white">{locale === "ar" ? "المستشار\nالمهني" : "Career\nAgent"}</span> : null}
        </div>
        <nav className={cn("flex-1 space-y-2", resumeWorkspace ? "px-3 py-7" : "px-4 py-8")}>
          {navItems.map((item) => {
            const active = isCurrentPath(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                className={cn(
                  "relative flex min-h-[52px] items-center gap-4 rounded-lg px-4 text-sm font-semibold transition-colors",
                  resumeWorkspace
                    ? active ? "bg-[#0b7c5b] text-white" : "text-white/88 hover:bg-white/10 hover:text-white"
                    : active ? "bg-emerald-pale text-ink" : "text-ink hover:bg-slate-50"
                )}
                href={item.href}
                key={item.href}
                aria-current={active ? "page" : undefined}
              >
                {active && !resumeWorkspace ? <span className="absolute -right-4 h-full w-1 rounded-l-full bg-emerald" aria-hidden="true" /> : null}
                <Icon className={cn("h-5 w-5", resumeWorkspace ? "text-current" : active ? "text-emerald" : "text-ink")} strokeWidth={1.7} aria-hidden="true" />
                {text(item.label)}
              </Link>
            );
          })}
        </nav>
        <div className={cn("border-t p-5", resumeWorkspace ? "border-white/15 [&_*]:!text-white" : "border-border")}>
          <div className="min-h-12 rounded-lg px-2 py-1"><AccountControl sidebar /></div>
        </div>
      </aside>

      <div className={resumeWorkspace ? "lg:pr-[174px]" : "lg:pr-[244px]"}>
        {resumeWorkspace ? null : <header className="sticky top-0 z-30 hidden h-20 items-center justify-between border-b border-border bg-white/95 px-8 backdrop-blur-sm lg:flex">
          <div className="flex items-center gap-3">
            <LanguageSwitch />
            {!apiConfiguration.baseUrl ? <DemoNotice compact /> : null}
            {!authConfiguration.clerkEnabled ? <span className="text-xs font-semibold text-amber">{locale === "ar" ? "وضع تطوير بلا مصادقة" : "Development mode · no auth"}</span> : null}
          </div>
          <div className="flex items-center gap-5">
            <button className="grid h-11 w-11 place-items-center rounded-lg hover:bg-slate-50" type="button" aria-label={locale === "ar" ? "الإشعارات" : "Notifications"}>
              <Bell className="h-5 w-5" strokeWidth={1.7} />
            </button>
            <AccountControl />
          </div>
        </header>}

        <header className="sticky top-0 z-30 flex h-[86px] items-center justify-between border-b border-border bg-white/95 px-5 backdrop-blur-sm lg:hidden">
          <Brand />
          <div className="flex items-center gap-3">
            <LanguageSwitch />
            <button
              className="grid h-11 w-11 place-items-center rounded-lg border border-border bg-white"
              type="button"
              aria-label={locale === "ar" ? "فتح القائمة" : "Open menu"}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              {menuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>
        </header>

        {menuOpen ? (
          <div className="fixed inset-x-0 top-[86px] z-40 border-b border-border bg-white px-5 py-4 shadow-subtle lg:hidden">
            <nav className="grid gap-2" aria-label={locale === "ar" ? "القائمة الإضافية" : "More navigation"}>
              {moreItems.map((item) => {
                const Icon = item.icon;
                return (
                  <Link href={item.href} key={item.href} className="flex min-h-12 items-center gap-3 rounded-lg px-3 font-semibold hover:bg-slate-50">
                    <Icon className="h-5 w-5" /> {text(item.label)}
                  </Link>
                );
              })}
              {!apiConfiguration.baseUrl ? <DemoNotice className="px-3 py-2" /> : null}
              {!authConfiguration.clerkEnabled ? <p className="px-3 py-2 text-xs font-semibold text-amber">{locale === "ar" ? "وضع تطوير بلا مصادقة — لا تستخدم بيانات حقيقية." : "Development mode without authentication — do not use real data."}</p> : null}
            </nav>
          </div>
        ) : null}

        <main className={cn("pb-24 lg:pb-0", resumeWorkspace ? "min-h-screen" : "min-h-[calc(100vh-80px)]")}>{children}</main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-border bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm lg:hidden" aria-label={locale === "ar" ? "التنقل الرئيسي" : "Primary navigation"}>
        {mobileItems.map((item) => {
          const active = isCurrentPath(pathname, item.href);
          const Icon = item.icon;
          return (
            <Link
              href={item.href}
              key={item.href}
              className={cn(
                "relative min-w-0 flex min-h-[72px] flex-col items-center justify-center gap-1 px-1 text-[10px] font-semibold sm:text-[11px]",
                active ? "text-ink" : "text-muted"
              )}
              aria-current={active ? "page" : undefined}
            >
              {active ? <span className="absolute inset-x-4 top-0 h-1 rounded-b-full bg-emerald" aria-hidden="true" /> : null}
              <Icon className="h-6 w-6" fill={active ? "currentColor" : "none"} strokeWidth={active ? 1.6 : 1.8} aria-hidden="true" />
              <span className="max-w-full truncate">{text(item.mobileLabel)}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
