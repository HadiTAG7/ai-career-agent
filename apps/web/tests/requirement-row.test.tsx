import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RequirementRow } from "@/components/jobs/requirement-row";
import { demoJobs } from "@/lib/demo-data";
import { LocaleProvider } from "@/lib/i18n";

const requirement = demoJobs[0].requirements[0];

describe("RequirementRow", () => {
  it("reveals the evidence explanation on request", async () => {
    const user = userEvent.setup();
    render(<LocaleProvider><RequirementRow requirement={requirement} selected={false} onSelect={() => undefined} /></LocaleProvider>);

    await user.click(screen.getByRole("button", { name: "عرض تفسير المطابقة" }));

    expect(screen.getByText(requirement.explanation.ar)).toBeVisible();
  });

  it("shows review metadata instead of a false missing-evidence state before analysis", () => {
    render(
      <LocaleProvider>
        <RequirementRow requirement={requirement} reviewMode selected={false} onSelect={() => undefined} />
      </LocaleProvider>,
    );

    expect(screen.getByText("أساسي")).toBeVisible();
    expect(screen.getByText("مهارة")).toBeVisible();
    expect(screen.queryByText("لم يُعثر على دليل")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "مراجعة المتطلب" })).toBeVisible();
  });
});
