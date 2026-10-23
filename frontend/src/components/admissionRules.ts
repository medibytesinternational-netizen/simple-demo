export const ALLERGY_UNAVAILABLE = "The allergy record must be available before admission";
export const ALLERGY_NOT_VERIFIED = "A clinician must verify the allergy record before admission.";

/**
 * The allergy gate for an admission. A record that could not be read can never be verified,
 * so it blocks admission whatever the checkbox says (it may still be ticked from another patient).
 */
export function allergyGateError(allergiesKnown: boolean, verified: boolean): string | null {
  if (!allergiesKnown) return ALLERGY_UNAVAILABLE;
  if (!verified) return ALLERGY_NOT_VERIFIED;
  return null;
}
