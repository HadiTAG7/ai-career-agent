import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "@/components/layout/app-shell";
import { LocaleProvider } from "@/lib/i18n";
import { ThemeProvider } from "@/lib/theme";

vi.mock("next/navigation", () => ({ usePathname: () => "/career-path" }));

function renderShell() {
  return render(
    <ThemeProvider>
      <LocaleProvider><AppShell><p>content</p></AppShell></LocaleProvider>
    </ThemeProvider>,
  );
}

describe("AppShell chapter navigation", () => {
  it("keeps the exact desktop chapter order and exposes the current chapter on mobile", async () => {
    const user = userEvent.setup();
    renderShell();

    const desktopSidebar = screen.getByRole("complementary", { name: "التنقل الرئيسي" });
    const desktopNavigation = within(desktopSidebar).getByRole("navigation", { name: "التنقل الرئيسي" });
    const desktopLinks = within(desktopNavigation).getAllByRole("link");
    expect(desktopLinks).toHaveLength(8);
    expect(desktopLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/dashboard",
      "/resume",
      "/career-path",
      "/profile",
      "/jobs",
      "/applications",
      "/documents",
      "/settings",
    ]);
    expect(desktopLinks[1]).toHaveTextContent("02");
    expect(desktopLinks[1]).toHaveTextContent("السيرة الذاتية");
    expect(desktopLinks[2]).toHaveTextContent("مساري");
    expect(desktopLinks[2]).toHaveAttribute("aria-current", "page");

    const currentChapter = screen.getByLabelText("الفصل الحالي: مساري");
    expect(currentChapter).toHaveTextContent("03");
    expect(currentChapter).toHaveTextContent("مساري");
    expect(screen.getAllByRole("navigation", { name: "التنقل الرئيسي" })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "فتح القائمة" }));
    const moreNavigation = screen.getByRole("navigation", { name: "القائمة الإضافية" });
    const mobileLinks = within(moreNavigation).getAllByRole("link");
    expect(mobileLinks).toHaveLength(8);
    expect(mobileLinks.map((link) => link.getAttribute("href"))).toEqual(desktopLinks.map((link) => link.getAttribute("href")));
    expect(within(moreNavigation).getByRole("link", { name: "الملف المهني" })).toBeVisible();
    expect(within(moreNavigation).getByRole("link", { name: "المستندات" })).toBeVisible();
    expect(within(moreNavigation).getByRole("link", { name: "الإعدادات" })).toBeVisible();
  });

  it("mirrors document direction without changing chapter order", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "en" }));

    expect(document.documentElement).toHaveAttribute("dir", "ltr");
    const desktopSidebar = screen.getByRole("complementary", { name: "Primary navigation" });
    const desktopLinks = within(within(desktopSidebar).getByRole("navigation", { name: "Primary navigation" })).getAllByRole("link");
    expect(desktopLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/dashboard",
      "/resume",
      "/career-path",
      "/profile",
      "/jobs",
      "/applications",
      "/documents",
      "/settings",
    ]);
    expect(desktopLinks[2]).toHaveAccessibleName("My path");
    expect(desktopLinks[2]).toHaveAttribute("aria-current", "page");
  });
});
