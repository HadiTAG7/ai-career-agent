import { render, screen } from "@testing-library/react";
import { CareerPathStatusCard } from "@/components/career-path/career-path-status-card";
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

function renderCard(workspace: CareerPathWorkspace | null, unavailable = false) {
  return render(<LocaleProvider><CareerPathStatusCard connected workspace={workspace} unavailable={unavailable} /></LocaleProvider>);
}

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

  it("makes resume preparation the prerequisite when there are no confirmed facts", () => {
    renderCard({ ...baseWorkspace, confirmed_fact_count: 0 });
    expect(screen.getByRole("heading", { name: "الخطوة الأولى: جهّز سيرتك الذاتية" })).toBeVisible();
    expect(screen.getByRole("link", { name: /ابدأ بالسيرة الذاتية/ })).toHaveAttribute("href", "/resume");
  });

  it("makes path discovery the second step after resume facts are confirmed", () => {
    renderCard(baseWorkspace);
    expect(screen.getByRole("heading", { name: "الخطوة الثانية: اكتشف مسارك" })).toBeVisible();
    expect(screen.getByRole("link", { name: /ابدأ المحادثة/ })).toHaveAttribute("href", "/career-path");
  });

  it("shows in-progress and suggestion-ready states from real conversation data", () => {
    const { rerender } = renderCard({
      ...baseWorkspace,
      conversation: { id: "conversation-1", revision: 1, messages: [{ id: "m1", role: "user", content: "أحب التحليل", suggestions: [], model: null, created_at: "2026-08-07T10:00:00Z" }] },
    });
    expect(screen.getByRole("heading", { name: "محادثة اكتشاف المسار قيد التكوين" })).toBeVisible();

    rerender(
      <LocaleProvider>
        <CareerPathStatusCard connected workspace={{
          ...baseWorkspace,
          conversation: { id: "conversation-1", revision: 2, messages: [{ id: "m2", role: "assistant", content: "اقتراحات", model: "gpt-test", created_at: "2026-08-07T10:00:01Z", suggestions: [{ title: "محلل أعمال", why_fit: [], unknowns: [], seven_day_experiment: "جرّب", signal: "partial", evidence: [] }] }] },
        }} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("heading", { name: "1 مسارات تستحق المراجعة" })).toBeVisible();
    expect(screen.getByRole("link", { name: /راجع الاقتراحات/ })).toHaveAttribute("href", "/career-path");
  });

  it("fails closed when the workspace is unavailable", () => {
    renderCard(null, true);
    expect(screen.getByRole("heading", { name: "تعذر تحميل حالة مسارك" })).toBeVisible();
    expect(screen.getByText(/لن نعرض اقتراحات تجريبية/)).toBeVisible();
  });
});
