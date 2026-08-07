import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "@/components/layout/app-shell";
import { LocaleProvider } from "@/lib/i18n";

vi.mock("next/navigation", () => ({ usePathname: () => "/career-path" }));

describe("AppShell career path navigation", () => {
  it("places the resume before My path and keeps five explicit primary destinations on mobile", async () => {
    const user = userEvent.setup();
    render(<LocaleProvider><AppShell><p>content</p></AppShell></LocaleProvider>);

    const desktopSidebar = screen.getByRole("complementary", { name: "التنقل الرئيسي" });
    const desktopLinks = within(within(desktopSidebar).getByRole("navigation")).getAllByRole("link");
    expect(desktopLinks[1]).toHaveTextContent("السيرة الذاتية");
    expect(desktopLinks[1]).toHaveAttribute("href", "/resume");
    expect(desktopLinks[2]).toHaveTextContent("مساري");
    expect(desktopLinks[2]).toHaveAttribute("aria-current", "page");

    const mobileNavigation = screen.getByRole("navigation", { name: "التنقل الرئيسي" });
    const mobileLinks = within(mobileNavigation).getAllByRole("link");
    expect(mobileLinks).toHaveLength(5);
    expect(mobileLinks.map((link) => link.textContent)).toEqual(["الرئيسية", "السيرة", "مساري", "الفرص", "التقديمات"]);
    expect(mobileLinks[1]).toHaveAttribute("href", "/resume");
    expect(mobileLinks[2]).toHaveAttribute("href", "/career-path");
    expect(mobileLinks[2]).toHaveAttribute("aria-current", "page");

    await user.click(screen.getByRole("button", { name: "فتح القائمة" }));
    const moreNavigation = screen.getByRole("navigation", { name: "القائمة الإضافية" });
    expect(within(moreNavigation).getByRole("link", { name: "الملف المهني" })).toBeVisible();
    expect(within(moreNavigation).getByRole("link", { name: "المستندات" })).toBeVisible();
    expect(within(moreNavigation).getByRole("link", { name: "الإعدادات" })).toBeVisible();
    expect(within(moreNavigation).queryByRole("link", { name: "مساري" })).not.toBeInTheDocument();
  });
});
