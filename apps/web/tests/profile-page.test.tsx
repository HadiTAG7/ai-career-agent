import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const profile = {
  id: "profile-1",
  owner_id: "demo-user",
  full_name: "هادي الغانم",
  headline: null,
  summary: null,
  preferred_language: "ar",
  city: null,
  years_experience: null,
  completed_fact_categories: [],
  evidence_revision: 0,
  created_at: "2026-08-07T06:15:49Z",
  updated_at: "2026-08-07T06:15:49Z",
};

const manualSource = {
  id: "source-1",
  profile_id: profile.id,
  kind: "manual",
  label: "User-confirmed manual entries",
  original_filename: null,
  source_locator: null,
  source_metadata: {},
  created_at: "2026-08-07T06:15:49Z",
};

const identityFact = {
  id: "fact-identity",
  profile_id: profile.id,
  source_id: manualSource.id,
  category: "identity",
  label: profile.full_name,
  detail: null,
  structured_value: { profile_field: "full_name" },
  source_excerpt: profile.full_name,
  verification_status: "confirmed",
  extraction_confidence: 1,
  confirmed_at: "2026-08-07T06:15:49Z",
  user_correction_reason: null,
  user_corrected_at: null,
  original_extraction: null,
  created_at: "2026-08-07T06:15:49Z",
};

const extractedSkill = {
  ...identityFact,
  id: "fact-skill",
  source_id: "source-cv",
  category: "skill",
  label: "Python",
  detail: "Built a FastAPI service",
  structured_value: {},
  source_excerpt: "Skills: Python",
  verification_status: "extracted",
  extraction_confidence: 0.8,
  confirmed_at: null,
};

const cvSource = {
  ...manualSource,
  id: "source-cv",
  kind: "cv_upload",
  label: "Imported resume.docx",
  original_filename: "resume.docx",
};

function summary(quality = 0) {
  return {
    profile_id: profile.id,
    profile_quality_percent: quality,
    confirmed_facts: quality ? 2 : 1,
    total_facts: quality ? 2 : 1,
    extracted_facts: 0,
    unconfirmed_facts: 0,
    covered_quality_categories: quality ? ["skill"] : [],
    total_quality_categories: 6,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 422 ? "Unprocessable Entity" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

async function renderProfilePage() {
  const [{ default: ProfilePage }, { LocaleProvider }] = await Promise.all([
    import("@/app/profile/page"),
    import("@/lib/i18n"),
  ]);
  return render(<LocaleProvider><ProfilePage /></LocaleProvider>);
}

describe("connected profile workflow", () => {
  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("starts with the review filter when opened from a resume result link", async () => {
    window.history.replaceState({}, "", "/profile?status=review#facts-title");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/v1/profiles")) return jsonResponse(profile);
      if (url.endsWith("/facts")) return jsonResponse([identityFact, extractedSkill]);
      if (url.endsWith("/sources")) return jsonResponse([manualSource, cvSource]);
      if (url.endsWith("/summary")) return jsonResponse(summary(0));
      throw new Error(`Unexpected request: ${url}`);
    }));

    await renderProfilePage();

    const statusFilter = await screen.findByRole("combobox", { name: "تصفية حسب الحالة" });
    await waitFor(() => expect(statusFilter).toHaveValue("review"));
    expect(screen.getByText("Python")).toBeVisible();
    expect(screen.queryByText(profile.full_name)).not.toBeInTheDocument();
  });

  it("uses the same category-based quality metric as the dashboard", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/v1/profiles")) return jsonResponse(profile);
      if (url.endsWith("/facts")) return jsonResponse([identityFact]);
      if (url.endsWith("/sources")) return jsonResponse([manualSource]);
      if (url.endsWith("/summary")) return jsonResponse(summary(0));
      throw new Error(`Unexpected request: ${url}`);
    }));

    await renderProfilePage();

    expect(await screen.findByRole("img", { name: "جودة الملف 0 بالمئة" })).toBeVisible();
    expect(screen.getByText("0/6")).toBeVisible();
    expect(screen.queryByText("100%")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "ابدأ باستيراد سيرتك" })).toBeVisible();
  });

  it("reveals imported facts even when an earlier filter would hide them", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/profiles")) return jsonResponse(profile);
      if (url.endsWith("/facts") && !init?.method) return jsonResponse([identityFact]);
      if (url.endsWith("/sources")) return jsonResponse([manualSource]);
      if (url.endsWith("/summary")) return jsonResponse(summary(0));
      if (url.endsWith("/imports") && init?.method === "POST") {
        expect(init.body).toBeInstanceOf(FormData);
        expect(new Headers(init.headers).has("Content-Type")).toBe(false);
        return jsonResponse({ source: cvSource, facts: [extractedSkill], requires_user_review: true }, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    await renderProfilePage();
    const statusFilter = await screen.findByRole("combobox", { name: "تصفية حسب الحالة" });
    await user.selectOptions(statusFilter, "confirmed");

    await user.upload(
      screen.getByLabelText("رفع سيرة ذاتية أو أرشيف لينكدإن"),
      new File(["docx"], "resume.docx", {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      }),
    );

    expect(await screen.findByText("استُخرجت 1 حقائق؛ راجعها وأكد الصحيح فقط.")).toBeVisible();
    expect(statusFilter).toHaveValue("review");
    expect(screen.getByText("Skills: Python")).toBeVisible();
    expect(screen.getByRole("button", { name: "أؤكد صحة المعلومة" })).toBeVisible();
  });

  it("refreshes profile quality after confirming an extracted fact", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    let summaryCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/profiles")) return jsonResponse(profile);
      if (url.endsWith("/facts") && !init?.method) return jsonResponse([identityFact, extractedSkill]);
      if (url.endsWith("/sources")) return jsonResponse([manualSource, cvSource]);
      if (url.endsWith("/summary")) {
        summaryCalls += 1;
        return jsonResponse(summary(summaryCalls > 1 ? 17 : 0));
      }
      if (url.endsWith("/fact-skill/confirm") && init?.method === "POST") {
        return jsonResponse({ ...extractedSkill, verification_status: "confirmed", confirmed_at: "2026-08-07T07:00:00Z" });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    await renderProfilePage();
    await user.click(await screen.findByRole("button", { name: /المهارات Python/ }));
    await user.click(screen.getByRole("button", { name: "أؤكد صحة المعلومة" }));

    expect(await screen.findByRole("img", { name: "جودة الملف 17 بالمئة" })).toBeVisible();
    expect(screen.getByRole("link", { name: /عرض التحديث/ })).toHaveAttribute("href", "/dashboard");
  });

  it("keeps a failed add dialog open and shows an error instead of a success notice", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/profiles")) return jsonResponse(profile);
      if (url.endsWith("/facts") && !init?.method) return jsonResponse([identityFact]);
      if (url.endsWith("/sources")) return jsonResponse([manualSource]);
      if (url.endsWith("/summary")) return jsonResponse(summary(0));
      if (url.endsWith("/facts") && init?.method === "POST") return jsonResponse({ detail: "Invalid fact" }, 422);
      throw new Error(`Unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    await renderProfilePage();
    await user.click(await screen.findByRole("button", { name: "أضف حقيقة" }));
    await user.type(screen.getByRole("textbox", { name: "عنوان الحقيقة" }), "Python");
    await user.type(screen.getByRole("textbox", { name: "التفاصيل" }), "خبرة عملية");
    await user.click(screen.getByRole("button", { name: "حفظ الحقيقة" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("تعذر قبول البيانات: Invalid fact");
    expect(screen.getByRole("dialog", { name: "أضف حقيقة مهنية" })).toBeVisible();
  });
});
