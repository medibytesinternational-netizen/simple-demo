// What the consultation tab says about how the note was made: a banner when the AI model was
// unavailable, and the sections nobody spoke about.

import { Banner, Pill } from "../../components/ui";

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
        <Banner tone="warning" title="Prepared from documented rules">
          MediBytes Analysis was unavailable, so this note was prepared from documented rules and the transcript.
          {result.llm.fallback_reason ? <div className="small mt-1">{result.llm.fallback_reason}</div> : null}
        </Banner>
      ) : null}
      {missing.length ? (
        <Banner title="Not documented in this consultation">
          <div className="pill-row mt-1">
            {missing.map((section) => (
              <Pill key={section} tone="warning">{section}</Pill>
            ))}
          </div>
        </Banner>
      ) : null}
    </>
  );
}
