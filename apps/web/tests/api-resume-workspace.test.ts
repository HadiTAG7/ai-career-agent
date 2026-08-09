import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResumeDraftContent, ApiResumeRecord } from "@/lib/api-client";

const draft: ApiResumeDraftContent = {
  headline: "محلل بيانات",
  professional_summary: "محلل بيانات يحول المعلومات إلى تقارير واضحة تدعم القرار.",
  summary_evidence_handles: ["fact:fact-1"],
  sections: [{
    key: "experience",
    title: "الخبرة المهنية",
    items: [{
      id: "experience_1",
      title: "محلل بيانات",
      organization: null,
      date_range: null,
      location: null,
      bullets: ["بنيت لوحة Power BI."],
      evidence_handles: ["fact:fact-1"],
    }],
  }],
};

const educationRecord: ApiResumeRecord = {
  schema_version: "resume_record.v1",
  record_type: "education",
  source_handles: ["fact:education-1"],
  title: "بكالوريوس علوم الحاسب",
  institution: "جامعة الملك سعود",
  gpa_score: "4.75",
  gpa_scale: "5",
  gpa_display_recommended: true,
  responsibilities: [],
  outcomes: [],
  tools: [],
  coursework: [],
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("resume workspace API client", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("uses the durable start and adaptive-message wire contract", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (request: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(request), init });
      return jsonResponse({ id: "workspace-1" });
    }));
    const { resetResumeWorkspace, startResumeWorkspace, sendResumeWorkspaceMessage } = await import("@/lib/api-client");

    await startResumeWorkspace("profile-1", {
      conversationLanguage: "ar",
      language: "en",
      contact: { email: "hadi@example.com" },
      dataSharingAcknowledged: true,
    });
    await sendResumeWorkspaceMessage("profile-1", {
      content: "بنيت لوحة للمبيعات.",
      clientTurnId: "4a74cf68-b085-471c-83f7-6ab6f74f5029",
      expectedRevision: 3,
      quickAction: "improve",
    });
    await sendResumeWorkspaceMessage("profile-1", {
      content: "أعطني مثالًا",
      clientTurnId: "52738cce-439b-403e-9e22-a75935c9fd0b",
      expectedRevision: 4,
      quickAction: "show_example",
    });
    await sendResumeWorkspaceMessage("profile-1", {
      content: "ما عندي رقم دقيق",
      clientTurnId: "e1483d35-d16c-42b4-84fc-28cae17e0200",
      expectedRevision: 5,
      quickAction: "no_exact_metric",
    });
    await resetResumeWorkspace("profile-1", 5);

    expect(calls[0].url).toBe("https://api.test/v1/profiles/profile-1/resume-workspace");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      conversation_language: "ar",
      language: "en",
      contact: { email: "hadi@example.com", phone: null, linkedin: null },
      data_sharing_acknowledged: true,
    });
    expect(calls[1].url.endsWith("/resume-workspace/messages")).toBe(true);
    expect(JSON.parse(String(calls[1].init?.body))).toEqual({
      content: "بنيت لوحة للمبيعات.",
      client_turn_id: "4a74cf68-b085-471c-83f7-6ab6f74f5029",
      expected_revision: 3,
      quick_action: "improve",
    });
    expect(JSON.parse(String(calls[2].init?.body))).toEqual({
      content: "أعطني مثالًا",
      client_turn_id: "52738cce-439b-403e-9e22-a75935c9fd0b",
      expected_revision: 4,
      quick_action: "show_example",
    });
    expect(JSON.parse(String(calls[3].init?.body))).toEqual({
      content: "ما عندي رقم دقيق",
      client_turn_id: "e1483d35-d16c-42b4-84fc-28cae17e0200",
      expected_revision: 5,
      quick_action: "no_exact_metric",
    });
    expect(calls[4].url).toBe("https://api.test/v1/profiles/profile-1/resume-workspace?expected_revision=5");
    expect(calls[4].init?.method).toBe("DELETE");
    expect(calls[4].init?.body).toBeUndefined();
    expect(educationRecord).toMatchObject({
      gpa_score: "4.75",
      gpa_scale: "5",
      gpa_display_recommended: true,
    });
  });

  it("accepts an empty 204 response when permanently clearing a workspace", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const { resetResumeWorkspace } = await import("@/lib/api-client");

    await expect(resetResumeWorkspace("profile-1", 12)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.test/v1/profiles/profile-1/resume-workspace?expected_revision=12",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("forwards the import acknowledgement exactly as supplied", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (request: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(request), init });
      return jsonResponse({ facts: [] });
    }));
    const { importResumeWorkspaceFile } = await import("@/lib/api-client");
    const file = new File(["resume"], "resume.pdf", { type: "application/pdf" });

    await importResumeWorkspaceFile("profile-1", file, { dataSharingAcknowledged: false });

    expect(calls[0].url.endsWith("/resume-workspace/import")).toBe(true);
    const body = calls[0].init?.body as FormData;
    expect(body.get("data_sharing_acknowledged")).toBe("false");
    expect(body.get("file")).toBe(file);
  });

  it("sends strict draft, rewrite, review, and export payloads", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.test");
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (request: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(request), init });
      if (String(request).endsWith(".pdf")) return new Response("%PDF", { status: 200, headers: { "Content-Type": "application/pdf" } });
      if (String(request).endsWith("/review")) return jsonResponse({ export_allowed: true });
      if (String(request).endsWith("/rewrite")) return jsonResponse({ suggestion_id: "suggestion-1" });
      return jsonResponse({ id: "workspace-1" });
    }));
    const {
      exportResumeWorkspacePdf,
      patchResumeWorkspaceDraft,
      reviewResumeWorkspace,
      rewriteResumeDraftSelection,
    } = await import("@/lib/api-client");

    await patchResumeWorkspaceDraft("profile-1", { draft, expectedDraftRevision: 5 });
    await rewriteResumeDraftSelection("profile-1", {
      targetKind: "professional_summary",
      mode: "stronger",
      expectedDraftRevision: 6,
    });
    await reviewResumeWorkspace("profile-1", 6);
    await exportResumeWorkspacePdf("profile-1", 6);

    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ draft, expected_draft_revision: 5 });
    expect(JSON.parse(String(calls[1].init?.body))).toEqual({
      target_kind: "professional_summary",
      section_key: null,
      item_id: null,
      bullet_index: null,
      mode: "stronger",
      instruction: null,
      expected_draft_revision: 6,
    });
    expect(JSON.parse(String(calls[2].init?.body))).toEqual({
      expected_draft_revision: 6,
      review_acknowledged: true,
    });
    expect(JSON.parse(String(calls[3].init?.body))).toEqual({
      expected_draft_revision: 6,
      review_acknowledged: true,
    });
  });
});
