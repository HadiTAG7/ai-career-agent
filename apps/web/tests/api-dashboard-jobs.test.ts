import { afterEach, describe, expect, it, vi } from "vitest";

const job = (id: string, title: string) => ({
  id,
  source_url: null,
  intake_method: "manual",
  title,
  company: "Example Company",
  description: "A role description",
  location: "Riyadh",
  posted_at: null,
  expires_at: null,
  fetched_at: null,
  requirements_reviewed_at: null,
  requirements_reviewed_by_owner_id: null,
  requirements_review_hash: null,
  requirements_revision: 1,
  created_at: "2026-08-06T18:40:00Z",
  source_policy: { display_name: "Manual entry" },
  requirements: [],
});

const analysis = (id: string, jobId: string, coverage: number) => ({
  id,
  profile_id: "profile-1",
  job_id: jobId,
  coverage_score: coverage,
  mandatory_coverage_score: coverage,
  readiness_band: "medium",
  confidence_band: "high",
  decision: "improve_then_apply",
  explanation: {},
  invalidated_at: null,
  invalidation_reason: null,
  evidence_revision: 1,
  requirements_revision: 1,
  requirement_matches: [],
  created_at: "2026-08-06T18:45:00Z",
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 404 ? "Not Found" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

describe("jobs and dashboard API mapping", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("maps each job to its latest analysis and treats a 404 as not analyzed", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const firstJob = job("job-1", "Analyzed role");
    const secondJob = job("job-2", "New role");
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/v1/jobs")) return jsonResponse([firstJob, secondJob]);
      if (url.endsWith("/job-1/analyses/latest")) return jsonResponse(analysis("analysis-1", "job-1", 74));
      if (url.endsWith("/job-2/analyses/latest")) return jsonResponse({ detail: "No current analysis" }, 404);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { getJobs } = await import("@/lib/api-client");
    const result = await getJobs();

    expect(result.map((item) => item.id)).toEqual(["job-1", "job-2"]);
    expect(result[0]).toMatchObject({ analysisId: "analysis-1", coverage: 74, recommendation: "improve_then_apply" });
    expect(result[1].analysisId).toBeUndefined();
    expect(result[1].freshness.en).toBe("Added 2026-08-06");
  });

  it("does not swallow a latest-analysis server error", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/v1/jobs")) return jsonResponse([job("job-1", "Role")]);
      return jsonResponse({ detail: "Analysis service failed" }, 500);
    }));

    const { ApiHttpError, getJobs } = await import("@/lib/api-client");
    await expect(getJobs()).rejects.toBeInstanceOf(ApiHttpError);
  });

  it("joins dashboard opportunities in API order and maps the application pipeline", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const dashboard = {
      profile_id: "profile-1",
      profile_quality_percent: 50,
      confirmed_facts: 4,
      total_facts: 6,
      application_pipeline: {
        discovered: 1,
        saved: 2,
        preparing: 3,
        ready: 4,
        submitted: 5,
        interview: 6,
        rejected: 7,
        offer: 1,
        withdrawn: 0,
      },
      submitted_applications: 5,
      qualified_interviews: 2,
      qualified_interviews_per_completed_application: 0.4,
      actions_due: 3,
      top_opportunities: [analysis("analysis-2", "job-2", 88), analysis("analysis-1", "job-1", 70)],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/v1/dashboard")) return jsonResponse(dashboard);
      if (url.endsWith("/v1/jobs/job-1")) return jsonResponse(job("job-1", "First role"));
      if (url.endsWith("/v1/jobs/job-2")) return jsonResponse(job("job-2", "Second role"));
      throw new Error(`Unexpected request: ${url}`);
    }));

    const { getDashboard } = await import("@/lib/api-client");
    const result = await getDashboard();

    expect(result.topOpportunities.map((item) => item.id)).toEqual(["job-2", "job-1"]);
    expect(result.applicationStages).toEqual({ saved: 3, ready: 7, applied: 5, interviews: 6 });
    expect(result).toMatchObject({ profileQualityPercent: 50, interviewRate: 0.4, actionsDue: 3 });
  });

  it("does not request job details when the dashboard has no opportunities", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      profile_id: "profile-1",
      profile_quality_percent: 0,
      confirmed_facts: 1,
      total_facts: 1,
      application_pipeline: {},
      submitted_applications: 0,
      qualified_interviews: 0,
      qualified_interviews_per_completed_application: null,
      actions_due: 0,
      top_opportunities: [],
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { getDashboard } = await import("@/lib/api-client");
    const result = await getDashboard();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.topOpportunities).toEqual([]);
    expect(result.applicationStages).toEqual({ saved: 0, ready: 0, applied: 0, interviews: 0 });
  });
});
