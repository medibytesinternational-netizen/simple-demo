import type { Color, Entities, Spanned } from "../api/types";

export type SpanKind = "drug" | "vital" | "symptom" | "allergy";

export interface HighlightSpan {
  start: number;
  end: number;
  color: Color;
  kind: SpanKind;
  label: string;
}

export interface TextPiece {
  text: string;
  span: HighlightSpan | null;
}

interface Labelled extends Spanned {
  color: Color;
}

function spansOf<T extends Labelled>(
  rows: readonly T[],
  kind: SpanKind,
  label: (row: T) => string,
): HighlightSpan[] {
  return rows
    .filter((r) => r.span_status === "exact")
    .map((r) => ({ start: r.start_char, end: r.end_char, color: r.color, kind, label: label(r) }));
}

/** Collect exact-offset spans from every entity list. Ambiguous / not_found spans are ignored. */
export function collectSpans(entities: Entities): HighlightSpan[] {
  return [
    ...spansOf(entities.drugs, "drug", (r) => r.name),
    ...spansOf(entities.vitals, "vital", (r) => r.text),
    ...spansOf(entities.symptoms, "symptom", (r) => r.text),
    ...spansOf(entities.allergies, "allergy", (r) => r.text),
  ];
}

/**
 * Split `text` into plain and highlighted pieces. Spans that are out of range,
 * empty, or overlap an earlier span are dropped so the output always covers the
 * text exactly once.
 */
export function splitBySpans(text: string, spans: readonly HighlightSpan[]): TextPiece[] {
  const valid = spans
    .filter(
      (s) =>
        Number.isInteger(s.start) &&
        Number.isInteger(s.end) &&
        s.start >= 0 &&
        s.end > s.start &&
        s.end <= text.length,
    )
    .sort((a, b) => a.start - b.start || b.end - a.end);

  const pieces: TextPiece[] = [];
  let cursor = 0;
  for (const span of valid) {
    if (span.start < cursor) continue;
    if (span.start > cursor) pieces.push({ text: text.slice(cursor, span.start), span: null });
    pieces.push({ text: text.slice(span.start, span.end), span });
    cursor = span.end;
  }
  if (cursor < text.length) pieces.push({ text: text.slice(cursor), span: null });
  return pieces;
}
