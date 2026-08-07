import { afterEach, describe, expect, it, vi } from "vitest";

const input = {
  title: "محلل بيانات",
  company: "شركة اختبار",
  location: "الرياض",
  description: "نبحث عن محلل بيانات يجيد Python وSQL وPower BI ويستطيع إعداد التقارير وتحليل احتياجات العمل.",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 201 ? "Created" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

describe("manual job API client", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("creates a local analysis when FastAPI is not configured", async () => {
    const { createManualJob } = await import("@/lib/api-client");
    const result = await createManualJob(input);

    expect(result.source).toBe("demo");
    expect(result.data.id).toBe("local-analysis");
    expect(result.data.title.ar).toBe("محلل بيانات");
    expect(result.data.company.en).toBe("شركة اختبار");
    expect(result.data.isDemo).toBe(true);
  });

  it("extracts requirements without running analysis before user review", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn(async (request: string | URL | Request, init?: RequestInit) => {
      const url = String(request);
      expect(url).toBe("https://api.test/v1/jobs/manual");
      expect(init?.method).toBe("POST");
      return jsonResponse({
        id: "job-1",
        source_url: null,
        title: input.title,
        company: input.company,
        description: input.description,
        location: input.location,
        created_at: "2026-08-07T08:00:00Z",
        requirements_reviewed_at: null,
        source_policy: { display_name: "Manual entry" },
        requirements: [{
          id: "requirement-1",
          category: "skill",
          importance: "mandatory",
          text: "Python مطلوب",
          weight: 1,
          needs_user_review: false,
          is_active: true,
          user_added: false,
        }],
      }, 201);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { createManualJob } = await import("@/lib/api-client");

    const result = await createManualJob(input);

    expect(result.source).toBe("api");
    expect(result.data.analysisId).toBeUndefined();
    expect(result.data.requirements[0].status).toBe("unknown");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
