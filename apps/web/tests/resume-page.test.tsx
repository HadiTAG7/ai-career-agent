import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const apiMocks = vi.hoisted(() => ({
  getCareerProfile: vi.fn(),
  createCareerProfile: vi.fn(),
  getCareerPathWorkspace: vi.fn(),
  importCareerFile: vi.fn(),
  createResumeDraft: vi.fn(),
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
  headline: null,
  preferred_language: "ar" as const,
  city: "الرياض",
  completed_fact_categories: [],
};

const readyWorkspace = {
  provider_ready: true,
  provider: "mistral",
  model: "mistral-small-2603",
  profile_id: profile.id,
  confirmed_fact_count: 0,
  consent_required: true,
  conversation: null,
};

const extractedFact = {
  id: "fact-1",
  source_id: "source-1",
  category: "skill",
  label: "تحليل البيانات",
  detail: "استخدام Excel لبناء تقارير أسبوعية",
  verification_status: "extracted" as const,
  source_excerpt: "Built weekly reports in Excel",
  extraction_confidence: 0.9,
  structured_value: {},
  created_at: "2026-08-07T10:00:00Z",
};

const importResult = {
  source: {
    id: "source-1",
    kind: "cv_upload" as const,
    label: "Imported resume.pdf",
    original_filename: "resume.pdf",
  },
  facts: [extractedFact],
  requires_user_review: true,
  analysis_status: "created" as const,
};

async function renderResumePage() {
  const [{ default: ResumePage }, { LocaleProvider }, { LanguageSwitch }] = await Promise.all([
    import("@/app/resume/page"),
    import("@/lib/i18n"),
    import("@/components/layout/language-switch"),
  ]);
  await act(async () => {
    render(<LocaleProvider><LanguageSwitch /><ResumePage /></LocaleProvider>);
  });
}

async function startGuidedInterview(
  user: ReturnType<typeof userEvent.setup>,
  stage: "طالب أو طالبة" | "خريج أو خريجة حديثًا" | "لدي خبرة عملية" | "أغيّر مساري المهني" | "مستقل أو صاحب عمل حر" = "طالب أو طالبة",
) {
  await user.click(screen.getByRole("button", { name: /ابنِ محتوى سيرتك من الصفر/ }));
  await user.click(screen.getByRole("radio", { name: stage }));
  await user.click(screen.getByRole("button", { name: "التالي" }));
}

async function uploadAndAnalyze(user: ReturnType<typeof userEvent.setup>, filename = "resume.pdf") {
  const file = new File(["resume"], filename, { type: "application/pdf" });
  await user.upload(await screen.findByLabelText(/اختر ملف السيرة/), file);
  await user.click(screen.getByRole("checkbox", { name: /موافقة مستقلة لتحليل السيرة/ }));
  await user.click(screen.getByRole("button", { name: "حلّل السيرة بالذكاء الاصطناعي" }));
  return file;
}

async function completeMinimalInterview(
  user: ReturnType<typeof userEvent.setup>,
  options: {
    target?: string;
    field?: string;
    environment?: string;
    degree?: string;
    major?: string;
    institution?: string;
    graduation?: string;
    gpa?: string;
    gpaScale?: string;
    highlights?: string;
    skill?: string;
    skillSource?: string;
    skillExample?: string;
  } = {},
) {
  await startGuidedInterview(user, "خريج أو خريجة حديثًا");
  if (options.target || options.field || options.environment) {
    if (options.target) await user.type(screen.getByRole("textbox", { name: "الدور أو المسمى المستهدف" }), options.target);
    if (options.field) await user.type(screen.getByRole("textbox", { name: "المجال" }), options.field);
    if (options.environment) await user.type(screen.getByRole("textbox", { name: "بيئة العمل المفضلة" }), options.environment);
    await user.click(screen.getByRole("button", { name: "التالي" }));
  } else {
    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));
  }

  await user.type(screen.getByRole("textbox", { name: "الدرجة أو المؤهل" }), options.degree ?? "بكالوريوس");
  await user.type(screen.getByRole("textbox", { name: "التخصص" }), options.major ?? "نظم معلومات");
  await user.type(screen.getByRole("textbox", { name: "الجامعة أو الجهة التعليمية" }), options.institution ?? "جامعة الملك سعود");
  await user.selectOptions(screen.getByRole("combobox", { name: "الحالة الدراسية" }), "graduated");
  if (options.graduation) await user.type(screen.getByRole("textbox", { name: "سنة التخرج أو السنة المتوقعة" }), options.graduation);
  if (options.gpa) await user.type(screen.getByRole("textbox", { name: "المعدل (اختياري)" }), options.gpa);
  if (options.gpaScale) await user.type(screen.getByRole("textbox", { name: "مقياس المعدل (اختياري)" }), options.gpaScale);
  if (options.highlights) await user.type(screen.getByRole("textbox", { name: "تكريم أو مواد بارزة (اختياري)" }), options.highlights);
  if (options.gpa && options.gpaScale) expect(screen.getByText("سيظهر في المسودة")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "التالي" }));
  await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // experience
  await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // projects
  await user.type(screen.getByRole("textbox", { name: "اسم المهارة" }), options.skill ?? "Excel");
  if (options.skillSource) await user.type(screen.getByRole("textbox", { name: "مصدر الدليل" }), options.skillSource);
  await user.type(screen.getByRole("textbox", { name: "مثال على استخدامها" }), options.skillExample ?? "بنيت تقريرًا أسبوعيًا");
  await user.click(screen.getByRole("button", { name: "التالي" }));
  await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // certifications
  await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // achievements
  await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // languages
  await screen.findByRole("heading", { name: "إجاباتك جاهزة لبناء مسودة السيرة" });
}

describe("AI resume preparation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getCareerProfile.mockResolvedValue(profile);
    apiMocks.getCareerPathWorkspace.mockResolvedValue(readyWorkspace);
    apiMocks.importCareerFile.mockResolvedValue(importResult);
    apiMocks.createResumeDraft.mockResolvedValue(importResult);
    apiMocks.createCareerProfile.mockResolvedValue(profile);
  });

  it("requires separate consent before uploading a resume for AI extraction", async () => {
    const user = userEvent.setup();
    await renderResumePage();

    expect(await screen.findByText("mistral · mistral-small-2603")).toBeVisible();
    const submitButton = screen.getByRole("button", { name: "حلّل السيرة بالذكاء الاصطناعي" });
    const file = new File(["resume"], "resume.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText(/اختر ملف السيرة/), file);
    expect(submitButton).toBeDisabled();
    expect(screen.getByText(/لا يُرسل ملف PDF أو DOCX نفسه إلى المزود/)).toBeVisible();

    await user.click(screen.getByRole("checkbox", { name: /موافقة مستقلة لتحليل السيرة/ }));
    expect(submitButton).toBeEnabled();
    await user.click(submitButton);

    await waitFor(() => expect(apiMocks.importCareerFile).toHaveBeenCalledWith(
      profile.id,
      file,
      { useAi: true, dataSharingAcknowledged: true },
    ));
    expect(await screen.findByRole("heading", { name: "استخرجنا 1 حقائق للمراجعة" })).toBeVisible();
    expect(screen.getByText("تحليل البيانات")).toBeVisible();
    expect(screen.getByText("بحاجة إلى مراجعة")).toBeVisible();
    expect(screen.getByRole("link", { name: "افتح الحقائق وعدّلها" })).toHaveAttribute("href", "/profile?status=review#facts-title");
    expect(screen.getByRole("checkbox", { name: /موافقة مستقلة لتحليل السيرة/ })).not.toBeChecked();
  });

  it("shows AI-upgraded suggestions as reviewable facts", async () => {
    apiMocks.importCareerFile.mockResolvedValue({
      ...importResult,
      analysis_status: "ai_upgraded",
    });
    const user = userEvent.setup();
    await renderResumePage();
    await uploadAndAnalyze(user);

    expect(await screen.findByRole("heading", { name: "اكتمل تحليل السيرة بالذكاء الاصطناعي" })).toBeVisible();
    expect(screen.getByText("أضاف التحليل اقتراحات جديدة تحتاج مراجعتك؛ صحّح ما يلزم وأكد الصحيح فقط.")).toBeVisible();
    expect(screen.getByText("تحليل البيانات")).toBeVisible();
    expect(screen.getByText("بحاجة إلى مراجعة")).toBeVisible();
    expect(screen.getByRole("link", { name: "افتح الحقائق وعدّلها" })).toHaveAttribute("href", "/profile?status=review#facts-title");
  });

  it("explains an AI upgrade with no new suggestions without implying confirmed facts changed", async () => {
    apiMocks.importCareerFile.mockResolvedValue({
      ...importResult,
      facts: [],
      analysis_status: "ai_upgraded",
    });
    const user = userEvent.setup();
    await renderResumePage();
    await uploadAndAnalyze(user);

    expect(await screen.findByRole("heading", { name: "اكتمل تحليل السيرة بالذكاء الاصطناعي" })).toBeVisible();
    expect(screen.getByText("لم نجد اقتراحات جديدة. حافظنا على الحقائق السابقة ولم نستبدل أي حقيقة مؤكدة.")).toBeVisible();
    expect(screen.queryByText("بحاجة إلى مراجعة")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "افتح الحقائق وعدّلها" })).toHaveAttribute("href", "/profile#facts-title");
  });

  it("does not present existing facts as newly reviewable when the resume was already AI-analyzed", async () => {
    apiMocks.importCareerFile.mockResolvedValue({
      ...importResult,
      analysis_status: "already_ai_analyzed",
    });
    const user = userEvent.setup();
    await renderResumePage();
    await uploadAndAnalyze(user);

    expect(await screen.findByRole("heading", { name: "هذه السيرة محللة بالذكاء الاصطناعي مسبقًا" })).toBeVisible();
    expect(screen.getByText("لم نكرر التحليل أو ننشئ حقائق مكررة. افتح ملفك المهني لمراجعة النتائج الحالية وتعديلها.")).toBeVisible();
    expect(screen.queryByText("تحليل البيانات")).not.toBeInTheDocument();
    expect(screen.queryByText("بحاجة إلى مراجعة")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "افتح الحقائق وعدّلها" })).toHaveAttribute("href", "/profile#facts-title");
  });

  it("shows an honest localized fallback and profile link for the legacy duplicate conflict", async () => {
    const { ApiHttpError } = await import("@/lib/api-client");
    apiMocks.importCareerFile.mockRejectedValue(new ApiHttpError(
      409,
      "This file has already been imported",
      "resume_content_duplicate",
    ));
    const user = userEvent.setup();
    await renderResumePage();
    await uploadAndAnalyze(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("سبق استيراد الملف ولم يُحلل بالذكاء بعد.");
    expect(screen.queryByText("This file has already been imported")).not.toBeInTheDocument();
    expect(screen.getByText("resume.pdf")).toBeVisible();
    expect(screen.getByRole("link", { name: "افتح الحقائق وعدّلها" })).toHaveAttribute("href", "/profile#facts-title");

    await user.upload(screen.getByLabelText(/resume\.pdf/), new File(["other"], "other.pdf", { type: "application/pdf" }));
    expect(screen.getByText("other.pdf")).toBeVisible();
    expect(screen.queryByText("سبق استيراد الملف ولم يُحلل بالذكاء بعد.")).not.toBeInTheDocument();
  });

  it("branches questions by career stage and supports back, skip, and an undecided target", async () => {
    const user = userEvent.setup();
    await renderResumePage();
    await screen.findByRole("heading", { name: "كيف تبغى تبدأ؟" });
    await startGuidedInterview(user);

    expect(screen.getByRole("progressbar", { name: "تقدم مقابلة السيرة" })).toHaveAttribute("aria-valuenow", "2");
    expect(screen.queryByRole("button", { name: "تخطي هذا القسم" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));
    expect(screen.getByRole("textbox", { name: "الدرجة أو المؤهل" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "التخصص" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "الجامعة أو الجهة التعليمية" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "الحالة الدراسية" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "رجوع" }));
    expect(screen.getByRole("textbox", { name: "الدور أو المسمى المستهدف" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "رجوع" }));
    await user.click(screen.getByRole("radio", { name: "أغيّر مساري المهني" }));
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" }));
    expect(screen.getByRole("heading", { name: /المهارات القابلة للنقل/ })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "المسمى أو الدور" })).toBeVisible();
    expect(apiMocks.createResumeDraft).not.toHaveBeenCalled();
  });

  it("keeps stable select values when the interface switches from Arabic to English", async () => {
    const user = userEvent.setup();
    await renderResumePage();
    await startGuidedInterview(user, "خريج أو خريجة حديثًا");
    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));

    await user.type(screen.getByRole("textbox", { name: "الدرجة أو المؤهل" }), "Bachelor");
    await user.type(screen.getByRole("textbox", { name: "التخصص" }), "Information Systems");
    await user.type(screen.getByRole("textbox", { name: "الجامعة أو الجهة التعليمية" }), "King Saud University");
    const arabicStatus = screen.getByRole("combobox", { name: "الحالة الدراسية" });
    await user.selectOptions(arabicStatus, "graduated");
    expect(arabicStatus).toHaveValue("graduated");

    await user.click(screen.getByRole("button", { name: "en" }));

    const englishStatus = await screen.findByRole("combobox", { name: "Study status" });
    expect(englishStatus).toHaveValue("graduated");
    expect(screen.getByRole("option", { name: "Graduated" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Skip this section" })); // experience
    await user.click(screen.getByRole("button", { name: "Skip this section" })); // projects
    await user.type(screen.getByRole("textbox", { name: "Skill name" }), "Excel");
    await user.type(screen.getByRole("textbox", { name: "Usage example" }), "Built a weekly report");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Skip this section" })); // certifications
    await user.click(screen.getByRole("button", { name: "Skip this section" })); // achievements
    await user.click(screen.getByRole("button", { name: "Skip this section" })); // languages
    await user.click(screen.getByRole("checkbox", { name: /Separate consent for resume analysis/ }));
    await user.click(screen.getByRole("button", { name: "Build resume draft" }));

    await waitFor(() => expect(apiMocks.createResumeDraft).toHaveBeenCalledOnce());
    const [, payload] = apiMocks.createResumeDraft.mock.calls[0];
    expect(payload.content).toContain("Study status: Graduated");
    expect(payload.content).not.toContain("Study status: graduated");
  }, 15_000);

  it("adds and removes education entries while preserving their serialized order", async () => {
    const user = userEvent.setup();
    await renderResumePage();
    await startGuidedInterview(user, "خريج أو خريجة حديثًا");
    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));

    await user.type(screen.getByRole("textbox", { name: "الدرجة أو المؤهل" }), "المؤهل الأول");
    await user.type(screen.getByRole("textbox", { name: "التخصص" }), "التخصص الأول");
    await user.type(screen.getByRole("textbox", { name: "الجامعة أو الجهة التعليمية" }), "الجامعة الأولى");
    await user.selectOptions(screen.getByRole("combobox", { name: "الحالة الدراسية" }), "graduated");
    await user.click(screen.getByRole("button", { name: "إضافة مؤهل آخر" }));

    expect(screen.getByRole("textbox", { name: "الدرجة أو المؤهل 1" })).toHaveValue("المؤهل الأول");
    await user.type(screen.getByRole("textbox", { name: "الدرجة أو المؤهل 2" }), "المؤهل الثاني");
    await user.type(screen.getByRole("textbox", { name: "التخصص 2" }), "التخصص الثاني");
    await user.type(screen.getByRole("textbox", { name: "الجامعة أو الجهة التعليمية 2" }), "الجامعة الثانية");
    await user.selectOptions(screen.getByRole("combobox", { name: "الحالة الدراسية 2" }), "graduated");

    expect(screen.getAllByRole("button", { name: "حذف هذا السجل" })).toHaveLength(2);
    await user.click(screen.getAllByRole("button", { name: "حذف هذا السجل" })[0]);
    expect(screen.getByRole("textbox", { name: "الدرجة أو المؤهل" })).toHaveValue("المؤهل الثاني");
    expect(screen.queryByDisplayValue("المؤهل الأول")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "إضافة مؤهل آخر" }));
    await user.type(screen.getByRole("textbox", { name: "الدرجة أو المؤهل 2" }), "المؤهل الثالث");
    await user.type(screen.getByRole("textbox", { name: "التخصص 2" }), "التخصص الثالث");
    await user.type(screen.getByRole("textbox", { name: "الجامعة أو الجهة التعليمية 2" }), "الجامعة الثالثة");
    await user.selectOptions(screen.getByRole("combobox", { name: "الحالة الدراسية 2" }), "graduated");
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // experience
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // projects
    await user.type(screen.getByRole("textbox", { name: "اسم المهارة" }), "Excel");
    await user.type(screen.getByRole("textbox", { name: "مثال على استخدامها" }), "بنيت تقريرًا أسبوعيًا");
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // certifications
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // achievements
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // languages
    await user.click(screen.getByRole("checkbox", { name: /موافقة مستقلة لتحليل السيرة/ }));
    await user.click(screen.getByRole("button", { name: "ابنِ مسودة السيرة" }));

    await waitFor(() => expect(apiMocks.createResumeDraft).toHaveBeenCalledOnce());
    const [, payload] = apiMocks.createResumeDraft.mock.calls[0];
    expect(payload.content).not.toContain("المؤهل الأول");
    expect(payload.content).toContain("المؤهل الثاني التخصص الثاني");
    expect(payload.content).toContain("المؤهل الثالث التخصص الثالث");
    expect(payload.content.indexOf("المؤهل الثاني")).toBeLessThan(payload.content.indexOf("المؤهل الثالث"));
  }, 15_000);

  it("blocks completion until there is career evidence plus a skill example", async () => {
    const user = userEvent.setup();
    await renderResumePage();
    await startGuidedInterview(user, "لدي خبرة عملية");

    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // education
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // experience
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // projects
    await user.type(screen.getByRole("textbox", { name: "اسم المهارة" }), "Excel");
    await user.type(screen.getByRole("textbox", { name: "مثال على استخدامها" }), "بنيت تقريرًا أسبوعيًا");
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // certifications
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // achievements
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // languages

    expect(screen.getByRole("alert")).toHaveTextContent("معلومة مهنية مكتملة، ومهارة واحدة مع مثال استخدامها");
    expect(screen.queryByRole("checkbox", { name: /موافقة مستقلة/ })).not.toBeInTheDocument();
    expect(apiMocks.createResumeDraft).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "رجوع" }));
    await user.type(screen.getByRole("textbox", { name: "السياق أو التحدي" }), "التقرير كان يستغرق يومين");
    await user.type(screen.getByRole("textbox", { name: "وش سويت؟" }), "أنشأت قالبًا موحدًا");
    await user.type(screen.getByRole("textbox", { name: "النتيجة" }), "صار التقرير جاهزًا في نفس اليوم");
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" }));
    expect(await screen.findByRole("heading", { name: "إجاباتك جاهزة لبناء مسودة السيرة" })).toBeVisible();
  });

  it("accepts an optional project URL only when it uses http or https", async () => {
    const user = userEvent.setup();
    await renderResumePage();
    await startGuidedInterview(user, "خريج أو خريجة حديثًا");
    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // education
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // experience

    await user.type(screen.getByRole("textbox", { name: "اسم المشروع أو النشاط" }), "لوحة المبيعات");
    expect(screen.queryByRole("button", { name: "تخطي هذا القسم" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "الهدف أو المشكلة" }), "توضيح أداء الفروع");
    await user.type(screen.getByRole("textbox", { name: "دورك ومساهمتك" }), "جمعت البيانات وصممت المؤشرات");
    const link = screen.getByRole("textbox", { name: "الرابط (اختياري)" });
    await user.type(link, "example.com/project");

    expect(link).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("أدخل رابطًا صحيحًا يبدأ بـ http:// أو https://، أو اترك الحقل فارغًا.")).toHaveAttribute("role", "alert");
    expect(screen.getByRole("button", { name: "التالي" })).toBeDisabled();

    await user.clear(link);
    await user.type(link, "https://example.com/project");
    expect(link).not.toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText("أدخل رابطًا صحيحًا يبدأ بـ http:// أو https://، أو اترك الحقل فارغًا.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "التالي" })).toBeEnabled();
  });

  it("blocks completion when the serialized guided content exceeds 19,000 characters", async () => {
    const user = userEvent.setup();
    await renderResumePage();
    await startGuidedInterview(user, "لدي خبرة عملية");
    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // education

    for (let entryIndex = 1; entryIndex <= 10; entryIndex += 1) {
      const suffix = entryIndex === 1 ? "" : ` ${entryIndex}`;
      fireEvent.change(screen.getByRole("textbox", { name: `المسمى أو الدور${suffix}` }), { target: { value: "د".repeat(180) } });
      fireEvent.change(screen.getByRole("textbox", { name: `الجهة (أو اكتب سري)${suffix}` }), { target: { value: "ج".repeat(180) } });
      fireEvent.change(screen.getByRole("textbox", { name: `الفترة${suffix}` }), { target: { value: "ف".repeat(180) } });
      fireEvent.change(screen.getByRole("textbox", { name: `أبرز المسؤوليات (1–3 نقاط)${suffix}` }), { target: { value: "م".repeat(600) } });
      fireEvent.change(screen.getByRole("textbox", { name: `الإنجازات (اختياري)${suffix}` }), { target: { value: "ن".repeat(600) } });
      fireEvent.change(screen.getByRole("textbox", { name: `الأدوات المستخدمة (اختياري)${suffix}` }), { target: { value: "أ".repeat(180) } });
      if (entryIndex < 10) await user.click(screen.getByRole("button", { name: "إضافة خبرة أخرى" }));
    }

    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // projects
    await user.type(screen.getByRole("textbox", { name: "اسم المهارة" }), "Excel");
    fireEvent.change(screen.getByRole("textbox", { name: "مثال على استخدامها" }), { target: { value: "س".repeat(600) } });
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // certifications
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // achievements
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // languages

    expect(screen.getByRole("alert")).toHaveTextContent("المحتوى أطول من الحد المسموح (19,000 حرف). اختصر بعض الإجابات قبل بناء المسودة.");
    expect(screen.queryByRole("heading", { name: "إجاباتك جاهزة لبناء مسودة السيرة" })).not.toBeInTheDocument();
    expect(apiMocks.createResumeDraft).not.toHaveBeenCalled();
  }, 15_000);

  it("sends one labelled bilingual payload only after completion and separate consent", async () => {
    const user = userEvent.setup();
    await renderResumePage();

    await completeMinimalInterview(user, {
      target: "محلل بيانات",
      field: "التقنية المالية",
      environment: "فريق صغير",
      graduation: "2025",
      gpa: "4",
      gpaScale: "5",
      highlights: "مرتبة الشرف",
      skill: "Excel",
      skillSource: "مشروع لوحة المبيعات",
      skillExample: "نظفت 500 سجل وبنيت تقريرًا أسبوعيًا",
    });

    await user.type(screen.getByRole("textbox", { name: "البريد الإلكتروني" }), "hadi@example.com");
    await user.type(screen.getByRole("textbox", { name: "رقم الهاتف" }), "+966500000000");
    expect(apiMocks.createResumeDraft).not.toHaveBeenCalled();

    const submitButton = screen.getByRole("button", { name: "ابنِ مسودة السيرة" });
    expect(submitButton).toBeDisabled();
    expect(screen.getByText(/بيانات التواصل الاختيارية المخصصة للمعاينة لا تدخل في النص المرسل/)).toBeVisible();
    await user.click(screen.getByRole("checkbox", { name: /موافقة مستقلة لتحليل السيرة/ }));
    await user.click(submitButton);

    await waitFor(() => expect(apiMocks.createResumeDraft).toHaveBeenCalledOnce());
    const [, payload] = apiMocks.createResumeDraft.mock.calls[0];
    expect(payload.dataSharingAcknowledged).toBe(true);
    expect(payload.content).toContain("Context — Career stage / المرحلة المهنية: New graduate | خريج/خريجة حديثًا");
    expect(payload.content).toContain("Context — Target role / الهدف المهني: محلل بيانات — المجال: التقنية المالية؛ بيئة العمل المفضلة: فريق صغير");
    expect(payload.content).toContain("Evidence — Education / التعليم: بكالوريوس نظم معلومات — الجامعة أو الجهة التعليمية: جامعة الملك سعود؛ الحالة الدراسية: متخرج؛ سنة التخرج أو السنة المتوقعة: 2025؛ المعدل: 4 من 5؛ تكريم أو مواد بارزة: مرتبة الشرف");
    expect(payload.content).toContain("Evidence — Skills / المهارات: Excel — مصدر الدليل: مشروع لوحة المبيعات؛ مثال على استخدامها: نظفت 500 سجل وبنيت تقريرًا أسبوعيًا");
    expect(payload.content).not.toContain("hadi@example.com");
    expect(payload.content).not.toContain("+966500000000");
    expect(apiMocks.importCareerFile).not.toHaveBeenCalled();
  }, 15_000);

  it("omits a valid low GPA from AI payload while keeping independent education highlights", async () => {
    const user = userEvent.setup();
    await renderResumePage();
    await startGuidedInterview(user, "خريج أو خريجة حديثًا");
    await user.click(screen.getByRole("button", { name: "غير متأكد بعد" }));

    await user.type(screen.getByRole("textbox", { name: "الدرجة أو المؤهل" }), "بكالوريوس");
    await user.type(screen.getByRole("textbox", { name: "التخصص" }), "إدارة أعمال");
    await user.type(screen.getByRole("textbox", { name: "الجامعة أو الجهة التعليمية" }), "جامعة الملك سعود");
    await user.selectOptions(screen.getByRole("combobox", { name: "الحالة الدراسية" }), "graduated");
    await user.type(screen.getByRole("textbox", { name: "المعدل (اختياري)" }), "2.8");
    expect(screen.getByText("أكمل المعدل ومقياسه أو اتركهما فارغين")).toBeVisible();
    expect(screen.getByRole("button", { name: "التالي" })).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "مقياس المعدل (اختياري)" }), "5");
    await user.type(screen.getByRole("textbox", { name: "تكريم أو مواد بارزة (اختياري)" }), "مشروع مميز في ريادة الأعمال");
    expect(screen.getByText("لن نضيفه لأن المعدل أقل من حد العرض 80%")).toBeVisible();
    expect(screen.getByRole("button", { name: "التالي" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "التالي" }));

    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // experience
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" })); // projects
    await user.type(screen.getByRole("textbox", { name: "اسم المهارة" }), "التواصل");
    await user.type(screen.getByRole("textbox", { name: "مثال على استخدامها" }), "قدمت عرض مشروع التخرج أمام لجنة التحكيم");
    await user.click(screen.getByRole("button", { name: "التالي" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" }));
    await user.click(screen.getByRole("button", { name: "تخطي هذا القسم" }));
    await user.click(screen.getByRole("checkbox", { name: /موافقة مستقلة لتحليل السيرة/ }));
    await user.click(screen.getByRole("button", { name: "ابنِ مسودة السيرة" }));

    await waitFor(() => expect(apiMocks.createResumeDraft).toHaveBeenCalledOnce());
    const [, payload] = apiMocks.createResumeDraft.mock.calls[0];
    expect(payload.content).toContain("تكريم أو مواد بارزة: مشروع مميز في ريادة الأعمال");
    expect(payload.content).not.toContain("2.8");
    expect(payload.content).not.toContain("المعدل:");
  }, 15_000);

  it("renders a full review-only resume preview without claiming a final PDF", async () => {
    apiMocks.createResumeDraft.mockResolvedValue({
      ...importResult,
      facts: [
        {
          ...extractedFact,
          detail: null,
          source_excerpt: "Evidence — Skills / المهارات: استخدام Excel لبناء تقارير أسبوعية",
        },
        {
          ...extractedFact,
          id: "fact-2",
          category: "achievement",
          label: "خفض وقت إعداد التقرير إلى النصف",
          detail: null,
          source_excerpt: "Evidence — Achievements / الإنجازات: خفض وقت إعداد التقرير إلى النصف",
        },
      ],
    });
    const user = userEvent.setup();
    await renderResumePage();
    await completeMinimalInterview(user, { field: "التقنية المالية" });
    await user.type(screen.getByRole("textbox", { name: "البريد الإلكتروني" }), "hadi@example.com");
    await user.click(screen.getByRole("checkbox", { name: /موافقة مستقلة لتحليل السيرة/ }));
    await user.click(screen.getByRole("button", { name: "ابنِ مسودة السيرة" }));

    expect(await screen.findByText("معاينة مسودة السيرة")).toBeVisible();
    const [, payload] = apiMocks.createResumeDraft.mock.calls[0];
    expect(payload.content).toContain("Context — Target role / الهدف المهني: التقنية المالية");
    expect(screen.getByRole("heading", { name: "هادي الغانم" })).toBeVisible();
    expect(screen.getByText("الرياض")).toBeVisible();
    expect(screen.getAllByText("التقنية المالية").length).toBeGreaterThan(0);
    expect(screen.getByText("hadi@example.com")).toBeVisible();
    expect(screen.getByText("مسودة تحتاج مراجعة")).toBeVisible();
    expect(screen.getByText("استخدام Excel لبناء تقارير أسبوعية")).toBeVisible();
    expect(screen.queryByText("Evidence — Skills / المهارات: استخدام Excel لبناء تقارير أسبوعية")).not.toBeInTheDocument();
    expect(screen.getAllByText("خفض وقت إعداد التقرير إلى النصف")).toHaveLength(1);
    ["الملخص المهني", "التعليم", "الخبرة العملية", "المشاريع والتطوع", "المهارات", "الشهادات", "اللغات", "الإنجازات"].forEach((section) => {
      expect(screen.getByRole("heading", { name: section })).toBeVisible();
    });
    expect(screen.getByText("هذه ليست سيرة نهائية")).toBeVisible();
    expect(screen.getByText(/لم نؤكد أي حقيقة ولم ننشئ ملف PDF/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /تنزيل/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /راجع الحقائق وأكد الصحيح/ })).toHaveAttribute("href", "/profile");
  }, 15_000);

  it("shows provider readiness and never enables fake generation when AI is disabled", async () => {
    apiMocks.getCareerPathWorkspace.mockResolvedValue({ ...readyWorkspace, provider_ready: false, model: null });
    const user = userEvent.setup();
    await renderResumePage();

    expect(await screen.findByRole("heading", { name: "مساعد السيرة الذكي غير مفعّل" })).toBeVisible();
    expect(screen.getByText("لن نحلل أي مصدر ولن ننشئ نتيجة تجريبية حتى يُفعّل المزود على الخادم.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /ابنِ محتوى سيرتك من الصفر/ }));
    expect(screen.getByRole("radio", { name: "طالب أو طالبة" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "ابنِ مسودة السيرة" })).toBeDisabled();
    expect(apiMocks.createResumeDraft).not.toHaveBeenCalled();
  });

  it("creates the basic profile before loading provider details", async () => {
    apiMocks.getCareerProfile.mockResolvedValue(null);
    const user = userEvent.setup();
    await renderResumePage();

    expect(await screen.findByRole("heading", { name: "أنشئ ملفك الأساسي أولًا" })).toBeVisible();
    expect(apiMocks.getCareerPathWorkspace).not.toHaveBeenCalled();
    await user.type(screen.getByRole("textbox", { name: "الاسم الكامل" }), "هادي الغانم");
    await user.type(screen.getByRole("textbox", { name: "المدينة \(اختياري\)" }), "الرياض");
    await user.click(screen.getByRole("button", { name: "إنشاء الملف والمتابعة" }));

    await waitFor(() => expect(apiMocks.createCareerProfile).toHaveBeenCalledWith({
      fullName: "هادي الغانم",
      city: "الرياض",
      preferredLanguage: "ar",
    }));
    expect(await screen.findByRole("heading", { name: "كيف تبغى تبدأ؟" })).toBeVisible();
    expect(apiMocks.getCareerPathWorkspace).toHaveBeenCalledOnce();
  });
});
