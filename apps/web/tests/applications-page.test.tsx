import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 500 ? "Server Error" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

async function renderApplicationsPage() {
  const [{ default: ApplicationsPage }, { LocaleProvider }] = await Promise.all([
    import("@/app/applications/page"),
    import("@/lib/i18n"),
  ]);
  return render(<LocaleProvider><ApplicationsPage /></LocaleProvider>);
}

describe("connected application tracker", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("does not flash the empty state while applications are loading", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    let resolveRequest!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { resolveRequest = resolve; })));
    await renderApplicationsPage();

    expect(await screen.findByText("جارٍ تحميل التقديمات…")).toBeVisible();
    expect(screen.queryByText("لا توجد تقديمات في هذه المرحلة")).not.toBeInTheDocument();

    await act(async () => { resolveRequest(jsonResponse([])); });
    expect(await screen.findByText("لا توجد تقديمات في هذه المرحلة")).toBeVisible();
  });

  it("offers a working retry after a load error", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      calls += 1;
      return calls === 1 ? jsonResponse({ detail: "Temporary failure" }, 500) : jsonResponse([]);
    }));
    const user = userEvent.setup();
    await renderApplicationsPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Temporary failure");
    await user.click(screen.getByRole("button", { name: "إعادة المحاولة" }));

    expect(await screen.findByText("لا توجد تقديمات في هذه المرحلة")).toBeVisible();
    expect(calls).toBe(2);
  });
});
