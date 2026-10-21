// What the consultation tab says about how the note was made: a banner when the AI model was
// unavailable, and the sections nobody spoke about.

export type ConsultLlmInfo = {
  mode?: string;
  model?: string;
  fallback?: boolean;
  fallback_reason?: string | null;
};

export type ConsultGenerateResult = {
  llm?: ConsultLlmInfo;
  draft?: { content?: { not_documented?: string[] } };
};

export function ConsultNoteStatus({ result }: { result: ConsultGenerateResult | null }) {
  if (!result) return null;
  const missing = result.draft?.content?.not_documented ?? [];
  return (
    <>
      {result.llm?.fallback ? (
        <div className="banner warning mt-3">
          The AI model was unavailable, so this note was written by rules from the transcript.
          {result.llm.fallback_reason ? <div className="small muted mt-1">{result.llm.fallback_reason}</div> : null}
        </div>
      ) : null}
      {missing.length ? (
        <div className="banner mt-3">
          Not documented in this consultation:
          <ul>
            {missing.map((section) => (
              <li key={section}>{section}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}
