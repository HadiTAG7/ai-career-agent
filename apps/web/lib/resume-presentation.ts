import type {
  ApiCareerFact,
  ApiCareerProfile,
  ApiResumeDraftContent,
  ApiResumeDraftItem,
  ApiResumeDraftSection,
  ApiResumeSectionKey,
} from "@/lib/api-client";

export const RESUME_PRESENTATION_ORDER: readonly ApiResumeSectionKey[] = [
  "education",
  "experience",
  "trading_experience",
  "certification",
  "skill",
  "language",
  "project",
  "achievement",
];

const SECTION_LABELS: Record<ApiResumeSectionKey, { ar: string; en: string }> = {
  education: { ar: "التعليم", en: "Education" },
  experience: { ar: "الخبرة الاحترافية", en: "Professional Experience" },
  trading_experience: { ar: "خبرة الاستثمار والتداول", en: "Investment & Trading Experience" },
  certification: { ar: "الشهادات", en: "Certifications" },
  skill: { ar: "المهارات", en: "Skills" },
  language: { ar: "اللغات", en: "Languages" },
  project: { ar: "المشاريع", en: "Projects" },
  achievement: { ar: "الإنجازات", en: "Achievements" },
};

const TRADING_SECTION_HEADINGS = new Set([
  "investment & trading experience",
  "investment and trading experience",
  "trading experience",
  "خبرة الاستثمار والتداول",
  "خبرة التداول",
]);

const GENERIC_DETAIL_HEADINGS = new Set([
  "skills",
  "financial skills",
  "technical skills",
  "data & technical",
  "data and technical",
  "soft skills",
  "languages",
  "certifications",
  "experience",
  "professional experience",
  "education",
  "المهارات",
  "المهارات المالية",
  "المهارات التقنية",
  "اللغات",
  "الشهادات",
  "الخبرة",
  "التعليم",
]);

function stringValue(fact: ApiCareerFact, ...keys: string[]) {
  for (const key of keys) {
    const value = fact.structured_value[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function stringList(fact: ApiCareerFact, key: string) {
  const value = fact.structured_value[key];
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    .map((item) => item.trim());
}

function courseworkValues(fact: ApiCareerFact) {
  const structured = stringList(fact, "coursework");
  if (structured.length || !fact.source_excerpt) return structured;
  const labels = new Set([
    "relevant courses",
    "relevant course",
    "relevant coursework",
    "coursework",
    "courses",
    "المقررات ذات الصلة",
    "المقررات الدراسية",
    "المقررات",
    "المواد ذات الصلة",
  ]);
  for (const line of fact.source_excerpt.split(/\r?\n/u)) {
    const match = line.match(/^\s*([^:：]+)\s*[:：]\s*(.+?)\s*$/u);
    if (!match || !labels.has(normalizedHeading(match[1]))) continue;
    return [...new Set(match[2].split(/\s*[,،]\s*/u).filter(Boolean))];
  }
  return [];
}

function normalizedHeading(value: string) {
  return value
    .normalize("NFKC")
    .trim()
    .replace(/[:：—–\-|]+$/u, "")
    .trim()
    .toLocaleLowerCase();
}

export function resumeSectionForFact(fact: ApiCareerFact): ApiResumeSectionKey | null {
  if (fact.category === "experience") {
    const sourceSection = stringValue(fact, "source_section")
      ?? fact.source_excerpt?.split(/\r?\n/u, 1)[0]
      ?? "";
    return TRADING_SECTION_HEADINGS.has(normalizedHeading(sourceSection))
      ? "trading_experience"
      : "experience";
  }
  if (
    fact.category === "education"
    || fact.category === "project"
    || fact.category === "skill"
    || fact.category === "certification"
    || fact.category === "language"
    || fact.category === "achievement"
  ) {
    return fact.category;
  }
  return null;
}

function factBullets(fact: ApiCareerFact) {
  const bullets = [
    ...stringList(fact, "responsibilities"),
    ...stringList(fact, "outcomes"),
  ];
  const honors = stringValue(fact, "honors");
  if (honors) bullets.push(honors);
  const gpaRecommended = fact.structured_value.gpa_display_recommended === true;
  const gpaScore = stringValue(fact, "gpa_score");
  const gpaScale = stringValue(fact, "gpa_scale");
  if (fact.category === "education" && gpaRecommended && gpaScore && gpaScale) {
    bullets.push("GPA: " + gpaScore + "/" + gpaScale);
  }
  const coursework = courseworkValues(fact);
  if (fact.category === "education" && coursework.length) {
    bullets.push("Relevant Coursework: " + coursework.join(", "));
  }
  if (bullets.length) return [...new Set(bullets)];

  const detail = fact.detail?.trim();
  const detailAlreadyPresented = (
    fact.category === "language" && Boolean(stringValue(fact, "proficiency"))
  ) || (
    fact.category === "certification" && Boolean(stringValue(fact, "issuer"))
  );
  if (
    detail
    && !detailAlreadyPresented
    && normalizedHeading(detail) !== normalizedHeading(fact.label)
    && !GENERIC_DETAIL_HEADINGS.has(normalizedHeading(detail))
  ) {
    return [detail];
  }
  return [];
}

function factOrganization(fact: ApiCareerFact) {
  if (fact.category === "education") return stringValue(fact, "institution");
  if (fact.category === "certification") return stringValue(fact, "issuer");
  if (fact.category === "language") return stringValue(fact, "proficiency");
  return stringValue(fact, "organization");
}

function factToDraftItem(fact: ApiCareerFact): ApiResumeDraftItem {
  return {
    id: fact.id,
    title: stringValue(fact, "title", "degree") ?? fact.label,
    organization: factOrganization(fact),
    date_range: stringValue(fact, "date_range"),
    location: stringValue(fact, "location"),
    bullets: factBullets(fact),
    evidence_handles: ["fact:" + fact.id],
  };
}

export function factsToResumeSections(
  language: "ar" | "en",
  facts: ApiCareerFact[],
): ApiResumeDraftSection[] {
  const grouped = new Map<ApiResumeSectionKey, ApiResumeDraftItem[]>();
  for (const fact of facts) {
    const sectionKey = resumeSectionForFact(fact);
    if (!sectionKey) continue;
    const items = grouped.get(sectionKey) ?? [];
    items.push(factToDraftItem(fact));
    grouped.set(sectionKey, items);
  }
  return RESUME_PRESENTATION_ORDER.flatMap((key) => {
    const items = grouped.get(key);
    return items?.length
      ? [{ key, title: SECTION_LABELS[key][language], items }]
      : [];
  });
}

export function buildFallbackResumeDraft(
  language: "ar" | "en",
  profile: ApiCareerProfile,
  facts: ApiCareerFact[],
): ApiResumeDraftContent {
  return {
    headline: profile.headline ?? (
      language === "ar" ? "عنوانك المهني" : "Your professional headline"
    ),
    professional_summary: language === "ar"
      ? "سيتكوّن ملخصك المهني هنا أثناء حديثنا. كل إجابة تؤكدها تضيف معنى أقوى إلى سيرتك."
      : "Your professional summary will take shape here as we talk. Every confirmed answer makes it stronger.",
    summary_evidence_handles: [],
    sections: factsToResumeSections(language, facts),
  };
}
