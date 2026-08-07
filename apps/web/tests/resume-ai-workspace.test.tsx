import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  createResumeQuestions: vi.fn(),
  generateProfessionalResume: vi.fn(),
  exportProfessionalResumePdf: vi.fn(),
}));

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, ...apiMocks };
});

import { ResumeAiWorkspace } from "@/components/resume/resume-ai-workspace";
import { ResumeDraftEditor } from "@/components/resume/resume-draft-editor";
import type {
  ApiCareerFact,
  ApiCareerProfile,
  ApiResumeDraft,
  ApiResumeQuestionsResult,
} from "@/lib/api-client";

const profile: ApiCareerProfile = {
  id: "profile-1",
  full_name: "هادي الغانم",
  headline: null,
  preferred_language: "ar",
  city: "الرياض",
  completed_fact_categories: [],
};

const facts: ApiCareerFact[] = [
  {
    id: "fact-1",
    source_id: "source-1",
    category: "experience",
    label: "تدريب في تحليل البيانات",
    detail: "إعداد تقارير أسبوعية باستخدام Excel",
    verification_status: "confirmed",
    source_excerpt: "إعداد تقارير أسبوعية باستخدام Excel",
    extraction_confidence: 0.97,
    structured_value: {},
    created_at: "2026-08-07T10:00:00Z",
  },
];

const questionsResult = {
  provider: "mistral",
  model: "mistral-small-2603",
  covered_categories: ["experience"],
  questions: [
    {
      id: "impact_result",
      category: "achievement",
      question: "وش كانت النتيجة الأهم من إعداد التقارير؟",
      why_it_matters: "النتيجة تجعل نقطة الخبرة أوضح لمسؤول التوظيف.",
      placeholder: "مثال: اختصر التقرير وقت المتابعة الأسبوعية",
      required: false,
    },
  ],
} satisfies ApiResumeQuestionsResult;

const generatedDraft = {
  headline: "محلل بيانات مبتدئ",
  professional_summary: "محلل بيانات مبتدئ لديه خبرة عملية في إعداد التقارير الأسبوعية وتحسين وضوح المعلومات.",
  summary_evidence_handles: ["fact:fact-1", "answer:impact_result"],
  sections: [
    {
      key: "experience",
      title: "الخبرة العملية",
      items: [
        {
          id: "experience_1",
          title: "متدرب تحليل بيانات",
          organization: "شركة تجريبية",
          date_range: "2025",
          location: "الرياض",
          bullets: ["أعددت تقارير أسبوعية باستخدام Excel لتوضيح مؤشرات الأداء."],
          evidence_handles: ["fact:fact-1", "answer:impact_result"],
        },
      ],
    },
  ],
  provider: "mistral",
  model: "mistral-small-2603",
  fact_count: 1,
} satisfies ApiResumeDraft;

const regeneratedDraft: ApiResumeDraft = {
  ...generatedDraft,
  professional_summary: "صياغة جديدة للمسودة بعد إعادة التوليد وتحتاج مراجعة المستخدم قبل تنزيلها.",
};

function RegenerationHarness() {
  const [draft, setDraft] = useState<ApiResumeDraft>(generatedDraft);
  return (
    <ResumeDraftEditor
      locale="ar"
      profile={profile}
      draft={draft}
      onChange={setDraft}
      onRegenerate={async () => setDraft(regeneratedDraft)}
      regenerating={false}
    />
  );
}

describe("AI resume workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.createResumeQuestions.mockResolvedValue(questionsResult);
    apiMocks.generateProfessionalResume.mockResolvedValue(generatedDraft);
    apiMocks.exportProfessionalResumePdf.mockResolvedValue(
      new Blob(["%PDF-test"], { type: "application/pdf" }),
    );
  });

  it("runs questions, generation, editing, review, and PDF download as one flow", async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => "blob:resume-pdf");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<ResumeAiWorkspace locale="ar" profile={profile} facts={facts} />);

    const startButton = screen.getByRole("button", { name: "ابدأ الأسئلة الذكية" });
    expect(startButton).toBeDisabled();
    await user.type(
      screen.getByRole("textbox", { name: "المسمى أو المجال المستهدف (اختياري)" }),
      "محلل بيانات",
    );
    await user.click(screen.getByRole("checkbox", { name: /موافقة على تشغيل كاتب السيرة/ }));
    await user.click(startButton);

    await waitFor(() => expect(apiMocks.createResumeQuestions).toHaveBeenCalledWith(profile.id, {
      language: "ar",
      targetRole: "محلل بيانات",
      dataSharingAcknowledged: true,
    }));
    expect(await screen.findByRole("heading", { name: questionsResult.questions[0].question })).toBeVisible();

    await user.type(
      screen.getByRole("textbox", { name: questionsResult.questions[0].question }),
      "اختصرت وقت إعداد التقرير الأسبوعي وسهّلت متابعة المؤشرات.",
    );
    await user.click(screen.getByRole("button", { name: "إرسال الإجابة" }));
    await user.click(await screen.findByRole("button", { name: "ولّد السيرة الاحترافية" }));

    await waitFor(() => expect(apiMocks.generateProfessionalResume).toHaveBeenCalledWith(profile.id, {
      language: "ar",
      targetRole: "محلل بيانات",
      answers: [
        {
          question_id: "impact_result",
          category: "achievement",
          question: questionsResult.questions[0].question,
          answer: "اختصرت وقت إعداد التقرير الأسبوعي وسهّلت متابعة المؤشرات.",
          skipped: false,
        },
      ],
      dataSharingAcknowledged: true,
    }));
    expect(await screen.findByRole("heading", { name: "راجع السيرة وعدّلها قبل التنزيل" })).toBeVisible();

    const downloadButton = screen.getByRole("button", { name: "تحميل السيرة PDF" });
    const reviewCheckbox = screen.getByRole("checkbox", { name: /راجعت النص والمعلومات/ });
    expect(downloadButton).toBeDisabled();
    expect(reviewCheckbox).not.toBeChecked();

    const improvedSummary = "محلل بيانات يترجم الأرقام إلى تقارير أسبوعية واضحة تدعم متابعة مؤشرات الأداء.";
    fireEvent.change(screen.getByRole("textbox", { name: "الملخص المهني" }), {
      target: { value: improvedSummary },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "نقطة 1" }), {
      target: { value: "أنشأت تقارير Excel أسبوعية سهّلت متابعة مؤشرات الأداء." },
    });
    await user.type(screen.getByRole("textbox", { name: "البريد الإلكتروني" }), "hadi@example.com");
    expect(reviewCheckbox).not.toBeChecked();
    expect(downloadButton).toBeDisabled();

    await user.click(reviewCheckbox);
    expect(downloadButton).toBeEnabled();
    await user.click(downloadButton);

    await waitFor(() => expect(apiMocks.exportProfessionalResumePdf).toHaveBeenCalledOnce());
    expect(apiMocks.exportProfessionalResumePdf).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({
        language: "ar",
        reviewAcknowledged: true,
        contact: { email: "hadi@example.com", phone: "", linkedin: "" },
        draft: expect.objectContaining({
          professional_summary: improvedSummary,
          sections: [
            expect.objectContaining({
              items: [
                expect.objectContaining({
                  bullets: ["أنشأت تقارير Excel أسبوعية سهّلت متابعة مؤشرات الأداء."],
                }),
              ],
            }),
          ],
        }),
      }),
    );
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(anchorClick).toHaveBeenCalledOnce();
    const downloadedAnchor = anchorClick.mock.instances[0] as unknown as HTMLAnchorElement;
    expect(downloadedAnchor.download).toBe("هادي الغانم-resume.pdf");
    expect(downloadedAnchor.href).toBe("blob:resume-pdf");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:resume-pdf");
  });

  it("requires a fresh review after regenerating the draft", async () => {
    const user = userEvent.setup();
    render(<RegenerationHarness />);

    const reviewCheckbox = screen.getByRole("checkbox", { name: /راجعت النص والمعلومات/ });
    const downloadButton = screen.getByRole("button", { name: "تحميل السيرة PDF" });
    await user.click(reviewCheckbox);
    expect(downloadButton).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "أعد توليد الصياغة" }));

    await waitFor(() => expect(screen.getByRole("textbox", { name: "الملخص المهني" })).toHaveValue(
      regeneratedDraft.professional_summary,
    ));
    expect(reviewCheckbox).not.toBeChecked();
    expect(downloadButton).toBeDisabled();
    expect(apiMocks.exportProfessionalResumePdf).not.toHaveBeenCalled();
  });
});
