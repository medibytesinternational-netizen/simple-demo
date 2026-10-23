import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, openApiWindow, post } from "../api";
import type { Draft } from "../types";
import { DraftReview } from "../components/DraftReview";
import { ReadinessPanel } from "../features/f09/ReadinessPanel";
import { SignPanel } from "../features/f09/SignPanel";
import type { Readiness } from "../features/f09/types";

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
            <button className="btn" onClick={() => openApiWindow(`/discharge/${draft.id}/print`)}>Print summary</button>
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
              <ReadinessPanel readiness={readiness.data} />
            </div>
          </div>

          <div className="card">
            <div className="card-head"><div className="card-title">What signing does</div></div>
            <div className="card-pad small muted" style={{ lineHeight: 1.7 }}>
              Approving writes a discharge summary event, marks the encounter discharged, escalates tasks that are still open, and records an audit entry with the model, prompt version, and evidence count. Open critical alerts, open tasks or undecided medicine differences need a written reason.
              The medication table comes from current active orders; the model never invents a discharge prescription.
            </div>
          </div>
        </div>

        <div>
          {draft ? (
            <>
              {/* The Approve button here cannot send a reason; SignPanel does. */}
              <style>{`.f09-review .draft-actions { display: none; }`}</style>
              <div className="f09-review"><DraftReview draft={draft} /></div>
              <SignPanel draft={draft} readiness={readiness.data} />
            </>
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
