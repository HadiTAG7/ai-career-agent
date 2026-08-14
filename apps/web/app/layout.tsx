import type { Metadata } from "next";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/noto-sans-arabic/400.css";
import "@fontsource/noto-sans-arabic/500.css";
import "@fontsource/noto-sans-arabic/600.css";
import "@fontsource/noto-sans-arabic/700.css";
import "./globals.css";
import { AuthGate } from "@/components/auth/auth-gate";
import { AppShell } from "@/components/layout/app-shell";
import { LocaleInitScript } from "@/components/layout/locale-init-script";
import { ThemeInitScript } from "@/components/layout/theme-init-script";
import { LocaleProvider } from "@/lib/i18n";
import { ThemeProvider } from "@/lib/theme";

export const metadata: Metadata = {
  title: { default: "AI Career Agent", template: "%s · AI Career Agent" },
  description: "Evidence-first career application workspace for the Saudi market.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ar" dir="rtl" data-theme="dark" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head><ThemeInitScript /><LocaleInitScript /></head>
      <body>
        <ThemeProvider>
          <LocaleProvider>
            <AuthGate><AppShell>{children}</AppShell></AuthGate>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
