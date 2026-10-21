export const URGENCIES = ["routine", "urgent", "emergency"] as const;
export type Urgency = (typeof URGENCIES)[number];

export type ReferralBody = { specialty?: string; urgency?: Urgency; question?: string };

/** The request body: trimmed, and a blank field is left out so the server can infer or default it. */
export function referralBody(specialty: string, urgency: string, question: string): ReferralBody {
  const body: ReferralBody = {};
  if (specialty.trim()) body.specialty = specialty.trim();
  if ((URGENCIES as readonly string[]).includes(urgency)) body.urgency = urgency as Urgency;
  if (question.trim()) body.question = question.trim();
  return body;
}

/** A referral that is approved but not yet delivered is "queued". */
export function referralStatusLabel(status: string): string {
  return status === "queued" ? "Queued, not yet sent" : status;
}

/** Acknowledge is allowed from queued or sent. */
export function canAcknowledge(status: string): boolean {
  return status === "queued" || status === "sent";
}
