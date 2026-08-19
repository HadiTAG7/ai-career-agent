import { render, screen } from "@testing-library/react";
import { DashboardWorkspace } from "@/app/dashboard/page";
import { LocaleProvider } from "@/lib/i18n";
import type { CareerPathWorkspace, DashboardData } from "@/lib/types";

const baseWorkspace: CareerPathWorkspace = {
  provider_ready: true,
  provider: "openai",
  model: "gpt-test",
  profile_id: "profile-1",
  confirmed_fact_count: 4,
  consent_required: false,
  conversation: null,
};

const dashboardData: DashboardData = {
  profileQualityPercent: 0,
  confirmedFacts: 0,
  totalFacts: 0,
  submittedApplications: 0,
  qualifiedInterviews: 0,
  interviewRate: null,
  actionsDue: 0,
  applicationStages: { saved: 0, ready: 0, applied: 0, interviews: 0 },
  topOpportunities: [],
};

describe("dashboard career path status", () => {
  it("routes the dashboard primary action through resume before path discovery", () => {
    const { rerender } = render(
      <LocaleProvider>
        <DashboardWorkspace data={dashboardData} careerPath={{ ...baseWorkspace, confirmed_fact_count: 0 }} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("link", { name: "جهّز سيرتك الذاتية" })).toHaveAttribute("href", "/resume");

    rerender(
      <LocaleProvider>
        <DashboardWorkspace data={{ ...dashboardData, confirmedFacts: 4, totalFacts: 4 }} careerPath={baseWorkspace} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("link", { name: "ابدأ اكتشاف مسارك" })).toHaveAttribute("href", "/career-path");

    rerender(
      <LocaleProvider>
        <DashboardWorkspace data={{ ...dashboardData, confirmedFacts: 4, totalFacts: 4 }} careerPath={{
          ...baseWorkspace,
          conversation: { id: "conversation-1", revision: 1, messages: [{ id: "m1", role: "user", content: "أحب التحليل", suggestions: [], model: null, created_at: "2026-08-07T10:00:00Z" }] },
        }} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("link", { name: "أكمل اكتشاف مسارك" })).toHaveAttribute("href", "/career-path");
  });
});
