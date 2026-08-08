import { afterEach, describe, expect, it, vi } from "vitest";

describe("API authentication and HTTP errors", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("adds the Clerk bearer token and does not replace a 422 response with demo data", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid profile data" }), {
      status: 422,
      statusText: "Unprocessable Entity",
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { ApiHttpError, getJob, setApiTokenGetter } = await import("@/lib/api-client");
    setApiTokenGetter(async () => "clerk-test-token");

    await expect(getJob("11111111-1111-4111-8111-111111111111")).rejects.toBeInstanceOf(ApiHttpError);
    const request = fetchMock.mock.calls[0];
    const headers = request[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer clerk-test-token");
  });

  it("fails closed on a network error when an API is configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network unavailable"));
    vi.stubGlobal("fetch", fetchMock);
    const { getJob } = await import("@/lib/api-client");

    await expect(getJob("11111111-1111-4111-8111-111111111111")).rejects.toThrow("network unavailable");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries one transient GET failure while Render is warming up", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const profile = {
      id: "11111111-1111-4111-8111-111111111111",
      full_name: "Hadi Alghanim",
      preferred_language: "ar",
      city: "Riyadh",
      created_at: "2026-08-08T00:00:00Z",
      updated_at: "2026-08-08T00:00:00Z",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Service waking" }), { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(profile), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    const { getCareerProfile } = await import("@/lib/api-client");

    await expect(getCareerProfile()).resolves.toEqual(profile);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry a non-idempotent POST after a transient server failure", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Service unavailable" }), {
      status: 503,
      statusText: "Service Unavailable",
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { ApiHttpError, createCareerProfile } = await import("@/lib/api-client");

    await expect(createCareerProfile({ fullName: "Hadi Alghanim", city: "Riyadh", preferredLanguage: "ar" }))
      .rejects.toBeInstanceOf(ApiHttpError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("maps the user-facing applied stage to the backend submitted enum", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const { mapApplicationStageFromApi, mapApplicationStageToApi } = await import("@/lib/api-client");

    expect(mapApplicationStageFromApi("submitted")).toBe("applied");
    expect(mapApplicationStageToApi("applied")).toBe("submitted");
  });

  it("explains that scanned resumes need OCR instead of showing a generic 422", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const { ApiHttpError, apiErrorMessage } = await import("@/lib/api-client");
    const error = new ApiHttpError(
      422,
      "No readable resume text was found",
      "resume_text_unreadable",
    );

    expect(apiErrorMessage(error, "ar")).toContain("OCR");
    expect(apiErrorMessage(error, "en")).toContain("scanned resumes");
  });

  it("normalizes the real application timestamp before the tracker formats it", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const applicationPayload = [{
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      profile_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      job_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      analysis_id: null,
      cv_document_id: null,
      cover_letter_document_id: null,
      status: "saved",
      submitted_at: null,
      next_action_at: null,
      notes: null,
      outcomes: [],
      created_at: "2026-08-06T18:42:10.151236Z",
      updated_at: "2026-08-06T18:42:10.151236Z",
    }];
    const jobPayload = {
      id: applicationPayload[0].job_id,
      source_url: null,
      intake_method: "manual",
      title: "Data Analyst",
      company: "Example Company",
      description: "User-provided description",
      location: "Riyadh",
      posted_at: null,
      expires_at: null,
      fetched_at: null,
      requirements_reviewed_at: null,
      requirements_reviewed_by_owner_id: null,
      requirements_review_hash: null,
      created_at: "2026-08-06T18:40:00Z",
      source_policy: { display_name: "Manual entry" },
      requirements: [],
    };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(applicationPayload), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(jobPayload), { status: 200, headers: { "Content-Type": "application/json" } })));

    const { getApplications } = await import("@/lib/api-client");
    const { formatDemoDate, normalizeApiDate } = await import("@/lib/utils");
    const applications = await getApplications();

    expect(applications[0].updatedAt).toBe("2026-08-06");
    expect(formatDemoDate(applications[0].updatedAt, "en")).not.toBe("Date unavailable");
    expect(normalizeApiDate("not-a-date")).toBe("");
    expect(formatDemoDate("", "en")).toBe("Date unavailable");
  });
});
