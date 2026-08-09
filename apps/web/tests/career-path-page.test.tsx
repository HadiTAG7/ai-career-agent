import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const emptyWorkspace = {
  provider_ready: true,
  provider: "openai",
  model: "gpt-test",
  profile_id: "profile-1",
  confirmed_fact_count: 4,
  consent_required: true,
  conversation: null,
};

const suggestion = {
  title: "محلل أعمال",
  why_fit: ["ذكرت أنك تستمتع بالتحليل وحل المشكلات."],
  unknowns: ["مدى ارتياحك للتواصل مع أصحاب المصلحة."],
  seven_day_experiment: "حلّل عملية تعرفها واكتب توصيتين لتحسينها.",
  signal: "partial" as const,
  evidence: [
    { source: "chat" as const, reference: "أحب الأرقام والتحليل" },
    { source: "confirmed_fact" as const, reference: "خبرة موثقة في Excel" },
  ],
};

const responseWorkspace = {
  ...emptyWorkspace,
  consent_required: false,
  conversation: {
    id: "conversation-1",
    revision: 2,
    messages: [
      { id: "message-1", role: "user" as const, content: "أحب الأرقام والتحليل", suggestions: [], model: null, created_at: "2026-08-07T10:00:00Z" },
      { id: "message-2", role: "assistant" as const, content: "هذا يعطينا مؤشرًا أوليًا، ونحتاج تجربة عملية.", suggestions: [suggestion], model: "gpt-test", created_at: "2026-08-07T10:00:01Z" },
    ],
  },
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 500 ? "Server Error" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

async function renderCareerPathPage() {
  const [{ default: CareerPathPage }, { LocaleProvider }] = await Promise.all([
    import("@/app/career-path/page"),
    import("@/lib/i18n"),
  ]);
  return render(<LocaleProvider><CareerPathPage /></LocaleProvider>);
}

describe("career path conversation", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("requires explicit data-sharing consent and renders only API suggestions", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/career-path") && !init?.method) return jsonResponse(emptyWorkspace);
      if (url.endsWith("/v1/career-path/messages") && init?.method === "POST") return jsonResponse(responseWorkspace);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    await renderCareerPathPage();

    await user.click(await screen.findByRole("button", { name: "أحب الأرقام والتحليل" }));
    const textbox = screen.getByRole("textbox", { name: "رسالتك" });
    expect(textbox).toHaveValue("أحب الأرقام والتحليل");
    const sendButton = screen.getByRole("button", { name: "إرسال" });
    expect(sendButton).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /موافقة مشاركة البيانات/ }));
    expect(sendButton).toBeEnabled();
    await user.click(sendButton);

    expect(await screen.findByRole("heading", { name: "محلل أعمال" })).toBeVisible();
    expect(screen.getByText("مؤشرات جزئية")).toBeVisible();
    expect(screen.getByText("اقتراح للاستكشاف، وليس حكمًا نهائيًا.")).toBeVisible();
    expect(screen.getByText("حقيقة مؤكدة")).toBeVisible();
    expect(screen.getByText("من المحادثة")).toBeVisible();

    const postCall = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/messages"));
    const requestBody = JSON.parse(String(postCall?.[1]?.body));
    expect(requestBody).toMatchObject({ content: "أحب الأرقام والتحليل", expected_revision: 0, data_sharing_acknowledged: true });
    expect(requestBody.client_turn_id).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("deletes the current path only after an explicit confirmation", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/career-path") && !init?.method) return jsonResponse(responseWorkspace);
      if (url.endsWith("/v1/career-path/conversation") && init?.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    await renderCareerPathPage();

    const deleteTrigger = await screen.findByRole("button", { name: "حذف مساري" });
    expect(screen.getByRole("heading", { name: "محلل أعمال" })).toBeVisible();
    await user.click(deleteTrigger);

    const dialog = screen.getByRole("alertdialog", { name: "حذف مسارك الحالي والبدء من جديد؟" });
    expect(within(dialog).getByText(/ستبقى سيرتك الذاتية وحقائق ملفك المهني/)).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "إلغاء" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "DELETE")).toBe(false);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deleteTrigger).toHaveFocus();

    await user.click(deleteTrigger);
    await user.click(screen.getByRole("button", { name: "احذف المسار" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "DELETE")).toHaveLength(1);
    });
    expect(screen.queryByRole("heading", { name: "محلل أعمال" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "حذف مساري" })).not.toBeInTheDocument();
    expect(screen.getByText("خلّنا نبدأ بما يهمك في يوم العمل.")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: /موافقة مشاركة البيانات/ })).toBeVisible();
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).endsWith("/v1/career-path"))).toHaveLength(1);
  });

  it("keeps the path and confirmation open when deletion fails", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/career-path") && !init?.method) return jsonResponse(responseWorkspace);
      if (url.endsWith("/v1/career-path/conversation") && init?.method === "DELETE") {
        return jsonResponse({ detail: "Delete failed" }, 500);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    await renderCareerPathPage();

    await user.click(await screen.findByRole("button", { name: "حذف مساري" }));
    await user.click(screen.getByRole("button", { name: "احذف المسار" }));

    const dialog = await screen.findByRole("alertdialog", { name: "حذف مسارك الحالي والبدء من جديد؟" });
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Delete failed");
    expect(within(dialog).getByRole("button", { name: "احذف المسار" })).toBeEnabled();
    expect(screen.getByText("محلل أعمال")).toBeInTheDocument();
  });

  it("shows an explicit provider-disabled state without a composer or fake suggestions", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...emptyWorkspace, provider_ready: false, model: null })));
    await renderCareerPathPage();

    expect(await screen.findByRole("heading", { name: "المستشار الذكي غير مفعّل على الخادم" })).toBeVisible();
    expect(screen.getByText("لن نعرض اقتراحات وهمية أثناء عدم جاهزية المزود.")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "رسالتك" })).not.toBeInTheDocument();
    expect(screen.queryByText("محلل أعمال")).not.toBeInTheDocument();
  });

  it("requires resume facts before rendering the career path conversation", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...emptyWorkspace, confirmed_fact_count: 0 })));
    await renderCareerPathPage();

    expect(await screen.findByRole("heading", { name: "ابدأ بسيرتك الذاتية أولًا" })).toBeVisible();
    expect(screen.getByRole("link", { name: /إنشاء أو رفع السيرة/ })).toHaveAttribute("href", "/resume");
    expect(screen.queryByRole("textbox", { name: "رسالتك" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /موافقة مشاركة البيانات/ })).not.toBeInTheDocument();
  });

  it("directs a user without a base profile through profile setup and then resume", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "Profile not found" }, 404)));
    await renderCareerPathPage();

    expect(await screen.findByRole("heading", { name: "أنشئ ملفك الأساسي أولًا" })).toBeVisible();
    expect(screen.getByText("نحتاج اسمك ولغتك أولًا، وبعدها أنشئ سيرتك الذاتية أو ارفعها قبل بدء تحديد المسار.")).toBeVisible();
    expect(screen.queryByText(/رفع السيرة ليس شرطًا/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /إنشاء الملف/ })).toHaveAttribute("href", "/profile");
  });

  it("preserves the draft after a failed send so the user can retry", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/career-path") && !init?.method) return jsonResponse({ ...emptyWorkspace, consent_required: false });
      if (url.endsWith("/messages")) return jsonResponse({ detail: "Temporary provider failure" }, 500);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    await renderCareerPathPage();
    const textbox = await screen.findByRole("textbox", { name: "رسالتك" });
    await user.type(textbox, "أحتاج مسارًا يجمع التحليل والتواصل");
    await user.click(screen.getByRole("button", { name: "إرسال" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Temporary provider failure");
    expect(textbox).toHaveValue("أحتاج مسارًا يجمع التحليل والتواصل");
    expect(screen.getByText("احتفظنا برسالتك؛ يمكنك إعادة الإرسال دون كتابتها من جديد.")).toBeVisible();
  });
});
