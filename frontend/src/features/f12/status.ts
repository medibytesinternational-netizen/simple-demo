import type { Tone } from "../../components/ui";

/** Where in the app each missing claim document is resolved. Absent keys have no in-app fix. */
export const RESOLVE_DOCUMENT: Record<string, { to: string; label: string }> = {
  signed_discharge: { to: "/discharge", label: "Go to Discharge" },
  pre_auth: { to: "/documents?tab=followup", label: "Go to Documents" },
  lab_reports: { to: "/documents?tab=inbound", label: "Go to Documents" },
};

/**
 * Claim pack status as shown to billing staff. The API has three states; there is no
 * approved or rejected state because nothing is sent to a payer from this app.
 */
export function claimStatus(status: string | undefined): { label: string; tone: Tone; detail: string } {
  switch (status) {
    case "needs_clarification":
      return { label: "Flagged", tone: "critical", detail: "Needs clarification: contradictions in the record" };
    case "on_hold":
      return { label: "Pending", tone: "warning", detail: "On hold until the blockers below are resolved" };
    case "review_ready":
    case "ready_for_review":
      return { label: "Ready for review", tone: "success", detail: "No blockers; ready for human review" };
    case undefined:
      return { label: "Loading", tone: "neutral", detail: "Checking the claim" };
    default:
      return { label: status.replaceAll("_", " "), tone: "neutral", detail: "" };
  }
}
