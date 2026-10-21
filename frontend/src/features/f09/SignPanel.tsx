import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api";
import { useCan } from "../../session";
import type { Draft, Meta } from "../../types";
import type { Readiness } from "./types";
import { MIN_REASON, reasonOk, warningCount } from "./types";

/** Approve (with a reason when there are open alerts or tasks) or reject a discharge summary draft. */
export function SignPanel({ draft, readiness }: { draft: Draft; readiness: Readiness | undefined }) {
  const queryClient = useQueryClient();
  const canApprove = useCan("approve_draft");
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [error, setError] = useState("");

  const needsReason = warningCount(readiness?.warnings) > 0;
  const blocked = !!readiness && !readiness.ready;

  const approve = useMutation({
    mutationFn: () =>
      post<any>(`/drafts/${draft.id}/approve`, {
        approved_by: meta.data?.user.name || "Dr. Meera Shah",
        ...(needsReason ? { override: { reason: reason.trim() } } : {}),
      }),
    onSuccess: () => {
      setError("");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const reject = useMutation({
    mutationFn: () => post<any>(`/drafts/${draft.id}/reject`, { reason: rejectReason.trim(), actor: meta.data?.user.name }),
    onSuccess: () => {
      setError("");
      setRejecting(false);
      setRejectReason("");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  if (draft.status === "approved" || draft.status === "rejected") return null;

  return (
    <div className="card mt-3">
      <div className="card-head"><div className="card-title">Approve discharge</div></div>
      <div className="card-pad">
        {blocked ? (
          <div className="small" style={{ color: "var(--warning)", fontWeight: 600 }}>
            Required documentation is missing. This summary cannot be approved yet.
          </div>
        ) : null}
        {needsReason && !blocked ? (
          <div className="mt-2">
            <label className="field-label">Why discharge with open alerts, open tasks or undecided medicine differences?</label>
            <input
              className="input"
              value={reason}
              placeholder={`At least ${MIN_REASON} characters`}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
        ) : null}
        {error ? <div className="banner warning mt-2">{error}</div> : null}
        <div className="button-row mt-3">
          <button
            className="btn btn-primary"
            disabled={!canApprove || blocked || approve.isPending || (needsReason && !reasonOk(reason))}
            onClick={() => approve.mutate()}
          >
            {approve.isPending ? <><span className="spinner" /> Signing…</> : "Approve and discharge"}
          </button>
          <button className="btn btn-danger btn-sm" disabled={!canApprove} onClick={() => setRejecting(!rejecting)}>
            Reject
          </button>
        </div>
        {rejecting ? (
          <div className="form-row mt-2" style={{ alignItems: "flex-end" }}>
            <div style={{ flex: 1, minWidth: 260 }}>
              <label className="field-label">Why reject this summary?</label>
              <input
                className="input"
                value={rejectReason}
                placeholder={`At least ${MIN_REASON} characters`}
                onChange={(event) => setRejectReason(event.target.value)}
              />
            </div>
            <button className="btn btn-danger btn-sm" disabled={!reasonOk(rejectReason) || reject.isPending} onClick={() => reject.mutate()}>
              Reject with reason
            </button>
          </div>
        ) : null}
        <div className="small muted mt-2">Nothing is written until you approve. Signing locks the encounter and escalates tasks that are still open.</div>
      </div>
    </div>
  );
}
