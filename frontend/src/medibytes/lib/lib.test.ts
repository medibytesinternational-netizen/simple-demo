import { describe, expect, it } from "vitest";
import { formatDose, formatPercent, formatSeconds } from "./format";
import { splitBySpans, type HighlightSpan } from "./highlight";
import { tokenizeJson } from "./jsonTokens";
import { validateUpload } from "./upload";

const span = (start: number, end: number): HighlightSpan => ({
  start,
  end,
  color: "GREEN",
  kind: "symptom",
  label: "x",
});

describe("splitBySpans", () => {
  it("covers the text exactly once, dropping overlapping and out-of-range spans", () => {
    const text = "fever and cough";
    const pieces = splitBySpans(text, [span(10, 15), span(0, 5), span(3, 8), span(14, 99), span(-1, 2)]);
    expect(pieces.map((p) => p.text).join("")).toBe(text);
    expect(pieces.filter((p) => p.span).map((p) => p.text)).toEqual(["fever", "cough"]);
  });
});

describe("tokenizeJson", () => {
  it("round-trips and classifies tokens", () => {
    const source = JSON.stringify({ a: "x: \"q\"", n: -1.5e3, t: true, z: null, l: [1, false] }, null, 2);
    const tokens = tokenizeJson(source);
    expect(tokens.map((t) => t.text).join("")).toBe(source);
    expect(tokens.find((t) => t.text === '"a"')?.type).toBe("key");
    expect(tokens.find((t) => t.text === '"x: \\"q\\""')?.type).toBe("string");
    expect(tokens.find((t) => t.text === "-1500")?.type).toBe("number");
    expect(tokens.find((t) => t.text === "true")?.type).toBe("boolean");
    expect(tokens.find((t) => t.text === "null")?.type).toBe("null");
  });
});

describe("validateUpload", () => {
  it("accepts every supported extension case-insensitively", () => {
    for (const name of ["a.wav", "a.MP3", "a.m4a", "a.mp4", "a.aac", "a.flac", "a.ogg", "a.webm"]) {
      expect(validateUpload({ name, size: 10 })).toBeNull();
    }
  });

  it("rejects bad extensions, empty and oversized files", () => {
    expect(validateUpload({ name: "a.txt", size: 10 })).toMatch(/not supported/);
    expect(validateUpload({ name: "noext", size: 10 })).toMatch(/not supported/);
    expect(validateUpload({ name: "a.wav", size: 0 })).toMatch(/empty/);
    expect(validateUpload({ name: "a.wav", size: 64 * 1024 * 1024 + 1 })).toMatch(/64 MB/);
  });
});

describe("format", () => {
  it("formats seconds, percentages and doses", () => {
    expect(formatSeconds(null)).toBe("");
    expect(formatSeconds(0.734)).toBe("0.7 s");
    expect(formatSeconds(21.4)).toBe("21 s");
    expect(formatSeconds(75.2)).toBe("1 min 15 s");
    expect(formatPercent(0.87)).toBe("87%");
    expect(formatDose(650, "mg")).toBe("650 mg");
    expect(formatDose(null, null)).toBe("");
  });
});
