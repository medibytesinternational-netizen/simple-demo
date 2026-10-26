import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api";
import { useCan } from "../../session";
import { Banner, Field, Panel } from "../../components/ui";
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
    <Panel
      className="sign-panel"
      title="Approve discharge"
      sub="Nothing is written until you approve. Signing locks the encounter and escalates tasks that are still open."
      padded
    >
      <div className="flex-col gap-3">
        {blocked ? (
          <Banner tone="warning" role="status">
            Required documentation is missing. This summary cannot be approved yet.
          </Banner>
        ) : null}
        {needsReason && !blocked ? (
          <Field label="Why discharge with open alerts, open tasks or undecided medicine differences?" htmlFor="discharge-override-reason" required>
            <input
              id="discharge-override-reason"
              className="input"
              value={reason}
              placeholder={`At least ${MIN_REASON} characters`}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
        ) : null}
        {error ? <Banner tone="warning" role="alert">{error}</Banner> : null}
        <div className="button-row">
          <button
            className="btn btn-primary"
            disabled={!canApprove || blocked || approve.isPending || (needsReason && !reasonOk(reason))}
            onClick={() => approve.mutate()}
            aria-busy={approve.isPending || undefined}
          >
            {approve.isPending ? <><span className="spinner" /> Signing…</> : "Approve and discharge"}
          </button>
          <button className="btn btn-danger btn-sm" disabled={!canApprove} onClick={() => setRejecting(!rejecting)} aria-expanded={rejecting}>
            Reject
          </button>
        </div>
        {rejecting ? (
          <div className="form-row">
            <Field label="Why reject this summary?" htmlFor="discharge-reject-reason">
              <input
                id="discharge-reject-reason"
                className="input"
                value={rejectReason}
                placeholder={`At least ${MIN_REASON} characters`}
                onChange={(event) => setRejectReason(event.target.value)}
              />
            </Field>
            <button
              className="btn btn-danger btn-sm"
              disabled={!reasonOk(rejectReason) || reject.isPending}
              onClick={() => reject.mutate()}
              aria-busy={reject.isPending || undefined}
            >
              {reject.isPending ? <span className="spinner" /> : null}
              Reject with reason
            </button>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
