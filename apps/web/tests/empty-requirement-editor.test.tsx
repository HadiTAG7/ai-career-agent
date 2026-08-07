import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EmptyRequirementEditor } from "@/components/jobs/empty-requirement-editor";

it("adds the first requirement to a saved job when extraction is empty", async () => {
  const onAdd = vi.fn(async () => undefined);
  const user = userEvent.setup();
  render(<EmptyRequirementEditor locale="ar" onAdd={onAdd} onBack={vi.fn()} />);

  await user.type(screen.getByRole("textbox", { name: "نص المتطلب" }), "خبرة في تحليل البيانات");
  await user.selectOptions(screen.getByRole("combobox", { name: "الفئة" }), "experience");
  await user.selectOptions(screen.getByRole("combobox", { name: "الأهمية" }), "preferred");
  await user.click(screen.getByRole("button", { name: "إضافة المتطلب" }));

  expect(onAdd).toHaveBeenCalledWith({
    text: "خبرة في تحليل البيانات",
    category: "experience",
    importance: "preferred",
    correctionReason: "Missing from automatic extraction",
  });
});
