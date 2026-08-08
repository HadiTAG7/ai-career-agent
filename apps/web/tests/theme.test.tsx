import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { LocaleProvider } from "@/lib/i18n";
import {
  getStoredTheme,
  resolveTheme,
  THEME_STORAGE_KEY,
  ThemeProvider,
  useTheme,
} from "@/lib/theme";

function installMatchMedia(matches: boolean) {
  const listeners = new Set<() => void>();
  const mediaQuery = {
    matches,
    media: "(prefers-color-scheme: light)",
    onchange: null,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    addListener: (listener: () => void) => listeners.add(listener),
    removeListener: (listener: () => void) => listeners.delete(listener),
    dispatchEvent: () => true,
  };
  vi.stubGlobal("matchMedia", vi.fn(() => mediaQuery));
}

function ThemeReadout() {
  const { theme } = useTheme();
  return <span>{theme}</span>;
}

beforeEach(() => {
  installMatchMedia(false);
  document.documentElement.dataset.theme = "dark";
  document.documentElement.style.colorScheme = "dark";
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.dataset.theme = "dark";
  document.documentElement.style.colorScheme = "";
});

describe("theme preference", () => {
  it("uses the system preference only when no explicit choice exists", () => {
    installMatchMedia(true);
    expect(getStoredTheme()).toBeNull();
    expect(resolveTheme()).toBe("light");

    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(resolveTheme()).toBe("dark");
  });

  it("persists an accessible explicit toggle and updates the document", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <LocaleProvider><ThemeToggle /></LocaleProvider>
      </ThemeProvider>,
    );

    await user.click(screen.getByRole("button", { name: "تفعيل الوضع الفاتح" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("button", { name: "تفعيل الوضع الداكن" })).toBeVisible();
  });

  it("hydrates safely when the early initializer selected light mode", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const tree = <ThemeProvider><ThemeReadout /></ThemeProvider>;
    const container = document.createElement("div");
    container.innerHTML = renderToString(tree);
    document.body.appendChild(container);
    document.documentElement.dataset.theme = "light";

    const root = hydrateRoot(container, tree);
    await act(async () => undefined);

    expect(container).toHaveTextContent("light");
    expect(consoleError.mock.calls.flat().join(" ")).not.toMatch(/hydration|did not match/i);

    await act(async () => root.unmount());
    container.remove();
    consoleError.mockRestore();
  });
});
