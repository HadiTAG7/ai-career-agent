import { render, screen } from "@testing-library/react";
import { ApplicationStageRail } from "@/components/dashboard/application-stage-rail";
import { EvidenceProgress } from "@/components/dashboard/evidence-progress";
import { JobRow } from "@/components/dashboard/job-row";
import { demoJobs } from "@/lib/demo-data";
import { LocaleProvider } from "@/lib/i18n";

describe("connected dashboard components", () => {
  it("renders application stage counts supplied by the API mapping", () => {
    render(
      <LocaleProvider>
        <ApplicationStageRail counts={{ saved: 8, ready: 7, applied: 6, interviews: 5 }} />
      </LocaleProvider>,
    );

    for (const count of ["8", "7", "6", "5"]) expect(screen.getByText(count)).toBeVisible();
  });

  it("renders real evidence totals without demo-only profile claims", () => {
    render(
      <LocaleProvider>
        <EvidenceProgress data={{ profileQualityPercent: 25, confirmedFacts: 2, totalFacts: 5, actionsDue: 2 }} />
      </LocaleProvider>,
    );

    expect(screen.getByText("جودة ملفك 25%")).toBeVisible();
    expect(screen.getByText("2 إجراءات مستحقة")).toBeVisible();
    expect(screen.queryByText(/Google Data Analytics/i)).not.toBeInTheDocument();
    expect(screen.queryByText("ملفك موثّق بنسبة 82%")).not.toBeInTheDocument();
  });

  it("labels a real job without an analysis instead of claiming zero coverage", () => {
    render(
      <LocaleProvider>
        <JobRow job={{ ...demoJobs[0], id: "real-job", analysisId: undefined, coverage: 0, isDemo: false }} />
      </LocaleProvider>,
    );

    expect(screen.getByText("لم تُحلل")).toBeVisible();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
});
