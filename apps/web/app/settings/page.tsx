"use client";

import { useState } from "react";
import { Database, Download, ShieldCheck, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiConfiguration, apiErrorMessage, deleteMyData, exportMyData } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import { clearCareerAgentLocalData } from "@/lib/local-store";

export default function SettingsPage() {
  const { locale } = useLocale();
  const [analytics, setAnalytics] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleExport() {
    if (!apiConfiguration.baseUrl) {
      setNotice(locale === "ar" ? "التصدير الحقيقي متاح عند ربط FastAPI؛ هذا الوضع تجريبي فقط." : "Real export is available when FastAPI is connected; this is demo-only mode.");
      return;
    }
    setBusy(true);
    try {
      const blob = await exportMyData();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "career-agent-export.json";
      anchor.click();
      URL.revokeObjectURL(url);
      setNotice(locale === "ar" ? "تم تصدير بياناتك." : "Your data was exported.");
    } catch (error) {
      setNotice(apiErrorMessage(error, locale));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(locale === "ar" ? "حذف بيانات مساحتك المهنية؟ لا يمكن التراجع عن حذف هذه البيانات، لكن حساب تسجيل الدخول سيبقى." : "Delete your career workspace data? This data deletion cannot be undone, but your sign-in account will remain.")) return;
    setBusy(true);
    try {
      if (apiConfiguration.baseUrl) await deleteMyData();
      clearCareerAgentLocalData();
      setNotice(locale === "ar" ? "حُذفت بيانات المساحة المهنية. بقي حساب تسجيل الدخول كما هو." : "Career workspace data was deleted. Your sign-in account remains active.");
    } catch (error) {
      setNotice(apiErrorMessage(error, locale));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-wrap page-enter max-w-[900px]">
      <h1 className="page-title">{locale === "ar" ? "الإعدادات" : "Settings"}</h1>
      <p className="mt-2 text-muted">{locale === "ar" ? "تحكم في اللغة والخصوصية ووضع الاتصال." : "Control language, privacy, and connection mode."}</p>
      <div className="mt-8 divide-y divide-border border-y border-border">
        <section className="py-7"><h2 className="section-title flex items-center gap-2"><Database className="h-5 w-5 text-primary-text" />{locale === "ar" ? "اتصال البيانات" : "Data connection"}</h2><p className="mt-3 text-sm text-muted">{locale === "ar" ? "الوضع الحالي" : "Current mode"}: <code dir="ltr" className="border-b border-border px-2 py-1 text-foreground">{apiConfiguration.mode}</code></p><p className="mt-2 text-xs text-muted">{apiConfiguration.baseUrl ? (locale === "ar" ? "الوضع متصل بالخادم ويفشل بأمان عند انقطاعه؛ لا تُستبدل بياناتك بنتائج تجريبية." : "Connected mode fails closed during an outage; your data is never replaced with demo results.") : (locale === "ar" ? "لا يوجد خادم مضبوط؛ تعمل الواجهة كساحة تجريبية محلية موسومة بوضوح." : "No server is configured; the interface runs as a clearly labeled local demo sandbox.")}</p></section>
        <section className="py-7"><h2 className="section-title flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-emerald" />{locale === "ar" ? "الخصوصية" : "Privacy"}</h2><label className="mt-4 flex min-h-14 items-center justify-between gap-5 border-y border-border bg-surface px-1 py-4"><span><strong className="block text-sm">{locale === "ar" ? "تحليلات استخدام اختيارية" : "Optional usage analytics"}</strong><small className="text-muted">{locale === "ar" ? "مغلقة افتراضيًا في هذا النموذج." : "Off by default in this prototype."}</small></span><input className="h-5 w-5 accent-[var(--primary)]" type="checkbox" checked={analytics} onChange={(event) => setAnalytics(event.target.checked)} /></label></section>
        <section className="py-7"><h2 className="section-title">{locale === "ar" ? "بيانات المساحة المهنية" : "Career workspace data"}</h2><p className="mt-2 text-sm text-muted">{apiConfiguration.baseUrl ? (locale === "ar" ? "التصدير والحذف ينفذان عبر FastAPI وبجلسة تسجيل الدخول الحالية. الحذف يزيل بيانات المساحة المهنية فقط؛ حساب Clerk والجلسة يبقيان إلى أن ندمج حذف حساب الدخول قبل الإنتاج." : "Export and deletion run through FastAPI using your current authenticated session. Deletion removes career workspace data only; the Clerk account and session remain until account deletion is integrated before production.") : (locale === "ar" ? "وضع تجريبي: الحذف يمسح الحالة المحلية فقط، والتصدير الحقيقي غير متاح." : "Demo mode: deletion clears local state only, and real export is unavailable.")}</p><div className="mt-4 flex flex-wrap gap-3"><Button variant="secondary" disabled={busy} onClick={() => { void handleExport(); }}><Download className="h-4 w-4" />{locale === "ar" ? "تصدير بياناتي" : "Export my data"}</Button><Button variant="danger" disabled={busy} onClick={() => { void handleDelete(); }}><Trash2 className="h-4 w-4" />{apiConfiguration.baseUrl ? (locale === "ar" ? "حذف بيانات المساحة المهنية" : "Delete workspace data") : (locale === "ar" ? "مسح بيانات النموذج" : "Clear demo data")}</Button></div></section>
      </div>
      {notice ? <p className="mt-4 border-y border-emerald bg-emerald-pale/40 py-3 text-sm" role="status">{notice}</p> : null}
    </div>
  );
}
