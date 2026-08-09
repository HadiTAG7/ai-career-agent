import { describe, expect, it } from "vitest";
import type { ApiCareerFact, ApiCareerProfile } from "@/lib/api-client";
import {
  buildFallbackResumeDraft,
  factsToResumeSections,
} from "@/lib/resume-presentation";

function fact(
  id: string,
  category: string,
  label: string,
  structuredValue: Record<string, unknown>,
  detail: string | null = null,
  sourceExcerpt: string | null = null,
): ApiCareerFact {
  return {
    id,
    source_id: "source-1",
    category,
    label,
    detail,
    verification_status: "confirmed",
    source_excerpt: sourceExcerpt,
    extraction_confidence: 0.99,
    structured_value: structuredValue,
    created_at: "2026-08-09T00:00:00Z",
  };
}

const profile: ApiCareerProfile = {
  id: "profile-1",
  full_name: "Synthetic Candidate",
  city: "Riyadh",
  preferred_language: "en",
  headline: "Finance Professional",
  completed_fact_categories: [],
};

describe("resume presentation", () => {
  it("uses the requested source order and keeps trading experience separate", () => {
    const sections = factsToResumeSections("en", [
      fact("skill-1", "skill", "Financial Analysis", {}, "Financial Skills"),
      fact("language-1", "language", "English", { proficiency: "Fluent" }),
      fact("trade-1", "experience", "Independent Trader", {
        source_section: "Investment & Trading Experience",
        date_range: "2019 – Present",
        responsibilities: ["Tested strategies across 6 market regimes"],
      }),
      fact("work-1", "experience", "Finance Analyst", {
        source_section: "Professional Experience",
        organization: "Northstar",
        responsibilities: [
          "Reconciled 48 monthly reports",
          "Reduced review time by 9%",
        ],
      }, "Northstar; Reconciled 48 monthly reports; Reduced review time by 9%"),
      fact("cert-1", "certification", "CME-1", { issuer: "Synthetic Institute" }),
      fact("education-1", "education", "Bachelor of Finance", {
        institution: "Synthetic University",
        gpa_score: "3.6",
        gpa_scale: "4",
        gpa_display_recommended: true,
      }, null, "Education\nRelevant Courses: Auditing, Risk Management"),
    ]);

    expect(sections.map((section) => section.key)).toEqual([
      "education",
      "experience",
      "trading_experience",
      "certification",
      "skill",
      "language",
    ]);
    expect(sections[1].items[0].bullets).toEqual([
      "Reconciled 48 monthly reports",
      "Reduced review time by 9%",
    ]);
    expect(sections[2].items[0].bullets).toEqual([
      "Tested strategies across 6 market regimes",
    ]);
    expect(sections[0].items[0].organization).toBe("Synthetic University");
    expect(sections[0].items[0].bullets).toEqual([
      "GPA: 3.6/4",
      "Relevant Coursework: Auditing, Risk Management",
    ]);
    expect(sections[4].items[0].bullets).toEqual([]);
    expect(sections[5].items[0].organization).toBe("Fluent");
  });

  it("builds the fallback draft from the same complete section model", () => {
    const draft = buildFallbackResumeDraft("en", profile, [
      fact("work-1", "experience", "Finance Analyst", {
        responsibilities: ["Prepared 8 monthly forecasts"],
      }),
      fact("education-1", "education", "Bachelor of Finance", {
        institution: "Synthetic University",
      }),
    ]);

    expect(draft.sections.map((section) => section.key)).toEqual([
      "education",
      "experience",
    ]);
    expect(draft.sections[1].items[0].bullets).toEqual([
      "Prepared 8 monthly forecasts",
    ]);
  });
});
