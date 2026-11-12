import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { DischargeNote } from "../api/types";
import { loadResult } from "../test/fixtures";
import { DischargeNoteView } from "./DischargeNoteView";

function note(): DischargeNote {
  return loadResult().discharge;
}

const TITLES = [
  "Present illness",
  "Examination findings",
  "Previous diagnosis",
  "Plan of management",
  "Diet instructions",
  "General instructions",
];

describe("DischargeNoteView", () => {
  it("renders all six sections with friendly titles in order", () => {
    render(<DischargeNoteView note={note()} />);
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(TITLES);
  });

  it("shows each item with its verification badge, confidence and heard-as sentence", () => {
    render(<DischargeNoteView note={note()} />);
    const plan = screen.getByRole("region", { name: "Plan of management" });
    const item = within(plan).getByText("Paracetamol 650 mg twice daily.").closest("li");
    expect(item).not.toBeNull();
    const scope = within(item as HTMLElement);
    expect(scope.getByText("Verified")).toBeInTheDocument();
    expect(scope.getByText("70% confidence")).toBeInTheDocument();
    expect(scope.getByText("Piracetamol 650 mg twice daily.")).toBeInTheDocument();
    expect(within(plan).getAllByText("Needs review").length).toBeGreaterThan(0);
  });

  it("shows a clear empty state for sections with nothing dictated", () => {
    const n = note();
    n.sections.diet_instructions.items = [];
    render(<DischargeNoteView note={n} />);
    const diet = screen.getByRole("region", { name: "Diet instructions" });
    expect(within(diet).getByText("Nothing dictated")).toBeInTheDocument();
    const general = screen.getByRole("region", { name: "General instructions" });
    expect(within(general).queryByText("Nothing dictated")).not.toBeInTheDocument();
  });

  it("flags a section that was dictated but not written", () => {
    const n = note();
    n.sections.diet_instructions.items = [];
    n.provenance = { ...n.provenance, coverage: { missing: ["diet_instructions"], dictated: { diet_instructions: 1 } } };
    render(<DischargeNoteView note={n} />);
    expect(screen.getByText("Missing sections").nextElementSibling).toHaveTextContent("Diet instructions");
    const diet = screen.getByRole("region", { name: "Diet instructions" });
    expect(within(diet).getByText("Spoken but not written")).toBeInTheDocument();
    expect(within(diet).queryByText("Nothing dictated")).not.toBeInTheDocument();
  });

  it("lists the dictated parts that were not written", () => {
    const n = note();
    n.provenance = {
      ...n.provenance,
      coverage: {
        source: "analysis",
        missing: [],
        unused: { general_instructions: ["check the aquity index before the exercising"] },
      },
    };
    render(<DischargeNoteView note={n} />);
    expect(screen.getByText("1 dictated part not written in the note")).toBeInTheDocument();
    expect(screen.getByText(/check the aquity index before the exercising/)).toBeInTheDocument();
  });

  it("copies the raw discharge JSON to the clipboard", async () => {
    const user = userEvent.setup();
    const n = note();
    render(<DischargeNoteView note={n} />);
    await user.click(screen.getByRole("button", { name: /copy json/i }));
    const copied = await navigator.clipboard.readText();
    expect(JSON.parse(copied)).toEqual(n);
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("shows provenance, including an INVALID schema", () => {
    const n = note();
    n.provenance = { ...n.provenance, schema: "INVALID", schema_error: "missing diet_instructions" };
    render(<DischargeNoteView note={n} />);
    expect(screen.getByText("INVALID")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("missing diet_instructions");
    expect(screen.getByText("llm:gpt-4.1")).toBeInTheDocument();
    expect(screen.getByText("Dropped unproven")).toBeInTheDocument();
  });
});
