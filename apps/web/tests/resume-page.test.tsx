import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiHttpError } from "@/lib/api-client";
import type {
  ApiCareerFact,
  ApiResumeDraftContent,
  ApiResumeWorkspace,
} from "@/lib/api-client";

const apiMocks = vi.hoisted(() => ({
  getCareerProfile: vi.fn(),
  getCareerFacts: vi.fn(),
  getResumeWorkspace: vi.fn(),
  resetResumeWorkspace: vi.fn(),
  createCareerProfile: vi.fn(),
  startResumeWorkspace: vi.fn(),
  sendResumeWorkspaceMessage: vi.fn(),
  importResumeWorkspaceFile: vi.fn(),
  confirmCareerFact: vi.fn(),
  confirmCareerFactsBatch: vi.fn(),
  prepareResumeImportFlow: vi.fn(),
  confirmResumeUnderstanding: vi.fn(),
  correctResumeUnderstanding: vi.fn(),
  patchResumeWorkspaceDraft: vi.fn(),
  rewriteResumeDraftSelection: vi.fn(),
  decideResumeRewriteSuggestion: vi.fn(),
  getResumeDraftVersions: vi.fn(),
  restoreResumeDraftVersion: vi.fn(),
  reviewResumeWorkspace: vi.fn(),
  previewResumeWorkspacePdf: vi.fn(),
  exportResumeWorkspacePdf: vi.fn(),
}));

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    apiConfiguration: { baseUrl: "https://api.test" },
    ...apiMocks,
  };
});

const profile = {
  id: "profile-1",
  full_name: "هادي الغانم",
  headline: "محلل بيانات",
  preferred_language: "ar" as const,
  city: "الرياض",
  completed_fact_categories: [],
};

const draft: ApiResumeDraftContent = {
  headline: "محلل بيانات",
  professional_summary: "محلل بيانات يحول المعلومات إلى تقارير واضحة تساعد الفرق على اتخاذ قرارات أفضل.",
  summary_evidence_handles: ["fact:fact-1"],
  sections: [
    {
      key: "experience",
      title: "الخبرة المهنية",
      items: [
        {
          id: "experience_1",
          title: "محلل بيانات",
          organization: "شركة التقنية",
          date_range: "2023 - الآن",
          location: "الرياض",
          bullets: ["بنيت لوحات Power BI لمتابعة مؤشرات الأداء."],
          evidence_handles: ["fact:fact-1"],
        },
      ],
    },
  ],
};

const assistantQuestion = {
  id: "message-1",
  sequence: 1,
  role: "assistant" as const,
  kind: "question" as const,
  content: "احكِ لي عن تجربة مهنية تفخر بها.",
  structured_payload: {},
  status: "sent" as const,
  client_turn_id: null,
  created_at: "2026-08-08T10:00:00Z",
};

function makeWorkspace(overrides: Partial<ApiResumeWorkspace> = {}): ApiResumeWorkspace {
  return {
    id: "workspace-1",
    profile_id: profile.id,
    conversation_language: "ar",
    language: "ar",
    stage: "understanding",
    revision: 0,
    evidence_revision: 1,
    readiness_score: 25,
    section_coverage: {
      experience: false,
      education: true,
      project: false,
      skill: true,
      certification: false,
      language: false,
      achievement: false,
    },
    current_draft: null,
    draft_revision: 0,
    contact: {},
    pending_understanding: null,
    pending_suggestion: null,
    provider_ready: true,
    provider: "mistral",
    model: "mistral-small-latest",
    provider_metadata: {},
    consent_required: false,
    consent_version: "2026-08-08-v2:mistral",
    consented_at: "2026-08-08T10:00:00Z",
    messages: [assistantQuestion],
    versions: [],
    created_at: "2026-08-08T10:00:00Z",
    updated_at: "2026-08-08T10:00:00Z",
    ...overrides,
  };
}

const fact: ApiCareerFact = {
  id: "fact-1",
  source_id: "source-1",
  category: "experience",
  label: "محلل بيانات",
  detail: "بنيت لوحات Power BI لمتابعة مؤشرات الأداء.",
  verification_status: "confirmed",
  source_excerpt: "Built Power BI dashboards",
  extraction_confidence: 0.95,
  structured_value: { organization: "شركة التقنية", date_range: "2023 - الآن" },
  created_at: "2026-08-08T10:00:00Z",
};

const extractedFact: ApiCareerFact = {
  ...fact,
  id: "fact-imported-1",
  source_id: "source-imported-1",
  structured_value: {
    organization: "Data Company",
    date_range: "2023 - Present",
    responsibilities: [
      "Reduced monthly reporting time by 35% through SQL automation.",
      "Built Power BI dashboards tracking 12 regional sites.",
    ],
  },
  verification_status: "extracted",
  label: "لوحات Power BI",
  detail: "بنيت لوحات Power BI لمتابعة مؤشرات الأداء.",
};

const previouslyRejectedFact: ApiCareerFact = {
  ...extractedFact,
  id: "fact-rejected-1",
  label: "معلومة مرفوضة سابقًا",
  verification_status: "unconfirmed",
};

const extractedEducationFact: ApiCareerFact = {
  ...extractedFact,
  id: "fact-imported-education-1",
  category: "education",
  label: "Bachelor of Finance",
  detail: "King Fahd University of Petroleum and Minerals",
  structured_value: {
    degree: "Bachelor of Finance",
    institution: "King Fahd University of Petroleum and Minerals",
    date_range: "2019 - 2023",
  },
};

const confirmedImportedFact: ApiCareerFact = {
  ...extractedFact,
  verification_status: "confirmed",
};

async function renderResumePage() {
  const [{ default: ResumePage }, { LocaleProvider }] = await Promise.all([
    import("@/app/resume/page"),
    import("@/lib/i18n"),
  ]);
  await act(async () => {
    render(<LocaleProvider><ResumePage /></LocaleProvider>);
  });
}

describe("resume workspace v2", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getCareerProfile.mockResolvedValue(profile);
    apiMocks.getCareerFacts.mockResolvedValue([]);
    apiMocks.getResumeWorkspace.mockResolvedValue(null);
    apiMocks.createCareerProfile.mockResolvedValue(profile);
    apiMocks.startResumeWorkspace.mockResolvedValue(makeWorkspace({ language: "en" }));
    apiMocks.resetResumeWorkspace.mockResolvedValue(undefined);
    apiMocks.sendResumeWorkspaceMessage.mockResolvedValue(makeWorkspace());
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: { id: "source-1", kind: "cv_upload", label: "resume.pdf", original_filename: "resume.pdf" },
      facts: [extractedFact],
      requires_user_review: true,
      analysis_status: "created",
    });
    apiMocks.confirmCareerFact.mockResolvedValue({ ...extractedFact, verification_status: "confirmed" });
    apiMocks.confirmCareerFactsBatch.mockResolvedValue({
      facts: [{ ...extractedFact, verification_status: "confirmed" }],
      evidence_revision: 2,
    });
    apiMocks.prepareResumeImportFlow.mockResolvedValue(makeWorkspace({
      revision: 1,
      evidence_revision: 2,
      provider_metadata: {
        conversation_language: "ar",
        import_flow: {
          phase: "additions_choice",
          can_generate: false,
          source_id: extractedFact.source_id,
          file_name: "resume.pdf",
          assessment: {
            verdict: "needs_information",
            found_sections: ["experience"],
            section_counts: { experience: 1 },
            missing_sections: ["education", "skill", "language"],
            gaps: [
              { key: "education_details", category: "education", requested_fields: ["degree"], priority: "high", reason: "Education details are incomplete.", evidence_handles: [] },
            ],
            ats_checks: [],
            page_target: 1,
            disclaimer: "Structure only",
          },
          gap_queue: [],
          page_target: 1,
        },
      },
    }));
    apiMocks.confirmResumeUnderstanding.mockResolvedValue(makeWorkspace({ revision: 2 }));
    apiMocks.getResumeDraftVersions.mockResolvedValue([]);
    apiMocks.reviewResumeWorkspace.mockResolvedValue({
      workspace_id: "workspace-1",
      draft_version_id: "version-1",
      draft_revision: 1,
      status: "export_ready",
      reviewed_at: "2026-08-08T10:10:00Z",
      review_hash: "review-hash",
      evidence_revision: 1,
      export_allowed: true,
    });
    apiMocks.previewResumeWorkspacePdf.mockResolvedValue(new Blob(["%PDF"], { type: "application/pdf" }));
    apiMocks.exportResumeWorkspacePdf.mockResolvedValue(new Blob(["%PDF"], { type: "application/pdf" }));
  });

  it("explains a slow staging wake-up instead of looking stuck", async () => {
    vi.useFakeTimers();
    apiMocks.getCareerProfile.mockImplementation(() => new Promise(() => undefined));
    try {
      await renderResumePage();
      expect(screen.getByRole("heading", { name: "نجهّز مساحة سيرتك" })).toBeVisible();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });

      expect(screen.getByRole("heading", { name: "نشغّل الخادم ونستعيد سيرتك" })).toBeVisible();
      expect(screen.getByText(/سنعيد محاولة التحميل تلقائيًا/)).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });

  it("starts one chat-first workspace after choosing language and acknowledging AI use", async () => {
    const user = userEvent.setup();
    await renderResumePage();

    expect(await screen.findByRole("heading", { name: "خلّنا نبني قصتك المهنية" })).toBeVisible();
    expect(screen.getByRole("button", { name: "لغة الحوار: العربية" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "لغة السيرة: الإنجليزية" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "خلّنا نبني قصتك المهنية" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "لغة السيرة: العربية" }));
    expect(screen.getByRole("heading", { name: "خلّنا نبني قصتك المهنية" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "لغة السيرة: الإنجليزية" }));
    const start = screen.getByRole("button", { name: "ابدأ المحادثة" });
    expect(start).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /موافقة استخدام الذكاء الاصطناعي/ }));
    await user.click(start);

    await waitFor(() => expect(apiMocks.startResumeWorkspace).toHaveBeenCalledWith(profile.id, {
      conversationLanguage: "ar",
      language: "en",
      dataSharingAcknowledged: true,
    }));
    expect(await screen.findByText("احكِ لي عن تجربة مهنية تفخر بها.")).toBeVisible();
    expect(screen.getByRole("button", { name: "إرفاق سيرة موجودة" })).toBeVisible();
    expect(screen.getByLabelText("معاينة السيرة الحية")).toBeVisible();
  });

  it("sends independently changed conversation and resume languages without changing the UI locale", async () => {
    const user = userEvent.setup();
    apiMocks.startResumeWorkspace.mockResolvedValue(makeWorkspace({
      conversation_language: "en",
      language: "ar",
    }));
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "لغة الحوار: الإنجليزية" }));
    await user.click(screen.getByRole("button", { name: "لغة السيرة: العربية" }));
    expect(screen.getByRole("heading", { name: "خلّنا نبني قصتك المهنية" })).toBeVisible();
    await user.click(screen.getByRole("checkbox", { name: /موافقة استخدام الذكاء الاصطناعي/ }));
    await user.click(screen.getByRole("button", { name: "ابدأ المحادثة" }));

    await waitFor(() => expect(apiMocks.startResumeWorkspace).toHaveBeenCalledWith(profile.id, {
      conversationLanguage: "en",
      language: "ar",
      dataSharingAcknowledged: true,
    }));
    expect(screen.getByRole("heading", { name: "خلّنا نبني قصتك المهنية" })).toBeVisible();
  });

  it("blocks AI actions until an expired consent is explicitly renewed", async () => {
    const user = userEvent.setup();
    const expiredWorkspace = makeWorkspace({
      consent_required: true,
      consented_at: null,
      consent_version: "2026-08-08-v1:mistral",
      contact: { email: "hadi@example.com" },
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(expiredWorkspace);
    apiMocks.startResumeWorkspace.mockResolvedValue(makeWorkspace({ contact: expiredWorkspace.contact }));
    await renderResumePage();

    expect(await screen.findByRole("heading", { name: "جدّد موافقتك للمتابعة" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "إرفاق سيرة موجودة" })).not.toBeInTheDocument();
    const renew = screen.getByRole("button", { name: "جدّد الموافقة وتابع" });
    expect(renew).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /أوافق على النسخة الحالية/ }));
    await user.click(renew);

    await waitFor(() => expect(apiMocks.startResumeWorkspace).toHaveBeenCalledWith(profile.id, {
      conversationLanguage: "ar",
      language: "ar",
      contact: { email: "hadi@example.com", phone: undefined, linkedin: undefined },
      dataSharingAcknowledged: true,
    }));
    expect(await screen.findByRole("button", { name: "إرفاق سيرة موجودة" })).toBeVisible();
  });

  it("keeps an Arabic conversation while rendering an English resume left-to-right", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      conversation_language: "ar",
      language: "en",
      stage: "writing",
      current_draft: {
        ...draft,
        headline: "Data Analyst",
        professional_summary: "Data analyst who turns evidence into clear decisions.",
      },
      draft_revision: 1,
    }));
    await renderResumePage();

    expect(await screen.findByText("احكِ لي عن تجربة مهنية تفخر بها.")).toBeVisible();
    expect(screen.getByText("الحوار AR · السيرة EN")).toBeVisible();
    const preview = screen.getByLabelText("معاينة السيرة الحية");
    expect(preview.querySelector("article")).toHaveAttribute("dir", "ltr");
    expect(preview.querySelector("article")).toHaveAttribute("lang", "en");
    expect(within(preview).getByRole("heading", { name: "Professional summary" })).toBeVisible();
    expect(within(preview).queryByRole("heading", { name: "نبذة مهنية" })).not.toBeInTheDocument();
  });

  it("never renders rejected import facts in the live resume or evidence rail", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({ language: "en" }));
    apiMocks.getCareerFacts.mockResolvedValue([fact, previouslyRejectedFact]);
    await renderResumePage();

    const preview = await screen.findByLabelText("معاينة السيرة الحية");
    expect(within(preview).getAllByText(fact.label).length).toBeGreaterThan(0);
    expect(within(preview).queryByText(previouslyRejectedFact.label)).not.toBeInTheDocument();
    expect(screen.queryByText(previouslyRejectedFact.label)).not.toBeInTheDocument();
  });

  it.each([
    [
      "ai_unavailable_existing_draft_preserved",
      "تعذر الوصول إلى كاتب الذكاء الاصطناعي مؤقتًا؛ مسودتك الحالية محفوظة دون تغيير.",
    ],
    [
      "ai_unavailable_evidence_fallback_created",
      "هذه مسودة موثقة من معلوماتك المؤكدة لأن كاتب الذكاء الاصطناعي غير متاح مؤقتًا.",
    ],
  ])("shows the generation fallback warning banner for %s", async (warning, message) => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "writing",
      current_draft: draft,
      draft_revision: 1,
      provider_metadata: { generation_warning: warning },
    }));

    await renderResumePage();

    expect(await screen.findByText(message)).toHaveAttribute("role", "status");
  });

  it("does not mislabel an unknown generation warning as an evidence-only fallback", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "writing",
      current_draft: draft,
      draft_revision: 1,
      provider_metadata: { generation_warning: "draft_patch_language_mismatch" },
    }));

    await renderResumePage();

    expect(await screen.findByDisplayValue(draft.professional_summary)).toBeVisible();
    expect(screen.queryByText(
      "هذه مسودة موثقة من معلوماتك المؤكدة لأن كاتب الذكاء الاصطناعي غير متاح مؤقتًا.",
    )).not.toBeInTheDocument();
  });

  it("falls back to the resume language for legacy workspaces without a conversation language", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      conversation_language: undefined,
      language: "en",
    }));
    await renderResumePage();

    expect(await screen.findByText("الحوار EN · السيرة EN")).toBeVisible();
  });

  it("requires confirmation before permanently clearing the resume workspace", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      conversation_language: "en",
      language: "ar",
      stage: "writing",
      revision: 7,
      current_draft: draft,
      draft_revision: 2,
    }));
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    await renderResumePage();

    const resetTrigger = await screen.findByRole("button", { name: "مسح والبدء من جديد" });
    await user.click(resetTrigger);
    const dialog = screen.getByRole("alertdialog", { name: "مسح مساحة السيرة والبدء من جديد؟" });
    expect(within(dialog).getByText(/ستبقى الحقائق المهنية المؤكدة/)).toBeVisible();
    expect(apiMocks.resetResumeWorkspace).not.toHaveBeenCalled();
    const cancel = within(dialog).getByRole("button", { name: "إلغاء" });
    const confirm = within(dialog).getByRole("button", { name: "امسح وابدأ من جديد" });
    expect(cancel).toHaveFocus();
    expect(document.body).toHaveStyle({ overflow: "hidden" });
    await user.tab();
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();

    await user.click(cancel);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(resetTrigger).toHaveFocus();
    expect(document.body).not.toHaveStyle({ overflow: "hidden" });
    expect(screen.getByDisplayValue(draft.professional_summary)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "مسح والبدء من جديد" }));
    await user.click(screen.getByRole("button", { name: "امسح وابدأ من جديد" }));

    await waitFor(() => expect(apiMocks.resetResumeWorkspace).toHaveBeenCalledWith(profile.id, 7));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "لغة الحوار: الإنجليزية" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "لغة السيرة: العربية" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "ابدأ المحادثة" })).toBeDisabled();
  });

  it("keeps the current draft when permanent clearing fails", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "writing",
      revision: 4,
      current_draft: draft,
      draft_revision: 1,
    }));
    apiMocks.resetResumeWorkspace.mockRejectedValue(new Error("تعذر مسح مساحة السيرة"));
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "مسح والبدء من جديد" }));
    await user.click(screen.getByRole("button", { name: "امسح وابدأ من جديد" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("حدث خطأ غير متوقع");
    expect(screen.getByDisplayValue(draft.professional_summary)).toBeVisible();
    expect(screen.getByRole("alertdialog")).toBeVisible();
  });

  it("refreshes a conflicting workspace revision and retries clearing with the latest revision", async () => {
    const user = userEvent.setup();
    const original = makeWorkspace({ revision: 7, stage: "writing", current_draft: draft, draft_revision: 1 });
    const refreshed = makeWorkspace({ revision: 8, stage: "writing", current_draft: draft, draft_revision: 1 });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(original)
      .mockResolvedValueOnce(refreshed);
    apiMocks.resetResumeWorkspace
      .mockRejectedValueOnce(new ApiHttpError(409, "Workspace revision changed", "resume_workspace_revision_conflict"))
      .mockResolvedValueOnce(undefined);
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "مسح والبدء من جديد" }));
    await user.click(screen.getByRole("button", { name: "امسح وابدأ من جديد" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("حدّثنا أحدث نسخة");
    expect(apiMocks.resetResumeWorkspace).toHaveBeenNthCalledWith(1, profile.id, 7);
    await user.click(screen.getByRole("button", { name: "امسح وابدأ من جديد" }));

    await waitFor(() => expect(apiMocks.resetResumeWorkspace).toHaveBeenNthCalledWith(2, profile.id, 8));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ابدأ المحادثة" })).toBeDisabled();
  });

  it("treats an already-missing workspace as a successful local reset", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({ revision: 3, stage: "writing", current_draft: draft }));
    apiMocks.resetResumeWorkspace.mockRejectedValue(new ApiHttpError(404, "Workspace not found"));
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "مسح والبدء من جديد" }));
    await user.click(screen.getByRole("button", { name: "امسح وابدأ من جديد" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "ابدأ المحادثة" })).toBeDisabled();
  });

  it("allows clearing after an autosave error once no persistence request remains", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      revision: 5,
      stage: "writing",
      current_draft: draft,
      draft_revision: 1,
    }));
    apiMocks.patchResumeWorkspaceDraft.mockRejectedValue(new Error("save failed"));
    await renderResumePage();

    await user.click(await screen.findByRole("tab", { name: "السيرة" }));
    const summary = screen.getByRole("textbox", { name: "الملخص المهني" });
    await user.type(summary, " تعديل");
    expect(await screen.findByText("تعذر الحفظ", {}, { timeout: 2_000 })).toBeVisible();
    const reset = screen.getByRole("button", { name: "مسح والبدء من جديد" });
    expect(reset).toBeEnabled();

    await user.click(reset);
    await user.click(screen.getByRole("button", { name: "امسح وابدأ من جديد" }));
    await waitFor(() => expect(apiMocks.resetResumeWorkspace).toHaveBeenCalledWith(profile.id, 5));
    expect(screen.getByRole("button", { name: "ابدأ المحادثة" })).toBeDisabled();
  });

  it("ignores a renewal response that arrives after a same-tick successful reset", async () => {
    const expired = makeWorkspace({
      revision: 9,
      consent_required: true,
      consented_at: null,
    });
    let resolveRenew!: (workspace: ApiResumeWorkspace) => void;
    const renewRequest = new Promise<ApiResumeWorkspace>((resolve) => {
      resolveRenew = resolve;
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(expired);
    apiMocks.startResumeWorkspace.mockReturnValue(renewRequest);
    await renderResumePage();

    const renew = await screen.findByRole("button", { name: "جدّد الموافقة وتابع" });
    fireEvent.click(screen.getByRole("checkbox", { name: /أوافق على النسخة الحالية/ }));
    const reset = screen.getByRole("button", { name: "مسح والبدء من جديد" });
    fireEvent.click(reset);
    const confirm = screen.getByRole("button", { name: "امسح وابدأ من جديد" });
    act(() => {
      renew.click();
      confirm.click();
    });

    await waitFor(() => expect(apiMocks.resetResumeWorkspace).toHaveBeenCalledWith(profile.id, 9));
    expect(await screen.findByRole("button", { name: "ابدأ المحادثة" })).toBeDisabled();
    await act(async () => {
      resolveRenew(makeWorkspace({ revision: 10 }));
      await renewRequest;
    });
    expect(screen.getByRole("button", { name: "ابدأ المحادثة" })).toBeDisabled();
    expect(screen.queryByText("احكِ لي عن تجربة مهنية تفخر بها.")).not.toBeInTheDocument();
  });

  it("sends only one DELETE while the reset request is in flight", async () => {
    const user = userEvent.setup();
    let resolveReset!: () => void;
    const resetRequest = new Promise<void>((resolve) => {
      resolveReset = resolve;
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({ revision: 6, stage: "writing", current_draft: draft }));
    apiMocks.resetResumeWorkspace.mockReturnValue(resetRequest);
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "مسح والبدء من جديد" }));
    const confirm = screen.getByRole("button", { name: "امسح وابدأ من جديد" });
    act(() => {
      confirm.click();
      confirm.click();
    });
    expect(apiMocks.resetResumeWorkspace).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveReset();
      await resetRequest;
    });
    expect(await screen.findByRole("button", { name: "ابدأ المحادثة" })).toBeDisabled();
  });

  it("autosaves contact details without manufacturing a new AI acknowledgement", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace());
    apiMocks.startResumeWorkspace.mockResolvedValue(makeWorkspace({ contact: { email: "hadi@example.com" } }));
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "التواصل" }));
    await user.type(screen.getByRole("textbox", { name: "البريد الإلكتروني" }), "hadi@example.com");

    await waitFor(() => expect(apiMocks.startResumeWorkspace).toHaveBeenCalledWith(profile.id, {
      conversationLanguage: "ar",
      language: "ar",
      contact: { email: "hadi@example.com", phone: undefined, linkedin: undefined },
      dataSharingAcknowledged: false,
    }), { timeout: 2_000 });
  });

  it("sends an adaptive answer and requires confirming what the assistant understood", async () => {
    const user = userEvent.setup();
    const withUnderstanding = makeWorkspace({
      revision: 1,
      pending_understanding: {
        id: "understanding-1",
        understanding: "استخدمت Power BI لبناء لوحة ساعدت المدير على متابعة المبيعات.",
        understanding_detail: { confidence: "high" },
        proposed_records: [],
        next_question: null,
        draft_patch: null,
      },
      messages: [
        assistantQuestion,
        {
          id: "message-2",
          sequence: 2,
          role: "user",
          kind: "text",
          content: "بنيت لوحة للمبيعات في Power BI.",
          structured_payload: {},
          status: "sent",
          client_turn_id: "turn-1",
          created_at: "2026-08-08T10:01:00Z",
        },
      ],
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace());
    apiMocks.sendResumeWorkspaceMessage.mockResolvedValue(withUnderstanding);
    apiMocks.confirmResumeUnderstanding.mockResolvedValue(makeWorkspace({ revision: 2 }));
    await renderResumePage();

    await user.type(await screen.findByLabelText("اكتب رسالتك"), "بنيت لوحة للمبيعات في Power BI.");
    await user.click(screen.getByRole("button", { name: "إرسال الرسالة" }));

    await waitFor(() => expect(apiMocks.sendResumeWorkspaceMessage).toHaveBeenCalledWith(profile.id, expect.objectContaining({
      content: "بنيت لوحة للمبيعات في Power BI.",
      expectedRevision: 0,
      clientTurnId: expect.any(String),
    })));
    expect(await screen.findByText("استخدمت Power BI لبناء لوحة ساعدت المدير على متابعة المبيعات.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "صحيح" }));
    await waitFor(() => expect(apiMocks.confirmResumeUnderstanding).toHaveBeenCalledWith(profile.id, "understanding-1", 1));
  });

  it("locks helper actions, skip, and resume attachment while an understanding is pending", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      pending_understanding: {
        id: "understanding-awaiting-review",
        understanding: "استخدمت Power BI لبناء لوحة مبيعات.",
        understanding_detail: { confidence: "high" },
        proposed_records: [],
        next_question: null,
        draft_patch: null,
      },
    }));
    await renderResumePage();

    expect(await screen.findByRole("button", { name: "أعطني مثالًا" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "ما عندي رقم دقيق" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "تخطَّ هذا السؤال" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "إرفاق سيرة موجودة" })).toBeDisabled();
    expect(document.querySelector<HTMLInputElement>("#resume-workspace-file")).toBeDisabled();
  });

  it("reconciles a committed understanding after a lost response and refreshes the new evidence", async () => {
    const user = userEvent.setup();
    const pending = makeWorkspace({
      revision: 1,
      pending_understanding: {
        id: "understanding-lost-1",
        understanding: "استخدمت Power BI لإعداد تقرير شهري.",
        understanding_detail: { confidence: "high" },
        proposed_records: [],
        next_question: null,
        draft_patch: null,
      },
    });
    const completed = makeWorkspace({ revision: 2, pending_understanding: null });
    const addedFact: ApiCareerFact = {
      ...fact,
      id: "fact-from-confirmed-answer",
      label: "Power BI reporting",
    };
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(pending)
      .mockResolvedValue(completed);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([addedFact]);
    apiMocks.confirmResumeUnderstanding.mockRejectedValue(new TypeError("response lost"));
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "صحيح" }));

    await waitFor(() => expect(apiMocks.getCareerFacts).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("استخدمت Power BI لإعداد تقرير شهري.")).not.toBeInTheDocument();
  });

  it("shows a sent answer immediately while the AI request is still running", async () => {
    const user = userEvent.setup();
    const answer = "حللت المبيعات الأسبوعية باستخدام Power BI.";
    let resolveMessage!: (workspace: ApiResumeWorkspace) => void;
    const request = new Promise<ApiResumeWorkspace>((resolve) => {
      resolveMessage = resolve;
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace());
    apiMocks.sendResumeWorkspaceMessage.mockReturnValue(request);
    await renderResumePage();

    const input = await screen.findByLabelText("اكتب رسالتك");
    await user.type(input, answer);
    await user.click(screen.getByRole("button", { name: "إرسال الرسالة" }));

    expect(input).toHaveValue("");
    expect(screen.getByText(answer)).toBeVisible();
    expect(screen.getByText(/تم إرسال إجابتك/)).toBeVisible();

    await act(async () => {
      resolveMessage(makeWorkspace({
        revision: 1,
        messages: [
          assistantQuestion,
          {
            id: "message-optimistic-confirmed",
            sequence: 2,
            role: "user",
            kind: "text",
            content: answer,
            structured_payload: {},
            status: "sent",
            client_turn_id: "confirmed-turn",
            created_at: "2026-08-08T10:01:00Z",
          },
        ],
      }));
      await request;
    });

    await waitFor(() => expect(screen.queryByText(/تم إرسال إجابتك/)).not.toBeInTheDocument());
    expect(screen.getAllByText(answer)).toHaveLength(1);
  });

  it("restores a typed answer when the AI request fails", async () => {
    const user = userEvent.setup();
    const answer = "أنشأت تقريرًا ماليًا أسبوعيًا.";
    let rejectMessage!: (error: Error) => void;
    const request = new Promise<ApiResumeWorkspace>((_resolve, reject) => {
      rejectMessage = reject;
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace());
    apiMocks.sendResumeWorkspaceMessage.mockReturnValue(request);
    await renderResumePage();

    const input = await screen.findByLabelText("اكتب رسالتك");
    await user.type(input, answer);
    await user.click(screen.getByRole("button", { name: "إرسال الرسالة" }));
    expect(input).toHaveValue("");

    await act(async () => {
      rejectMessage(new Error("provider unavailable"));
      await request.catch(() => undefined);
    });

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(input).toHaveValue(answer);
    expect(screen.getAllByText(answer)).toHaveLength(1);
  });

  it("reconciles a sent message after the response is lost without restoring the input", async () => {
    const user = userEvent.setup();
    const answer = "حللت الانحرافات الشهرية باستخدام Excel.";
    let committedWorkspace = makeWorkspace();
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(makeWorkspace())
      .mockImplementation(() => Promise.resolve(committedWorkspace));
    apiMocks.sendResumeWorkspaceMessage.mockImplementation((
      _profileId: string,
      input: { clientTurnId: string },
    ) => {
      committedWorkspace = makeWorkspace({
        revision: 1,
        messages: [
          assistantQuestion,
          {
            id: "message-committed-after-timeout",
            sequence: 2,
            role: "user",
            kind: "text",
            content: answer,
            structured_payload: {},
            status: "sent",
            client_turn_id: input.clientTurnId,
            created_at: "2026-08-08T10:01:00Z",
          },
        ],
      });
      return Promise.reject(new TypeError("response lost"));
    });
    await renderResumePage();

    const input = await screen.findByLabelText("اكتب رسالتك");
    await user.type(input, answer);
    await user.click(screen.getByRole("button", { name: "إرسال الرسالة" }));

    await waitFor(() => expect(apiMocks.getResumeWorkspace).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getAllByText(answer)).toHaveLength(1));
    expect(input).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not mistake a persisted failed turn for a committed message", async () => {
    const user = userEvent.setup();
    const answer = "أنشأت تقرير المصروفات الأسبوعي.";
    let failedWorkspace = makeWorkspace();
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(makeWorkspace())
      .mockImplementation(() => Promise.resolve(failedWorkspace));
    apiMocks.sendResumeWorkspaceMessage.mockImplementation((
      _profileId: string,
      input: { clientTurnId: string },
    ) => {
      failedWorkspace = makeWorkspace({
        messages: [
          assistantQuestion,
          {
            id: "message-failed-after-provider-error",
            sequence: 2,
            role: "user",
            kind: "text",
            content: answer,
            structured_payload: {},
            status: "failed",
            client_turn_id: input.clientTurnId,
            created_at: "2026-08-08T10:01:00Z",
          },
        ],
      });
      return Promise.reject(new ApiHttpError(503, "provider unavailable", "resume_writer_unavailable"));
    });
    await renderResumePage();

    const input = await screen.findByLabelText("اكتب رسالتك");
    await user.type(input, answer);
    await user.click(screen.getByRole("button", { name: "إرسال الرسالة" }));

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(input).toHaveValue(answer);
    expect(screen.getAllByText(answer)).toHaveLength(1);
  });

  it("returns to a clean setup state when another tab permanently resets the workspace", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(makeWorkspace())
      .mockResolvedValueOnce(null);
    apiMocks.getCareerFacts.mockResolvedValue([]);
    apiMocks.sendResumeWorkspaceMessage.mockRejectedValue(
      new ApiHttpError(409, "Workspace was reset", "resume_workspace_revision_conflict"),
    );
    await renderResumePage();

    const input = await screen.findByLabelText("اكتب رسالتك");
    await user.type(input, "إجابة من تبويب قديم");
    await user.click(screen.getByRole("button", { name: "إرسال الرسالة" }));

    const start = await screen.findByRole("button", { name: "ابدأ المحادثة" });
    expect(start).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /موافقة استخدام الذكاء الاصطناعي/ })).not.toBeChecked();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("hydrates a pending import discovered while reconciling another-tab changes", async () => {
    const user = userEvent.setup();
    const pendingWorkspace = makeWorkspace({
      revision: 2,
      evidence_revision: 3,
      provider_metadata: {
        pending_import_source_id: extractedFact.source_id,
        pending_import_filename: "resume.pdf",
        pending_import_analysis_status: "created",
      },
    });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(makeWorkspace())
      .mockResolvedValueOnce(pendingWorkspace);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([extractedFact]);
    apiMocks.sendResumeWorkspaceMessage.mockRejectedValue(
      new ApiHttpError(409, "Workspace changed", "resume_workspace_revision_conflict"),
    );
    await renderResumePage();

    const input = await screen.findByLabelText("اكتب رسالتك");
    await user.type(input, "هذه الرسالة أصبحت قديمة");
    await user.click(screen.getByRole("button", { name: "إرسال الرسالة" }));

    expect(await screen.findByRole("heading", { name: "تقييم مبدئي لجاهزية ATS" })).toBeVisible();
    expect(screen.getByRole("checkbox", { name: new RegExp(extractedFact.label) })).toBeChecked();
  });

  it("offers full AI generation without exposing provider internals or failed turns", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      messages: [
        assistantQuestion,
        {
          id: "failed-message",
          sequence: 2,
          role: "user",
          kind: "text",
          content: "رسالة فشلت ويجب ألا تتكرر",
          structured_payload: {},
          status: "failed",
          client_turn_id: "failed-turn",
          created_at: "2026-08-08T10:01:00Z",
        },
      ],
    }));
    await renderResumePage();

    expect(await screen.findByText("الذكاء الاصطناعي جاهز")).toBeVisible();
    expect(screen.queryByText(/mistral-small-latest/)).not.toBeInTheDocument();
    expect(screen.queryByText("رسالة فشلت ويجب ألا تتكرر")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "اكتب السيرة الآن" }));
    await waitFor(() => expect(apiMocks.sendResumeWorkspaceMessage).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({
        quickAction: "generate",
        expectedRevision: 0,
        clientTurnId: expect.any(String),
      }),
    ));
  });

  it("locks resume editing while a generate quick action is busy", async () => {
    const user = userEvent.setup();
    const writingWorkspace = makeWorkspace({
      stage: "writing",
      current_draft: draft,
      draft_revision: 1,
    });
    let resolveGeneration!: (workspace: ApiResumeWorkspace) => void;
    const generationRequest = new Promise<ApiResumeWorkspace>((resolve) => {
      resolveGeneration = resolve;
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(writingWorkspace);
    apiMocks.sendResumeWorkspaceMessage.mockReturnValue(generationRequest);
    await renderResumePage();

    const summary = await screen.findByRole("textbox", { name: "الملخص المهني" });
    const bullet = screen.getByRole("textbox", { name: /نقطة 1/ });
    expect(summary).toBeEnabled();
    expect(bullet).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "اكتب السيرة الآن" }));
    await waitFor(() => expect(apiMocks.sendResumeWorkspaceMessage).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({ quickAction: "generate" }),
    ));
    const editingWasLocked = (
      (summary as HTMLTextAreaElement).disabled
      && (bullet as HTMLTextAreaElement).disabled
    );

    await act(async () => {
      resolveGeneration({ ...writingWorkspace, revision: 1 });
      await generationRequest;
    });

    expect(editingWasLocked).toBe(true);
  });

  it("sends helper choices and skip as commands rather than ordinary answers", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({ conversation_language: "ar", language: "en" }));
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "أعطني مثالًا" }));
    await waitFor(() => expect(apiMocks.sendResumeWorkspaceMessage).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({ content: "أعطني مثالًا", quickAction: "show_example" }),
    ));

    await user.click(screen.getByRole("button", { name: "ما عندي رقم دقيق" }));
    await waitFor(() => expect(apiMocks.sendResumeWorkspaceMessage).toHaveBeenLastCalledWith(
      profile.id,
      expect.objectContaining({ content: "ما عندي رقم دقيق", quickAction: "no_exact_metric" }),
    ));

    await user.click(screen.getByRole("button", { name: "تخطَّ هذا السؤال" }));
    await waitFor(() => expect(apiMocks.sendResumeWorkspaceMessage).toHaveBeenLastCalledWith(
      profile.id,
      expect.objectContaining({ content: "تخطَّ هذا السؤال", quickAction: "skip" }),
    ));
  });

  it.each([
    ["gap_interview", false],
    ["ready_to_generate", true],
  ])("keeps resume attachment disabled during the %s import phase", async (phase, canGenerate) => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      provider_metadata: {
        import_flow: {
          phase,
          can_generate: canGenerate,
          source_id: "source-imported-1",
          file_name: "resume.pdf",
          assessment: { gaps: [], page_target: 1 },
          gap_queue: [],
          page_target: 1,
        },
      },
    }));
    await renderResumePage();

    expect(await screen.findByRole("button", { name: "إرفاق سيرة موجودة" })).toBeDisabled();
    expect(document.querySelector<HTMLInputElement>("#resume-workspace-file")).toBeDisabled();
    expect(screen.getByRole("button", { name: "التواصل" })).toBeDisabled();
  });

  it("shows only the ATS generation action after all import gaps are complete", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      provider_metadata: {
        import_flow: {
          phase: "ready_to_generate",
          can_generate: true,
          source_id: "source-imported-1",
          file_name: "resume.pdf",
          assessment: { gaps: [], page_target: 1 },
          gap_queue: [],
          completed_gap_keys: ["experience_context"],
          skipped_gap_keys: ["certification_issuer"],
          page_target: 1,
        },
      },
    }));
    await renderResumePage();

    expect(await screen.findByRole("button", { name: "أنشئ مسودة ATS" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "أعطني مثالًا" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ما عندي رقم دقيق" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "تخطَّ هذا السؤال" })).not.toBeInTheDocument();
  });

  it("keeps resolved and skipped gaps in the interview progress total", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      provider_metadata: {
        import_flow: {
          phase: "gap_interview",
          can_generate: false,
          source_id: "source-imported-1",
          file_name: "resume.pdf",
          assessment: {
            gaps: [
              { key: "erp", category: "experience" },
              { key: "cme1", category: "certification" },
              { key: "excel", category: "certification" },
              { key: "cme4", category: "certification" },
              { key: "market", category: "skill" },
            ],
            page_target: 1,
          },
          active_gap_key: "erp",
          completed_gap_keys: ["trading_context"],
          skipped_gap_keys: [],
          gap_queue: [
            { key: "cme1", category: "certification" },
            { key: "excel", category: "certification" },
            { key: "cme4", category: "certification" },
            { key: "market", category: "skill" },
          ],
          page_target: 1,
        },
      },
    }));
    await renderResumePage();

    expect(await screen.findByText("سؤال النقص 2 من 6")).toBeVisible();
  });

  it("hides messages before the import marker while keeping the current gap question", async () => {
    const oldQuestion = {
      ...assistantQuestion,
      id: "message-before-import",
      content: "هذه رسالة قديمة قبل رفع السيرة.",
    };
    const importMarker = {
      ...assistantQuestion,
      id: "message-import-marker",
      sequence: 2,
      content: "سنبدأ الآن مراجعة الملف المرفوع.",
      structured_payload: { import_flow_phase: "additions_choice" },
    };
    const currentGap = {
      ...assistantQuestion,
      id: "message-current-gap",
      sequence: 3,
      content: "ما الأدوات التي استخدمتها في أحدث تجربة؟",
      structured_payload: {
        question: {
          id: "gap-tools",
          category: "skill",
          question: "ما الأدوات التي استخدمتها في أحدث تجربة؟",
        },
      },
    };
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      messages: [oldQuestion, importMarker, currentGap],
      provider_metadata: {
        import_flow: {
          phase: "gap_interview",
          can_generate: false,
          source_id: "source-imported-1",
          file_name: "resume.pdf",
          assessment: {
            gaps: [
              { key: "skills", category: "skill", priority: "high" },
            ],
            page_target: 1,
          },
          gap_queue: [
            { key: "skills", category: "skill", priority: "high" },
          ],
          page_target: 1,
        },
      },
    }));
    await renderResumePage();

    expect(await screen.findByText("ما الأدوات التي استخدمتها في أحدث تجربة؟")).toBeVisible();
    expect(screen.queryByText("هذه رسالة قديمة قبل رفع السيرة.")).not.toBeInTheDocument();
  });

  it("shows an ATS readiness assessment before asking about additions or building a draft", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace();
    const refreshed = makeWorkspace({
      evidence_revision: 2,
      readiness_score: 55,
      section_coverage: {
        experience: true,
        education: true,
        project: false,
        skill: false,
        certification: false,
        language: false,
        achievement: false,
      },
    });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(refreshed);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([extractedFact, extractedEducationFact]);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: extractedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: [extractedFact, extractedEducationFact],
      requires_user_review: true,
      analysis_status: "created",
    });
    apiMocks.confirmCareerFactsBatch.mockResolvedValue({
      facts: [
        { ...extractedFact, verification_status: "confirmed" },
        { ...extractedEducationFact, verification_status: "confirmed" },
      ],
      evidence_revision: 3,
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));

    const assessmentHeading = await screen.findByRole("heading", { name: "تقييم مبدئي لجاهزية ATS" });
    const assessment = assessmentHeading.closest("section");
    expect(assessment).not.toBeNull();
    expect(within(assessment!).getByText(/هذا تقييم لاكتمال بنية السيرة، وليس احتمال قبول وظيفي/)).toBeVisible();
    expect(within(assessment!).getByText(/التعليم/)).toBeVisible();
    expect(within(assessment!).getByText(/المهارات/)).toBeVisible();

    const experienceReview = screen
      .getByRole("checkbox", { name: new RegExp(extractedFact.label) })
      .closest("article");
    const educationReview = screen
      .getByRole("checkbox", { name: new RegExp(extractedEducationFact.label) })
      .closest("article");
    expect(experienceReview).not.toBeNull();
    expect(educationReview).not.toBeNull();
    expect(within(experienceReview!).getByText(extractedFact.detail!)).toBeVisible();
    expect(within(educationReview!).getAllByText(extractedEducationFact.detail!)).toHaveLength(1);

    const continueButton = screen.getByRole("button", { name: "اعتماد التحليل والمتابعة" });
    await user.click(continueButton);

    await waitFor(() => expect(apiMocks.confirmCareerFactsBatch).toHaveBeenCalled());
    await waitFor(() => expect(apiMocks.prepareResumeImportFlow).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "هل عندك معلومات غير موجودة في الملف؟" })).toBeVisible();
    expect(screen.getByRole("button", { name: "نعم، أضيفها" })).toBeVisible();
    expect(screen.getByRole("button", { name: "لا، اسألني عن النواقص" })).toBeVisible();
    expect(screen.queryByText(/يحتاج تفصيل/)).not.toBeInTheDocument();
  });

  it("does not report optional project, certification, or achievement sections as missing", async () => {
    const user = userEvent.setup();
    const skillFact: ApiCareerFact = {
      ...extractedFact,
      id: "fact-imported-skill-1",
      category: "skill",
      label: "Power BI",
      detail: null,
      structured_value: {},
    };
    const languageFact: ApiCareerFact = {
      ...extractedFact,
      id: "fact-imported-language-1",
      category: "language",
      label: "English",
      detail: "Fluent",
      structured_value: { proficiency: "Fluent" },
    };
    const completeCoreFacts = [
      extractedEducationFact,
      extractedFact,
      skillFact,
      languageFact,
    ];
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(makeWorkspace())
      .mockResolvedValue(makeWorkspace({ evidence_revision: 2, readiness_score: 70 }));
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue(completeCoreFacts);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: extractedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: completeCoreFacts,
      requires_user_review: true,
      analysis_status: "created",
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));

    const assessmentHeading = await screen.findByRole("heading", { name: "تقييم مبدئي لجاهزية ATS" });
    const assessment = assessmentHeading.closest("section");
    expect(assessment).not.toBeNull();
    expect(within(assessment!).getByText("الأقسام الأساسية موجودة")).toBeVisible();
    expect(within(assessment!).getByText(/التعليم/)).toBeVisible();
    expect(within(assessment!).getByText(/الخبرة/)).toBeVisible();
    expect(within(assessment!).getByText(/المهارات/)).toBeVisible();
    expect(within(assessment!).getByText(/اللغات/)).toBeVisible();
    expect(within(assessment!).queryByText("المشاريع")).not.toBeInTheDocument();
    expect(within(assessment!).queryByText("الشهادات")).not.toBeInTheDocument();
    expect(within(assessment!).queryByText("الإنجازات")).not.toBeInTheDocument();
  });

  it("presents found ATS sections in the same order as the generated resume", async () => {
    const user = userEvent.setup();
    const categories: ApiCareerFact["category"][] = [
      "education",
      "experience",
      "certification",
      "skill",
      "language",
      "project",
      "achievement",
    ];
    const imported = categories.map((category, index) => ({
      ...extractedFact,
      id: `ordered-${category}-${index}`,
      category,
      label: `Ordered ${category}`,
      detail: null,
      structured_value: {},
    }));
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(makeWorkspace())
      .mockResolvedValue(makeWorkspace({ evidence_revision: 2 }));
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue(imported);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: extractedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: imported,
      requires_user_review: true,
      analysis_status: "created",
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));

    const assessment = (await screen.findByRole("heading", { name: "تقييم مبدئي لجاهزية ATS" })).closest("section");
    expect(assessment).not.toBeNull();
    const found = within(assessment!).getByText("موجود في الملف").parentElement;
    expect(found).not.toBeNull();
    const certification = within(found!).getByText(/الشهادات/);
    const skills = within(found!).getByText(/المهارات/);
    const languages = within(found!).getByText(/اللغات/);
    const projects = within(found!).getByText(/المشاريع/);
    const achievements = within(found!).getByText(/الإنجازات/);
    expect(certification.compareDocumentPosition(skills) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(skills.compareDocumentPosition(languages) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(languages.compareDocumentPosition(projects) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(projects.compareDocumentPosition(achievements) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
  });

  it("does not auto-build an already reviewed file before the additions and gap steps", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace({ evidence_revision: 4 });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(current);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([confirmedImportedFact]);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: confirmedImportedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: [confirmedImportedFact],
      requires_user_review: false,
      analysis_status: "already_ai_analyzed",
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));

    expect(await screen.findByRole("heading", { name: "تقييم مبدئي لجاهزية ATS" })).toBeVisible();
    expect(apiMocks.prepareResumeImportFlow).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: "الملخص المهني" })).not.toBeInTheDocument();
  });

  it("restores the pending ATS assessment when the upload response is lost after commit", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace({ evidence_revision: 4 });
    const recovered = makeWorkspace({
      evidence_revision: 4,
      provider_metadata: {
        pending_import_source_id: confirmedImportedFact.source_id,
        pending_import_filename: "resume.pdf",
        pending_import_analysis_status: "already_ai_analyzed",
      },
    });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(recovered);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([confirmedImportedFact]);
    apiMocks.importResumeWorkspaceFile.mockRejectedValue(new TypeError("response lost"));
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));

    expect(await screen.findByRole("heading", { name: "تقييم مبدئي لجاهزية ATS" })).toBeVisible();
    expect(screen.getByRole("button", { name: "اعتماد التحليل والمتابعة" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(apiMocks.prepareResumeImportFlow).not.toHaveBeenCalled();
  });

  it("discards a stale upload card when another tab has already advanced an import flow", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace({ evidence_revision: 4 });
    const activeOtherFlow = makeWorkspace({
      revision: 2,
      evidence_revision: 5,
      messages: [],
      provider_metadata: {
        import_flow: {
          phase: "additions_choice",
          can_generate: false,
          source_id: "source-from-other-tab",
          file_name: "resume.pdf",
          assessment: { gaps: [], page_target: 1 },
          gap_queue: [],
          page_target: 1,
        },
      },
    });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(activeOtherFlow);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([confirmedImportedFact]);
    apiMocks.importResumeWorkspaceFile.mockRejectedValue(
      new ApiHttpError(409, "Another import flow is active", "resume_import_phase_conflict"),
    );
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));

    expect(await screen.findByRole("heading", { name: "هل عندك معلومات غير موجودة في الملف؟" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "حلّل الملف" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("restores the additions decision and starts one AI gap question without early generation", async () => {
    const user = userEvent.setup();
    const additionsWorkspace = makeWorkspace({
      evidence_revision: 4,
      readiness_score: 55,
      messages: [],
      provider_metadata: {
        conversation_language: "ar",
        import_flow: {
          phase: "additions_choice",
          source_id: confirmedImportedFact.source_id,
          file_name: "resume.pdf",
          assessment: {
            score: 55,
            found_sections: ["education", "experience"],
            missing_sections: ["skill", "language"],
          },
        },
      },
    });
    const gapQuestion = {
      ...assistantQuestion,
      id: "gap-skill-1",
      content: "ما الأدوات أو المهارات التي استخدمتها فعليًا؟",
      structured_payload: {
        question: {
          id: "gap_skill_1",
          category: "skill",
          question: "ما الأدوات أو المهارات التي استخدمتها فعليًا؟",
        },
      },
    };
    const gapWorkspace = makeWorkspace({
      ...additionsWorkspace,
      revision: 1,
      messages: [gapQuestion],
      provider_metadata: {
        ...additionsWorkspace.provider_metadata,
        import_flow: {
          ...(additionsWorkspace.provider_metadata?.import_flow as Record<string, unknown>),
          phase: "gap_interview",
        },
      },
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(additionsWorkspace);
    apiMocks.getCareerFacts.mockResolvedValue([confirmedImportedFact]);
    apiMocks.sendResumeWorkspaceMessage.mockResolvedValue(gapWorkspace);
    await renderResumePage();

    expect(await screen.findByRole("heading", { name: "هل عندك معلومات غير موجودة في الملف؟" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "اكتب السيرة الآن" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "لا، اسألني عن النواقص" }));

    await waitFor(() => expect(apiMocks.sendResumeWorkspaceMessage).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({ quickAction: "additions_no" }),
    ));
    expect(await screen.findByText("ما الأدوات أو المهارات التي استخدمتها فعليًا؟")).toBeVisible();
    expect(screen.getAllByRole("textbox", { name: "اكتب رسالتك" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "اكتب السيرة الآن" })).not.toBeInTheDocument();
  });

  it("groups imported facts, confirms the selected facts, rejects the rest, then prepares the additions step", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace();
    const refreshed = makeWorkspace({ readiness_score: 55, evidence_revision: 2 });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(refreshed);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([extractedFact, extractedEducationFact]);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: extractedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: [extractedFact, extractedEducationFact],
      requires_user_review: true,
      analysis_status: "created",
    });
    apiMocks.confirmCareerFactsBatch.mockResolvedValue({
      facts: [{ ...extractedFact, verification_status: "confirmed" }],
      evidence_revision: 3,
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    const file = new File(["resume"], "resume.pdf", { type: "application/pdf" });
    await user.upload(input!, file);

    expect(apiMocks.importResumeWorkspaceFile).not.toHaveBeenCalled();
    expect(await screen.findByRole("heading", { name: "حلّل هذا الملف بالذكاء الاصطناعي؟" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "حلّل الملف" }));

    await waitFor(() => expect(apiMocks.importResumeWorkspaceFile).toHaveBeenCalledWith(
      profile.id,
      file,
      { dataSharingAcknowledged: true },
    ));
    expect(await screen.findByRole("heading", { name: "تقييم مبدئي لجاهزية ATS" })).toBeVisible();
    const review = screen.getByRole("heading", { name: "راجع المعلومات المستخرجة" }).closest("section");
    expect(review).not.toBeNull();
    const educationHeading = within(review!).getByRole("heading", { name: "التعليم" });
    const experienceHeading = within(review!).getByRole("heading", { name: "الخبرة" });
    expect(educationHeading.compareDocumentPosition(experienceHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(review!).getByText("Reduced monthly reporting time by 35% through SQL automation.")).toBeVisible();
    expect(within(review!).getByText("Built Power BI dashboards tracking 12 regional sites.")).toBeVisible();
    expect(within(review!).getByText("لوحات Power BI")).toBeVisible();
    expect(within(review!).getAllByText("Bachelor of Finance")).toHaveLength(2);
    expect(within(review!).queryByText("معلومة من استيراد أقدم")).not.toBeInTheDocument();
    expect(apiMocks.confirmCareerFact).not.toHaveBeenCalled();
    expect(within(review!).queryByRole("button", { name: "تأكيد هذه المعلومة" })).not.toBeInTheDocument();

    const experienceCheckbox = within(review!).getByRole("checkbox", { name: new RegExp(extractedFact.label) });
    const educationCheckbox = within(review!).getByRole("checkbox", { name: new RegExp(extractedEducationFact.label) });
    const confirmAndContinue = within(review!).getByRole("button", { name: "اعتماد التحليل والمتابعة" });
    expect(experienceCheckbox).toBeChecked();
    expect(educationCheckbox).toBeChecked();
    await user.click(educationCheckbox);
    expect(educationCheckbox).not.toBeChecked();
    expect(confirmAndContinue).toBeEnabled();
    await user.click(confirmAndContinue);

    await waitFor(() => expect(apiMocks.confirmCareerFactsBatch).toHaveBeenCalledWith(
      profile.id,
      {
        sourceId: extractedFact.source_id,
        clientRequestId: expect.any(String),
        factIds: [extractedFact.id],
        rejectedFactIds: [extractedEducationFact.id],
        expectedEvidenceRevision: refreshed.evidence_revision,
      },
    ));
    await waitFor(() => expect(apiMocks.prepareResumeImportFlow).toHaveBeenCalledWith(
      profile.id,
      {
        sourceId: extractedFact.source_id,
        clientRequestId: expect.any(String),
        expectedRevision: refreshed.revision,
        expectedEvidenceRevision: 3,
      },
    ));
    expect(apiMocks.confirmCareerFact).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("heading", { name: "راجع المعلومات المستخرجة" })).not.toBeInTheDocument());
  });

  it("does not reopen previously rejected facts when the same analyzed file is uploaded", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(makeWorkspace())
      .mockResolvedValue(makeWorkspace({ readiness_score: 55 }));
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([extractedFact, previouslyRejectedFact]);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: extractedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: [extractedFact, previouslyRejectedFact],
      requires_user_review: true,
      analysis_status: "already_ai_analyzed",
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    const file = new File(["resume"], "resume.pdf", { type: "application/pdf" });
    await user.upload(input!, file);
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));

    const reviewHeading = await screen.findByRole("heading", { name: "راجع المعلومات المستخرجة" });
    const review = reviewHeading.closest("section");
    expect(review).not.toBeNull();
    expect(within(review!).getByText(extractedFact.label)).toBeVisible();
    expect(within(review!).queryByText(previouslyRejectedFact.label)).not.toBeInTheDocument();
    expect(within(review!).getByRole("checkbox", { name: new RegExp(extractedFact.label) })).toBeVisible();
    expect(within(review!).queryByRole("button", { name: "تأكيد هذه المعلومة" })).not.toBeInTheDocument();
  });

  it("restores an already analyzed all-confirmed file and prepares the additions step after approval", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace({ evidence_revision: 4 });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(current);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([confirmedImportedFact]);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: confirmedImportedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: [confirmedImportedFact],
      requires_user_review: true,
      analysis_status: "already_ai_analyzed",
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    const file = new File(["resume"], "resume.pdf", { type: "application/pdf" });
    await user.upload(input!, file);
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));
    expect(await screen.findByRole("heading", { name: "تقييم مبدئي لجاهزية ATS" })).toBeVisible();
    expect(apiMocks.prepareResumeImportFlow).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "اعتماد التحليل والمتابعة" }));

    await waitFor(() => expect(apiMocks.prepareResumeImportFlow).toHaveBeenCalledWith(
      profile.id,
      {
        sourceId: confirmedImportedFact.source_id,
        clientRequestId: expect.any(String),
        expectedRevision: current.revision,
        expectedEvidenceRevision: current.evidence_revision,
      },
    ));
    expect(apiMocks.confirmCareerFactsBatch).not.toHaveBeenCalled();
  });

  it("reconciles a prepared same-file interview when the response is lost", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace({ evidence_revision: 4 });
    const committed = makeWorkspace({
      revision: 1,
      evidence_revision: 4,
      provider_metadata: {
        import_flow: {
          phase: "additions_choice",
          can_generate: false,
          source_id: confirmedImportedFact.source_id,
          file_name: "resume.pdf",
          assessment: { found_sections: ["experience"], missing_sections: ["skill"] },
          gap_queue: [],
          page_target: 1,
        },
      },
    });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValueOnce(current)
      .mockResolvedValue(committed);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([confirmedImportedFact]);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: confirmedImportedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: [confirmedImportedFact],
      requires_user_review: false,
      analysis_status: "already_ai_analyzed",
    });
    apiMocks.prepareResumeImportFlow.mockRejectedValue(new TypeError("response lost"));
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));
    await user.click(await screen.findByRole("button", { name: "اعتماد التحليل والمتابعة" }));

    expect(await screen.findByRole("heading", { name: "هل عندك معلومات غير موجودة في الملف؟" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("rejects deselected pending facts and prepares the interview from confirmed facts", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace({ evidence_revision: 4 });
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(current);
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([confirmedImportedFact, extractedEducationFact]);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: confirmedImportedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: [confirmedImportedFact, extractedEducationFact],
      requires_user_review: true,
      analysis_status: "already_ai_analyzed",
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));
    const pendingCheckbox = await screen.findByRole("checkbox", { name: new RegExp(extractedEducationFact.label) });
    expect(pendingCheckbox).toBeChecked();
    await user.click(pendingCheckbox);
    await user.click(screen.getByRole("button", { name: "اعتماد التحليل والمتابعة" }));

    await waitFor(() => expect(apiMocks.confirmCareerFactsBatch).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({ factIds: [], rejectedFactIds: [extractedEducationFact.id] }),
    ));
    await waitFor(() => expect(apiMocks.prepareResumeImportFlow).toHaveBeenCalled());
  });

  it("prevents uploading another resume while a draft is active", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "writing",
      current_draft: draft,
      draft_revision: 1,
    }));
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: "امسح المسودة أولًا لرفع ملف آخر" })).toBeDisabled();
  });

  it("blocks the generic generate action while imported facts still need review", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace();
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(makeWorkspace({ evidence_revision: 2 }));
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([])
      .mockResolvedValue([extractedFact]);
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: {
        id: extractedFact.source_id,
        kind: "cv_upload",
        label: "resume.pdf",
        original_filename: "resume.pdf",
      },
      facts: [extractedFact],
      requires_user_review: true,
      analysis_status: "created",
    });
    await renderResumePage();

    const input = document.querySelector<HTMLInputElement>("#resume-workspace-file");
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["resume"], "resume.pdf", { type: "application/pdf" }));
    await user.click(await screen.findByRole("button", { name: "حلّل الملف" }));

    expect(await screen.findByRole("checkbox", { name: new RegExp(extractedFact.label) })).toBeVisible();
    expect(screen.getByRole("button", { name: "اكتب السيرة الآن" })).toBeDisabled();
  });

  it("restores pending extracted-fact review from the initial facts after reload", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      evidence_revision: 2,
      provider_metadata: {
        pending_import_source_id: extractedFact.source_id,
        pending_import_filename: "resume.pdf",
        pending_import_analysis_status: "created",
      },
    }));
    apiMocks.getCareerFacts.mockResolvedValue([extractedEducationFact, extractedFact]);
    await renderResumePage();

    const reviewHeading = await screen.findByRole("heading", { name: "راجع المعلومات المستخرجة" });
    const review = reviewHeading.closest("section");
    expect(review).not.toBeNull();
    expect(within(review!).getByRole("checkbox", { name: new RegExp(extractedEducationFact.label) })).toBeVisible();
    expect(within(review!).getByRole("checkbox", { name: new RegExp(extractedFact.label) })).toBeVisible();
    expect(within(review!).getByRole("heading", { name: "التعليم" })).toBeVisible();
    expect(within(review!).getByRole("heading", { name: "الخبرة" })).toBeVisible();
    expect(apiMocks.importResumeWorkspaceFile).not.toHaveBeenCalled();
  });

  it("shows a before-and-after AI rewrite and accepts it without replacing the whole draft", async () => {
    const user = userEvent.setup();
    const suggestion = {
      suggestion_id: "suggestion-1",
      target_kind: "bullet" as const,
      section_key: "experience" as const,
      item_id: "experience_1",
      bullet_index: 0,
      mode: "stronger" as const,
      instruction: null,
      before_text: "بنيت لوحات Power BI.",
      after_text: "بنيت لوحات Power BI تفاعلية سهّلت متابعة مؤشرات الأداء.",
      base_draft_revision: 1,
      evidence_handles: ["fact:fact-1"],
    };
    const reviewWorkspace = makeWorkspace({
      stage: "writing",
      readiness_score: 91,
      current_draft: draft,
      draft_revision: 1,
      pending_suggestion: suggestion,
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(reviewWorkspace);
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    const acceptedDraft: ApiResumeDraftContent = {
      ...draft,
      sections: draft.sections.map((section) => ({
        ...section,
        items: section.items.map((item) => ({
          ...item,
          bullets: item.bullets.map((bullet, index) => (
            item.id === suggestion.item_id && index === suggestion.bullet_index
              ? suggestion.after_text
              : bullet
          )),
        })),
      })),
    };
    apiMocks.decideResumeRewriteSuggestion.mockResolvedValue({
      ...reviewWorkspace,
      current_draft: acceptedDraft,
      pending_suggestion: null,
      draft_revision: 2,
    });
    await renderResumePage();

    expect(await screen.findByText("بنيت لوحات Power BI.")).toBeVisible();
    expect(screen.getByText("بنيت لوحات Power BI تفاعلية سهّلت متابعة مؤشرات الأداء.")).toBeVisible();
    expect(screen.getByDisplayValue(draft.sections[0].items[0].bullets[0])).toBeVisible();
    expect(screen.queryAllByText(/قابل للقياس|نتيجة قابلة للتحقق/)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "اعتمد التحسين" }));
    await waitFor(() => expect(apiMocks.decideResumeRewriteSuggestion).toHaveBeenCalledWith(
      profile.id,
      "suggestion-1",
      "accept",
      1,
    ));
    expect(await screen.findByDisplayValue(suggestion.after_text)).toBeVisible();
    expect(screen.queryByDisplayValue(draft.sections[0].items[0].bullets[0])).not.toBeInTheDocument();
  });

  it("does not start a generate quick action while a draft autosave is pending", async () => {
    const user = userEvent.setup();
    const writingWorkspace = makeWorkspace({
      stage: "writing",
      current_draft: draft,
      draft_revision: 1,
      updated_at: "2026-08-08T10:00:00Z",
    });
    const editedSummary = "ملخص مهني جديد يجب حفظه قبل بدء إعادة التوليد.";
    let resolveSave!: (workspace: ApiResumeWorkspace) => void;
    const saveRequest = new Promise<ApiResumeWorkspace>((resolve) => {
      resolveSave = resolve;
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(writingWorkspace);
    apiMocks.patchResumeWorkspaceDraft.mockReturnValue(saveRequest);
    apiMocks.sendResumeWorkspaceMessage.mockResolvedValue({
      ...writingWorkspace,
      revision: 1,
    });
    await renderResumePage();

    const summary = await screen.findByRole("textbox", { name: "الملخص المهني" });
    await user.clear(summary);
    await user.type(summary, editedSummary);
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 750));
    });
    await waitFor(() => expect(apiMocks.patchResumeWorkspaceDraft).toHaveBeenCalledOnce());

    const generate = screen.getByRole("button", { name: "اكتب السيرة الآن" });
    const generateWasDisabled = (generate as HTMLButtonElement).disabled;
    await user.click(generate);
    const messagesSentBeforeSave = apiMocks.sendResumeWorkspaceMessage.mock.calls.length;

    await act(async () => {
      resolveSave({
        ...writingWorkspace,
        current_draft: { ...draft, professional_summary: editedSummary },
        draft_revision: 2,
        updated_at: "2026-08-08T10:01:00Z",
      });
      await saveRequest;
    });

    expect(generateWasDisabled).toBe(true);
    expect(messagesSentBeforeSave).toBe(0);
  });

  it("serializes draft autosaves and never lets an older response replace newer text", async () => {
    const user = userEvent.setup();
    const writingWorkspace = makeWorkspace({
      stage: "writing",
      current_draft: draft,
      draft_revision: 0,
      updated_at: "2026-08-08T10:00:00Z",
    });
    let resolveFirstSave!: (workspace: ApiResumeWorkspace) => void;
    const firstSave = new Promise<ApiResumeWorkspace>((resolve) => {
      resolveFirstSave = resolve;
    });
    const firstSummary = "النسخة الأولى من الملخص المهني.";
    const newestSummary = "النسخة الأحدث التي يجب أن تبقى ظاهرة ومحفوظة.";
    apiMocks.getResumeWorkspace.mockResolvedValue(writingWorkspace);
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    apiMocks.patchResumeWorkspaceDraft
      .mockReturnValueOnce(firstSave)
      .mockResolvedValueOnce(makeWorkspace({
        ...writingWorkspace,
        current_draft: { ...draft, professional_summary: newestSummary },
        draft_revision: 2,
        updated_at: "2026-08-08T10:02:00Z",
      }));
    await renderResumePage();

    await user.click(await screen.findByRole("tab", { name: "السيرة" }));
    const summary = screen.getByRole("textbox", { name: "الملخص المهني" });
    await user.clear(summary);
    await user.type(summary, firstSummary);
    await waitFor(() => expect(apiMocks.patchResumeWorkspaceDraft).toHaveBeenCalledTimes(1), { timeout: 2_000 });

    await user.clear(summary);
    await user.type(summary, newestSummary);
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 750));
    });
    expect(apiMocks.patchResumeWorkspaceDraft).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirstSave(makeWorkspace({
        ...writingWorkspace,
        current_draft: { ...draft, professional_summary: firstSummary },
        draft_revision: 1,
        updated_at: "2026-08-08T10:01:00Z",
      }));
      await firstSave;
    });

    await waitFor(() => expect(apiMocks.patchResumeWorkspaceDraft).toHaveBeenCalledTimes(2));
    expect(apiMocks.patchResumeWorkspaceDraft).toHaveBeenLastCalledWith(profile.id, {
      draft: expect.objectContaining({ professional_summary: newestSummary }),
      expectedDraftRevision: 1,
    });
    await waitFor(() => expect(summary).toHaveValue(newestSummary));
  }, 15_000);

  it("waits for autosave and merges a rewrite into the latest workspace without losing edits", async () => {
    const user = userEvent.setup();
    const writingWorkspace = makeWorkspace({
      stage: "writing",
      current_draft: draft,
      draft_revision: 1,
      updated_at: "2026-08-08T10:00:00Z",
    });
    const savedSummary = "ملخص مهني محفوظ يجب أن يبقى بعد وصول اقتراح الذكاء الاصطناعي.";
    const savedDraft = { ...draft, professional_summary: savedSummary };
    let resolveSave!: (workspace: ApiResumeWorkspace) => void;
    let resolveRewrite!: (suggestion: Awaited<ReturnType<typeof apiMocks.rewriteResumeDraftSelection>>) => void;
    const saveRequest = new Promise<ApiResumeWorkspace>((resolve) => {
      resolveSave = resolve;
    });
    const rewriteRequest = new Promise<Awaited<ReturnType<typeof apiMocks.rewriteResumeDraftSelection>>>((resolve) => {
      resolveRewrite = resolve;
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(writingWorkspace);
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    apiMocks.patchResumeWorkspaceDraft.mockReturnValue(saveRequest);
    apiMocks.rewriteResumeDraftSelection.mockReturnValue(rewriteRequest);
    await renderResumePage();

    await user.click(await screen.findByRole("tab", { name: "السيرة" }));
    const summary = screen.getByDisplayValue(draft.professional_summary);
    await user.click(summary);
    await user.clear(summary);
    await user.type(summary, savedSummary);
    await waitFor(() => expect(apiMocks.patchResumeWorkspaceDraft).toHaveBeenCalledOnce(), { timeout: 2_000 });

    const strengthen = within(summary.parentElement!).getAllByRole("button")[0];
    expect(strengthen).toBeDisabled();
    await user.click(strengthen);
    expect(apiMocks.rewriteResumeDraftSelection).not.toHaveBeenCalled();

    await act(async () => {
      resolveSave(makeWorkspace({
        ...writingWorkspace,
        current_draft: savedDraft,
        draft_revision: 2,
        updated_at: "2026-08-08T10:01:00Z",
      }));
      await saveRequest;
    });
    await waitFor(() => expect(strengthen).toBeEnabled());

    await user.click(strengthen);
    await waitFor(() => expect(apiMocks.rewriteResumeDraftSelection).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({
        targetKind: "professional_summary",
        expectedDraftRevision: 2,
      }),
    ));
    expect(summary).toBeDisabled();

    await user.click(screen.getByRole("tab", { name: "المحادثة" }));
    await user.click(screen.getByRole("button", { name: "التواصل" }));
    await user.type(screen.getByRole("textbox", { name: "البريد الإلكتروني" }), "latest@example.com");

    const suggestion = {
      suggestion_id: "suggestion-latest",
      target_kind: "professional_summary" as const,
      section_key: null,
      item_id: null,
      bullet_index: null,
      mode: "stronger" as const,
      instruction: null,
      before_text: savedSummary,
      after_text: "ملخص مهني محسّن ومدعوم بالحقائق المؤكدة.",
      base_draft_revision: 2,
      evidence_handles: ["fact:fact-1"],
    };
    await act(async () => {
      resolveRewrite(suggestion);
      await rewriteRequest;
    });

    expect(await screen.findByDisplayValue(savedSummary)).toBeEnabled();
    expect(screen.getByText("latest@example.com")).toBeVisible();
    expect(screen.getByText(suggestion.after_text)).toBeVisible();
  }, 15_000);

  it("reviews the saved draft before exporting its PDF", async () => {
    const user = userEvent.setup();
    const reviewWorkspace = makeWorkspace({
      stage: "review",
      readiness_score: 91,
      current_draft: draft,
      draft_revision: 1,
      section_coverage: { experience: true, education: true, project: true, skill: true, certification: true, language: true, achievement: true },
      versions: [{
        id: "old-export-ready-version",
        workspace_id: "workspace-1",
        version: 1,
        base_version_id: null,
        reason: "review",
        status: "export_ready",
        content: draft,
        diff: {},
        evidence_revision: 0,
        reviewed_at: "2026-08-07T10:00:00Z",
        review_hash: "old-review-hash",
        created_at: "2026-08-07T10:00:00Z",
      }],
    });
    apiMocks.getResumeWorkspace.mockResolvedValue(reviewWorkspace);
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    const createObjectURL = vi.fn(() => "blob:resume-v2");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await renderResumePage();

    expect(screen.getByRole("textbox", { name: "العنوان المهني" }).tagName).toBe("TEXTAREA");

    const download = await screen.findByRole("button", { name: "تنزيل PDF" });
    expect(download).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "راجعت المعلومات" }));
    await waitFor(() => expect(apiMocks.reviewResumeWorkspace).toHaveBeenCalledWith(profile.id, 1));
    expect(download).toBeEnabled();
    await user.click(download);

    await waitFor(() => expect(apiMocks.exportResumeWorkspacePdf).toHaveBeenCalledWith(profile.id, 1));
    expect(anchorClick).toHaveBeenCalledOnce();
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    expect(screen.getByText(/تم تجهيز ملف PDF/)).toBeVisible();
    expect(screen.getByRole("link", { name: "نزّله من هنا" })).toHaveAttribute(
      "href",
      "blob:resume-v2",
    );
    expect(screen.getByRole("link", { name: "نزّله من هنا" })).toHaveAttribute(
      "download",
      `${profile.full_name}-resume.pdf`,
    );

    await user.type(screen.getByRole("textbox", { name: "العنوان المهني" }), " updated");
    await waitFor(() => expect(screen.queryByRole("link", { name: "نزّله من هنا" })).not.toBeInTheDocument());
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:resume-v2");
  });

  it("restores the current server review after reloading the review stage", async () => {
    const currentReview = {
      id: "current-export-ready-version",
      workspace_id: "workspace-1",
      version: 2,
      base_version_id: null,
      reason: "review" as const,
      status: "export_ready" as const,
      content: draft,
      diff: {},
      evidence_revision: 1,
      reviewed_at: "2026-08-08T10:10:00Z",
      review_hash: "current-review-hash",
      created_at: "2026-08-08T10:10:00Z",
    };
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "review",
      current_draft: draft,
      draft_revision: 1,
      evidence_revision: 1,
      versions: [currentReview],
    }));
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    await renderResumePage();

    expect(await screen.findByRole("checkbox", { name: "راجعت المعلومات" })).toBeChecked();
    expect(screen.getByRole("button", { name: "تنزيل PDF" })).toBeEnabled();
    expect(screen.getByLabelText("إجراءات اعتماد السيرة")).toHaveClass(
      "xl:relative",
      "xl:z-50",
      "xl:bg-background",
    );
    expect(apiMocks.reviewResumeWorkspace).not.toHaveBeenCalled();
  });

  it("invalidates the restored review immediately when contact details change", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "writing",
      current_draft: draft,
      draft_revision: 1,
      evidence_revision: 1,
      versions: [{
        id: "review-before-contact-edit",
        workspace_id: "workspace-1",
        version: 2,
        base_version_id: null,
        reason: "review",
        status: "export_ready",
        content: draft,
        diff: {},
        evidence_revision: 1,
        reviewed_at: "2026-08-08T10:10:00Z",
        review_hash: "review-before-contact-edit-hash",
        created_at: "2026-08-08T10:10:00Z",
      }],
    }));
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    await renderResumePage();

    const review = await screen.findByRole("checkbox", { name: "راجعت المعلومات" });
    expect(review).toBeChecked();
    await user.click(screen.getByRole("button", { name: "التواصل" }));
    await user.type(
      screen.getByRole("textbox", { name: "البريد الإلكتروني" }),
      "new@example.com",
    );

    expect(review).not.toBeChecked();
    expect(screen.getByRole("button", { name: "تنزيل PDF" })).toBeDisabled();
    await waitFor(() => expect(apiMocks.startResumeWorkspace).toHaveBeenCalled(), { timeout: 2_000 });
    expect(review).not.toBeChecked();
    expect(screen.getByRole("button", { name: "تنزيل PDF" })).toBeDisabled();
  });

  it("does not trust the complete stage without a current export-ready review", async () => {
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "complete",
      current_draft: draft,
      draft_revision: 2,
      evidence_revision: 2,
      versions: [],
    }));
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    await renderResumePage();

    expect(await screen.findByRole("checkbox", { name: "راجعت المعلومات" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "تنزيل PDF" })).toBeDisabled();
  });

  it("revokes a prepared PDF link when the workspace is permanently cleared", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "review",
      revision: 7,
      current_draft: draft,
      draft_revision: 1,
    }));
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:reset-resume"),
    });
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await renderResumePage();

    await user.click(await screen.findByRole("checkbox", { name: "راجعت المعلومات" }));
    await waitFor(() => expect(apiMocks.reviewResumeWorkspace).toHaveBeenCalledWith(profile.id, 1));
    await user.click(screen.getByRole("button", { name: "تنزيل PDF" }));
    expect(await screen.findByRole("link", { name: "نزّله من هنا" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "مسح والبدء من جديد" }));
    await user.click(screen.getByRole("button", { name: "امسح وابدأ من جديد" }));

    await waitFor(() => expect(apiMocks.resetResumeWorkspace).toHaveBeenCalledWith(profile.id, 7));
    expect(screen.queryByRole("link", { name: "نزّله من هنا" })).not.toBeInTheDocument();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:reset-resume");
  });

  it("shows the PDF preview inside the workspace instead of relying on a popup", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace({
      stage: "review",
      current_draft: draft,
      draft_revision: 1,
    }));
    apiMocks.getCareerFacts.mockResolvedValue([fact]);
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:preview") });
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "معاينة PDF" }));

    expect(await screen.findByRole("dialog", { name: "معاينة السيرة بصيغة PDF" })).toBeVisible();
    expect(screen.getByTitle("ملف السيرة بصيغة PDF")).toHaveAttribute("src", "blob:preview");
    expect(screen.getByRole("link", { name: "تنزيل ملف PDF" })).toHaveAttribute("href", "blob:preview");
    expect(screen.getByRole("link", { name: "تنزيل ملف PDF" })).toHaveAttribute(
      "download",
      `${profile.full_name}-resume.pdf`,
    );
    await user.click(screen.getByRole("button", { name: "إغلاق معاينة PDF" }));
    expect(screen.queryByRole("dialog", { name: "معاينة السيرة بصيغة PDF" })).not.toBeInTheDocument();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview"));
  });

  it("creates the basic profile before showing the language step", async () => {
    const user = userEvent.setup();
    apiMocks.getCareerProfile.mockResolvedValue(null);
    await renderResumePage();

    expect(await screen.findByRole("heading", { name: "عرّفنا بنفسك أولًا" })).toBeVisible();
    await user.type(screen.getByRole("textbox", { name: "الاسم الكامل" }), "هادي الغانم");
    await user.type(screen.getByRole("textbox", { name: "المدينة (اختياري)" }), "الرياض");
    await user.click(screen.getByRole("button", { name: "أنشئ ملفي وابدأ" }));

    await waitFor(() => expect(apiMocks.createCareerProfile).toHaveBeenCalledWith({
      fullName: "هادي الغانم",
      city: "الرياض",
      preferredLanguage: "ar",
    }));
    expect(await screen.findByRole("button", { name: "ابدأ المحادثة" })).toBeVisible();
  });
});
