import type { LocalizedText } from "@/lib/types";

export type NavigationItem = {
  chapter: string;
  href: string;
  label: LocalizedText;
  mobileLabel: LocalizedText;
};

export const navigationItems: NavigationItem[] = [
  { chapter: "01", href: "/dashboard", label: { ar: "نظرة عامة", en: "Overview" }, mobileLabel: { ar: "الرئيسية", en: "Home" } },
  { chapter: "02", href: "/resume", label: { ar: "السيرة الذاتية", en: "Resume" }, mobileLabel: { ar: "السيرة", en: "Resume" } },
  { chapter: "03", href: "/career-path", label: { ar: "مساري", en: "My path" }, mobileLabel: { ar: "مساري", en: "My path" } },
  { chapter: "04", href: "/profile", label: { ar: "الملف المهني", en: "Career profile" }, mobileLabel: { ar: "الملف", en: "Profile" } },
  { chapter: "05", href: "/jobs", label: { ar: "الفرص", en: "Opportunities" }, mobileLabel: { ar: "الفرص", en: "Jobs" } },
  { chapter: "06", href: "/applications", label: { ar: "التقديمات", en: "Applications" }, mobileLabel: { ar: "التقديمات", en: "Applications" } },
  { chapter: "07", href: "/documents", label: { ar: "المستندات", en: "Documents" }, mobileLabel: { ar: "المستندات", en: "Documents" } },
  { chapter: "08", href: "/settings", label: { ar: "الإعدادات", en: "Settings" }, mobileLabel: { ar: "الإعدادات", en: "Settings" } },
];

export function isCurrentPath(pathname: string, href: string) {
  if (href === "/dashboard") return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function currentNavigationItem(pathname: string) {
  return navigationItems.find((item) => isCurrentPath(pathname, item.href)) ?? navigationItems[0];
}
