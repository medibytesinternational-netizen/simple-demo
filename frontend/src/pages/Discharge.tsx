import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../api";
import type { Draft } from "../types";
import { DraftReview } from "../components/DraftReview";

type Readiness = {
  items: { key: string; label: string; present: boolean; source: string }[];
  ready: boolean;
  already_signed: boolean;
  encounter_status: string;
};

export function DischargePage() {
  const queryClient = useQueryClient();
  const readiness = useQuery<Readiness>({ queryKey: ["discharge-readiness"], queryFn: () => get("/discharge/readiness") });
  const drafts = useQuery<{ drafts: Draft[] }>({
    queryKey: ["drafts", "F9"],
    queryFn: () => get("/drafts?feature=F9&limit=1"),
  });
  const generate = useMutation({
    mutationFn: () => post<any>("/discharge/generate"),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const draft = drafts.data?.drafts?.[0];
  const signed = readiness.data?.already_signed;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Discharge</h1>
          <div className="page-sub">
            The summary is assembled from approved timeline events. Every paragraph carries its evidence. The medication list is built by code, not by the model. Signing locks the encounter.
          </div>
        </div>
        <div className="page-actions">
          {draft?.status === "approved" ? (
            <button className="btn" onClick={() => window.open(`/api/discharge/${draft.id}/print`, "_blank")}>Print summary</button>
          ) : null}
          <button className="btn btn-primary" onClick={() => generate.mutate()} disabled={generate.isPending || !readiness.data?.ready || Boolean(signed)}>
            {generate.isPending ? <><span className="spinner" /> Generating…</> : draft ? "Regenerate summary" : "Generate summary"}
          </button>
        </div>
      </div>

      {signed ? (
        <div className="banner success mb-3">
          Encounter discharged and the summary signed. The record is locked for this demo; reset to walk it again.
        </div>
      ) : null}

      <div className="split-main">
        <div className="flex-col gap-3">
          <div className="card">
            <div className="card-head">
              <div><div className="card-title">Discharge readiness</div><div className="card-sub">Deterministic checklist over approved events</div></div>
              <span className={`badge ${signed ? "badge-success" : readiness.data?.ready ? "badge-success" : "badge-warning"}`}>
                {signed ? "signed" : readiness.data?.ready ? "ready" : "incomplete"}
              </span>
            </div>
            <div className="card-pad">
              <div className="checklist">
                {readiness.data?.items.map((item) => (
                  <div className="check-row" key={item.key}>
                    <span className={`check-mark ${item.present ? "ok" : "bad"}`}>{item.present ? "✓" : "!"}</span>
                    <span style={{ flex: 1 }}>{item.label}</span>
                    <span className="small muted">{item.source}</span>
                  </div>
                ))}
              </div>
              {!readiness.data?.ready ? (
                <div className="banner warning mt-3">
                  Missing sections block generation. Complete the notes and lab review first — the demo refuses to fabricate a discharge summary.
                </div>
              ) : null}
            </div>
          </div>

          <div className="card">
            <div className="card-head"><div className="card-title">What signing does</div></div>
            <div className="card-pad small muted" style={{ lineHeight: 1.7 }}>
              One click writes a discharge summary event, marks the encounter discharged, and records an audit entry with the model, prompt version, and evidence count.
              The medication table comes from current active orders; the model never invents a discharge prescription.
            </div>
          </div>
        </div>

        <div>
          {draft ? (
            <DraftReview draft={draft} />
          ) : (
            <div className="card empty">
              <div className="empty-title">No discharge draft yet.</div>
              <div>Generate one after the timeline is ready. It will cite the consultation, admission, round, labs, procedure and OCR-confirmed values.</div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
