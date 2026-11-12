import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Entities } from "../api/types";
import { loadResult } from "../test/fixtures";
import { ChartView } from "./ChartView";

function entities(): Entities {
  return loadResult().entities;
}

describe("ChartView", () => {
  it("lists drugs with status pill, dose and frequency", () => {
    render(<ChartView entities={entities()} />);
    const row = screen.getByRole("button", { name: /paracetamol/i });
    expect(within(row).getByText("RED")).toBeInTheDocument();
    expect(within(row).getByText("650 mg · twice daily")).toBeInTheDocument();
    expect(screen.getAllByText("No dose dictated")).toHaveLength(2);
  });

  it("tags negated drugs NOT GIVEN and allergens ALLERGEN", () => {
    const e = entities();
    const [first, second] = e.drugs;
    if (!first || !second) throw new Error("fixture needs two drugs");
    first.negated = true;
    second.allergen = true;
    render(<ChartView entities={e} />);
    expect(within(screen.getByRole("button", { name: /paracetamol/i })).getByText("NOT GIVEN")).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: /amoxicillin/i })).getByText("ALLERGEN")).toBeInTheDocument();
    expect(screen.getAllByText("NOT GIVEN")).toHaveLength(1);
  });

  it("expands a drug to show its provenance", async () => {
    const user = userEvent.setup();
    render(<ChartView entities={entities()} />);
    const toggle = screen.getByRole("button", { name: /paracetamol/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Shortlist shown to gpt-4.1")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(panel).not.toBeNull();
    const scope = within(panel as HTMLElement);
    expect(scope.getByText("piracetamol")).toBeInTheDocument(); // heard raw_token
    expect(scope.getByText("Matcher pick")).toBeInTheDocument();
    expect(scope.getByText("0.909")).toBeInTheDocument();
    expect(scope.getByText("0.900")).toBeInTheDocument();
    expect(scope.getByText("piracetam")).toBeInTheDocument();
    expect(scope.getByText("Ambiguous, sent for human review")).toBeInTheDocument();
    expect(scope.getByText("50% confidence")).toBeInTheDocument();
    expect(
      scope.getByText("both candidates are plausible at 650 mg and the sentence does not specify indication"),
    ).toBeInTheDocument();
    expect(scope.getByText("Piracetamol 650 mg twice daily.")).toBeInTheDocument();

    await user.click(toggle);
    expect(screen.queryByText("Shortlist shown to gpt-4.1")).not.toBeInTheDocument();
  });

  it("switches tabs and flags second-pass vitals", async () => {
    const user = userEvent.setup();
    render(<ChartView entities={entities()} />);
    await user.click(screen.getByRole("tab", { name: /vitals/i }));
    expect(screen.getByRole("tab", { name: /vitals/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Temperature 101 degrees Fahrenheit")).toBeInTheDocument();
    expect(screen.getByText("second pass")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /allergies/i }));
    expect(screen.getByText("No allergies dictated.")).toBeInTheDocument();
  });

  it("shows follow-up and hides an empty diagnosis", () => {
    render(<ChartView entities={entities()} />);
    expect(screen.getByText("Follow-up")).toBeInTheDocument();
    expect(screen.getByText("Follow up in three days")).toBeInTheDocument();
    expect(screen.queryByText("Diagnosis")).not.toBeInTheDocument();
  });
});
