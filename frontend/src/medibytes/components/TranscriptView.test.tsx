import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { loadResult } from "../test/fixtures";
import { TranscriptView } from "./TranscriptView";

describe("TranscriptView", () => {
  it("highlights only exact spans, coloured by row colour", () => {
    const { transcript, entities } = loadResult();
    const { container } = render(<TranscriptView transcript={transcript} entities={entities} />);
    const marks = Array.from(container.querySelectorAll("mark"));
    const texts = marks.map((m) => m.textContent);

    // exact spans from the real run
    expect(texts).toEqual([
      "cough",
      "vomiting",
      "Temperature 101 degrees Fahrenheit",
      "blood pressure 130/85",
      "pulse 92",
      "respiratory rate 22",
      "94% on room air",
      "clavulanic acid",
    ]);
    // "fever" is ambiguous and paracetamol / amoxicillin are not_found: never highlighted
    expect(texts).not.toContain("fever");
    expect(texts.some((t) => /piracetamol|amoxicilin/i.test(t ?? ""))).toBe(false);

    const clav = marks.find((m) => m.textContent === "clavulanic acid");
    expect(clav).toHaveAttribute("data-color", "RED");
    expect(marks.find((m) => m.textContent === "cough")).toHaveAttribute("data-color", "YELLOW");

    // highlighted text still reads as the full normalised transcript
    expect(screen.getByTestId("transcript-text").textContent).toBe(transcript.normalized_en);
  });

  it("ignores spans whose status is not exact even if offsets are present", () => {
    const { transcript, entities } = loadResult();
    for (const row of entities.vitals) row.span_status = "ambiguous";
    for (const row of entities.symptoms) row.span_status = "not_found";
    for (const row of entities.drugs) row.span_status = "ambiguous";
    const { container } = render(<TranscriptView transcript={transcript} entities={entities} />);
    expect(container.querySelectorAll("mark")).toHaveLength(0);
  });

  it("toggles to the raw ASR text without highlights", async () => {
    const user = userEvent.setup();
    const { transcript, entities } = loadResult();
    const { container } = render(<TranscriptView transcript={transcript} entities={entities} />);
    await user.click(screen.getByRole("button", { name: "Raw ASR" }));
    expect(screen.getByRole("button", { name: "Raw ASR" })).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelectorAll("mark")).toHaveLength(0);
    expect(screen.getByTestId("transcript-text").textContent).toBe(transcript.text);
  });
});
