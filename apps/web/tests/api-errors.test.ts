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
    expect(fetchMock).toHaveBeenCalledTimes(3);
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
    const { formatDisplayDate, normalizeApiDate } = await import("@/lib/utils");
    const applications = await getApplications();

    expect(applications[0].updatedAt).toBe("2026-08-06");
    expect(formatDisplayDate(applications[0].updatedAt, "en")).not.toBe("Date unavailable");
    expect(normalizeApiDate("not-a-date")).toBe("");
    expect(formatDisplayDate("", "en")).toBe("Date unavailable");
  });
});

describe("error code coverage", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  // Every error code the backend emits must resolve to a translated message in both
  // languages, never the generic fallback with a raw English server string.
  const backendEmittedCodes = [
    "ai_provider_not_configured", "ai_provider_unavailable",
    "career_path_context_changed", "career_path_rate_limited", "career_path_revision_conflict",
    "career_path_save_conflict", "career_profile_evidence_required",
    "data_sharing_acknowledgement_required", "profile_deletion_in_progress",
    "internal_error", "unsupported_claims",
    "resume_ai_consent_required", "resume_ai_not_configured", "resume_ai_unavailable",
    "resume_content_duplicate", "resume_conversation_language_change_not_allowed",
    "resume_correction_required", "resume_draft_required", "resume_draft_revision_conflict",
    "resume_evidence_revision_conflict", "resume_export_failed", "resume_gap_interview",
    "resume_import_confirmed_evidence_required", "resume_import_draft_exists",
    "resume_import_fact_mismatch", "resume_import_fact_rejected",
    "resume_import_guided_flow_required", "resume_import_phase_conflict",
    "resume_import_questions_incomplete", "resume_import_review_idempotency_conflict",
    "resume_import_review_incomplete", "resume_language_change_requires_new_version",
    "resume_quick_action_invalid", "resume_review_blocked", "resume_review_required",
    "resume_review_stale", "resume_rewrite_not_supported", "resume_suggestion_stale",
    "resume_text_unreadable", "resume_understanding_pending",
    "resume_verified_translation_invalid", "resume_workspace_revision_conflict",
    "resume_writer_consent_required", "resume_writer_evidence_required",
    "resume_writer_not_configured", "resume_writer_unavailable",
  ];

  it("translates every backend error code in both languages", async () => {
    const { ApiHttpError, apiErrorMessage } = await import("@/lib/api-client");
    for (const code of backendEmittedCodes) {
      const error = new ApiHttpError(409, "raw server text", code);
      const arabic = apiErrorMessage(error, "ar");
      const english = apiErrorMessage(error, "en");
      expect(arabic, `missing ar translation for ${code}`).not.toContain("raw server text");
      expect(english, `missing en translation for ${code}`).not.toContain("raw server text");
      expect(arabic.length).toBeGreaterThan(5);
      expect(english.length).toBeGreaterThan(5);
    }
  });

  it("renders FastAPI 422 validation arrays as readable text, not raw JSON", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: [
        { type: "missing", loc: ["body", "full_name"], msg: "Field required" },
        { type: "string_too_short", loc: ["body", "city"], msg: "String should have at least 1 character" },
      ],
    }), { status: 422, statusText: "Unprocessable Entity", headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const { ApiHttpError, getJob } = await import("@/lib/api-client");
    const failure = await getJob("11111111-1111-4111-8111-111111111111").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiHttpError);
    const detail = (failure as InstanceType<typeof ApiHttpError>).detail;
    expect(detail).toBe("full_name: Field required; city: String should have at least 1 character");
    expect(detail).not.toContain("{");
  });
});
