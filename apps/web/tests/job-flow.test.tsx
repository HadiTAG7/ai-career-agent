import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const navigation = vi.hoisted(() => ({ push: vi.fn(), back: vi.fn() }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "job-1" }),
  useRouter: () => navigation,
}));

const requirement = {
  id: "requirement-1",
  category: "skill",
  importance: "mandatory",
  text: "Python is required",
  normalized_value: "python",
  weight: 1,
  needs_user_review: false,
  is_active: true,
  user_added: false,
};

function backendJob(reviewed: boolean) {
  return {
    id: "job-1",
    source_url: null,
    title: "Backend Engineer",
    company: "Example",
    description: "Python is required for this role.",
    location: "Riyadh",
    created_at: "2026-08-07T08:00:00Z",
    requirements_reviewed_at: reviewed ? "2026-08-07T08:05:00Z" : null,
    source_policy: { display_name: "Manual entry" },
    requirements: [requirement],
  };
}

const profile = {
  id: "profile-1",
  full_name: "Hadi",
  headline: null,
  preferred_language: "ar",
  city: "Riyadh",
  completed_fact_categories: ["skill"],
};

const analysis = {
  id: "analysis-1",
  profile_id: profile.id,
  job_id: "job-1",
  coverage_score: 100,
  mandatory_coverage_score: 100,
  readiness_band: "high",
  confidence_band: "high",
  decision: "apply_now",
  explanation: {},
  invalidated_at: null,
  invalidation_reason: null,
  evidence_revision: 1,
  requirements_revision: 1,
  requirement_matches: [{
    id: "match-1",
    requirement_id: requirement.id,
    evidence_fact_id: null,
    status: "matched",
    reason: "Covered by a confirmed profile fact",
    earned_weight: 2,
    requirement,
  }],
  created_at: "2026-08-07T08:06:00Z",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 404 ? "Not Found" : status === 201 ? "Created" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

describe("reviewed job workflow", () => {
  afterEach(() => {
    navigation.push.mockReset();
    navigation.back.mockReset();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("reviews extracted requirements, runs matching, then saves the application", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    let reviewed = false;
    let analyzed = false;
    let applicationPosts = 0;
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: false,
      media: "",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    vi.stubGlobal("fetch", vi.fn(async (request: string | URL | Request, init?: RequestInit) => {
      const url = String(request);
      if (url.endsWith("/v1/jobs/job-1") && !init?.method) return jsonResponse(backendJob(reviewed));
      if (url.endsWith("/v1/jobs/job-1/analyses/latest") && !init?.method) return analyzed ? jsonResponse(analysis) : jsonResponse({ detail: "No current analysis found" }, 404);
      if (url.endsWith("/v1/profiles") && !init?.method) return jsonResponse(profile);
      if (url.endsWith("/v1/profiles/profile-1/facts") && !init?.method) return jsonResponse([]);
      if (url.endsWith("/v1/profiles/profile-1/sources") && !init?.method) return jsonResponse([]);
      if (url.endsWith("/v1/jobs/job-1/requirements/review") && init?.method === "POST") {
        reviewed = true;
        return jsonResponse(backendJob(true));
      }
      if (url.endsWith("/v1/jobs/job-1/analyze") && init?.method === "POST") {
        analyzed = true;
        return jsonResponse(analysis);
      }
      if (url.endsWith("/v1/applications") && init?.method === "POST") {
        applicationPosts += 1;
        expect(JSON.parse(String(init.body))).toMatchObject({ job_id: "job-1", analysis_id: "analysis-1", status: "saved" });
        return jsonResponse({ id: "application-1", job_id: "job-1", status: "saved" }, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const [{ default: JobAnalysisPage }, { LocaleProvider }] = await Promise.all([
      import("@/app/jobs/[id]/page"),
      import("@/lib/i18n"),
    ]);
    const user = userEvent.setup();
    render(<LocaleProvider><JobAnalysisPage /></LocaleProvider>);

    expect(await screen.findByText(/الخطوة 2 من 3/)).toBeVisible();
    expect(screen.getByRole("button", { name: "حفظ للمتابعة" })).toBeDisabled();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "اعتماد وتشغيل المطابقة" }));

    expect(await screen.findByText(/الخطوة 3 من 3/)).toBeVisible();
    expect(screen.getAllByText("100%")).toHaveLength(2);
    const saveButton = screen.getByRole("button", { name: "حفظ للمتابعة" });
    expect(saveButton).toBeEnabled();
    await user.click(saveButton);

    expect(await screen.findByRole("link", { name: "عرض لوحة التقديمات" })).toHaveAttribute("href", "/applications");
    await waitFor(() => expect(screen.getByRole("button", { name: "محفوظ للمتابعة" })).toBeDisabled());
    expect(applicationPosts).toBe(1);
  });

  it("retries matching without reconfirming requirements after a transient failure", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    let reviewed = false;
    let analyzed = false;
    let reviewCalls = 0;
    let analyzeCalls = 0;
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: false,
      media: "",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    vi.stubGlobal("fetch", vi.fn(async (request: string | URL | Request, init?: RequestInit) => {
      const url = String(request);
      if (url.endsWith("/v1/jobs/job-1") && !init?.method) return jsonResponse(backendJob(reviewed));
      if (url.endsWith("/v1/jobs/job-1/analyses/latest") && !init?.method) return analyzed ? jsonResponse(analysis) : jsonResponse({ detail: "No current analysis found" }, 404);
      if (url.endsWith("/v1/profiles") && !init?.method) return jsonResponse(profile);
      if (url.endsWith("/v1/profiles/profile-1/facts") && !init?.method) return jsonResponse([]);
      if (url.endsWith("/v1/profiles/profile-1/sources") && !init?.method) return jsonResponse([]);
      if (url.endsWith("/v1/jobs/job-1/requirements/review") && init?.method === "POST") {
        reviewed = true;
        reviewCalls += 1;
        return jsonResponse(backendJob(true));
      }
      if (url.endsWith("/v1/jobs/job-1/analyze") && init?.method === "POST") {
        analyzeCalls += 1;
        if (analyzeCalls === 1) return jsonResponse({ detail: "Temporary matching failure" }, 500);
        analyzed = true;
        return jsonResponse(analysis);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    const [{ default: JobAnalysisPage }, { LocaleProvider }] = await Promise.all([
      import("@/app/jobs/[id]/page"),
      import("@/lib/i18n"),
    ]);
    const user = userEvent.setup();
    render(<LocaleProvider><JobAnalysisPage /></LocaleProvider>);

    await user.click(await screen.findByRole("button", { name: "اعتماد وتشغيل المطابقة" }));
    const retry = await screen.findByRole("button", { name: "إعادة تشغيل المطابقة" });
    expect(screen.getByText(/المطابقة لم تكتمل/)).toBeVisible();
    expect(reviewCalls).toBe(1);
    expect(analyzeCalls).toBe(1);

    await user.click(retry);

    expect(await screen.findByText(/الخطوة 3 من 3/)).toBeVisible();
    expect(reviewCalls).toBe(1);
    expect(analyzeCalls).toBe(2);
  });
});
