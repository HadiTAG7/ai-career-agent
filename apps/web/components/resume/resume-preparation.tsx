"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  LoaderCircle,
  RotateCcw,
  ServerOff,
  UserRoundPlus,
} from "lucide-react";
import { ResumeWorkspaceV2 } from "@/components/resume/resume-workspace-v2";
import { Button } from "@/components/ui/button";
import {
  apiConfiguration,
  apiErrorMessage,
  createCareerProfile,
  getCareerFacts,
  getCareerProfile,
  getResumeWorkspace,
  type ApiCareerFact,
  type ApiCareerProfile,
  type ApiResumeWorkspace,
} from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";

type LoadState = "loading" | "ready" | "error";

function WorkspaceMessage({
  locale,
  icon,
  title,
  description,
  action,
}: {
  locale: "ar" | "en";
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="grid min-h-[calc(100vh-104px)] place-items-center bg-background px-5 py-12 shell:min-h-[calc(100vh-64px)]">
      <section className="w-full max-w-2xl border-y border-border py-10" aria-live="polite">
        <div className="flex items-center justify-between border-b border-border pb-4 text-xs font-semibold uppercase tracking-[0.18em] text-muted">
          <span>{locale === "ar" ? "استوديو تدقيق السيرة" : "Resume proofing studio"}</span>
          <span className="font-latin text-primary-text">02 / RESUME</span>
        </div>
        <div className="mt-8 grid h-12 w-12 place-items-center border border-emerald text-emerald">{icon}</div>
        <h1 className="mt-6 text-2xl font-bold text-foreground md:text-3xl">{title}</h1>
        <p className="mt-3 max-w-xl text-sm leading-7 text-muted">{description}</p>
        {action ? <div className="mt-7 flex">{action}</div> : null}
        <span className="sr-only">{locale}</span>
      </section>
    </div>
  );
}

export function ResumePreparation() {
  const { locale } = useLocale();
  const [loadState, setLoadState] = useState<LoadState>(() => apiConfiguration.baseUrl ? "loading" : "ready");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [profile, setProfile] = useState<ApiCareerProfile | null>(null);
  const [facts, setFacts] = useState<ApiCareerFact[]>([]);
  const [workspace, setWorkspace] = useState<ApiResumeWorkspace | null>(null);
  const [creatingProfile, setCreatingProfile] = useState(false);
  const [profileError, setProfileError] = useState<unknown>(null);
  const [waitingForServer, setWaitingForServer] = useState(false);

  useEffect(() => {
    if (loadState !== "loading") return;
    const timer = window.setTimeout(() => setWaitingForServer(true), 5_000);
    return () => window.clearTimeout(timer);
  }, [loadState]);

  useEffect(() => {
    if (!apiConfiguration.baseUrl) return;
    let active = true;
    async function load() {
      setWaitingForServer(false);
      setLoadState("loading");
      try {
        const existingProfile = await getCareerProfile();
        if (!active) return;
        setProfile(existingProfile);
        if (existingProfile) {
          const [profileFacts, resumeWorkspace] = await Promise.all([
            getCareerFacts(existingProfile.id),
            getResumeWorkspace(existingProfile.id),
          ]);
          if (!active) return;
          setFacts(profileFacts);
          setWorkspace(resumeWorkspace);
        }
        setLoadState("ready");
      } catch (error) {
        if (!active) return;
        setLoadError(error);
        setLoadState("error");
      }
    }
    void load();
    return () => { active = false; };
  }, [retryKey]);

  async function handleCreateProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const fullName = String(data.get("fullName") ?? "").trim();
    const city = String(data.get("city") ?? "").trim();
    if (!fullName) return;
    setCreatingProfile(true);
    setProfileError(null);
    try {
      const created = await createCareerProfile({ fullName, city, preferredLanguage: locale });
      setProfile(created);
      setFacts([]);
      setWorkspace(null);
    } catch (error) {
      setProfileError(error);
    } finally {
      setCreatingProfile(false);
    }
  }

  if (!apiConfiguration.baseUrl) {
    return (
      <WorkspaceMessage
        locale={locale}
        icon={<ServerOff className="h-7 w-7" />}
        title={locale === "ar" ? "مساحة السيرة تحتاج اتصال الخادم" : "The resume workspace needs a server connection"}
        description={locale === "ar" ? "اربط الواجهة بخادم API أولًا. لن نعرض مسودة تجريبية بدلًا من بياناتك الحقيقية." : "Connect the interface to the API server first. We will not replace your data with a demo draft."}
      />
    );
  }

  if (loadState === "loading") {
    return (
      <WorkspaceMessage
        locale={locale}
        icon={<LoaderCircle className="h-7 w-7 animate-spin" />}
        title={waitingForServer
          ? (locale === "ar" ? "نشغّل الخادم ونستعيد سيرتك" : "Waking the server and restoring your resume")
          : (locale === "ar" ? "نجهّز مساحة سيرتك" : "Preparing your resume workspace")}
        description={waitingForServer
          ? (locale === "ar"
              ? "الخادم التجريبي يستيقظ بعد الخمول. سنعيد محاولة التحميل تلقائيًا؛ لا تحتاج إلى تحديث الصفحة."
              : "The staging server is waking after being idle. We will retry automatically; you do not need to refresh.")
          : (locale === "ar" ? "نستعيد المحادثة وآخر نسخة محفوظة من سيرتك." : "Restoring your conversation and latest saved resume version.")}
      />
    );
  }

  if (loadState === "error") {
    return (
      <WorkspaceMessage
        locale={locale}
        icon={<AlertCircle className="h-7 w-7" />}
        title={locale === "ar" ? "تعذر فتح مساحة السيرة" : "Could not open the resume workspace"}
        description={apiErrorMessage(loadError, locale)}
        action={<Button variant="secondary" onClick={() => { setLoadError(null); setRetryKey((value) => value + 1); }}><RotateCcw className="h-4 w-4" />{locale === "ar" ? "إعادة المحاولة" : "Try again"}</Button>}
      />
    );
  }

  if (!profile) {
    return (
      <div className="grid min-h-[calc(100vh-104px)] place-items-center bg-background px-5 py-12 shell:min-h-[calc(100vh-64px)]">
        <section className="w-full max-w-2xl border-y border-border py-10" aria-labelledby="resume-profile-title">
          <div className="flex items-center justify-between border-b border-border pb-4 text-xs font-semibold uppercase tracking-[0.18em] text-muted">
            <span>{locale === "ar" ? "دفتر بيانات المرشح" : "Candidate record"}</span>
            <span className="font-latin text-primary-text">00 / INTAKE</span>
          </div>
          <div className="mt-8 grid h-12 w-12 place-items-center border border-emerald text-emerald"><UserRoundPlus className="h-6 w-6" /></div>
          <h1 id="resume-profile-title" className="mt-6 text-2xl font-bold text-foreground md:text-3xl">{locale === "ar" ? "عرّفنا بنفسك أولًا" : "Tell us who you are first"}</h1>
          <p className="mt-2 text-sm leading-7 text-muted">{locale === "ar" ? "نحتاج اسمك فقط لبدء مساحة السيرة. لن يُرسل الاسم أو بيانات التواصل إلى مزود الذكاء الاصطناعي." : "We only need your name to start the resume workspace. Your name and contact details are not sent to the AI provider."}</p>
          <form className="mt-7 grid gap-5 border-t border-border pt-7" onSubmit={handleCreateProfile}>
            <label><span className="field-label">{locale === "ar" ? "الاسم الكامل" : "Full name"}</span><input className="field-control" name="fullName" autoComplete="name" required maxLength={200} disabled={creatingProfile} /></label>
            <label><span className="field-label">{locale === "ar" ? "المدينة (اختياري)" : "City (optional)"}</span><input className="field-control" name="city" autoComplete="address-level2" maxLength={120} disabled={creatingProfile} /></label>
            {profileError ? <p className="border-y border-danger bg-danger-pale px-3 py-3 text-sm text-danger" role="alert">{apiErrorMessage(profileError, locale)}</p> : null}
            <Button type="submit" size="lg" className="mt-2 justify-self-start" disabled={creatingProfile}>{creatingProfile ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <ArrowLeft className="h-5 w-5 rtl:rotate-0 ltr:rotate-180" />}{creatingProfile ? (locale === "ar" ? "جارٍ الإنشاء…" : "Creating…") : (locale === "ar" ? "أنشئ ملفي وابدأ" : "Create profile and start")}</Button>
          </form>
        </section>
      </div>
    );
  }

  return (
    <ResumeWorkspaceV2
      locale={locale}
      profile={profile}
      initialFacts={facts}
      initialWorkspace={workspace}
    />
  );
}
