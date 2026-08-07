import { readApplications, updateApplicationStage } from "@/lib/local-store";

describe("application local store", () => {
  it("updates a user-confirmed application stage", () => {
    const seeded = readApplications();
    const updated = updateApplicationStage(seeded[0].id, "applied");

    expect(updated.find((item) => item.id === seeded[0].id)?.stage).toBe("applied");
    expect(JSON.parse(window.localStorage.getItem("ai-career-agent:applications:v1") ?? "[]")).toHaveLength(updated.length);
  });
});
