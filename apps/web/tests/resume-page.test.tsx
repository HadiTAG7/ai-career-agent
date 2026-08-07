import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  ApiCareerFact,
  ApiResumeDraftContent,
  ApiResumeWorkspace,
} from "@/lib/api-client";

const apiMocks = vi.hoisted(() => ({
  getCareerProfile: vi.fn(),
  getCareerFacts: vi.fn(),
  getResumeWorkspace: vi.fn(),
  createCareerProfile: vi.fn(),
  startResumeWorkspace: vi.fn(),
  sendResumeWorkspaceMessage: vi.fn(),
  importResumeWorkspaceFile: vi.fn(),
  confirmCareerFact: vi.fn(),
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
  verification_status: "extracted",
  label: "لوحات Power BI",
  detail: "بنيت لوحات Power BI لمتابعة مؤشرات الأداء.",
};

const olderExtractedFact: ApiCareerFact = {
  ...extractedFact,
  id: "fact-older-1",
  source_id: "source-older-1",
  label: "معلومة من استيراد أقدم",
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
    apiMocks.startResumeWorkspace.mockResolvedValue(makeWorkspace());
    apiMocks.sendResumeWorkspaceMessage.mockResolvedValue(makeWorkspace());
    apiMocks.importResumeWorkspaceFile.mockResolvedValue({
      source: { id: "source-1", kind: "cv_upload", label: "resume.pdf", original_filename: "resume.pdf" },
      facts: [extractedFact],
      requires_user_review: true,
      analysis_status: "created",
    });
    apiMocks.confirmCareerFact.mockResolvedValue({ ...extractedFact, verification_status: "confirmed" });
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
    apiMocks.exportResumeWorkspacePdf.mockResolvedValue(new Blob(["%PDF"], { type: "application/pdf" }));
  });

  it("starts one chat-first workspace after choosing language and acknowledging AI use", async () => {
    const user = userEvent.setup();
    await renderResumePage();

    expect(await screen.findByRole("heading", { name: "خلّنا نبني قصتك المهنية" })).toBeVisible();
    expect(screen.getByRole("button", { name: "العربية" })).toHaveAttribute("aria-pressed", "true");
    const start = screen.getByRole("button", { name: "ابدأ المحادثة" });
    expect(start).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /موافقة استخدام الذكاء الاصطناعي/ }));
    await user.click(start);

    await waitFor(() => expect(apiMocks.startResumeWorkspace).toHaveBeenCalledWith(profile.id, {
      language: "ar",
      dataSharingAcknowledged: true,
    }));
    expect(await screen.findByText("احكِ لي عن تجربة مهنية تفخر بها.")).toBeVisible();
    expect(screen.getByRole("button", { name: "إرفاق سيرة موجودة" })).toBeVisible();
    expect(screen.getByLabelText("معاينة السيرة الحية")).toBeVisible();
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
      language: "ar",
      contact: { email: "hadi@example.com", phone: undefined, linkedin: undefined },
      dataSharingAcknowledged: true,
    }));
    expect(await screen.findByRole("button", { name: "إرفاق سيرة موجودة" })).toBeVisible();
  });

  it("autosaves contact details without manufacturing a new AI acknowledgement", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace());
    apiMocks.startResumeWorkspace.mockResolvedValue(makeWorkspace({ contact: { email: "hadi@example.com" } }));
    await renderResumePage();

    await user.click(await screen.findByRole("button", { name: "التواصل" }));
    await user.type(screen.getByRole("textbox", { name: "البريد الإلكتروني" }), "hadi@example.com");

    await waitFor(() => expect(apiMocks.startResumeWorkspace).toHaveBeenCalledWith(profile.id, {
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

  it("sends helper choices and skip as commands rather than ordinary answers", async () => {
    const user = userEvent.setup();
    apiMocks.getResumeWorkspace.mockResolvedValue(makeWorkspace());
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

  it("requires explicit import consent, then reviews only facts returned by that upload", async () => {
    const user = userEvent.setup();
    const current = makeWorkspace();
    apiMocks.getResumeWorkspace
      .mockResolvedValueOnce(current)
      .mockResolvedValue(makeWorkspace({ readiness_score: 55 }));
    apiMocks.getCareerFacts
      .mockResolvedValueOnce([olderExtractedFact])
      .mockResolvedValue([olderExtractedFact, extractedFact]);
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
    expect(await screen.findByText("تم استخراج معلومات من resume.pdf")).toBeVisible();
    const review = screen.getByRole("heading", { name: "راجع المعلومات المستخرجة" }).closest("section");
    expect(review).not.toBeNull();
    expect(within(review!).getByText("لوحات Power BI")).toBeVisible();
    expect(within(review!).queryByText("معلومة من استيراد أقدم")).not.toBeInTheDocument();
    expect(apiMocks.confirmCareerFact).not.toHaveBeenCalled();

    await user.click(within(review!).getByRole("button", { name: "تأكيد هذه المعلومة" }));
    await waitFor(() => expect(apiMocks.confirmCareerFact).toHaveBeenCalledWith(profile.id, extractedFact.id));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "راجع المعلومات المستخرجة" })).not.toBeInTheDocument());
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
    apiMocks.decideResumeRewriteSuggestion.mockResolvedValue({ ...reviewWorkspace, pending_suggestion: null, draft_revision: 2 });
    await renderResumePage();

    expect(await screen.findByText("بنيت لوحات Power BI.")).toBeVisible();
    expect(screen.getByText("بنيت لوحات Power BI تفاعلية سهّلت متابعة مؤشرات الأداء.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "اعتمد التحسين" }));
    await waitFor(() => expect(apiMocks.decideResumeRewriteSuggestion).toHaveBeenCalledWith(
      profile.id,
      "suggestion-1",
      "accept",
      1,
    ));
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
  });

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
  });

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

    const download = await screen.findByRole("button", { name: "تنزيل PDF" });
    expect(download).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "راجعت المعلومات" }));
    await waitFor(() => expect(apiMocks.reviewResumeWorkspace).toHaveBeenCalledWith(profile.id, 1));
    expect(download).toBeEnabled();
    await user.click(download);

    await waitFor(() => expect(apiMocks.exportResumeWorkspacePdf).toHaveBeenCalledWith(profile.id, 1));
    expect(anchorClick).toHaveBeenCalledOnce();
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:resume-v2");
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
