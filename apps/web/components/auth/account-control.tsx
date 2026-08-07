"use client";

import { UserButton, useUser } from "@clerk/nextjs";
import { ChevronDown } from "lucide-react";
import { authConfiguration } from "@/components/auth/auth-gate";
import { useLocale } from "@/lib/i18n";

function ClerkAccount() {
  const { user } = useUser();
  return (
    <div className="flex items-center gap-3">
      <span className="max-w-40 truncate text-sm font-semibold">{user?.fullName ?? user?.primaryEmailAddress?.emailAddress}</span>
      <UserButton appearance={{ elements: { avatarBox: "h-10 w-10" } }} />
    </div>
  );
}

export function AccountControl({ sidebar = false }: { sidebar?: boolean }) {
  const { locale } = useLocale();
  if (authConfiguration.clerkEnabled) return <ClerkAccount />;
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-ink text-sm font-bold text-white">م</span>
      {sidebar ? <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{locale === "ar" ? "محمد العتيبي" : "Mohammed Alotaibi"}</span><span className="block text-xs text-muted">{locale === "ar" ? "وضع تطوير" : "Development mode"}</span></span> : <span className="text-sm font-semibold">{locale === "ar" ? "محمد العتيبي" : "Mohammed Alotaibi"}</span>}
      {sidebar ? <ChevronDown className="h-4 w-4" aria-hidden="true" /> : null}
    </div>
  );
}
