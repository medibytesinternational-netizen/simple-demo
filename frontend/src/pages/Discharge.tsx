import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, openApiWindow, post } from "../api";
import type { Draft } from "../types";
import { DraftReview } from "../components/DraftReview";
import { ReadinessPanel } from "../features/f09/ReadinessPanel";
import { SignPanel } from "../features/f09/SignPanel";
import type { Readiness } from "../features/f09/types";
import { PageHeader } from "../components/PageHeader";
import { Banner, Disclosure, EmptyState, Panel, Pill, Progress, Skeleton, Stepper } from "../components/ui";
import type { StepState } from "../components/ui";

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

  const items = readiness.data?.items ?? [];
  const presentCount = items.filter((item) => item.present).length;
  const steps: { label: string; state: StepState }[] = [
    { label: "Readiness", state: signed || readiness.data?.ready ? "done" : "current" },
    { label: "Summary", state: signed || draft ? "done" : readiness.data?.ready ? "current" : "todo" },
    { label: "Sign", state: signed ? "done" : draft && readiness.data?.ready ? "current" : "todo" },
  ];

  return (
    <div className="page pg-discharge">
      <PageHeader
        title="Discharge"
        description="Check the record is complete, review the discharge summary, then sign. Signing locks the stay. The medicine list is built from active orders, not written by AI."
        meta={<Stepper label="Discharge steps" steps={steps} />}
        actions={<>
          {draft?.status === "approved" ? (
            <button className="btn" onClick={() => openApiWindow(`/discharge/${draft.id}/print`)}>Print summary</button>
          ) : null}
          <button
            className="btn btn-primary"
            onClick={() => generate.mutate()}
            disabled={generate.isPending || !readiness.data?.ready || Boolean(signed)}
            aria-busy={generate.isPending || undefined}
          >
            {generate.isPending ? <><span className="spinner" /> Generating…</> : draft ? "Regenerate summary" : "Generate summary"}
          </button>
        </>}
      />

      {/* Generation can be refused (credits exhausted, encounter locked, backend unreachable): say so. */}
      {generate.isError ? (
        <Banner tone="danger" role="alert">The discharge summary was not generated: {(generate.error as Error).message}</Banner>
      ) : null}

      {signed ? (
        <Banner tone="success" role="status">
          Encounter discharged and the summary signed. The record is locked for this demo; reset to walk it again.
        </Banner>
      ) : null}

      <div className="workspace">
        <div className="dc-left">
          <Panel
            title="Discharge readiness"
            sub="Deterministic checklist over approved events"
            actions={(
              <Pill tone={signed || readiness.data?.ready ? "success" : "warning"} dot>
                {signed ? "signed" : readiness.data?.ready ? "ready" : "incomplete"}
              </Pill>
            )}
            padded
          >
            {readiness.isLoading ? <Skeleton count={5} /> : null}
            {readiness.data ? (
              <div className="flex-col gap-3">
                <Progress
                  value={presentCount}
                  max={items.length}
                  tone={items.length && presentCount === items.length ? "success" : "warning"}
                  label={`${presentCount} of ${items.length} documents present`}
                />
                <ReadinessPanel readiness={readiness.data} />
              </div>
            ) : null}
          </Panel>

          <Disclosure title="What signing does">
            <p>
              Approving writes a discharge summary event, marks the encounter discharged, escalates tasks that are still open, and records an audit entry with the model, prompt version, and evidence count. Open critical alerts, open tasks or undecided medicine differences need a written reason.
            </p>
            <p>The medication table comes from current active orders; the model never invents a discharge prescription.</p>
          </Disclosure>
        </div>

        <div className="dc-right">
          {draft ? (
            <>
              {/* The Approve button here cannot send a reason; SignPanel does. clinical.css hides it inside .f09-review. */}
              <div className="f09-review"><DraftReview draft={draft} /></div>
              <SignPanel draft={draft} readiness={readiness.data} />
            </>
          ) : (
            <Panel>
              <EmptyState icon="discharge" title="No discharge draft yet.">
                Generate one once the readiness checklist is complete. It will cite the consultation, admission, round, labs, procedure and OCR-confirmed values.
              </EmptyState>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
