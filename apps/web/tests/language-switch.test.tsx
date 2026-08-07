import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LanguageSwitch } from "@/components/layout/language-switch";
import { LocaleProvider } from "@/lib/i18n";

describe("LanguageSwitch", () => {
  it("switches the document direction and persists English", async () => {
    const user = userEvent.setup();
    render(<LocaleProvider><LanguageSwitch /></LocaleProvider>);

    await user.click(screen.getByRole("button", { name: "en" }));

    expect(document.documentElement).toHaveAttribute("dir", "ltr");
    expect(document.documentElement).toHaveAttribute("lang", "en");
    expect(window.localStorage.getItem("ai-career-agent:locale:v1")).toBe("en");
  });
});
