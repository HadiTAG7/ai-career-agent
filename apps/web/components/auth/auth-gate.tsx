"use client";

import { useEffect } from "react";
import { ClerkProvider, SignInButton, useAuth } from "@clerk/nextjs";
import { LogIn, ShieldCheck } from "lucide-react";
import { Brand } from "@/components/layout/brand";
import { LanguageSwitch } from "@/components/layout/language-switch";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { setApiTokenGetter } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import { clearCareerAgentLocalData } from "@/lib/local-store";

const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
const devAuthBypass = process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS === "true";

function ClerkTokenBridge() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  useEffect(() => {
    setApiTokenGetter(() => getToken());
    return () => setApiTokenGetter(null);
  }, [getToken]);
  useEffect(() => {
    if (isLoaded && !isSignedIn) clearCareerAgentLocalData();
  }, [isLoaded, isSignedIn]);
  return null;
}

function SignInGuard() {
  const { locale } = useLocale();
  return (
    <main className="grid min-h-screen place-items-center bg-background p-5">
      <section className="w-full max-w-md border-y border-border py-8 text-center">
        <div className="flex items-center justify-between gap-3"><Brand /><div className="flex items-center gap-2"><ThemeToggle /><LanguageSwitch /></div></div>
        <ShieldCheck className="mx-auto mt-10 h-10 w-10 text-emerald" />
        <h1 className="mt-5 text-2xl font-bold">{locale === "ar" ? "سجّل الدخول إلى مساحتك المهنية" : "Sign in to your career workspace"}</h1>
        <p className="mt-3 text-sm text-muted">{locale === "ar" ? "يحمي تسجيل الدخول حقائقك المهنية ومستنداتك وسجل تقديماتك." : "Authentication protects your career facts, documents, and application history."}</p>
        <SignInButton mode="modal">
          <button className="mt-7 inline-flex min-h-[52px] w-full items-center justify-center gap-2 bg-primary px-6 font-semibold text-primary-foreground hover:bg-primary-hover" type="button"><LogIn className="h-5 w-5" />{locale === "ar" ? "تسجيل الدخول" : "Sign in"}</button>
        </SignInButton>
      </section>
    </main>
  );
}

function ClerkSessionGuard({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth();
  if (!isLoaded) return <div className="grid min-h-screen place-items-center text-sm text-muted" role="status">Loading secure workspace…</div>;
  return isSignedIn ? children : <SignInGuard />;
}

function AuthNotConfigured() {
  const { locale } = useLocale();
  return (
    <main className="grid min-h-screen place-items-center bg-background p-5">
      <section className="w-full max-w-md border-y border-border py-8 text-center">
        <div className="flex items-center justify-between gap-3"><Brand /><div className="flex items-center gap-2"><ThemeToggle /><LanguageSwitch /></div></div>
        <ShieldCheck className="mx-auto mt-10 h-10 w-10 text-danger" />
        <h1 className="mt-5 text-2xl font-bold">{locale === "ar" ? "المصادقة غير مهيأة" : "Authentication is not configured"}</h1>
        <p className="mt-3 text-sm text-muted">{locale === "ar" ? "لم يتم ضبط NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY. لحماية بياناتك، لا يعمل التطبيق بدون مصادقة إلا عند تفعيل وضع التطوير صراحة عبر NEXT_PUBLIC_DEV_AUTH_BYPASS=true." : "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is not set. To protect your data, the app refuses to run without authentication unless development mode is explicitly enabled via NEXT_PUBLIC_DEV_AUTH_BYPASS=true."}</p>
      </section>
    </main>
  );
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  if (!publishableKey) {
    // Fail closed: an unauthenticated app is only reachable behind an explicit local-dev flag.
    return devAuthBypass ? children : <AuthNotConfigured />;
  }
  return (
    <ClerkProvider publishableKey={publishableKey}>
      <ClerkTokenBridge />
      <ClerkSessionGuard>{children}</ClerkSessionGuard>
    </ClerkProvider>
  );
}

export const authConfiguration = {
  clerkEnabled: Boolean(publishableKey),
  mode: publishableKey ? "clerk" : devAuthBypass ? "development-no-auth" : "unconfigured",
} as const;
