"use client";

import Link from "next/link";
import { CheckCircle2, ChevronLeft, ChevronRight, PencilLine, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import type { ApiCareerFact, ApiCareerProfile } from "@/lib/api-client";
import { cn } from "@/lib/utils";

export type CareerStage = "student" | "new_graduate" | "experienced" | "career_changer" | "freelancer";

export type GuidedResumeAnswers = {
  careerStage: CareerStage | "";
  targetRole: string;
  targetContext?: string;
  targetUndecided: boolean;
  education: string;
  experience: string;
  projects: string;
  skills: string;
  certifications: string;
  achievements: string;
  languages: string;
  localEmail: string;
  localPhone: string;
};

type EntryValues = Record<string, string>;
type EvidenceSectionKey = "education" | "experience" | "projects" | "skills" | "certifications" | "achievements" | "languages";
type StructuredSectionKey = "targetRole" | EvidenceSectionKey;

type StructuredResumeState = {
  careerStage: CareerStage | "";
  targetUndecided: boolean;
  targetRole: EntryValues;
  education: EntryValues[];
  experience: EntryValues[];
  projects: EntryValues[];
  skills: EntryValues[];
  certifications: EntryValues[];
  achievements: EntryValues[];
  languages: EntryValues[];
  localEmail: string;
  localPhone: string;
};

type StructuredField = {
  key: string;
  label: string;
  placeholder?: string;
  kind?: "text" | "textarea" | "url" | "select";
  options?: Array<{ label: string; value: string }>;
  wide?: boolean;
  minimumHint?: string;
};

type StructuredSection = {
  key: StructuredSectionKey;
  title: string;
  prompt: string;
  helper: string;
  fields: StructuredField[];
  titleFields: string[];
  addLabel?: string;
};

const EMPTY_STRUCTURED_STATE: StructuredResumeState = {
  careerStage: "",
  targetUndecided: false,
  targetRole: {},
  education: [{}],
  experience: [{}],
  projects: [{}],
  skills: [{}],
  certifications: [{}],
  achievements: [{}],
  languages: [{}],
  localEmail: "",
  localPhone: "",
};

function parseLocalizedNumber(value: string) {
  const arabicDigits = "٠١٢٣٤٥٦٧٨٩";
  const normalized = value
    .trim()
    .replace(/[٠-٩]/g, (digit) => String(arabicDigits.indexOf(digit)))
    .replace("٫", ".")
    .replace(",", ".");
  if (!normalized) return null;
  const number = Number(normalized);
  return Number.isFinite(number) ? number : null;
}

export function gpaDisplayDecision(gpaValue: string, scaleValue: string): "include" | "exclude" | "invalid" | "incomplete" {
  if (!gpaValue.trim() || !scaleValue.trim()) return "incomplete";
  const gpa = parseLocalizedNumber(gpaValue);
  const scale = parseLocalizedNumber(scaleValue);
  if (gpa === null || scale === null || scale <= 0 || gpa < 0 || gpa > scale) return "invalid";
  return gpa / scale >= 0.8 ? "include" : "exclude";
}

const stageLabels: Record<CareerStage, { ar: string; en: string; canonical: string }> = {
  student: { ar: "طالب أو طالبة", en: "Student", canonical: "Student | طالب/طالبة" },
  new_graduate: { ar: "خريج أو خريجة حديثًا", en: "New graduate", canonical: "New graduate | خريج/خريجة حديثًا" },
  experienced: { ar: "لدي خبرة عملية", en: "Experienced professional", canonical: "Experienced professional | محترف/محترفة ذو خبرة" },
  career_changer: { ar: "أغيّر مساري المهني", en: "Career changer", canonical: "Career changer | تغيير المسار المهني" },
  freelancer: { ar: "مستقل أو صاحب عمل حر", en: "Freelancer", canonical: "Freelancer | مستقل/صاحب عمل حر" },
};

const evidenceLabels: Record<EvidenceSectionKey, string> = {
  education: "Evidence — Education / التعليم",
  experience: "Evidence — Experience / الخبرة",
  projects: "Evidence — Projects and volunteering / المشاريع والتطوع",
  skills: "Evidence — Skills / المهارات",
  certifications: "Evidence — Certifications / الشهادات",
  achievements: "Evidence — Achievements / الإنجازات",
  languages: "Evidence — Languages / اللغات",
};

function localized(locale: "ar" | "en", ar: string, en: string) {
  return locale === "ar" ? ar : en;
}

function structuredSections(locale: "ar" | "en", stage: CareerStage | ""): StructuredSection[] {
  const text = (ar: string, en: string) => localized(locale, ar, en);
  const optional = text(" (اختياري)", " (optional)");
  const field = (
    key: string,
    arLabel: string,
    enLabel: string,
    placeholder?: { ar: string; en: string },
    extra: Partial<StructuredField> = {},
  ): StructuredField => ({
    key,
    label: text(arLabel, enLabel),
    placeholder: placeholder ? text(placeholder.ar, placeholder.en) : undefined,
    ...extra,
  });
  const select = (key: string, arLabel: string, enLabel: string, values: Array<[string, string, string]>) => field(
    key,
    arLabel,
    enLabel,
    undefined,
    { kind: "select", options: values.map(([value, ar, en]) => ({ label: text(ar, en), value })) },
  );
  const experiencePrompt = stage === "student"
    ? text("أضف تدريبًا أو عملًا جزئيًا أو نشاطًا مارست فيه مسؤولية.", "Add an internship, part-time role, or activity where you held responsibility.")
    : stage === "new_graduate"
      ? text("أضف تدريبك أو أول خبرة عملية، حتى لو كانت قصيرة.", "Add an internship or first work experience, even if it was brief.")
      : stage === "career_changer"
        ? text("أضف خبرة سابقة وركّز على المسؤوليات والمهارات القابلة للنقل.", "Add previous experience and focus on transferable responsibilities and skills.")
        : stage === "freelancer"
          ? text("أضف خدمة أو عملًا قدمته لعميل، ويمكن كتابة «سري» بدل اسم الجهة.", "Add work delivered to a client; you may write “Confidential” instead of the organization name.")
          : text("أضف خبرة عملية واحدة، ثم أضف خبرات أخرى عند الحاجة.", "Add one work experience, then add more when needed.");

  return [
    {
      key: "targetRole",
      title: text("الهدف المهني", "Career goal"),
      prompt: text("وش نوع الفرصة اللي تبي تستكشفها؟", "What kind of opportunity would you like to explore?"),
      helper: text("كل الحقول اختيارية، وتقدر تختار «غير متأكد بعد». هذا لا يثبت مسارك النهائي.", "Every field is optional, and you can choose “I am not sure yet.” This does not lock in your path."),
      titleFields: ["role"],
      fields: [
        field("role", "الدور أو المسمى المستهدف", "Target role", { ar: "مثال: محلل بيانات", en: "Example: Data analyst" }),
        field("field", "المجال", "Field", { ar: "مثال: التقنية المالية", en: "Example: Fintech" }),
        field("environment", "بيئة العمل المفضلة", "Preferred work environment", { ar: "مثال: فريق صغير، عمل ميداني، أو عن بُعد", en: "Example: Small team, field work, or remote" }, { wide: true }),
      ],
    },
    {
      key: "education",
      title: text("التعليم", "Education"),
      prompt: text("أضف مؤهلك أو دراستك الحالية", "Add your qualification or current study"),
      helper: text("المعدل اختياري، ولن يُرسل أو يظهر إلا إذا كان 80% فأعلى من مقياسه. التكريم والمواد البارزة مستقلة عنه.", "GPA is optional and is only sent or shown when it is at least 80% of its scale. Honors and coursework are handled separately."),
      titleFields: ["degree", "major"],
      addLabel: text("إضافة مؤهل آخر", "Add another qualification"),
      fields: [
        field("degree", "الدرجة أو المؤهل", "Degree or qualification", { ar: "مثال: بكالوريوس", en: "Example: Bachelor's" }),
        field("major", "التخصص", "Major", { ar: "مثال: نظم معلومات", en: "Example: Information Systems" }),
        field("institution", "الجامعة أو الجهة التعليمية", "Institution", { ar: "مثال: جامعة الملك سعود", en: "Example: King Saud University" }),
        select("status", "الحالة الدراسية", "Study status", [
          ["studying", "قيد الدراسة", "Currently studying"],
          ["graduated", "متخرج", "Graduated"],
          ["expected", "متوقع التخرج", "Expected to graduate"],
          ["incomplete", "دراسة غير مكتملة", "Not completed"],
        ]),
        field("graduation", "سنة التخرج أو السنة المتوقعة", "Graduation or expected year", { ar: "مثال: 2027", en: "Example: 2027" }),
        field("gpa", `المعدل${optional}`, `GPA${optional}`, { ar: "مثال: 4.2", en: "Example: 4.2" }),
        field("gpaScale", `مقياس المعدل${optional}`, `GPA scale${optional}`, { ar: "مثال: 5", en: "Example: 5" }),
        field("highlights", `تكريم أو مواد بارزة${optional}`, `Honors or relevant coursework${optional}`, { ar: "مثال: مرتبة الشرف، تحليل الأعمال", en: "Example: Honors, Business Analytics" }, { wide: true }),
      ],
    },
    {
      key: "experience",
      title: text("الخبرة العملية", "Experience"),
      prompt: experiencePrompt,
      helper: text("لا توجد خبرة رسمية؟ تخطَّ القسم؛ المشاريع والتطوع مفيدة أيضًا. لا نطلب سبب فجوة مهنية.", "No formal experience? Skip this section; projects and volunteering are useful too. We do not ask about career gaps."),
      titleFields: ["title"],
      addLabel: text("إضافة خبرة أخرى", "Add another experience"),
      fields: [
        field("title", "المسمى أو الدور", "Role or title", { ar: "مثال: متدرب تحليل بيانات", en: "Example: Data analysis intern" }),
        field("organization", "الجهة (أو اكتب سري)", "Organization (or write Confidential)", { ar: "مثال: شركة س", en: "Example: Company X" }),
        field("period", "الفترة", "Period", { ar: "مثال: يناير–مارس 2025", en: "Example: Jan–Mar 2025" }),
        field("responsibilities", "أبرز المسؤوليات (1–3 نقاط)", "Key responsibilities (1–3 points)", { ar: "مثال: إعداد تقارير أسبوعية؛ مراجعة جودة البيانات", en: "Example: Prepared weekly reports; checked data quality" }, { kind: "textarea", wide: true }),
        field("achievements", `الإنجازات${optional}`, `Achievements${optional}`, { ar: "مثال: اختصرت وقت إعداد التقرير", en: "Example: Reduced report preparation time" }, { kind: "textarea", wide: true }),
        field("tools", `الأدوات المستخدمة${optional}`, `Tools used${optional}`, { ar: "مثال: Excel، Power BI", en: "Example: Excel, Power BI" }, { wide: true }),
      ],
    },
    {
      key: "projects",
      title: text("المشاريع والتطوع", "Projects and volunteering"),
      prompt: text("أضف مشروعًا أو عملًا تطوعيًا يوضح قدراتك", "Add a project or volunteer experience that demonstrates your abilities"),
      helper: text("قد يكون مشروع جامعة، مشروعًا شخصيًا، فعالية، ناديًا، أو عملًا لجهة.", "This can be academic, personal, a club, an event, or work for an organization."),
      titleFields: ["name"],
      addLabel: text("إضافة مشروع أو تطوع آخر", "Add another project or volunteer entry"),
      fields: [
        field("name", "اسم المشروع أو النشاط", "Project or activity name", { ar: "مثال: لوحة متابعة المبيعات", en: "Example: Sales dashboard" }),
        select("kind", "النوع أو السياق", "Type or context", [
          ["academic", "مشروع جامعي", "Academic project"], ["personal", "مشروع شخصي", "Personal project"], ["volunteering", "تطوع", "Volunteering"], ["work", "مشروع عمل", "Work project"],
        ]),
        field("goal", "الهدف أو المشكلة", "Goal or problem", { ar: "مثال: توضيح أداء الفروع", en: "Example: Show branch performance" }, { wide: true }),
        field("contribution", "دورك ومساهمتك", "Your role and contribution", { ar: "مثال: جمعت البيانات وصممت المؤشرات", en: "Example: Collected data and designed metrics" }, { kind: "textarea", wide: true }),
        field("tools", `الأدوات${optional}`, `Tools${optional}`, { ar: "مثال: Power BI، SQL", en: "Example: Power BI, SQL" }),
        field("result", `النتيجة${optional}`, `Outcome${optional}`, { ar: "مثال: لوحة تفاعلية من 4 صفحات", en: "Example: Four-page interactive dashboard" }),
        field("link", `الرابط${optional}`, `Link${optional}`, { ar: "https://…", en: "https://…" }, { kind: "url", wide: true }),
      ],
    },
    {
      key: "skills",
      title: text("المهارات مع دليل", "Skills with evidence"),
      prompt: text("أضف مهارة واكتب مثالًا حقيقيًا لاستخدامها", "Add a skill and a real example of how you used it"),
      helper: text("لبناء مسودة مفيدة نحتاج مهارة واحدة على الأقل مع مثال. يمكنك إضافة مهارتين أو أكثر.", "A useful draft needs at least one skill with an example. You can add two or more."),
      titleFields: ["name"],
      addLabel: text("إضافة مهارة أخرى", "Add another skill"),
      fields: [
        field("name", "اسم المهارة", "Skill name", { ar: "مثال: Excel", en: "Example: Excel" }, { minimumHint: text("مطلوب للحد الأدنى", "Required for the minimum") }),
        select("kind", "نوع المهارة", "Skill type", [
          ["technical", "تقنية", "Technical"], ["tool", "أداة أو برنامج", "Tool or software"], ["domain", "معرفة مجال", "Domain knowledge"], ["soft", "مهارة ناعمة", "Soft skill"],
        ]),
        field("source", "مصدر الدليل", "Evidence source", { ar: "مثال: مشروع لوحة المبيعات", en: "Example: Sales dashboard project" }),
        field("example", "مثال على استخدامها", "Usage example", { ar: "مثال: نظفت 500 سجل وبنيت تقريرًا أسبوعيًا", en: "Example: Cleaned 500 records and built a weekly report" }, { kind: "textarea", wide: true, minimumHint: text("مطلوب للحد الأدنى", "Required for the minimum") }),
      ],
    },
    {
      key: "certifications",
      title: text("الشهادات والدورات", "Certifications and courses"),
      prompt: text("أضف شهادة أو دورة مرتبطة بالعمل", "Add a work-related certification or course"),
      helper: text("السنة والرابط اختياريان.", "Year and link are optional."),
      titleFields: ["name"],
      addLabel: text("إضافة شهادة أخرى", "Add another certification"),
      fields: [
        field("name", "اسم الشهادة أو الدورة", "Certification or course name", { ar: "مثال: Google Data Analytics", en: "Example: Google Data Analytics" }),
        field("issuer", "الجهة المانحة", "Issuer", { ar: "مثال: Coursera", en: "Example: Coursera" }),
        field("year", `السنة${optional}`, `Year${optional}`, { ar: "مثال: 2025", en: "Example: 2025" }),
        field("link", `رابط التحقق${optional}`, `Verification link${optional}`, { ar: "https://…", en: "https://…" }, { kind: "url", wide: true }),
      ],
    },
    {
      key: "achievements",
      title: text("الإنجازات", "Achievements"),
      prompt: text("حوّل إنجازك إلى سياق وفعل ونتيجة", "Describe an achievement through context, action, and outcome"),
      helper: text("الرقم اختياري تمامًا؛ لا تضف رقمًا غير متأكد منه.", "A metric is completely optional; do not add a number unless you are sure."),
      titleFields: ["context"],
      addLabel: text("إضافة إنجاز آخر", "Add another achievement"),
      fields: [
        field("context", "السياق أو التحدي", "Context or challenge", { ar: "مثال: إعداد التقرير كان يستغرق يومين", en: "Example: Reporting took two days" }),
        field("action", "وش سويت؟", "What did you do?", { ar: "مثال: أنشأت قالبًا وأتمتّ خطوات التنظيف", en: "Example: Created a template and automated cleanup" }, { wide: true }),
        field("result", "النتيجة", "Outcome", { ar: "مثال: صار التقرير جاهزًا في نفس اليوم", en: "Example: The report was ready the same day" }, { wide: true }),
        field("metric", `رقم أو مقياس${optional}`, `Metric${optional}`, { ar: "مثال: خفض الوقت 50%", en: "Example: Reduced time by 50%" }),
        field("year", `السنة${optional}`, `Year${optional}`, { ar: "مثال: 2025", en: "Example: 2025" }),
      ],
    },
    {
      key: "languages",
      title: text("اللغات", "Languages"),
      prompt: text("أضف لغة ومستواك واستخدامك الحقيقي لها", "Add a language, your level, and how you actually use it"),
      helper: text("اختر مستوى صادقًا بدون مبالغة.", "Choose an honest level without exaggeration."),
      titleFields: ["name"],
      addLabel: text("إضافة لغة أخرى", "Add another language"),
      fields: [
        field("name", "اللغة", "Language", { ar: "مثال: الإنجليزية", en: "Example: English" }),
        select("level", "المستوى", "Level", [
          ["native", "لغة أم", "Native"], ["fluent", "طليق", "Fluent"], ["advanced", "متقدم", "Advanced"], ["intermediate", "متوسط", "Intermediate"], ["basic", "أساسي", "Basic"],
        ]),
        field("usage", `الاستخدام${optional}`, `Usage${optional}`, { ar: "مثال: اجتماعات وقراءة تقارير", en: "Example: Meetings and reading reports" }, { wide: true }),
      ],
    },
  ];
}

function entryHasAnyValue(entry: EntryValues) {
  return Object.values(entry).some((value) => value.trim().length > 0);
}

function displayEntryValue(field: StructuredField, rawValue: string) {
  const value = rawValue.trim();
  if (field.kind !== "select") return value;
  return field.options?.find((option) => option.value === value)?.label ?? value;
}

function isValidOptionalHttpUrl(value: string) {
  const candidate = value.trim();
  if (!candidate) return true;
  try {
    const url = new URL(candidate);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function formatStructuredEntry(section: StructuredSection, entry: EntryValues, locale: "ar" | "en") {
  const gpaDecision = section.key === "education"
    ? gpaDisplayDecision(entry.gpa ?? "", entry.gpaScale ?? "")
    : "incomplete";
  const includedFields = section.fields.filter((field) => {
    if (!entry[field.key]?.trim()) return false;
    if (section.key === "education" && field.key === "gpaScale") return false;
    if (section.key === "education" && field.key === "gpa") return gpaDecision === "include";
    return true;
  });
  if (!includedFields.length) return "";

  const titleFieldKeys = new Set(section.titleFields);
  const titleValues = section.titleFields
    .map((key) => {
      const field = section.fields.find((candidate) => candidate.key === key);
      return field ? displayEntryValue(field, entry[key] ?? "") : entry[key]?.trim();
    })
    .filter(Boolean);
  let fallbackTitleKey = "";
  if (!titleValues.length) {
    fallbackTitleKey = includedFields[0].key;
    titleValues.push(displayEntryValue(includedFields[0], entry[fallbackTitleKey]));
  }
  const details = includedFields.flatMap((field) => {
    if (titleFieldKeys.has(field.key) || field.key === fallbackTitleKey) return [];
    const cleanLabel = field.label.replace(/\s*\((?:اختياري|optional)\)\s*$/iu, "");
    if (section.key === "education" && field.key === "gpa") {
      return [`${cleanLabel}: ${entry.gpa.trim()} ${locale === "ar" ? "من" : "of"} ${entry.gpaScale.trim()}`];
    }
    return [`${cleanLabel}: ${displayEntryValue(field, entry[field.key])}`];
  });
  const title = titleValues.join(" ");
  return details.length ? `${title} — ${details.join("؛ ")}` : title;
}

function buildStructuredAnswers(state: StructuredResumeState, sections: StructuredSection[], locale: "ar" | "en"): GuidedResumeAnswers {
  const definitions = new Map(sections.map((section) => [section.key, section]));
  const targetDefinition = definitions.get("targetRole");
  const targetRole = state.targetUndecided
    ? ""
    : ((state.targetRole.role ?? "").trim() || (state.targetRole.field ?? "").trim());
  const targetContext = !state.targetUndecided && targetDefinition
    ? formatStructuredEntry(targetDefinition, state.targetRole, locale)
    : "";
  const serializeEntries = (key: EvidenceSectionKey) => {
    const definition = definitions.get(key);
    if (!definition) return "";
    return state[key].map((entry) => formatStructuredEntry(definition, entry, locale)).filter(Boolean).join("\n");
  };
  return {
    careerStage: state.careerStage,
    targetRole,
    targetContext,
    targetUndecided: state.targetUndecided,
    education: serializeEntries("education"),
    experience: serializeEntries("experience"),
    projects: serializeEntries("projects"),
    skills: serializeEntries("skills"),
    certifications: serializeEntries("certifications"),
    achievements: serializeEntries("achievements"),
    languages: serializeEntries("languages"),
    localEmail: state.localEmail,
    localPhone: state.localPhone,
  };
}

function hasStructuredMinimum(state: StructuredResumeState) {
  const careerEvidence = [
    state.education.some((entry) => ["degree", "major", "institution"].some((key) => entry[key]?.trim())),
    state.experience.some((entry) => ["title", "organization", "responsibilities"].some((key) => entry[key]?.trim())),
    state.projects.some((entry) => ["name", "goal", "contribution"].some((key) => entry[key]?.trim())),
    state.achievements.some((entry) => ["context", "action", "result"].some((key) => entry[key]?.trim())),
  ].some(Boolean);
  const evidencedSkill = state.skills.some((entry) => entry.name?.trim() && entry.example?.trim());
  return careerEvidence && evidencedSkill;
}

const requiredEntryFields: Record<EvidenceSectionKey, string[]> = {
  education: ["degree", "major", "institution", "status"],
  experience: ["title", "organization", "period", "responsibilities"],
  projects: ["name", "goal", "contribution"],
  skills: ["name", "example"],
  certifications: ["name", "issuer"],
  achievements: ["context", "action", "result"],
  languages: ["name", "level"],
};

function entryIsComplete(sectionKey: EvidenceSectionKey, entry: EntryValues) {
  if (!entryHasAnyValue(entry)) return true;
  const requiredComplete = requiredEntryFields[sectionKey].every((key) => entry[key]?.trim());
  if (!requiredComplete) return false;
  if (!isValidOptionalHttpUrl(entry.link ?? "")) return false;
  if (sectionKey !== "education") return true;
  const hasAnyGpaValue = Boolean(entry.gpa?.trim() || entry.gpaScale?.trim());
  if (!hasAnyGpaValue) return true;
  return gpaDisplayDecision(entry.gpa ?? "", entry.gpaScale ?? "") !== "incomplete"
    && gpaDisplayDecision(entry.gpa ?? "", entry.gpaScale ?? "") !== "invalid";
}

function sectionIsComplete(state: StructuredResumeState, key: StructuredSectionKey) {
  if (key === "targetRole") return entryHasAnyValue(state.targetRole);
  return state[key].filter(entryHasAnyValue).every((entry) => entryIsComplete(key, entry));
}

function labelledLines(label: string, value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => `${label}: ${line}`);
}

export function buildGuidedResumeContent(answers: GuidedResumeAnswers) {
  if (!answers.careerStage) return "";
  const lines = [
    `Context — Career stage / المرحلة المهنية: ${stageLabels[answers.careerStage].canonical}`,
  ];
  const targetContext = answers.targetContext?.trim() || answers.targetRole.trim();
  if (!answers.targetUndecided && targetContext) {
    lines.push(...labelledLines("Context — Target role / الهدف المهني", targetContext));
  }
  (Object.keys(evidenceLabels) as EvidenceSectionKey[]).forEach((key) => {
    lines.push(...labelledLines(evidenceLabels[key], answers[key]));
  });
  return lines.join("\n");
}

const MAX_GUIDED_RESUME_CONTENT_LENGTH = 19_000;

type GuidedResumeInterviewProps = {
  locale: "ar" | "en";
  disabled: boolean;
  onComplete: (answers: GuidedResumeAnswers, content: string) => void;
  onInvalidate: () => void;
};

type StructuredEntryEditorProps = {
  section: StructuredSection;
  entry: EntryValues;
  index: number;
  totalEntries: number;
  locale: "ar" | "en";
  disabled: boolean;
  onChange: (fieldKey: string, value: string) => void;
  onRemove: () => void;
};

function StructuredEntryEditor({ section, entry, index, totalEntries, locale, disabled, onChange, onRemove }: StructuredEntryEditorProps) {
  const evidenceKey = section.key === "targetRole" ? null : section.key;
  const gpaDecision = evidenceKey === "education" ? gpaDisplayDecision(entry.gpa ?? "", entry.gpaScale ?? "") : "incomplete";
  const hasAnyGpaValue = Boolean(entry.gpa?.trim() || entry.gpaScale?.trim());
  const gpaMessage = !hasAnyGpaValue
    ? null
    : gpaDecision === "include"
      ? localized(locale, "سيظهر في المسودة", "It will appear in the draft")
      : gpaDecision === "exclude"
        ? localized(locale, "لن نضيفه لأن المعدل أقل من حد العرض 80%", "It will not be added because the GPA is below the 80% display threshold")
        : gpaDecision === "incomplete"
          ? localized(locale, "أكمل المعدل ومقياسه أو اتركهما فارغين", "Complete both GPA and scale, or leave both blank")
          : localized(locale, "تحقق من المعدل ومقياسه؛ يجب أن يكونا أرقامًا صحيحة والمعدل لا يتجاوز المقياس", "Check the GPA and scale; both must be valid numbers and GPA cannot exceed its scale");

  return (
    <fieldset className="rounded-xl border border-border bg-white p-4 sm:p-5" disabled={disabled}>
      <legend className="font-bold text-ink">
        {section.key === "targetRole"
          ? section.title
          : `${section.title} ${index + 1}`}
      </legend>
      {section.key !== "targetRole" && totalEntries > 1 ? (
        <div className="flex justify-end">
          <button type="button" className="text-xs font-semibold text-danger hover:underline" onClick={onRemove}>
            {localized(locale, "حذف هذا السجل", "Remove this entry")}
          </button>
        </div>
      ) : null}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {section.fields.map((field) => {
          const requiredForEntry = evidenceKey ? requiredEntryFields[evidenceKey].includes(field.key) : false;
          const accessibleLabel = totalEntries > 1 ? `${field.label} ${index + 1}` : field.label;
          const inputId = `guided-${section.key}-${index}-${field.key}`;
          const invalidUrl = field.kind === "url" && !isValidOptionalHttpUrl(entry[field.key] ?? "");
          const validationId = `${inputId}-validation`;
          return (
            <div key={field.key} className={field.wide ? "sm:col-span-2" : undefined}>
              <label className="field-label" htmlFor={inputId}>
                {field.label}{requiredForEntry ? " *" : ""}
                {field.minimumHint ? <span className="ms-1 text-xs font-normal text-emerald">({field.minimumHint})</span> : null}
              </label>
              {field.kind === "select" ? (
                <select
                  id={inputId}
                  aria-label={accessibleLabel}
                  aria-required={requiredForEntry}
                  className="field-control"
                  value={entry[field.key] ?? ""}
                  onChange={(event) => onChange(field.key, event.target.value)}
                >
                  <option value="">{localized(locale, "اختر", "Select")}</option>
                  {field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              ) : field.kind === "textarea" ? (
                <textarea
                  id={inputId}
                  aria-label={accessibleLabel}
                  aria-required={requiredForEntry}
                  className="field-control min-h-24 resize-y py-3"
                  value={entry[field.key] ?? ""}
                  maxLength={600}
                  placeholder={field.placeholder}
                  onChange={(event) => onChange(field.key, event.target.value)}
                />
              ) : (
                <input
                  id={inputId}
                  aria-label={accessibleLabel}
                  aria-required={requiredForEntry}
                  aria-invalid={invalidUrl || undefined}
                  aria-describedby={invalidUrl ? validationId : undefined}
                  className="field-control"
                  type={field.kind === "url" ? "url" : "text"}
                  inputMode={field.key === "gpa" || field.key === "gpaScale" ? "decimal" : undefined}
                  value={entry[field.key] ?? ""}
                  maxLength={field.kind === "url" ? 500 : 180}
                  placeholder={field.placeholder}
                  onChange={(event) => onChange(field.key, event.target.value)}
                />
              )}
              {invalidUrl ? (
                <p id={validationId} className="mt-1 text-xs font-semibold text-danger" role="alert">
                  {localized(locale, "أدخل رابطًا صحيحًا يبدأ بـ http:// أو https://، أو اترك الحقل فارغًا.", "Enter a valid URL starting with http:// or https://, or leave the field blank.")}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
      {gpaMessage ? (
        <p
          className={cn(
            "mt-4 rounded-lg border p-3 text-sm font-semibold",
            gpaDecision === "include" && "border-emerald bg-emerald-pale text-emerald-dark",
            gpaDecision === "exclude" && "border-amber bg-amber-pale text-amber",
            (gpaDecision === "invalid" || gpaDecision === "incomplete") && "border-danger bg-danger-pale text-danger",
          )}
          role={gpaDecision === "include" || gpaDecision === "exclude" ? "status" : "alert"}
        >
          {gpaMessage}
        </p>
      ) : null}
    </fieldset>
  );
}

export function GuidedResumeInterview({ locale, disabled, onComplete, onInvalidate }: GuidedResumeInterviewProps) {
  const [state, setState] = useState<StructuredResumeState>(() => ({
    ...EMPTY_STRUCTURED_STATE,
    targetRole: {},
    education: [{}],
    experience: [{}],
    projects: [{}],
    skills: [{}],
    certifications: [{}],
    achievements: [{}],
    languages: [{}],
  }));
  const [stepIndex, setStepIndex] = useState(0);
  const [completed, setCompleted] = useState(false);
  const [minimumWarning, setMinimumWarning] = useState(false);
  const [completionError, setCompletionError] = useState(false);
  const sections = useMemo(() => structuredSections(locale, state.careerStage), [locale, state.careerStage]);
  const totalSteps = sections.length + 1;
  const currentSection = stepIndex === 0 ? null : sections[stepIndex - 1];

  function commit(nextState: StructuredResumeState) {
    setState(nextState);
    setMinimumWarning(false);
    setCompletionError(false);
    onInvalidate();
  }

  function entriesFor(sectionKey: StructuredSectionKey) {
    return sectionKey === "targetRole" ? [state.targetRole] : state[sectionKey];
  }

  function updateEntry(sectionKey: StructuredSectionKey, index: number, fieldKey: string, value: string) {
    if (sectionKey === "targetRole") {
      commit({ ...state, targetUndecided: false, targetRole: { ...state.targetRole, [fieldKey]: value } });
      return;
    }
    commit({
      ...state,
      [sectionKey]: state[sectionKey].map((entry, entryIndex) => entryIndex === index ? { ...entry, [fieldKey]: value } : entry),
    });
  }

  function addEntry(sectionKey: EvidenceSectionKey) {
    commit({ ...state, [sectionKey]: [...state[sectionKey], {}] });
  }

  function removeEntry(sectionKey: EvidenceSectionKey, index: number) {
    commit({ ...state, [sectionKey]: state[sectionKey].filter((_, entryIndex) => entryIndex !== index) });
  }

  function advance(nextState = state) {
    if (stepIndex < totalSteps - 1) {
      setStepIndex((value) => value + 1);
      setMinimumWarning(false);
      return;
    }
    if (!hasStructuredMinimum(nextState)) {
      setMinimumWarning(true);
      return;
    }
    const answers = buildStructuredAnswers(nextState, sections, locale);
    const content = buildGuidedResumeContent(answers);
    if (content.length > MAX_GUIDED_RESUME_CONTENT_LENGTH) {
      setCompletionError(true);
      return;
    }
    setCompleted(true);
    onComplete(answers, content);
  }

  function skipCurrentSection() {
    if (!currentSection) return;
    const nextState = currentSection.key === "targetRole"
      ? { ...state, targetUndecided: false, targetRole: {} }
      : { ...state, [currentSection.key]: [{}] };
    commit(nextState);
    advance(nextState);
  }

  function chooseUndecidedTarget() {
    const nextState = { ...state, targetUndecided: true, targetRole: {} };
    commit(nextState);
    advance(nextState);
  }

  function editAnswers() {
    setCompleted(false);
    setCompletionError(false);
    setStepIndex(totalSteps - 1);
    onInvalidate();
  }

  function updateLocalContact(key: "localEmail" | "localPhone", value: string) {
    const nextState = { ...state, [key]: value };
    setState(nextState);
    const answers = buildStructuredAnswers(nextState, sections, locale);
    onComplete(answers, buildGuidedResumeContent(answers));
  }

  if (completed) {
    const answeredCount = sections
      .filter((section) => section.key !== "targetRole")
      .filter((section) => entriesFor(section.key).some(entryHasAnyValue)).length;
    return (
      <section className="rounded-xl border border-emerald bg-emerald-pale p-5" aria-labelledby="guided-resume-ready-title">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-emerald" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h3 id="guided-resume-ready-title" className="font-bold text-ink">
              {localized(locale, "إجاباتك جاهزة لبناء مسودة السيرة", "Your answers are ready for a resume draft")}
            </h3>
            <p className="mt-1 text-sm text-muted">
              {localized(locale, `جمّعنا ${answeredCount} أقسام مهنية. لن نرسلها حتى توافق وتضغط زر بناء المسودة.`, `We collected ${answeredCount} career sections. Nothing is sent until you consent and build the draft.`)}
            </p>
          </div>
        </div>
        <Button type="button" variant="secondary" className="mt-4" disabled={disabled} onClick={editAnswers}>
          <PencilLine className="h-4 w-4" aria-hidden="true" />
          {localized(locale, "تعديل الإجابات", "Edit answers")}
        </Button>
        <fieldset className="mt-5 border-t border-emerald/20 pt-5" disabled={disabled}>
          <legend className="font-bold text-ink">{localized(locale, "بيانات التواصل للمعاينة (اختياري)", "Preview contact details (optional)")}</legend>
          <p className="mt-1 text-xs text-muted">
            {localized(locale, "تبقى في هذه الصفحة فقط: لا تدخل في النص المرسل للمزوّد، ولا نحفظها في المتصفح.", "These stay on this page only: they are excluded from provider text and are not stored in the browser.")}
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <label className="field-label" htmlFor="guided-resume-local-email">{localized(locale, "البريد الإلكتروني", "Email")}</label>
              <input id="guided-resume-local-email" className="field-control" type="email" autoComplete="email" maxLength={254} value={state.localEmail} onChange={(event) => updateLocalContact("localEmail", event.target.value)} />
            </div>
            <div>
              <label className="field-label" htmlFor="guided-resume-local-phone">{localized(locale, "رقم الهاتف", "Phone")}</label>
              <input id="guided-resume-local-phone" className="field-control" type="tel" autoComplete="tel" maxLength={40} value={state.localPhone} onChange={(event) => updateLocalContact("localPhone", event.target.value)} />
            </div>
          </div>
        </fieldset>
      </section>
    );
  }

  const currentEntries = currentSection ? entriesFor(currentSection.key) : [];
  const currentHasValues = currentEntries.some(entryHasAnyValue);
  const currentComplete = currentSection ? sectionIsComplete(state, currentSection.key) : Boolean(state.careerStage);
  const partialEntry = currentHasValues && !currentComplete;

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-slate-50" aria-labelledby="guided-resume-section-title">
      <div className="border-b border-border bg-white px-4 py-4 sm:px-5">
        <div className="flex items-center justify-between gap-3 text-xs font-semibold text-muted">
          <span>{localized(locale, `القسم ${stepIndex + 1} من ${totalSteps}`, `Section ${stepIndex + 1} of ${totalSteps}`)}</span>
          <span>{Math.round(((stepIndex + 1) / totalSteps) * 100)}%</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-label={localized(locale, "تقدم مقابلة السيرة", "Resume interview progress")} aria-valuemin={1} aria-valuemax={totalSteps} aria-valuenow={stepIndex + 1}>
          <div className="h-full rounded-full bg-emerald transition-[width]" style={{ width: `${((stepIndex + 1) / totalSteps) * 100}%` }} />
        </div>
      </div>

      <div className="p-4 sm:p-6">
        {stepIndex === 0 ? (
          <fieldset disabled={disabled}>
            <legend id="guided-resume-section-title" className="text-xl font-bold text-ink">{localized(locale, "وين أنت الآن في رحلتك المهنية؟", "Where are you in your career journey?")}</legend>
            <p className="mt-2 text-sm text-muted">{localized(locale, "بنغيّر صياغة الأسئلة والأمثلة حسب اختيارك.", "We will tailor the wording and examples to your choice.")}</p>
            <div className="mt-5 grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label={localized(locale, "المرحلة المهنية", "Career stage")}>
              {(Object.keys(stageLabels) as CareerStage[]).map((stage) => (
                <button key={stage} type="button" role="radio" aria-checked={state.careerStage === stage} className={cn("min-h-16 rounded-lg border px-4 py-3 text-start text-sm font-semibold transition-colors", state.careerStage === stage ? "border-emerald bg-emerald-pale text-emerald-dark" : "border-border bg-white text-ink hover:border-slate-400")} onClick={() => commit({ ...state, careerStage: stage })}>
                  {stageLabels[stage][locale]}
                </button>
              ))}
            </div>
          </fieldset>
        ) : currentSection ? (
          <div>
            <p className="text-xs font-bold text-emerald">{currentSection.title}</p>
            <h3 id="guided-resume-section-title" className="mt-2 text-xl font-bold text-ink">{currentSection.prompt}</h3>
            <p className="mt-2 text-sm text-muted">{currentSection.helper}</p>
            {currentSection.key !== "targetRole" ? (
              <p className="mt-3 rounded-lg bg-white p-3 text-xs text-muted">
                {localized(locale, "الحقول المعلّمة * مطلوبة فقط إذا أضفت سجلًا في هذا القسم؛ تقدر تخطي القسم كاملًا. المعدل والأرقام اختيارية.", "Fields marked * are required only when you add an entry in this section; you may skip the whole section. GPA and metrics are optional.")}
              </p>
            ) : null}
            <div className="mt-5 space-y-4">
              {currentEntries.map((entry, index) => (
                <StructuredEntryEditor
                  key={`${currentSection.key}-${index}`}
                  section={currentSection}
                  entry={entry}
                  index={index}
                  totalEntries={currentEntries.length}
                  locale={locale}
                  disabled={disabled}
                  onChange={(fieldKey, value) => updateEntry(currentSection.key, index, fieldKey, value)}
                  onRemove={() => currentSection.key !== "targetRole" && removeEntry(currentSection.key as EvidenceSectionKey, index)}
                />
              ))}
            </div>
            {currentSection.key !== "targetRole" ? (
              <Button type="button" variant="secondary" className="mt-4" disabled={disabled || currentEntries.length >= 10 || !entryIsComplete(currentSection.key, currentEntries[currentEntries.length - 1]) || !entryHasAnyValue(currentEntries[currentEntries.length - 1])} onClick={() => addEntry(currentSection.key as EvidenceSectionKey)}>
                {currentSection.addLabel}
              </Button>
            ) : null}
            {partialEntry ? (
              <p className="mt-4 rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">
                {localized(locale, "أكمل الحقول المعلّمة * في كل سجل بدأته. وفي التعليم: أكمل المعدل ومقياسه أو اتركهما فارغين.", "Complete the fields marked * in every entry you started. For education, complete both GPA and scale or leave both blank.")}
              </p>
            ) : null}
          </div>
        ) : null}

        <div className="mt-5 rounded-lg border border-emerald/30 bg-emerald-pale p-3 text-xs text-muted">
          {localized(locale, "الحد الأدنى لبناء المسودة: تعليم أو خبرة أو مشروع أو إنجاز مكتمل، مع مهارة واحدة ومثال حقيقي لاستخدامها.", "Minimum for a draft: one complete education, experience, project, or achievement entry, plus one skill with a real usage example.")}
        </div>

        {minimumWarning ? (
          <p className="mt-4 rounded-lg border border-amber bg-amber-pale p-3 text-sm text-amber" role="alert">
            {localized(locale, "ارجع وأضف معلومة مهنية مكتملة، ومهارة واحدة مع مثال استخدامها، قبل بناء المسودة.", "Go back and add one complete career entry plus one skill with a usage example before building the draft.")}
          </p>
        ) : null}

        {completionError ? (
          <p className="mt-4 rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">
            {localized(locale, "المحتوى أطول من الحد المسموح (19,000 حرف). اختصر بعض الإجابات قبل بناء المسودة.", "The content exceeds the 19,000-character limit. Shorten some answers before building the draft.")}
          </p>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center gap-3">
          {stepIndex > 0 ? (
            <Button type="button" variant="secondary" disabled={disabled} onClick={() => { setStepIndex((value) => value - 1); setMinimumWarning(false); }}>
              {locale === "ar" ? <ChevronRight className="h-4 w-4" aria-hidden="true" /> : <ChevronLeft className="h-4 w-4" aria-hidden="true" />}
              {localized(locale, "رجوع", "Back")}
            </Button>
          ) : null}
          {currentSection && currentSection.key !== "targetRole" && !currentHasValues ? <Button type="button" variant="ghost" disabled={disabled} onClick={skipCurrentSection}>{localized(locale, "تخطي هذا القسم", "Skip this section")}</Button> : null}
          {currentSection?.key === "targetRole" ? <Button type="button" variant="secondary" disabled={disabled} onClick={chooseUndecidedTarget}>{localized(locale, "غير متأكد بعد", "I am not sure yet")}</Button> : null}
          <Button type="button" className="ms-auto" disabled={disabled || (stepIndex === 0 ? !state.careerStage : !currentHasValues || !currentComplete)} onClick={() => advance()}>
            {stepIndex === totalSteps - 1 ? <Sparkles className="h-4 w-4" aria-hidden="true" /> : null}
            {stepIndex === totalSteps - 1 ? localized(locale, "إنهاء المقابلة", "Finish interview") : localized(locale, "التالي", "Next")}
            {stepIndex < totalSteps - 1 ? (locale === "ar" ? <ChevronLeft className="h-4 w-4" aria-hidden="true" /> : <ChevronRight className="h-4 w-4" aria-hidden="true" />) : null}
          </Button>
        </div>
      </div>
    </section>
  );
}

const previewSections = [
  { key: "education", ar: "التعليم", en: "Education" },
  { key: "experience", ar: "الخبرة العملية", en: "Experience" },
  { key: "project", ar: "المشاريع والتطوع", en: "Projects and volunteering" },
  { key: "skill", ar: "المهارات", en: "Skills" },
  { key: "certification", ar: "الشهادات", en: "Certifications" },
  { key: "language", ar: "اللغات", en: "Languages" },
  { key: "achievement", ar: "الإنجازات", en: "Achievements" },
] as const;

type ResumePreviewProps = {
  locale: "ar" | "en";
  profile: ApiCareerProfile;
  answers: GuidedResumeAnswers;
  facts: ApiCareerFact[];
};

function previewFactDetail(fact: ApiCareerFact) {
  const rawDetail = (fact.detail || fact.source_excerpt || "").trim();
  const withoutCanonicalPrefix = rawDetail.replace(/^(?:Context|Evidence)\s+—\s+[^:]+:\s*/u, "").trim();
  return withoutCanonicalPrefix && withoutCanonicalPrefix !== fact.label.trim() ? withoutCanonicalPrefix : "";
}

export function ResumePreview({ locale, profile, answers, facts }: ResumePreviewProps) {
  const target = answers.targetUndecided ? "" : answers.targetRole.trim();
  const highlights = facts.slice(0, 2).map((fact) => fact.label).filter(Boolean);
  const summary = locale === "ar"
    ? target
      ? `يسعى إلى فرصة في ${target}. ${highlights.length ? `ومن أبرز المعلومات المدخلة: ${highlights.join("، ")}.` : "تُستكمل نقاط القوة بعد مراجعة الحقائق المستخرجة."}`
      : highlights.length
        ? `مسودة مهنية أولية مبنية على المعلومات المدخلة، ومن أبرزها: ${highlights.join("، ")}.`
        : "مسودة مهنية أولية تُستكمل بعد مراجعة المعلومات المدخلة."
    : target
      ? `Seeking an opportunity in ${target}. ${highlights.length ? `Entered highlights include: ${highlights.join(", ")}.` : "Strengths will be completed after the extracted facts are reviewed."}`
      : highlights.length
        ? `An initial professional draft based on the entered information, including: ${highlights.join(", ")}.`
        : "An initial professional draft to be completed after reviewing the entered information.";

  return (
    <section className="mt-7 overflow-hidden rounded-xl border border-emerald bg-white" aria-labelledby="resume-preview-title" aria-live="polite">
      <header className="border-b border-border bg-emerald-pale p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p id="resume-preview-title" className="text-xs font-bold uppercase tracking-wide text-emerald">
              {locale === "ar" ? "معاينة مسودة السيرة" : "Resume draft preview"}
            </p>
            <h2 className="mt-2 text-2xl font-bold text-ink">{profile.full_name}</h2>
            {profile.city ? <p className="mt-1 text-sm text-muted">{profile.city}</p> : null}
            {answers.localEmail || answers.localPhone ? (
              <p className="mt-2 text-sm text-muted">
                {[answers.localEmail, answers.localPhone].filter(Boolean).join(" · ")}
              </p>
            ) : null}
            {target ? <p className="mt-3 font-semibold text-emerald-dark">{target}</p> : null}
          </div>
          <span className="rounded-full border border-amber bg-amber-pale px-3 py-1.5 text-xs font-bold text-amber">
            {locale === "ar" ? "مسودة تحتاج مراجعة" : "Draft — review required"}
          </span>
        </div>
      </header>

      <div className="p-5 sm:p-6">
        <section aria-labelledby="resume-summary-title">
          <h3 id="resume-summary-title" className="text-lg font-bold text-ink">{locale === "ar" ? "الملخص المهني" : "Professional summary"}</h3>
          <p className="mt-2 text-sm leading-7 text-muted">{summary}</p>
        </section>

        <div className="mt-6 grid gap-6 md:grid-cols-2">
          {previewSections.map((section) => {
            const sectionFacts = facts.filter((fact) => fact.category === section.key);
            return (
              <section key={section.key} className="border-t border-border pt-4" aria-labelledby={`resume-preview-${section.key}`}>
                <h3 id={`resume-preview-${section.key}`} className="font-bold text-ink">{section[locale]}</h3>
                {sectionFacts.length ? (
                  <ul className="mt-3 space-y-3">
                    {sectionFacts.map((fact) => {
                      const detail = previewFactDetail(fact);
                      return (
                        <li key={fact.id}>
                          <p className="text-sm font-semibold text-ink">{fact.label}</p>
                          {detail ? <p className="mt-1 whitespace-pre-wrap text-sm text-muted">{detail}</p> : null}
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="mt-2 text-sm text-muted">{locale === "ar" ? "لم تُستخرج معلومات لهذا القسم بعد." : "No information has been extracted for this section yet."}</p>
                )}
              </section>
            );
          })}
        </div>

        <div className="mt-7 rounded-lg border border-amber bg-amber-pale p-4 text-sm text-muted">
          <strong className="block text-ink">{locale === "ar" ? "هذه ليست سيرة نهائية" : "This is not a final resume"}</strong>
          <p className="mt-1">
            {locale === "ar"
              ? "هذه معاينة محتوى فقط. لم نؤكد أي حقيقة ولم ننشئ ملف PDF؛ راجع الحقائق وصححها ثم أكد الصحيح بنفسك."
              : "This is a content preview only. No fact was confirmed and no PDF was created; review, correct, and confirm accurate facts yourself."}
          </p>
        </div>

        <Link href="/profile" className="mt-5 inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald px-5 text-sm font-semibold text-white hover:bg-emerald-dark">
          {locale === "ar" ? "راجع الحقائق وأكد الصحيح" : "Review facts and confirm what is accurate"}
          {locale === "ar" ? <ChevronLeft className="h-4 w-4" aria-hidden="true" /> : <ChevronRight className="h-4 w-4" aria-hidden="true" />}
        </Link>
      </div>
    </section>
  );
}
